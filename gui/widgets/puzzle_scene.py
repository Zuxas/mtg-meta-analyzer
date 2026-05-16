"""MTGA-style render widget for a puzzle Scene.

Layout (top → bottom):
  1. Opp hand (face-down row, small)
  2. Opp avatar (top-left, absolute) + Opp life circle (top-center, absolute)
  3. Opp lands row (their back)
  4. Opp creatures row (closer to center)
  5. Stack divider
  6. Your creatures row (closer to center)
  7. Your lands row (your back)
  8. Your avatar (bottom-left, absolute) + Your life circle (bottom-center, absolute)
  9. Your hand (fanned, bottom)

Cards render via gui/widgets/card_image_cache. Cards with no Scryfall hit
fall back to a text-placeholder QFrame.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
)

from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
from gui.widgets.card_image_cache import load_pixmap

import gui.theme as theme


_CARD_W, _CARD_H = 76, 106


class PuzzleSceneWidget(QWidget):
    """Render a Scene as an MTGA-styled play table."""

    def __init__(self, scene: Optional[Scene] = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"PuzzleSceneWidget {{ background: {theme.BG}; }} "
            f"QLabel {{ color: {theme.TEXT}; }} "
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(8, 8, 8, 8)
        self._outer.setSpacing(6)
        self._scene: Optional[Scene] = None
        if scene is not None:
            self.set_scene(scene)

    def set_scene(self, scene: Scene) -> None:
        """Replace the rendered scene."""
        self._scene = scene
        # Clear existing children
        while self._outer.count():
            item = self._outer.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        # Top → bottom
        self._outer.addLayout(self._make_opp_header(scene.opp))
        self._outer.addLayout(self._make_card_row(scene.opp.battlefield_lands, label="opp lands"))
        self._outer.addLayout(self._make_card_row(scene.opp.battlefield_creatures, label="opp creatures"))
        self._outer.addWidget(self._make_divider())
        self._outer.addLayout(self._make_card_row(scene.you.battlefield_creatures, label="your creatures"))
        self._outer.addLayout(self._make_card_row(scene.you.battlefield_lands, label="your lands"))
        self._outer.addLayout(self._make_you_header(scene.you))
        self._outer.addLayout(self._make_hand_row(scene.you.hand, label=f"your hand ({len(scene.you.hand)})"))

    # ── Header builders ────────────────────────────────────────
    def _make_opp_header(self, opp: PlayerState) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(self._make_player_label(opp, is_opp=True))
        h.addStretch(1)
        h.addWidget(self._make_life_circle(opp.life, is_opp=True))
        h.addStretch(1)
        h.addWidget(QLabel(f"hand: {len(opp.hand)}"))
        return h

    def _make_you_header(self, you: PlayerState) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(self._make_player_label(you, is_opp=False))
        h.addStretch(1)
        low = you.life <= 5
        h.addWidget(self._make_life_circle(you.life, is_opp=False, low=low))
        h.addStretch(1)
        h.addWidget(QLabel(f"mana: {_format_mana(you.mana_available)}"))
        return h

    def _make_player_label(self, player: PlayerState, *, is_opp: bool) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(w); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(0)
        name = QLabel(f"<b>{player.name}</b>")
        arch = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>{player.archetype}</span>")
        v.addWidget(name); v.addWidget(arch)
        color = theme.ACCENT if not is_opp else "#d88060"
        w.setStyleSheet(f"QFrame {{ border: 1px solid {color}; border-radius: 6px; }}")
        return w

    def _make_life_circle(self, life: int, *, is_opp: bool, low: bool = False) -> QLabel:
        color = "#f04040" if low else ("#d88060" if is_opp else theme.ACCENT)
        lbl = QLabel(str(life))
        lbl.setFixedSize(64, 64)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; border: 3px solid {color}; "
            f"border-radius: 32px; color: {theme.TEXT}; "
            f"font-size: 22px; font-weight: bold; }}"
        )
        return lbl

    def _make_divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {theme.BORDER};")
        return f

    # ── Card rows ──────────────────────────────────────────────
    def _make_card_row(self, cards: list[CardInZone], *, label: str) -> QHBoxLayout:
        h = QHBoxLayout(); h.setSpacing(3)
        tag = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>{label}</span>")
        tag.setFixedWidth(80)
        h.addWidget(tag)
        h.addStretch(1)
        for c in cards:
            h.addWidget(self._make_card_widget(c))
        h.addStretch(1)
        return h

    def _make_hand_row(self, cards: list[CardInZone], *, label: str) -> QHBoxLayout:
        h = QHBoxLayout(); h.setSpacing(3)
        tag = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>{label}</span>")
        tag.setFixedWidth(80)
        h.addWidget(tag)
        h.addStretch(1)
        for c in cards:
            h.addWidget(self._make_card_widget(c, is_hand=True))
        h.addStretch(1)
        return h

    def _make_card_widget(self, card: CardInZone, *, is_hand: bool = False) -> QWidget:
        """Try Scryfall image; fall back to text placeholder."""
        if card.is_face_down:
            return self._make_face_down()
        px: Optional[QPixmap] = None
        if not is_hand or card.name:
            px = load_pixmap(card_name=card.name, grpid=card.grpid)
        if px is not None:
            lbl = QLabel()
            lbl.setPixmap(px.scaled(_CARD_W, _CARD_H,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lbl.setToolTip(self._tooltip_for(card))
            if card.tapped:
                lbl.setStyleSheet("QLabel { padding: 0; transform: rotate(15deg); }")
            return lbl
        return self._make_placeholder(card)

    def _make_face_down(self) -> QLabel:
        lbl = QLabel("")
        lbl.setFixedSize(_CARD_W, _CARD_H)
        lbl.setStyleSheet(
            "QLabel { background: #3d1a1a; border: 1px solid #7d2a2a; border-radius: 4px; }"
        )
        return lbl

    def _make_placeholder(self, card: CardInZone) -> QLabel:
        lbl = QLabel(f"<b>{card.name}</b>")
        lbl.setFixedSize(_CARD_W, _CARD_H)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; border: 1px dashed {theme.ACCENT}; "
            f"border-radius: 4px; padding: 4px; color: {theme.TEXT}; font-size: 9px; }}"
        )
        lbl.setToolTip(self._tooltip_for(card))
        return lbl

    def _tooltip_for(self, card: CardInZone) -> str:
        parts = [card.name]
        if card.power is not None and card.toughness is not None:
            parts.append(f"{card.power}/{card.toughness}")
        if card.tapped:
            parts.append("(tapped)")
        return " · ".join(parts)


def _format_mana(mana: dict[str, int]) -> str:
    """Render a mana dict as a compact string: {'U': 2, 'R': 1} -> 'UUR'."""
    if not mana:
        return "0"
    parts = []
    for color in "WUBRGC":
        parts.extend([color] * mana.get(color, 0))
    return "".join(parts) or "0"
