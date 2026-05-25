"""Smoke test for the generalized install_card_hover."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Stub the tooltip's image fetch so a hover Enter event does NOT spawn a
    # real Scryfall _FetchWorker QThread. Pytest runs no Qt event loop, so the
    # worker's deleteLater never fires; an orphaned running QThread lingers and
    # crashes the full suite downstream (native 0xC0000409). The event filter
    # still dispatches Enter -> show_for_card; we just make that a no-op here.
    # (In the real app an event loop processes deleteLater, so this is test-only.)
    monkeypatch.setattr(
        "gui.widgets.card_tooltip.CardTooltip.show_for_card",
        lambda self, *a, **k: None,
    )


def test_install_card_hover_tags_widget():
    from PyQt6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    from gui.widgets.card_tooltip import install_card_hover
    lbl = QLabel("Lightning Strike")
    install_card_hover(lbl, "Lightning Strike")
    assert lbl._hover_card_name == "Lightning Strike"
    # Re-installing updates the name without error
    install_card_hover(lbl, "Make Disappear")
    assert lbl._hover_card_name == "Make Disappear"


def test_install_card_hover_enter_event_does_not_crash():
    from PyQt6.QtWidgets import QApplication, QLabel
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtCore import QPointF
    app = QApplication.instance() or QApplication([])
    from gui.widgets.card_tooltip import install_card_hover
    lbl = QLabel("Island")
    install_card_hover(lbl, "Island")
    # Posting an Enter event through the filter must not raise.
    ev = QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0))
    app.sendEvent(lbl, ev)
    leave = QEvent(QEvent.Type.Leave)
    app.sendEvent(lbl, leave)
