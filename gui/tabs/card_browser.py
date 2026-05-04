"""
Tab — Card Browser (local Scryfall-style card database)

Full card database browser powered by the local scryfall_oracle.json file.
Supports name search, oracle text search, filters (color, type, CMC, rarity,
format legality), and a "Cards in Meta" toggle that shows only cards appearing
in your local tournament data.

Card detail panel shows full image, oracle text, legalities, and meta usage
(which archetypes play this card, average copies).
"""
import json
import os
import re
from functools import lru_cache

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QCheckBox, QSplitter, QFrame, QTextBrowser,
    QSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QColor

from gui.worker_threads import DataLoadWorker
import gui.theme as theme
from gui.icons_util import btn_icon


# ---------------------------------------------------------------------------
# Scryfall query parser  (supports common Scryfall search operators)
# ---------------------------------------------------------------------------

def _parse_query(raw: str) -> dict:
    """
    Parse a Scryfall-style query string into structured filters.

    Supported operators:
        t:creature      — type line contains "creature"
        o:"draw a card" — oracle text contains "draw a card"
        c:red / c:r     — color filter (w/u/b/r/g or full names)
        ci:wub          — color identity
        cmc<=3 / cmc=5  — converted mana cost comparisons
        f:standard      — format legality
        r:mythic        — rarity filter
        is:legendary    — type line contains "legendary"
        pow>=4 / tou<=2 — power / toughness
        s:tdm           — set code
        k:flying        — keyword (searches oracle text)

    Bare words (no operator) search card name.
    """
    filters = {
        "name_terms": [],
        "type_terms": [],
        "oracle_terms": [],
        "colors": None,
        "color_identity": None,
        "cmc_op": None,        # (op, value) e.g. ("<=", 3)
        "format": None,
        "rarity": None,
        "is_terms": [],
        "power_op": None,      # (op, value)
        "toughness_op": None,
        "set_code": None,
        "keyword_terms": [],
    }

    # Color abbreviation map
    _COLOR_MAP = {
        "w": "W", "white": "W",
        "u": "U", "blue": "U",
        "b": "B", "black": "B",
        "r": "R", "red": "R",
        "g": "G", "green": "G",
    }

    # Tokenize: handles operator:"quoted value" and bare words
    tokens = []
    i = 0
    text = raw.strip()
    while i < len(text):
        if text[i] == ' ':
            i += 1
            continue
        # Check for prefix:\"quoted\" pattern (e.g. o:"draw a card")
        colon_pos = text.find(':', i)
        quote_after_colon = (colon_pos != -1
                             and colon_pos < len(text) - 1
                             and text[colon_pos + 1] == '"'
                             and (text.find(' ', i) == -1 or colon_pos < text.find(' ', i)))
        if quote_after_colon:
            end_quote = text.find('"', colon_pos + 2)
            if end_quote == -1:
                end_quote = len(text)
            # Reconstruct as prefix:value (without quotes)
            prefix = text[i:colon_pos + 1]
            value = text[colon_pos + 2:end_quote]
            tokens.append(prefix + value)
            i = end_quote + 1
        elif text[i] == '"':
            end = text.find('"', i + 1)
            if end == -1:
                end = len(text)
            tokens.append(text[i+1:end])
            i = end + 1
        else:
            end = text.find(' ', i)
            if end == -1:
                end = len(text)
            tokens.append(text[i:end])
            i = end + 1

    for tok in tokens:
        low = tok.lower()

        # t:type
        if low.startswith("t:"):
            filters["type_terms"].append(tok[2:])
            continue

        # o:"oracle text"
        if low.startswith("o:"):
            filters["oracle_terms"].append(tok[2:])
            continue

        # c:colors
        if low.startswith("c:") and not low.startswith("ci:") and not low.startswith("cmc"):
            colors = set()
            for ch in tok[2:].lower():
                if ch in _COLOR_MAP:
                    colors.add(_COLOR_MAP[ch])
            for word in tok[2:].lower().split(","):
                word = word.strip()
                if word in _COLOR_MAP:
                    colors.add(_COLOR_MAP[word])
            if colors:
                filters["colors"] = colors
            continue

        # ci:color_identity
        if low.startswith("ci:"):
            colors = set()
            for ch in tok[3:].lower():
                if ch in _COLOR_MAP:
                    colors.add(_COLOR_MAP[ch])
            if colors:
                filters["color_identity"] = colors
            continue

        # cmc comparisons
        m = re.match(r"cmc([<>=!]+)(\d+)", low)
        if m:
            filters["cmc_op"] = (m.group(1), int(m.group(2)))
            continue

        # f:format
        if low.startswith("f:"):
            filters["format"] = tok[2:].lower()
            continue

        # r:rarity
        if low.startswith("r:"):
            r = tok[2:].lower()
            rarity_map = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic"}
            filters["rarity"] = rarity_map.get(r, r)
            continue

        # is:keyword
        if low.startswith("is:"):
            filters["is_terms"].append(tok[3:].lower())
            continue

        # pow/tou comparisons
        m = re.match(r"pow(?:er)?([<>=!]+)(\d+)", low)
        if m:
            filters["power_op"] = (m.group(1), int(m.group(2)))
            continue
        m = re.match(r"tou(?:ghness)?([<>=!]+)(\d+)", low)
        if m:
            filters["toughness_op"] = (m.group(1), int(m.group(2)))
            continue

        # s:set
        if low.startswith("s:"):
            filters["set_code"] = tok[2:].lower()
            continue

        # k:keyword
        if low.startswith("k:"):
            filters["keyword_terms"].append(tok[2:])
            continue

        # Bare word = name search
        filters["name_terms"].append(tok)

    return filters


