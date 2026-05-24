"""Pure-function tests for gui/replay_view_model.py (no Qt required)."""
from gui import replay_view_model as vm


def test_phase_label_known_and_fallback():
    assert vm.phase_label("Phase_Main1") == "Precombat Main"
    assert vm.phase_label("Phase_Combat") == "Combat"
    # Unknown enum strips the prefix as a best-effort label
    assert vm.phase_label("Phase_Wibble") == "Wibble"
    assert vm.phase_label(None) == "—"


def test_step_label_known_and_none():
    assert vm.step_label("Step_Upkeep") == "Upkeep"
    assert vm.step_label("Step_DeclareAttackers") == "Declare Attackers"
    assert vm.step_label("Step_Mystery") == "Mystery"
    assert vm.step_label(None) is None


def test_kind_label():
    assert vm.kind_label("cast_spell") == "Cast"
    assert vm.kind_label("priority_grant") == "Priority"
    # Unknown kind title-cases the slug
    assert vm.kind_label("some_new_kind") == "Some New Kind"


def _ev(**kw):
    base = {
        "seq": 0, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
        "step": None, "active_seat": 1, "priority_seat": 1, "actor_seat": 1,
        "kind": "cast_spell", "card_name": None, "card_grpid": None,
        "targets": [], "details": {}, "life_after": None,
        "mana_pool_after": None, "stack_after": [], "board_diff": [],
        "log_offset": None, "revealed_cards": [], "shuffle_cause": None,
    }
    base.update(kw)
    return base


def test_player_label_maps_seat():
    assert vm.player_label(_ev(actor_seat=1), my_seat=1, opp_seat=2, opp_name="Bob") == "You"
    assert vm.player_label(_ev(actor_seat=2), my_seat=1, opp_seat=2, opp_name="Bob") == "Bob"
    # No actor -> fall back to active_seat
    assert vm.player_label(_ev(actor_seat=None, active_seat=2), my_seat=1, opp_seat=2, opp_name="Bob") == "Bob"
    # Unknown -> em dash
    assert vm.player_label(_ev(actor_seat=None, active_seat=None), my_seat=1, opp_seat=2, opp_name="Bob") == "—"


def test_event_summary_cast_with_targets():
    e = _ev(kind="cast_spell", card_name="Lightning Strike",
            targets=[{"name": "Make Disappear", "grpid": 1, "kind": "spell"}])
    s = vm.event_summary(e, opp_name="Bob")
    assert "Lightning Strike" in s
    assert "Make Disappear" in s


def test_event_summary_life_change():
    e = _ev(kind="life_change", details={"seat": 1, "delta": -3, "from": 11, "to": 8})
    s = vm.event_summary(e, opp_name="Bob")
    assert "8" in s and ("-3" in s or "−3" in s or "3" in s)


def test_event_summary_phase_change():
    e = _ev(kind="phase_change", phase="Phase_Combat", step="Step_DeclareAttackers")
    s = vm.event_summary(e, opp_name="Bob")
    assert "Combat" in s and "Declare Attackers" in s


def test_event_summary_falls_back_to_kind_label():
    assert vm.event_summary(_ev(kind="shuffle", shuffle_cause="fetch"), opp_name="Bob")


def test_format_event_row_shape():
    e = _ev(seq=42, turn_num=7, kind="cast_spell", card_name="Lightning Strike",
            actor_seat=1)
    row = vm.format_event_row(e, my_seat=1, opp_seat=2, opp_name="Bob")
    assert row["seq"] == 42
    assert row["turn"] == 7
    assert row["player"] == "You"
    assert "Lightning Strike" in row["summary"]
    assert row["kind"] == "cast_spell"


def test_kind_groups_cover_all_event_kinds():
    from analysis.replay_events import EVENT_KINDS
    covered = set()
    for kinds in vm.KIND_GROUPS.values():
        covered |= kinds
    assert covered == set(EVENT_KINDS), covered.symmetric_difference(set(EVENT_KINDS))


def test_kinds_for_groups_union():
    kinds = vm.kinds_for_groups({"Casts", "Combat"})
    assert "cast_spell" in kinds
    assert "attack_declared" in kinds
    assert "scry" not in kinds


def test_filter_events_returns_visible_seqs():
    events = [_ev(seq=0, kind="cast_spell"), _ev(seq=1, kind="priority_grant"),
              _ev(seq=2, kind="life_change")]
    seqs = vm.filter_events(events, {"cast_spell", "life_change"})
    assert seqs == [0, 2]
    # None => all
    assert vm.filter_events(events, None) == [0, 1, 2]


def test_default_off_groups():
    assert "Priority" in vm.DEFAULT_OFF_GROUPS
    assert "Raw" in vm.DEFAULT_OFF_GROUPS


def test_nav_target_directions():
    visible = [0, 3, 5, 9]
    assert vm.nav_target(visible, None, "first") == 0
    assert vm.nav_target(visible, None, "last") == 9
    assert vm.nav_target(visible, 3, "next") == 5
    assert vm.nav_target(visible, 3, "prev") == 0
    # clamp at ends
    assert vm.nav_target(visible, 9, "next") == 9
    assert vm.nav_target(visible, 0, "prev") == 0
    # current not in visible: next => first greater, prev => last lesser
    assert vm.nav_target(visible, 4, "next") == 5
    assert vm.nav_target(visible, 4, "prev") == 3
    # empty
    assert vm.nav_target([], 0, "next") is None
    # current None on next => first
    assert vm.nav_target(visible, None, "next") == 0


def test_build_timeline_tree_variable_depth():
    events = [
        _ev(seq=0, game_num=1, turn_num=1, phase="Phase_Beginning",
            step="Step_Upkeep", kind="phase_change", active_seat=1),
        _ev(seq=1, game_num=1, turn_num=1, phase="Phase_Beginning",
            step="Step_Draw", kind="draw_card", active_seat=1),
        _ev(seq=2, game_num=1, turn_num=1, phase="Phase_Main1", step=None,
            kind="cast_spell", active_seat=1),
        _ev(seq=3, game_num=1, turn_num=2, phase="Phase_Main1", step=None,
            kind="cast_spell", active_seat=2),
    ]
    tree = vm.build_timeline_tree(events, my_seat=1, opp_seat=2, opp_name="Bob")
    # One game
    assert len(tree) == 1
    game = tree[0]
    assert game["type"] == "game" and game["game_num"] == 1
    # Two turns
    assert len(game["children"]) == 2
    t1 = game["children"][0]
    assert t1["type"] == "turn" and t1["turn_num"] == 1
    assert "You" in t1["label"]
    # Turn 1 has two phases
    phases = t1["children"]
    assert [p["phase"] for p in phases] == ["Phase_Beginning", "Phase_Main1"]
    # Beginning has step children (Upkeep, Draw)
    beg = phases[0]
    assert all(c["type"] == "step" for c in beg["children"])
    assert [c["step"] for c in beg["children"]] == ["Step_Upkeep", "Step_Draw"]
    # Each step holds its event(s)
    assert beg["children"][0]["children"][0]["type"] == "event"
    # Main1 (no steps) has event children directly
    main1 = phases[1]
    assert all(c["type"] == "event" for c in main1["children"])
    assert main1["children"][0]["seq"] == 2
    # Turn 2 label shows opp
    t2 = game["children"][1]
    assert "Bob" in t2["label"]
