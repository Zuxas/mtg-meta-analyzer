"""
Main application window.

Startup flow:
  1. Check DB for event count.
  2. If < MIN_EVENTS (50): show SetupWizard first.
  3. Otherwise: load dashboard directly and run QuickScrapeWorker in background
     to pull any new events since last run.

Theme: dark navy (#0a0e1a) with cyan (#00bcd4) accents — techy/competitive feel.
"""
import os

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QApplication,
)
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import Qt, QTimer

from gui.tabs.dashboard    import DashboardTab
from gui.tabs.deck_analyzer import DeckAnalyzerTab
from gui.tabs.search       import SearchTab
from gui.tabs.charts       import ChartsTab
from gui.tabs.predictions  import PredictionsTab
from gui.worker_threads    import QuickScrapeWorker, _count_events

MIN_EVENTS = 50


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def apply_dark_palette(app: QApplication):
    """Apply the dark-navy + cyan theme."""
    app.setStyle("Fusion")
    pal = QPalette()

    BG    = QColor("#0a0e1a")   # deepest background
    PANEL = QColor("#1a2035")   # content panels
    INPUT = QColor("#101525")   # input fields, table cells
    ALT   = QColor("#141c30")   # alternating table rows
    TEXT  = QColor("#e0e0e0")   # primary text
    DIM   = QColor("#5a6a8a")   # placeholder / secondary text
    ACC   = QColor("#00bcd4")   # cyan accent
    BTN   = QColor("#1a2a3a")   # button background
    WHT   = QColor("#ffffff")

    pal.setColor(QPalette.ColorRole.Window,          BG)
    pal.setColor(QPalette.ColorRole.WindowText,      TEXT)
    pal.setColor(QPalette.ColorRole.Base,            INPUT)
    pal.setColor(QPalette.ColorRole.AlternateBase,   ALT)
    pal.setColor(QPalette.ColorRole.ToolTipBase,     PANEL)
    pal.setColor(QPalette.ColorRole.ToolTipText,     TEXT)
    pal.setColor(QPalette.ColorRole.Text,            TEXT)
    pal.setColor(QPalette.ColorRole.PlaceholderText, DIM)
    pal.setColor(QPalette.ColorRole.Button,          BTN)
    pal.setColor(QPalette.ColorRole.ButtonText,      TEXT)
    pal.setColor(QPalette.ColorRole.BrightText,      WHT)
    pal.setColor(QPalette.ColorRole.Link,            ACC)
    pal.setColor(QPalette.ColorRole.Highlight,       ACC)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0e1a"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text,       QColor("#3a4a5a"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, QColor("#3a4a5a"))

    app.setPalette(pal)

    app.setStyleSheet("""
        /* ── Global ─────────────────────────────────────────── */
        * { font-family: "Segoe UI", "Inter", sans-serif; font-size: 12px; }
        QWidget { background: #0a0e1a; color: #e0e0e0; }

        /* ── Tab bar — navbar style ──────────────────────────── */
        QTabWidget::pane {
            border: none;
            border-top: 1px solid #1e3a4a;
        }
        QTabBar {
            background: #070b14;
            border-bottom: 1px solid #1e3a4a;
        }
        QTabBar::tab {
            background: transparent;
            color: #5a6a8a;
            padding: 10px 22px;
            border: none;
            border-bottom: 2px solid transparent;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 12px;
            letter-spacing: 0.5px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            color: #00bcd4;
            border-bottom: 2px solid #00bcd4;
        }
        QTabBar::tab:hover:!selected {
            color: #a0c8d4;
            border-bottom: 2px solid #1e4a5a;
        }

        /* ── Panels / GroupBox ───────────────────────────────── */
        QGroupBox {
            background: #1a2035;
            border: 1px solid #1e3a4a;
            border-radius: 4px;
            margin-top: 10px;
            padding-top: 10px;
            color: #5a6a8a;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 11px;
            letter-spacing: 0.5px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: #00bcd4;
        }

        /* ── Frames / separators ─────────────────────────────── */
        QFrame[frameShape="4"],  /* HLine */
        QFrame[frameShape="5"]  /* VLine */
        { color: #1e3a4a; }

        /* ── Inputs ──────────────────────────────────────────── */
        QComboBox, QSpinBox, QLineEdit, QPlainTextEdit,
        QTextBrowser, QDateEdit {
            background: #101525;
            color: #e0e0e0;
            border: 1px solid #1e3a4a;
            border-radius: 3px;
            padding: 3px 7px;
            selection-background-color: #00bcd4;
            selection-color: #0a0e1a;
        }
        QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
        QPlainTextEdit:focus, QDateEdit:focus {
            border-color: #00bcd4;
        }
        QComboBox::drop-down { border: none; width: 18px; }
        QComboBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #00bcd4;
            width: 0; height: 0;
        }
        QComboBox QAbstractItemView {
            background: #1a2035;
            color: #e0e0e0;
            border: 1px solid #1e3a4a;
            selection-background-color: #00bcd4;
            selection-color: #0a0e1a;
        }
        QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }

        /* ── Scrollbars ──────────────────────────────────────── */
        QScrollBar:vertical   { background: #0a0e1a; width:  8px; border: none; }
        QScrollBar:horizontal { background: #0a0e1a; height: 8px; border: none; }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #1e3a4a; border-radius: 4px; min-length: 20px;
        }
        QScrollBar::handle:vertical:hover,
        QScrollBar::handle:horizontal:hover { background: #00bcd4; }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: none; }

        /* ── Table ───────────────────────────────────────────── */
        QTableWidget {
            background: #101525;
            gridline-color: #1a2a3a;
            border: 1px solid #1e3a4a;
            alternate-background-color: #141c30;
        }
        QTableWidget::item:selected {
            background: #003a47;
            color: #00bcd4;
        }
        QHeaderView::section {
            background: #0d1020;
            color: #00bcd4;
            border: none;
            border-right: 1px solid #1e3a4a;
            border-bottom: 1px solid #1e3a4a;
            padding: 5px 8px;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 11px;
            letter-spacing: 0.5px;
        }
        QHeaderView::section:hover { background: #141c30; }

        /* ── Progress bars ───────────────────────────────────── */
        QProgressBar {
            border: 1px solid #1e3a4a;
            border-radius: 3px;
            background: #101525;
            color: #00bcd4;
            text-align: center;
            height: 20px;
        }
        QProgressBar::chunk {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #007a8a, stop:1 #00bcd4
            );
            border-radius: 2px;
        }

        /* ── Checkboxes ──────────────────────────────────────── */
        QCheckBox { color: #8a9aaa; spacing: 6px; }
        QCheckBox::indicator {
            width: 14px; height: 14px;
            border: 1px solid #1e4a5a;
            border-radius: 2px;
            background: #101525;
        }
        QCheckBox::indicator:checked {
            background: #00bcd4;
            border-color: #00bcd4;
        }

        /* ── Splitters ───────────────────────────────────────── */
        QSplitter::handle:horizontal { background: #1e3a4a; width: 1px; }
        QSplitter::handle:vertical   { background: #1e3a4a; height: 1px; }

        /* ── Status bar ──────────────────────────────────────── */
        QStatusBar {
            background: #070b14;
            color: #3a5a6a;
            border-top: 1px solid #1e3a4a;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 11px;
        }
        QStatusBar QLabel { color: #3a5a6a; }

        /* ── Tool tips ───────────────────────────────────────── */
        QToolTip {
            background: #1a2035;
            color: #e0e0e0;
            border: 1px solid #00bcd4;
            padding: 4px 8px;
        }

        /* ── Labels ──────────────────────────────────────────── */
        QLabel { color: #8a9aaa; }

        /* ── Toolbar (matplotlib nav) ────────────────────────── */
        QToolBar {
            background: #070b14;
            border: none;
            border-top: 1px solid #1e3a4a;
            spacing: 2px;
            padding: 2px;
        }
        QToolBar QToolButton {
            background: transparent;
            color: #5a6a8a;
            border: 1px solid transparent;
            border-radius: 3px;
            padding: 3px 5px;
        }
        QToolBar QToolButton:hover {
            background: #1a2035;
            border-color: #00bcd4;
            color: #00bcd4;
        }
        QToolBar QToolButton:pressed { background: #003a47; }
    """)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Meta Analyzer")
        self.setMinimumSize(1100, 700)
        self.resize(1300, 820)

        apply_dark_palette(QApplication.instance())
        self._build_ui()
        # Slight delay so the window paints before we check/run setup
        QTimer.singleShot(150, self._startup_check)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)

        self._dash   = DashboardTab()
        self._deck   = DeckAnalyzerTab()
        self._search = SearchTab()
        self._charts = ChartsTab()
        self._preds  = PredictionsTab()

        self._tabs.addTab(self._dash,   "  \u29c6  DASHBOARD  ")
        self._tabs.addTab(self._deck,   "  \u25c8  DECK ANALYZER  ")
        self._tabs.addTab(self._search, "  \u2295  SEARCH  ")
        self._tabs.addTab(self._charts, "  \u2248  CHARTS  ")
        self._tabs.addTab(self._preds,  "  \u25c7  PREDICTIONS  ")

        self.setCentralWidget(self._tabs)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            "color: #3a6a7a; font-family: 'Consolas','Courier New',monospace; font-size: 11px;"
        )
        sb.addWidget(self._status_lbl)

        self._event_count_lbl = QLabel("")
        self._event_count_lbl.setStyleSheet(
            "color: #00bcd4; font-family: 'Consolas','Courier New',monospace; "
            "font-size: 11px; padding-right: 12px;"
        )
        sb.addPermanentWidget(self._event_count_lbl)

    # ------------------------------------------------------------------
    # Startup logic
    # ------------------------------------------------------------------

    def _startup_check(self):
        """Show setup wizard for new installs; do a background scrape otherwise."""
        from db.database import DB_PATH
        count = _count_events("standard")
        needs_setup = not os.path.exists(DB_PATH) or count < MIN_EVENTS
        if needs_setup:
            self._show_setup_wizard()
        else:
            self._on_ready(count)

    def _show_setup_wizard(self):
        from gui.setup_wizard import SetupWizard
        wizard = SetupWizard(self)
        wizard.setup_complete.connect(self._on_setup_done)
        wizard.exec()

    def _on_setup_done(self, event_count):
        self._update_event_count()
        if event_count >= MIN_EVENTS:
            self._on_ready(event_count)
        else:
            n = event_count
            self._status_lbl.setText(
                f"Running with limited data ({n} events). "
                "Run backfill for better results."
            )
            QTimer.singleShot(100, self._dash.refresh)

    def _on_ready(self, event_count=None):
        self._update_event_count()
        self._status_lbl.setText("Loading dashboard\u2026")
        QTimer.singleShot(100, self._dash.refresh)
        # Start background scrape after UI has settled
        QTimer.singleShot(4000, self._background_scrape)

    def _background_scrape(self):
        """Quietly check for new events since last run."""
        self._scrape_worker = QuickScrapeWorker("standard")
        self._scrape_worker.status.connect(self._status_lbl.setText)
        self._scrape_worker.finished.connect(self._on_scrape_done)
        self._scrape_worker.start()

    def _on_scrape_done(self, new_events):
        self._update_event_count()
        if new_events > 0:
            self._status_lbl.setText(
                f"Added {new_events} new event{'s' if new_events != 1 else ''}. "
                "Refreshing\u2026"
            )
            QTimer.singleShot(500, self._dash.refresh)
        else:
            self._status_lbl.setText("Ready")

    def _update_event_count(self):
        count = _count_events("standard")
        self._event_count_lbl.setText(f"Standard: {count:,} events")