def _cmp(op: str, val, target) -> bool:
    """Apply a comparison operator."""
    try:
        val = float(val)
        target = float(target)
    except (ValueError, TypeError):
        return False
    if op in ("<=", "=<"):
        return val <= target
    if op in (">=", "=>"):
        return val >= target
    if op in ("=", "=="):
        return val == target
    if op in ("<",):
        return val < target
    if op in (">",):
        return val > target
    if op in ("!=",):
        return val != target
    return False


def _match_card(card: dict, filters: dict) -> bool:
    """Check if a card dict matches all filters."""
    name_lower = card.get("name", "").lower()
    type_lower = card.get("type_line", "").lower()
    oracle_lower = card.get("oracle_text", "").lower()

    # Name terms
    for term in filters["name_terms"]:
        if term.lower() not in name_lower:
            return False

    # Type terms
    for term in filters["type_terms"]:
        if term.lower() not in type_lower:
            return False

    # Oracle text terms
    for term in filters["oracle_terms"]:
        if term.lower() not in oracle_lower:
            return False

    # Colors
    if filters["colors"] is not None:
        card_colors = set(card.get("colors", []))
        if not filters["colors"].issubset(card_colors):
            return False

    # Color identity
    if filters["color_identity"] is not None:
        card_ci = set(card.get("color_identity", []))
        if not filters["color_identity"].issubset(card_ci):
            return False

    # CMC
    if filters["cmc_op"]:
        op, target = filters["cmc_op"]
        if not _cmp(op, card.get("cmc", 0), target):
            return False

    # Format legality
    if filters["format"]:
        legalities = card.get("legalities", {})
        if isinstance(legalities, str):
            try:
                legalities = json.loads(legalities)
            except Exception:
                legalities = {}
        status = legalities.get(filters["format"], "not_legal")
        if status not in ("legal", "restricted"):
            return False

    # Rarity
    if filters["rarity"]:
        if card.get("rarity", "").lower() != filters["rarity"]:
            return False

    # is: keywords
    for term in filters["is_terms"]:
        if term == "legendary":
            if "legendary" not in type_lower:
                return False
        elif term == "instant":
            if "instant" not in type_lower:
                return False
        elif term == "sorcery":
            if "sorcery" not in type_lower:
                return False
        else:
            if term not in type_lower and term not in oracle_lower:
                return False

    # Power/Toughness
    if filters["power_op"]:
        op, target = filters["power_op"]
        if not _cmp(op, card.get("power", ""), target):
            return False
    if filters["toughness_op"]:
        op, target = filters["toughness_op"]
        if not _cmp(op, card.get("toughness", ""), target):
            return False

    # Set code
    if filters["set_code"]:
        if card.get("set", "").lower() != filters["set_code"]:
            return False

    # Keywords
    for kw in filters["keyword_terms"]:
        if kw.lower() not in oracle_lower:
            return False

    return True


# ---------------------------------------------------------------------------
# Search worker
# ---------------------------------------------------------------------------

