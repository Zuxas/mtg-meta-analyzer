"""Hand-crafted MTGA log-blob fixtures for replay_events tests.

Fixtures are Python lists of dicts (the same shape _iter_json_blobs
yields). Tests inject these via the `_blobs` parameter on
build_event_stream so we don't need real Player.log files in source
control.
"""
from typing import Iterator


def make_blob_iter(blobs):
    """Return a callable that yields the given blobs.

    Replaces _iter_json_blobs in tests via monkeypatch.
    """
    def _iter(log_path):
        for b in blobs:
            yield b
    return _iter


def match_start(match_id, my_user_id="GCIUQPR6DRC4XL7L2ZTNU2OMNI",
                opp_name="TestOpp"):
    """Minimal matchGameRoomStateChangedEvent putting our user in seat 1."""
    return {
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "matchId": match_id,
                    "reservedPlayers": [
                        {"userId": my_user_id, "systemSeatId": 1,
                         "playerName": "You"},
                        {"userId": "OPPONENT_ID", "systemSeatId": 2,
                         "playerName": opp_name},
                    ],
                },
                "stateType": "MatchGameRoomStateType_Playing",
            },
        },
    }


def match_end(match_id):
    """Minimal matchGameRoomStateChangedEvent ending the match."""
    return {
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {"matchId": match_id, "reservedPlayers": []},
                "stateType": "MatchGameRoomStateType_MatchCompleted",
            },
        },
    }


def game_state(*, game_num=1, turn_num=1, active_seat=1, priority_seat=1,
               phase="Phase_Main1", step=None,
               life=(20, 20), mana_pool=("", ""),
               annotations=None, game_objects=None, zones=None,
               players=None, game_state_id=None):
    """Build a greToClientEvent blob with one GameStateMessage."""
    msg = {
        "type": "GREMessageType_GameStateMessage",
        "gameStateMessage": {
            "gameInfo": {"gameNumber": game_num, "stage": "GameStage_Playing"},
            "turnInfo": {
                "turnNumber": turn_num,
                "activePlayer": active_seat,
                "priorityPlayer": priority_seat,
                "phase": phase,
                "step": step,
            },
            "players": players or [
                {"systemSeatNumber": 1, "lifeTotal": life[0],
                 "manaPool": mana_pool[0]},
                {"systemSeatNumber": 2, "lifeTotal": life[1],
                 "manaPool": mana_pool[1]},
            ],
            "gameObjects": game_objects or [],
            "zones": zones or [],
            "annotations": annotations or [],
        },
    }
    if game_state_id is not None:
        msg["gameStateMessage"]["gameStateId"] = game_state_id
    return {"greToClientEvent": {"greToClientMessages": [msg]}}
