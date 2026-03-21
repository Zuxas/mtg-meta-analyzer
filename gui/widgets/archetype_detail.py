"""
ArchetypeDetailDialog — opens when a user clicks an archetype row.

Three tabs:
  1. Average Deck   — inclusion rate + avg copies for every card
  2. Recent Lists   — up to 5 latest tournament lists in a side-by-side grid
  3. Tech Choices   — cards in 15–80 % of lists (the flexible slots)

The heavy DB work runs in DataLoadWorker so the UI stays responsive.
"""
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QSplitter, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker
from gui.widgets.deck_export import show_export_menu


# ---------------------------------------------------------------------------
# Data loader (runs in background thread)
# ---------------------------------------------------------------------------

def _load_archetype_data(archetype: str, format_name: str, since_dt):
    """
    Single bulk DB query — returns everything the dialog needs.
    Returns None if no decks found.
    """
    from db.database import get_combined_connection

    conn = get_combined_connection()
    try:
        # ── All decks for this archetype ──────────────────────────────
        q = """
            SELECT d.id, d.archetype, d.player, d.placement,
                   e.date, e.name AS event_name, e.format
            FROM decks d
            JOIN events e ON e.id = d.event_id
            WHERE lower(d.archetype) LIKE lower(?)
              AND lower(e.format) = lower(?)
        """
        _date_key = (
            "CASE WHEN instr(e.date,'/')>0 "
            "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
            "ELSE replace(e.date,'-','') END"
        )
        params = [f"%{archetype}%", format_name]
        if since_dt:
            q += f" AND ({_date_key}) >= ?"
            params.append(since_dt.strftime("%Y%m%d"))
        q += f" ORDER BY ({_date_key}) DESC, d.placement ASC"
        deck_rows = conn.execute(q, params).fetchall()

        if not deck_rows:
            return None

        deck_ids = [r["id"] for r in deck_rows]
        total = len(deck_ids)

        # ── All cards for those decks ─────────────────────────────────
        ph = ",".join("?" * len(deck_ids))
        card_rows = conn.execute(f"""
            SELECT dc.deck_id, c.name, dc.quantity, dc.is_sideboard
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            WHERE dc.deck_id IN ({ph})
        """, deck_ids).fetchall()
    finally:
        conn.close()

    # ── Compute average deck ──────────────────────────────────────────
    appearances: dict = {}     # (name, is_sb) -> list[qty]
    for row in card_rows:
        key = (row["name"], bool(row["is_sideboard"]))
        appearances.setdefault(key, []).append(row["quantity"])

    mainboard, sideboard = [], []
    for (name, is_sb), qtys in appearances.items():
        inc = len(qtys) / total
        if inc < 0.10:
            continue
        avg_qty = sum(qtys) / len(qtys)
        entry = {
            "name": name,
            "inclusion_rate": round(inc, 3),
            "avg_qty": round(avg_qty, 2),
        }
        (sideboard if is_sb else mainboard).append(entry)

    mainboard.sort(key=lambda x: (-x["inclusion_rate"], x["name"]))
    sideboard.sort(key=lambda x: (-x["inclusion_rate"], x["name"]))

    # ── Build recent decks (up to 5) ──────────────────────────────────
    recent_ids = [r["id"] for r in deck_rows[:5]]
    recent_meta = {r["id"]: dict(r) for r in deck_rows[:5]}

    # Organise card rows by deck_id for the recent decks
    recent_id_set = set(recent_ids)
    deck_cards: dict = {}
    for row in card_rows:
        if row["deck_id"] not in recent_id_set:
            continue
        dk = deck_cards.setdefault(row["deck_id"], {"main": {}, "side": {}})
        zone = "side" if row["is_sideboard"] else "main"
        dk[zone][row["name"]] = row["quantity"]

    recent_decks = []
    for did in recent_ids:
        meta = recent_meta[did]
        cards = deck_cards.get(did, {"main": {}, "side": {}})
        recent_decks.append({
            "id": did,
            "player": meta["player"] or "Unknown",
            "placement": meta["placement"],
            "event_name": meta["event_name"],
            "date": meta["date"],
            "mainboard": cards["main"],
            "sideboard": cards["side"],
        })

    return {
        "archetype": archetype,
        "format": format_name,
        "deck_count": total,
        "mainboard": mainboard,
        "sideboard": sideboard,
        "recent_decks": recent_decks,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inc_color(rate: float) -> QColor:
    """Background tint for an inclusion-rate cell."""
    if rate >= 0.80:
        return QColor(30, 60, 40)    # dark green
    if rate >= 0.50:
        return QColor(50, 50, 20)    # dark yellow
    if rate >= 0.25:
        return QColor(60, 35, 15)    # dark orange
    return QColor(55, 25, 25)        # dark red (tech / fringe)


def _fmt_date(raw: str) -> str:
    """DD/MM/YY or YYYY-MM-DD → 'Mar 12'."""
    try:
        if "/" in raw:
            d, m, y = raw.split("/")
            dt = datetime(2000 + int(y), int(m), int(d))
        else:
            dt = datetime.fromisoformat(raw)
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return raw


def _placement_str(p: int) -> str:
    s = {1: "1st", 2: "2nd", 3: "3rd"}
    return s.get(p, f"{p}th")


# ---------------------------------------------------------------------------
# Sub-widgets
# ---------------------------------------------------------------------------

def _make_avg_table(mainboard: list, sideboard: list) -> QTableWidget:
    """QTableWidget showing the average deck card list."""
    cols = ["Card", "Incl %", "Avg Copies"]
    rows_data = []
    if mainboard:
        rows_data.append(("__header__", "MAINBOARD", None, None))
        for c in mainboard:
            rows_data.append(("card", c["name"], c["inclusion_rate"], c["avg_qty"]))
    if sideboard:
        rows_data.append(("__header__", "SIDEBOARD", None, None))
        for c in sideboard:
            rows_data.append(("card", c["name"], c["inclusion_rate"], c["avg_qty"]))

    tbl = QTableWidget(len(rows_data), 3)
    tbl.setHorizontalHeaderLabels(cols)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setAlternatingRowColors(False)
    tbl.verticalHeader().setVisible(False)
    hh = tbl.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    section_font = QFont()
    section_font.setBold(True)
    section_font.setPointSize(9)

    for row, (kind, name, rate, qty) in enumerate(rows_data):
        if kind == "__header__":
            item = QTableWidgetItem(name)
            item.setFont(section_font)
            item.setForeground(QColor(theme.ACCENT))
            item.setBackground(QColor(theme.PANEL))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            tbl.setItem(row, 0, item)
            for col in range(1, 3):
                cell = QTableWidgetItem("")
                cell.setBackground(QColor(theme.PANEL))
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tbl.setItem(row, col, cell)
            tbl.setRowHeight(row, 22)
        else:
            bg = _inc_color(rate)
            name_item = QTableWidgetItem(name)
            name_item.setBackground(bg)
            tbl.setItem(row, 0, name_item)

            pct_item = QTableWidgetItem(f"{rate*100:.0f}%")
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pct_item.setBackground(bg)
            tbl.setItem(row, 1, pct_item)

            qty_item = QTableWidgetItem(f"{qty:.2f}")
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_item.setBackground(bg)
            tbl.setItem(row, 2, qty_item)

    return tbl


def _make_recent_grid(recent_decks: list) -> QTableWidget:
    """
    Side-by-side grid: rows = unique card names, cols = each recent deck.
    Tech-choice rows (card not in all decks) get a highlighted background.
    """
    if not recent_decks:
        t = QTableWidget(1, 1)
        t.setItem(0, 0, QTableWidgetItem("No recent decklists found."))
        return t

    # Collect all unique mainboard card names ordered by frequency then alpha
    freq: dict = {}
    for dk in recent_decks:
        for name in dk["mainboard"]:
            freq[name] = freq.get(name, 0) + 1
    all_cards = sorted(freq, key=lambda n: (-freq[n], n))

    n_decks = len(recent_decks)
    tbl = QTableWidget(len(all_cards), n_decks + 1)

    # Column headers
    tbl.setHorizontalHeaderItem(0, QTableWidgetItem("Card"))
    for ci, dk in enumerate(recent_decks):
        raw = dk.get("date", "")
        try:
            if "/" in raw:
                d, m, y = raw.split("/")
                dt = datetime(2000 + int(y), int(m), int(d))
            else:
                dt = datetime.fromisoformat(raw)
            date_str = dt.strftime("%b %d").lstrip("0")
        except Exception:
            date_str = raw
        header = f"{_placement_str(dk['placement'])}\n{date_str}"
        tbl.setHorizontalHeaderItem(ci + 1, QTableWidgetItem(header))

    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.verticalHeader().setVisible(False)
    hh = tbl.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for ci in range(1, n_decks + 1):
        hh.setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)

    # Core card: in 80%+ of decks. Tech card: less.
    core_bg = QColor(theme.PANEL)
    tech_bg = QColor(50, 38, 20)    # warm tint for tech choices

    for ri, name in enumerate(all_cards):
        in_count = freq[name]
        is_tech = in_count < (n_decks * 0.80)
        bg = tech_bg if is_tech else core_bg

        name_item = QTableWidgetItem(name)
        name_item.setBackground(bg)
        tbl.setItem(ri, 0, name_item)

        for ci, dk in enumerate(recent_decks):
            qty = dk["mainboard"].get(name)
            cell = QTableWidgetItem(str(qty) if qty else "")
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setBackground(bg)
            if qty and is_tech:
                cell.setForeground(QColor(theme.WARN))
            tbl.setItem(ri, ci + 1, cell)

    return tbl


