"""UIState — persisted GUI state singleton.

Reads and writes `data/preferences.json`. Adds a top-level `ui_state` key
without disturbing existing keys (`formats`, `anthropic_api_key`, etc.).

API:
    UIState.instance() -> singleton
    state.get(path, default=None)  # dotted-path access
    state.set(path, value)         # debounced disk save (250ms)
    state.reset()                  # clear ui_state key only
    state.flush()                  # synchronous save (used by tests + on exit)

Pure Python — no Qt dependency. Debounce via threading.Timer so unit tests
can run without QApplication.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# One lock for EVERY instance (tests build ad-hoc instances; the singleton is
# reset between tests). Two instances writing the same file with per-instance
# locks was the race that produced hybrid files -- see _save_now.
_FILE_LOCK = threading.Lock()
# Live instances, so pending debounced timers can be cancelled process-wide
# (tests/conftest.py does this after every test).
_LIVE: "weakref.WeakSet[UIState]" = weakref.WeakSet()

PREFERENCES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "preferences.json"
)
DEBOUNCE_SECONDS = 0.25


class UIState:
    _instance: "UIState | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._prefs: dict[str, Any] = {}
        self._data: dict[str, Any] = {}
        self._timer: threading.Timer | None = None
        self._save_lock = _FILE_LOCK
        _LIVE.add(self)
        self.load()

    @classmethod
    def cancel_all_pending(cls) -> int:
        """Cancel every scheduled (debounced) save on every live instance.

        Returns the number cancelled. Used by the test suite so a timer
        scheduled while PREFERENCES_PATH was monkeypatched can never fire
        after the patch is undone and write test data into the real
        data/preferences.json -- which is what corrupted it on 2026-09-21
        (and, most likely, how the `formats` key went missing in July).
        """
        n = 0
        for inst in list(_LIVE):
            t = inst._timer
            if t is not None:
                t.cancel()
                inst._timer = None
                n += 1
        return n

    @classmethod
    def instance(cls) -> "UIState":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def load(self) -> None:
        """Read preferences.json. Tolerant of missing file / corrupt JSON."""
        try:
            if PREFERENCES_PATH.exists():
                with PREFERENCES_PATH.open("r", encoding="utf-8") as f:
                    self._prefs = json.load(f)
            else:
                self._prefs = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("preferences.json unreadable (%s); using empty state", e)
            self._prefs = {}
        ui_state = self._prefs.get("ui_state")
        if isinstance(ui_state, dict):
            self._data = ui_state
        else:
            if ui_state is not None:
                logger.warning("ui_state key was not a dict; resetting to empty")
            self._data = {}

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, path: str, value: Any) -> None:
        keys = path.split(".")
        node = self._data
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value
        self._schedule_save()

    def reset(self) -> None:
        self._data = {}
        self._schedule_save()

    def flush(self) -> None:
        """Cancel pending debounce and save synchronously."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._save_now()

    def _schedule_save(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(DEBOUNCE_SECONDS, self._save_now)
        self._timer.daemon = True
        self._timer.start()

    def _save_now(self) -> None:
        with self._save_lock:
            try:
                PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
                # UIState owns ONLY the `ui_state` key. Everything else
                # (formats, api_key, date_window, ...) belongs to the other
                # writers (setup_wizard / settings / ask_claude), so the file
                # on disk is the source of truth for those keys. Until
                # 2026-09-20 this merged the LAUNCH-TIME snapshot over the
                # disk file, which reverted a freshly saved Settings format
                # selection on the next debounced UI-state save.
                disk = None
                try:
                    if PREFERENCES_PATH.exists():
                        with PREFERENCES_PATH.open("r", encoding="utf-8") as f:
                            disk = json.load(f)
                except (json.JSONDecodeError, OSError):
                    disk = None
                if isinstance(disk, dict):
                    merged = disk
                else:
                    # Unreadable / missing / not an object: fall back to the
                    # last known-good non-ui keys rather than writing a
                    # ui_state-only file that drops formats + api key.
                    merged = {k: v for k, v in self._prefs.items() if k != "ui_state"}
                merged["ui_state"] = self._data
                self._prefs = merged
                # Serialize FIRST so a JSON error can't leave a partial file,
                # then write a sibling temp file and os.replace() it in: the
                # file on disk is always one complete payload. The earlier
                # "leftover tail bytes" seen on this machine were NOT a
                # tmp+replace problem -- they were concurrent writers with
                # per-instance locks truncating and writing over each other
                # (a shorter payload landing on top of a longer one). The
                # process-wide _FILE_LOCK removes the race; replace() makes
                # even a stray writer unable to produce a hybrid file.
                payload = json.dumps(merged, indent=2)
                tmp = PREFERENCES_PATH.with_name(PREFERENCES_PATH.name + ".tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        pass
                os.replace(tmp, PREFERENCES_PATH)
            except OSError as e:
                logger.error("Failed to save preferences.json: %s", e)
