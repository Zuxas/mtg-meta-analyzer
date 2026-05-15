"""Popup dialog with a matplotlib line chart of rank progression.

Pulls rank_snapshots time series (newest-first), renders rank_score
over time. Y-tick labels show the tier names (Bronze 1 ... Mythic 1+)
so the climb is human-readable. X-axis = capture date.

Handles the sparse-data case: with <2 snapshots, shows the current
rank as a single point + a "data builds as you play" hint.

Used from MainWindow when the user clicks the rank label on the
Dashboard toolbar.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
)
from PyQt6.QtCore import Qt

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

import gui.theme as theme
from db.rank_snapshots import get_recent, rank_score


# Y-axis labels for rank scores. Bronze 1 = 1, Silver 1 = 101, etc.
# Each tier has 4 levels (1-4). Mythic doesn't cap at 4 but we use 4
# as the visual ceiling for Mythic-without-percentile rendering.
_TIER_BREAKS = [
    (1,   "Bronze 1"),
    (101, "Silver 1"),
    (201, "Gold 1"),
    (301, "Plat 1"),
    (401, "Diamond 1"),
    (501, "Mythic 1"),
]


class RankProgressionDialog(QDialog):
    """Modal popup showing rank-over-time line chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MTGA Rank Progression")
        self.setMinimumSize(720, 480)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        outer.setSpacing(8)

        # ── Header ────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title = QLabel(
            f"<b style='font-size:14px;color:{theme.ACCENT};'>"
            "Rank progression</b>"
        )
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        self._format_combo.addItem("Constructed", "constructed")
        self._format_combo.addItem("Limited", "limited")
        self._format_combo.currentIndexChanged.connect(self._reload)
        header_row.addWidget(self._format_combo)
        outer.addLayout(header_row)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # ── matplotlib canvas ─────────────────────────────────────
        self._fig = Figure(figsize=(7, 4), tight_layout=True,
                            facecolor=theme.BG)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setStyleSheet(f"background: {theme.BG};")
        outer.addWidget(self._canvas, 1)

        # ── Footer ────────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        self._reload()

    def _reload(self) -> None:
        fmt = self._format_combo.currentData() or "constructed"
        try:
            rows = get_recent(format_name=fmt, limit=200)
        except Exception as e:
            self._status.setText(
                f"<span style='color:#e07060;'>Failed to load: {e}</span>"
            )
            return

        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.set_facecolor(theme.PANEL)
        ax.tick_params(colors=theme.TEXT)
        for spine in ax.spines.values():
            spine.set_color(theme.BORDER)

        if not rows:
            self._status.setText(
                "<i style='color:#9aa3b8;'>No rank snapshots yet for this "
                "format. Open the Dashboard to capture one, or wait for "
                "the daily M/W/F pipeline.</i>"
            )
            ax.text(0.5, 0.5, "No data yet",
                    ha="center", va="center",
                    transform=ax.transAxes,
                    color=theme.TEXT_DIM, fontsize=14)
            self._canvas.draw()
            return

        # Sort by timestamp ascending for plotting
        rows = sorted(rows, key=lambda r: r["captured_at_utc"])
        xs, ys = [], []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["captured_at_utc"].replace("Z", "+00:00"))
            except Exception:
                continue
            xs.append(ts)
            ys.append(rank_score(r["class"], r["level"]))

        if len(xs) < 2:
            self._status.setText(
                f"<i style='color:#9aa3b8;'>1 snapshot so far -- "
                f"<b>{rows[0]['class']} {rows[0]['level']}</b> "
                f"({rows[0]['wins']}-{rows[0]['losses']}). The chart "
                f"populates as you play and snapshots accumulate via "
                f"GUI refresh + the daily pipeline.</i>"
            )
            ax.plot(xs, ys, "o", color=theme.ACCENT, markersize=8)
        else:
            n = len(xs)
            first, last = rows[0], rows[-1]
            delta = ys[-1] - ys[0]
            arrow = "+" if delta >= 0 else ""
            color_word = "climbed" if delta > 0 else "dropped" if delta < 0 else "held"
            self._status.setText(
                f"<i style='color:#9aa3b8;'>{n} snapshots from "
                f"<b>{first['class']} {first['level']}</b> -> "
                f"<b>{last['class']} {last['level']}</b> "
                f"({color_word} {arrow}{delta} pts; "
                f"{last['wins']-first['wins']}-{last['losses']-first['losses']} "
                f"in the window).</i>"
            )
            ax.plot(xs, ys, "-o", color=theme.ACCENT, linewidth=2,
                    markersize=5, markerfacecolor=theme.ACCENT)

        # Y-axis: tier-name ticks
        y_min = min(ys) - 50 if ys else 0
        y_max = max(ys) + 50 if ys else 600
        # Snap to nearest 100s for readability
        y_min = max(0, (y_min // 100) * 100)
        y_max = ((y_max // 100) + 1) * 100
        ax.set_ylim(y_min, y_max)
        # Major ticks at tier boundaries; labels
        tick_positions = [b for b, _ in _TIER_BREAKS
                          if y_min - 50 <= b <= y_max + 50]
        tick_labels = [label for b, label in _TIER_BREAKS
                       if y_min - 50 <= b <= y_max + 50]
        if tick_positions:
            ax.set_yticks(tick_positions)
            ax.set_yticklabels(tick_labels, color=theme.TEXT)

        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.set_xlabel("Date", color=theme.TEXT_DIM)
        ax.set_ylabel("Rank", color=theme.TEXT_DIM)
        ax.grid(True, color=theme.BORDER, alpha=0.3)
        ax.set_title(
            f"MTGA {fmt.title()} climb",
            color=theme.TEXT, fontsize=12,
        )

        self._canvas.draw()
