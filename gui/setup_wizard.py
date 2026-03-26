"""
First-time setup wizard.

Shown automatically when the database is missing or has fewer than
MIN_EVENTS tournament events. Guides the user through:
  Step 1 — Download the Scryfall card database (~75 MB)
  Step 2 — Pull historical tournament results via the backfill scraper

Analysis features unlock automatically once MIN_EVENTS events are collected.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QStackedWidget, QWidget, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from gui.worker_threads import ScryfallDownloadWorker, BackfillWorker, _count_events

MIN_EVENTS = 50


def _btn_style(color="#65bcd5", hover="#7acee0"):
    text = "#0a0e14" if color in ("#65bcd5", "#3cb44b") or color.startswith("#6") or color.startswith("#3c") else "white"
    return (
        f"QPushButton {{ background: {color}; color: {text}; border: none; "
        f"padding: 6px 20px; border-radius: 3px; font-weight: bold; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
        f"QPushButton:disabled {{ background: #39465c; color: #5a7080; border: 1px solid #4a5a6e; }}"
    )


class SetupWizard(QDialog):
    """
    Modal setup wizard. Emits setup_complete(event_count) when the user
    finishes or skips. The main window decides what to do with the count.
    """
    setup_complete = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MTG Meta Analyzer — First-Time Setup")
        self.setMinimumSize(640, 420)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._scryfall_worker = None
        self._backfill_worker = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(64)
        header.setStyleSheet(
            "background-color: #39465c; border-bottom: 2px solid #65bcd5;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 0, 24, 0)
        title = QLabel("MTG META ANALYZER")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #65bcd5; letter-spacing: 2px;")
        sub = QLabel("// FIRST-TIME SETUP")
        sub.setStyleSheet(
            "color: #6c8c94; font-size: 11px; letter-spacing: 1px;"
        )
        hl.addWidget(title)
        hl.addSpacing(12)
        hl.addWidget(sub)
        hl.addStretch()
        layout.addWidget(header)

        # Pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_welcome())
        self._stack.addWidget(self._build_scryfall_page())
        self._stack.addWidget(self._build_backfill_page())
        layout.addWidget(self._stack, 1)

        # Bottom button bar
        btn_bar = QFrame()
        btn_bar.setFixedHeight(62)
        btn_bar.setStyleSheet("border-top: 1px solid #3a4a5c;")
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(20, 10, 20, 10)
        bl.setSpacing(10)

        self._btn_skip = QPushButton("Skip Setup")
        self._btn_skip.setStyleSheet(
            "QPushButton { background: transparent; color: #6c8c94; "
            "border: 1px solid #4a5a6e; padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { color: #65bcd5; border-color: #65bcd5; }"
        )
        self._btn_skip.clicked.connect(self._skip)

        self._btn_next = QPushButton("Begin Setup")
        self._btn_next.setStyleSheet(_btn_style())
        self._btn_next.clicked.connect(self._next)

        bl.addWidget(self._btn_skip)
        bl.addStretch()
        bl.addWidget(self._btn_next)
        layout.addWidget(btn_bar)

    def _build_welcome(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 28, 40, 16)
        v.setSpacing(14)

        title = QLabel("Welcome")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        title.setStyleSheet("color: white;")
        v.addWidget(title)

        body = QLabel(
            "This tool analyzes competitive Magic: The Gathering tournament data "
            "to surface meta trends, evaluate decklists, and help you prepare for events.\n\n"
            "To get started we need to do two things:\n\n"
            "  \u2460  Download the Scryfall card database (~75 MB)\n"
            "      Enables card lookups, legality checks, and deck analysis.\n\n"
            "  \u2461  Pull historical tournament results from MTGTop8\n"
            "      Analysis features unlock automatically at 50 events.\n\n"
            "This takes roughly 5\u201310 minutes. You can skip and add data manually later."
        )
        body.setStyleSheet("color: #cccccc; font-size: 13px;")
        body.setWordWrap(True)
        v.addWidget(body)
        v.addStretch()
        return w

    def _build_scryfall_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 28, 40, 16)
        v.setSpacing(12)

        title = QLabel("Step 1 \u2014 Card Database")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: white;")
        v.addWidget(title)

        desc = QLabel(
            "Downloading Scryfall oracle cards database.\n"
            "Enables card lookups, mana curve analysis, and format legality checks."
        )
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._scryfall_status = QLabel("Starting download\u2026")
        self._scryfall_status.setStyleSheet("color: #65bcd5; font-size: 12px;")
        v.addWidget(self._scryfall_status)

        self._scryfall_bar = QProgressBar()
        self._scryfall_bar.setRange(0, 100)
        v.addWidget(self._scryfall_bar)

        self._scryfall_log = QLabel("")
        self._scryfall_log.setStyleSheet("color: #555; font-size: 10px;")
        self._scryfall_log.setWordWrap(True)
        v.addWidget(self._scryfall_log)

        v.addStretch()
        return w

    def _build_backfill_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 28, 40, 16)
        v.setSpacing(12)

        title = QLabel("Step 2 \u2014 Tournament History")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: white;")
        v.addWidget(title)

        desc = QLabel(
            "Pulling Standard tournament results from MTGTop8.\n"
            "Analysis features unlock automatically once 50 events are collected."
        )
        desc.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Big event counter
        self._event_counter = QLabel("0")
        self._event_counter.setFont(QFont("Arial", 48, QFont.Weight.Bold))
        self._event_counter.setStyleSheet("color: #65bcd5;")
        self._event_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._event_counter)

        self._counter_label = QLabel("events collected")
        self._counter_label.setStyleSheet("color: #888; font-size: 12px;")
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._counter_label)

        self._unlock_label = QLabel(f"Analysis unlocks at {MIN_EVENTS} events")
        self._unlock_label.setStyleSheet("color: #666; font-size: 11px;")
        self._unlock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._unlock_label)

        self._backfill_bar = QProgressBar()
        self._backfill_bar.setRange(0, MIN_EVENTS)
        v.addWidget(self._backfill_bar)

        self._backfill_status = QLabel("Starting scraper\u2026")
        self._backfill_status.setStyleSheet("color: #555; font-size: 10px;")
        self._backfill_status.setWordWrap(True)
        v.addWidget(self._backfill_status)

        v.addStretch()
        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _next(self):
        page = self._stack.currentIndex()
        if page == 0:
            self._stack.setCurrentIndex(1)
            self._btn_next.setEnabled(False)
            self._btn_next.setText("Downloading\u2026")
            self._start_scryfall()
        elif page == 2 and self._btn_next.text() == "Open App":
            self._finish()

    def _skip(self):
        if self._backfill_worker:
            self._backfill_worker.stop()
        count = _count_events("standard")
        self.setup_complete.emit(count)
        self.accept()

    def _finish(self):
        if self._backfill_worker:
            self._backfill_worker.stop()
        count = _count_events("standard")
        self.setup_complete.emit(count)
        self.accept()

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def _start_scryfall(self):
        self._scryfall_worker = ScryfallDownloadWorker()
        self._scryfall_worker.progress.connect(self._on_scryfall_progress)
        self._scryfall_worker.finished.connect(self._on_scryfall_done)
        self._scryfall_worker.start()

    def _on_scryfall_progress(self, pct, msg):
        self._scryfall_bar.setValue(pct)
        self._scryfall_status.setText(msg)

    def _on_scryfall_done(self, success, msg):
        if success:
            self._scryfall_bar.setValue(100)
            self._scryfall_status.setText("Card database ready!")
            self._scryfall_log.setText(msg)
            # Auto-advance to backfill page
            self._stack.setCurrentIndex(2)
            self._btn_next.setEnabled(False)
            self._btn_next.setText("Collecting data\u2026")
            self._start_backfill()
        else:
            self._scryfall_status.setText(f"Download failed: {msg}")
            self._scryfall_status.setStyleSheet("color: #e6194b; font-size: 12px;")
            self._btn_next.setEnabled(True)
            self._btn_next.setText("Retry")

    def _start_backfill(self):
        self._backfill_worker = BackfillWorker("standard")
        self._backfill_worker.event_count.connect(self._on_event_count)
        self._backfill_worker.finished.connect(self._on_backfill_done)
        self._backfill_worker.start()

    def _on_event_count(self, count, msg):
        self._event_counter.setText(str(count))
        self._backfill_status.setText(msg)
        self._backfill_bar.setValue(min(count, MIN_EVENTS))
        if count >= MIN_EVENTS and not self._btn_next.isEnabled():
            self._unlock_label.setText("\u2705 Analysis features unlocked!")
            self._unlock_label.setStyleSheet(
                "color: #3cb44b; font-size: 12px; font-weight: bold;"
            )
            self._btn_next.setEnabled(True)
            self._btn_next.setText("Open App")
            self._btn_next.setStyleSheet(_btn_style("#3cb44b", "#4cd45b"))

    def _on_backfill_done(self, final_count):
        self._on_event_count(final_count, "Historical data collection complete.")
        if final_count < MIN_EVENTS:
            self._unlock_label.setText(
                f"Collected {final_count} events \u2014 more data improves accuracy."
            )
            self._unlock_label.setStyleSheet("color: #f58231; font-size: 11px;")
            self._btn_next.setEnabled(True)
            self._btn_next.setText("Open App")

    def closeEvent(self, event):
        if self._scryfall_worker:
            try:
                self._scryfall_worker.blockSignals(True)
            except RuntimeError:
                pass
            self._scryfall_worker.deleteLater()
            self._scryfall_worker = None
        if self._backfill_worker:
            self._backfill_worker.stop()
            try:
                self._backfill_worker.blockSignals(True)
            except RuntimeError:
                pass
            self._backfill_worker.deleteLater()
            self._backfill_worker = None
        super().closeEvent(event)
