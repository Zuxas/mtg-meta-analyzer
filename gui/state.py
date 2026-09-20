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
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
        self._save_lock = threading.Lock()
        self.load()

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
                disk = merged
                # Write+replace pattern. Critical: serialize FIRST so a
                # JSON error doesn't leave the file truncated. THEN open
                # the real file with "w" which truncates atomically.
                payload = json.dumps(disk, indent=2)
                import os as _os
                # Truncate-and-write directly. Past tmp+replace was
                # leaving leftover tail bytes on this system, so use a
                # plain "w" open with explicit truncate + fsync to make
                # the writer-side fully deterministic.
                with PREFERENCES_PATH.open("w", encoding="utf-8") as f:
                    f.truncate(0)
                    f.write(payload)
                    f.flush()
                    try:
                        _os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        pass
            except OSError as e:
                logger.error("Failed to save preferences.json: %s", e)
