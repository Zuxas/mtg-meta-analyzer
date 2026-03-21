"""
Tab 1 — Dashboard (Untapped.gg-inspired layout)

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
    QHeaderView, QScrollArea, QCheckBox, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from gui.widgets.chart_canvas import ChartCanvas, fetch_chart_data
from gui.worker_threads import DataLoadWorker
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

def _load_panel_data(format_name: str, since_dt, top: int) -> dict:
    """Load standings + recent top finishes for the three top panels."""
    from analysis.win_rates import get_meta_standings
    from db.database import get_combined_connection

    standings = get_meta_standings(
        format_name=format_name, top=top, min_appearances=2, since=since_dt,
    )

    conn = get_combined_connection()
    try:
        # Normalize dates to YYYYMMDD for correct ordering (MTGTop8=DD/MM/YY, MTGDecks=ISO)
        _date_key = (
            "CASE WHEN instr(e.date,'/')>0 "
            "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
            "ELSE replace(e.date,'-','') END"
        )
        q = """
            SELECT d.archetype, d.player, d.placement,
                   e.name AS event_name, e.date
            FROM decks d JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?) AND d.placement <= 4
        """
        params = [format_name]
        if since_dt:
            q += f" AND ({_date_key}) >= ?"
            params.append(since_dt.strftime("%Y%m%d"))
        q += f" ORDER BY ({_date_key}) DESC, d.placement ASC LIMIT 15"
        recent = [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()

    return {"standings": standings, "recent": recent}


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


def _placement_str(p: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(p, f"{p}th")


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

    _TIMEFRAME_OPTIONS = [
        ("2 weeks",  2),
        ("4 weeks",  4),
        ("8 weeks",  8),
        ("12 weeks", 12),
        ("6 months", 26),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_worker  = None
        self._chart_worker  = None
        self._chart_data    = None     # cached fetch_chart_data result
        self._chart_checks  = {}       # archetype -> QCheckBox
        self._chart_mode    = "meta_share"
        self._standings     = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Controls bar ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(110)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Timeframe:"))
        self._tf = QComboBox()
        for label, _ in self._TIMEFRAME_OPTIONS:
            self._tf.addItem(label)
        self._tf.setCurrentText("2 weeks")
        self._tf.setFixedWidth(100)
        ctrl.addWidget(self._tf)

        ctrl.addWidget(QLabel("Top N:"))
        self._top_n = QComboBox()
        self._top_n.addItems(["8", "12", "16", "20"])
        self._top_n.setCurrentText("12")
        self._top_n.setFixedWidth(60)
        ctrl.addWidget(self._top_n)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_primary())
        self._refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(self._refresh_btn)

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
            top_layout, "WIN RATE THIS WEEK", ["", "Archetype", "Win%"])
        self._pop_tbl, self._pop_hdr = self._build_ranked_panel(
            top_layout, "POPULAR THIS WEEK", ["", "Archetype", "Apps", "Meta%"])
        self._vsplit.addWidget(top_widget)

        # -- Bottom: chart + checkbox sidebar --------------------------
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(4)

        # Chart mode toggle
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._mode_pop_btn = QPushButton("Popularity Over Time")
        self._mode_win_btn = QPushButton("Win Rate Over Time")
        for btn in (self._mode_pop_btn, self._mode_win_btn):
            btn.setFixedHeight(26)
            btn.setStyleSheet(theme.btn_secondary())
        self._mode_pop_btn.clicked.connect(lambda: self._set_chart_mode("meta_share"))
        self._mode_win_btn.clicked.connect(lambda: self._set_chart_mode("win_pct"))
        mode_row.addWidget(self._mode_pop_btn)
        mode_row.addWidget(self._mode_win_btn)
        mode_row.addStretch()
        bl.addLayout(mode_row)

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
        sidebar_vl.setSpacing(4)

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
        frame, tbl, _ = self._panel_frame("RECENT TOP FINISHES",
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
        frame, tbl, hdr_lbl = self._panel_frame(title, cols)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, len(cols)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        tbl.itemDoubleClicked.connect(self._on_ranked_dblclick)
        tbl.itemClicked.connect(self._on_ranked_dblclick)
        parent_layout.addWidget(frame)
        return tbl, hdr_lbl

    def _panel_frame(self, title: str, cols: list):
        """Return (QFrame, QTableWidget, header_QLabel) for a titled panel."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            f" border-radius: 3px; }}"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        hdr = QLabel(f"  {title}")
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.ACCENT}; font-size: 10px;"
            f" font-weight: bold; letter-spacing: 1px;"
            f" border-bottom: 1px solid {theme.BORDER};"
            f" font-family: '{theme.HEADING_FONT}', Arial;"
        )
        fl.addWidget(hdr)

        tbl = _make_panel_table(cols)
        fl.addWidget(tbl, 1)
        return frame, tbl, hdr

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self):
        self._status_lbl.setText("Loading…")
        self._refresh_btn.setEnabled(False)
        self._canvas.show_message("Loading chart data…", theme.ACCENT)

        fmt   = self._fmt.currentText()
        top   = int(self._top_n.currentText())
        since = self._since_dt()

        self._panel_worker = DataLoadWorker(
            _load_panel_data,
            # Fetch top=50 so high-frequency archetypes (e.g. Izzet Prowess) aren't
            # excluded by performance-based ranking; display is limited to top N below.
            {"format_name": fmt, "since_dt": since, "top": 50},
        )
        self._panel_worker.result.connect(self._on_panel_data)
        self._panel_worker.error.connect(self._on_error)
        self._panel_worker.finished.connect(
            lambda: self._refresh_btn.setEnabled(True)
        )
        self._panel_worker.start()

        # Load chart data separately (slower — one trend query per archetype)
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        self._chart_worker = DataLoadWorker(
            fetch_chart_data,
            {"format_name": fmt, "top": top, "weeks": weeks,
             "since": since, "until": None, "standings": None},
        )
        self._chart_worker.result.connect(self._on_chart_data)
        self._chart_worker.error.connect(
            lambda e: self._canvas.show_message(f"Chart error: {e}", theme.ERR)
        )
        self._chart_worker.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_panel_data(self, data: dict):
        self._standings = data["standings"]
        n = len(self._standings)
        self._status_lbl.setText(f"{n} archetype{'s' if n != 1 else ''} loaded")

        # Update panel titles to reflect the current timeframe
        tf_label = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
        self._winrate_hdr.setText(f"  WIN RATE — {tf_label.upper()}")
        self._pop_hdr.setText(f"  POPULAR — {tf_label.upper()}")

        self._populate_winrate(self._standings)
        self._populate_popularity(self._standings)
        self._populate_recent(data["recent"])

    def _on_chart_data(self, data):
        self._chart_data = data
        self._rebuild_checkboxes(data["archetypes"] if data else [])
        self._canvas.draw_from_data(data, mode=self._chart_mode)

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"Error: {msg}")

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
        arch_item = self._recent_tbl.item(self._recent_tbl.currentRow(), 2)
        if arch_item:
            raw = arch_item.data(Qt.ItemDataRole.UserRole) or arch_item.text()
            self._open_detail(raw)

    def _open_detail(self, archetype: str):
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        dlg = ArchetypeDetailDialog(
            archetype=archetype,
            format_name=self._fmt.currentText(),
            initial_weeks=weeks,
            parent=self,
        )
        dlg.exec()

    # ------------------------------------------------------------------
    # Panel population
    # ------------------------------------------------------------------

    def _populate_winrate(self, standings: list):
        tbl = self._winrate_tbl
        top_n = int(self._top_n.currentText())
        ranked = sorted(
            [s for s in standings if s.get("est_match_winpct") is not None],
            key=lambda s: -s["est_match_winpct"],
        )[:top_n]
        tbl.setRowCount(len(ranked))
        for ri, s in enumerate(ranked):
            ident = _color_identity(s["archetype"])
            tbl.setCellWidget(ri, 0, theme.make_pip_widget(ident))
            _set_cell(tbl, ri, 1, s["archetype"])
            pct = s["est_match_winpct"] * 100
            clr = QColor(theme.OK) if pct >= 55 else (
                  QColor(theme.WARN) if pct >= 50 else QColor(theme.ERR))
            _set_cell(tbl, ri, 2, f"{pct:.1f}%",
                      align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                      fg=clr)
        tbl.resizeRowsToContents()

    def _populate_popularity(self, standings: list):
        tbl = self._pop_tbl
        top_n = int(self._top_n.currentText())
        ranked = sorted(standings, key=lambda s: -s["appearances"])[:top_n]
        total_apps = sum(s["appearances"] for s in standings) or 1  # use full list for accurate %
        tbl.setRowCount(len(ranked))
        for ri, s in enumerate(ranked):
            ident = _color_identity(s["archetype"])
            tbl.setCellWidget(ri, 0, theme.make_pip_widget(ident))
            _set_cell(tbl, ri, 1, s["archetype"])
            _set_cell(tbl, ri, 2, str(s["appearances"]),
                      align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            meta_pct = s["appearances"] / total_apps * 100
            _set_cell(tbl, ri, 3, f"{meta_pct:.1f}%",
                      align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        tbl.resizeRowsToContents()

    def _populate_recent(self, recent: list):
        # Columns: 0=Pl, 1=Colors(pip), 2=Archetype, 3=Player, 4=Event, 5=Date
        tbl = self._recent_tbl
        tbl.setRowCount(len(recent))
        for ri, r in enumerate(recent):
            pl  = r["placement"]
            clr = (QColor(theme.ACCENT) if pl == 1 else
                   QColor(theme.ACCENT2) if pl == 2 else
                   QColor(theme.TEXT))
            _set_cell(tbl, ri, 0, _placement_str(pl), fg=clr, bold=(pl == 1))
            ident = _color_identity(r["archetype"])
            tbl.setCellWidget(ri, 1, theme.make_pip_widget(ident))
            _set_cell(tbl, ri, 2, r["archetype"])
            tbl.item(ri, 2).setData(Qt.ItemDataRole.UserRole, r["archetype"])
            player = r.get("player", "") or ""
            _set_cell(tbl, ri, 3, player)
            event = r.get("event_name", "") or ""
            _set_cell(tbl, ri, 4, event[:28])
            _set_cell(tbl, ri, 5, _fmt_date(r.get("date", "")))
        tbl.resizeRowsToContents()

    # ------------------------------------------------------------------
    # Chart checkbox sidebar
    # ------------------------------------------------------------------

    def _rebuild_checkboxes(self, archetypes: list):
        """Rebuild the checkbox list when archetypes change."""
        # Remove old checkboxes
        self._chart_checks.clear()
        while self._check_layout.count() > 1:  # keep the trailing stretch
            item = self._check_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        palette = __import__("gui.theme", fromlist=["CHART_PALETTE"]).CHART_PALETTE
        for i, arch in enumerate(archetypes):
            color_hex = palette[i % len(palette)]
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_hl = QHBoxLayout(row_widget)
            row_hl.setContentsMargins(2, 0, 2, 0)
            row_hl.setSpacing(4)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color_hex}; font-size: 10px; background: transparent;")
            dot.setFixedWidth(14)
            row_hl.addWidget(dot)

            cb = QCheckBox(_shorten_arch(arch))
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {theme.TEXT}; font-size: 11px; background: transparent;")
            cb.stateChanged.connect(self._on_checkbox_changed)
            row_hl.addWidget(cb, 1)

            self._check_layout.insertWidget(self._check_layout.count() - 1, row_widget)
            self._chart_checks[arch] = cb

    def _on_checkbox_changed(self):
        if self._chart_data:
            visible = {a for a, cb in self._chart_checks.items() if cb.isChecked()}
            self._canvas.draw_from_data(self._chart_data, visible, mode=self._chart_mode)

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
            self._canvas.draw_from_data(self._chart_data, visible, mode=mode)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _since_dt(self):
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        return datetime.now() - timedelta(weeks=weeks)


def _shorten_arch(name: str, max_len: int = 22) -> str:
    return name if len(name) <= max_len else name[:max_len - 1] + "\u2026"
