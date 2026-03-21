"""
QThread workers for background I/O — keeps the GUI responsive.
"""
import os
import sys
import time
import sqlite3
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _count_events(format_name="standard"):
    """Count events in the active DB for the given format. Returns 0 on any error."""
    try:
        from db.database import DB_PATH
        if not os.path.exists(DB_PATH):
            return 0
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE LOWER(format)=?",
                (format_name.lower(),)
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


class ScryfallDownloadWorker(QThread):
    """Downloads the Scryfall bulk card database (~75 MB)."""
    progress = pyqtSignal(int, str)    # (percent 0-100, message)
    finished = pyqtSignal(bool, str)   # (success, message)

    def run(self):
        self.progress.emit(5, "Connecting to Scryfall API...")
        try:
            cmd = [sys.executable, "-m", "scrapers.scryfall", "--download"]
            proc = subprocess.Popen(
                cmd,
                cwd=_project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            percent = 5
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if "Downloading" in line or "Fetching" in line:
                    percent = max(percent, 10)
                    self.progress.emit(percent, line)
                elif "MB" in line or "kB" in line:
                    import re
                    m = re.search(r'(\d+)%', line)
                    if m:
                        pct = int(m.group(1))
                        self.progress.emit(10 + int(pct * 0.7), line)
                    else:
                        percent = min(percent + 3, 78)
                        self.progress.emit(percent, line)
                elif "Saved" in line or "saved" in line or "written" in line.lower():
                    self.progress.emit(85, line)
                elif "Building" in line or "Loading" in line:
                    self.progress.emit(92, line)
                else:
                    percent = min(percent + 1, 95)
                    self.progress.emit(percent, line)

            proc.wait()
            if proc.returncode == 0:
                self.progress.emit(100, "Scryfall database ready.")
                self.finished.emit(True, "Card database downloaded successfully.")
            else:
                self.finished.emit(False, f"Download failed (exit code {proc.returncode}).")
        except Exception as e:
            self.finished.emit(False, f"Error: {e}")


class BackfillWorker(QThread):
    """Runs the historical backfill scraper and reports live event counts."""
    event_count = pyqtSignal(int, str)  # (count, status_line)
    finished    = pyqtSignal(int)       # final event count

    def __init__(self, format_name="standard", parent=None):
        super().__init__(parent)
        self._format = format_name
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        cmd = [sys.executable, "-m", "scrapers.backfill", "--format", self._format]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=_project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.event_count.emit(0, f"Failed to start backfill: {e}")
            self.finished.emit(0)
            return

        last_count = _count_events(self._format)
        last_emit  = time.time()

        for line in proc.stdout:
            if self._stop:
                proc.terminate()
                break
            line = line.strip()
            if not line:
                continue
            # Throttle DB polls to once per 2 s
            now = time.time()
            if now - last_emit >= 2.0:
                count = _count_events(self._format)
                if count != last_count:
                    last_count = count
                    self.event_count.emit(count, line[:90])
                last_emit = now
            elif "Saved" in line or "event" in line.lower():
                count = _count_events(self._format)
                if count != last_count:
                    last_count = count
                    self.event_count.emit(count, line[:90])
                    last_emit = now

        proc.wait()
        final = _count_events(self._format)
        self.finished.emit(final)


class QuickScrapeWorker(QThread):
    """Runs the daily scraper to fetch latest events (used at app startup)."""
    status   = pyqtSignal(str)
    finished = pyqtSignal(int)   # number of new events added

    def __init__(self, format_name="standard", parent=None):
        super().__init__(parent)
        self._format = format_name

    def run(self):
        self.status.emit("Checking for new events...")
        try:
            before = _count_events(self._format)
            cmd = [sys.executable, "main.py", "--format", self._format]
            subprocess.run(
                cmd, cwd=_project_root,
                capture_output=True, text=True, timeout=120
            )
            after = _count_events(self._format)
            new   = max(0, after - before)
            self.status.emit(f"Added {new} new events." if new else "Database up to date.")
            self.finished.emit(new)
        except subprocess.TimeoutExpired:
            self.status.emit("Scrape timed out.")
            self.finished.emit(0)
        except Exception as e:
            self.status.emit(f"Scrape error: {e}")
            self.finished.emit(0)


class DataLoadWorker(QThread):
    """Runs any callable in a background thread and emits the result."""
    result = pyqtSignal(object)
    error  = pyqtSignal(str)

    def __init__(self, fn, kwargs=None, parent=None):
        super().__init__(parent)
        self._fn     = fn
        self._kwargs = kwargs or {}

    def run(self):
        try:
            data = self._fn(**self._kwargs)
            self.result.emit(data)
        except Exception as e:
            self.error.emit(str(e))
