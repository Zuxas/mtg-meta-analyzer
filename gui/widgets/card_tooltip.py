"""
Card image tooltip — shows Scryfall card images on hover.

Usage:
    Install on any QTableWidget:
        install_card_tooltip(table, card_name_column=0)

    The tooltip appears when the mouse hovers over a card name cell.
    Images are fetched from Scryfall API on a background thread and
    cached in memory for the session (no disk writes).
"""
import time
from urllib.parse import quote

from PyQt6.QtWidgets import QLabel, QWidget, QTableWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QTimer
from PyQt6.QtGui import QPixmap, QCursor, QColor, QPainter, QFont

import gui.theme as theme

# In-memory session cache: card_name → QPixmap (or None for "not found")
_IMAGE_CACHE: dict[str, QPixmap | None] = {}

# Rate limiter — track last fetch time
_last_fetch_time: float = 0.0


class _FetchWorker(QThread):
    """Fetch a single card image from Scryfall in the background."""
    done = pyqtSignal(str, object)  # (card_name, QPixmap or None)

    def __init__(self, card_name: str):
        super().__init__()
        self.card_name = card_name

    def run(self):
        global _last_fetch_time
        try:
            import requests

            # Rate limit: 100ms between requests
            now = time.time()
            wait = 0.1 - (now - _last_fetch_time)
            if wait > 0:
                time.sleep(wait)

            url = f"https://api.scryfall.com/cards/named?fuzzy={quote(self.card_name)}"
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "MTGMetaAnalyzer/1.0"})
            _last_fetch_time = time.time()

            if resp.status_code != 200:
                self.done.emit(self.card_name, None)
                return

            data = resp.json()
            # Normal card
            img_url = None
            uris = data.get("image_uris")
            if uris:
                img_url = uris.get("normal") or uris.get("large") or uris.get("small")
            else:
                # Double-faced card
                faces = data.get("card_faces", [])
                if faces and faces[0].get("image_uris"):
                    img_url = faces[0]["image_uris"].get("normal")

            if not img_url:
                self.done.emit(self.card_name, None)
                return

            img_resp = requests.get(img_url, timeout=15)
            if img_resp.status_code != 200:
                self.done.emit(self.card_name, None)
                return

            pix = QPixmap()
            pix.loadFromData(img_resp.content)
            self.done.emit(self.card_name, pix)

        except Exception:
            self.done.emit(self.card_name, None)


class CardTooltip(QLabel):
    """Borderless floating label that shows a card image near the cursor."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setStyleSheet(
            f"background: {theme.PANEL}; "
            f"border: 2px solid {theme.ACCENT}; "
            f"border-radius: 6px; "
            f"padding: 4px;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._worker = None
        self._pending_name = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_for_card(self, card_name: str, pos: QPoint):
        """Show the tooltip for a card name at the given global position."""
        if not card_name:
            self.hide()
            return

        self._hide_timer.stop()

        # Check cache first
        if card_name in _IMAGE_CACHE:
            pix = _IMAGE_CACHE[card_name]
            if pix is None:
                self._show_placeholder("Image not available", pos)
            else:
                self._show_image(pix, pos)
            return

        # Start background fetch
        self._pending_name = card_name
        self._show_placeholder("Loading\u2026", pos)

        # Cancel old worker
        if self._worker is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass

        self._worker = _FetchWorker(card_name)
        self._worker.done.connect(self._on_image_loaded)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_image_loaded(self, card_name: str, pix):
        _IMAGE_CACHE[card_name] = pix
        if card_name == self._pending_name and self.isVisible():
            if pix:
                self._show_image(pix, self.pos())
            else:
                self._show_placeholder("Image not available", self.pos())

    def _show_image(self, pix: QPixmap, pos: QPoint):
        scaled = pix.scaledToWidth(220, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
        self.adjustSize()
        self.move(pos.x() + 20, pos.y() - 10)
        self.show()

    def _show_placeholder(self, text: str, pos: QPoint):
        self.clear()
        self.setText(text)
        self.setStyleSheet(
            f"background: {theme.PANEL}; "
            f"border: 2px solid {theme.ACCENT}; "
            f"border-radius: 6px; padding: 12px; "
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        self.adjustSize()
        self.move(pos.x() + 20, pos.y() - 10)
        self.show()

    def schedule_hide(self):
        """Hide after a short delay (allows moving to an adjacent cell)."""
        self._hide_timer.start(300)


# Shared tooltip instance (lazy)
_tooltip: CardTooltip | None = None


def _get_tooltip() -> CardTooltip:
    global _tooltip
    if _tooltip is None:
        _tooltip = CardTooltip()
    return _tooltip


def install_card_tooltip(table: QTableWidget, card_name_column: int = 0):
    """Install card image tooltip on a QTableWidget.

    Hovering over cells in card_name_column shows the card image.
    """
    table.setMouseTracking(True)
    table._card_col = card_name_column
    table._last_hover_name = ""

    original_enter = table.enterEvent if hasattr(table, "enterEvent") else None
    original_leave = table.leaveEvent if hasattr(table, "leaveEvent") else None

    def _on_cell_entered(row, col):
        if col != card_name_column:
            _get_tooltip().schedule_hide()
            return
        item = table.item(row, col)
        if not item:
            return
        name = item.text().strip()
        if not name or name in ("MAINBOARD", "SIDEBOARD", "\u2014", ""):
            _get_tooltip().schedule_hide()
            return
        if name == table._last_hover_name:
            return
        table._last_hover_name = name
        _get_tooltip().show_for_card(name, QCursor.pos())

    table.cellEntered.connect(_on_cell_entered)

    def _leave_event(event):
        _get_tooltip().schedule_hide()
        table._last_hover_name = ""
        if original_leave:
            original_leave(event)

    table.leaveEvent = _leave_event
