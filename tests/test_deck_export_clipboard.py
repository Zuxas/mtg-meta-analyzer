"""Deck export: copy the decklist to the clipboard (Arena / MTGO text), the same text the .txt
exports write -- one builder, so the two can never drift apart."""
import os

import pytest
from PyQt6.QtWidgets import QApplication

from gui.widgets import deck_export as de

MAIN = {"Lightning Bolt": 4, "Mountain": 18, "Monastery Swiftspear": 4}
SIDE = {"Smash to Smithereens": 2}


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_deck_text_formats():
    assert de.deck_text(MAIN, SIDE, "mtga") == (
        "Deck\n4 Lightning Bolt\n4 Monastery Swiftspear\n18 Mountain\n\nSideboard\n2 Smash to Smithereens")
    assert de.deck_text(MAIN, SIDE, "mtgo") == (
        "4 Lightning Bolt\n4 Monastery Swiftspear\n18 Mountain\n\nSideboard\n2 Smash to Smithereens")
    assert de.deck_text(MAIN, {}, "mtgo") == "4 Lightning Bolt\n4 Monastery Swiftspear\n18 Mountain"
    avg = [{"name": "Lightning Bolt", "avg_qty": 3.6}]                     # archetype average-deck rows
    assert de.deck_text(avg, [], "mtgo") == "4 Lightning Bolt"


def test_file_exports_write_the_same_text(tmp_path, monkeypatch):
    monkeypatch.setattr(de, "_exports_dir", lambda: str(tmp_path))
    for fn, style in ((de.export_mtgo, "mtgo"), (de.export_mtga, "mtga")):
        path = fn(MAIN, SIDE, "Burn", "modern")
        assert open(path, encoding="utf-8").read() == de.deck_text(MAIN, SIDE, style)


def test_copy_puts_the_list_on_the_clipboard(app):
    n = de.copy_decklist(MAIN, SIDE, "mtga")
    assert QApplication.clipboard().text() == de.deck_text(MAIN, SIDE, "mtga")
    assert n == 4 + 18 + 4 + 2                                             # cards copied (for the toast)