class _SearchWorker(QThread):
    """Search the Scryfall bulk data in background."""
    results = pyqtSignal(list)
    error   = pyqtSignal(str)

    def __init__(self, query: str, use_filters: dict, meta_only: bool,
                 meta_cards: set | None = None, limit: int = 200):
        super().__init__()
        self._query = query
        self._filters = use_filters
        self._meta_only = meta_only
        self._meta_cards = meta_cards or set()
        self._limit = limit

    def run(self):
        try:
            from scrapers.scryfall import _get_bulk_cache
            cache = _get_bulk_cache()  # name.lower() → card dict
            if not cache:
                self.results.emit([])
                return

            # Deduplicate by canonical name (cache has multiple keys per card)
            seen = set()
            matches = []
            for _key, card in cache.items():
                name = card.get("name") or card.get("canonical_name", "")
                if not name or name in seen:
                    continue

                # Meta-only filter
                if self._meta_only and name not in self._meta_cards:
                    continue

                if _match_card(card, self._filters):
                    seen.add(name)
                    matches.append(card)
                    if len(matches) >= self._limit:
                        break

            # Sort by name
            matches.sort(key=lambda c: c.get("name", "").lower())
            self.results.emit(matches)
        except Exception as e:
            self.error.emit(str(e))


class _MetaUsageWorker(QThread):
    """Query deck_cards table for a card's meta usage."""
    results = pyqtSignal(list)  # list of (archetype, avg_copies, deck_count)
    error   = pyqtSignal(str)

    def __init__(self, card_name: str, fmt: str = None):
        super().__init__()
        self._name = card_name
        self._fmt = fmt

    def run(self):
        try:
            from db.database import get_connection
            conn = get_connection()
            if self._fmt:
                rows = conn.execute("""
                    SELECT d.archetype,
                           ROUND(AVG(dc.quantity), 1) AS avg_copies,
                           COUNT(DISTINCT d.id) AS deck_count
                    FROM deck_cards dc
                    JOIN decks d ON d.id = dc.deck_id
                    JOIN events e ON e.id = d.event_id
                    WHERE dc.card_name = ?
                      AND lower(e.format) = lower(?)
                      AND d.archetype IS NOT NULL AND d.archetype != ''
                    GROUP BY d.archetype
                    ORDER BY deck_count DESC
                    LIMIT 20
                """, [self._name, self._fmt]).fetchall()
            else:
                rows = conn.execute("""
                    SELECT d.archetype,
                           ROUND(AVG(dc.quantity), 1) AS avg_copies,
                           COUNT(DISTINCT d.id) AS deck_count
                    FROM deck_cards dc
                    JOIN decks d ON d.id = dc.deck_id
                    WHERE dc.card_name = ?
                      AND d.archetype IS NOT NULL AND d.archetype != ''
                    GROUP BY d.archetype
                    ORDER BY deck_count DESC
                    LIMIT 20
                """, [self._name]).fetchall()
            conn.close()
            self.results.emit([dict(r) for r in rows])
        except Exception as e:
            self.error.emit(str(e))


class _SimilarCardsWorker(QThread):
    """Find cards with similar text/mechanics via embeddings."""
    results = pyqtSignal(list)  # list of {"name": str, "similarity": float}

    def __init__(self, card_name: str, fmt: str = None):
        super().__init__()
        self._name = card_name
        self._fmt = fmt

    def run(self):
        try:
            from analysis.card_embeddings import find_similar_cards, is_available
            if not is_available():
                self.results.emit([])
                return
            similar = find_similar_cards(self._name, top_n=8,
                                          format_filter=self._fmt)
            self.results.emit(similar)
        except Exception:
            self.results.emit([])


class _CardTrendWorker(QThread):
    """Compute per-week inclusion rate for a card in a format."""
    results = pyqtSignal(dict)

    def __init__(self, card_name: str, fmt: str = None, weeks: int = 12):
        super().__init__()
        self._name = card_name
        self._fmt = fmt or "modern"
        self._weeks = weeks

    def run(self):
        try:
            from analysis.card_adoption import get_card_trend
            self.results.emit(get_card_trend(self._name, self._fmt, self._weeks))
        except Exception:
            self.results.emit({"weeks": [], "rates": []})


class _SubstitutesWorker(QThread):
    """Find functional substitutes via Card2Vec co-occurrence embeddings."""
    results = pyqtSignal(list)

    def __init__(self, card_name: str, fmt: str = None):
        super().__init__()
        self._name = card_name
        self._fmt = fmt

    def run(self):
        try:
            from analysis.cooccurrence_embeddings import (
                find_functional_substitutes, is_trained
            )
            if not is_trained(self._fmt):
                self.results.emit([])
                return
            subs = find_functional_substitutes(self._name, self._fmt, top_n=8)
            self.results.emit(subs)
        except Exception:
            self.results.emit([])


# ---------------------------------------------------------------------------
# Color/rarity helpers
# ---------------------------------------------------------------------------

