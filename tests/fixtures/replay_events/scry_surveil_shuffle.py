"""Fixture for revealed_cards + shuffle_cause capture (Odds Engine contract)."""
from . import match_start, match_end, game_state

MATCH_ID = "scry-shuffle-test-match-001"

GRPID_NAMES = {300: "Opt", 301: "Island", 302: "Mountain"}


def build_scry():
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=600,
            game_objects=[
                {"instanceId": 10, "grpId": 300, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 11, "grpId": 301, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 12, "grpId": 302, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 20, "type": ["AnnotationType_Scry"],
                 "affectedIds": [],
                 "details": [
                     {"key": "topIds", "valueInt32": [11]},
                     {"key": "bottomIds", "valueInt32": [12]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]


def build_surveil():
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=601,
            game_objects=[
                {"instanceId": 13, "grpId": 300, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 21, "type": ["AnnotationType_Surveil"],
                 "affectedIds": [13],
                 "details": [
                     {"key": "topIds", "valueInt32": [13]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]


def build_surveil_mixed():
    """Surveil revealing 2 cards: iid 14 kept on top, iid 15 sent to graveyard."""
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=605,
            game_objects=[
                {"instanceId": 14, "grpId": 301, "ownerSeatId": 1,
                 "controllerSeatId": 1},  # Island
                {"instanceId": 15, "grpId": 302, "ownerSeatId": 1,
                 "controllerSeatId": 1},  # Mountain
            ],
            annotations=[
                {"id": 23, "type": ["AnnotationType_Surveil"],
                 "affectedIds": [14, 15],
                 "details": [
                     {"key": "topIds", "valueInt32": [14]},  # only iid 14 kept on top
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]


def build_shuffle(cause="effect"):
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=602,
            annotations=[
                {"id": 22, "type": ["AnnotationType_Shuffle"],
                 "affectedIds": [],
                 "details": [
                     {"key": "cause", "valueString": [cause]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]
