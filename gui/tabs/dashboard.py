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
    from datetime import datetime
    from analysis.win_rates import get_meta_standings
    from db.database import get_combined_connection

    standings = get_meta_standings(
        format_name=format_name, top=top, min_appearances=2, since=since_dt,
    )

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

    return {"standings": standings, "prior_standings": prior_standings, "recent": recent}


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


_SORT_ROLE = Qt.ItemDataRole.UserRole + 100


class _SortItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a numeric/string key stored in _SORT_ROLE."""
    def __lt__(self, other):
        a = self.data(_SORT_ROLE)
        b = other.data(_SORT_ROLE)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return super().__lt__(other)


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
        self._tf.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._tf.setFixedWidth(110)
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
            top_layout, "WIN RATE THIS WEEK", ["", "Archetype", "Win%", "Tier"])
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

        prior_map = {s["archetype"]: s for s in data.get("prior_standings", [])}
        self._populate_winrate(self._standings, prior_map)
        self._populate_popularity(self._standings, prior_map)
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
    _ROW_RISING  = QColor(18, 48, 22)   # dark green
    _ROW_FALLING = QColor(52, 18, 18)   # dark red

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

    def _populate_winrate(self, standings: list, prior_map: dict = None):
        tbl = self._winrate_tbl
        tbl.setSortingEnabled(False)
        top_n = int(self._top_n.currentText())
        ranked = sorted(
            [s for s in standings if s.get("est_match_winpct") is not None],
            key=lambda s: -s["est_match_winpct"],
        )[:top_n]

        total_apps  = sum(s["appearances"] for s in standings) or 1
        prior_total = (sum(p.get("appearances", 0) for p in prior_map.values()) or 1
                       if prior_map else 1)

        tbl.setRowCount(len(ranked))
        for ri, s in enumerate(ranked):
            ident = _color_identity(s["archetype"])
            tbl.setCellWidget(ri, 0, theme.make_pip_widget(ident))

            pct = s["est_match_winpct"] * 100
            bg  = self._trend_bg(s["archetype"], prior_map,
                                  s["est_match_winpct"], "est_match_winpct",
                                  threshold=0.02)

            arch_item = _set_cell(tbl, ri, 1, s["archetype"])
            if bg:
                arch_item.setBackground(bg)

            clr = QColor(theme.OK) if pct >= 55 else (
                  QColor(theme.WARN) if pct >= 50 else QColor(theme.ERR))
            pct_item = _SortItem(f"{pct:.1f}%")
            pct_item.setData(_SORT_ROLE, pct)
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            pct_item.setForeground(clr)
            pct_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if bg:
                pct_item.setBackground(bg)
            tbl.setItem(ri, 2, pct_item)

            # Tier badge
            meta_share  = s["appearances"] / total_apps
            prior_apps  = (prior_map[s["archetype"]].get("appearances", 0)
                           if prior_map and s["archetype"] in prior_map else 0)
            prior_share = prior_apps / prior_total if prior_map else meta_share
            is_declining = prior_map is not None and (meta_share - prior_share) < -0.005
            tier, tier_color = self._tier_badge(s["est_match_winpct"], meta_share, is_declining)
            tier_item = QTableWidgetItem(tier)
            tier_item.setForeground(tier_color)
            tier_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            tier_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            f = tier_item.font(); f.setBold(True); tier_item.setFont(f)
            if bg:
                tier_item.setBackground(bg)
            tbl.setItem(ri, 3, tier_item)

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
            tbl.item(ri, 2).setData(Qt.ItemDataRole.UserRole, r["archetype"])
            player = r.get("player", "") or ""
            _set_cell(tbl, ri, 3, player)
            event = r.get("event_name", "") or ""
            _set_cell(tbl, ri, 4, event[:28])

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
        return (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None


def _shorten_arch(name: str, max_len: int = 22) -> str:
    return name if len(name) <= max_len else name[:max_len - 1] + "\u2026"
