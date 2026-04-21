"""
StatusRow — a combined status label + indeterminate progress bar.

Rolled out to replace the duplicated QLabel+QProgressBar pattern
scattered across simulate / calibration / event_optimizer / heatmap.
Three states:

  busy(text)  — show progress bar, set status, grey text
  done(text)  — hide progress bar, set status, grey text (optional)
  error(text) — hide progress bar, set status, red text
  idle()      — hide progress bar, clear status

Use StatusRow().attach_to(layout) to add it in one call.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar

import gui.theme as theme


class StatusRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_XS)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        lay.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)           # indeterminate
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        self._bar.setVisible(False)
        lay.addWidget(self._bar)

    # ── Public API ────────────────────────────────────────────────────

    def busy(self, text: str = ""):
        """Show progress bar + set status in the default dim style."""
        self._label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._label.setText(text)
        self._bar.setVisible(True)

    def done(self, text: str = ""):
        """Hide progress bar + set status (empty text is fine)."""
        self._label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._label.setText(text)
        self._bar.setVisible(False)

    def error(self, text: str):
        """Hide progress bar + set status in the error color."""
        self._label.setStyleSheet(f"color: {theme.ERR}; font-size: 11px;")
        self._label.setText(text)
        self._bar.setVisible(False)

    def idle(self):
        """Hide progress bar + clear status."""
        self._label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._label.setText("")
        self._bar.setVisible(False)

    def set_text(self, text: str):
        """Set status text without changing progress-bar visibility."""
        self._label.setText(text)

    def label(self) -> QLabel:
        """Escape hatch: direct access for tabs that still need it."""
        return self._label

    def progress(self) -> QProgressBar:
        """Escape hatch: direct access when callers set range / value manually."""
        return self._bar
