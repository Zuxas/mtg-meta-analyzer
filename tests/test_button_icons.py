"""Buttons named by the ROADMAP icon item must actually carry icons.

The item read: "Extend icons to remaining text-only buttons (ask_claude /
predictions / card_browser Search button / h2h / vs-field forms)". Probing
the real widgets showed three of those five were already done, so only
SearchTab (which owns the h2h "Show Matchups" and the deck "Search"
buttons) and the vs-field DeckEvWidget "Recalc" button were outstanding.

Deliberately NOT covered here, because it is a wider design decision the
ROADMAP item did not ask for and which cannot be verified headlessly:
HeatmapTab (8 buttons), MyDecksTab (13) and SettingsTab (11) are still
icon-free. HeatmapTab in particular was given a deliberate grouped toolbar
design in GUI polish Wave A (GR-5), so adding icons there should be a
choice, not a side effect of this item.

Icons degrade safely: icons_util.btn_icon returns a null QIcon when
qtawesome is missing or the name is unknown, and Qt then renders a bare
button. So these assertions are skipped rather than failed when qtawesome
is unavailable -- otherwise this file would fail on a machine where the
optional dependency simply is not installed.
"""
import pytest

from PyQt6.QtWidgets import QApplication, QPushButton


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _needs_qtawesome():
    from gui.icons_util import is_available
    if not is_available():
        pytest.skip("qtawesome not installed — icons degrade to null QIcon by design")


def _labelled_buttons(widget):
    return [b for b in widget.findChildren(QPushButton) if b.text().strip()]


def test_search_tab_buttons_all_have_icons(app):
    """Covers the ROADMAP's "h2h" (Show Matchups) and "Search" buttons."""
    from gui.tabs.search import SearchTab

    w = SearchTab()
    try:
        missing = [b.text() for b in _labelled_buttons(w) if b.icon().isNull()]
        assert not missing, f"SearchTab buttons without icons: {missing}"
    finally:
        try:
            w.cleanup()
        except Exception:
            pass


def test_deck_ev_recalc_button_has_an_icon(app):
    """Covers the ROADMAP's "vs-field forms"."""
    from gui.widgets.deck_ev_widget import DeckEvWidget

    w = DeckEvWidget()
    try:
        missing = [b.text() for b in _labelled_buttons(w) if b.icon().isNull()]
        assert not missing, f"DeckEvWidget buttons without icons: {missing}"
    finally:
        try:
            w.cleanup()
        except Exception:
            pass


def test_already_done_tabs_stay_done(app):
    """ask_claude / predictions / card_browser already had icons before this
    change. Pin them so the item cannot silently regress."""
    import importlib

    for cls_name, mod_name in (
        ("AskClaudeTab", "gui.tabs.ask_claude"),
        ("PredictionsTab", "gui.tabs.predictions"),
        ("CardBrowserTab", "gui.tabs.card_browser"),
    ):
        w = getattr(importlib.import_module(mod_name), cls_name)()
        try:
            missing = [b.text() for b in _labelled_buttons(w) if b.icon().isNull()]
            assert not missing, f"{cls_name} buttons without icons: {missing}"
        finally:
            try:
                w.cleanup()
            except Exception:
                pass


def test_btn_helper_is_still_optional(app):
    """search.py's local _btn() must work with no icon argument — the icon is
    an addition, not a new requirement."""
    from gui.tabs.search import _btn

    plain = _btn("No Icon Here")
    assert plain.text() == "No Icon Here"
    assert plain.icon().isNull(), "a button asking for no icon should not get one"


def test_unknown_icon_name_degrades_instead_of_raising(app):
    """btn_icon returns a null QIcon for an unknown name, so a typo makes a
    plain button rather than crashing a tab at construction."""
    from gui.tabs.search import _btn

    w = _btn("Typo", icon="definitely-not-an-icon-name")
    assert w.icon().isNull()
