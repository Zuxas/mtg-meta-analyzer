"""Tests for analysis.replay_events.replay_board_at (headless, no Qt)."""
from analysis.replay_events import replay_board_at


def _ev(seq, game_num, diffs):
    return {"seq": seq, "game_num": game_num, "turn_num": 1, "phase": None,
            "step": None, "kind": "zone_change", "card_name": None,
            "card_grpid": None, "board_diff": diffs}


def _d(iid, grpid, name, frm, to, controller):
    return {"instance_id": iid, "grpid": grpid, "card": name,
            "from": frm, "to": to, "controller": controller}


def test_reconstructs_battlefield_and_zones():
    events = [
        _ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")]),
        _ev(1, 1, [_d(2, 200, "Goblin", "hand", "battlefield", "you")]),
        _ev(2, 1, [_d(3, 300, "Bear", None, "battlefield", "opp")]),
        _ev(3, 1, [_d(2, 200, "Goblin", "battlefield", "graveyard", "you")]),
    ]
    b0 = replay_board_at(events, 0)
    assert b0["seq"] == 0
    assert [c["name"] for c in b0["you"]["battlefield"]] == ["Mountain"]

    b1 = replay_board_at(events, 1)
    assert sorted(c["name"] for c in b1["you"]["battlefield"]) == ["Goblin", "Mountain"]

    b3 = replay_board_at(events, 3)
    assert [c["name"] for c in b3["you"]["battlefield"]] == ["Mountain"]
    assert [c["name"] for c in b3["you"]["graveyard"]] == ["Goblin"]
    assert b3["you"]["graveyard_count"] == 1
    assert [c["name"] for c in b3["opp"]["battlefield"]] == ["Bear"]


def test_to_none_removes_instance_and_token_enters():
    events = [
        _ev(0, 1, [_d(9, 900, "Goblin Token", None, "battlefield", "you")]),
        _ev(1, 1, [_d(9, 900, "Goblin Token", "battlefield", None, "you")]),
    ]
    assert [c["name"] for c in replay_board_at(events, 0)["you"]["battlefield"]] == ["Goblin Token"]
    assert replay_board_at(events, 1)["you"]["battlefield"] == []


def test_hand_and_library_counts():
    events = [
        _ev(0, 1, [_d(1, 100, "Island", None, "hand", "you")]),
        _ev(0, 1, [_d(2, None, None, None, "hand", "opp")]),
        _ev(1, 1, [_d(5, None, None, None, "library", "you")]),
    ]
    b = replay_board_at(events, 1)
    assert b["you"]["hand_count"] == 1
    assert [c["name"] for c in b["you"]["hand"]] == ["Island"]
    assert b["opp"]["hand_count"] == 1
    assert b["opp"]["hand"] == []
    assert b["you"]["library_count"] == 1


def test_controller_none_excluded():
    events = [_ev(0, 1, [_d(1, 100, "Mystery", None, "battlefield", None)])]
    b = replay_board_at(events, 0)
    assert b["you"]["battlefield"] == []
    assert b["opp"]["battlefield"] == []


def test_resets_on_game_change():
    events = [
        _ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")]),
        {"seq": 1, "game_num": 1, "turn_num": 9, "phase": None, "step": None,
         "kind": "game_end", "card_name": None, "card_grpid": None, "board_diff": []},
        _ev(2, 2, [_d(7, 700, "Forest", None, "battlefield", "you")]),
    ]
    b = replay_board_at(events, 2)
    names = [c["name"] for c in b["you"]["battlefield"]]
    assert names == ["Forest"]
    assert "Mountain" not in names


def test_seq_beyond_end_is_clamped_safely():
    events = [_ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")])]
    b = replay_board_at(events, 999)
    assert [c["name"] for c in b["you"]["battlefield"]] == ["Mountain"]
