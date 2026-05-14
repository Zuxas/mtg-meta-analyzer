"""Tests for gui.widgets._palette_actions.

Pure-Python coverage of helpers that don't require Qt or a live DB. The
registration entry points themselves (register_tab_entries, etc.) take a
QMainWindow and aren't tested here.
"""
from gui.widgets._palette_actions import _card_slug


def test_card_slug_normalizes_basic():
    assert _card_slug("Sheoldred, the Apocalypse") == "sheoldred-the-apocalypse"


def test_card_slug_no_collision_on_long_names():
    """Two distinct cards sharing the first 60 characters must produce
    distinct slugs. Previously `[:60]` truncation could collide on DFC /
    split / Adventure card names."""
    shared = "A" * 70
    a = _card_slug(shared + " variant alpha")
    b = _card_slug(shared + " variant beta")
    assert a != b


def test_card_slug_handles_dfc_split_separator():
    """Slugs for // names preserve both halves."""
    front = "Bruna, the Fading Light // Brisela, Voice of Nightmares"
    back = "Brisela, Voice of Nightmares"
    assert _card_slug(front) != _card_slug(back)
    assert "brisela" in _card_slug(front)
    assert "bruna" in _card_slug(front)
