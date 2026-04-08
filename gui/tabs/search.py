"""
Tab 3 — Search
  Sub-tabs: Card Lookup | Deck Search | Head-to-Head
"""
import os
import re
import sqlite3
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextBrowser, QTextEdit, QComboBox, QFrame, QSplitter,
    QDialog, QDialogButtonBox, QScrollArea, QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap, QColor

from gui.worker_threads import DataLoadWorker
import gui.theme as theme


# ---------------------------------------------------------------------------
# Card image helpers  (unchanged)
# ---------------------------------------------------------------------------

def _card_image_cache_path(card_name: str) -> str:
    here = os.path.dirname(__file__)
    cache_dir = os.path.normpath(os.path.join(here, "..", "..", "data", "card_images"))
    os.makedirs(cache_dir, exist_ok=True)
    safe = card_name.replace("/", "_").replace(":", "_").replace("?", "_")
    return os.path.join(cache_dir, f"{safe}.jpg")


def _fetch_card_image(card_name: str) -> str | None:
    path = _card_image_cache_path(card_name)
    if os.path.exists(path):
        return path
    try:
        import requests
        from urllib.parse import quote
        r = requests.get(
            f"https://api.scryfall.com/cards/named?exact={quote(card_name)}",
            timeout=10,
            headers={"User-Agent": "MTGMetaAnalyzer/1.0"},
        )
        if r.status_code != 200:
            return None
        uris = r.json().get("image_uris", {})
        img_url = uris.get("normal") or uris.get("large") or uris.get("small")
        if not img_url:
            return None
        ir = requests.get(img_url, timeout=15)
        if ir.status_code == 200:
            with open(path, "wb") as f:
                f.write(ir.content)
            return path
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _btn(text, style="primary"):
    w = QPushButton(text)
    w.setStyleSheet(theme.btn_primary() if style == "primary" else theme.btn_secondary())
    return w


from gui.widgets.table_helpers import NumItem as _NumItem, DateItem as _DateItem, date_sort_key as _date_sort_key


_DATE_KEY = (
    "CASE WHEN instr(e.date,'/')>0 "
    "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
    "ELSE replace(e.date,'-','') END"
)

_PLACEMENT_FILTERS = {
    "Any placement": None,
    "1st place":     1,
    "Top 4":         4,
    "Top 8":         8,
    "Top 16":        16,
}


# ---------------------------------------------------------------------------
# Deck detail dialog — shows exact registered 75 for one deck_id
# ---------------------------------------------------------------------------