def _make_tech_table(mainboard: list) -> QWidget:
    """Cards with 15–80 % inclusion — the flexible/situational slots."""
    tech = [c for c in mainboard if 0.15 <= c["inclusion_rate"] <= 0.80]

    container = QWidget()
    vl = QVBoxLayout(container)
    vl.setContentsMargins(8, 8, 8, 8)

    if not tech:
        lbl = QLabel("No tech choices found — the list is very consistent.")
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        vl.addWidget(lbl)
        return container

    note = QLabel(
        "Cards appearing in 15–80 % of lists. "
        "These are the flexible slots that vary most between pilots."
    )
    note.setWordWrap(True)
    note.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
    vl.addWidget(note)

    tbl = QTableWidget(len(tech), 3)
    tbl.setHorizontalHeaderLabels(["Card", "Incl %", "Avg Copies"])
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setAlternatingRowColors(True)
    tbl.verticalHeader().setVisible(False)
    hh = tbl.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    for ri, c in enumerate(tech):
        name_i = QTableWidgetItem(c["name"])
        pct_i  = QTableWidgetItem(f"{c['inclusion_rate']*100:.0f}%")
        pct_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        qty_i  = QTableWidgetItem(f"{c['avg_qty']:.2f}")
        qty_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.setItem(ri, 0, name_i)
        tbl.setItem(ri, 1, pct_i)
        tbl.setItem(ri, 2, qty_i)

    vl.addWidget(tbl, 1)
    return container


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class ArchetypeDetailDialog(QDialog):
    """
    Opens when user clicks an archetype row in the dashboard table.
    Pass archetype name, format, and current timeframe in weeks.
    """

    _TIMEFRAME_OPTIONS = [
        ("2 weeks",  2),
        ("4 weeks",  4),
        ("8 weeks",  8),
        ("3 months", 13),
        ("6 months", 26),
        ("All time", None),
    ]

    def __init__(self, archetype: str, format_name: str,
                 initial_weeks: int = 8, parent=None):
        super().__init__(parent)
        self._archetype   = archetype
        self._format_name = format_name
        self._worker      = None
        self._data        = None   # populated by _on_data; used by export

        self.setWindowTitle(f"{archetype} — Deck Analysis")
        self.setMinimumSize(900, 620)
        self.resize(1000, 680)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()
        self._set_timeframe_by_weeks(initial_weeks)
        self._reload()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(54)
        header.setStyleSheet(
            f"background: {theme.PANEL}; border-bottom: 2px solid {theme.ACCENT};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)

        pip_w = theme.make_pip_widget(theme.color_identity(self._archetype))
        hl.addWidget(pip_w)

        title = QLabel(self._archetype)
        title.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 15px; font-weight: bold;"
            f" font-family: '{theme.HEADING_FONT}', Arial;"
        )
        hl.addWidget(title)
        hl.addStretch()

        hl.addWidget(QLabel("Timeframe:"))
        self._tf_combo = QComboBox()
        for label, _ in self._TIMEFRAME_OPTIONS:
            self._tf_combo.addItem(label)
        self._tf_combo.setFixedWidth(110)
        self._tf_combo.currentIndexChanged.connect(self._reload)
        hl.addWidget(self._tf_combo)

        self._deck_count_lbl = QLabel("")
        self._deck_count_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; margin-left: 16px;"
        )
        hl.addWidget(self._deck_count_lbl)

        self._export_btn = QPushButton("Export ▾")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setFixedHeight(26)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        hl.addWidget(self._export_btn)

        outer.addWidget(header)

        # ── Status bar (shown while loading) ─────────────────────────
        self._status_lbl = QLabel("Loading…")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; padding: 12px;"
        )
        outer.addWidget(self._status_lbl)

        # ── Tab widget (hidden until data loads) ──────────────────────
        self._tabs = QTabWidget()
        self._tabs.setVisible(False)
        outer.addWidget(self._tabs, 1)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _set_timeframe_by_weeks(self, weeks: int):
        """Pre-select the combo item closest to the given week count."""
        best_idx, best_diff = 0, 9999
        for i, (_, w) in enumerate(self._TIMEFRAME_OPTIONS):
            if w is None:
                continue
            diff = abs(w - weeks)
            if diff < best_diff:
                best_diff, best_idx = diff, i
        self._tf_combo.blockSignals(True)
        self._tf_combo.setCurrentIndex(best_idx)
        self._tf_combo.blockSignals(False)

    def _since_dt(self):
        weeks = self._TIMEFRAME_OPTIONS[self._tf_combo.currentIndex()][1]
        return (datetime.now() - timedelta(weeks=weeks)) if weeks else None

    def _reload(self):
        self._status_lbl.setText("Loading…")
        self._status_lbl.setVisible(True)
        self._tabs.setVisible(False)

        self._worker = DataLoadWorker(
            _load_archetype_data,
            {
                "archetype":   self._archetype,
                "format_name": self._format_name,
                "since_dt":    self._since_dt(),
            },
        )
        self._worker.result.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_export(self):
        if not self._data:
            return
        show_export_menu(
            self._export_btn,
            self._data["mainboard"],
            self._data["sideboard"],
            self._archetype,
            self._format_name,
            deck_count=self._data["deck_count"],
        )

    def _on_data(self, data):
        if data is None:
            self._status_lbl.setText(
                "No decklists found for this archetype in the selected timeframe."
            )
            return

        self._data = data
        self._export_btn.setEnabled(True)
        self._status_lbl.setVisible(False)
        self._deck_count_lbl.setText(f"{data['deck_count']:,} decks analysed")

        # Rebuild tabs (clear old ones first)
        self._tabs.blockSignals(True)
        while self._tabs.count():
            self._tabs.removeTab(0)

        # Tab 1 — Average Deck
        avg_tbl = _make_avg_table(data["mainboard"], data["sideboard"])
        self._tabs.addTab(avg_tbl, "Average Deck")

        # Tab 2 — Recent Lists
        grid = _make_recent_grid(data["recent_decks"])
        self._tabs.addTab(grid, f"Recent Lists ({len(data['recent_decks'])})")

        # Tab 3 — Tech Choices
        tech_widget = _make_tech_table(data["mainboard"])
        tech_count = len([c for c in data["mainboard"]
                          if 0.15 <= c["inclusion_rate"] <= 0.80])
        self._tabs.addTab(tech_widget, f"Tech Choices ({tech_count})")

        self._tabs.blockSignals(False)
        self._tabs.setVisible(True)

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"Error loading data: {msg}")
