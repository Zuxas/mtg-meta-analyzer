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
    QVBoxLayout, QHBoxLayout, QFrame, QWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap

from gui.tabs.dashboard         import DashboardTab
from gui.tabs.deck_analyzer     import DeckAnalyzerTab
from gui.tabs.search            import SearchTab
from gui.tabs.charts            import ChartsTab
from gui.tabs.predictions       import PredictionsTab
from gui.tabs.settings          import SettingsTab
from gui.tabs.knowledge_base    import KnowledgeBaseTab
from gui.tabs.ask_claude        import AskClaudeTab
from gui.tabs.set_analysis      import SetAnalysisTab
from gui.tabs.tournament_prep   import TournamentPrepTab
from gui.tabs.heatmap_tab       import HeatmapTab
from gui.tabs.my_decks          import MyDecksTab
from gui.tabs.match_log         import MatchLogTab
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

        # Periodic memory + thread logging — requires psutil; silent if missing
        self._mem_timer = QTimer(self)
        self._mem_timer.timeout.connect(self._log_memory)
        self._mem_timer.start(5 * 60 * 1000)  # every 5 minutes

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # ── Branded header bar ───────────────────────────────────
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet(
            f"background: {theme.PANEL}; border-bottom: 1px solid {theme.BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(10)

        # Logo
        _icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        logo_path = os.path.join(_icon_dir, "icon_32.png")
        if os.path.exists(logo_path):
            logo_lbl = QLabel()
            logo_lbl.setPixmap(
                QPixmap(logo_path).scaled(
                    28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            logo_lbl.setStyleSheet("background: transparent;")
            hl.addWidget(logo_lbl)

        app_title = QLabel("MTG META ANALYZER")
        app_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: 600; "
            f"letter-spacing: 1.5px; background: transparent;"
        )
        hl.addWidget(app_title)

        team_label = QLabel("by Team Resolve")
        team_label.setStyleSheet(
            f"color: {theme.TEXT_OFF}; font-size: 10px; background: transparent;"
        )
        hl.addWidget(team_label)
        hl.addStretch()

        central_layout.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        central_layout.addWidget(self._tabs, 1)

        self._dash      = DashboardTab()
        self._deck      = DeckAnalyzerTab()
        self._search    = SearchTab()
        self._charts    = ChartsTab()
        self._preds     = PredictionsTab()
        self._kb        = KnowledgeBaseTab()
        self._tourney   = TournamentPrepTab()
        self._heatmap   = HeatmapTab()
        self._my_decks  = MyDecksTab()
        self._match_log = MatchLogTab()
        self._claude    = AskClaudeTab()
        self._set_analysis = SetAnalysisTab()
        self._settings  = SettingsTab()

        self._tabs.addTab(self._dash,         "DASHBOARD")
        self._tabs.addTab(self._deck,         "DECK ANALYZER")
        self._tabs.addTab(self._my_decks,     "MY DECKS")
        self._tabs.addTab(self._match_log,    "MATCH LOG")
        self._tabs.addTab(self._search,       "SEARCH")
        self._tabs.addTab(self._tourney,      "TOURNAMENT PREP")
        self._tabs.addTab(self._heatmap,      "MATCHUP DATA")
        self._tabs.addTab(self._kb,           "KNOWLEDGE BASE")
        self._tabs.addTab(self._preds,        "PREDICTIONS")
        self._tabs.addTab(self._charts,       "CHARTS")
        self._tabs.addTab(self._settings,     "SETTINGS")

        # Wire "Open in Event Optimizer" from My Decks → Tournament Prep
        self._my_decks.open_in_rcq.connect(self._on_open_in_rcq)

        # AI tabs — added/removed dynamically based on API key presence
        self._claude_tab_index = -1
        self._set_analysis_tab_index = -1
        self._settings.api_key_changed.connect(self._on_api_key_changed)
        # Show on startup if key already saved
        from gui.tabs.settings import load_preferences
        if load_preferences().get("anthropic_api_key", "").strip():
            self._add_claude_tab()
            self._add_set_analysis_tab()

        self.setCentralWidget(central)

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

    def _add_set_analysis_tab(self):
        if self._set_analysis_tab_index >= 0:
            return
        settings_idx = self._tabs.indexOf(self._settings)
        self._tabs.insertTab(settings_idx, self._set_analysis, "SET ANALYSIS")
        self._set_analysis_tab_index = self._tabs.indexOf(self._set_analysis)

    def _remove_set_analysis_tab(self):
        if self._set_analysis_tab_index < 0:
            return
        self._tabs.removeTab(self._tabs.indexOf(self._set_analysis))
        self._set_analysis_tab_index = -1

    def _on_api_key_changed(self, key: str):
        if key:
            self._add_claude_tab()
            self._add_set_analysis_tab()
        else:
            self._remove_claude_tab()
            self._remove_set_analysis_tab()

    def _on_open_in_rcq(self, deck: dict):
        """Switch to Tournament Prep tab when user clicks 'Open in Event Optimizer'."""
        idx = self._tabs.indexOf(self._tourney)
        if idx >= 0:
            self._tabs.setCurrentIndex(idx)
        # Pre-fill Event Optimizer with the deck's archetype and format
        if hasattr(self._tourney, "load_deck"):
            self._tourney.load_deck(deck)

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
        # Guard: never start a second scrape while one is already running
        if getattr(self, '_scrape_worker', None) is not None and self._scrape_worker.isRunning():
            return
        # Time gate: skip if last successful scrape was <4 hours ago
        from gui.tray_icon import read_scrape_state
        from datetime import datetime
        state = read_scrape_state()
        ts = state.get("last_updated")
        if ts:
            try:
                last = datetime.fromisoformat(ts)
                if (datetime.now() - last).total_seconds() < 4 * 3600:
                    self._status_lbl.setText("Ready (data current)")
                    return
            except Exception:
                pass
        if self._tray:
            from gui.tray_icon import STATUS_RUNNING
            self._tray.set_status(STATUS_RUNNING, "checking for new events")
        self._scrape_worker = QuickScrapeWorker("standard")
        self._scrape_worker.status.connect(self._status_lbl.setText)
        self._scrape_worker.finished.connect(self._on_scrape_done)
        # Clean up the C++ QThread object after the worker finishes
        self._scrape_worker.finished.connect(lambda _n: self._scrape_worker.deleteLater())
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

    def _log_memory(self):
        """Log RSS memory and active thread count every 5 minutes."""
        try:
            import psutil
            import threading
            rss_mb = psutil.Process().memory_info().rss / 1_048_576
            thread_count = threading.active_count()
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
            )
            os.makedirs(log_dir, exist_ok=True)
            from datetime import datetime
            now = datetime.now()
            entry = f"{now.strftime('%Y-%m-%d %H:%M:%S')}  RSS={rss_mb:.1f}MB  threads={thread_count}\n"
            log_path = os.path.join(log_dir, f"memory_{now.strftime('%Y-%m-%d')}.log")
            with open(log_path, "a") as f:
                f.write(entry)
        except Exception:
            pass  # psutil not installed or write failed — skip silently

    def _update_event_count(self):
        count = _count_events("standard")
        self._event_count_lbl.setText(f"Standard: {count:,} events")

    # ------------------------------------------------------------------
    # Tray integration
    # ------------------------------------------------------------------

    def cleanup(self):
        """Stop all running workers. Called by app.aboutToQuit before process exits."""
        self._mem_timer.stop()
        # Stop background scrape worker
        if getattr(self, "_scrape_worker", None) is not None:
            try:
                self._scrape_worker.blockSignals(True)
                self._scrape_worker.quit()
                self._scrape_worker.wait(2000)
            except RuntimeError:
                pass
            self._scrape_worker = None
        # Delegate cleanup to tabs that hold their own workers
        for tab in (self._dash, self._deck, self._heatmap, self._charts, self._claude, self._set_analysis, self._search, self._my_decks, self._match_log):
            if hasattr(tab, "cleanup"):
                try:
                    tab.cleanup()
                except Exception:
                    pass

    def set_tray(self, tray):
        """Called by run_gui.py after the tray icon is created."""
        self._tray = tray
        tray.set_run_now_callback(self._background_scrape)

    def closeEvent(self, event):
        """Minimize to tray instead of quitting — but only for user-initiated close.

        event.spontaneous() is True when the close came from the window system
        (user clicking X, Alt+F4, etc.) and False when generated programmatically
        (e.g. widget deletion cascade, deleteLater on child widgets).
        Only hide-to-tray on spontaneous events to prevent the window from
        disappearing during background operations like heatmap loads.
        """
        if not event.spontaneous():
            # Programmatic close event — accept it normally, do NOT hide to tray
            event.ignore()
            return

        if self._tray and self._tray.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            # Show balloon only on first close-to-tray so it doesn't nag every time
            from gui.tray_icon import read_scrape_state, _STATE_FILE
            import json, os
            state = read_scrape_state()
            if not state.get("balloon_shown"):
                self._tray.showMessage(
                    "MTG Meta Analyzer",
                    "Running in the background. Right-click the tray icon to open or exit.",
                    self._tray.MessageIcon.Information,
                    3000,
                )
                try:
                    state["balloon_shown"] = True
                    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
                    with open(_STATE_FILE, "w") as _f:
                        json.dump(state, _f, indent=2)
                except Exception:
                    pass
        else:
            event.accept()