_RARITY_COLORS = {
    "common":   "#888888",
    "uncommon": "#c0c0c0",
    "rare":     "#d4a017",
    "mythic":   "#e65100",
    "special":  "#9c27b0",
}

_COLOR_SYMBOLS = {"W": "W", "U": "U", "B": "B", "R": "R", "G": "G"}


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class CardBrowserTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list = []
        self._meta_card_set: set | None = None
        self._build_ui()

    def cleanup(self):
        from gui.worker_utils import stop_worker
        for w in self._workers:
            stop_worker(w)
        self._workers.clear()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        layout.setSpacing(6)

        # Header
        header = QLabel("CARD BROWSER")
        header.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(header)

        # Search bar row
        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(
            'Search: card name, or Scryfall syntax like  t:creature c:red cmc<=3  '
            'o:"draw a card" f:standard  r:mythic  is:legendary  k:flying'
        )
        self._search_input.setFont(QFont("Consolas", 10))
        self._search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self._search_input, 1)

        self._search_btn = QPushButton(btn_icon("search"), "Search")
        self._search_btn.setStyleSheet(theme.btn_primary())
        self._search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self._search_btn)
        layout.addLayout(search_row)

        # Filter row
        filt_row = QHBoxLayout()

        filt_row.addWidget(QLabel("Format:"))
        self._fmt_filter = QComboBox()
        self._fmt_filter.addItems(["(any)", "standard", "pioneer", "modern", "legacy", "pauper"])
        self._fmt_filter.setFixedWidth(100)
        filt_row.addWidget(self._fmt_filter)

        filt_row.addWidget(QLabel("Color:"))
        self._color_filter = QComboBox()
        self._color_filter.addItems([
            "(any)", "White", "Blue", "Black", "Red", "Green",
            "Colorless", "Multicolor",
        ])
        self._color_filter.setFixedWidth(100)
        filt_row.addWidget(self._color_filter)

        filt_row.addWidget(QLabel("Type:"))
        self._type_filter = QComboBox()
        self._type_filter.addItems([
            "(any)", "Creature", "Instant", "Sorcery", "Enchantment",
            "Artifact", "Planeswalker", "Land", "Battle",
        ])
        self._type_filter.setFixedWidth(110)
        filt_row.addWidget(self._type_filter)

        filt_row.addWidget(QLabel("Rarity:"))
        self._rarity_filter = QComboBox()
        self._rarity_filter.addItems(["(any)", "common", "uncommon", "rare", "mythic"])
        self._rarity_filter.setFixedWidth(95)
        filt_row.addWidget(self._rarity_filter)

        filt_row.addWidget(QLabel("CMC:"))
        self._cmc_op = QComboBox()
        self._cmc_op.addItems(["any", "=", "<=", ">=", "<", ">"])
        self._cmc_op.setFixedWidth(55)
        filt_row.addWidget(self._cmc_op)
        self._cmc_val = QSpinBox()
        self._cmc_val.setRange(0, 20)
        self._cmc_val.setFixedWidth(50)
        filt_row.addWidget(self._cmc_val)

        self._meta_toggle = QCheckBox("Cards in Meta only")
        self._meta_toggle.setToolTip(
            "Show only cards that appear in your local tournament decks"
        )
        filt_row.addWidget(self._meta_toggle)

        filt_row.addStretch()

        self._result_count = QLabel("")
        self._result_count.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        filt_row.addWidget(self._result_count)

        layout.addLayout(filt_row)

        # Splitter: results table (left) / card detail (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: results table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Name", "Mana Cost", "Type", "CMC", "Rarity", "Set"
        ])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        for col in (1, 3, 4, 5):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(self._on_card_selected)

        # Install card tooltip
        try:
            from gui.widgets.card_tooltip import install_card_tooltip
            install_card_tooltip(self._table, card_name_column=0)
        except Exception:
            pass

        splitter.addWidget(self._table)

        # Right: card detail panel
        detail_frame = QFrame()
        detail_lay = QVBoxLayout(detail_frame)
        detail_lay.setContentsMargins(4, 4, 4, 4)

        # Card image
        self._detail_image = QLabel("Select a card\nto view details")
        self._detail_image.setFixedHeight(340)
        self._detail_image.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._detail_image.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        detail_lay.addWidget(self._detail_image)

        # Card info
        self._detail_info = QTextBrowser()
        self._detail_info.setFont(QFont("Consolas", 10))
        self._detail_info.setOpenExternalLinks(False)
        self._detail_info.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        detail_lay.addWidget(self._detail_info, 1)

        splitter.addWidget(detail_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, 1)

        # Status
        self._status = QLabel(
            "Search the full Scryfall card database. "
            "Supports Scryfall syntax: t:creature c:red cmc<=3 o:\"draw\" f:standard"
        )
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _build_filters(self) -> dict:
        """Combine text query + dropdown filters into a single filter dict."""
        raw = self._search_input.text().strip()
        filters = _parse_query(raw)

        # Format dropdown
        fmt_text = self._fmt_filter.currentText()
        if fmt_text != "(any)" and not filters["format"]:
            filters["format"] = fmt_text

        # Color dropdown
        color_text = self._color_filter.currentText()
        if color_text != "(any)" and filters["colors"] is None:
            _map = {
                "White": {"W"}, "Blue": {"U"}, "Black": {"B"},
                "Red": {"R"}, "Green": {"G"},
            }
            if color_text in _map:
                filters["colors"] = _map[color_text]
            elif color_text == "Colorless":
                # Special: we'll handle this in _match_card_extended
                filters["_colorless"] = True
            elif color_text == "Multicolor":
                filters["_multicolor"] = True

        # Type dropdown
        type_text = self._type_filter.currentText()
        if type_text != "(any)" and not filters["type_terms"]:
            filters["type_terms"].append(type_text.lower())

        # Rarity dropdown
        rarity_text = self._rarity_filter.currentText()
        if rarity_text != "(any)" and not filters["rarity"]:
            filters["rarity"] = rarity_text

        # CMC dropdown
        cmc_op_text = self._cmc_op.currentText()
        if cmc_op_text != "any" and not filters["cmc_op"]:
            filters["cmc_op"] = (cmc_op_text, self._cmc_val.value())

        return filters

    def _do_search(self):
        filters = self._build_filters()

        # Check if we have any filter at all
        has_filter = (
            filters["name_terms"] or filters["type_terms"] or
            filters["oracle_terms"] or filters["colors"] is not None or
            filters.get("_colorless") or filters.get("_multicolor") or
            filters["cmc_op"] or filters["format"] or filters["rarity"] or
            filters["is_terms"] or filters["power_op"] or
            filters["toughness_op"] or filters["set_code"] or
            filters["keyword_terms"] or filters.get("color_identity") or
            self._meta_toggle.isChecked()
        )
        if not has_filter:
            self._status.setText("Enter a search query or select filters.")
            return

        self._status.setText("Searching...")
        self._search_btn.setEnabled(False)
        self._table.setRowCount(0)

        meta_only = self._meta_toggle.isChecked()
        meta_cards = None
        if meta_only:
            meta_cards = self._get_meta_cards()

        worker = _SearchWorkerExtended(
            filters=filters,
            meta_only=meta_only,
            meta_cards=meta_cards,
        )
        worker.results.connect(self._on_results)
        worker.error.connect(self._on_search_error)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._workers.append(worker)

    def _get_meta_cards(self) -> set:
        """Get set of card names that appear in the deck_cards table."""
        if self._meta_card_set is not None:
            return self._meta_card_set
        try:
            from db.database import get_connection
            conn = get_connection()
            rows = conn.execute(
                "SELECT DISTINCT card_name FROM deck_cards"
            ).fetchall()
            conn.close()
            self._meta_card_set = {r[0] for r in rows}
            return self._meta_card_set
        except Exception:
            return set()

    def _on_results(self, cards: list):
        self._search_btn.setEnabled(True)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(cards))

        for row, card in enumerate(cards):
            name = card.get("name", "")
            mana = card.get("mana_cost", "")
            type_line = card.get("type_line", "")
            cmc = card.get("cmc", 0)
            rarity = card.get("rarity", "")
            set_code = card.get("set", "").upper()

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, card)
            self._table.setItem(row, 0, name_item)

            self._table.setItem(row, 1, QTableWidgetItem(mana))
            self._table.setItem(row, 2, QTableWidgetItem(type_line))

            cmc_item = QTableWidgetItem()
            cmc_item.setData(Qt.ItemDataRole.DisplayRole, int(cmc) if cmc == int(cmc) else cmc)
            self._table.setItem(row, 3, cmc_item)

            rarity_item = QTableWidgetItem(rarity.capitalize())
            rcolor = _RARITY_COLORS.get(rarity, theme.TEXT_FG)
            rarity_item.setForeground(QColor(rcolor))
            self._table.setItem(row, 4, rarity_item)

            self._table.setItem(row, 5, QTableWidgetItem(set_code))

        self._table.setSortingEnabled(True)
        self._result_count.setText(f"{len(cards)} results")
        self._status.setText(
            f"Found {len(cards)} cards"
            + (" (capped at 200)" if len(cards) >= 200 else "")
        )

    def _on_search_error(self, msg: str):
        self._search_btn.setEnabled(True)
        self._status.setText(f"Search error: {msg}")

    # ------------------------------------------------------------------
    # Card detail
    # ------------------------------------------------------------------

    def _on_card_selected(self, row, col, prev_row, prev_col):
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        card = item.data(Qt.ItemDataRole.UserRole)
        if not card:
            return

        self._show_card_detail(card)

    def _show_card_detail(self, card: dict):
        name = card.get("name", "")

        # Load image
        self._detail_image.setText("Loading image...")
        try:
            from gui.widgets.card_tooltip import _FetchWorker as _ImgFetch, _IMAGE_CACHE
            if name in _IMAGE_CACHE and _IMAGE_CACHE[name]:
                pix = _IMAGE_CACHE[name].scaledToWidth(
                    240, Qt.TransformationMode.SmoothTransformation)
                self._detail_image.setPixmap(pix)
            else:
                w = _ImgFetch(name)
                def _on_img(n, pix, _name=name):
                    if pix and _name == name:
                        self._detail_image.setPixmap(
                            pix.scaledToWidth(
                                240, Qt.TransformationMode.SmoothTransformation))
                    elif not pix:
                        self._detail_image.setText("No image available")
                w.done.connect(_on_img)
                w.finished.connect(w.deleteLater)
                w.start()
                self._workers.append(w)
        except Exception:
            self._detail_image.setText("Image unavailable")

        # Build info HTML
        html = self._build_detail_html(card)
        self._detail_info.setHtml(html)

        # Fetch meta usage
        fmt_text = self._fmt_filter.currentText()
        fmt = None if fmt_text == "(any)" else fmt_text
        usage_worker = _MetaUsageWorker(name, fmt)
        usage_worker.results.connect(
            lambda rows, _name=name: self._on_meta_usage(rows, _name))
        usage_worker.finished.connect(usage_worker.deleteLater)
        usage_worker.start()
        self._workers.append(usage_worker)

        # Fetch weekly inclusion trend
        trend_worker = _CardTrendWorker(name, fmt or "modern")
        trend_worker.results.connect(
            lambda data, _name=name: self._on_card_trend(data, _name))
        trend_worker.finished.connect(trend_worker.deleteLater)
        trend_worker.start()
        self._workers.append(trend_worker)

        # Fetch similar cards (embeddings)
        sim_worker = _SimilarCardsWorker(name, fmt)
        sim_worker.results.connect(
            lambda rows, _name=name: self._on_similar_cards(rows, _name))
        sim_worker.finished.connect(sim_worker.deleteLater)
        sim_worker.start()
        self._workers.append(sim_worker)

        # Fetch functional substitutes (Card2Vec)
        sub_worker = _SubstitutesWorker(name, fmt)
        sub_worker.results.connect(
            lambda rows, _name=name: self._on_substitutes(rows, _name))
        sub_worker.finished.connect(sub_worker.deleteLater)
        sub_worker.start()
        self._workers.append(sub_worker)

    def _build_detail_html(self, card: dict) -> str:
        name = card.get("name", "")
        mana = card.get("mana_cost", "")
        type_line = card.get("type_line", "")
        oracle = card.get("oracle_text", "")
        rarity = card.get("rarity", "").capitalize()
        set_code = card.get("set", "").upper()
        power = card.get("power", "")
        toughness = card.get("toughness", "")
        cmc = card.get("cmc", 0)

        parts = []
        parts.append(f"<h3 style='color:{theme.ACCENT}; margin:2px 0;'>{_esc(name)}</h3>")
        if mana:
            parts.append(f"<b>Mana:</b> {_esc(mana)} &nbsp; <b>CMC:</b> {cmc}")
        parts.append(f"<b>Type:</b> {_esc(type_line)}")
        if oracle:
            parts.append("<hr style='border-color:#555;'>")
            for line in oracle.split("\n"):
                parts.append(f"<p style='margin:2px 0;'>{_esc(line)}</p>")
        if power and toughness:
            parts.append(f"<b>P/T:</b> {power}/{toughness}")
        parts.append(f"<b>Rarity:</b> "
                      f"<span style='color:{_RARITY_COLORS.get(rarity.lower(), '#fff')};'>"
                      f"{rarity}</span> &nbsp; <b>Set:</b> {set_code}")

        # Legalities
        legalities = card.get("legalities", {})
        if isinstance(legalities, str):
            try:
                legalities = json.loads(legalities)
            except Exception:
                legalities = {}

        if legalities:
            parts.append("<hr style='border-color:#555;'>")
            parts.append("<b>Format Legality:</b><br>")
            for fmt in ("standard", "pioneer", "modern", "legacy", "pauper", "vintage"):
                status = legalities.get(fmt, "unknown")
                if status == "legal":
                    color = "#3cb44b"
                    sym = "Legal"
                elif status == "banned":
                    color = "#e6194b"
                    sym = "Banned"
                elif status == "restricted":
                    color = "#f58231"
                    sym = "Restricted"
                elif status == "not_legal":
                    color = "#888"
                    sym = "Not Legal"
                else:
                    color = "#888"
                    sym = status.replace("_", " ").title()
                parts.append(
                    f"&nbsp;&nbsp;<span style='color:{color};'>{sym}</span> "
                    f"— {fmt.capitalize()}<br>"
                )

        # Weekly inclusion trend placeholder
        parts.append("<hr style='border-color:#555;'>")
        parts.append(f"<div id='card-trend'><i style='color:{theme.TEXT_DIM};'>"
                      "Loading inclusion trend...</i></div>")

        # Meta usage placeholder
        parts.append("<hr style='border-color:#555;'>")
        parts.append(f"<div id='meta-usage'><i style='color:{theme.TEXT_DIM};'>"
                      "Loading meta usage...</i></div>")

        # Similar cards placeholder
        parts.append("<hr style='border-color:#555;'>")
        parts.append(f"<div id='similar-cards'><i style='color:{theme.TEXT_DIM};'>"
                      "Loading similar cards...</i></div>")

        # Functional substitutes placeholder
        parts.append(f"<div id='substitutes'><i style='color:{theme.TEXT_DIM};'>"
                      "Loading functional substitutes...</i></div>")

        return "".join(parts)

    def _on_card_trend(self, data: dict, card_name: str):
        """Render a compact weekly inclusion-rate sparkline in the detail panel."""
        current_row = self._table.currentRow()
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item and item.text() != card_name:
                return

        weeks = data.get("weeks") or []
        rates = data.get("rates") or []
        fmt = (data.get("format") or "modern").capitalize()

        if not weeks:
            html_block = (f"<i style='color:{theme.TEXT_DIM};'>"
                          f"No {fmt} decks in the last 12 weeks — nothing "
                          f"to trend.</i>")
        else:
            # Unicode block sparkline (8 levels). Max rate anchors the top.
            blocks = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
            peak = max(rates) if rates else 0.0
            def _spark(r):
                if peak <= 0:
                    return blocks[0]
                idx = min(len(blocks) - 1, int(round(r / peak * (len(blocks) - 1))))
                return blocks[idx]
            sparkline = "".join(_spark(r) for r in rates)

            first_pct = round(rates[0] * 100, 1)
            last_pct = round(rates[-1] * 100, 1)
            delta = round(last_pct - first_pct, 1)
            arrow = ("\u2197" if delta > 1 else
                     ("\u2198" if delta < -1 else "\u2192"))
            color = (theme.OK if delta > 1 else
                     (theme.ERR if delta < -1 else theme.TEXT_DIM))
            total = data.get("total_decks", 0)
            inclusions = data.get("total_inclusions", 0)

            html_block = (
                f"<b>Inclusion Trend ({fmt}, last {len(weeks)} weeks):</b><br>"
                f"<span style='font-family:Consolas,monospace;font-size:14px;'>"
                f"{sparkline}</span><br>"
                f"{first_pct}% &rarr; {last_pct}% "
                f"<span style='color:{color};'>({arrow} "
                f"{'+' if delta >= 0 else ''}{delta} pts)</span><br>"
                f"<span style='color:{theme.TEXT_DIM};font-size:11px;'>"
                f"Across {total:,} {fmt} decks, {inclusions:,} played the card."
                f"</span>"
            )

        html = self._detail_info.toHtml()
        html = html.replace("Loading inclusion trend...", html_block)
        self._detail_info.setHtml(html)

    def _on_meta_usage(self, rows: list, card_name: str):
        """Append meta usage data to the detail panel."""
        # Check we're still looking at the same card
        current_row = self._table.currentRow()
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item and item.text() != card_name:
                return

        html = self._detail_info.toHtml()
        usage_html = ""
        if rows:
            usage_html = f"<b>Meta Usage ({len(rows)} archetypes):</b><br>"
            usage_html += ("<table cellpadding='2' style='font-size:11px;'>"
                           "<tr><th align='left'>Archetype</th>"
                           "<th>Decks</th><th>Avg Copies</th></tr>")
            for r in rows:
                arch = r.get("archetype", "")
                dc = r.get("deck_count", 0)
                avg = r.get("avg_copies", 0)
                usage_html += (f"<tr><td>{_esc(arch)}</td>"
                               f"<td align='center'>{dc}</td>"
                               f"<td align='center'>{avg}</td></tr>")
            usage_html += "</table>"
        else:
            usage_html = (f"<i style='color:{theme.TEXT_DIM};'>"
                          "Not found in any tournament decks.</i>")

        # Replace the placeholder
        html = html.replace(
            "Loading meta usage...",
            usage_html
        )
        self._detail_info.setHtml(html)


    def _on_similar_cards(self, similar: list, card_name: str):
        """Append similar cards data to the detail panel."""
        current_row = self._table.currentRow()
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item and item.text() != card_name:
                return

        html = self._detail_info.toHtml()
        if similar:
            sim_html = f"<b>Similar Cards (by text/mechanics):</b><br>"
            sim_html += ("<table cellpadding='2' style='font-size:11px;'>"
                         "<tr><th align='left'>Card</th>"
                         "<th>Similarity</th></tr>")
            for s in similar:
                pct = s["similarity"] * 100
                color = (theme.OK if pct >= 85 else
                         theme.ACCENT if pct >= 75 else
                         theme.TEXT_DIM)
                sim_html += (f"<tr><td>{_esc(s['name'])}</td>"
                             f"<td align='center' style='color:{color};'>"
                             f"{pct:.0f}%</td></tr>")
            sim_html += "</table>"
        else:
            sim_html = (f"<i style='color:{theme.TEXT_DIM};'>"
                        "No embedding data available. Download card embeddings "
                        "in Settings.</i>")

        html = html.replace("Loading similar cards...", sim_html)
        self._detail_info.setHtml(html)

    def _on_substitutes(self, subs: list, card_name: str):
        """Append functional substitutes to the detail panel."""
        current_row = self._table.currentRow()
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item and item.text() != card_name:
                return

        html = self._detail_info.toHtml()
        if subs:
            sub_html = f"<b>Functional Substitutes (by deck usage):</b><br>"
            sub_html += ("<table cellpadding='2' style='font-size:11px;'>"
                         "<tr><th align='left'>Card</th>"
                         "<th>Match</th></tr>")
            for s in subs:
                pct = s["similarity"] * 100
                color = (theme.OK if pct >= 70 else
                         theme.ACCENT if pct >= 50 else
                         theme.TEXT_DIM)
                sub_html += (f"<tr><td>{_esc(s['name'])}</td>"
                             f"<td align='center' style='color:{color};'>"
                             f"{pct:.0f}%</td></tr>")
            sub_html += "</table>"
        else:
            sub_html = (f"<i style='color:{theme.TEXT_DIM};'>"
                        "No Card2Vec model trained yet. "
                        "Train in Settings.</i>")

        html = html.replace("Loading functional substitutes...", sub_html)
        self._detail_info.setHtml(html)


