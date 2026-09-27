"""
UI kit -- small reusable building blocks that make every tab look related.

Design rules (see docs/superpowers/specs/2026-09-27-ui-kit-sidebar-design.md):
  * Neutral surfaces + ONE accent. Win/loss green/red are the only other
    saturated colors.
  * Sizes come from gui.theme tokens (FONT_*, RADIUS*, SPACE_*), never raw px.
  * Components opt into styling with the dynamic property ``kit`` so the
    additive QSS in theme.kit_stylesheet() never touches existing widgets.

Components:
  StatCard          label / big value / hint card
  KpiStrip          horizontal row of StatCards
  WinRateBar        thin two-tone bar + % text, fades with low sample size
  RecordPill        "5-2" pill tinted by result
  SegmentedControl  mutually-exclusive toggle group (emits valueChanged)
  Toast / toast()   non-blocking notification in the window's corner
  toast_info()      drop-in for QMessageBox.information on short messages
"""
from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QEvent, QObject,
)
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget,
    QPushButton, QButtonGroup, QGraphicsOpacityEffect, QMessageBox,
    QSizePolicy,
)

import gui.theme as theme


def _set_kit(w: QWidget, role: str) -> None:
    """Tag a widget with its kit role and force a QSS re-polish."""
    w.setProperty("kit", role)
    st = w.style()
    if st is not None:
        st.unpolish(w)
        st.polish(w)


# ── StatCard / KpiStrip ────────────────────────────────────────────────────

