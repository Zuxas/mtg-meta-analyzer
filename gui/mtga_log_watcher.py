"""Background QThread watching MTGA Player.log for new matches.

Polls the file's mtime every POLL_INTERVAL_SEC seconds; when the file
has changed since the last successful parse, re-runs mtga_log_parser
and emits `matches_imported(count)` if new rows landed.

Lightweight: full re-parse takes ~1-2s for a 200k-line log and dedup
via arena_match_id prevents duplicate inserts. We don't try to do
incremental byte-offset parsing -- simpler and robust against log
rotation.

Lifecycle: created once at MainWindow init, started, runs until app
exit. Use `stop()` to terminate cleanly.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


POLL_INTERVAL_SEC = 30  # check every 30 seconds


class MtgaLogWatcher(QThread):
    """Watches Player.log mtime; emits a signal when new matches land."""

    matches_imported = pyqtSignal(int)  # count of new rows
    status_changed = pyqtSignal(str)    # human-readable status text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._last_mtime: float = 0.0

    def stop(self) -> None:
        self._stop_requested = True
        self.wait(timeout=5000)

    def run(self) -> None:
        from scrapers.mtga_log_parser import (
            PLAYER_LOG, PLAYER_PREV_LOG, parse_log_file, save_matches_to_db,
        )
        log_paths = [Path(PLAYER_LOG), Path(PLAYER_PREV_LOG)]

        # Prime the mtime so we don't fire on the first tick if the log
        # hasn't changed since the last app launch.
        for p in log_paths:
            if p.exists():
                self._last_mtime = max(self._last_mtime, p.stat().st_mtime)

        self.status_changed.emit("MTGA watcher: armed")

        while not self._stop_requested:
            # Sleep in 1s chunks so stop() returns quickly
            for _ in range(POLL_INTERVAL_SEC):
                if self._stop_requested:
                    return
                time.sleep(1)

            # Find newest mtime across both logs
            cur_mtime = 0.0
            for p in log_paths:
                if p.exists():
                    cur_mtime = max(cur_mtime, p.stat().st_mtime)

            if cur_mtime <= self._last_mtime:
                continue  # no change

            # File grew or was rewritten -- re-parse
            self.status_changed.emit("MTGA watcher: parsing new matches...")
            try:
                all_matches = []
                for p in log_paths:
                    if p.exists():
                        try:
                            all_matches.extend(parse_log_file(str(p)))
                        except Exception:
                            pass
                n_new = 0
                if all_matches:
                    n_new = save_matches_to_db(all_matches,
                                                format_name="standard")
                # Also capture latest rank (dedup'd; only inserts on change)
                try:
                    from analysis.rank_tracker import capture_current_rank
                    capture_current_rank(notes="live_tail")
                except Exception:
                    pass
                self._last_mtime = cur_mtime
                if n_new > 0:
                    self.matches_imported.emit(n_new)
                    self.status_changed.emit(
                        f"MTGA watcher: {n_new} new match(es) imported"
                    )
                else:
                    self.status_changed.emit("MTGA watcher: armed")
            except Exception as e:
                self.status_changed.emit(f"MTGA watcher error: {e}")
