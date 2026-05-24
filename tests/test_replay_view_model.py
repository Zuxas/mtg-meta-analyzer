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
