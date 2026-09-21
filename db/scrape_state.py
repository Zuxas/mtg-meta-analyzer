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
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(_ROOT, "data", "scrape_state.json")


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
    target = path or STATE_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
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

    with open(target, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
