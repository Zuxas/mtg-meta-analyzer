"""CommandPalette — modal QDialog presenting PaletteRegistry results.

Triggered by Ctrl+K from MainWindow. Self-closes on Esc, Enter, or focus loss.
Reuses the dark theme from gui.theme — no separate stylesheet.

Performance note: search() over 32k card entries (when `c:` prefix used) costs
~130ms with rapidfuzz, ~1.5s without. Input is debounced to 80ms via QTimer
so rapid typing doesn't queue up redundant searches.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QLabel,
    QFrame, QHBoxLayout, QWidget,
)

import gui.theme as theme
from gui.widgets.palette_registry import PaletteEntry, PaletteRegistry

# Verified token names from gui/theme.py: PANEL, SURFACE, INPUT, BORDER,
# ACCENT, ACCENT_LT, ACCENT_DK, ACCENT2, TEXT, TEXT_DIM, TEXT_OFF, WARN, OK, ERR.
# There is NO theme.HOVER, NO theme.MUTED, NO theme.WARNING — use rgba()
# literals for hover (matching existing stylesheet patterns) and TEXT_DIM /
# WARN respectively.
CATEGORY_COLORS = {
    "TAB":  theme.ACCENT,
    "ACT":  theme.WARN,
    "ARCH": theme.ACCENT_LT,
    "DECK": theme.OK,
    "CARD": theme.ACCENT2,
}

DEBOUNCE_MS = 80  # input debounce — keeps c: card-search responsive even with rapidfuzz


class _ResultRow(QFrame):
    """Single result row: [TAG] name / secondary."""

    def __init__(self, entry: PaletteEntry):
        super().__init__()
        self.entry = entry
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        tag = QLabel(entry.category)
        tag.setFixedWidth(48)
        tag.setStyleSheet(
            f"color: {CATEGORY_COLORS.get(entry.category, theme.TEXT_DIM)};"
            f" font-size: 10px; font-weight: 600;"
        )
        text = QWidget()
        text_lay = QVBoxLayout(text)
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(0)
        name_lbl = QLabel(entry.name)
        name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        text_lay.addWidget(name_lbl)
        if entry.secondary:
            sec_lbl = QLabel(entry.secondary)
            sec_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            text_lay.addWidget(sec_lbl)
        layout.addWidget(tag)
        layout.addWidget(text, 1)


class CommandPalette(QDialog):
    def __init__(
        self,
        registry: PaletteRegistry,
        recents_provider: Callable[[], list[str]],
        recents_writer: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self._registry = registry
        self._recents_provider = recents_provider
        self._recents_writer = recents_writer
        self._setup_ui()
        self._refresh_results("")

    def _setup_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setModal(True)
        self.setFixedSize(600, 400)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Type to search — prefixes: > actions  # tabs  @ archetypes  : decks  c: cards"
        )
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {theme.TEXT};"
            f" border: none; border-bottom: 1px solid {theme.BORDER};"
            f" padding: 12px; font-size: 14px; }}"
        )
        # Debounce input to keep c: card search responsive even with rapidfuzz
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._refresh_for_current_input)
        self.input.textChanged.connect(self._on_input_changed)
        layout.addWidget(self.input)

        self.list_widget = QListWidget()
        # Selected-item style matches the existing stylesheet pattern (see
        # gui/theme.py: QTableWidget::item:selected uses
        # `rgba(94, 181, 207, 0.15)` with color ACCENT_LT).
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; }}"
            f" QListWidget::item:selected {{"
            f"   background: rgba(94, 181, 207, 0.15);"
            f"   color: {theme.ACCENT_LT};"
            f" }}"
        )
        self.list_widget.itemActivated.connect(self._on_activate)
        layout.addWidget(self.list_widget)

    def _on_input_changed(self, _text: str) -> None:
        self._debounce_timer.start()  # restarts on every keystroke

    def _refresh_for_current_input(self) -> None:
        self._refresh_results(self.input.text())

    def _refresh_results(self, query: str) -> None:
        self.list_widget.clear()
        if not query:
            recents = self._registry.prune_recents(self._recents_provider())
            entries = [self._registry.get(rid) for rid in recents[:5]]
            entries = [e for e in entries if e is not None]
            if not entries:
                entries = self._registry.search("", limit=8)
        else:
            entries = self._registry.search(query, limit=8)

        for e in entries:
            row = _ResultRow(e)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, e.id)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.list_widget.currentItem()
            if current is not None:
                self._on_activate(current)
            return
        if key == Qt.Key.Key_Down:
            row = min(self.list_widget.currentRow() + 1, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(row)
            return
        if key == Qt.Key.Key_Up:
            row = max(self.list_widget.currentRow() - 1, 0)
            self.list_widget.setCurrentRow(row)
            return
        super().keyPressEvent(event)

    def _on_activate(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        entry = self._registry.get(entry_id)
        if entry is None:
            self.accept()
            return
        self._recents_writer(entry_id)
        self.accept()
        # Defer handler call until after the dialog has actually closed,
        # so handlers that open another modal don't fight the palette's focus.
        QTimer.singleShot(0, entry.handler)
