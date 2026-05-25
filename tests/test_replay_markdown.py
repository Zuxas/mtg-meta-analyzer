# tests/test_replay_markdown.py
"""Tests for gui.replay_view_model.replay_markdown (headless, no Qt)."""
from gui import replay_view_model as vm


def _stream():
    def ev(seq, **kw):
        base = {"seq": seq, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
                "step": None, "actor_seat": 1, "active_seat": 1, "kind": "cast_spell",
                "card_name": None, "targets": [], "details": {}}
        base.update(kw)
        return base
    return {
        "my_seat": 1, "opp_seat": 2, "opp_name": "Bob",
        "match_meta": {"event_name": "RC Cincinnati", "winner_seat": 1,
                       "winner_reason": "Concede"},
        "events": [
            ev(3, turn_num=7, kind="cast_spell", card_name="Lightning Strike"),
            ev(5, turn_num=9, kind="life_change",
               details={"delta": -3, "to": 2}),
        ],
    }


def test_markdown_header_notes_and_marks():
    md = vm.replay_markdown(_stream(), [3], "Should have held up the burn.")
    assert "# Replay review" in md
    assert "RC Cincinnati" in md and "Bob" in md
    assert "**Won**" in md and "Concede" in md
    assert "Should have held up the burn." in md
    assert "## Marked events" in md
    assert "Lightning Strike" in md          # the marked event
    assert "T7" in md


def test_markdown_no_marks_and_no_notes():
    md = vm.replay_markdown(_stream(), [], "")
    assert "_(no notes)_" in md
    assert "_(none marked)_" in md


def test_markdown_unknown_result_and_filters_bad_marks():
    s = _stream()
    s["match_meta"]["winner_seat"] = None
    md = vm.replay_markdown(s, [3, 999], "")   # 999 isn't a real seq -> dropped
    assert "unknown" in md.lower()
    assert "Lightning Strike" in md
    assert "999" not in md


def test_markdown_loss_when_opp_wins():
    s = _stream()
    s["match_meta"]["winner_seat"] = 2
    assert "**Lost**" in vm.replay_markdown(s, [], "")
