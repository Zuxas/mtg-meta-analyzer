# tests/test_replay_board_panel.py
"""Offscreen-Qt tests for ReplayBoardPanel."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Avoid Scryfall network on cache miss; panel falls back to text labels.
    monkeypatch.setattr("gui.widgets.card_image_cache.load_pixmap",
                        lambda **kwargs: None)


def _board():
    return {
        "seq": 5,
        "you": {"battlefield": [{"instance_id": 1, "grpid": 100, "name": "Mountain"},
                                {"instance_id": 2, "grpid": 200, "name": "Goblin"}],
                "graveyard": [], "exile": [], "hand": [],
                "hand_count": 3, "library_count": 30,
                "graveyard_count": 0, "exile_count": 0},
        "opp": {"battlefield": [{"instance_id": 9, "grpid": 900, "name": "Bear"}],
                "graveyard": [], "exile": [], "hand": [],
                "hand_count": 5, "library_count": 28,
                "graveyard_count": 1, "exile_count": 0},
    }


def _event(**kw):
    base = {"seq": 5, "card_grpid": 200, "board_diff": [],
            "life_after": {"you": 12, "opp": 7},
            "mana_pool_after": {"you": "{R}", "opp": ""}}
    base.update(kw)
    return base


def test_panel_renders_battlefield_and_counts():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), _event())
    assert sorted(p._battlefield_names("you")) == ["Goblin", "Mountain"]
    assert p._battlefield_names("opp") == ["Bear"]
    assert "12" in p._header_text("you")          # life (from the event)
    assert "7" in p._header_text("opp")           # opp life
    # Hand/Lib/GY/Exile counts are deliberately not shown (M1 data too sparse);
    # the header shows the reliable Battlefield count instead.
    assert "Battlefield 2" in p._header_text("you")
    assert "Hand" not in p._header_text("you")


def test_panel_highlights_current_card():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), _event(card_grpid=200))   # Goblin is the current card
    assert 2 in p._highlighted_instances()       # Goblin's instance_id


def test_panel_show_changes_highlights_diff_instances():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    ev = _event(card_grpid=None,
                board_diff=[{"instance_id": 1, "grpid": 100, "card": "Mountain",
                             "from": "hand", "to": "battlefield", "controller": "you"}])
    p.render(_board(), ev, show_changes=True)
    assert 1 in p._highlighted_instances()       # Mountain just changed
    p.render(_board(), ev, show_changes=False)
    assert 1 not in p._highlighted_instances()


def test_panel_handles_none_event_fields():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), {"seq": 5, "card_grpid": None, "board_diff": [],
                        "life_after": None, "mana_pool_after": None})
    assert p._header_text("you")
