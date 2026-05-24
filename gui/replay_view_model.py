# -*- coding: utf-8 -*-
"""Qt-free display logic for the full-depth replay viewer.

Pure functions that transform the M1 event stream (analysis.replay_events
build_event_stream output) into structures the QMainWindow renders:
timeline tree, event-table rows, kind filtering, navigation, jump-to
targets, and right-pane detail rows.

NO PyQt6 imports here -- this module is unit-tested headless. The Qt widgets
live in gui/widgets/replay_viewer_window.py and import from here.

Source-of-Truth Hierarchy: this is Layer-5 presentation logic. It reads the
events[] data contract and never re-parses Player.log.
"""
from __future__ import annotations

from typing import Optional

_PHASE_LABELS = {
    "Phase_Beginning": "Beginning",
    "Phase_Main1": "Precombat Main",
    "Phase_Combat": "Combat",
    "Phase_Main2": "Postcombat Main",
    "Phase_Ending": "Ending",
}
_STEP_LABELS = {
    "Step_Untap": "Untap",
    "Step_Upkeep": "Upkeep",
    "Step_Draw": "Draw",
    "Step_BeginCombat": "Begin Combat",
    "Step_DeclareAttackers": "Declare Attackers",
    "Step_DeclareBlockers": "Declare Blockers",
    "Step_FirstStrikeDamage": "First Strike Damage",
    "Step_CombatDamage": "Combat Damage",
    "Step_EndCombat": "End Combat",
    "Step_End": "End Step",
    "Step_Cleanup": "Cleanup",
}
_KIND_LABELS = {
    "phase_change": "Phase", "step_change": "Step",
    "priority_grant": "Priority", "priority_pass": "Priority Pass",
    "mulligan_decision": "Mulligan", "keep_hand": "Keep",
    "draw_card": "Draw", "play_land": "Land", "cast_spell": "Cast",
    "activate_ability": "Activate", "trigger_ability": "Trigger",
    "target_chosen": "Targets", "mana_paid": "Mana Paid",
    "mana_added": "Mana Added", "resolve": "Resolve",
    "counter_spell": "Counter", "counter_ability": "Counter Ability",
    "damage_dealt": "Damage", "life_change": "Life", "zone_change": "Zone",
    "token_created": "Token", "counter_added": "Counter+",
    "counter_removed": "Counter-", "scry": "Scry", "surveil": "Surveil",
    "shuffle": "Shuffle", "reveal": "Reveal", "cascade": "Cascade",
    "library_look": "Look", "attack_declared": "Attack",
    "block_declared": "Block", "combat_damage_assigned": "Combat Damage",
    "game_end": "Game End", "raw": "Raw",
}


def _strip_prefix(value: str) -> str:
    """'Phase_Main1' -> 'Main1', 'Step_Foo' -> 'Foo'."""
    return value.split("_", 1)[1] if "_" in value else value


def phase_label(phase: Optional[str]) -> str:
    """Return a human-readable phase name.

    Known phases map to canonical labels; unknown Phase_* enums fall back to
    stripping the prefix. None returns an em-dash placeholder.
    """
    if not phase:
        return "—"
    return _PHASE_LABELS.get(phase) or _strip_prefix(phase)


def step_label(step: Optional[str]) -> Optional[str]:
    """Return a human-readable step name, or None if step is None."""
    if not step:
        return None
    return _STEP_LABELS.get(step) or _strip_prefix(step)


def kind_label(kind: str) -> str:
    """Return a human-readable event-kind label.

    Known kinds map to short canonical labels; unknown kinds are title-cased
    slug-to-words conversions.
    """
    if kind in _KIND_LABELS:
        return _KIND_LABELS[kind]
    return kind.replace("_", " ").title()
