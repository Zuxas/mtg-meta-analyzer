"""
Decklist pane — grouped-by-type deck rendering for the My Decks tab.

Replaces the old raw-text QTextEdit dump with:
  - Cards grouped Creatures / Spells (non-creature) / Lands / Sideboard,
    each group header showing its own card count.
  - A mana-curve mini-bar (CMC 0-7+ buckets) for mainboard nonland cards.
  - Color-identity pips (theme.make_pip_widget) for the deck's archetype.
  - Card-name hover images via gui.widgets.card_tooltip.install_card_hover
    (already the app-standard hover mechanism, e.g. replay_board_panel.py).

Card type/CMC data comes from the local `card_data` table (already
populated by scrapers.scryfall for cards seen in tournament data --
read-only SELECT only, no scraping, no DB writes, no live API calls).
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QBrush

import gui.theme as theme
from gui.widgets.card_tooltip import install_card_hover

_GROUP_ORDER = ("Creatures", "Spells", "Lands", "Sideboard")
_GROUP_LABELS = {
    "Creatures": "CREATURES",
    "Spells":    "SPELLS",
    "Lands":     "LANDS",
    "Sideboard": "SIDEBOARD",
}


def classify_card_type(type_line: str) -> str:
    """Return 'Lands' / 'Creatures' / 'Spells' for a Scryfall type_line.

    Unknown/blank type lines fall back to 'Spells' -- a card with no
    local card_data row still shows up somewhere in the pane rather than
    silently vanishing from the deck view.
    """
    tl = (type_line or "").lower()
    if "land" in tl:
        return "Lands"
    if "creature" in tl:
        return "Creatures"
    return "Spells"


def _card_type_lookup(names) -> dict:
    """Batch, read-only lookup of {name: {"type_line", "cmc"}} from the
    local card_data table. Missing cards are simply absent -- callers
    treat that as an unknown/blank type_line. Never touches the network
    or writes to any table (mirrors the read-only pattern already used
    by MyDecksTab._find_banned_cards)."""
    names = [n for n in names if n]
    if not names:
        return {}
    from db.database import get_combined_connection
    conn = get_combined_connection()
    try:
        placeholders = ",".join("?" * len(names))
        rows = conn.execute(
            f"SELECT name, type_line, cmc FROM card_data WHERE name IN ({placeholders})",
            names,
        ).fetchall()
    finally:
        conn.close()
    return {
        row["name"]: {"type_line": row["type_line"] or "", "cmc": row["cmc"] or 0.0}
        for row in rows
    }


class ManaCurveWidget(QWidget):
    """Theme-consistent CMC 0-7+ mini bar chart, hand-painted with
    QPainter (the same technique theme.make_pip_widget uses for pips --
    stylesheet backgrounds don't clip/scale reliably for custom shapes)."""

    _LABELS = ("0", "1", "2", "3", "4", "5", "6", "7+")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = [0] * 8
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background: transparent;")

    def set_counts(self, counts) -> None:
        """counts: 8 ints for CMC buckets 0,1,2,3,4,5,6,7+ (extra entries
        ignored, short lists zero-padded)."""
        counts = list(counts)[:8]
        counts += [0] * (8 - len(counts))
        self._counts = counts
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._counts)
        if n == 0 or w <= 0 or h <= 0:
            p.end()
            return

        max_c = max(self._counts) or 1
        bar_w = w / n
        label_h = 14
        count_h = 12
        bar_area_h = max(1, h - label_h - count_h)

        for i, c in enumerate(self._counts):
            x = i * bar_w + 2
            bw = max(1.0, bar_w - 4)
            bar_h = (c / max_c) * bar_area_h if c else 0
            y = count_h + (bar_area_h - bar_h)

            if c:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(theme.ACCENT)))
                p.drawRoundedRect(int(x), int(y), int(bw), int(max(bar_h, 2)), 2, 2)
                p.setPen(QColor(theme.TEXT_DIM))
                p.drawText(int(x), 0, int(bw), count_h,
                           Qt.AlignmentFlag.AlignCenter, str(c))

            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(int(x), h - label_h, int(bw), label_h,
                       Qt.AlignmentFlag.AlignCenter, self._LABELS[i])
        p.end()