def _esc(text: str) -> str:
    """HTML-escape text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Extended search worker (handles colorless/multicolor special filters)
# ---------------------------------------------------------------------------

class _SearchWorkerExtended(QThread):
    results = pyqtSignal(list)
    error   = pyqtSignal(str)

    def __init__(self, filters: dict, meta_only: bool = False,
                 meta_cards: set | None = None, limit: int = 200):
        super().__init__()
        self._filters = filters
        self._meta_only = meta_only
        self._meta_cards = meta_cards or set()
        self._limit = limit

    def run(self):
        try:
            from scrapers.scryfall import _get_bulk_cache
            cache = _get_bulk_cache()
            if not cache:
                self.results.emit([])
                return

            is_colorless = self._filters.pop("_colorless", False)
            is_multicolor = self._filters.pop("_multicolor", False)

            seen = set()
            matches = []
            for _key, card in cache.items():
                name = card.get("name") or card.get("canonical_name", "")
                if not name or name in seen:
                    continue

                if self._meta_only and name not in self._meta_cards:
                    continue

                if is_colorless:
                    colors = card.get("colors", [])
                    if colors:
                        continue
                if is_multicolor:
                    colors = card.get("colors", [])
                    if len(colors) < 2:
                        continue

                if _match_card(card, self._filters):
                    seen.add(name)
                    matches.append(card)
                    if len(matches) >= self._limit:
                        break

            matches.sort(key=lambda c: c.get("name", "").lower())
            self.results.emit(matches)
        except Exception as e:
            self.error.emit(str(e))
