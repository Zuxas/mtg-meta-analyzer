"""
Main application window.

Startup flow:
  1. Check DB for event count.
  2. If < MIN_EVENTS (50): show SetupWizard first.
  3. Otherwise: load dashboard directly and run QuickScrapeWorker in background
     to pull any new events since last run.

Dark Fusion palette matches the chart colour scheme (#1a1a2e background,
#4363d8 accent).
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
    app.setStyle("Fusion")
    pal = QPalette()

    BG   = QColor("#1a1a2e")
    MID  = QColor("#16213e")
    HIGH = QColor("#1e2040")
    TEXT = QColor("#e0e0e0")
    DIM  = QColor("#888888")
    ACC  = QColor("#4363d8")
    BTN  = QColor("#2a2a4e")
    WHT  = QColor("#ffffff")

    pal.setColor(QPalette.ColorRole.Window,          BG)
    pal.setColor(QPalette.ColorRole.WindowText,      TEXT)
    pal.setColor(QPalette.ColorRole.Base,            MID)
    pal.setColor(QPalette.ColorRole.AlternateBase,   HIGH)
    pal.setColor(QPalette.ColorRole.ToolTipBase,     MID)
    pal.setColor(QPalette.ColorRole.ToolTipText,     TEXT)
    pal.setColor(QPalette.ColorRole.Text,            TEXT)
    pal.setColor(QPalette.ColorRole.PlaceholderText, DIM)
    pal.setColor(QPalette.ColorRole.Button,          BTN)
    pal.setColor(QPalette.ColorRole.ButtonText,      TEXT)
    pal.setColor(QPalette.ColorRole.BrightText,      WHT)
    pal.setColor(QPalette.ColorRole.Link,            ACC)
    pal.setColor(QPalette.ColorRole.Highlight,       ACC)
    pal.setColor(QPalette.ColorRole.HighlightedText, WHT)
    # Disabled state
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text, QColor("#555555"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, QColor("#555555"))

    app.setPalette(pal)

    # Extra stylesheet for controls that Qt palette doesn't fully reach
    app.setStyleSheet("""
        QTabWidget::pane { border: 1px solid #2a2a4e; }
        QTabBar::tab {
            background: #1e2040; color: #aaaaaa;
            padding: 6px 16px; border-radius: 3px 3px 0 0;
            margin-right: 2px;
        }
        QTabBar::tab:selected { background: #2a2a4e; color: white; }
        QTabBar::tab:hover    { background: #252550; color: white; }
        QGroupBox {
            border: 1px solid #2a2a4e; border-radius: 4px;
            margin-top: 8px; padding-top: 8px;
            color: #aaaaaa;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        QComboBox, QSpinBox, QLineEdit, QPlainTextEdit, QTextBrowser, QDateEdit {
            background: #16213e; color: #e0e0e0;
            border: 1px solid #2a2a4e; border-radius: 3px; padding: 3px 6px;
        }
        QComboBox::drop-down { border: none; }
        QComboBox QAbstractItemView { background: #16213e; color: #e0e0e0;
                                      selection-background-color: #4363d8; }
        QScrollBar:vertical   { background: #16213e; width:  10px; }
        QScrollBar:horizontal { background: #16213e; height: 10px; }
        QScrollBar::handle    { background: #2a2a4e; border-radius: 4px; }
        QScrollBar::handle:hover { background: #4363d8; }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
        QHeaderView::section {
            background: #1e2040; color: #aaaaaa;
            border: none; border-right: 1px solid #2a2a4e;
            padding: 4px 6px;
        }
        QTableWidget { gridline-color: #2a2a4e; }
        QProgressBar {
            border: 1px solid #2a2a4e; border-radius: 3px;
            background: #16213e; color: white; text-align: center;
        }
        QProgressBar::chunk { background: #4363d8; border-radius: 2px; }
        QCheckBox { color: #aaaaaa; }
        QCheckBox::indicator { border: 1px solid #4a4a6e;
                               background: #16213e; width: 13px; height: 13px; }
        QCheckBox::indicator:checked { background: #4363d8; }
        QStatusBar { background: #0d0d1e; color: #888888; }
        QSplitter::handle { background: #2a2a4e; }
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

        self._tabs.addTab(self._dash,   "  Dashboard  ")
        self._tabs.addTab(self._deck,   "  Deck Analyzer  ")
        self._tabs.addTab(self._search, "  Search  ")
        self._tabs.addTab(self._charts, "  Charts  ")
        self._tabs.addTab(self._preds,  "  Predictions  ")

        self.setCentralWidget(self._tabs)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color: #888888;")
        sb.addWidget(self._status_lbl)

        self._event_count_lbl = QLabel("")
        self._event_count_lbl.setStyleSheet("color: #555555; padding-right: 8px;")
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
