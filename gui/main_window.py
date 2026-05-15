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
    QVBoxLayout, QHBoxLayout, QFrame, QWidget, QPushButton,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut

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
from gui.tabs.ladder_meta       import LadderMetaTab
from gui.tabs.my_decks          import MyDecksTab
from gui.tabs.match_log         import MatchLogTab
from gui.tabs.simulate          import SimulateTab
from gui.tabs.calibration       import CalibrationTab
from gui.worker_threads    import QuickScrapeWorker, _count_events
from gui.state import UIState
from gui.state_keys import LAST_ACTIVE_TAB_PATH, GLOBAL_FORMAT, PALETTE_RECENTS
from gui.widgets.palette_registry import PaletteRegistry
from gui.widgets.command_palette import CommandPalette
from gui.widgets._palette_actions import (
    register_all as _palette_register_all,
    register_card_entries as _palette_register_card_entries,
)
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

        # Persisted UI state singleton — used by tabs for filter persistence
        self.ui_state = UIState.instance()

        # Command palette — populated after _build_ui()
        self._palette_registry = PaletteRegistry()

        self._build_ui()

        # Populate palette registry — fast categories synchronously (tabs
        # must exist by now). Card entries (~32k rows, ~120ms DB walk) are
        # deferred to after first paint so the window is responsive
        # immediately. CARD entries are gated behind the `c:` prefix, so
        # not having them for the first ~120ms is invisible to the user.
        _palette_register_all(self._palette_registry, self)
        QTimer.singleShot(
            0, lambda: _palette_register_card_entries(self._palette_registry)
        )

        # Auto-sync MTGA Player.log on launch (deferred via QTimer so it
        # doesn't block the first paint). Imports any games played since
        # the last parse, dedup'd by arena_match_id.
        QTimer.singleShot(500, self._auto_sync_mtga_on_launch)

        # Live tail Player.log -- background QThread polls mtime every
        # 30s; on change, re-runs the parser. New rows fire
        # `matches_imported` signal -> active tab refreshes.
        from gui.mtga_log_watcher import MtgaLogWatcher
        self._mtga_watcher = MtgaLogWatcher(self)
        self._mtga_watcher.matches_imported.connect(self._on_live_matches_imported)
        self._mtga_watcher.status_changed.connect(self._on_watcher_status)
        self._mtga_watcher.start()

        # Ctrl+K opens palette
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self._open_palette)

        # Restore last active tab path, if any
        last_path = self.ui_state.get(LAST_ACTIVE_TAB_PATH)
        if last_path:
            self.activate_tab_by_path(last_path)

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

        # Refresh button (F5 shortcut) — re-queries DB for the active tab
        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.setToolTip(
            "Reload the current tab from the database (F5).\n"
            "Use after editing data outside the GUI (CLI, manual DB writes, etc.)"
        )
        self._refresh_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.clicked.connect(self._refresh_current_tab)
        hl.addWidget(self._refresh_btn)

        # F5 keyboard shortcut
        self._refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self._refresh_shortcut.activated.connect(self._refresh_current_tab)

        central_layout.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        central_layout.addWidget(self._tabs, 1)

        # ── Cross-tab callbacks (defined early so downstream tabs can take them) ─
        # 'Send deck to SIMULATE' — invoked by any tab that has a current
        # decklist (Deck Analyzer paste, Deck Search result, Dashboard avg deck).
        # Late binding: self._simulate / self._tabs / self._meta_tab are looked
        # up on the instance at call time, so they can be constructed below.
        def _send_to_simulate(deck_text: str, source_label: str,
                              format_hint: str = None):
            self._simulate.set_deck_paste(deck_text, source_label,
                                           format_hint=format_hint)
            self._tabs.setCurrentWidget(self._meta_tab)
            self._meta_tab.setCurrentWidget(self._simulate)

        # 'Jump to SIMULATE matchup' — invoked by CalibrationTab double-click
        # and Match Log context menu.
        def _jump_to_simulate_matchup(a_label: str, b_label: str,
                                       format_hint: str = None):
            self._simulate.set_matchup(a_label, b_label,
                                        format_hint=format_hint)
            self._tabs.setCurrentWidget(self._meta_tab)
            self._meta_tab.setCurrentWidget(self._simulate)

        # ── Create all tab widgets ────────────────────────────────
        self._dash      = DashboardTab(on_simulate=_send_to_simulate)
        self._deck      = DeckAnalyzerTab(on_simulate=_send_to_simulate)
        self._search    = SearchTab(on_simulate=_send_to_simulate)
        self._charts    = ChartsTab()
        self._preds     = PredictionsTab()
        self._kb        = KnowledgeBaseTab()
        self._tourney   = TournamentPrepTab()
        self._heatmap   = HeatmapTab()
        self._ladder    = LadderMetaTab()
        self._simulate  = SimulateTab()
        self._calibration = CalibrationTab(on_cell_activate=_jump_to_simulate_matchup)
        self._my_decks  = MyDecksTab()
        self._match_log = MatchLogTab(on_simulate_matchup=_jump_to_simulate_matchup)
        self._claude    = AskClaudeTab()
        self._set_analysis = SetAnalysisTab()
        self._settings  = SettingsTab()

        # ── Compose merged tabs ───────────────────────────────────
        # META = Charts + Matchup Data + Predictions + Sim + Cal + Ladder
        self._meta_tab = QTabWidget()
        self._meta_tab.addTab(self._charts,  "CHARTS")
        self._meta_tab.addTab(self._heatmap, "MATCHUP DATA")
        self._meta_tab.addTab(self._preds,   "PREDICTIONS")
        self._meta_tab.addTab(self._simulate, "SIMULATE")
        self._meta_tab.addTab(self._calibration, "CALIBRATION")
        self._meta_tab.addTab(self._ladder,  "LADDER")

        # DECKS = Deck Analyzer + My Decks
        self._decks_tab = QTabWidget()
        self._decks_tab.addTab(self._deck,     "ANALYZE")
        self._decks_tab.addTab(self._my_decks, "MY DECKS")

        # TOURNAMENT = Event Optimizer + Breaker Math (already sub-tabbed) + Match Log
        self._tournament_tab = QTabWidget()
        self._tournament_tab.addTab(self._tourney,   "EVENT OPTIMIZER")
        self._tournament_tab.addTab(self._match_log, "MATCH LOG")

        # RESOURCES = Knowledge Base (+ AI tabs added dynamically)
        self._resources_tab = QTabWidget()
        self._resources_tab.addTab(self._kb, "GUIDES & BOOKMARKS")

        # ── Add top-level tabs ────────────────────────────────────
        _tab_info = [
            (self._dash,          "DASHBOARD",  "Current meta standings, win rates, and trending archetypes"),
            (self._meta_tab,      "META",       "Charts, matchup heatmap, and meta predictions"),
            (self._decks_tab,     "DECKS",      "Analyze decklists and manage your saved decks + sideboard plans"),
            (self._search,        "SEARCH",     "Browse cards, search decklists, and compare head-to-head matchups"),
            (self._tournament_tab,"TOURNAMENT", "Event prep, top-cut math, breaker calculator, and match logging"),
            (self._resources_tab, "RESOURCES",  "Sideboard guides, bookmarks, and AI-powered analysis"),
            (self._settings,      "SETTINGS",   "Format preferences, data management, API keys, and ML models"),
        ]
        for i, (widget, label, tip) in enumerate(_tab_info):
            self._tabs.addTab(widget, label)
            self._tabs.setTabToolTip(i, tip)

        # Wire "Open in Event Optimizer" from My Decks → Tournament tab
        self._my_decks.open_in_rcq.connect(self._on_open_in_rcq)

        # AI tabs — added/removed dynamically within RESOURCES based on API key
        self._claude_added = False
        self._set_analysis_added = False
        self._settings.api_key_changed.connect(self._on_api_key_changed)
        from gui.tabs.settings import load_preferences
        if load_preferences().get("anthropic_api_key", "").strip():
            self._add_claude_tab()
            self._add_set_analysis_tab()

        # Persist tab navigation at every depth — top-level clicks AND
        # sub-tab clicks (META/CHARTS, DECKS/MY DECKS, etc.) — to UIState.
        # The palette's activate_tab_by_path() also writes this; all paths
        # converge on UIState.set(LAST_ACTIVE_TAB_PATH, full_leaf_path).
        self._tabs.currentChanged.connect(self._on_active_tab_changed)
        for nested in (self._meta_tab, self._decks_tab,
                       self._tournament_tab, self._resources_tab):
            nested.currentChanged.connect(self._on_active_tab_changed)

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
    # Refresh / Reload
    # ------------------------------------------------------------------

    def _refresh_current_tab(self):
        """Reload the currently visible tab from the database.

        Walks down through any QTabWidget containers to find the actual
        leaf tab, then calls its reload() method if it exists. Falls back
        to known per-tab load method names. No-op (with a status hint) if
        the leaf tab doesn't expose a refresh hook.
        """
        widget = self._tabs.currentWidget()
        # Descend through nested QTabWidget containers (META / DECKS / TOURNAMENT / RESOURCES)
        for _ in range(3):  # bound recursion
            if isinstance(widget, QTabWidget):
                widget = widget.currentWidget()
            else:
                break

        name = type(widget).__name__ if widget else "(none)"

        # Try common reload hooks in priority order
        for method_name in ("reload", "refresh", "_load_decks",
                            "_load_combined", "_load_dashboard"):
            method = getattr(widget, method_name, None)
            if callable(method):
                try:
                    method()
                    self._status_lbl.setText(f"Refreshed {name} via {method_name}()")
                    return
                except Exception as exc:
                    self._status_lbl.setText(f"Refresh {name} failed: {exc}")
                    return
        self._status_lbl.setText(f"{name} has no refresh hook")

    # ------------------------------------------------------------------
    # Palette helpers
    # ------------------------------------------------------------------

    def _on_live_matches_imported(self, n: int) -> None:
        """Live tail saw new matches land. Refresh any tab that
        displays match_log rows so the user sees the update without
        a manual refresh."""
        # Find the active tab and refresh if it has a reload method.
        # Match Log + My Decks both pull from match_log.
        current = self.centralWidget().currentWidget() if hasattr(self, "centralWidget") else None
        for attr in ("_load_matches", "refresh", "reload"):
            if current and hasattr(current, attr):
                try:
                    getattr(current, attr)()
                    break
                except Exception:
                    pass

    def _on_watcher_status(self, status: str) -> None:
        """Watcher heartbeat -- show in status bar if present."""
        if hasattr(self, "statusBar"):
            try:
                self.statusBar().showMessage(status, 3000)  # 3-second flash
            except Exception:
                pass

    def closeEvent(self, event):
        """Clean shutdown of the live-tail watcher."""
        try:
            if hasattr(self, "_mtga_watcher"):
                self._mtga_watcher.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _auto_sync_mtga_on_launch(self) -> None:
        """Re-parse MTGA Player.log on launch so new matches show up
        without waiting for the 6 AM pipeline. Runs in a worker thread
        so it doesn't block the UI."""
        from gui.worker_threads import DataLoadWorker
        import os

        def _do():
            from scrapers.mtga_log_parser import (
                parse_log_file, save_matches_to_db, PLAYER_LOG, PLAYER_PREV_LOG,
            )
            all_matches = []
            for log_path in (PLAYER_LOG, PLAYER_PREV_LOG):
                if os.path.exists(log_path):
                    try:
                        all_matches.extend(parse_log_file(log_path))
                    except Exception:
                        pass
            if all_matches:
                return save_matches_to_db(all_matches, format_name="standard")
            return 0

        def _done(n):
            if n > 0:
                print(f"[auto-sync] {n} new MTGA matches imported on launch")

        def _err(exc):
            print(f"[auto-sync] MTGA launch sync failed: {exc}")

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(_err)
        w.start()
        self._launch_sync_worker = w  # keep ref

    def _open_palette(self) -> None:
        dlg = CommandPalette(
            self._palette_registry,
            recents_provider=lambda: self.ui_state.get(PALETTE_RECENTS, []) or [],
            recents_writer=self._record_palette_recent,
            parent=self,
        )
        dlg.exec()

    def _record_palette_recent(self, entry_id: str) -> None:
        recents = self.ui_state.get(PALETTE_RECENTS, []) or []
        recents = [r for r in recents if r != entry_id]
        recents.insert(0, entry_id)
        self.ui_state.set(PALETTE_RECENTS, recents[:20])

    # ------------------------------------------------------------------
    # Tab navigation helpers (used by palette handlers)
    # ------------------------------------------------------------------

    def activate_tab_by_path(self, path: str) -> None:
        """Switch to a tab by path, e.g. 'DECKS/MY DECKS'.

        Splits on '/' and descends through nested QTabWidgets, matching
        each part against tabText(). Persists the path to UIState so the
        active tab can be restored on next launch.
        """
        parts = path.split("/")
        from PyQt6.QtWidgets import QTabWidget
        node = self._tabs
        for part in parts:
            for i in range(node.count()):
                if node.tabText(i) == part:
                    node.setCurrentIndex(i)
                    child = node.widget(i)
                    if isinstance(child, QTabWidget):
                        node = child
                    break
        self.ui_state.set(LAST_ACTIVE_TAB_PATH, path)

    def set_format(self, fmt: str) -> None:
        """Write chosen format to UIState and refresh the current tab."""
        self.ui_state.set(GLOBAL_FORMAT, fmt)
        # Tabs hydrate from this on their next showEvent. Trigger a refresh
        # so the currently visible tab reflects the change immediately.
        self._refresh_current_tab()

    def open_archetype_detail(self, archetype_name: str) -> None:
        """Open the archetype detail dialog for the given archetype."""
        # ArchetypeDetailDialog(__init__) requires format_name; pull from
        # UIState (set by act:format-* palette actions), default to standard.
        fmt = self.ui_state.get(GLOBAL_FORMAT) or "standard"
        try:
            from gui.widgets.archetype_detail import ArchetypeDetailDialog
            dlg = ArchetypeDetailDialog(archetype_name, format_name=fmt, parent=self)
        except Exception as e:
            import logging
            logging.warning("Could not construct ArchetypeDetailDialog for %s: %s", archetype_name, e)
            return
        dlg.exec()

    def open_saved_deck(self, deck_id: int) -> None:
        """Switch to My Decks tab and select the given deck by id (if supported)."""
        self.activate_tab_by_path("DECKS/MY DECKS")
        my_decks = self._find_tab("MY DECKS")
        if my_decks is not None and hasattr(my_decks, "select_deck_by_id"):
            my_decks.select_deck_by_id(deck_id)

    def _find_tab(self, name: str):
        """Walk QTabWidget tree; return first widget whose tabText matches name."""
        from PyQt6.QtWidgets import QTabWidget
        def _walk(tabs):
            for i in range(tabs.count()):
                if tabs.tabText(i) == name:
                    return tabs.widget(i)
                child = tabs.widget(i)
                if isinstance(child, QTabWidget):
                    found = _walk(child)
                    if found is not None:
                        return found
            return None
        return _walk(self._tabs)

    def reset_ui_state(self) -> None:
        """Prompt user then clear persisted UI state (filters, selections, recents)."""
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Reset UI state",
            "Clear all persisted selections, filters, palette recents?\n"
            "(Format / API key / scrape preferences are NOT affected.)"
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.ui_state.reset()
            self.ui_state.flush()

    # ------------------------------------------------------------------
    # Ask Claude tab (optional — shown only when API key is configured)
    # ------------------------------------------------------------------

    def _add_claude_tab(self):
        if self._claude_added:
            return
        self._resources_tab.addTab(self._claude, "ASK CLAUDE")
        self._claude_added = True

    def _remove_claude_tab(self):
        if not self._claude_added:
            return
        idx = self._resources_tab.indexOf(self._claude)
        if idx >= 0:
            self._resources_tab.removeTab(idx)
        self._claude_added = False

    def _add_set_analysis_tab(self):
        if self._set_analysis_added:
            return
        self._resources_tab.addTab(self._set_analysis, "SET ANALYSIS")
        self._set_analysis_added = True

    def _remove_set_analysis_tab(self):
        if not self._set_analysis_added:
            return
        idx = self._resources_tab.indexOf(self._set_analysis)
        if idx >= 0:
            self._resources_tab.removeTab(idx)
        self._set_analysis_added = False

    def _on_api_key_changed(self, key: str):
        if key:
            self._add_claude_tab()
            self._add_set_analysis_tab()
        else:
            self._remove_claude_tab()
            self._remove_set_analysis_tab()

    def _on_open_in_rcq(self, deck: dict):
        """Switch to Tournament tab → Event Optimizer sub-tab."""
        idx = self._tabs.indexOf(self._tournament_tab)
        if idx >= 0:
            self._tabs.setCurrentIndex(idx)
        # Switch to Event Optimizer sub-tab (index 0)
        self._tournament_tab.setCurrentIndex(0)
        # Pre-fill Event Optimizer with the deck's archetype and format
        if hasattr(self._tourney, "load_deck"):
            self._tourney.load_deck(deck)

    def _compute_active_tab_path(self) -> str:
        """Walk from the root QTabWidget through any nested QTabWidget
        containers, joining tabText() at each level with '/'. Returns the
        full leaf path (e.g. 'DECKS/MY DECKS', 'META/CHARTS', 'DASHBOARD').
        """
        from PyQt6.QtWidgets import QTabWidget
        parts: list[str] = []
        node = self._tabs
        for _ in range(4):  # bounded — current tree depth is 2
            idx = node.currentIndex()
            if idx < 0:
                break
            label = node.tabText(idx)
            if label:
                parts.append(label)
            child = node.widget(idx)
            if isinstance(child, QTabWidget):
                node = child
            else:
                break
        return "/".join(parts)

    def _on_active_tab_changed(self, _index: int = -1) -> None:
        """Persist the full active-tab path. Fires from every QTabWidget
        in the tree, so sub-tab clicks (DECKS/MY DECKS, META/CHARTS, ...)
        get captured, not just the top-level switch."""
        path = self._compute_active_tab_path()
        if path:
            self.ui_state.set(LAST_ACTIVE_TAB_PATH, path)

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
        # Delegate cleanup to ALL tabs that hold workers
        for tab in (
            self._dash, self._deck, self._heatmap, self._charts,
            self._simulate, self._calibration, self._preds,
            self._claude, self._set_analysis, self._search,
            self._my_decks, self._match_log, self._kb,
            self._tourney, self._settings,
        ):
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
        # Flush persisted UI state on every close (spontaneous or not).
        try:
            self.ui_state.flush()
        except Exception:
            pass

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