class StatCard(QFrame):
    """A card with a small caps label, a big value and an optional hint.

        card = StatCard("WIN RATE", "57.1%", "last 30 days")
        card.set_value("58.0%", tone="win")
    """

    _TONES = {
        "neutral": None,
        "win": theme.WIN,
        "loss": theme.LOSS,
        "accent": theme.ACCENT,
    }

    def __init__(self, label: str, value: str = "--", hint: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        _set_kit(self, "card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD + 2, theme.SPACE_MD,
                               theme.SPACE_MD + 2, theme.SPACE_MD)
        lay.setSpacing(2)

        self._label = QLabel(label.upper())
        _set_kit(self._label, "card-label")
        self._value = QLabel(value)
        _set_kit(self._value, "card-value")
        self._hint = QLabel(hint)
        _set_kit(self._hint, "card-hint")
        self._hint.setVisible(bool(hint))

        lay.addWidget(self._label)
        lay.addWidget(self._value)
        lay.addWidget(self._hint)

    def set_value(self, value: str, hint: str | None = None,
                  tone: str = "neutral") -> None:
        self._value.setText(value)
        color = self._TONES.get(tone)
        self._value.setStyleSheet(f"color: {color};" if color else "")
        if hint is not None:
            self._hint.setText(hint)
            self._hint.setVisible(bool(hint))

    def value_text(self) -> str:
        return self._value.text()


class KpiStrip(QWidget):
    """A row of StatCards keyed by id.

        strip = KpiStrip([("wr", "Win rate"), ("rec", "Record")])
        strip.set("wr", "57%", "n=42", tone="win")
    """

    def __init__(self, items: list[tuple[str, str]],
                 parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_SM + 2)
        self._cards: dict[str, StatCard] = {}
        for key, label in items:
            card = StatCard(label)
            self._cards[key] = card
            lay.addWidget(card)

    def set(self, key: str, value: str, hint: str | None = None,
            tone: str = "neutral") -> None:
        self._cards[key].set_value(value, hint, tone)

    def card(self, key: str) -> StatCard:
        return self._cards[key]


# ── WinRateBar ─────────────────────────────────────────────────────────────

class WinRateBar(QWidget):
    """Thin horizontal bar: win share in WIN green, the rest in LOSS red,
    with the percentage drawn to the right. Below theme.LOW_N_THRESHOLD
    matches the bar fades (same honesty rule as the heatmap's GR-8 tint)."""

    def __init__(self, winrate: float | None = None, n: int = 0,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._wr = winrate
        self._n = n
        self.setMinimumWidth(90)
        self.setFixedHeight(18)

    def set_winrate(self, winrate: float | None, n: int = 0) -> None:
        self._wr = winrate
        self._n = n
        self.update()

    def winrate(self) -> float | None:
        return self._wr

    def paintEvent(self, _e):  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_w = 42
        bar_w = max(10, self.width() - text_w - 6)
        bar_h = 6
        y = (self.height() - bar_h) // 2

        if self._wr is None:
            p.setPen(QColor(theme.TEXT_OFF))
            p.drawText(0, 0, self.width(), self.height(),
                       Qt.AlignmentFlag.AlignVCenter, "--")
            p.end()
            return

        wr = max(0.0, min(1.0, float(self._wr)))
        ramp = min(1.0, max(0, self._n) / theme.LOW_N_THRESHOLD) if self._n else 1.0
        alpha = int(theme.LOW_N_ALPHA_FLOOR + (255 - theme.LOW_N_ALPHA_FLOOR) * ramp)

        win_c = QColor(theme.WIN); win_c.setAlpha(alpha)
        loss_c = QColor(theme.LOSS); loss_c.setAlpha(int(alpha * 0.55))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(loss_c)
        p.drawRoundedRect(0, y, bar_w, bar_h, 3, 3)
        p.setBrush(win_c)
        p.drawRoundedRect(0, y, int(bar_w * wr), bar_h, 3, 3)

        fg = theme.winrate_fg(wr)
        fg.setAlpha(max(alpha, 150))
        p.setPen(QPen(fg))
        p.drawText(bar_w + 6, 0, text_w, self.height(),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{wr * 100:.0f}%")
        p.end()


# ── RecordPill ─────────────────────────────────────────────────────────────

class RecordPill(QLabel):
    """'W-L' (or 'W-L-D') pill, tinted green/red/neutral by the result."""

    def __init__(self, wins: int = 0, losses: int = 0, draws: int = 0,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_record(wins, losses, draws)

    def set_record(self, wins: int, losses: int, draws: int = 0) -> None:
        self.setText(f"{wins}-{losses}" + (f"-{draws}" if draws else ""))
        if wins > losses:
            fg, bg = theme.WIN, theme.WIN_BG
        elif losses > wins:
            fg, bg = theme.LOSS, theme.LOSS_BG
        else:
            fg, bg = theme.TEXT_DIM, theme.INPUT
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: {theme.RADIUS_SM}px;"
            f" padding: 1px 8px; font-size: {theme.FONT_SM}px; font-weight: 700;"
        )


# ── SegmentedControl ───────────────────────────────────────────────────────

class SegmentedControl(QFrame):
    """Pill-style exclusive toggle. Replaces a QComboBox when there are
    2-5 short options the user flips between often (format, timeframe,
    play/draw).

        seg = SegmentedControl(["Standard", "Modern", "Pioneer"])
        seg.valueChanged.connect(on_format)
    """

    valueChanged = pyqtSignal(str)

    def __init__(self, options: list[str], current: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        _set_kit(self, "segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(b)
            self._buttons[opt] = b
            lay.addWidget(b)
        start = current if current in self._buttons else (options[0] if options else None)
        if start:
            self._buttons[start].setChecked(True)
        self._group.buttonClicked.connect(
            lambda b: self.valueChanged.emit(b.text()))

    def value(self) -> str | None:
        b = self._group.checkedButton()
        return b.text() if b else None

    def set_value(self, value: str, emit: bool = False) -> None:
        if value in self._buttons:
            self._buttons[value].setChecked(True)
            if emit:
                self.valueChanged.emit(value)


# ── Toasts ─────────────────────────────────────────────────────────────────

_KIND_ACCENT = {
    "info": theme.ACCENT,
    "success": theme.OK,
    "warning": theme.WARN,
    "error": theme.ERR,
}

TOAST_MAX_CHARS = 180   # longer messages keep the modal dialog
TOAST_MAX_LINES = 3
TOAST_MS = 3500


class Toast(QFrame):
    """One notification card. Created and positioned by _ToastHost."""

    closed = pyqtSignal()

    def __init__(self, title: str, text: str, kind: str = "info",
                 parent: QWidget | None = None):
        super().__init__(parent)
        _set_kit(self, "toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(340)
        accent = _KIND_ACCENT.get(kind, theme.ACCENT)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        stripe = QFrame()
        stripe.setFixedWidth(4)
        stripe.setStyleSheet(
            f"background: {accent}; border-top-left-radius: {theme.RADIUS_LG}px;"
            f" border-bottom-left-radius: {theme.RADIUS_LG}px;")
        outer.addWidget(stripe)

        body = QVBoxLayout()
        body.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM + 2,
                                theme.SPACE_MD, theme.SPACE_SM + 2)
        body.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: 700; font-size: {theme.FONT_MD}px;")
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_label.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SM}px;")
        body.addWidget(self.title_label)
        if text:
            body.addWidget(self.text_label)
        outer.addLayout(body, 1)

        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedSize(26, 26)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_OFF}; background: transparent;"
            f" border: none; font-size: {theme.FONT_SM}px; }}"
            f" QPushButton:hover {{ color: {theme.TEXT}; }}")
        close.clicked.connect(self.dismiss)
        outer.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)
        self._anim: QPropertyAnimation | None = None
        self._closing = False

    def start(self, ms: int = TOAST_MS) -> None:
        self.adjustSize()
        self.show()
        self.raise_()
        if ms > 0:
            QTimer.singleShot(ms, self.dismiss)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        anim = QPropertyAnimation(self._fx, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._finish)
        self._anim = anim
        anim.start()

    def _finish(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()


class _ToastHost(QObject):
    """Stacks toasts in the bottom-right corner of one top-level window and
    re-positions them when the window resizes."""

    _HOSTS: dict[int, "_ToastHost"] = {}
    MARGIN = 18
    GAP = 8
    MAX_LIVE = 4

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._win = window
        self._toasts: list[Toast] = []
        window.installEventFilter(self)

    @classmethod
    def for_window(cls, window: QWidget) -> "_ToastHost":
        key = id(window)
        host = cls._HOSTS.get(key)
        if host is None:
            host = cls(window)
            cls._HOSTS[key] = host
            window.destroyed.connect(lambda *_: cls._HOSTS.pop(key, None))
        return host

    def add(self, toast: Toast, ms: int) -> None:
        toast.setParent(self._win)
        toast.closed.connect(lambda t=toast: self._remove(t))
        self._toasts.append(toast)
        live = [t for t in self._toasts if not t._closing]
        for old in live[:-self.MAX_LIVE]:  # never bury the window in toasts
            old.dismiss()
        toast.start(ms)
        self._layout()

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        y = self._win.height() - self.MARGIN
        for t in reversed(self._toasts):
            t.adjustSize()
            y -= t.height()
            t.move(self._win.width() - t.width() - self.MARGIN, y)
            t.raise_()
            y -= self.GAP

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt override)
        if obj is self._win and ev.type() == QEvent.Type.Resize:
            self._layout()
        return False

    def active(self) -> list[Toast]:
        return list(self._toasts)


def toast(parent: QWidget | None, title: str, text: str = "",
          kind: str = "info", ms: int = TOAST_MS) -> Toast | None:
    """Show a non-blocking toast in parent's top-level window.
    Returns the Toast, or None when there is no visible window to host it."""
    win = parent.window() if parent is not None else QApplication.activeWindow()
    if win is None or not win.isVisible():
        return None
    t = Toast(title, text, kind)
    _ToastHost.for_window(win).add(t, ms)
    return t


def _fits_toast(text: str) -> bool:
    text = text or ""
    return len(text) <= TOAST_MAX_CHARS and text.count("\n") < TOAST_MAX_LINES


def toast_info(parent: QWidget | None, title: str, text: str = "",
               *args, **kwargs):
    """Drop-in replacement for QMessageBox.information.

    Short messages become a toast (no click needed). Long messages, extra
    button arguments, or no visible window fall back to the original modal
    dialog, so behavior never gets worse than before.
    """
    if not args and not kwargs and _fits_toast(text):
        kind = "success" if any(
            w in (title or "").lower()
            for w in ("saved", "complete", "exported", "imported", "added")
        ) else "info"
        if toast(parent, title, text, kind) is not None:
            return QMessageBox.StandardButton.Ok
    return QMessageBox.information(parent, title, text, *args, **kwargs)
