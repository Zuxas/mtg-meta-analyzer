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
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(_ROOT, "data", "scrape_state.json")

# One lock for the read-modify-write: the scheduled driver writes one entry
# per format in quick succession while the GUI may write the global fields.
# Same shape of bug as gui/state.py had (racing writers -> hybrid file).
_LOCK = threading.Lock()


def read_scrape_state(path=None) -> dict:
    """Whole file as a dict; {} when missing or unreadable."""
    try:
        with open(path or STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


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
    target = str(path or STATE_PATH)
    with _LOCK:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        state = read_scrape_state(target)

        if fmt:
            formats = state.setdefault("formats", {})
            if not isinstance(formats, dict):
                formats = state["formats"] = {}
            entry = formats.setdefault(fmt.lower(), {})
        else:
            entry = state

        entry["last_updated"] = datetime.now().isoformat(timespec="seconds")
        entry["last_status"] = status
        if error:
            entry["last_error"] = str(error)
        else:
            entry.pop("last_error", None)

        # Serialize FIRST (a JSON error can't truncate the file), write a
        # sibling temp file, then replace atomically: the file on disk is
        # always one complete payload even with another process writing.
        payload = json.dumps(state, indent=2)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, target)


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
    target = str(path or STATE_PATH)
    with _LOCK:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        state = read_scrape_state(target)
        fn(state)
        payload = json.dumps(state, indent=2)
        tmp = f"{target}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, target)


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
