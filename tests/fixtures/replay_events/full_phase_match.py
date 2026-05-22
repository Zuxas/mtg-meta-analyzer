"""Fixture covering one game touching every MTG phase + step.

Phase coverage acceptance gate from the spec: at least one event per
phase/step pair MTGA emits (Beginning/Untap, Beginning/Upkeep,
Beginning/Draw, Main1, Combat/Begin, Combat/DeclareAttackers,
Combat/DeclareBlockers, Combat/Damage, Combat/End, Main2, Ending/End,
Ending/Cleanup).
"""
from . import match_start, match_end, game_state

MATCH_ID = "full-phase-test-match-001"

_PHASES_STEPS = [
    ("Phase_Beginning", "Step_Untap"),
    ("Phase_Beginning", "Step_Upkeep"),
    ("Phase_Beginning", "Step_Draw"),
    ("Phase_Main1", None),
    ("Phase_Combat", "Step_BeginCombat"),
    ("Phase_Combat", "Step_DeclareAttackers"),
    ("Phase_Combat", "Step_DeclareBlockers"),
    ("Phase_Combat", "Step_CombatDamage"),
    ("Phase_Combat", "Step_EndCombat"),
    ("Phase_Main2", None),
    ("Phase_Ending", "Step_End"),
    ("Phase_Ending", "Step_Cleanup"),
]


def build():
    blobs = [match_start(MATCH_ID)]
    for idx, (phase, step) in enumerate(_PHASES_STEPS):
        blobs.append(game_state(
            game_num=1, turn_num=1, active_seat=1, priority_seat=1,
            phase=phase, step=step, game_state_id=100 + idx,
        ))
    blobs.append(match_end(MATCH_ID))
    return blobs
