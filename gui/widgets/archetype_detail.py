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
                   e.date, e.name AS event_name, e.format,
                   e.id AS event_id, e.url AS event_url
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
            "event_id": meta.get("event_id"),
            "event_url": meta.get("event_url", ""),
            "mainboard": cards["main"],
            "sideboard": cards["side"],
        })

    # ── Guides for this archetype ─────────────────────────────────────
    # Match on archetype name (bidirectional partial, case-insensitive).
    # Format priority: Standard=1, Modern=2, Pioneer=3, Legacy=4, rest=5.
    # ── Guides + bookmarks for this archetype ────────────────────────
    _fmt_order = (
        "CASE lower(format) WHEN 'standard' THEN 1 "
        "WHEN 'modern' THEN 2 WHEN 'pioneer' THEN 3 "
        "WHEN 'legacy' THEN 4 ELSE 5 END"
    )
    _arch_match = (
        "lower(archetype) LIKE lower('%' || ? || '%') "
        "OR lower(?) LIKE lower('%' || archetype || '%')"
    )
    resources = []
    try:
        conn2 = get_combined_connection()
        guide_rows = conn2.execute(f"""
            SELECT date AS date_str, url, format, archetype,
                   type, author AS title, source, comment, 'guide' AS origin
            FROM guides
            WHERE {_arch_match}
            ORDER BY {_fmt_order}, (CASE WHEN instr(date,'/')>0 AND length(date)=10
                THEN substr(date,7,4)||substr(date,4,2)||substr(date,1,2)
                WHEN instr(date,'/')>0
                THEN '20'||substr(date,7,2)||substr(date,4,2)||substr(date,1,2)
                ELSE replace(date,'-','') END) DESC
        """, [archetype, archetype]).fetchall()
        bm_rows = conn2.execute(f"""
            SELECT added_at AS date_str, url, format, archetype,
                   type, title, '' AS source, note AS comment, 'bookmark' AS origin
            FROM bookmarks
            WHERE {_arch_match}
            ORDER BY {_fmt_order}, added_at DESC
        """, [archetype, archetype]).fetchall()
        conn2.close()
        # Bookmarks first (manually curated), then scraped guides
        resources = [dict(r) for r in bm_rows] + [dict(r) for r in guide_rows]
    except Exception:
        resources = []

    return {
        "archetype": archetype,
        "format": format_name,
        "deck_count": total,
        "mainboard": mainboard,
        "sideboard": sideboard,
        "recent_decks": recent_decks,
        "resources": resources,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from gui.widgets.table_helpers import NumItem as _NumItem


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
    tbl.setSortingEnabled(True)
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


def _make_resources_tab(resources: list) -> QWidget:
    """
    Clickable table of guides and manual bookmarks for this archetype.
    Bookmarks (manually saved) shown first, then scraped guides.
    """
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    _TYPE_COLOR = {
        "guide":          QColor(30,  60, 40),
        "primer":         QColor(25,  40, 65),
        "sideboard guide":QColor(55,  35, 15),
        "tweet":          QColor(20,  45, 60),
        "article":        QColor(40,  35, 55),
        "video":          QColor(55,  28, 28),
        "deck tech":      QColor(40,  50, 20),
    }

    container = QWidget()
    vl = QVBoxLayout(container)
    vl.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
    vl.setSpacing(6)

    if not resources:
        lbl = QLabel(
            "No guides or bookmarks found for this archetype.\n\n"
            "• Run  python -m scrapers.guides  to import the Skill Issue Magic database.\n"
            "• Use the Knowledge Base tab to bookmark tweets or articles."
        )
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        lbl.setWordWrap(True)
        vl.addWidget(lbl)
        return container

    bm_count = sum(1 for r in resources if r.get("origin") == "bookmark")
    g_count  = len(resources) - bm_count
    parts = []
    if bm_count:
        parts.append(f"{bm_count} bookmark{'s' if bm_count != 1 else ''}")
    if g_count:
        parts.append(f"{g_count} guide{'s' if g_count != 1 else ''}")
    note = QLabel(
        ", ".join(parts) + " — click any row to open in browser. "
        "★ = manually bookmarked."
    )
    note.setWordWrap(True)
    note.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
    vl.addWidget(note)

    tbl = QTableWidget(len(resources), 5)
    tbl.setHorizontalHeaderLabels(["Title / Description", "Format", "Type", "Author / Source", "Date"])
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.verticalHeader().setVisible(False)
    tbl.setAlternatingRowColors(False)
    tbl.setCursor(Qt.CursorShape.PointingHandCursor)
    tbl.setToolTip("Click a row to open in your browser")
    tbl.setSortingEnabled(True)
    hh = tbl.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

    for row, r in enumerate(resources):
        origin  = r.get("origin", "guide")
        is_bm   = origin == "bookmark"
        title   = r.get("title")   or r.get("comment") or r.get("archetype") or "—"
        if is_bm:
            title = f"★ {title}"
        fmt     = (r.get("format")  or "—").capitalize()
        rtype   = r.get("type")     or "—"
        author  = r.get("title")    if not is_bm else ""
        source  = r.get("source")   or ""
        credit  = " / ".join(x for x in [author, source] if x) or "—"
        date    = (r.get("date_str") or "")[:10]
        url     = r.get("url") or ""
        comment = r.get("comment") or ""
        tooltip = f"{title}\n{comment}\n{url}".strip()

        base = _TYPE_COLOR.get(rtype.lower(), QColor(40, 40, 52))
        if is_bm:
            tint = QColor(min(base.red()+15,255), min(base.green()+15,255), min(base.blue()+20,255))
        else:
            tint = base

        for ci, text in enumerate([title, fmt, rtype, credit, date]):
            item = QTableWidgetItem(text)
            item.setBackground(tint)
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, url)
            tbl.setItem(row, ci, item)

    def _open(item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    tbl.itemClicked.connect(_open)
    tbl.sortByColumn(4, Qt.SortOrder.DescendingOrder)
    vl.addWidget(tbl)
    return container


def _classify_card_role(type_line: str, oracle_text: str) -> str:
    """Classify a card into a competitive role based on type line and oracle text."""
    tl = (type_line or "").lower()
    ot = (oracle_text or "").lower()

    # Lands
    if "land" in tl:
        return "Mana"

    # Removal / interaction
    removal_keywords = [
        "destroy target", "exile target", "deals damage to",
        "counter target", "return target", "-x/-x", "gets -",
        "sacrifice a", "destroy all", "exile all",
    ]
    if any(kw in ot for kw in removal_keywords):
        return "Removal"

    # Card advantage / selection
    draw_keywords = [
        "draw a card", "draw two", "draw cards", "scry",
        "look at the top", "search your library", "surveil",
    ]
    if any(kw in ot for kw in draw_keywords):
        # Creatures that also draw are threats
        if "creature" in tl or "planeswalker" in tl:
            return "Threat"
        return "Card Advantage"

    # Threats: creatures, planeswalkers, vehicles
    if "creature" in tl or "planeswalker" in tl or "vehicle" in tl:
        return "Threat"

    # Protection / combat tricks
    protect_keywords = [
        "hexproof", "indestructible", "protection from",
        "can't be countered", "ward",
    ]
    if any(kw in ot for kw in protect_keywords):
        return "Protection"

    # Enchantments / artifacts that buff or generate value
    return "Utility"


def _get_card_roles(card_names: list) -> dict:
    """Look up card_data for a list of card names, return {name: role}."""
    if not card_names:
        return {}
    try:
        from db.database import get_connection
        conn = get_connection()
        try:
            ph = ",".join("?" * len(card_names))
            rows = conn.execute(f"""
                SELECT name, type_line, oracle_text
                FROM card_data WHERE name IN ({ph})
            """, card_names).fetchall()
        finally:
            conn.close()
        return {
            r["name"]: _classify_card_role(r["type_line"], r["oracle_text"])
            for r in rows
        }
    except Exception:
        return {}


_ROLE_COLORS = {
    "Threat":         "#3cb44b",  # green
    "Removal":        "#e6194b",  # red
    "Card Advantage": "#42a5f5",  # blue
    "Mana":           "#f58231",  # orange
    "Protection":     "#ffe119",  # yellow
    "Utility":        "#aaaaaa",  # grey
}


def _make_tech_table(mainboard: list) -> QWidget:
    """Cards with 15–80 % inclusion — the flexible/situational slots, grouped by role."""
    tech = [c for c in mainboard if 0.15 <= c["inclusion_rate"] <= 0.80]

    container = QWidget()
    vl = QVBoxLayout(container)
    vl.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)

    if not tech:
        lbl = QLabel("No tech choices found — the list is very consistent.")
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        vl.addWidget(lbl)
        return container

    note = QLabel(
        "Flex slots (15\u201380% inclusion) grouped by role. "
        "Cards in the same role group compete for the same slots."
    )
    note.setWordWrap(True)
    note.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
    vl.addWidget(note)

    # Look up roles from card_data
    card_names = [c["name"] for c in tech]
    roles = _get_card_roles(card_names)

    # Assign role to each tech card
    for c in tech:
        c["role"] = roles.get(c["name"], "Utility")

    # Sort by role then inclusion
    role_order = ["Threat", "Removal", "Card Advantage", "Mana", "Protection", "Utility"]
    tech.sort(key=lambda c: (
        role_order.index(c["role"]) if c["role"] in role_order else 99,
        -c["inclusion_rate"],
    ))

    tbl = QTableWidget(len(tech), 4)
    tbl.setHorizontalHeaderLabels(["Role", "Card", "Incl %", "Avg Copies"])
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setAlternatingRowColors(True)
    tbl.verticalHeader().setVisible(False)
    tbl.setSortingEnabled(True)
    hh = tbl.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

    tbl.setSortingEnabled(False)
    for ri, c in enumerate(tech):
        role = c["role"]
        role_i = QTableWidgetItem(role)
        role_color = _ROLE_COLORS.get(role, "#aaaaaa")
        role_i.setForeground(QColor(role_color))
        f = role_i.font()
        f.setBold(True)
        role_i.setFont(f)
        tbl.setItem(ri, 0, role_i)

        name_i = QTableWidgetItem(c["name"])
        tbl.setItem(ri, 1, name_i)

        pct_i = _NumItem(f"{c['inclusion_rate']*100:.0f}%")
        pct_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.setItem(ri, 2, pct_i)

        qty_i = _NumItem(f"{c['avg_qty']:.2f}")
        qty_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.setItem(ri, 3, qty_i)

    tbl.setSortingEnabled(True)
    tbl.sortByColumn(0, Qt.SortOrder.AscendingOrder)
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

    _TIMEFRAME_OPTIONS = theme.TIMEFRAME_OPTIONS

    def __init__(self, archetype: str, format_name: str,
                 initial_weeks: int | None = 2, parent=None,
                 deck_id: int = None, on_simulate=None):
        super().__init__(parent)
        self._archetype   = archetype
        self._format_name = format_name
        self._worker      = None
        self._data        = None   # populated by _on_data; used by export
        self._deck_id     = deck_id  # specific deck to show in "This List" tab
        self._on_simulate = on_simulate

        self.setWindowTitle(f"{archetype} — Deck Analysis")
        self.setMinimumSize(*theme.DIALOG_LG)
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

        self._event_btn = QPushButton("View Event")
        self._event_btn.setStyleSheet(theme.btn_secondary())
        self._event_btn.setFixedHeight(26)
        self._event_btn.setEnabled(False)
        self._event_btn.setVisible(self._deck_id is not None)
        self._event_btn.clicked.connect(self._on_view_event)
        hl.addWidget(self._event_btn)

        self._export_btn = QPushButton("Export ▾")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setFixedHeight(26)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        hl.addWidget(self._export_btn)

        # Simulate the consensus 75 — only shown when a callback is wired.
        if self._on_simulate is not None:
            self._sim_btn = QPushButton("Simulate ▸")
            self._sim_btn.setStyleSheet(theme.btn_secondary())
            self._sim_btn.setFixedHeight(26)
            self._sim_btn.setToolTip(
                f"Send the consensus '{self._archetype}' deck to SIMULATE."
            )
            self._sim_btn.clicked.connect(self._on_send_to_simulate)
            hl.addWidget(self._sim_btn)

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

    def _set_timeframe_by_weeks(self, weeks: int | None):
        """Pre-select the combo item closest to the given week count (None = All Time)."""
        self._tf_combo.blockSignals(True)
        if weeks is None:
            idx = next(
                (i for i, (_, w) in enumerate(self._TIMEFRAME_OPTIONS) if w is None),
                len(self._TIMEFRAME_OPTIONS) - 1,
            )
            self._tf_combo.setCurrentIndex(idx)
        else:
            best_idx, best_diff = 0, 9999
            for i, (_, w) in enumerate(self._TIMEFRAME_OPTIONS):
                if w is None:
                    continue
                diff = abs(w - weeks)
                if diff < best_diff:
                    best_diff, best_idx = diff, i
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

    def _on_send_to_simulate(self):
        """Compute the archetype's avg deck and dispatch to SIMULATE."""
        try:
            from analysis.deck_analysis import get_average_deck
            avg = get_average_deck(self._archetype,
                                   format_name=self._format_name)
            if not avg:
                # Status bar fallback
                if hasattr(self, "_status_lbl"):
                    self._status_lbl.setText(
                        f"No deck data available for {self._archetype} "
                        f"({self._format_name}) — can't build an average deck."
                    )
                return

            lines = []
            for entry in avg.get("mainboard", []):
                qty = entry.get("suggested_qty") or 0
                name = entry.get("name")
                if qty > 0 and name:
                    lines.append(f"{qty} {name}")
            sb = avg.get("sideboard") or []
            if sb:
                lines.append("")
                lines.append("Sideboard")
                for entry in sb:
                    qty = entry.get("suggested_qty") or 0
                    name = entry.get("name")
                    if qty > 0 and name:
                        lines.append(f"{qty} {name}")
            text = "\n".join(lines)
            n_decks = avg.get("deck_count", 0)
            source = f"{self._archetype} avg (from {n_decks} decks)"
            if self._on_simulate:
                self._on_simulate(text, source, format_hint=self._format_name)
                self.accept()
        except Exception as e:
            if hasattr(self, "_status_lbl"):
                self._status_lbl.setText(f"Simulate failed: {e}")

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

    def _on_view_event(self):
        info = getattr(self, "_event_info", None)
        if not info:
            return
        from gui.widgets.event_peers import EventPeersDialog
        dlg = EventPeersDialog(
            event_id=info["event_id"],
            event_name=info.get("event_name", ""),
            event_url=info.get("event_url", ""),
            parent=self,
        )
        dlg.exec()

    def _on_data(self, data):
        if data is None:
            self._status_lbl.setText(
                "No decklists found for this archetype in the selected timeframe."
            )
            return

        self._data = data
        self._export_btn.setEnabled(True)
        # Enable "View Event" if we can find this deck's event
        if self._deck_id is not None:
            for rd in data.get("recent_decks", []):
                if rd.get("id") == self._deck_id and rd.get("event_id"):
                    self._event_info = {
                        "event_id": rd["event_id"],
                        "event_name": rd.get("event_name", ""),
                        "event_url": rd.get("event_url", ""),
                    }
                    self._event_btn.setEnabled(True)
                    break
        self._status_lbl.setVisible(False)
        self._deck_count_lbl.setText(f"{data['deck_count']:,} decks analysed")

        # Rebuild tabs (clear old ones first)
        self._tabs.blockSignals(True)
        while self._tabs.count():
            self._tabs.removeTab(0)

        # Tab 0 — This List (specific deck from Recent Top Finishes click)
        if self._deck_id is not None:
            this_tab = self._make_this_list_tab(self._deck_id)
            if this_tab is not None:
                self._tabs.addTab(this_tab, "This List")

        # Tab 1 — Average Deck (with card image tooltips on hover)
        avg_tbl = _make_avg_table(data["mainboard"], data["sideboard"])
        from gui.widgets.card_tooltip import install_card_tooltip
        install_card_tooltip(avg_tbl, card_name_column=0)
        self._tabs.addTab(avg_tbl, "Average Deck")

        # Tab 2 — Recent Lists
        grid = _make_recent_grid(data["recent_decks"])
        self._tabs.addTab(grid, f"Recent Lists ({len(data['recent_decks'])})")

        # Tab 3 — Tech Choices (with card image tooltips)
        tech_widget = _make_tech_table(data["mainboard"])
        tech_count = len([c for c in data["mainboard"]
                          if 0.15 <= c["inclusion_rate"] <= 0.80])
        self._tabs.addTab(tech_widget, f"Tech Choices ({tech_count})")

        # Tab 4 — Card Trends (adoption changes)
        trend_tab = self._make_card_trends_tab(data["mainboard"], data["sideboard"])
        if trend_tab:
            self._tabs.addTab(trend_tab, "Card Trends")

        # Tab 5 — Resources (guides + bookmarks)
        resources    = data.get("resources", [])
        res_tab      = _make_resources_tab(resources)
        res_label    = f"Resources ({len(resources)})" if resources else "Resources"
        self._tabs.addTab(res_tab, res_label)

        self._tabs.blockSignals(False)
        self._tabs.setVisible(True)

    def _make_card_trends_tab(self, mainboard, sideboard):
        """Compare card inclusion rates: recent half vs older half of available data."""
        all_cards = mainboard + sideboard
        if len(all_cards) < 5:
            return None

        # Split data conceptually: we have inclusion rates from the full period.
        # To show trends, we load a second dataset from a narrower recent window.
        try:
            from gui.widgets.archetype_detail import _load_archetype_data
            from datetime import datetime, timedelta
            # Recent = last 2 weeks
            recent_since = datetime.now() - timedelta(weeks=2)
            recent_data = _load_archetype_data(
                self._archetype, self._format_name, since_dt=recent_since)
            if not recent_data or not recent_data.get("mainboard"):
                return None
        except Exception:
            return None

        # Build lookup: card name → recent inclusion rate
        recent_rates = {}
        for c in recent_data["mainboard"] + recent_data.get("sideboard", []):
            recent_rates[c["name"]] = c["inclusion_rate"]

        # Compare full-period vs recent
        changes = []
        for c in all_cards:
            name = c["name"]
            full_rate = c["inclusion_rate"]
            recent_rate = recent_rates.get(name, 0)
            delta = recent_rate - full_rate
            if abs(delta) >= 0.05:  # only show 5%+ changes
                changes.append((name, full_rate, recent_rate, delta))

        if not changes:
            return None

        changes.sort(key=lambda x: -x[3])  # biggest gainers first

        tbl = QTableWidget(len(changes), 4)
        tbl.setHorizontalHeaderLabels(["Card", "Overall Incl%", "Recent Incl%", "Change"])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)

        for ri, (name, full, recent, delta) in enumerate(changes):
            tbl.setItem(ri, 0, QTableWidgetItem(name))
            fi = QTableWidgetItem(f"{full*100:.0f}%")
            fi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 1, fi)
            ri_item = QTableWidgetItem(f"{recent*100:.0f}%")
            ri_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 2, ri_item)
            di = QTableWidgetItem(f"{delta*100:+.0f}%")
            di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if delta > 0:
                di.setForeground(QColor(theme.OK))
            elif delta < 0:
                di.setForeground(QColor(theme.ERR))
            tbl.setItem(ri, 3, di)

        from gui.widgets.card_tooltip import install_card_tooltip
        install_card_tooltip(tbl, card_name_column=0)
        return tbl

    def _make_this_list_tab(self, deck_id: int):
        """Build a tab showing the exact 75 for a specific deck ID."""
        try:
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT c.name, dc.quantity, dc.is_sideboard
                    FROM deck_cards dc
                    JOIN cards c ON c.id = dc.card_id
                    WHERE dc.deck_id = ?
                    ORDER BY dc.is_sideboard ASC, dc.quantity DESC, c.name ASC
                """, (deck_id,)).fetchall()
            finally:
                conn.close()
        except Exception:
            return None

        if not rows:
            return None

        from PyQt6.QtWidgets import QTextEdit
        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            f"background: {theme.BG}; color: #f0f0f0; "
            f"font-family: Consolas, monospace; font-size: 12px; "
            f"border: none; padding: 12px;"
        )

        lines = []
        main_total = side_total = 0
        in_side = False
        for r in rows:
            if r["is_sideboard"] and not in_side:
                in_side = True
                lines.append("")
                lines.append("Sideboard")
            qty = r["quantity"]
            if r["is_sideboard"]:
                side_total += qty
            else:
                main_total += qty
            lines.append(f"{qty} {r['name']}")

        header = f"// Exact list ({main_total} main"
        if side_total:
            header += f" / {side_total} side"
        header += ")\n"
        text.setPlainText(header + "\n".join(lines))
        return text

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"Error loading data: {msg}")
