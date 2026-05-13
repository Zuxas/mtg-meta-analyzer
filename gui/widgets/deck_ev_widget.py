"""
gui/widgets/deck_ev_widget.py -- Field-weighted EV view for a saved deck.

Per-deck dashboard that combines paper matchup data + Untapped Bo3 +
SB plan difficulty bumps into a single field-weighted WR with a
matchup-by-matchup breakdown.

Auto-runs when a deck is loaded. Recalc button pulls fresh field shares
from the last 14 days of paper meta.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme


def _wr_color(wr: float) -> QColor:
    """Foreground color for a win-rate value (0..1)."""
    if wr >= 0.60:   return QColor(80, 220, 100)
    if wr >= 0.55:   return QColor(120, 190, 130)
    if wr >= 0.45:   return QColor(theme.TEXT)
    if wr >= 0.40:   return QColor(220, 140, 120)
    return QColor(230, 90, 70)


_SOURCE_COLORS = {
    "paper":    QColor(theme.ACCENT),
    "untapped": QColor(166, 117, 194),  # untapped purple-ish
    "mirror":   QColor(theme.TEXT_DIM),
    "guess":    QColor(theme.WARN),
}


class DeckEvWidget(QWidget):
    """Per-deck field-weighted EV breakdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck_id = None
        self._result = None
        self._build_ui()

    def set_deck(self, deck: dict):
        """Load EV view for the given deck."""
        if not deck or not deck.get("id"):
            self._render_empty()
            return
        self._deck_id = deck["id"]
        self._recompute()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM,
                                theme.SPACE_SM, theme.SPACE_SM)
        root.setSpacing(8)

        # Top: headline EV + recalc button
        header_row = QHBoxLayout()
        self._head_lbl = QLabel("Loading…")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        self._head_lbl.setFont(hf)
        header_row.addWidget(self._head_lbl)
        header_row.addStretch()

        self._recalc_btn = QPushButton("Recalc (pull latest 14d field)")
        self._recalc_btn.setStyleSheet(theme.btn_secondary())
        self._recalc_btn.clicked.connect(self._recompute)
        header_row.addWidget(self._recalc_btn)
        root.addLayout(header_row)

        # Subline: covered field share + low-confidence
        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self._sub_lbl)

        # Best / Worst summary
        bw_row = QHBoxLayout()
        self._best_box = QGroupBox("Top favorable matchups")
        self._best_layout = QVBoxLayout(self._best_box)
        self._best_layout.setContentsMargins(8, 14, 8, 8)
        bw_row.addWidget(self._best_box, 1)
        self._worst_box = QGroupBox("Top unfavorable matchups")
        self._worst_layout = QVBoxLayout(self._worst_box)
        self._worst_layout.setContentsMargins(8, 14, 8, 8)
        bw_row.addWidget(self._worst_box, 1)
        root.addLayout(bw_row)

        # Full breakdown table
        breakdown_lbl = QLabel(
            "<b>Per-matchup breakdown</b>  "
            f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
            "(sorted by contribution to total EV)</span>"
        )
        root.addWidget(breakdown_lbl)
        self._tbl = QTableWidget(0, 8)
        self._tbl.setHorizontalHeaderLabels([
            "Opponent", "Field %", "Pre-board WR", "Post-board WR",
            "Diff", "Source", "N", "Contrib"
        ])
        self._tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setAlternatingRowColors(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci in range(1, 8):
            hh.setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._tbl, 1)

    def _recompute(self):
        if not self._deck_id:
            self._render_empty()
            return
        try:
            from analysis.deck_ev import compute_deck_ev
            self._result = compute_deck_ev(self._deck_id)
        except Exception as exc:
            self._head_lbl.setText(f"Error: {exc}")
            self._sub_lbl.setText("")
            self._tbl.setRowCount(0)
            return

        if "error" in self._result:
            self._head_lbl.setText(f"Error: {self._result['error']}")
            self._sub_lbl.setText("")
            self._tbl.setRowCount(0)
            return

        self._render(self._result)

    def _render_empty(self):
        self._head_lbl.setText("Select a deck on the left.")
        self._sub_lbl.setText("")
        self._tbl.setRowCount(0)
        self._clear_layout(self._best_layout)
        self._clear_layout(self._worst_layout)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render(self, r: dict):
        wr_pct = r["field_weighted_wr"] * 100
        self._head_lbl.setText(f"Field-weighted WR: {wr_pct:.1f}%")
        self._head_lbl.setStyleSheet(
            f"color: {_wr_color(r['field_weighted_wr']).name()};"
        )

        cov = r["field_total_share"] * 100
        low = r["low_confidence_share"] * 100
        self._sub_lbl.setText(
            f"{r['deck_archetype']}  ·  "
            f"covers {cov:.0f}% of expected field  ·  "
            f"<span style='color:{theme.WARN};'>{low:.0f}% low-confidence (n<20)</span>  ·  "
            f"{len(r['rows'])} matchups in field"
        )
        self._sub_lbl.setTextFormat(Qt.TextFormat.RichText)

        # Best / worst summaries
        self._clear_layout(self._best_layout)
        for row in r["best"]:
            edge_pp = (row["post_board_wr"] - 0.5) * 100
            contrib = row["contribution"] * 100
            lbl = QLabel(
                f"<b>{row['opponent']}</b>  "
                f"<span style='color:{theme.OK};'>+{edge_pp:.1f}pp</span>  "
                f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
                f"({row['share']*100:.1f}% field, contrib {contrib:.2f}pp)</span>"
            )
            lbl.setStyleSheet("font-size: 12px;")
            self._best_layout.addWidget(lbl)
        if not r["best"]:
            empty = QLabel("(no >55% post-board matchups)")
            empty.setStyleSheet(f"color: {theme.TEXT_DIM}; font-style: italic;")
            self._best_layout.addWidget(empty)
        self._best_layout.addStretch()

        self._clear_layout(self._worst_layout)
        for row in r["worst"]:
            edge_pp = (row["post_board_wr"] - 0.5) * 100
            contrib = row["contribution"] * 100
            drag = (contrib - 0.5 * row["share"] * 100)
            lbl = QLabel(
                f"<b>{row['opponent']}</b>  "
                f"<span style='color:{theme.ERR};'>{edge_pp:+.1f}pp</span>  "
                f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
                f"({row['share']*100:.1f}% field, drag {drag:+.2f}pp)</span>"
            )
            lbl.setStyleSheet("font-size: 12px;")
            self._worst_layout.addWidget(lbl)
        if not r["worst"]:
            empty = QLabel("(no <45% post-board matchups)")
            empty.setStyleSheet(f"color: {theme.TEXT_DIM}; font-style: italic;")
            self._worst_layout.addWidget(empty)
        self._worst_layout.addStretch()

        # Full table
        rows = r["rows"]
        self._tbl.setRowCount(len(rows))
        for ri, row in enumerate(rows):
            name = QTableWidgetItem(row["opponent"])
            self._tbl.setItem(ri, 0, name)

            share = QTableWidgetItem(f"{row['share']*100:.1f}%")
            share.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tbl.setItem(ri, 1, share)

            pre = QTableWidgetItem(f"{row['pre_board_wr']*100:.1f}%")
            pre.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pre.setForeground(_wr_color(row['pre_board_wr']))
            self._tbl.setItem(ri, 2, pre)

            post = QTableWidgetItem(f"{row['post_board_wr']*100:.1f}%")
            post.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            post.setForeground(_wr_color(row['post_board_wr']))
            self._tbl.setItem(ri, 3, post)

            diff_item = QTableWidgetItem(row.get("difficulty") or "—")
            diff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            diff_colors = {"Easy": theme.OK, "Medium": theme.WARN, "Hard": theme.ERR}
            if row.get("difficulty") in diff_colors:
                diff_item.setForeground(QColor(diff_colors[row["difficulty"]]))
            self._tbl.setItem(ri, 4, diff_item)

            src = row["source"]
            src_item = QTableWidgetItem(src)
            src_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            src_item.setForeground(_SOURCE_COLORS.get(src, QColor(theme.TEXT)))
            self._tbl.setItem(ri, 5, src_item)

            n_item = QTableWidgetItem(str(row["sample_n"]) if row["sample_n"] > 0 else "—")
            n_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if row["sample_n"] < 20 and src != "mirror":
                n_item.setForeground(QColor(theme.WARN))
            self._tbl.setItem(ri, 6, n_item)

            contrib_item = QTableWidgetItem(f"{row['contribution']*100:.2f}pp")
            contrib_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tbl.setItem(ri, 7, contrib_item)
