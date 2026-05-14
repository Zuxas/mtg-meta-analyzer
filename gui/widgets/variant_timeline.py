"""Right-sidebar panel for the Match Log tab.

Renders a deck's variant history as vertical rows: variant label, match count,
win rate, Wilson-significance flag, +/- card-swap delta from the previous variant.

Pure widget — no tab coupling, no signals back yet (clicks filter the table
via a callback the parent passes in, see set_on_variant_click)."""
from __future__ import annotations

import json
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QHBoxLayout,
)
from PyQt6.QtCore import Qt

import gui.theme as theme
from db.database import get_connection
from db.deck_variants import variant_diff
from analysis.wilson import classify_tweak

_FLAG_COLORS = {
    "validated": "#5ec27a",
    "promising": "#e2a55c",
    "noisy":     "#9aa3b8",
}


class VariantTimelinePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck_id: Optional[int] = None
        self._on_variant_click: Optional[Callable[[str], None]] = None
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        self._header = QLabel("Pick a deck above to see its variant history")
        self._header.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        self._header.setWordWrap(True)
        outer.addWidget(self._header)

        self._summary = QLabel("")
        self._summary.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 11px;")
        outer.addWidget(self._summary)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._content_layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

    def set_on_variant_click(self, cb: Callable[[str], None]) -> None:
        self._on_variant_click = cb

    def set_deck(self, deck_id: Optional[int]) -> None:
        self._deck_id = deck_id
        self._reload()

    def _clear_rows(self):
        # Remove all child widgets except the trailing stretch
        layout = self._content_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _reload(self):
        self._clear_rows()
        if self._deck_id is None:
            self._header.setText("Pick a deck above to see its variant history")
            self._summary.setText("")
            return

        variants = self._load_variants(self._deck_id)
        if not variants:
            self._header.setText("No variants yet")
            self._summary.setText("Log a match to start tracking variants.")
            return

        from db.saved_decks import get_decks
        deck = next((d for d in get_decks() if d["id"] == self._deck_id), None)
        deck_name = deck["name"] if deck else f"deck {self._deck_id}"

        total_m = sum(v["match_count"] for v in variants)
        total_w = sum(v["win_count"] for v in variants)
        wr = (100.0 * total_w / total_m) if total_m else 0.0
        self._header.setText(f"Variant Timeline — {deck_name}")
        self._summary.setText(
            f"{len(variants)} variants · {total_m} matches · {wr:.1f}% WR"
        )

        for i, v in enumerate(variants):
            prev = variants[i - 1] if i > 0 else None
            row = self._build_row(v, prev, label=f"v{i+1}")
            self._content_layout.insertWidget(i, row)

    def _build_row(self, v: dict, prev: Optional[dict], label: str) -> QWidget:
        row = QFrame()
        flag = "noisy"
        if prev is not None:
            flag = classify_tweak(
                prev_wins=prev["win_count"], prev_total=prev["match_count"],
                curr_wins=v["win_count"], curr_total=v["match_count"],
            )
        border_color = _FLAG_COLORS.get(flag, "#9aa3b8")
        row.setStyleSheet(
            f"QFrame {{ border-left: 3px solid {border_color}; "
            f"background: {theme.PANEL}; border-radius: 3px; padding: 6px 8px; }}"
        )
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        wr = (100.0 * v["win_count"] / v["match_count"]) if v["match_count"] else 0.0
        header = QLabel(
            f"<b>{label}</b> · {v['match_count']} mtch · {wr:.0f}%   "
            f"<span style='color:{border_color}'>● {flag}</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        date_lbl = QLabel(f"{v['first_seen'][:10]} – {v['last_seen'][:10]}")
        date_lbl.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px;")
        layout.addWidget(date_lbl)

        if prev is not None:
            prev_mb = json.loads(prev["mainboard_json"])
            prev_sb = json.loads(prev["sideboard_json"])
            curr_mb = json.loads(v["mainboard_json"])
            curr_sb = json.loads(v["sideboard_json"])
            d = variant_diff(prev_mb, prev_sb, curr_mb, curr_sb)
            lines = []
            for n, q in d["mainboard"]["added"]:
                lines.append(f"+{q} {n}")
            for n, q in d["mainboard"]["removed"]:
                lines.append(f"-{q} {n}")
            sb_lines = []
            for n, q in d["sideboard"]["added"]:
                sb_lines.append(f"+{q} {n} (SB)")
            for n, q in d["sideboard"]["removed"]:
                sb_lines.append(f"-{q} {n} (SB)")
            if lines or sb_lines:
                diff_lbl = QLabel(", ".join(lines + sb_lines))
                diff_lbl.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px;")
                diff_lbl.setWordWrap(True)
                layout.addWidget(diff_lbl)
        else:
            init_lbl = QLabel("(initial)")
            init_lbl.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px;")
            layout.addWidget(init_lbl)

        if self._on_variant_click is not None:
            row.mousePressEvent = lambda _e, h=v["variant_hash"]: self._on_variant_click(h)
            row.setCursor(Qt.CursorShape.PointingHandCursor)

        return row

    def _load_variants(self, deck_id: int) -> list[dict]:
        with get_connection() as conn:
            conn.row_factory = __import__("sqlite3").Row
            rows = conn.execute(
                "SELECT * FROM deck_variants WHERE deck_id=? ORDER BY first_seen",
                (deck_id,),
            ).fetchall()
        return [dict(r) for r in rows]
