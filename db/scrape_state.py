"""
data/scrape_state.json -- last scrape timestamp/status, global AND per format.

Qt-free so the scheduled pipeline (scripts/run_fill_from_prefs.py) can record
what it did without importing the GUI. `gui/tray_icon.py` re-exports these
for its existing callers.

Shape (2026-09-20, per-format added):

    {
      "last_updated": "...", "last_status": "ok", "last_error": "...",   # global
      "balloon_shown": true,                                             # GUI-owned
      "formats": {
        "modern": {"last_updated": "...", "last_status": "ok"},
        "pioneer": {"last_updated": "...", "last_status": "error", "last_error": "..."}
      }
    }

Why per format: until 2026-09-20 the single global `last_status: ok` sat next
to a `matches` table that had had no Modern rows for ten weeks. A format-
specific stall was invisible. The old, flat shape is still read (and still
written for the global fields) so existing installs keep working.
"""
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(_ROOT, "data", "scrape_state.json")

# The file has writers in TWO processes -- the GUI (gui/tray_icon.py) and the
# scheduled scraper (scripts/run_fill_from_prefs.py) -- so the read-modify-write
# is guarded by a CROSS-PROCESS lock on a sibling `<file>.lock` (fcntl.flock /
# msvcrt.locking; the OS drops it if the holder dies, so it can't go stale).
# A thread lock is kept underneath because msvcrt region locks are per handle
# and two threads of one process would otherwise spin on each other.
# PR #10 review: with only a threading.Lock, a GUI write could replace the file
# with a snapshot taken before the scheduler's per-source failure was recorded;
# on Windows the scheduler's os.replace() could also raise PermissionError while
# the other process had the file open.
_LOCK = threading.Lock()
LOCK_TIMEOUT_S = 15.0


@contextmanager
def _state_lock(target: str, timeout_s: float = LOCK_TIMEOUT_S):
    lock_path = target + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with _LOCK:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"could not lock {lock_path} in {timeout_s}s")
                    time.sleep(0.005)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_unlocked(target: str) -> dict:
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _replace_with_retry(tmp: str, target: str, attempts: int = 50) -> None:
    """os.replace, retried briefly on Windows sharing violations (an antivirus or
    indexer can hold the file open for a moment even when every app writer locks)."""
    for i in range(attempts):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.02)


def read_scrape_state(path=None) -> dict:
    """Whole file as a dict; {} when missing or unreadable. Takes the lock, so a
    reader never holds the file open while a writer is replacing it (Windows)."""
    target = str(path or STATE_PATH)
    try:
        with _state_lock(target):
            return _read_unlocked(target)
    except TimeoutError:
        return _read_unlocked(target)      # never block a GUI paint on a stuck writer


def format_scrape_state(fmt: str, path=None) -> dict:
    """
    Status for one format. Returns the per-format entry plus `scope: "format"`
    when one exists; otherwise the global fields plus `scope: "global"` so the
    caller can tell it is NOT format-specific evidence.
    """
    state = read_scrape_state(path)
    entry = (state.get("formats") or {}).get((fmt or "").lower())
    if isinstance(entry, dict):
        return {**entry, "scope": "format"}
    out = {k: state[k] for k in ("last_updated", "last_status", "last_error") if k in state}
    out["scope"] = "global"
    return out


def write_scrape_state(status="ok", error=None, fmt=None, path=None) -> None:
    """
    Persist a scrape outcome. With `fmt`, writes that format's entry under
    `formats` and leaves the global fields alone; without it, updates the
    global fields (the pre-2026-09-20 behaviour). Other keys (balloon_shown,
    other formats) are preserved.
    """
    now = datetime.now().isoformat(timespec="seconds")

    def fn(state):
        if fmt:
            formats = state.setdefault("formats", {})
            if not isinstance(formats, dict):
                formats = state["formats"] = {}
            entry = formats.setdefault(fmt.lower(), {})
        else:
            entry = state
        entry["last_updated"] = now
        entry["last_status"] = status
        if error:
            entry["last_error"] = str(error)
        else:
            entry.pop("last_error", None)
    _mutate(path, fn)


# --- per-source outcomes + run markers (2026-10-03, issue #8) -----------------
#
#   "formats": {"pioneer": {..., "sources": {"mtgmelee": {
#         "last_attempt": "...", "last_status": "error", "last_success": "...",
#         "last_error": "...", "error_class": "requests.exceptions.ConnectTimeout"}}}}
#   "runs": {"pipeline": {"last_started": "...", "last_finished": "...",
#                         "last_step": "MTGMelee — modern"}}
#
# Written after EACH step, not at the end of the run: the 2026-10-03 06:00 run was
# killed mid-pipeline and, because outcomes were only written at the end, left no
# trace at all.

def _mutate(path, fn) -> None:
    """The ONE read-modify-write path for every writer, under the cross-process lock.
    Serialize first (a JSON error can't truncate the file), write a uniquely named
    sibling temp file, then replace atomically."""
    target = str(path or STATE_PATH)
    with _state_lock(target):
        state = _read_unlocked(target)
        fn(state)
        payload = json.dumps(state, indent=2)
        tmp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            _replace_with_retry(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def write_source_outcome(fmt: str, source: str, status: str, *, error=None,
                         error_class=None, path=None) -> None:
    """Record one source's outcome for one format. `last_success` survives failures,
    so 'failing since <last_success>' is always answerable."""
    now = datetime.now().isoformat(timespec="seconds")

    def fn(state):
        formats = state.setdefault("formats", {})
        if not isinstance(formats, dict):
            formats = state["formats"] = {}
        entry = formats.setdefault(fmt.lower(), {})
        sources = entry.setdefault("sources", {})
        s = sources.setdefault(source, {})
        s["last_attempt"] = now
        s["last_status"] = status
        if status == "ok":
            s["last_success"] = now
            s.pop("last_error", None)
            s.pop("error_class", None)
        else:
            if error:
                s["last_error"] = str(error)[:500]
            s["error_class"] = error_class or "unknown"
    _mutate(path, fn)


def mark_run(event: str, *, step=None, run="pipeline", path=None) -> None:
    """event: 'started' | 'step' | 'finished'. A run whose last_started is newer than
    its last_finished was interrupted (or is still running)."""
    now = datetime.now().isoformat(timespec="seconds")

    def fn(state):
        r = state.setdefault("runs", {}).setdefault(run, {})
        if event == "started":
            r["last_started"] = now
            r.pop("last_step", None)
        elif event == "step":
            r["last_step"] = step
            r["last_step_at"] = now
        elif event == "finished":
            r["last_finished"] = now
        else:
            raise ValueError(f"unknown run event {event!r}")
    _mutate(path, fn)


def run_status(run="pipeline", path=None) -> dict:
    """{'state': 'finished'|'interrupted_or_running'|'never', ...markers}."""
    r = (read_scrape_state(path).get("runs") or {}).get(run) or {}
    started, finished = r.get("last_started"), r.get("last_finished")
    if not started:
        state = "never"
    elif finished and finished >= started:
        state = "finished"
    else:
        state = "interrupted_or_running"
    return {**r, "state": state}
