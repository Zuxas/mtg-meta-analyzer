"""Smoke test for the generalized install_card_hover."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


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
