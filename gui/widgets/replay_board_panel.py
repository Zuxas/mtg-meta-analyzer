# gui/widgets/replay_board_panel.py
"""Board-state panel for the full-depth replay viewer (M3).

Renders a two-row board (opp on top, you on the bottom) from the snapshot
produced by analysis.replay_events.replay_board_at(). Card thumbnails use
gui/widgets/card_image_cache (disk cache) with a text fallback, mirroring
gui/widgets/puzzle_scene.py. Hover shows the full Scryfall image via
gui/widgets/card_tooltip.install_card_hover.

Deferred to later milestones (data not in the M1 contract): tap rotation,
+1/+1 counters, attached auras, combat highlighting, lands/creatures split,
hand thumbnails. See docs/superpowers/plans/2026-05-24-replay-viewer-m3.md.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from gui.widgets.card_image_cache import load_pixmap
from gui.widgets.card_tooltip import install_card_hover
import gui.theme as theme

_CARD_W, _CARD_H = 56, 78


class ReplayBoardPanel(QWidget):
    """Two-row board rendered from a replay_board_at() snapshot + the event."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.PANEL};")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(6, 4, 6, 4)
        self._outer.setSpacing(4)
        self._bf_names: dict[str, list[str]] = {"you": [], "opp": []}
        self._header_txt: dict[str, str] = {"you": "", "opp": ""}
        self._highlighted: set[int] = set()
        self._build_skeleton()

    def _build_skeleton(self) -> None:
        self._rows: dict[str, dict] = {}
        for seat in ("opp", "you"):
            row = QVBoxLayout()
            row.setSpacing(2)
            header = QLabel("")
            header.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            bf = QHBoxLayout()
            bf.setSpacing(3)
            bf_holder = QWidget()
            bf_holder.setLayout(bf)
            row.addWidget(header)
            row.addWidget(bf_holder)
            self._outer.addLayout(row)
            if seat == "opp":
                self._outer.addWidget(self._divider())
            self._rows[seat] = {"header": header, "bf": bf}

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {theme.BORDER};")
        return f

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def render(self, board: dict, event: dict, *, show_changes: bool = False) -> None:
        life = event.get("life_after") or {}
        mana = event.get("mana_pool_after") or {}
        cur_grpid = event.get("card_grpid")
        changed_iids: set[int] = set()
        if show_changes:
            changed_iids = {d.get("instance_id")
                            for d in (event.get("board_diff") or [])
                            if d.get("instance_id") is not None}
        self._highlighted = set()

        for seat in ("opp", "you"):
            seat_board = board.get(seat) or {}
            life_v = life.get(seat)
            mana_v = mana.get(seat)
            header = (
                f"{'You' if seat == 'you' else 'Opp'}  "
                f"Life {life_v if life_v is not None else '?'}  "
                f"Mana {mana_v or '-'}  "
                f"Hand {seat_board.get('hand_count', 0)}  "
                f"Lib {seat_board.get('library_count', 0)}  "
                f"GY {seat_board.get('graveyard_count', 0)}  "
                f"Exile {seat_board.get('exile_count', 0)}"
            )
            self._header_txt[seat] = header
            self._rows[seat]["header"].setText(header)

            bf_layout = self._rows[seat]["bf"]
            self._clear_layout(bf_layout)
            names: list[str] = []
            cards = seat_board.get("battlefield") or []
            for card in cards:
                names.append(card.get("name") or "?")
                iid = card.get("instance_id")
                grp = card.get("grpid")
                highlight = None
                if cur_grpid is not None and grp == cur_grpid:
                    highlight = theme.ACCENT
                elif iid in changed_iids:
                    highlight = theme.WARN
                if highlight is not None and iid is not None:
                    self._highlighted.add(iid)
                bf_layout.addWidget(self._make_card(card, highlight))
            bf_layout.addStretch(1)
            self._bf_names[seat] = names

    def _make_card(self, card: dict, highlight: Optional[str]) -> QWidget:
        name = card.get("name")
        grpid = card.get("grpid")
        border = highlight or theme.BORDER
        px = load_pixmap(card_name=name, grpid=grpid) if name else None
        lbl = QLabel()
        lbl.setFixedSize(_CARD_W, _CARD_H)
        if px is not None:
            lbl.setPixmap(px.scaled(_CARD_W, _CARD_H,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lbl.setStyleSheet(f"border: 2px solid {border};")
        else:
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setText(name or "?")
            lbl.setStyleSheet(
                f"border: 2px solid {border}; background: {theme.INPUT}; "
                f"color: {theme.TEXT}; font-size: 8px;"
            )
        if name:
            lbl.setToolTip(name)
            install_card_hover(lbl, name)
        return lbl

    def _battlefield_names(self, seat: str) -> list:
        return list(self._bf_names.get(seat, []))

    def _header_text(self, seat: str) -> str:
        return self._header_txt.get(seat, "")

    def _highlighted_instances(self) -> set:
        return set(self._highlighted)