class DecklistPane(QWidget):
    """Grouped deck view: type-grouped card lists + mana curve + color
    pips + hover images. Replaces the old plain-text decklist dump."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._group_headers: dict[str, QLabel] = {}
        self._name_labels: list[QLabel] = []
        self._pip_widget = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_SM)

        top_row = QHBoxLayout()
        top_row.setSpacing(theme.SPACE_MD)
        self._pip_container = QWidget()
        self._pip_layout = QHBoxLayout(self._pip_container)
        self._pip_layout.setContentsMargins(0, 0, 0, 0)
        self._pip_container.setFixedWidth(70)
        top_row.addWidget(self._pip_container, 0)

        self._curve = ManaCurveWidget()
        top_row.addWidget(self._curve, 1)
        root.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self._groups_layout = QVBoxLayout(inner)
        self._groups_layout.setContentsMargins(4, 4, 4, 4)
        self._groups_layout.setSpacing(theme.SPACE_MD)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset to an empty pane (no deck selected)."""
        self.set_deck({})

    def set_deck(self, deck: dict) -> None:
        """Render `deck` (a saved_decks-shaped dict: mainboard/sideboard/
        archetype). Read-only -- never writes to the DB."""
        while self._groups_layout.count():
            item = self._groups_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        while self._pip_layout.count():
            item = self._pip_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._group_headers.clear()
        self._name_labels.clear()
        self._pip_widget = None

        main = deck.get("mainboard", {}) or {}
        side = deck.get("sideboard", {}) or {}
        archetype = deck.get("archetype", "") or ""

        ident = theme.color_identity(archetype)
        if ident:
            self._pip_widget = theme.make_pip_widget(ident)
            self._pip_layout.addWidget(self._pip_widget)

        all_names = set(main) | set(side)
        type_info = _card_type_lookup(all_names)

        buckets = {"Creatures": [], "Spells": [], "Lands": []}
        curve_counts = [0] * 8
        for name, qty in main.items():
            info = type_info.get(name, {})
            group = classify_card_type(info.get("type_line", ""))
            buckets[group].append((name, qty))
            if group != "Lands":
                cmc = info.get("cmc") or 0.0
                idx = min(max(int(cmc), 0), 7)
                curve_counts[idx] += qty

        for group in ("Creatures", "Spells", "Lands"):
            cards = sorted(buckets[group])
            count = sum(q for _, q in cards)
            self._groups_layout.addWidget(self._make_group_section(group, cards, count))

        side_cards = sorted(side.items())
        side_count = sum(q for _, q in side_cards)
        self._groups_layout.addWidget(
            self._make_group_section("Sideboard", side_cards, side_count)
        )
        self._groups_layout.addStretch()

        self._curve.set_counts(curve_counts)

    def _make_group_section(self, group: str, cards: list, count: int) -> QWidget:
        section = QWidget()
        sl = QVBoxLayout(section)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)

        label = _GROUP_LABELS.get(group, group.upper())
        hdr = QLabel(f"{label} ({count})")
        hdr.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.5px; padding-top: 4px;"
        )
        sl.addWidget(hdr)
        self._group_headers[group] = hdr

        if not cards:
            empty = QLabel("(none)")
            empty.setStyleSheet(f"color: {theme.TEXT_DIM}; font-style: italic; font-size: 11px;")
            sl.addWidget(empty)
            return section

        for name, qty in cards:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 0, 4, 0)
            rl.setSpacing(6)

            qty_lbl = QLabel(f"{qty}")
            qty_lbl.setFixedWidth(18)
            qty_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold; font-size: 11px;")
            rl.addWidget(qty_lbl)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 11px;")
            install_card_hover(name_lbl, name)
            rl.addWidget(name_lbl, 1)
            self._name_labels.append(name_lbl)

            sl.addWidget(row)

        return section
