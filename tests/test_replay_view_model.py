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
