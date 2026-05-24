"""Offscreen-Qt smoke tests for gui/widgets/replay_viewer_window.py."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Stub the Scryfall image fetch so window tests never hit the network
    # (load_pixmap otherwise blocks up to 8s on a cache miss). The viewer
    # falls back to rendering the card name as text when this returns None.
    monkeypatch.setattr(
        "gui.widgets.card_image_cache.load_pixmap",
        lambda **kwargs: None,
    )


def _sample_stream():
    """Minimal but realistic build_event_stream() output: 1 game, 2 turns,
    a phase with a step and a phase without, a cast + counter + life + end."""
    def ev(seq, **kw):
        base = {
            "seq": seq, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
            "step": None, "active_seat": 1, "priority_seat": 1, "actor_seat": 1,
            "kind": "cast_spell", "card_name": None, "card_grpid": None,
            "targets": [], "details": {}, "life_after": {"you": 20, "opp": 20},
            "mana_pool_after": {"you": "", "opp": ""}, "stack_after": [],
            "board_diff": [], "log_offset": None, "revealed_cards": [],
            "shuffle_cause": None,
        }
        base.update(kw)
        return base
    events = [
        ev(0, kind="phase_change", phase="Phase_Beginning", step="Step_Upkeep"),
        ev(1, kind="draw_card", phase="Phase_Beginning", step="Step_Draw",
           card_name="Island"),
        ev(2, kind="phase_change", phase="Phase_Main1", step=None),
        ev(3, kind="cast_spell", phase="Phase_Main1", card_name="Lightning Strike",
           card_grpid=70404,
           targets=[{"name": "Make Disappear", "grpid": 81234, "kind": "spell"}],
           stack_after=[{"name": "Lightning Strike", "controller": "you", "targets": []}]),
        ev(4, kind="counter_spell", phase="Phase_Main1", actor_seat=2,
           card_name="Make Disappear"),
        ev(5, kind="life_change", turn_num=2, phase="Phase_Combat",
           step="Step_CombatDamage", details={"seat": 2, "delta": -3, "from": 20, "to": 17},
           life_after={"you": 20, "opp": 17}),
        ev(6, kind="game_end", turn_num=2, details={"reason": "Concede", "winning_seat": 1}),
    ]
    return {
        "arena_match_id": "test-match", "schema_version": 1,
        "capabilities": {"events": True}, "my_seat": 1, "opp_seat": 2,
        "opp_name": "Bob",
        "match_meta": {
            "event_name": "Constructed_BestOf3_Ranked", "winner_seat": 1,
            "winner_reason": "Concede",
            "key_events_by_turn": [
                {"turn": 1, "kind": "first_spell", "actor": "you", "seq": 3,
                 "card": "Lightning Strike"},
                {"turn": 2, "kind": "concede", "actor": "opp", "seq": 6},
            ],
            "games": [],
        },
        "events": events,
    }


def test_table_model_rows_and_cells():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [e["seq"] for e in s["events"]],
                                  my_seat=1, opp_seat=2, opp_name="Bob")
    assert model.rowCount() == 7
    assert model.columnCount() == 4
    # Row 3 = the cast
    idx = model.index(3, 3)  # Event column
    assert "Lightning Strike" in model.data(idx, Qt.ItemDataRole.DisplayRole)
    # seq <-> row mapping
    assert model.seq_for_row(3) == 3
    assert model.row_for_seq(3) == 3


def test_table_model_visible_subset():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [3, 4], my_seat=1, opp_seat=2,
                                  opp_name="Bob")
    assert model.rowCount() == 2
    assert model.seq_for_row(0) == 3
    assert model.row_for_seq(4) == 1
    assert model.row_for_seq(0) is None  # seq 0 not visible
    # Reset to a different subset
    model.set_visible_seqs([0, 1, 2, 3, 4, 5, 6])
    assert model.rowCount() == 7
