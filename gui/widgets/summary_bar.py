"""
Reusable quick-glance summary bar for tab headers.

Creates a slim one-line bar showing key stats at a glance, rendered as
chips (UI kit, 2026-09-27) instead of one bullet-joined string.
Usage:
    bar = SummaryBar()
    layout.addWidget(bar)
    bar.update("STANDARD", ["3,843 events", "Top meta share (2 weeks): Boros Energy 12.3%"])
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

import gui.theme as theme


def _chip(text: str, role: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("kit", role)
    return lbl


class SummaryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.setFixedHeight(30)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 2, 0, 2)
        self._lay.setSpacing(theme.SPACE_XS + 2)

        self._title = _chip("", "chip-accent")
        self._title.setVisible(False)
        self._lay.addWidget(self._title)
        self._chips: list[QLabel] = []
        self._lay.addStretch(1)

    # Kept for backward compatibility with callers/tests that read it.
    @property
    def _stats(self) -> QLabel:
        joined = "  •  ".join(c.text() for c in self._chips)
        lbl = QLabel(f"    {joined}" if joined else "")
        return lbl

    def update(self, title: str, stats: list[str]):
        """Update the bar. title = left label, stats = list of stat strings."""
        self._title.setText(title)
        self._title.setVisible(bool(title))
        for c in self._chips:
            self._lay.removeWidget(c)
            c.deleteLater()
        self._chips = []
        for i, s in enumerate(stats or []):
            chip = _chip(s, "chip")
            self._lay.insertWidget(1 + i, chip)
            self._chips.append(chip)

    def clear(self):
        self.update("", [])

    def stat_texts(self) -> list[str]:
        return [c.text() for c in self._chips]