class _DeckDetailDialog(QDialog):
    def __init__(self, deck_id: int, archetype: str, player: str,
                 placement, event: str, date: str, fmt: str, parent=None):
        super().__init__(parent)
        self._deck_id   = deck_id
        self._archetype = archetype
        self._player    = player
        self._fmt       = fmt
        self._workers   = []

        title = f"{archetype}  —  {player or 'Unknown'}  (#{placement})"
        self.setWindowTitle(title)
        self.setMinimumSize(680, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(f"<b>{archetype}</b>  ·  {player or '—'}  ·  "
                     f"Placement: <b>{placement}</b>  ·  {event}  ·  {date}")
        hdr.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        layout.addWidget(sep)

        # Deck list area: two columns (mainboard | sideboard)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._main_browser = QTextBrowser()
        self._main_browser.setFont(QFont("Consolas", 10))
        self._main_browser.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 3px;"
        )
        splitter.addWidget(self._main_browser)

        self._side_browser = QTextBrowser()
        self._side_browser.setFont(QFont("Consolas", 10))
        self._side_browser.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 3px;"
        )
        splitter.addWidget(self._side_browser)
        splitter.setSizes([420, 240])
        layout.addWidget(splitter, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("Export")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.clicked.connect(self._export)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._main_browser.setPlainText("Loading…")
        self._load()

    def _load(self):
        deck_id = self._deck_id

        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT c.name, dc.quantity, dc.is_sideboard
                    FROM deck_cards dc
                    JOIN cards c ON c.id = dc.card_id
                    WHERE dc.deck_id = ?
                    ORDER BY dc.is_sideboard, c.name
                """, (deck_id,)).fetchall()
            finally:
                conn.close()
            main, side = {}, {}
            for r in rows:
                if r["is_sideboard"]:
                    side[r["name"]] = r["quantity"]
                else:
                    main[r["name"]] = r["quantity"]
            return {"main": main, "side": side}

        def _show(data):
            main = data["main"]
            side = data["side"]
            self._mainboard = main
            self._sideboard = side

            if not main and not side:
                self._main_browser.setPlainText("No card data stored for this deck.")
                return

            # Mainboard grouped by type heuristic (lands last, spells first)
            def _type_sort_key(name):
                return name  # alphabetical for now

            main_total = sum(main.values())
            side_total = sum(side.values())

            main_lines = [f"// Mainboard ({main_total} cards)"]
            for name in sorted(main.keys(), key=_type_sort_key):
                main_lines.append(f"{main[name]:2d}  {name}")

            self._main_browser.setPlainText("\n".join(main_lines))

            side_lines = [f"// Sideboard ({side_total} cards)"]
            if side:
                for name in sorted(side.keys()):
                    side_lines.append(f"{side[name]:2d}  {name}")
            else:
                side_lines.append("(none stored)")
            self._side_browser.setPlainText("\n".join(side_lines))

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: self._main_browser.setPlainText(f"Error: {e}"))
        w.start()
        self._workers.append(w)

    def _export(self):
        if not hasattr(self, "_mainboard"):
            return
        from gui.widgets.deck_export import show_export_menu
        show_export_menu(
            self._export_btn,
            self._mainboard,
            self._sideboard,
            self._archetype,
            self._fmt,
        )


# ---------------------------------------------------------------------------
# Main Search Tab
# ---------------------------------------------------------------------------

class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._card_browser = None
        self._build_ui()

    def cleanup(self):
        from gui.worker_utils import cancel_worker
        for w in self._workers:
            cancel_worker(w)
        self._workers.clear()
        if self._card_browser and hasattr(self._card_browser, "cleanup"):
            self._card_browser.cleanup()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_card_browser_tab(), "Card Browser")
        tabs.addTab(self._build_deck_tab(),         "Deck Search")
        tabs.addTab(self._build_h2h_tab(),          "Head-to-Head")
        layout.addWidget(tabs)

    # ======================================================================
    # Card Browser  (replaced old Card Lookup — now full Scryfall-style)
    # ======================================================================

    def _build_card_browser_tab(self):
        from gui.tabs.card_browser import CardBrowserTab
        self._card_browser = CardBrowserTab()
        return self._card_browser

    # ======================================================================
    # Deck Search  (rewritten — filters + sortable + click opens exact deck)
    # ======================================================================

    def _build_deck_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # ── Row 1: query + format + placement ─────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        row1.addWidget(QLabel("Archetype:"))
        self._deck_q = QLineEdit()
        self._deck_q.setPlaceholderText("e.g. Prowess")
        self._deck_q.returnPressed.connect(self._search_decks)
        row1.addWidget(self._deck_q, 2)

        row1.addWidget(QLabel("Format:"))
        self._deck_fmt = QComboBox()
        self._deck_fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._deck_fmt.setFixedWidth(110)
        row1.addWidget(self._deck_fmt)

        row1.addWidget(QLabel("Placement:"))
        self._deck_placement = QComboBox()
        self._deck_placement.addItems(list(_PLACEMENT_FILTERS.keys()))
        self._deck_placement.setFixedWidth(110)
        row1.addWidget(self._deck_placement)

        v.addLayout(row1)

        # ── Row 2: date filter + search button ────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2.addWidget(QLabel("From:"))
        self._deck_from = QLineEdit()
        self._deck_from.setPlaceholderText("YYYY-MM-DD")
        self._deck_from.setFixedWidth(100)
        row2.addWidget(self._deck_from)

        row2.addWidget(QLabel("To:"))
        self._deck_to = QLineEdit()
        self._deck_to.setPlaceholderText("YYYY-MM-DD")
        self._deck_to.setFixedWidth(100)
        row2.addWidget(self._deck_to)

        row2.addWidget(QLabel("Player:"))
        self._deck_player_q = QLineEdit()
        self._deck_player_q.setPlaceholderText("optional")
        self._deck_player_q.setFixedWidth(120)
        row2.addWidget(self._deck_player_q)

        btn = _btn("Search")
        btn.clicked.connect(self._search_decks)
        row2.addWidget(btn)

        self._deck_status = QLabel("")
        self._deck_status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        row2.addWidget(self._deck_status)
        row2.addStretch()
        v.addLayout(row2)

        # ── Results table ──────────────────────────────────────────────
        hint = QLabel("Click any row to open the exact registered decklist for that player.")
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        v.addWidget(hint)

        self._deck_table = QTableWidget(0, 5)
        self._deck_table.setHorizontalHeaderLabels(
            ["Archetype", "Player", "Place", "Event", "Date"]
        )
        hh = self._deck_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._deck_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._deck_table.setAlternatingRowColors(True)
        self._deck_table.verticalHeader().setVisible(False)
        self._deck_table.setSortingEnabled(True)
        self._deck_table.itemDoubleClicked.connect(self._on_deck_row_click)
        self._deck_table.itemClicked.connect(self._on_deck_row_click)
        v.addWidget(self._deck_table, 1)
        return w

    def _search_decks(self):
        query = self._deck_q.text().strip()
        fmt   = self._deck_fmt.currentText()

        placement_label = self._deck_placement.currentText()
        max_placement   = _PLACEMENT_FILTERS.get(placement_label)

        date_from = self._deck_from.text().strip().replace("-", "")
        date_to   = self._deck_to.text().strip().replace("-", "")
        player_q  = self._deck_player_q.text().strip()

        self._deck_status.setText("Searching…")
        self._deck_table.setSortingEnabled(False)
        self._deck_table.setRowCount(0)

        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                sql = f"""
                    SELECT d.id AS deck_id, d.archetype, d.player, d.placement,
                           e.id AS event_id, e.name AS event_name, e.date,
                           e.url AS event_url,
                           ({_DATE_KEY}) AS sort_date
                    FROM decks d
                    JOIN events e ON e.id = d.event_id
                    WHERE lower(e.format) = lower(?)
                """
                params = [fmt]
                if query:
                    sql += " AND lower(d.archetype) LIKE ?"
                    params.append(f"%{query.lower()}%")
                if max_placement is not None:
                    sql += " AND d.placement <= ?"
                    params.append(max_placement)
                if date_from:
                    sql += f" AND ({_DATE_KEY}) >= ?"
                    params.append(date_from)
                if date_to:
                    sql += f" AND ({_DATE_KEY}) <= ?"
                    params.append(date_to)
                if player_q:
                    sql += " AND lower(d.player) LIKE ?"
                    params.append(f"%{player_q.lower()}%")
                sql += " ORDER BY sort_date DESC, d.placement ASC LIMIT 500"
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in rows]

        def _show(rows):
            self._deck_table.setSortingEnabled(False)
            self._deck_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                arch_item = QTableWidgetItem(row["archetype"] or "")
                # Store deck_id + format in UserRole for click handler
                arch_item.setData(Qt.ItemDataRole.UserRole, {
                    "deck_id":   row["deck_id"],
                    "archetype": row["archetype"] or "",
                    "player":    row["player"] or "",
                    "placement": row["placement"],
                    "event":     row["event_name"] or "",
                    "date":      row["date"] or "",
                    "fmt":       fmt,
                })
                self._deck_table.setItem(r, 0, arch_item)
                self._deck_table.setItem(r, 1, QTableWidgetItem(row["player"] or ""))

                place_item = _NumItem(str(row["placement"] or ""))
                place_val  = row["placement"] or 9999
                if place_val == 1:
                    place_item.setForeground(QColor("#f0c020"))
                elif place_val <= 4:
                    place_item.setForeground(QColor("#3cb44b"))
                elif place_val <= 8:
                    place_item.setForeground(QColor("#5eb5cf"))
                self._deck_table.setItem(r, 2, place_item)
                ev_item = QTableWidgetItem(row["event_name"] or "")
                ev_item.setForeground(QColor(theme.ACCENT))
                ev_item.setToolTip("Click to see all decks from this event")
                ev_item.setData(Qt.ItemDataRole.UserRole, {
                    "event_id": row.get("event_id"),
                    "event_name": row.get("event_name", ""),
                    "event_url": row.get("event_url", ""),
                })
                self._deck_table.setItem(r, 3, ev_item)
                raw_date = row["date"] or ""
                self._deck_table.setItem(r, 4, _DateItem(raw_date, _date_sort_key(raw_date)))

            self._deck_table.setSortingEnabled(True)
            self._deck_table.sortByColumn(4, Qt.SortOrder.DescendingOrder)
            self._deck_status.setText(f"{len(rows)} result{'s' if len(rows) != 1 else ''}")

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: (
            self._deck_status.setText(f"Error: {e}"),
        ))
        w.start()
        self._workers.append(w)

    def _on_deck_row_click(self, item):
        row = self._deck_table.currentRow()
        col = self._deck_table.currentColumn()

        # Event column click → show all decks from that event
        if col == 3:
            ev_item = self._deck_table.item(row, 3)
            if ev_item:
                ev_data = ev_item.data(Qt.ItemDataRole.UserRole)
                if isinstance(ev_data, dict) and ev_data.get("event_id"):
                    from gui.widgets.event_peers import EventPeersDialog
                    dlg = EventPeersDialog(
                        event_id=ev_data["event_id"],
                        event_name=ev_data.get("event_name", ""),
                        event_url=ev_data.get("event_url", ""),
                        parent=self,
                    )
                    dlg.exec()
                    return

        arch_item = self._deck_table.item(row, 0)
        if not arch_item:
            return
        meta = arch_item.data(Qt.ItemDataRole.UserRole)
        if not meta or not isinstance(meta, dict):
            return
        dlg = _DeckDetailDialog(
            deck_id   = meta["deck_id"],
            archetype = meta["archetype"],
            player    = meta["player"],
            placement = meta["placement"],
            event     = meta["event"],
            date      = meta["date"],
            fmt       = meta["fmt"],
            parent    = self,
        )
        dlg.exec()

    # ======================================================================
    # Head-to-Head  (rewritten — rich HTML + My Deck vs Field)
    # ======================================================================

    def _build_h2h_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        inner = QTabWidget()
        inner.addTab(self._build_avsa_pane(),  "Archetype vs Archetype")
        inner.addTab(self._build_vsfield_pane(), "My Deck vs Field")
        v.addWidget(inner)
        return w

    # ------------------------------------------------------------------
    # Archetype vs Archetype pane
    # ------------------------------------------------------------------

    def _build_avsa_pane(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(QLabel("Deck A:"))
        self._h2h_a = QLineEdit()
        self._h2h_a.setPlaceholderText("e.g. Boros Energy")
        self._h2h_a.returnPressed.connect(self._run_h2h)
        row.addWidget(self._h2h_a, 1)

        row.addWidget(QLabel("vs"))

        row.addWidget(QLabel("Deck B:"))
        self._h2h_b = QLineEdit()
        self._h2h_b.setPlaceholderText("e.g. Azorius Control")
        self._h2h_b.returnPressed.connect(self._run_h2h)
        row.addWidget(self._h2h_b, 1)

        self._h2h_fmt = QComboBox()
        self._h2h_fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._h2h_fmt.setFixedWidth(110)
        row.addWidget(self._h2h_fmt)

        self._h2h_tf = QComboBox()
        for label, _ in theme.TIMEFRAME_OPTIONS:
            self._h2h_tf.addItem(label)
        self._h2h_tf.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._h2h_tf.setFixedWidth(100)
        row.addWidget(self._h2h_tf)

        btn = _btn("Compare")
        btn.clicked.connect(self._run_h2h)
        row.addWidget(btn)
        v.addLayout(row)

        self._h2h_result = QTextBrowser()
        self._h2h_result.setFont(QFont("Consolas", 10))
        self._h2h_result.setOpenExternalLinks(True)
        v.addWidget(self._h2h_result, 1)
        return w

    def _run_h2h(self):
        from datetime import datetime, timedelta
        a     = self._h2h_a.text().strip()
        b     = self._h2h_b.text().strip()
        fmt   = self._h2h_fmt.currentText()
        weeks = theme.TIMEFRAME_OPTIONS[self._h2h_tf.currentIndex()][1]
        since = (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None
        if not a or not b:
            self._h2h_result.setPlainText("Enter both archetype names.")
            return
        self._h2h_result.setPlainText("Loading…")

        def _do():
            from analysis.win_rates import get_head_to_head, get_meta_standings
            h2h       = get_head_to_head(a, b, format_name=fmt, since=since)
            # Also fetch meta standings for context / fallback
            standings = get_meta_standings(fmt, top=60, since=since)
            wr_map = {s["archetype"].lower(): s["est_match_winpct"] for s in standings}
            return {"h2h": h2h, "wr_map": wr_map}

        def _show(data):
            self._h2h_result.setHtml(
                _format_h2h_html(a, b, fmt, data["h2h"], data["wr_map"])
            )

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: self._h2h_result.setPlainText(f"Error: {e}"))
        w.start()
        self._workers.append(w)

    # ------------------------------------------------------------------
    # My Deck vs Field pane
    # ------------------------------------------------------------------

    def _build_vsfield_pane(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(QLabel("My archetype:"))
        self._vsf_arch = QComboBox()
        self._vsf_arch.setEditable(True)
        self._vsf_arch.lineEdit().setPlaceholderText("e.g. Boros Energy")
        row.addWidget(self._vsf_arch, 1)

        row.addWidget(QLabel("Format:"))
        self._vsf_fmt = QComboBox()
        self._vsf_fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._vsf_fmt.setFixedWidth(110)
        self._vsf_fmt.currentTextChanged.connect(self._vsf_fmt_changed)
        row.addWidget(self._vsf_fmt)

        btn = _btn("Show Matchups")
        btn.clicked.connect(self._run_vs_field)
        row.addWidget(btn)

        self._vsf_status = QLabel("")
        self._vsf_status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        row.addWidget(self._vsf_status)
        v.addLayout(row)

        # Paste decklist for auto-detect
        hint = QLabel(
            "Optionally paste your decklist below for archetype auto-detection:"
        )
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        v.addWidget(hint)

        dl_row = QHBoxLayout()
        self._vsf_decklist = QTextEdit()
        self._vsf_decklist.setPlaceholderText(
            "4 Emberholt Charger\n2 Manifold Mouse\n..."
        )
        self._vsf_decklist.setMaximumHeight(100)
        self._vsf_decklist.setFont(QFont("Consolas", 9))
        dl_row.addWidget(self._vsf_decklist, 1)

        detect_btn = _btn("Detect", style="secondary")
        detect_btn.setToolTip("Detect archetype from pasted decklist")
        detect_btn.setFixedWidth(70)
        detect_btn.clicked.connect(self._detect_archetype)
        dl_row.addWidget(detect_btn)
        v.addLayout(dl_row)

        # Matchup table
        self._vsf_table = QTableWidget(0, 5)
        self._vsf_table.setHorizontalHeaderLabels(
            ["Opponent Archetype", "Win Rate", "Favored?", "Confidence", "Shared Events"]
        )
        hh = self._vsf_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._vsf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._vsf_table.setAlternatingRowColors(True)
        self._vsf_table.verticalHeader().setVisible(False)
        self._vsf_table.setSortingEnabled(True)
        v.addWidget(self._vsf_table, 1)

        # Populate arch combo on load
        self._vsf_fmt_changed("standard")
        return w

    def _vsf_fmt_changed(self, fmt):
        current = self._vsf_arch.currentText()
        def _do():
            from analysis.win_rates import get_meta_standings
            return [s["archetype"] for s in get_meta_standings(fmt, top=30)]
        def _done(archs):
            self._vsf_arch.blockSignals(True)
            self._vsf_arch.clear()
            self._vsf_arch.addItems(archs or [])
            self._vsf_arch.setCurrentText(current)
            self._vsf_arch.blockSignals(False)
        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _detect_archetype(self):
        decklist = self._vsf_decklist.toPlainText().strip()
        if not decklist:
            self._vsf_status.setText("Paste a decklist first.")
            return
        fmt = self._vsf_fmt.currentText()
        self._vsf_status.setText("Detecting…")

        def _do():
            # Parse card names from decklist
            input_cards = set()
            for line in decklist.splitlines():
                line = line.strip()
                m = re.match(r'^\d+\s+(.+)$', line)
                if m:
                    input_cards.add(m.group(1).strip().lower())
            if not input_cards:
                return ""

            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                archs = conn.execute("""
                    SELECT d.archetype, COUNT(*) as cnt
                    FROM decks d JOIN events e ON e.id = d.event_id
                    WHERE lower(e.format) = lower(?) AND d.archetype != ''
                    GROUP BY d.archetype HAVING cnt >= 5
                    ORDER BY cnt DESC LIMIT 30
                """, [fmt]).fetchall()

                best_arch, best_score = "", 0.0
                for arch_row in archs:
                    arch = arch_row["archetype"]
                    cards = conn.execute("""
                        SELECT c.name, COUNT(*) as freq
                        FROM deck_cards dc
                        JOIN cards c ON c.id = dc.card_id
                        JOIN decks d ON d.id = dc.deck_id
                        JOIN events e ON e.id = d.event_id
                        WHERE lower(d.archetype) LIKE lower(?)
                          AND lower(e.format) = lower(?)
                          AND dc.is_sideboard = 0
                        GROUP BY c.name HAVING freq >= 2
                    """, [f"%{arch}%", fmt]).fetchall()

                    arch_cards = {r["name"].lower() for r in cards}
                    if not arch_cards:
                        continue
                    overlap = len(input_cards & arch_cards)
                    score = overlap / len(arch_cards)
                    if score > best_score:
                        best_score = score
                        best_arch = arch
            finally:
                conn.close()

            return best_arch if best_score > 0.25 else ""

        def _done(detected):
            if detected:
                self._vsf_arch.setCurrentText(detected)
                self._vsf_status.setText(f"Detected: {detected}")
            else:
                self._vsf_status.setText("Could not detect archetype — enter manually.")

        dw = DataLoadWorker(_do)
        dw.result.connect(_done)
        dw.error.connect(lambda e: self._vsf_status.setText(f"Error: {e}"))
        dw.start()
        self._workers.append(dw)

    def _run_vs_field(self):
        archetype = self._vsf_arch.currentText().strip()
        fmt       = self._vsf_fmt.currentText()
        if not archetype:
            self._vsf_status.setText("Enter your archetype.")
            return
        self._vsf_status.setText("Loading matchups…")
        self._vsf_table.setSortingEnabled(False)
        self._vsf_table.setRowCount(0)

        def _do():
            from analysis.win_rates import get_archetype_matchups
            return get_archetype_matchups(archetype, format_name=fmt, min_shared_events=1)

        def _show(matchups):
            self._vsf_table.setSortingEnabled(False)
            self._vsf_table.setRowCount(len(matchups))

            for r, m in enumerate(matchups):
                wr   = m["win_rate"]
                conf = m["confidence"]
                se   = m["shared_events"]

                opp_item = QTableWidgetItem(m["opponent"])
                self._vsf_table.setItem(r, 0, opp_item)

                wr_item = _NumItem(f"{wr*100:.0f}%")
                wr_color = "#3cb44b" if wr >= 0.52 else ("#e6194b" if wr <= 0.48 else None)
                if wr_color:
                    wr_item.setForeground(QColor(wr_color))
                self._vsf_table.setItem(r, 1, wr_item)

                fav_text = "Favored" if wr >= 0.52 else ("Unfavored" if wr <= 0.48 else "Even")
                fav_item = QTableWidgetItem(fav_text)
                if wr_color:
                    fav_item.setForeground(QColor(wr_color))
                self._vsf_table.setItem(r, 2, fav_item)

                conf_colors = {"high": "#3cb44b", "medium": "#f0c020", "low": "#f58231", "none": "#888888"}
                conf_item = QTableWidgetItem(conf)
                conf_item.setForeground(QColor(conf_colors.get(conf, theme.TEXT)))
                self._vsf_table.setItem(r, 3, conf_item)

                self._vsf_table.setItem(r, 4, _NumItem(str(se)))

            self._vsf_table.setSortingEnabled(True)
            self._vsf_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
            count = len(matchups)
            favored   = sum(1 for m in matchups if m["win_rate"] >= 0.52)
            unfavored = sum(1 for m in matchups if m["win_rate"] <= 0.48)
            self._vsf_status.setText(
                f"{count} matchups  ·  {favored} favored  ·  {unfavored} unfavored"
            )

        dw = DataLoadWorker(_do)
        dw.result.connect(_show)
        dw.error.connect(lambda e: self._vsf_status.setText(f"Error: {e}"))
        dw.start()
        self._workers.append(dw)


# ---------------------------------------------------------------------------
# H2H HTML formatter
# ---------------------------------------------------------------------------

def _format_h2h_html(a: str, b: str, fmt: str, data: dict, wr_map: dict) -> str:
    P = theme.PANEL
    T = theme.TEXT
    AC = theme.ACCENT
    DIM = theme.TEXT_DIM

    if not data or data.get("shared_events", 0) == 0:
        # Fallback: estimate from meta standings
        def _find_wr(name):
            nl = name.lower()
            if nl in wr_map:
                return wr_map[nl]
            for k, v in wr_map.items():
                if nl in k or k in nl:
                    return v
            return None

        wr_a = _find_wr(a)
        wr_b = _find_wr(b)

        lines = [
            f'<h3 style="color:{AC};">No Direct H2H Data Found</h3>',
            f'<p style="color:{DIM};">No shared events found for <b>{a}</b> vs <b>{b}</b> in {fmt.upper()}.</p>',
        ]
        if wr_a and wr_b:
            est = wr_a / (wr_a + wr_b)
            fav = a if est >= 0.5 else b
            lines.append(
                f'<p><b>Estimated matchup from meta data:</b></p>'
                f'<p style="font-size: 14px;">'
                f'<b>{a}</b>: {est*100:.1f}%  vs  <b>{b}</b>: {(1-est)*100:.1f}%</p>'
                f'<p style="color:{DIM};">'
                f'Based on estimated match win % ({a}: {wr_a*100:.1f}%, {b}: {wr_b*100:.1f}%). '
                f'<b>{fav}</b> is favored based on meta performance.</p>'
                f'<p style="color:#f58231; font-size: 10px;">'
                f'Note: This is an Elo-style estimate from placement data, not actual match results.</p>'
            )
        else:
            lines.append(
                f'<p style="color:{DIM};">Could not find meta data for one or both archetypes. '
                f'Check spelling or try a different format.</p>'
            )
        return f'<div style="color:{T}; font-family: Consolas; font-size: 11px; line-height: 1.5;">' + \
               "\n".join(lines) + "</div>"

    a_wins   = data["a_wins"]
    b_wins   = data["b_wins"]
    ties     = data["ties"]
    total    = data["shared_events"]
    a_wr     = data["a_win_rate"]
    b_wr     = data["b_win_rate"]
    conf     = data.get("confidence", "low")
    matchups = data.get("matchups", [])
    note     = data.get("note", "")

    fav_color = "#3cb44b" if a_wr > b_wr else ("#e6194b" if a_wr < b_wr else "#f0c020")
    conf_color = {"high": "#3cb44b", "medium": "#f0c020", "low": "#f58231", "none": "#888888"}.get(conf, DIM)

    lines = [
        f'<h3 style="color:{AC}; margin:0 0 8px 0;">{a}  vs  {b}  ({fmt.upper()})</h3>',
        '<table style="border-collapse: collapse; margin-bottom: 12px;">',
        f'<tr><td style="padding-right:24px; font-size: 18px; color:{fav_color};">'
        f'<b>{a}</b>: {a_wins}-{b_wins}-{ties} &nbsp;({a_wr*100:.0f}% win rate)</td>',
        f'<td style="color:{conf_color}; font-size: 11px;">Confidence: {conf} ({total} shared events)</td></tr>',
        '</table>',
    ]

    # Avg placement comparison
    a_avg = data.get("a_avg_placement")
    b_avg = data.get("b_avg_placement")
    if a_avg and b_avg:
        lines.append(
            f'<p style="color:{DIM}; font-size: 10px;">Avg placement when both appeared: '
            f'{a} → {a_avg:.1f}  |  {b} → {b_avg:.1f}</p>'
        )

    # Trend: last 90 days vs all-time
    if matchups:
        from datetime import datetime, timedelta
        cutoff_str = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

        def _to_sortable(d):
            d = d or ""
            if "/" in d:
                parts = d.split("/")
                if len(parts) == 3:
                    return f"20{parts[2]}{parts[1]}{parts[0]}"
            return d.replace("-", "")

        recent = [m for m in matchups if _to_sortable(m.get("date", "")) >= cutoff_str]
        if recent and len(recent) < total:
            a_key = f"{a}_place"
            b_key = f"{b}_place"
            r_a_wins = sum(1 for m in recent if m.get(a_key, 999) < m.get(b_key, 999))
            r_total  = len(recent)
            r_wr     = r_a_wins / r_total if r_total else 0
            trend_color = "#3cb44b" if abs(r_wr - a_wr) < 0.05 else "#f58231"
            lines.append(
                f'<p style="color:{trend_color}; font-size: 10px;">'
                f'Last 90 days ({r_total} events): {a} wins {r_a_wins}/{r_total} '
                f'({r_wr*100:.0f}%)  '
                f'{"— trending same" if abs(r_wr - a_wr) < 0.05 else "— trend shifted"}'
                f'</p>'
            )

    # Event-by-event table
    if matchups:
        lines.append(f'<h4 style="color:{AC}; margin: 10px 0 4px 0;">Shared Events ({len(matchups)})</h4>')
        lines.append(
            '<table style="border-collapse: collapse; width: 100%; font-size: 10px;">'
            f'<tr style="color:{DIM};">'
            '<th style="text-align:left; padding-right:12px;">Event</th>'
            '<th style="text-align:left; padding-right:12px;">Date</th>'
            f'<th style="padding-right:12px;">{a[:20]} Place</th>'
            f'<th style="padding-right:12px;">{b[:20]} Place</th>'
            '<th style="text-align:left;">Result</th>'
            '</tr>'
        )
        a_key = f"{a}_place"
        b_key = f"{b}_place"
        for m in matchups[:50]:
            result = m.get("result", "")
            rc = "#3cb44b" if a in result else ("#e6194b" if b in result else DIM)
            lines.append(
                f'<tr>'
                f'<td style="padding-right:12px;">{m.get("event","")[:35]}</td>'
                f'<td style="padding-right:12px; color:{DIM};">{m.get("date","")}</td>'
                f'<td style="text-align:center; padding-right:12px;">{m.get(a_key,"—")}</td>'
                f'<td style="text-align:center; padding-right:12px;">{m.get(b_key,"—")}</td>'
                f'<td style="color:{rc};">{result}</td>'
                f'</tr>'
            )
        lines.append('</table>')

    if note:
        lines.append(f'<p style="color:{DIM}; font-size: 10px; margin-top: 8px;">{note}</p>')

    return (
        f'<div style="color:{T}; font-family: Consolas; font-size: 11px; line-height: 1.5;">'
        + "\n".join(lines)
        + "</div>"
    )
