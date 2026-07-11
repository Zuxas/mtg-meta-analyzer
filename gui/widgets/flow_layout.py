"""FlowLayout — a QLayout that wraps child widgets onto additional rows
when the container is too narrow to fit them on one line.

Adapted from Qt's own "Flow Layout" example, ported to PyQt6. Pure layout
geometry, no styling opinions — a drop-in replacement for QHBoxLayout
wherever a filter/toolbar row needs to survive a narrow window without
eliding, clipping, or overlapping its children. Unlike QHBoxLayout, a
FlowLayout never shrinks a child below its sizeHint(): anything that
doesn't fit on the current line moves to the next one instead.

Usage:
    ctrl = FlowLayout(h_spacing=8, v_spacing=4)
    ctrl.addWidget(QLabel("Timeframe:"))
    ctrl.addWidget(combo)
    ...
    root.addLayout(ctrl)

`addStretch()` is a no-op (kept so call sites written for QHBoxLayout
don't need to change) — a flow layout has no trailing space to consume,
since overflow wraps instead of stretching.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0,
                 h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list = []

    def __del__(self):
        while self.count():
            self.takeAt(0)

    # -- QLayout protocol -------------------------------------------------

    def addItem(self, item) -> None:
        self._items.append(item)

    def addStretch(self, stretch: int = 0) -> None:
        """No-op — see module docstring."""
        return

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    # -- Layout logic -------------------------------------------------------

    def horizontalSpacing(self) -> int:
        return self._h_spacing

    def verticalSpacing(self) -> int:
        return self._v_spacing

    def _do_layout(self, rect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        x, y = effective.x(), effective.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            space_x = self._h_spacing
            space_y = self._v_spacing
            item_size = item.sizeHint()
            next_x = x + item_size.width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item_size.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + bottom
