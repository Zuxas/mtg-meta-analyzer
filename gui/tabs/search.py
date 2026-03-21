"""
Tab 3 — Search
  Sub-tabs: Card Lookup | Deck Search | Head-to-Head
"""
import os
import sqlite3
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextBrowser, QComboBox, QFrame, QSplitter,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap

from gui.worker_threads import DataLoadWorker
import gui.theme as theme


# ---------------------------------------------------------------------------
# Card image helpers
# ---------------------------------------------------------------------------

def _card_image_cache_path(card_name: str) -> str:
    here = os.path.dirname(__file__)
    cache_dir = os.path.normpath(os.path.join(here, "..", "..", "data", "card_images"))
    os.makedirs(cache_dir, exist_ok=True)
    safe = card_name.replace("/", "_").replace(":", "_").replace("?", "_")
    return os.path.join(cache_dir, f"{safe}.jpg")


def _fetch_card_image(card_name: str) -> str | None:
    """
    Return local cache path for card_name image.
    Downloads from Scryfall API on first request; subsequent calls use cache.
    Returns None if the image can't be retrieved.
    """
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


def _btn(text):
    w = QPushButton(text)
    w.setStyleSheet(theme.btn_primary())
    return w


class SearchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_card_tab(),  "Card Lookup")
        tabs.addTab(self._build_deck_tab(),  "Deck Search")
        tabs.addTab(self._build_h2h_tab(),   "Head-to-Head")
        layout.addWidget(tabs)

    # ------------------------------------------------------------------
    # Card Lookup
    # ------------------------------------------------------------------

    def _build_card_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Name or description:"))
        self._card_q = QLineEdit()
        self._card_q.setPlaceholderText(
            "e.g. Sheoldred, the Apocalypse  \u2014  or  \u2014  what does sheoldred do"
        )
        self._card_q.returnPressed.connect(self._search_card)
        row.addWidget(self._card_q, 1)

        self._card_fmt = QComboBox()
        self._card_fmt.addItems(
            ["(any format)", "standard", "pioneer", "modern", "legacy"]
        )
        self._card_fmt.setFixedWidth(130)
        row.addWidget(self._card_fmt)

        btn = _btn("Search")
        btn.clicked.connect(self._search_card)
        row.addWidget(btn)
        v.addLayout(row)

        # Results: card image on the left, text on the right
        split = QSplitter(Qt.Orientation.Horizontal)

        self._card_image_lbl = QLabel()
        self._card_image_lbl.setFixedWidth(230)
        self._card_image_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._card_image_lbl.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            " border-radius: 3px; padding: 4px;"
        )
        self._card_image_lbl.setText("Image loads\nafter search")
        split.addWidget(self._card_image_lbl)

        self._card_result = QTextBrowser()
        self._card_result.setFont(QFont("Consolas", 10))
        split.addWidget(self._card_result)
        split.setSizes([230, 600])

        v.addWidget(split, 1)
        return w

    def _search_card(self):
        query = self._card_q.text().strip()
        if not query:
            return
        self._card_result.setPlainText("Searching\u2026")
        self._card_image_lbl.setText("Loading image…")
        self._card_image_lbl.setPixmap(QPixmap())
        fmt_text = self._card_fmt.currentText()
        fmt = None if fmt_text == "(any format)" else fmt_text

        def _do():
            import json
            from scrapers.scryfall import search_local
            results = search_local(query)
            if not results:
                return {"text": "No results found.", "image_name": None}
            lines = []
            first_name = None
            for card in results[:8]:
                lines.append("=" * 52)
                name = card.get("name", "")
                if first_name is None:
                    first_name = name
                type_line = card.get("type_line", "")
                lines.append(f"  {name}")
                if type_line:
                    lines.append(f"  {type_line}")
                mana = card.get("mana_cost", "")
                cmc  = card.get("cmc", "")
                if mana or cmc != "":
                    lines.append(f"  Mana: {mana}  CMC: {cmc}")
                oracle = card.get("oracle_text", "")
                if oracle:
                    for ol in oracle.splitlines():
                        lines.append(f"  {ol}")
                pt = card.get("power"), card.get("toughness")
                if pt[0]:
                    lines.append(f"  P/T: {pt[0]}/{pt[1]}")
                rarity = card.get("rarity", "")
                set_code = card.get("set", "")
                if rarity or set_code:
                    lines.append(f"  {rarity.capitalize()} \u2014 {set_code.upper()}")
                if fmt:
                    legal = card.get("legalities", {})
                    if isinstance(legal, str):
                        try:
                            legal = json.loads(legal)
                        except Exception:
                            legal = {}
                    status = legal.get(fmt, "unknown")
                    lines.append(f"  {fmt.upper()}: {status}")
            return {"text": "\n".join(lines), "image_name": first_name}

        def _show(result):
            self._card_result.setPlainText(result["text"])
            img_name = result.get("image_name")
            if img_name:
                # Fetch image in a second background worker
                img_worker = DataLoadWorker(_fetch_card_image, {"card_name": img_name})
                img_worker.result.connect(self._show_card_image)
                img_worker.error.connect(lambda _: self._card_image_lbl.setText("No image"))
                img_worker.start()
                self._workers.append(img_worker)
            else:
                self._card_image_lbl.setText("No image")

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: self._card_result.setPlainText(f"Error: {e}"))
        w.start()
        self._workers.append(w)

    def _show_card_image(self, path):
        if path and os.path.exists(path):
            pix = QPixmap(path)
            pix = pix.scaledToWidth(
                220, Qt.TransformationMode.SmoothTransformation
            )
            self._card_image_lbl.setPixmap(pix)
        else:
            self._card_image_lbl.setText("No image available")

    # ------------------------------------------------------------------
    # Deck Search
    # ------------------------------------------------------------------

    def _build_deck_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Archetype search:"))
        self._deck_q = QLineEdit()
        self._deck_q.setPlaceholderText("e.g. Prowess")
        self._deck_q.returnPressed.connect(self._search_decks)
        row.addWidget(self._deck_q, 1)

        self._deck_fmt = QComboBox()
        self._deck_fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._deck_fmt.setFixedWidth(120)
        row.addWidget(self._deck_fmt)

        btn = _btn("Search")
        btn.clicked.connect(self._search_decks)
        row.addWidget(btn)
        v.addLayout(row)

        self._deck_table = QTableWidget(0, 5)
        self._deck_table.setHorizontalHeaderLabels(
            ["Archetype", "Player", "Placement", "Event", "Date"]
        )
        hh = self._deck_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._deck_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._deck_table.setAlternatingRowColors(True)
        self._deck_table.verticalHeader().setVisible(False)
        self._deck_table.itemClicked.connect(self._on_deck_row_click)

        hint = QLabel("Click any row to open the archetype deck detail view.")
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        v.addWidget(hint)
        v.addWidget(self._deck_table, 1)
        return w

    def _search_decks(self):
        query = self._deck_q.text().strip()
        if not query:
            return
        fmt = self._deck_fmt.currentText()

        def _do():
            from db.database import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    """
                    SELECT d.archetype, d.player, d.placement,
                           e.name, e.date
                    FROM decks d
                    JOIN events e ON e.id = d.event_id
                    WHERE LOWER(d.archetype) LIKE ?
                      AND LOWER(e.format) = ?
                    ORDER BY e.date DESC
                    LIMIT 200
                    """,
                    (f"%{query.lower()}%", fmt.lower()),
                ).fetchall()
            return rows

        def _show(rows):
            self._deck_table.setRowCount(len(rows))
            for r, (arch, player, placement, event, date) in enumerate(rows):
                arch_item = QTableWidgetItem(arch or "")
                # Store raw archetype name for click handler
                arch_item.setData(Qt.ItemDataRole.UserRole, arch or "")
                self._deck_table.setItem(r, 0, arch_item)
                self._deck_table.setItem(r, 1, QTableWidgetItem(player or ""))
                self._deck_table.setItem(r, 2, QTableWidgetItem(
                    str(placement) if placement else ""
                ))
                self._deck_table.setItem(r, 3, QTableWidgetItem(event or ""))
                self._deck_table.setItem(r, 4, QTableWidgetItem(date  or ""))

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: print(f"Deck search error: {e}"))
        w.start()
        self._workers.append(w)

    def _on_deck_row_click(self, item):
        row = self._deck_table.currentRow()
        arch_item = self._deck_table.item(row, 0)
        if not arch_item:
            return
        archetype = arch_item.data(Qt.ItemDataRole.UserRole) or arch_item.text()
        if not archetype:
            return
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        fmt = self._deck_fmt.currentText()
        dlg = ArchetypeDetailDialog(
            archetype=archetype,
            format_name=fmt,
            initial_weeks=4,
            parent=self,
        )
        dlg.exec()

    # ------------------------------------------------------------------
    # Head-to-Head
    # ------------------------------------------------------------------

    def _build_h2h_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Deck A:"))
        self._h2h_a = QLineEdit()
        self._h2h_a.setPlaceholderText("e.g. Izzet Prowess")
        row.addWidget(self._h2h_a, 1)

        row.addWidget(QLabel("vs"))

        row.addWidget(QLabel("Deck B:"))
        self._h2h_b = QLineEdit()
        self._h2h_b.setPlaceholderText("e.g. Azorius Control")
        row.addWidget(self._h2h_b, 1)

        self._h2h_fmt = QComboBox()
        self._h2h_fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._h2h_fmt.setFixedWidth(120)
        row.addWidget(self._h2h_fmt)

        btn = _btn("Compare")
        btn.clicked.connect(self._run_h2h)
        row.addWidget(btn)
        v.addLayout(row)

        self._h2h_result = QTextBrowser()
        self._h2h_result.setFont(QFont("Consolas", 11))
        v.addWidget(self._h2h_result, 1)
        return w

    def _run_h2h(self):
        a = self._h2h_a.text().strip()
        b = self._h2h_b.text().strip()
        if not a or not b:
            self._h2h_result.setPlainText("Enter both archetype names.")
            return
        fmt = self._h2h_fmt.currentText()
        self._h2h_result.setPlainText("Loading\u2026")

        def _do():
            from analysis.win_rates import get_head_to_head
            return get_head_to_head(a, b, format_name=fmt)

        def _show(data):
            if not data:
                self._h2h_result.setPlainText(
                    f"No head-to-head data found for:\n  {a}\nvs\n  {b}\n\n"
                    "Try different spelling or a broader format."
                )
                return
            lines = [
                f"{'='*52}",
                f"  {a}",
                f"  vs",
                f"  {b}",
                f"  Format: {fmt.upper()}",
                f"{'='*52}",
            ]
            skip = {"archetype_a", "archetype_b"}
            for k, v in data.items():
                if k not in skip:
                    label = k.replace("_", " ").title()
                    lines.append(f"  {label}: {v}")
            self._h2h_result.setPlainText("\n".join(lines))

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(
            lambda e: self._h2h_result.setPlainText(f"Error: {e}")
        )
        w.start()
        self._workers.append(w)
