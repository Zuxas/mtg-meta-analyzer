"""Single-instance enforcement for the MTG Meta Analyzer GUI.

Wraps Qt's QLockFile to refuse second-launch attempts. The lock file
lives at <project_root>/data/.run_gui.lock by default with a 30-second
stale-lock TTL -- if a previous process died ungracefully, the lock
self-heals after 30s so the user isn't permanently locked out.

QApplication does NOT need to exist before constructing a
SingleInstanceLock -- QLockFile is QtCore, not QtWidgets. However,
the calling code (run_gui.py) DOES need QApplication before showing
the "already running" dialog, so the call order in run_gui.py is:

    app = QApplication(sys.argv)        # FIRST
    lock = SingleInstanceLock()
    if not lock.acquire():
        # show dialog, exit
        ...
    app.aboutToQuit.connect(lock.release)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QLockFile


_DEFAULT_LOCK_NAME = ".run_gui.lock"
_STALE_LOCK_TTL_MS = 30_000  # 30 seconds
_ACQUIRE_TIMEOUT_MS = 100    # don't block startup if lock is held


def _default_lock_path() -> Path:
    """<project_root>/data/.run_gui.lock -- project root resolved
    relative to this file."""
    return (
        Path(__file__).resolve().parent.parent / "data" / _DEFAULT_LOCK_NAME
    )


class SingleInstanceLock:
    """QLockFile wrapper for single-instance enforcement.

    Usage:
        lock = SingleInstanceLock()
        if not lock.acquire():
            # show error dialog, sys.exit(1)
            ...
        # ... app runs ...
        lock.release()  # or wire to QApplication.aboutToQuit
    """

    def __init__(self, lock_path: Optional[Path] = None):
        """lock_path defaults to <project_root>/data/.run_gui.lock.
        Override for tests (use tmp_path)."""
        self._lock_path: Path = Path(lock_path) if lock_path else _default_lock_path()
        self._qlock: Optional[QLockFile] = None
        self._held: bool = False

    def acquire(self) -> bool:
        """Try to acquire the lock with a 100ms wait. Returns True if
        held by this process, False if another process holds it.

        Lazily creates the QLockFile and ensures the parent directory
        exists. Setting the stale-lock TTL means the lock auto-clears
        30s after an ungraceful previous-process exit."""
        # mkdir -p the parent directory (covers fresh-clone case where
        # data/ doesn't exist yet)
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Lazy-create so tests can monkeypatch _lock_path after construction
        if self._qlock is None:
            self._qlock = QLockFile(str(self._lock_path))
            self._qlock.setStaleLockTime(_STALE_LOCK_TTL_MS)

        result = self._qlock.tryLock(_ACQUIRE_TIMEOUT_MS)
        self._held = bool(result)
        return self._held

    def release(self) -> None:
        """Release the lock if held. Safe to call repeatedly."""
        if self._qlock is not None and self._held:
            self._qlock.unlock()
        self._held = False

    def is_held(self) -> bool:
        """Whether this instance currently holds the lock."""
        return self._held
