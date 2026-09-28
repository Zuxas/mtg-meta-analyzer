"""Background QThread that saves MTGO's local match files every few minutes.

MTGO overwrites mtgo.log (exact 75s + board frames) on every launch, so the
file has to be copied while the session is still on disk. File copies only --
no database writes; `python -m scripts.import_mtgo_matches --commit` imports.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal

POLL_INTERVAL_SEC = 600
STARTUP_DELAY_SEC = 30


class MtgoSnapshotWatcher(QThread):
    status_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True
        self.wait(5000)

    def tick(self) -> int:
        from scrapers.mtgo_snapshot import snapshot
        try:
            res = snapshot()
        except Exception as e:  # a locked or missing file must not kill the thread
            self.status_changed.emit(f"MTGO snapshot error: {e}")
            return 0
        if res["copied"]:
            self.status_changed.emit(f"MTGO snapshot: saved {res['copied']} file(s)")
        return res["copied"]

    def _sleep(self, seconds: int) -> bool:
        for _ in range(seconds):
            if self._stop_requested:
                return False
            time.sleep(1)
        return True

    def run(self) -> None:
        # Short delay first: windows built and torn down in tests never copy files.
        if not self._sleep(STARTUP_DELAY_SEC):
            return
        while not self._stop_requested:
            self.tick()
            if not self._sleep(POLL_INTERVAL_SEC):
                return
