"""
Reusable quick-glance summary bar for tab headers.

Creates a slim one-line bar showing key stats at a glance.
Usage:
    bar = SummaryBar()
    layout.addWidget(bar)
    bar.update("STANDARD", ["3,843 events", "Top meta share (2 weeks): Boros Energy 12.3%"])
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PyQt6.QtGui import QFont

import gui.theme as theme


class SummaryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {theme.INPUT}; "
            f"border-bottom: 1px solid {theme.BORDER_LO}; "
            "border-radius: 3px; "
        )
        self.setFixedHeight(30)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(10, 2, 10, 2)
        self._lay.setSpacing(0)

        self._title = QLabel("")
        self._title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {theme.ACCENT}; background: transparent;")
        self._lay.addWidget(self._title)

        self._stats = QLabel("")
        self._stats.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;"
        )
        self._lay.addWidget(self._stats, 1)

    def update(self, title: str, stats: list[str]):
        """Update the bar. title = left label, stats = list of stat strings."""
        self._title.setText(title)
        if stats:
            joined = "  \u2022  ".join(stats)
            self._stats.setText(f"    {joined}")
        else:
            self._stats.setText("")

    def clear(self):
        self._title.setText("")
        self._stats.setText("")
