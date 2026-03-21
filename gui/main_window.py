"""
Main application window.

Startup flow:
  1. Check DB for event count.
  2. If < MIN_EVENTS (50): show SetupWizard first.
  3. Otherwise: load dashboard directly and run QuickScrapeWorker in background
     to pull any new events since last run.

Theme: personal website design system — see gui/theme.py
"""
import os

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QApplication,
)
from PyQt6.QtCore import Qt, QTimer

from gui.tabs.dashboard         import DashboardTab
from gui.tabs.deck_analyzer     import DeckAnalyzerTab
from gui.tabs.search            import SearchTab
from gui.tabs.charts            import ChartsTab
from gui.tabs.predictions       import PredictionsTab
from gui.tabs.settings          import SettingsTab
from gui.tabs.knowledge_base    import KnowledgeBaseTab
from gui.tabs.ask_claude        import AskClaudeTab
from gui.tabs.tournament_prep   import TournamentPrepTab
from gui.worker_threads    import QuickScrapeWorker, _count_events
import gui.theme as theme

MIN_EVENTS = 50


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MTG Meta Analyzer")
        self.setMinimumSize(900, 600)
        self.resize(1200, 700)

        self._tray = None   # set later by run_gui.py via set_tray()

        theme.apply_theme(QApplication.instance())
        self._build_ui()
        # Slight delay so the window paints before we check/run setup
        QTimer.singleShot(150, self._startup_check)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)

        self._dash      = DashboardTab()
        self._deck      = DeckAnalyzerTab()
        self._search    = SearchTab()
        self._charts    = ChartsTab()
        self._preds     = PredictionsTab()
        self._kb        = KnowledgeBaseTab()
        self._tourney   = TournamentPrepTab()
        self._claude    = AskClaudeTab()
        self._settings  = SettingsTab()

        self._tabs.addTab(self._dash,     "DASHBOARD")
        self._tabs.addTab(self._deck,     "DECK ANALYZER")
        self._tabs.addTab(self._search,   "SEARCH")
        self._tabs.addTab(self._charts,   "CHARTS")
        self._tabs.addTab(self._preds,    "PREDICTIONS")
        self._tabs.addTab(self._kb,       "KNOWLEDGE BASE")
        self._tabs.addTab(self._tourney,  "TOURNAMENT PREP")
        self._tabs.addTab(self._settings, "SETTINGS")

        # Ask Claude tab — added/removed dynamically based on API key presence
        self._claude_tab_index = -1
        self._settings.api_key_changed.connect(self._on_api_key_changed)
        # Show on startup if key already saved
        from gui.tabs.settings import load_preferences
        if load_preferences().get("anthropic_api_key", "").strip():
            self._add_claude_tab()

        self.setCentralWidget(self._tabs)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_lbl = QLabel("Ready")
        sb.addWidget(self._status_lbl)

        self._event_count_lbl = QLabel("")
        self._event_count_lbl.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 11px; padding-right: 12px;"
        )
        sb.addPermanentWidget(self._event_count_lbl)

    # ------------------------------------------------------------------
    # Ask Claude tab (optional — shown only when API key is configured)
    # ------------------------------------------------------------------

    def _add_claude_tab(self):
        if self._claude_tab_index >= 0:
            return  # already added
        # Insert before Settings (last tab)
        settings_idx = self._tabs.indexOf(self._settings)
        self._tabs.insertTab(settings_idx, self._claude, "ASK CLAUDE")
        self._claude_tab_index = self._tabs.indexOf(self._claude)

    def _remove_claude_tab(self):
        if self._claude_tab_index < 0:
            return
        self._tabs.removeTab(self._tabs.indexOf(self._claude))
        self._claude_tab_index = -1

    def _on_api_key_changed(self, key: str):
        if key:
            self._add_claude_tab()
        else:
            self._remove_claude_tab()

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
        if self._tray:
            from gui.tray_icon import STATUS_RUNNING
            self._tray.set_status(STATUS_RUNNING, "checking for new events")
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
        if self._tray:
            from gui.tray_icon import STATUS_IDLE, write_scrape_state
            write_scrape_state(status="ok")
            self._tray.set_status(STATUS_IDLE)

    def _update_event_count(self):
        count = _count_events("standard")
        self._event_count_lbl.setText(f"Standard: {count:,} events")

    # ------------------------------------------------------------------
    # Tray integration
    # ------------------------------------------------------------------

    def set_tray(self, tray):
        """Called by run_gui.py after the tray icon is created."""
        self._tray = tray
        tray.set_run_now_callback(self._background_scrape)

    def closeEvent(self, event):
        """Minimize to tray instead of quitting when window is closed."""
        if self._tray and self._tray.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "MTG Meta Analyzer",
                "Running in the background. Right-click the tray icon to open or exit.",
                self._tray.MessageIcon.Information,
                3000,
            )
        else:
            event.accept()
