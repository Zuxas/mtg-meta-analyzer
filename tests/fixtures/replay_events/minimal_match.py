"""Minimal one-game fixture: match start, one priority grant, game end."""
from . import match_start, match_end, game_state

MATCH_ID = "minimal-test-match-001"


def build():
    return [
        match_start(MATCH_ID),
        game_state(game_num=1, turn_num=1, phase="Phase_Beginning",
                   step="Step_Untap"),
        match_end(MATCH_ID),
    ]
