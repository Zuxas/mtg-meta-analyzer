"""
SidebarTabBar -- turns the root QTabWidget into a left sidebar nav.

Why a QTabBar subclass instead of a new QListWidget + QStackedWidget:
main_window.py (command palette, tab-path persistence, Basic/Pro disclosure,
jump-to-SIMULATE callbacks) walks the QTabWidget tree by tabText(). Keeping
QTabWidget and only swapping how its bar looks means none of that changes.

Usage (before any addTab):
    tabs = QTabWidget()
    tabs.setObjectName("rootTabs")
    tabs.setTabBar(SidebarTabBar())
    tabs.setTabPosition(QTabWidget.TabPosition.West)
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon
from PyQt6.QtWidgets import QTabBar, QStyleOptionTab, QWidget

import gui.theme as theme

# Default icon per top-level label (qtawesome Phosphor set). Unknown labels
# simply render without an icon.
DEFAULT_ICONS = {
    "DASHBOARD": "ph.squares-four",
    "META": "ph.chart-bar",
    "DECKS": "ph.cards",
    "SEARCH": "ph.magnifying-glass",
    "TOURNAMENT": "ph.trophy",
    "RESOURCES": "ph.books",
    "PUZZLES": "ph.puzzle-piece",
    "SETTINGS": "ph.gear-six",
}


def nav_icon(name: str, color: str) -> QIcon:
    """Return a qtawesome icon, or an empty QIcon if qtawesome is missing."""
    try:
        import qtawesome as qta
        return qta.icon(name, color=color)
    except Exception:
        return QIcon()


class SidebarTabBar(QTabBar):
    """Vertical nav: icon + horizontal Title-case label, pill highlight."""

    ICON_PX = 18

    def __init__(self, icons: dict[str, str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebarTabBar")
        self._icons = dict(DEFAULT_ICONS if icons is None else icons)
        self._hover = -1
        self.setMouseTracking(True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── geometry ─────────────────────────────────────────────────────
    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802 (Qt override)
        return QSize(theme.SIDEBAR_W, theme.SIDEBAR_ITEM_H)

    def minimumTabSizeHint(self, index: int) -> QSize:  # noqa: N802
        return self.tabSizeHint(index)

    # ── hover tracking ───────────────────────────────────────────────
    def mouseMoveEvent(self, e):  # noqa: N802
        idx = self.tabAt(e.position().toPoint())
        if idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    # ── painting ─────────────────────────────────────────────────────
    @staticmethod
    def display_label(raw: str) -> str:
        """'MATCH LOG' -> 'Match Log' (sidebar reads calmer in Title case;
        tabText() itself is untouched so path lookups keep working)."""
        return " ".join(w.capitalize() if w.isupper() else w for w in raw.split(" "))

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL))

        font = QFont(theme.HEADING_FONT or theme.BODY_FONT or "Segoe UI")
        font.setPixelSize(theme.FONT_MD + 1)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)

        for i in range(self.count()):
            r = self.tabRect(i)
            if not r.isValid() or not self.isTabVisible(i):
                continue
            selected = i == self.currentIndex()
            hovered = i == self._hover and not selected
            pill = QRect(r.x() + 8, r.y() + 3, r.width() - 16, r.height() - 6)

            if selected:
                bg = QColor(theme.ACCENT); bg.setAlpha(34)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(pill, theme.RADIUS, theme.RADIUS)
                p.setBrush(QColor(theme.ACCENT))
                p.drawRoundedRect(QRect(r.x() + 2, pill.y() + 8, 3,
                                        pill.height() - 16), 1.5, 1.5)
            elif hovered:
                bg = QColor(255, 255, 255, 10)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(pill, theme.RADIUS, theme.RADIUS)

            fg = theme.ACCENT if selected else (theme.TEXT if hovered else theme.TEXT_DIM)
            if not self.isTabEnabled(i):
                fg = theme.TEXT_OFF

            x = pill.x() + 12
            raw = self.tabText(i)
            icon_name = self._icons.get(raw.upper())
            if icon_name:
                ic = nav_icon(icon_name, fg)
                if not ic.isNull():
                    iy = pill.y() + (pill.height() - self.ICON_PX) // 2
                    ic.paint(p, QRect(x, iy, self.ICON_PX, self.ICON_PX))
                x += self.ICON_PX + 12

            p.setPen(QColor(fg))
            text_rect = QRect(x, pill.y(), pill.right() - x - 6, pill.height())
            label = p.fontMetrics().elidedText(
                self.display_label(raw), Qt.TextElideMode.ElideRight,
                text_rect.width())
            p.drawText(text_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       label)
        p.end()


def install_sidebar(tabs, icons: dict[str, str] | None = None) -> SidebarTabBar:
    """Convert an EMPTY QTabWidget into the sidebar layout. Call before the
    first addTab (Qt only allows replacing the tab bar while it is empty)."""
    from PyQt6.QtWidgets import QTabWidget
    if tabs.count():
        raise RuntimeError("install_sidebar() must run before any addTab()")
    bar = SidebarTabBar(icons)
    tabs.setObjectName("rootTabs")
    tabs.setTabBar(bar)
    tabs.setTabPosition(QTabWidget.TabPosition.West)
    tabs.setDocumentMode(True)
    # lets the QSS PANEL fill reach the empty space under the last nav item
    tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return bar
