"""Win32 foreground-window watcher.

Polls ``GetForegroundWindow`` every ``POLL_INTERVAL_MS`` and emits the
window title via the ``foreground_changed`` signal whenever it changes.
MainWindow uses this to auto-show / auto-hide the matchup overlay when
MTGA is or isn't the active window.

Non-Windows: ``create_watcher`` returns ``None``; callers fall back to
"always available when user toggled it on."
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


POLL_INTERVAL_MS = 500


class ForegroundWatcher(QObject):
    """Polls the foreground window title on the GUI thread."""

    # Fired only when the title CHANGES (debounced on equality).
    foreground_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_title: str = ""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        # Emit initial value so listeners can decide visibility on launch
        self._poll(force_emit=True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def current_title(self) -> str:
        return self._last_title

    def _poll(self, force_emit: bool = False) -> None:
        title = self._get_foreground_title()
        if title != self._last_title or force_emit:
            self._last_title = title
            self.foreground_changed.emit(title)

    @staticmethod
    def _get_foreground_title() -> str:
        if sys.platform != "win32":
            return ""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or ""
        except Exception:
            return ""


def create_watcher(parent=None) -> ForegroundWatcher | None:
    """Construct + start a watcher on Windows, else return None."""
    if sys.platform != "win32":
        return None
    w = ForegroundWatcher(parent)
    w.start()
    return w


def is_mtga_window(title: str) -> bool:
    """Heuristic: does this window title belong to MTG Arena?

    Arena's main window is "MTGA" (uppercase). The Unity launcher window
    can be "MTG Arena" or similar variants. Match common shapes.
    """
    if not title:
        return False
    t = title.strip().lower()
    return (
        t == "mtga"
        or t.startswith("mtga ")
        or "magic: the gathering arena" in t
        or t.startswith("mtg arena")
    )


def is_meta_analyzer_window(title: str) -> bool:
    """Match the MTG Meta Analyzer's own window title.

    Used by the overlay-visibility gate so the overlay stays visible
    while the user is configuring it from inside the app, not just when
    MTGA itself has focus.
    """
    if not title:
        return False
    t = title.strip().lower()
    return "mtg meta analyzer" in t
