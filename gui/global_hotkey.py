"""Win32-only global hotkey listener.

Qt's ApplicationShortcut only fires while a window of THIS process has
focus -- useless for a matchup overlay that needs to toggle while
Magic: The Gathering Arena has focus. This module registers true OS-level
hotkeys via the Win32 ``RegisterHotKey`` API, which fires regardless of
which process owns keyboard focus.

Architecture:

* ``GlobalHotkeyListener(QThread)`` runs a dedicated Win32 message pump
  thread. ``RegisterHotKey`` is thread-affine: only the thread that
  called it receives ``WM_HOTKEY`` messages, so it must own the message
  loop for the lifetime of the registration.
* On ``WM_HOTKEY`` the worker emits ``hotkey_fired(id)``, marshalled to
  the GUI thread by Qt's auto signal connection.
* ``stop()`` posts a ``WM_QUIT`` to break the message loop, then waits.

Non-Windows: ``register_global_hotkeys`` returns ``None`` and the caller
should fall back to its in-app QShortcut wiring. The overlay still works
when the meta-analyzer window has focus; only the cross-process toggle
goes away.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QThread, pyqtSignal


# Win32 constants
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# MOD_NOREPEAT (Win 7+) keeps held-down keys from auto-firing the hotkey
MOD_NOREPEAT = 0x4000


# Virtual-key codes for letter keys (uppercase ASCII)
VK_M = 0x4D
VK_L = 0x4C
VK_Q = 0x51


class GlobalHotkeyListener(QThread):
    """Runs a Win32 message pump and fans hotkey events out as Qt signals.

    Construct with a list of ``(id, modifiers, vk)`` tuples. ``id`` is an
    arbitrary integer you assign; the matching ID comes back via the
    ``hotkey_fired`` signal so the caller can dispatch.
    """

    hotkey_fired = pyqtSignal(int)

    def __init__(self, hotkeys, parent=None):
        super().__init__(parent)
        self._hotkeys = list(hotkeys)
        self._thread_id: int | None = None
        self._stop_requested = False

    def run(self):  # pragma: no cover -- requires Windows + native API
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        registered_ids: list[int] = []
        for hk_id, mods, vk in self._hotkeys:
            ok = user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk)
            if ok:
                registered_ids.append(hk_id)
            # If RegisterHotKey fails (e.g. another process owns the
            # combo) we silently skip -- the user will see "hotkey did
            # nothing" rather than a hard crash, which is the right
            # tradeoff for a non-essential UX feature.

        try:
            msg = wintypes.MSG()
            while not self._stop_requested:
                ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if ret == 0 or ret == -1:
                    break  # WM_QUIT or error
                if msg.message == WM_HOTKEY:
                    try:
                        self.hotkey_fired.emit(int(msg.wParam))
                    except Exception:
                        pass
        finally:
            for hk_id in registered_ids:
                try:
                    user32.UnregisterHotKey(None, hk_id)
                except Exception:
                    pass

    def stop(self) -> None:
        """Break the message pump and wait for the thread to exit."""
        self._stop_requested = True
        tid = self._thread_id
        if tid is not None:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        self.wait(2000)


def register_global_hotkeys(hotkeys):
    """Start a listener on Windows; return None elsewhere.

    Caller is responsible for connecting ``hotkey_fired`` and calling
    ``stop()`` at shutdown.
    """
    if sys.platform != "win32":
        return None
    listener = GlobalHotkeyListener(hotkeys)
    listener.start()
    return listener
