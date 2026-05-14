"""
Tab — Dashboard (Untapped.gg-inspired layout)

Top section — three panels side by side:
  Left:   Recent Top Finishes  (placement 1-4, most recent first)
  Middle: Win Rate Today        (archetypes ranked by est win%)
  Right:  Popularity Today      (archetypes ranked by appearances)

Bottom section — chart + toggleable archetype checkboxes:
  Chart toggles between "Popularity Over Time" and "Win Rate Over Time".
  Checkbox panel shows/hides individual archetype lines on the chart.

Mana color pips are inferred from archetype names (guild/shard/mono keywords).
Double-clicking any archetype row opens ArchetypeDetailDialog.
"""
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSplitter, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QCheckBox, QSizePolicy, QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from gui.widgets.chart_canvas import ChartCanvas, fetch_chart_data
from gui.worker_threads import DataLoadWorker
from gui.worker_utils import cancel_worker as _cancel_worker
from gui.state import UIState
from gui.state_keys import DASHBOARD_TIMEFRAME
import gui.theme as theme


# ---------------------------------------------------------------------------
# Color identity inference — delegated to theme module
# ---------------------------------------------------------------------------

def _color_identity(name: str) -> str:
    return theme.color_identity(name)


def _pip_color(identity: str) -> QColor:
    """Legacy helper used by chart checkbox dots."""
    if not identity:
        return QColor(theme.TEXT_DIM)
    return QColor(theme.MANA_COLORS.get(identity[0], "#888888"))


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_panel_data(format_name: str, since_dt, top: int,
                     dedup_cross_source: bool = True,
                     unique_player_decks: bool = False) -> dict:
    """Load standings + recent top finishes for the three top panels.

    When any dedup filter is active, also fetches raw (unfiltered) standings so
    the Meta Impact bar can show how many rows the filters removed.  Both calls
    use the same SQL — the dedup filters are pure-Python post-processing, so the
    extra call costs ~50 ms at most.
    """
    from datetime import datetime
    from analysis.win_rates import get_meta_standings
    from db.database import get_combined_connection

    standings = get_meta_standings(
        format_name=format_name, top=top, min_appearances=2, since=since_dt,
        dedup_cross_source=dedup_cross_source,
        unique_player_decks=unique_player_decks,
    )

    # Raw (unfiltered) standings — fetched only when a filter is on so we can
    # show before/after impact without an extra query on every load.
    raw_standings = None
    if dedup_cross_source or unique_player_decks:
        raw_standings = get_meta_standings(
            format_name=format_name, top=top, min_appearances=2, since=since_dt,
            dedup_cross_source=False, unique_player_decks=False,
        )

    # Real match win rates from matches table (MTGMelee + bracket inference).
    # Silently empty if no data has been scraped yet.
    real_wrs: dict = {}
    try:
        from analysis.win_rates import get_real_archetype_winrates
        real_wrs = get_real_archetype_winrates(
            format_name, since=since_dt, min_matches=20
        )
    except Exception:
        pass

    # Also fetch the *prior* period (same duration, shifted back) for trend arrows.
    prior_standings = []
    if since_dt:
        now = datetime.now()
        duration = now - since_dt
        prior_until = since_dt
        prior_since = since_dt - duration
        prior_standings = get_meta_standings(
            format_name=format_name, top=top, min_appearances=2,
            since=prior_since, until=prior_until,
            dedup_cross_source=dedup_cross_source,
            unique_player_decks=unique_player_decks,
        )

    conn = get_combined_connection()
    try:
        # Normalize dates to YYYYMMDD for correct ordering (MTGTop8=DD/MM/YY, MTGDecks=ISO)
        _date_key = (
            "CASE WHEN instr(e.date,'/')>0 "
            "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
            "ELSE replace(e.date,'-','') END"
        )
        from analysis.win_rates import is_all_formats
        q = """
            SELECT d.id AS deck_id, d.archetype, d.player, d.placement,
                   e.id AS event_id, e.name AS event_name, e.date, e.url AS event_url
            FROM decks d JOIN events e ON e.id = d.event_id
            WHERE d.placement <= 4
        """
        params = []
        if not is_all_formats(format_name):
            q += " AND lower(e.format) = lower(?)"
            params.append(format_name)
        if since_dt:
            q += f" AND ({_date_key}) >= ?"
            params.append(since_dt.strftime("%Y%m%d"))
        q += f" ORDER BY ({_date_key}) DESC, d.placement ASC LIMIT 15"
        recent = [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()

    # Glicko-2 archetype power ratings
    ratings_map: dict = {}
    try:
        from analysis.ratings import get_ratings_map
        ratings_map = get_ratings_map(format_name, since=since_dt, min_matches=10)
    except Exception:
        pass

    return {"standings": standings, "prior_standings": prior_standings,
            "recent": recent, "real_wrs": real_wrs,
            "raw_standings": raw_standings, "ratings": ratings_map}


# ---------------------------------------------------------------------------
# Helper — compact panel table
# ---------------------------------------------------------------------------

def _make_panel_table(headers: list) -> QTableWidget:
    tbl = QTableWidget(0, len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setAlternatingRowColors(True)
    tbl.verticalHeader().setVisible(False)
    tbl.setShowGrid(False)
    tbl.horizontalHeader().setHighlightSections(False)
    tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    tbl.setSortingEnabled(True)
    return tbl


def _set_cell(tbl, row, col, text, align=Qt.AlignmentFlag.AlignVCenter,
              fg: QColor = None, bold=False):
    item = QTableWidgetItem(text)
    item.setTextAlignment(align | Qt.AlignmentFlag.AlignLeft)
    if fg:
        item.setForeground(fg)
    if bold:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    tbl.setItem(row, col, item)
    return item


def _placement_str(p: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(p, f"{p}th")


def _date_sort_key(raw: str) -> str:
    """Normalize DD/MM/YY or YYYY-MM-DD to YYYYMMDD for sort key."""
    raw = raw or ""
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 3:
            return f"20{parts[2]}{parts[1]}{parts[0]}"
    return raw.replace("-", "")


from gui.widgets.table_helpers import SortItem as _SortItem, SORT_ROLE as _SORT_ROLE


def _fmt_date(raw: str) -> str:
    try:
        if "/" in raw:
            d, m, y = raw.split("/")
            dt = datetime(2000 + int(y), int(m), int(d))
        else:
            dt = datetime.fromisoformat(raw)
        return dt.strftime("%b %d").replace(" 0", " ")
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Dashboard tab
# ---------------------------------------------------------------------------

class DashboardTab(QWidget):

    _TIMEFRAME_OPTIONS = theme.TIMEFRAME_OPTIONS

    def __init__(self, parent=None, on_simulate=None):
        """
        on_simulate: optional callable(deck_text: str, source_label: str).
        When set, the archetype detail dialog (opened by double-clicking an
        archetype row) shows a 'Simulate' button that sends the archetype's
        consensus 75 to the SIMULATE tab.
        """
        super().__init__(parent)
        self._panel_worker  = None
        self._chart_worker  = None
        self._chart_data    = None     # cached fetch_chart_data result
        self._chart_checks  = {}       # archetype -> QCheckBox
        self._chart_mode    = "win_pct"
        self._standings     = []
        self._on_simulate   = on_simulate
        self._hydrated_state = False   # sticky state hydration guard

        # Debounce rapid filter changes — a 200ms pause before firing
        # collapses 'format-then-timeframe' clicks into a single refresh.
        from PyQt6.QtCore import QTimer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self.refresh)

        self._build_ui()

    def _schedule_refresh(self):
        """Called by filter widgets — restarts the debounce timer so rapid
        changes coalesce into one refresh instead of spawning N workers."""
        self._refresh_timer.start()

    # ------------------------------------------------------------------
    # Sticky state — hydrate once on first show
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        self._hydrate_from_state()
        self._hydrated_state = True

    def _hydrate_from_state(self) -> None:
        state = UIState.instance()
        # Timeframe — self._tf is a QComboBox with labels like "2 weeks" / "All Time"
        tf = state.get(DASHBOARD_TIMEFRAME)
        if tf and hasattr(self, "_tf"):
            self._tf.blockSignals(True)
            idx = self._tf.findText(tf)
            if idx >= 0:
                self._tf.setCurrentIndex(idx)
            self._tf.blockSignals(False)
        # No single-archetype selector on Dashboard for v1 (archetypes selected
        # via double-click → dialog or checkbox panel); revisit if a combo is added.

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        root.setSpacing(6)

        # ── Summary bar ─────────────────────────────────────────────
        from gui.widgets.summary_bar import SummaryBar
        self._summary_bar = SummaryBar()
        root.addWidget(self._summary_bar)

        # ── Controls bar ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(theme.SPACE_SM)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy", "all"])
        self._fmt.setFixedWidth(110)
        self._fmt.setToolTip(
            "'all' merges every scraped format — archetype rows include "
            "the format in their label so collisions stay distinguishable."
        )
        self._fmt.currentIndexChanged.connect(lambda _: self._schedule_refresh())
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Timeframe:"))
        self._tf = QComboBox()
        for label, _ in self._TIMEFRAME_OPTIONS:
            self._tf.addItem(label)
        self._tf.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._tf.setFixedWidth(110)
        self._tf.currentIndexChanged.connect(lambda _: self._schedule_refresh())
        self._tf.currentTextChanged.connect(
            lambda txt: UIState.instance().set(DASHBOARD_TIMEFRAME, txt)
        )
        ctrl.addWidget(self._tf)

        ctrl.addWidget(QLabel("Top N:"))
        self._top_n = QComboBox()
        self._top_n.addItems(["8", "12", "16", "20"])
        self._top_n.setCurrentText("12")
        self._top_n.setFixedWidth(60)
        ctrl.addWidget(self._top_n)

        from gui.icons_util import btn_icon
        self._refresh_btn = QPushButton(btn_icon("refresh", color=theme.BTN_FG), "Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_primary())
        self._refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(self._refresh_btn)

        # ── Dedup controls ────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        ctrl.addWidget(sep)

        _chk_style = f"color: {theme.TEXT}; font-size: 11px;"

        self._dedup_cs = QCheckBox("Dedup cross-source")
        self._dedup_cs.setChecked(True)
        self._dedup_cs.setStyleSheet(_chk_style)
        self._dedup_cs.setToolTip(
            "Remove duplicate decks scraped from multiple sites for the same event.\n"
            "Prevents the same deck from being double-counted in meta-share and win-rate.\n"
            "Recommended: ON"
        )
        self._dedup_cs.stateChanged.connect(self._schedule_refresh)
        ctrl.addWidget(self._dedup_cs)

        self._dedup_upd = QCheckBox("One per player")
        self._dedup_upd.setChecked(False)
        self._dedup_upd.setStyleSheet(_chk_style)
        self._dedup_upd.setToolTip(
            "Count only a player's best result with each unique deck, not every event they entered.\n"
            "Useful when a single player is dominating raw appearance counts.\n"
            "Default: OFF (each tournament result counts separately)"
        )
        self._dedup_upd.stateChanged.connect(self._schedule_refresh)
        ctrl.addWidget(self._dedup_upd)

        # ── Insights actions ──────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedWidth(1)
        sep2.setStyleSheet(f"background: {theme.BORDER};")
        ctrl.addWidget(sep2)

        self._shift_btn = QPushButton("Meta Shift")
        self._shift_btn.setStyleSheet(theme.btn_secondary())
        self._shift_btn.setFixedHeight(26)
        self._shift_btn.setToolTip("Compare current meta to the prior period \u2014 shows what changed")
        self._shift_btn.clicked.connect(self._show_meta_shift)
        ctrl.addWidget(self._shift_btn)

        self._recommend_btn = QPushButton("Best Deck")
        self._recommend_btn.setStyleSheet(theme.btn_secondary())
        self._recommend_btn.setFixedHeight(26)
        self._recommend_btn.setToolTip("Recommend the best deck for the current meta based on matchup data")
        self._recommend_btn.clicked.connect(self._show_recommendations)
        ctrl.addWidget(self._recommend_btn)

        self._cluster_btn = QPushButton("Clusters")
        self._cluster_btn.setStyleSheet(theme.btn_secondary())
        self._cluster_btn.setFixedHeight(26)
        self._cluster_btn.setToolTip(
            "Group archetypes by card-shell similarity so the meta reads "
            "as playstyle buckets rather than a flat alphabetical list."
        )
        self._cluster_btn.clicked.connect(self._show_clusters)
        ctrl.addWidget(self._cluster_btn)

        ctrl.addStretch()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        ctrl.addWidget(self._status_lbl)

        root.addLayout(ctrl)

        # ── Main splitter: top panels | chart ─────────────────────────
        self._vsplit = QSplitter(Qt.Orientation.Vertical)

        # -- Top: three panels -----------------------------------------
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        self._recent_tbl  = self._build_recent_panel(top_layout)
        self._winrate_tbl, self._winrate_hdr = self._build_ranked_panel(
            top_layout, "WIN RATE THIS WEEK", ["", "Archetype", "Win%", "Change", "Rating", "Prep", "Status", "Tier", "Role"])
        self._winrate_tbl.horizontalHeaderItem(4).setToolTip(
            "Glicko-2 Power Rating\n"
            "Skill estimate from real match results.\n"
            "1500 = average · Higher = stronger · ±N = uncertainty"
        )
        self._winrate_tbl.horizontalHeaderItem(5).setToolTip(
            "Prep Priority (0-100)\n"
            "How important it is to have a plan vs this deck.\n"
            "Blends meta share (60%) + win rate (40%)."
        )
        self._winrate_tbl.horizontalHeaderItem(6).setToolTip(
            "Meta Status\n"
            "──────────────\n"
            "Pillar       (green)  High share + high win rate — the decks to beat\n"
            "Trap         (red)    Popular but losing — avoid or exploit\n"
            "Underplayed  (gold)   Low share + high win rate — sleeper pick\n"
            "Fringe       (grey)   Low share, middling win rate"
        )
        self._winrate_tbl.horizontalHeaderItem(7).setToolTip(
            "Tier badge key\n"
            "──────────────\n"
            "S  (gold)   Win% >55% AND meta share >8%\n"
            "A  (green)  Win% >52% OR meta share >5%\n"
            "B  (cyan)   All other top-N archetypes\n"
            "C  (red)    Declining trend (share dropped >0.5%)\n\n"
            "★  Real match W/L data from MTGMelee (n≥20)\n"
            "   (no star = estimated from placement tier)"
        )
        self._pop_tbl, self._pop_hdr = self._build_ranked_panel(
            top_layout, "POPULAR THIS WEEK", ["", "Archetype", "Apps", "Meta%", "Change"])
        self._vsplit.addWidget(top_widget)

        # -- Bottom: chart + checkbox sidebar --------------------------
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(theme.SPACE_XS)

        # Chart mode toggle
        mode_row = QHBoxLayout()
        mode_row.setSpacing(theme.SPACE_XS)
        self._mode_pop_btn = QPushButton("Popularity Over Time")
        self._mode_win_btn = QPushButton("Win Rate Over Time")
        for btn in (self._mode_pop_btn, self._mode_win_btn):
            btn.setFixedHeight(26)
            btn.setStyleSheet(theme.btn_secondary())
        self._mode_pop_btn.clicked.connect(lambda: self._set_chart_mode("meta_share"))
        self._mode_win_btn.clicked.connect(lambda: self._set_chart_mode("win_pct"))
        mode_row.addWidget(self._mode_pop_btn)
        mode_row.addWidget(self._mode_win_btn)

        sep = QLabel("|")
        sep.setStyleSheet(f"color: {theme.BORDER}; font-size: 14px;")
        sep.setFixedWidth(12)
        mode_row.addWidget(sep)

        self._gran_weekly_btn = QPushButton("Weekly")
        self._gran_daily_btn  = QPushButton("Daily")
        for btn in (self._gran_weekly_btn, self._gran_daily_btn):
            btn.setFixedHeight(26)
        self._gran_weekly_btn.clicked.connect(lambda: self._set_granularity("weekly"))
        self._gran_daily_btn.clicked.connect(lambda: self._set_granularity("daily"))
        mode_row.addWidget(self._gran_weekly_btn)
        mode_row.addWidget(self._gran_daily_btn)
        self._chart_granularity = "weekly"
        self._set_granularity("weekly")  # set initial button styles

        sep2 = QLabel("|")
        sep2.setStyleSheet(f"color: {theme.BORDER}; font-size: 14px;")
        sep2.setFixedWidth(12)
        mode_row.addWidget(sep2)

        self._show_events_cb = QCheckBox("Show Events")
        self._show_events_cb.setChecked(True)
        self._show_events_cb.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._show_events_cb.setToolTip("Show set releases, B&R announcements, and rotation dates on charts")
        self._show_events_cb.stateChanged.connect(self._on_events_toggled)
        mode_row.addWidget(self._show_events_cb)

        mode_row.addStretch()
        bl.addLayout(mode_row)

        # Meta Impact bar — shown only when dedup filters remove rows
        self._impact_bar = QFrame()
        self._impact_bar.setFixedHeight(22)
        self._impact_bar.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 3px;"
        )
        impact_hl = QHBoxLayout(self._impact_bar)
        impact_hl.setContentsMargins(8, 0, 8, 0)
        impact_hl.setSpacing(theme.SPACE_SM)

        impact_title = QLabel("META IMPACT:")
        impact_title.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 10px; font-weight: bold;"
            f" letter-spacing: 1px; font-family: '{theme.HEADING_FONT}', Arial;"
            f" background: transparent; border: none;"
        )
        impact_hl.addWidget(impact_title)

        self._impact_lbl = QLabel("")
        self._impact_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; background: transparent; border: none;"
        )
        impact_hl.addWidget(self._impact_lbl, 1)
        self._impact_bar.setVisible(False)
        bl.addWidget(self._impact_bar)

        # Chart + sidebar
        chart_row = QHBoxLayout()
        chart_row.setSpacing(6)

        self._canvas = ChartCanvas()
        chart_row.addWidget(self._canvas, 3)

        # Checkbox sidebar
        sidebar_frame = QFrame()
        sidebar_frame.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 3px;"
        )
        sidebar_vl = QVBoxLayout(sidebar_frame)
        sidebar_vl.setContentsMargins(6, 6, 6, 6)
        sidebar_vl.setSpacing(theme.SPACE_XS)

        sidebar_hdr = QLabel("ARCHETYPES")
        sidebar_hdr.setStyleSheet(
            f"font-size: 10px; font-weight: bold; color: {theme.ACCENT};"
            f" letter-spacing: 1px; font-family: '{theme.HEADING_FONT}', Arial;"
        )
        sidebar_vl.addWidget(sidebar_hdr)

        sel_row = QHBoxLayout()
        all_btn  = QPushButton("All")
        none_btn = QPushButton("None")
        for btn in (all_btn, none_btn):
            btn.setFixedHeight(20)
            btn.setStyleSheet(theme.btn_secondary())
        all_btn.clicked.connect(self._select_all_archetypes)
        none_btn.clicked.connect(self._deselect_all_archetypes)
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        sidebar_vl.addLayout(sel_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._check_container = QWidget()
        self._check_layout    = QVBoxLayout(self._check_container)
        self._check_layout.setContentsMargins(0, 0, 0, 0)
        self._check_layout.setSpacing(2)
        self._check_layout.addStretch()
        scroll.setWidget(self._check_container)
        sidebar_vl.addWidget(scroll, 1)

        chart_row.addWidget(sidebar_frame, 1)
        bl.addLayout(chart_row, 1)

        self._vsplit.addWidget(bottom)
        self._vsplit.setSizes([210, 440])

        root.addWidget(self._vsplit, 1)

    def _build_recent_panel(self, parent_layout) -> QTableWidget:
        # Columns: Pl | Colors | Archetype | Player | Event | Date
        frame, tbl, _, _hdr = self._panel_frame("RECENT TOP FINISHES",
                                       ["Pl", "Colors", "Archetype", "Player", "Event", "Date"])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        tbl.itemDoubleClicked.connect(self._on_recent_dblclick)
        tbl.itemClicked.connect(self._on_recent_dblclick)
        parent_layout.addWidget(frame)
        return tbl

    def _build_ranked_panel(self, parent_layout, title: str, cols: list):
        frame, tbl, hdr_lbl, hdr_row = self._panel_frame(title, cols)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, len(cols)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        tbl.itemDoubleClicked.connect(self._on_ranked_dblclick)
        tbl.itemClicked.connect(self._on_ranked_dblclick)

        csv_btn = QPushButton("CSV")
        csv_btn.setFixedSize(34, 18)
        csv_btn.setToolTip("Export this panel to CSV")
        csv_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_DIM};"
            f" border: 1px solid {theme.BORDER}; border-radius: 2px; font-size: 9px; }}"
            f"QPushButton:hover {{ color: {theme.ACCENT}; border-color: {theme.ACCENT}; }}"
        )
        csv_btn.clicked.connect(lambda: self._export_panel_csv(tbl, title))
        hdr_row.addWidget(csv_btn)

        parent_layout.addWidget(frame)
        return tbl, hdr_lbl

    def _panel_frame(self, title: str, cols: list):
        """Return (QFrame, QTableWidget, title_QLabel, hdr_QHBoxLayout)."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 3px; }}"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        # Header row — title label + space for action buttons
        hdr_frame = QFrame()
        hdr_frame.setFixedHeight(28)
        hdr_frame.setStyleSheet(
            f"background: {theme.PANEL}; border-bottom: 1px solid {theme.BORDER};"
        )
        hdr_row = QHBoxLayout(hdr_frame)
        hdr_row.setContentsMargins(0, 0, 4, 0)
        hdr_row.setSpacing(0)

        hdr = QLabel(f"  {title}")
        hdr.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 10px; font-weight: bold;"
            f" letter-spacing: 1px; font-family: '{theme.HEADING_FONT}', Arial;"
            f" background: transparent; border: none;"
        )
        hdr_row.addWidget(hdr, 1)
        fl.addWidget(hdr_frame)

        tbl = _make_panel_table(cols)
        fl.addWidget(tbl, 1)
        return frame, tbl, hdr, hdr_row

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cleanup(self):
        """Stop all running workers. Called by MainWindow on app exit."""
        from gui.worker_utils import stop_worker
        stop_worker(self._panel_worker)
        stop_worker(self._chart_worker)
        self._panel_worker = None
        self._chart_worker = None

    def refresh(self):
        self._status_lbl.setText("Loading…")
        self._refresh_btn.setEnabled(False)
        self._canvas.show_message("Loading chart data…", theme.ACCENT)

        # Discard results from any still-running workers before replacing them
        _cancel_worker(self._panel_worker)
        _cancel_worker(self._chart_worker)

        fmt       = self._fmt.currentText()
        top       = int(self._top_n.currentText())
        since     = self._since_dt()
        dedup_cs  = self._dedup_cs.isChecked()
        dedup_upd = self._dedup_upd.isChecked()

        self._panel_worker = DataLoadWorker(
            _load_panel_data,
            # Fetch top=50 so high-frequency archetypes (e.g. Izzet Prowess) aren't
            # excluded by performance-based ranking; display is limited to top N below.
            {"format_name": fmt, "since_dt": since, "top": 50,
             "dedup_cross_source": dedup_cs, "unique_player_decks": dedup_upd},
        )
        self._panel_worker.result.connect(self._on_panel_data)
        self._panel_worker.error.connect(self._on_error)
        self._panel_worker.finished.connect(
            lambda: self._refresh_btn.setEnabled(True)
        )
        self._panel_worker.finished.connect(self._panel_worker.deleteLater)
        self._panel_worker.finished.connect(
            lambda: setattr(self, "_panel_worker", None)
        )
        self._panel_worker.start()

        self._reload_chart(auto_suggest=True)

    def _reload_chart(self, auto_suggest=False):
        """Load chart data with current settings. Called from refresh() and _set_granularity()."""
        _cancel_worker(self._chart_worker)
        self._chart_worker = None

        fmt   = self._fmt.currentText()
        top   = int(self._top_n.currentText())
        since = self._since_dt()
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        # Cap chart weeks to 52 for performance (All Time = None → 52 week chart)
        chart_weeks = weeks if weeks is not None else 52
        gran  = getattr(self, "_chart_granularity", "weekly")

        # Auto-suggest: short timeframes default to daily (only on initial load, not user toggle)
        if auto_suggest and gran == "weekly" and weeks is not None and weeks <= 2:
            gran = "daily"
            self._chart_granularity = gran
            self._gran_weekly_btn.setStyleSheet(theme.btn_secondary())
            self._gran_daily_btn.setStyleSheet(theme.btn_primary())

        dedup_cs  = self._dedup_cs.isChecked()
        dedup_upd = self._dedup_upd.isChecked()

        self._chart_worker = DataLoadWorker(
            fetch_chart_data,
            {"format_name": fmt, "top": top, "weeks": chart_weeks,
             "since": since, "until": None, "standings": None,
             "dedup_cross_source": dedup_cs, "unique_player_decks": dedup_upd,
             "granularity": gran},
        )
        self._chart_worker.result.connect(self._on_chart_data)
        self._chart_worker.error.connect(
            lambda e: self._canvas.show_message(f"Chart error: {e}", theme.ERR)
        )
        self._chart_worker.finished.connect(self._chart_worker.deleteLater)
        self._chart_worker.finished.connect(
            lambda: setattr(self, "_chart_worker", None)
        )
        self._chart_worker.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_panel_data(self, data: dict):
        self._standings = data["standings"]
        self._prior_standings = data.get("prior_standings", [])
        n = len(self._standings)
        # Detect matches-table fallback
        using_matches = any(s.get("_source") == "matches" for s in self._standings)
        if n == 0:
            fmt = self._fmt.currentText()
            tf = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
            self._status_lbl.setText(
                f"No {fmt} data in the last {tf.lower()} — run "
                f"fill_database.bat or widen the timeframe."
            )
            self._status_lbl.setStyleSheet(f"color: {theme.WARN};")
        elif using_matches:
            self._status_lbl.setText(
                f"{n} archetypes (using match data \u2014 deck scraper needs refresh)"
            )
            self._status_lbl.setStyleSheet(f"color: {theme.WARN};")
        else:
            self._status_lbl.setText(f"{n} archetype{'s' if n != 1 else ''} loaded")
            self._status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM};")

        # Update panel titles to reflect the current timeframe
        tf_label = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
        self._winrate_hdr.setText(f"  WIN RATE — {tf_label.upper()}")
        self._pop_hdr.setText(f"  POPULAR — {tf_label.upper()}")

        # Enrich standings with prep priority + status labels
        from analysis.meta_scoring import score_standings
        real_wrs = data.get("real_wrs", {})
        score_standings(self._standings, real_wrs)

        prior_map = {s["archetype"]: s for s in data.get("prior_standings", [])}
        self._populate_winrate(self._standings, prior_map, real_wrs,
                               data.get("ratings", {}))
        self._populate_popularity(self._standings, prior_map)
        self._populate_recent(data["recent"])

        # Summary bar
        fmt = self._fmt.currentText().upper()
        stats = []
        total_apps = sum(s.get("appearances", 0) for s in self._standings)
        if total_apps:
            stats.append(f"{total_apps:,} appearances")
        if self._standings:
            top = self._standings[0]
            top_name = top.get("archetype", "?")
            top_share = top.get("appearances", 0) / max(total_apps, 1) * 100
            stats.append(f"Top: {top_name} {top_share:.1f}%")
        real_wrs = data.get("real_wrs", {})
        if real_wrs:
            stats.append(f"{len(real_wrs)} archetypes with real W/L data")
        self._summary_bar.update(fmt, stats)

        # Meta Impact bar
        impact = _compute_impact(self._standings, data.get("raw_standings"))
        if impact and impact["rows_removed"] > 0:
            parts = [f"-{impact['rows_removed']} decks ({impact['pct_removed']}%)"]
            if impact["most_affected"]:
                affected_str = ", ".join(
                    f"{_shorten_arch(a['archetype'], 18)} \u2212{a['delta']}"
                    for a in impact["most_affected"]
                )
                parts.append(f"Most affected: {affected_str}")
            if impact["most_stable"]:
                parts.append(f"Most stable: {_shorten_arch(impact['most_stable']['archetype'], 20)}")
            self._impact_lbl.setText("  \u2502  ".join(parts))
            self._impact_bar.setVisible(True)
        else:
            self._impact_bar.setVisible(False)

    def _on_chart_data(self, data):
        self._chart_data = data
        self._rebuild_checkboxes(data if data else None)
        show_ev = self._show_events_cb.isChecked()
        visible = {a for a, cb in self._chart_checks.items() if cb.isChecked()}
        self._canvas.draw_from_data(data, visible, mode=self._chart_mode, show_events=show_ev)

    def _on_error(self, msg: str):
        # Show user-friendly error instead of raw exception
        friendly = str(msg)
        if "no such table" in friendly.lower():
            friendly = "Database not initialized yet. Run the setup wizard or fill_database.bat first."
        elif "connection" in friendly.lower() or "locked" in friendly.lower():
            friendly = "Database is busy or locked. Try again in a few seconds."
        self._status_lbl.setText(f"Could not load data: {friendly}")

    def _on_ranked_dblclick(self, item):
        """Double-click on win-rate or popularity table → open detail."""
        tbl = self.sender().parent() if hasattr(self.sender(), 'parent') else None
        # Determine which table fired the signal
        for t in (self._winrate_tbl, self._pop_tbl):
            if t.selectedItems():
                arch = t.item(t.currentRow(), 1)
                if arch:
                    self._open_detail(arch.text())
                return

    def _on_recent_dblclick(self, item):
        row = self._recent_tbl.currentRow()
        col = self._recent_tbl.currentColumn()

        # Event column click → show all decks from that event
        if col == 4:
            ev_item = self._recent_tbl.item(row, 4)
            if ev_item:
                ev_data = ev_item.data(Qt.ItemDataRole.UserRole)
                if isinstance(ev_data, dict) and ev_data.get("event_id"):
                    self._open_event_peers(ev_data)
                    return

        # Archetype click → show deck detail
        arch_item = self._recent_tbl.item(row, 2)
        if arch_item:
            raw = arch_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(raw, dict):
                self._open_detail(raw["archetype"], deck_id=raw.get("deck_id"))
            else:
                self._open_detail(raw or arch_item.text())

    def _open_event_peers(self, ev_data: dict):
        from gui.widgets.event_peers import EventPeersDialog
        dlg = EventPeersDialog(
            event_id=ev_data["event_id"],
            event_name=ev_data.get("event_name", ""),
            event_url=ev_data.get("event_url", ""),
            parent=self,
        )
        dlg.exec()

    def _open_detail(self, archetype: str, deck_id: int = None):
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        dlg = ArchetypeDetailDialog(
            archetype=archetype,
            format_name=self._fmt.currentText(),
            initial_weeks=weeks,
            parent=self,
            deck_id=deck_id,
            on_simulate=self._on_simulate,
        )
        dlg.exec()

    # ------------------------------------------------------------------
    # Panel population
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def _export_panel_csv(self, tbl: QTableWidget, title: str):
        """Save the panel table to exports/<title>_<fmt>_<stamp>.csv."""
        import csv, os
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from datetime import datetime

        # Build header row — skip col 0 (pip widget, no text)
        headers = []
        for c in range(1, tbl.columnCount()):
            h = tbl.horizontalHeaderItem(c)
            headers.append(h.text() if h else "")

        rows = []
        for r in range(tbl.rowCount()):
            row = []
            for c in range(1, tbl.columnCount()):
                item = tbl.item(r, c)
                row.append(item.text() if item else "")
            rows.append(row)

        exports_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "exports")
        )
        os.makedirs(exports_dir, exist_ok=True)

        safe = title.replace(" ", "_").replace("—", "").replace("/", "_").strip("_")
        fmt  = self._fmt.currentText()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(exports_dir, f"{safe}_{fmt}_{stamp}.csv")

        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([headers] + rows)

        QMessageBox.information(self, "Export Complete", f"Saved to:\n{path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(exports_dir))

    # Subtle row tint colors for rising / falling archetypes
    _ROW_RISING  = QColor(20, 55, 28)   # subtle green tint
    _ROW_FALLING = QColor(60, 20, 20)   # subtle red tint

    @staticmethod
    def _tier_badge(winrate: float, meta_share: float, is_declining: bool):
        """Return (tier_letter, QColor) for a meta tier badge.

        S = win rate >55% AND meta share >8%
        A = win rate >52% OR meta share >5%
        B = everything else in top N
        C = declining trend
        """
        pct   = winrate * 100
        share = meta_share * 100
        if pct > 55 and share > 8:
            return "S", QColor("#FFD700")          # gold
        if pct > 52 or share > 5:
            return "A", QColor(theme.OK)            # green
        if is_declining:
            return "C", QColor(theme.ERR)           # red
        return "B", QColor(theme.ACCENT)            # cyan

    def _trend_bg(self, archetype: str, prior_map: dict,
                  current_val: float, prior_key: str,
                  threshold: float = 0.02) -> QColor | None:
        """Return a tint color if the archetype is clearly rising or falling."""
        if not prior_map or archetype not in prior_map:
            return None
        prior_val = prior_map[archetype].get(prior_key) or 0
        delta = current_val - prior_val
        if delta > threshold:
            return self._ROW_RISING
        if delta < -threshold:
            return self._ROW_FALLING
        return None

    def _populate_winrate(self, standings: list, prior_map: dict = None,
                          real_wrs: dict = None, ratings: dict = None):
        tbl = self._winrate_tbl
        tbl.setSortingEnabled(False)
        top_n = int(self._top_n.currentText())
        ranked = sorted(
            [s for s in standings
             if s.get("est_match_winpct") is not None and s["appearances"] >= 15],
            key=lambda s: -s["est_match_winpct"],
        )[:top_n]

        total_apps  = sum(s["appearances"] for s in standings) or 1
        prior_total = (sum(p.get("appearances", 0) for p in prior_map.values()) or 1
                       if prior_map else 1)

        tbl.setRowCount(len(ranked))
        for ri, s in enumerate(ranked):
            ident = _color_identity(s["archetype"])
            tbl.setCellWidget(ri, 0, theme.make_pip_widget(ident))

            # Use real match W/L where available (MTGMelee / bracket inference)
            real = (real_wrs or {}).get(s["archetype"])
            if s["appearances"] < 15:
                # Too few data points for meaningful win rate
                pct        = s["est_match_winpct"] * 100
                pct_text   = "\u2014"
                pct_tip    = f"Only {s['appearances']} appearances — need 15+ for reliable win rate"
                is_real_wr = False
            elif real:
                pct        = real["win_rate"] * 100
                pct_text   = f"{pct:.1f}%\u2605"   # ★ = real data
                pct_tip    = (f"Match W/L (n={real['total']:,})\n"
                              f"{real['wins']}W \u2013 {real['losses']}L \u2013 {real['draws']}D")
                is_real_wr = True
            else:
                pct        = s["est_match_winpct"] * 100
                pct_text   = f"{pct:.1f}%"
                pct_tip    = "Estimated from placement tier (no real match data yet)"
                is_real_wr = False

            bg  = self._trend_bg(s["archetype"], prior_map,
                                  s["est_match_winpct"], "est_match_winpct",
                                  threshold=0.02)

            arch_item = _set_cell(tbl, ri, 1, s["archetype"])
            if bg:
                arch_item.setBackground(bg)

            clr = QColor(theme.OK) if pct >= 55 else (
                  QColor(theme.WARN) if pct >= 50 else QColor(theme.ERR))
            if not is_real_wr:
                # Dim estimated values slightly
                clr = clr.darker(115)
            pct_item = _SortItem(pct_text)
            pct_item.setData(_SORT_ROLE, pct)
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            pct_item.setForeground(clr)
            pct_item.setToolTip(pct_tip)
            pct_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                pct_item.setBackground(bg)
            tbl.setItem(ri, 2, pct_item)

            # Win rate % change vs prior period
            meta_share  = s["appearances"] / total_apps
            prior_apps  = (prior_map[s["archetype"]].get("appearances", 0)
                           if prior_map and s["archetype"] in prior_map else 0)
            prior_share = prior_apps / prior_total if prior_map else meta_share
            is_declining = prior_map is not None and (meta_share - prior_share) < -0.005

            if prior_map and s["archetype"] in prior_map:
                prior_wr = prior_map[s["archetype"]].get("est_match_winpct")
                if prior_wr is not None:
                    wr_delta = (pct) - (prior_wr * 100)
                    wr_sign = "+" if wr_delta > 0 else ""
                    wr_chg_text = f"{wr_sign}{wr_delta:.1f}%"
                    wr_chg_clr = (QColor(theme.OK) if wr_delta > 1.0 else
                                  QColor(theme.ERR) if wr_delta < -1.0 else
                                  QColor(theme.TEXT_DIM))
                else:
                    wr_delta = 0
                    wr_chg_text = "\u2014"
                    wr_chg_clr = QColor(theme.TEXT_DIM)
            else:
                wr_delta = 0
                wr_chg_text = "NEW"
                wr_chg_clr = QColor(theme.ACCENT)
            wr_chg_item = _SortItem(wr_chg_text)
            wr_chg_item.setData(_SORT_ROLE, wr_delta)
            wr_chg_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            wr_chg_item.setForeground(wr_chg_clr)
            wr_chg_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                wr_chg_item.setBackground(bg)
            tbl.setItem(ri, 3, wr_chg_item)

            # Glicko-2 rating column
            r = (ratings or {}).get(s["archetype"])
            if r:
                rat_text = f"{r.rating:.0f}"
                rat_tip = (f"Glicko-2: {r.display}\n"
                           f"95% CI: {r.confidence_interval[0]:.0f} – "
                           f"{r.confidence_interval[1]:.0f}\n"
                           f"Based on {r.matches} matches")
                rat_val = r.rating
                rat_clr = (QColor(theme.OK) if r.rating >= 1600 else
                           QColor(theme.WARN) if r.rating >= 1500 else
                           QColor(theme.ERR))
                # Dim if high uncertainty
                if r.deviation > 100:
                    rat_clr = rat_clr.darker(130)
            else:
                rat_text = "\u2014"
                rat_tip = "No real match data for rating"
                rat_val = 0
                rat_clr = QColor(theme.TEXT_DIM)
            rat_item = _SortItem(rat_text)
            rat_item.setData(_SORT_ROLE, rat_val)
            rat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            rat_item.setForeground(rat_clr)
            rat_item.setToolTip(rat_tip)
            rat_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                rat_item.setBackground(bg)
            tbl.setItem(ri, 4, rat_item)

            # Prep priority column (0-100)
            pp = s.get("prep_priority", 0)
            pp_item = _SortItem(str(int(pp)))
            pp_item.setData(_SORT_ROLE, pp)
            pp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            pp_clr = (QColor(theme.ERR) if pp >= 70 else
                      QColor(theme.WARN) if pp >= 40 else
                      QColor(theme.TEXT_DIM))
            pp_item.setForeground(pp_clr)
            pp_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                pp_item.setBackground(bg)
            tbl.setItem(ri, 5, pp_item)

            # Status column (Pillar / Trap / Underplayed / Fringe)
            status = s.get("status", "")
            status_color = s.get("status_color", theme.TEXT_DIM)
            st_item = QTableWidgetItem(status)
            st_item.setForeground(QColor(status_color))
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            st_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            f = st_item.font(); f.setBold(True); st_item.setFont(f)
            if bg:
                st_item.setBackground(bg)
            tbl.setItem(ri, 6, st_item)

            tier, tier_color = self._tier_badge(s["est_match_winpct"], meta_share, is_declining)
            tier_item = QTableWidgetItem(tier)
            tier_item.setForeground(tier_color)
            tier_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            tier_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            f = tier_item.font(); f.setBold(True); tier_item.setFont(f)
            if bg:
                tier_item.setBackground(bg)
            tbl.setItem(ri, 7, tier_item)

        # Deck role classification (batch for all visible archetypes)
        try:
            from analysis.deck_roles import classify_roles_batch
            fmt = self._fmt.currentText()
            arch_names = [s["archetype"] for s in ranked]
            roles = classify_roles_batch(arch_names, fmt)
            _ROLE_COLORS = {
                "Aggro": theme.ERR, "Midrange": theme.OK,
                "Control": "#42a5f5", "Combo": "#a078e0",
                "Tempo": theme.ACCENT, "Unknown": theme.TEXT_DIM,
            }
            for ri, s in enumerate(ranked):
                role = roles.get(s["archetype"], "")
                role_item = QTableWidgetItem(role)
                role_item.setForeground(QColor(_ROLE_COLORS.get(role, theme.TEXT_DIM)))
                role_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                role_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                f = role_item.font(); f.setBold(True); role_item.setFont(f)
                tbl.setItem(ri, 8, role_item)
        except Exception:
            pass  # role classification is non-critical

        tbl.resizeRowsToContents()
        tbl.setSortingEnabled(True)
        tbl.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    def _populate_popularity(self, standings: list, prior_map: dict = None):
        tbl = self._pop_tbl
        tbl.setSortingEnabled(False)
        top_n = int(self._top_n.currentText())
        ranked = sorted(standings, key=lambda s: -s["appearances"])[:top_n]
        total_apps      = sum(s["appearances"] for s in standings) or 1
        prior_total     = sum(p.get("appearances", 0) for p in prior_map.values()) or 1 \
                          if prior_map else 1
        tbl.setRowCount(len(ranked))
        for ri, s in enumerate(ranked):
            ident = _color_identity(s["archetype"])
            tbl.setCellWidget(ri, 0, theme.make_pip_widget(ident))

            cur_share  = s["appearances"] / total_apps
            prior_share = (prior_map[s["archetype"]]["appearances"] / prior_total
                           if prior_map and s["archetype"] in prior_map else 0)
            bg = self._trend_bg(s["archetype"], prior_map,
                                cur_share, "__share__",  # sentinel — computed above
                                threshold=0.005)
            # Re-derive bg from share delta directly since prior_key trick won't work
            if prior_map and s["archetype"] in prior_map:
                delta = cur_share - prior_share
                bg = self._ROW_RISING if delta > 0.005 else (
                     self._ROW_FALLING if delta < -0.005 else None)
            else:
                bg = None

            arch_item = _set_cell(tbl, ri, 1, s["archetype"])
            if bg:
                arch_item.setBackground(bg)

            apps_item = _SortItem(str(s["appearances"]))
            apps_item.setData(_SORT_ROLE, s["appearances"])
            apps_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            apps_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                apps_item.setBackground(bg)
            tbl.setItem(ri, 2, apps_item)

            meta_pct  = cur_share * 100
            pct_item  = _SortItem(f"{meta_pct:.1f}%")
            pct_item.setData(_SORT_ROLE, meta_pct)
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            pct_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                pct_item.setBackground(bg)
            tbl.setItem(ri, 3, pct_item)

            # % change in meta share vs prior period
            if prior_map and s["archetype"] in prior_map:
                delta_pct = (cur_share - prior_share) * 100
                sign = "+" if delta_pct > 0 else ""
                chg_text = f"{sign}{delta_pct:.1f}%"
                chg_clr = (QColor(theme.OK) if delta_pct > 0.5 else
                           QColor(theme.ERR) if delta_pct < -0.5 else
                           QColor(theme.TEXT_DIM))
            else:
                chg_text = "NEW"
                chg_clr = QColor(theme.ACCENT)
                delta_pct = 0
                new_tip = f"New in this period: {s['appearances']} apps, {cur_share*100:.1f}% meta share"
            chg_item = _SortItem(chg_text)
            chg_item.setData(_SORT_ROLE, delta_pct)
            chg_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            chg_item.setForeground(chg_clr)
            chg_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if chg_text == "NEW":
                chg_item.setToolTip(new_tip)
            if bg:
                chg_item.setBackground(bg)
            tbl.setItem(ri, 4, chg_item)

        tbl.resizeRowsToContents()
        tbl.setSortingEnabled(True)
        tbl.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    def _populate_recent(self, recent: list):
        # Columns: 0=Pl, 1=Colors(pip), 2=Archetype, 3=Player, 4=Event, 5=Date
        tbl = self._recent_tbl
        tbl.setSortingEnabled(False)
        tbl.setRowCount(len(recent))
        for ri, r in enumerate(recent):
            pl  = r["placement"]
            clr = (QColor(theme.ACCENT) if pl == 1 else
                   QColor(theme.ACCENT2) if pl == 2 else
                   QColor(theme.TEXT))
            pl_item = _SortItem(_placement_str(pl))
            pl_item.setData(_SORT_ROLE, pl)
            pl_item.setForeground(clr)
            if pl == 1:
                f = pl_item.font(); f.setBold(True); pl_item.setFont(f)
            pl_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            tbl.setItem(ri, 0, pl_item)

            ident = _color_identity(r["archetype"])
            tbl.setCellWidget(ri, 1, theme.make_pip_widget(ident))
            _set_cell(tbl, ri, 2, r["archetype"])
            tbl.item(ri, 2).setData(Qt.ItemDataRole.UserRole, {
                "archetype": r["archetype"],
                "deck_id":   r.get("deck_id"),
            })
            player = r.get("player", "") or ""
            _set_cell(tbl, ri, 3, player)
            event = r.get("event_name", "") or ""
            ev_item = QTableWidgetItem(event[:28])
            ev_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            ev_item.setForeground(QColor(theme.ACCENT))
            ev_item.setToolTip(f"Click to see all decks from this event\n{event}")
            ev_item.setData(Qt.ItemDataRole.UserRole, {
                "event_id": r.get("event_id"),
                "event_name": event,
                "event_url": r.get("event_url", ""),
            })
            tbl.setItem(ri, 4, ev_item)

            raw_date = r.get("date", "") or ""
            date_item = _SortItem(_fmt_date(raw_date))
            date_item.setData(_SORT_ROLE, _date_sort_key(raw_date))
            date_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            tbl.setItem(ri, 5, date_item)

        tbl.resizeRowsToContents()
        tbl.setSortingEnabled(True)
        tbl.sortByColumn(5, Qt.SortOrder.DescendingOrder)

    # ------------------------------------------------------------------
    # Chart checkbox sidebar
    # ------------------------------------------------------------------

    def _rebuild_checkboxes(self, data):
        """Rebuild the checkbox list. Top 8 by total appearances are checked."""
        # Remove old checkboxes
        self._chart_checks.clear()
        while self._check_layout.count() > 1:  # keep the trailing stretch
            item = self._check_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not data:
            return
        archetypes = data.get("archetypes", [])
        if not archetypes:
            return

        # Determine top 8 by total appearances across all weeks
        sample = data.get("sample_data", {})
        total_apps = {arch: sum(sample.get(arch, {}).values()) for arch in archetypes}
        top8 = set(sorted(archetypes, key=lambda a: -total_apps.get(a, 0))[:8])

        palette = __import__("gui.theme", fromlist=["CHART_PALETTE"]).CHART_PALETTE
        for i, arch in enumerate(archetypes):
            color_hex = palette[i % len(palette)]
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_hl = QHBoxLayout(row_widget)
            row_hl.setContentsMargins(2, 0, 2, 0)
            row_hl.setSpacing(theme.SPACE_XS)

            dot = QLabel("\u25cf")
            dot.setStyleSheet(f"color: {color_hex}; font-size: 10px; background: transparent;")
            dot.setFixedWidth(14)
            row_hl.addWidget(dot)

            cb = QCheckBox(_shorten_arch(arch))
            cb.setChecked(arch in top8)
            cb.setStyleSheet(f"color: {theme.TEXT}; font-size: 11px; background: transparent;")
            cb.stateChanged.connect(self._on_checkbox_changed)
            row_hl.addWidget(cb, 1)

            self._check_layout.insertWidget(self._check_layout.count() - 1, row_widget)
            self._chart_checks[arch] = cb

    def _on_checkbox_changed(self):
        if self._chart_data:
            visible = {a for a, cb in self._chart_checks.items() if cb.isChecked()}
            show_ev = self._show_events_cb.isChecked()
            self._canvas.draw_from_data(self._chart_data, visible,
                                        mode=self._chart_mode, show_events=show_ev)

    def _select_all_archetypes(self):
        for cb in self._chart_checks.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self._on_checkbox_changed()

    def _deselect_all_archetypes(self):
        for cb in self._chart_checks.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._on_checkbox_changed()

    def _set_chart_mode(self, mode: str):
        self._chart_mode = mode
        self._mode_pop_btn.setStyleSheet(
            theme.btn_primary() if mode == "meta_share" else theme.btn_secondary()
        )
        self._mode_win_btn.setStyleSheet(
            theme.btn_primary() if mode == "win_pct" else theme.btn_secondary()
        )
        if self._chart_data:
            visible = {a for a, cb in self._chart_checks.items() if cb.isChecked()}
            show_ev = self._show_events_cb.isChecked()
            self._canvas.draw_from_data(self._chart_data, visible, mode=mode,
                                        show_events=show_ev)

    def _on_events_toggled(self):
        if self._chart_data:
            visible = {a for a, cb in self._chart_checks.items() if cb.isChecked()}
            show_ev = self._show_events_cb.isChecked()
            self._canvas.draw_from_data(self._chart_data, visible,
                                        mode=self._chart_mode, show_events=show_ev)

    def _set_granularity(self, gran: str):
        self._chart_granularity = gran
        self._gran_weekly_btn.setStyleSheet(
            theme.btn_primary() if gran == "weekly" else theme.btn_secondary()
        )
        self._gran_daily_btn.setStyleSheet(
            theme.btn_primary() if gran == "daily" else theme.btn_secondary()
        )
        # Reload chart data with new granularity (skip during _build_ui)
        if getattr(self, "_chart_data", None) is not None:
            self._reload_chart()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _since_dt(self):
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        return (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None

    def _show_meta_shift(self):
        """Compare current period vs prior period — shows rising/falling/new/gone archetypes."""
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        if weeks is None:
            weeks = 4  # default for All Time
        fmt = self._fmt.currentText()

        from analysis.meta_change import compare_periods
        try:
            result = compare_periods(fmt, weeks_current=weeks, weeks_prior=weeks)
        except Exception as e:
            QMessageBox.warning(self, "Meta Shift", theme.friendly_error(e))
            return

        archs = result["archetypes"]
        if not archs:
            QMessageBox.information(self, "Meta Shift", "No data for comparison.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Meta Shift \u2014 {fmt.capitalize()}")
        dlg.setMinimumSize(700, 500)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        s = result["summary"]
        summary = QLabel(
            f"{result['current_label']} vs {result['prior_label']}  \u2014  "
            f"{s['rising']} rising, {s['falling']} falling, "
            f"{s['new']} new, {s['gone']} gone"
        )
        summary.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; padding: 4px;")
        layout.addWidget(summary)

        tbl = QTableWidget(len(archs), 7)
        tbl.setHorizontalHeaderLabels([
            "Archetype", "Share Now", "Share Before", "\u0394 Share",
            "WR Now", "\u0394 WR", "Status",
        ])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 7):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)

        _STATUS_COLORS = {
            "rising": theme.OK, "falling": theme.ERR, "new": theme.ACCENT,
            "gone": theme.ERR, "stable": theme.TEXT_DIM,
        }
        _STATUS_LABELS = {
            "rising": "\u2191 Rising", "falling": "\u2193 Falling",
            "new": "\u2605 New", "gone": "\u2620 Gone", "stable": "\u2192 Stable",
        }

        for ri, a in enumerate(archs):
            tbl.setItem(ri, 0, QTableWidgetItem(a["archetype"]))

            for ci, val in [
                (1, f"{a['current_share']*100:.1f}%"),
                (2, f"{a['prior_share']*100:.1f}%"),
            ]:
                it = QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tbl.setItem(ri, ci, it)

            # Share delta
            sd = a["share_delta"] * 100
            di = QTableWidgetItem(f"{sd:+.1f}%" if sd else "0.0%")
            di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if sd > 0.5:
                di.setForeground(QColor(theme.OK))
            elif sd < -0.5:
                di.setForeground(QColor(theme.ERR))
            tbl.setItem(ri, 3, di)

            # WR now
            wr_now = a.get("current_wr")
            wi = QTableWidgetItem(f"{wr_now*100:.1f}%" if wr_now else "\u2014")
            wi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 4, wi)

            # WR delta
            wd = a.get("wr_delta")
            wdi = QTableWidgetItem(f"{wd*100:+.1f}%" if wd else "\u2014")
            wdi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if wd and wd > 0.02:
                wdi.setForeground(QColor(theme.OK))
            elif wd and wd < -0.02:
                wdi.setForeground(QColor(theme.ERR))
            tbl.setItem(ri, 5, wdi)

            # Status
            st = a["status"]
            si = QTableWidgetItem(_STATUS_LABELS.get(st, st))
            si.setForeground(QColor(_STATUS_COLORS.get(st, theme.TEXT_DIM)))
            f = si.font()
            f.setBold(True)
            si.setFont(f)
            tbl.setItem(ri, 6, si)

        layout.addWidget(tbl, 1)
        dlg.exec()

    def _show_clusters(self):
        """Open the meta-clustering dialog for the current format."""
        fmt = self._fmt.currentText()
        if fmt == "all":
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Clusters",
                "Pick a specific format — clustering needs one format's "
                "average-deck data."
            )
            return
        from gui.widgets.cluster_dialog import MetaClusterDialog
        dlg = MetaClusterDialog(self, format_name=fmt)
        dlg.exec()

    def _show_recommendations(self):
        """Show deck recommendation dialog based on current meta matchup data."""
        fmt = self._fmt.currentText()
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1] or 4

        from analysis.deck_recommender import recommend_deck
        try:
            result = recommend_deck(fmt, top=12, weeks=weeks)
        except Exception as e:
            QMessageBox.warning(self, "Deck Recommendation", theme.friendly_error(e))
            return

        recs = result.get("recommendations", [])
        if not recs:
            QMessageBox.information(self, "Deck Recommendation", "Not enough data for recommendations.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Best Deck \u2014 {fmt.capitalize()}")
        dlg.setMinimumSize(750, 500)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        snap = QLabel(result.get("meta_snapshot", ""))
        snap.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; padding: 4px;")
        layout.addWidget(snap)

        tbl = QTableWidget(len(recs), 7)
        tbl.setHorizontalHeaderLabels([
            "Rank", "Archetype", "Score", "Matchup WR", "Raw WR", "Trend", "Verdict",
        ])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in range(2, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)

        _TREND_COLORS = {
            "rising": theme.OK, "falling": theme.ERR,
            "stable": theme.TEXT_DIM, "new": theme.ACCENT,
        }

        for ri, r in enumerate(recs):
            # Rank
            rank_item = QTableWidgetItem(f"#{ri + 1}")
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if ri == 0:
                rank_item.setForeground(QColor("#ffd700"))  # gold
                f = rank_item.font(); f.setBold(True); rank_item.setFont(f)
            tbl.setItem(ri, 0, rank_item)

            tbl.setItem(ri, 1, QTableWidgetItem(r["archetype"]))

            # Score
            sc = QTableWidgetItem(f"{r['score']:.0f}")
            sc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sc_clr = theme.OK if r["score"] >= 55 else (theme.WARN if r["score"] >= 50 else theme.ERR)
            sc.setForeground(QColor(sc_clr))
            f = sc.font(); f.setBold(True); sc.setFont(f)
            tbl.setItem(ri, 2, sc)

            # Matchup WR
            mu_wr = r.get("matchup_wr")
            mu = QTableWidgetItem(f"{mu_wr*100:.1f}%" if mu_wr else "\u2014")
            mu.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 3, mu)

            # Raw WR
            rw = QTableWidgetItem(f"{r['raw_wr']*100:.1f}%")
            rw.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 4, rw)

            # Trend
            trend = r.get("trend", "stable")
            tr = QTableWidgetItem(trend.capitalize())
            tr.setForeground(QColor(_TREND_COLORS.get(trend, theme.TEXT_DIM)))
            tr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 5, tr)

            # Verdict
            vi = QTableWidgetItem(r.get("verdict", ""))
            vi.setToolTip(
                f"Strengths: {', '.join(r.get('strengths', []))}\n"
                f"Weaknesses: {', '.join(r.get('weaknesses', []))}"
            )
            tbl.setItem(ri, 6, vi)

        layout.addWidget(tbl, 1)
        dlg.exec()



def _shorten_arch(name: str, max_len: int = 22) -> str:
    return name if len(name) <= max_len else name[:max_len - 1] + "\u2026"


# ---------------------------------------------------------------------------
# Dedup impact computation
# ---------------------------------------------------------------------------

def _compute_impact(standings: list, raw_standings) -> dict | None:
    """Compare filtered standings vs raw to produce a dedup impact summary.

    Returns None when raw_standings is None (no filters active).
    Returns a dict:
      total_raw      int
      total_dedup    int
      rows_removed   int
      pct_removed    float
      most_affected  list[dict]  — up to 3, each: archetype, raw, dedup, delta
      most_stable    dict | None — archetype with smallest removal (still present)
    """
    if raw_standings is None:
        return None

    total_raw   = sum(s["appearances"] for s in raw_standings)
    total_dedup = sum(s["appearances"] for s in standings)
    rows_removed = total_raw - total_dedup
    pct_removed  = rows_removed * 100 / total_raw if total_raw else 0.0

    raw_map   = {s["archetype"]: s["appearances"] for s in raw_standings}
    dedup_map = {s["archetype"]: s["appearances"] for s in standings}

    deltas = []
    for arch in set(raw_map) | set(dedup_map):
        r = raw_map.get(arch, 0)
        d = dedup_map.get(arch, 0)
        deltas.append({"archetype": arch, "raw": r, "dedup": d, "delta": r - d})

    deltas.sort(key=lambda x: -x["delta"])
    most_affected = [a for a in deltas if a["delta"] > 0][:3]

    # Most stable: present in both with the smallest (non-negative) delta
    stable = [a for a in reversed(deltas)
              if a["raw"] > 0 and a["dedup"] > 0 and a["delta"] >= 0]
    most_stable = stable[0] if stable else None

    return {
        "total_raw":     total_raw,
        "total_dedup":   total_dedup,
        "rows_removed":  rows_removed,
        "pct_removed":   round(pct_removed, 1),
        "most_affected": most_affected,
        "most_stable":   most_stable,
    }
