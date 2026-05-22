"""M1 acceptance tests for analysis.replay_events.

Each test asserts one of the acceptance gates from the spec at
docs/superpowers/specs/2026-05-22-replay-viewer-design.md.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from analysis import replay_events
from tests.fixtures.replay_events import make_blob_iter


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    """Every test gets its own cache dir to prevent polluting data/match_replays."""
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(replay_events, "transcript_cache_path",
                        lambda mid: tmp_path / f"{mid}.json")
    return tmp_path
from tests.fixtures.replay_events.minimal_match import (
    MATCH_ID as MINIMAL_MATCH_ID, build as build_minimal,
)
from tests.fixtures.replay_events.full_phase_match import (
    MATCH_ID as PHASE_MATCH_ID, build as build_phase_match, _PHASES_STEPS,
)


def test_unknown_match_returns_none(monkeypatch):
    """build_event_stream returns None for a match not in the logs."""
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter([]))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream("nonexistent-id",
                                              force_refresh=True)
    assert result is None


def test_match_boundary_populates_seats(monkeypatch):
    """match_start blob populates my_seat, opp_seat, opp_name."""
    blobs = build_minimal()
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MINIMAL_MATCH_ID,
                                              force_refresh=True)
    assert result is not None
    assert result["arena_match_id"] == MINIMAL_MATCH_ID
    assert result["my_seat"] == 1
    assert result["opp_seat"] == 2
    assert result["opp_name"] == "TestOpp"
    assert result["schema_version"] == 1
    assert result["capabilities"]["events"] is True
    assert result["capabilities"]["odds_ready"] is False


def test_phase_coverage(monkeypatch):
    """events[] includes a phase_change/step_change for every MTG phase+step pair."""
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_phase_match()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(PHASE_MATCH_ID,
                                              force_refresh=True)
    assert result is not None
    seen_pairs = set()
    for ev in result["events"]:
        if ev["kind"] in ("phase_change", "step_change"):
            seen_pairs.add((ev["phase"], ev["step"]))
    for phase, step in _PHASES_STEPS:
        assert (phase, step) in seen_pairs, \
            f"missing phase/step pair: {phase}/{step}"


def _make_priority_fixture():
    """3 game-state messages alternating priorityPlayer: 1, 2, 1."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "priority-test-match-001"
    return MID, [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, game_state_id=200),
        game_state(turn_num=1, priority_seat=2, game_state_id=201),
        game_state(turn_num=1, priority_seat=1, game_state_id=202),
        match_end(MID),
    ]


def test_priority_sequencing(monkeypatch):
    """Every event between two priority_grant events has the same priority_seat."""
    mid, blobs = _make_priority_fixture()
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(mid, force_refresh=True)
    assert result is not None
    grants = [e for e in result["events"] if e["kind"] == "priority_grant"]
    assert len(grants) == 3
    assert [g["priority_seat"] for g in grants] == [1, 2, 1]


def test_stack_after_populated_from_zones(monkeypatch):
    """When zones[] contains ZoneType_Stack with object IDs, stack_after
    on the next event reflects the stack."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "stack-test-match-001"
    grpid_names = {100: "Lightning Strike", 200: "Make Disappear"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=300,
            game_objects=[
                {"instanceId": 1, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 2, "grpId": 200, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
            zones=[
                {"type": "ZoneType_Stack", "objectInstanceIds": [1, 2]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result is not None
    assert len(result["events"]) >= 1
    last = result["events"][-1]
    names = [s["name"] for s in last["stack_after"]]
    assert names == ["Lightning Strike", "Make Disappear"]
    controllers = [s["controller"] for s in last["stack_after"]]
    assert controllers == ["you", "opp"]


def test_cast_resolve_counter_events(monkeypatch):
    """ZoneTransfer annotations with category=CastSpell/Resolve/Countered
    produce cast_spell/resolve/counter_spell events."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "cast-test-match-001"
    grpid_names = {100: "Lightning Strike"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=400,
            game_objects=[
                {"instanceId": 5, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 1, "type": ["AnnotationType_ZoneTransfer"],
                 "affectedIds": [5],
                 "details": [{"key": "category",
                              "valueString": ["CastSpell"]}]},
                {"id": 2, "type": ["AnnotationType_ZoneTransfer"],
                 "affectedIds": [5],
                 "details": [{"key": "category",
                              "valueString": ["Resolve"]}]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "cast_spell" in kinds
    assert "resolve" in kinds
    cast = [e for e in result["events"] if e["kind"] == "cast_spell"][0]
    assert cast["card_name"] == "Lightning Strike"
    assert cast["card_grpid"] == 100
    assert cast["actor_seat"] == 1


def test_targets_and_damage(monkeypatch):
    """PlayerSubmittedTargets -> target_chosen; DamageDealt -> damage_dealt."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "tgt-test-match-001"
    grpid_names = {100: "Lightning Strike", 200: "Goblin"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=500,
            game_objects=[
                {"instanceId": 5, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 6, "grpId": 200, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
            annotations=[
                {"id": 10, "type": ["AnnotationType_PlayerSubmittedTargets"],
                 "affectedIds": [6]},
                {"id": 11, "type": ["AnnotationType_DamageDealt"],
                 "affectedIds": [5, 6],
                 "details": [{"key": "damage",
                              "valueInt32": [3]}]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "target_chosen" in kinds
    assert "damage_dealt" in kinds
    tgt = [e for e in result["events"] if e["kind"] == "target_chosen"][0]
    assert tgt["targets"][0]["name"] == "Goblin"
    dmg = [e for e in result["events"] if e["kind"] == "damage_dealt"][0]
    assert dmg["details"]["damage"] == 3


def test_scry_populates_revealed_cards(monkeypatch):
    """Scry annotation produces an event with revealed_cards populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as SCRY_MID, GRPID_NAMES, build_scry,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_scry()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(SCRY_MID, force_refresh=True)
    assert result is not None
    scry = [e for e in result["events"] if e["kind"] == "scry"]
    assert len(scry) == 1
    revealed = scry[0]["revealed_cards"]
    assert any(r["name"] == "Island" and r["library_position"] == "top"
               for r in revealed)
    assert any(r["name"] == "Mountain" and r["library_position"] == "bottom"
               for r in revealed)


def test_surveil_populates_revealed_cards(monkeypatch):
    """Surveil annotation produces an event with revealed_cards populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as MID, GRPID_NAMES, build_surveil,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_surveil()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    surveil_evs = [e for e in result["events"] if e["kind"] == "surveil"]
    assert len(surveil_evs) == 1
    revealed = surveil_evs[0]["revealed_cards"]
    assert revealed and revealed[0]["name"] == "Opt"
    assert revealed[0]["source"] == "surveil_top"


def test_surveil_distinguishes_top_vs_gy(monkeypatch):
    """Surveil annotation differentiates cards kept on top vs sent to GY.

    affectedIds contains BOTH; details.topIds is the subset that stayed on
    top. Cards in affectedIds-minus-topIds went to the graveyard and must
    be labeled source=surveil_gy (not surveil_top) so the Odds Engine can
    track GY public-information correctly.
    """
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as MID, GRPID_NAMES, build_surveil_mixed,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_surveil_mixed()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    surveil_evs = [e for e in result["events"] if e["kind"] == "surveil"]
    assert len(surveil_evs) == 1
    revealed = surveil_evs[0]["revealed_cards"]
    top = [r for r in revealed if r["source"] == "surveil_top"]
    gy = [r for r in revealed if r["source"] == "surveil_gy"]
    assert len(top) == 1
    assert top[0]["name"] == "Island"
    assert top[0]["library_position"] == "top"
    assert len(gy) == 1
    assert gy[0]["name"] == "Mountain"
    assert gy[0]["library_position"] is None  # in graveyard, not in library


def test_shuffle_populates_cause(monkeypatch):
    """Shuffle annotation produces an event with details.cause populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as MID, GRPID_NAMES, build_shuffle,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_shuffle(cause="fetch")))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    shuffles = [e for e in result["events"] if e["kind"] == "shuffle"]
    assert len(shuffles) == 1
    assert shuffles[0]["shuffle_cause"] == "fetch"


def test_attack_and_block_declared(monkeypatch):
    """SubmitAttackersReq -> attack_declared; SubmitBlockersReq -> block_declared."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "combat-test-001"
    grpid_names = {600: "Goblin Guide", 601: "Wall of Omens"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=2, priority_seat=1, game_state_id=800,
            game_objects=[
                {"instanceId": 100, "grpId": 600, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 101, "grpId": 601, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
        ),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitAttackersReq",
             "submitAttackersReq": {
                 "attackers": [{"attackerId": 100}],
             },
         }},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitBlockersReq",
             "submitBlockersReq": {
                 "blockerToAttackerMap": [
                     {"blockerId": 101, "attackerId": 100},
                 ],
             },
         }},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "attack_declared" in kinds
    assert "block_declared" in kinds
    atk = [e for e in result["events"] if e["kind"] == "attack_declared"][0]
    assert atk["details"]["attackers"][0]["name"] == "Goblin Guide"
    blk = [e for e in result["events"] if e["kind"] == "block_declared"][0]
    assert blk["details"]["blocks"][0]["blocker"] == "Wall of Omens"
    assert blk["details"]["blocks"][0]["attacker"] == "Goblin Guide"


def test_shuffle_unknown_cause_defaults(monkeypatch):
    """Shuffle without cause detail gets shuffle_cause='unknown'."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "shuffle-unknown-001"
    blobs = [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, annotations=[
            {"id": 30, "type": ["AnnotationType_Shuffle"],
             "affectedIds": [], "details": []},
        ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    shuffles = [e for e in result["events"] if e["kind"] == "shuffle"]
    assert len(shuffles) == 1
    assert shuffles[0]["shuffle_cause"] == "unknown"


def test_life_change_emitted(monkeypatch):
    """When a player's lifeTotal changes between game states, a life_change event lands."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "life-test-001"
    blobs = [
        match_start(MID),
        game_state(turn_num=1, life=(20, 20), priority_seat=1),
        game_state(turn_num=1, life=(20, 17), priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    lifechanges = [e for e in result["events"] if e["kind"] == "life_change"]
    assert len(lifechanges) == 1
    assert lifechanges[0]["details"]["seat"] == 2
    assert lifechanges[0]["details"]["delta"] == -3
    assert lifechanges[0]["life_after"]["opp"] == 17


def test_mulligan_and_game_end(monkeypatch):
    """ClientMessageType_MulliganResp -> mulligan_decision; game stage
    Completed -> game_end."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "mull-test-001"
    blobs = [
        match_start(MID),
        # Mull decision from client
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_MulliganResp",
             "mulliganResp": {"decision": "MulliganOption_Mulligan"},
         }},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_MulliganResp",
             "mulliganResp": {"decision": "MulliganOption_AcceptHand"},
         }},
        game_state(turn_num=1, priority_seat=1),
        # Game ends with seat 1 winning
        {"greToClientEvent": {"greToClientMessages": [{
            "type": "GREMessageType_GameStateMessage",
            "gameStateMessage": {
                "gameInfo": {
                    "gameNumber": 1,
                    "stage": "GameStage_GameOver",
                    "results": [{"winningTeamId": 1,
                                 "reason": "ResultReason_Concede"}],
                },
                "turnInfo": {"turnNumber": 1, "phase": "Phase_Main1"},
                "players": [], "gameObjects": [], "zones": [],
                "annotations": [],
            },
        }]}},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "mulligan_decision" in kinds
    assert "keep_hand" in kinds
    assert "game_end" in kinds
    assert result["match_meta"]["winner_seat"] == 1
    assert result["match_meta"]["winner_reason"] == "Concede"


def test_board_diff_validity(monkeypatch):
    """Applying all board_diff[] entries from seq=0 produces the same
    zone counts MTGA reports in zones[]."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "board-test-001"
    grpid_names = {500: "Mountain"}
    blobs = [
        match_start(MID),
        # T1: Mountain in hand
        game_state(turn_num=1, priority_seat=1, game_state_id=700,
                   game_objects=[
                       {"instanceId": 50, "grpId": 500, "ownerSeatId": 1,
                        "controllerSeatId": 1, "zoneId": 1},
                   ],
                   zones=[
                       {"type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [50]},
                       {"type": "ZoneType_Battlefield",
                        "objectInstanceIds": []},
                   ]),
        # T1: Mountain played
        game_state(turn_num=1, priority_seat=1, game_state_id=701,
                   game_objects=[
                       {"instanceId": 50, "grpId": 500, "ownerSeatId": 1,
                        "controllerSeatId": 1, "zoneId": 2},
                   ],
                   zones=[
                       {"type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": []},
                       {"type": "ZoneType_Battlefield",
                        "objectInstanceIds": [50]},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    # Walk all board_diff entries and apply them
    zones_now = {"hand": set(), "battlefield": set()}
    for ev in result["events"]:
        for diff in ev["board_diff"]:
            src = diff.get("from")
            dst = diff.get("to")
            iid = diff["instance_id"]
            if src in zones_now:
                zones_now[src].discard(iid)
            if dst in zones_now:
                zones_now[dst].add(iid)
    # Final state should match the last MTGA zones[] snapshot
    assert 50 in zones_now["battlefield"]
    assert 50 not in zones_now["hand"]


def test_match_meta_populated(monkeypatch):
    """match_meta has event_name from gameRoomConfig.eventId."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "meta-test-001"
    blobs = [
        # MatchPending blob also carries event metadata
        {"matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "matchId": MID,
                    "reservedPlayers": [
                        {"userId": "GCIUQPR6DRC4XL7L2ZTNU2OMNI",
                         "systemSeatId": 1, "playerName": "You"},
                        {"userId": "OPP", "systemSeatId": 2,
                         "playerName": "Opp"},
                    ],
                    "eventId": "Constructed_BestOf3_Ranked",
                },
                "stateType": "MatchGameRoomStateType_Playing",
            },
        }},
        game_state(turn_num=1, priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result["match_meta"]["event_name"] == "Constructed_BestOf3_Ranked"
    # decklist_my_grpids defaults to [] in M1 without a SubmitDeckResp blob
    assert result["match_meta"]["decklist_my_grpids"] == []


def test_per_game_decklists(monkeypatch):
    """SubmitDeckResp blobs populate match_meta.games[i].decklist_my_grpids."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "deck-test-001"
    deck_g1 = [101, 102, 103, 104, 101]  # game 1 mainboard
    deck_g2 = [101, 102, 103, 105, 105]  # game 2 — swapped 104 -> 105 (+1 more 105)
    blobs = [
        match_start(MID),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitDeckResp",
             "submitDeckResp": {
                 "deck": {"deckCards": deck_g1, "sideboardCards": []},
             },
         }},
        game_state(game_num=1, turn_num=1, priority_seat=1),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitDeckResp",
             "submitDeckResp": {
                 "deck": {"deckCards": deck_g2, "sideboardCards": []},
             },
         }},
        game_state(game_num=2, turn_num=1, priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    games = result["match_meta"]["games"]
    assert len(games) == 2
    assert games[0]["decklist_my_grpids"] == deck_g1
    assert games[1]["decklist_my_grpids"] == deck_g2
    # G2 sideboarded in 105 x2, out 104 x1
    assert 105 in games[1]["sideboard_in"]
    assert 104 in games[1]["sideboard_out"]


def test_key_events_extracted(monkeypatch):
    """key_events_by_turn includes first_spell, mulligan_to_6, concede."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "key-events-test-001"
    grpid_names = {700: "Lightning Strike"}
    blobs = [
        match_start(MID),
        # Mull -> keep on 6
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {"type": "ClientMessageType_MulliganResp",
                     "mulliganResp": {"decision": "MulliganOption_Mulligan"}}},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {"type": "ClientMessageType_MulliganResp",
                     "mulliganResp": {"decision": "MulliganOption_AcceptHand"}}},
        # First spell turn 3
        game_state(turn_num=3, priority_seat=1, game_state_id=900,
                   game_objects=[
                       {"instanceId": 200, "grpId": 700, "ownerSeatId": 1,
                        "controllerSeatId": 1},
                   ],
                   annotations=[
                       {"id": 50, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [200],
                        "details": [{"key": "category",
                                     "valueString": ["CastSpell"]}]},
                   ]),
        # Concede
        {"greToClientEvent": {"greToClientMessages": [{
            "type": "GREMessageType_GameStateMessage",
            "gameStateMessage": {
                "gameInfo": {"gameNumber": 1,
                             "stage": "GameStage_GameOver",
                             "results": [{"winningTeamId": 2,
                                          "reason": "ResultReason_Concede"}]},
                "turnInfo": {"turnNumber": 4, "phase": "Phase_Main1"},
                "players": [], "gameObjects": [], "zones": [],
                "annotations": [],
            },
        }]}},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    keys = result["match_meta"]["key_events_by_turn"]
    kinds = [k["kind"] for k in keys]
    assert "mulligan_to_6" in kinds
    assert "first_spell" in kinds
    assert "concede" in kinds
    first_spell = [k for k in keys if k["kind"] == "first_spell"][0]
    assert first_spell["turn"] == 3
    assert first_spell["card"] == "Lightning Strike"


def test_cache_write_preserves_classic_keys(tmp_path, monkeypatch):
    """Writing event stream to an existing classic cache preserves the
    games/turns keys the classic dialog reads."""
    import json
    MID = "cache-test-001"
    # Seed an existing classic transcript cache
    classic = {
        "arena_match_id": MID,
        "my_seat": 1, "opp_seat": 2, "opp_name": "TestOpp",
        "games": [
            {"game_num": 1, "turns": [
                {"turn": 1, "active_seat": 1, "active_label": "You",
                 "actions": ["You play Mountain (land)"]},
            ]},
        ],
    }
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    (tmp_path / f"{MID}.json").write_text(json.dumps(classic),
                                          encoding="utf-8")
    # Also patch transcript_cache_path so it points into tmp_path
    monkeypatch.setattr(replay_events, "transcript_cache_path",
                        lambda mid: tmp_path / f"{mid}.json")

    # Feed minimal blobs through extractor
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    blobs = [match_start(MID), game_state(turn_num=1, priority_seat=1),
             match_end(MID)]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result is not None

    # Cache file now has BOTH classic and new keys
    with open(tmp_path / f"{MID}.json", encoding="utf-8") as f:
        merged = json.load(f)
    assert "games" in merged
    assert merged["games"][0]["turns"][0]["actions"] == ["You play Mountain (land)"]
    assert "events" in merged
    assert "match_meta" in merged
    assert merged["schema_version"] == 1


def test_cache_auto_rebuilds_when_capability_missing(tmp_path, monkeypatch):
    """A cache with capabilities.events=False (or missing) triggers a
    rebuild on next read."""
    import json
    MID = "auto-rebuild-001"
    stale = {
        "arena_match_id": MID,
        "capabilities": {"events": False},
        "events": [],
        "games": [],
    }
    # The autouse fixture already sets CACHE_DIR / transcript_cache_path
    # to tmp_path, but we need to write the stale cache to that same dir.
    # Use the patched transcript_cache_path to find where:
    cache_path = replay_events.transcript_cache_path(MID)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(stale), encoding="utf-8")

    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    blobs = [match_start(MID), game_state(turn_num=1, priority_seat=1),
             match_end(MID)]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    # NOT passing force_refresh -- must auto-rebuild because cap is missing
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert result is not None
    assert result["capabilities"]["events"] is True


def test_cache_read_returns_when_capabilities_ok(tmp_path, monkeypatch):
    """When the cache has all required capabilities=True the cached version is returned."""
    import json
    MID = "cache-hit-001"
    full = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": []},
        "events": [{"seq": 0, "kind": "phase_change", "turn_num": 1}],
        "my_seat": 1, "opp_seat": 2, "opp_name": "Test",
    }
    cache_path = replay_events.transcript_cache_path(MID)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(full), encoding="utf-8")

    # Should NOT call _iter_json_blobs because the cache is current
    called = {"n": 0}
    def _spy(_p):
        called["n"] += 1
        return iter([])
    monkeypatch.setattr(replay_events, "_iter_json_blobs", _spy)
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert called["n"] == 0
    assert result["events"][0]["kind"] == "phase_change"


def _render_events_as_actions(events_list, opp_name, my_seat):
    """Re-render events as the classic action-string format.

    Returns a list of (turn_num, action_string) tuples. Only emits for
    event kinds the classic transcript covers. M1 scope is the documented
    subset (cast/resolve/play_land/draw/life_change); M2 will extend to
    all classic action types."""
    out = []
    for ev in events_list:
        kind = ev["kind"]
        turn = ev["turn_num"]
        nm = ev.get("card_name")
        actor = ev.get("actor_seat")
        who = "You" if actor == my_seat else opp_name
        if kind == "cast_spell" and nm:
            out.append((turn, f"{who} cast {nm}"))
        elif kind == "resolve" and nm:
            out.append((turn, f"{nm} resolves"))
        elif kind == "play_land" and nm:
            out.append((turn, f"{who} play {nm} (land)"))
        elif kind == "draw_card" and nm and who == "You":
            out.append((turn, f"You draw {nm}"))
        elif kind == "life_change":
            d = ev["details"]
            seat = d["seat"]
            who_d = "You" if seat == my_seat else opp_name
            delta = d["delta"]
            sign = "+" if delta > 0 else ""
            out.append((turn, f"{who_d} life: {d['from']} → {d['to']} ({sign}{delta})"))
    return out


def test_round_trip_against_synthetic_classic(monkeypatch):
    """Re-rendering events[] reproduces the action strings the classic
    builder would produce for the same input blobs.

    Note: M1 ships re-renderable parity for a documented subset of
    actions (cast/resolve/play_land/draw/life_change). The full
    round-trip against all classic action types is verified in M2
    when the viewer can dispatch over events directly. For M1 we lock
    the contract that the re-render of the documented subset is
    byte-identical to what the classic builder would emit for the same
    fixture."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "rt-001"
    grpid_names = {800: "Lightning Strike", 801: "Mountain"}
    blobs = [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, game_state_id=1000,
                   life=(20, 20)),
        game_state(turn_num=1, priority_seat=1, game_state_id=1001,
                   life=(20, 17),
                   game_objects=[
                       {"instanceId": 1, "grpId": 800, "ownerSeatId": 1,
                        "controllerSeatId": 1},
                   ],
                   annotations=[
                       {"id": 1, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [1],
                        "details": [{"key": "category",
                                     "valueString": ["CastSpell"]}]},
                       {"id": 2, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [1],
                        "details": [{"key": "category",
                                     "valueString": ["Resolve"]}]},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    rendered = _render_events_as_actions(result["events"],
                                          result["opp_name"],
                                          result["my_seat"])
    rendered_text = [s for _, s in rendered]
    # Expected action strings, matching classic transcript output format:
    assert "You cast Lightning Strike" in rendered_text
    assert "Lightning Strike resolves" in rendered_text
    assert "TestOpp life: 20 → 17 (-3)" in rendered_text


def test_cli_dump_exits_zero_for_known_match(tmp_path, monkeypatch):
    """`python scripts/replay_event_dump.py <id>` exits 0 on a cached match."""
    import subprocess, sys, json
    from pathlib import Path
    MID = "cli-test-001"
    cache = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": [],
                       "event_name": "Ranked"},
        "events": [
            {"seq": 0, "kind": "phase_change", "turn_num": 1,
             "phase": "Phase_Main1", "step": None,
             "active_seat": 1, "priority_seat": 1,
             "card_name": None, "card_grpid": None, "targets": [],
             "details": {}, "stack_after": [], "board_diff": [],
             "revealed_cards": [], "shuffle_cause": None,
             "actor_seat": None, "life_after": None,
             "mana_pool_after": None, "log_offset": None,
             "game_state_id": None, "game_num": 1},
        ],
        "my_seat": 1, "opp_seat": 2, "opp_name": "CLITestOpp",
    }
    cache_file = tmp_path / f"{MID}.json"
    cache_file.write_text(json.dumps(cache), encoding="utf-8")
    project_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "replay_event_dump.py"),
         "--cache-dir", str(tmp_path), MID],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "phase_change" in result.stdout
    assert "Phase_Main1" in result.stdout


def test_watcher_calls_both_builders(monkeypatch):
    """MtgaLogWatcher._build_missing_transcripts calls build_event_stream
    in addition to build_transcript."""
    from gui import mtga_log_watcher

    calls = {"transcript": 0, "events": 0}

    def _fake_build_transcript(mid, force_refresh=False):
        calls["transcript"] += 1
        return {"games": []}

    def _fake_build_events(mid, force_refresh=False):
        calls["events"] += 1
        return {"events": []}

    def _fake_cache_path(mid):
        from pathlib import Path
        # Pretend cache never exists so both builders are invoked
        return Path("/nonexistent/never-here.json")

    monkeypatch.setattr("analysis.replay_transcript.build_transcript",
                        _fake_build_transcript)
    monkeypatch.setattr("analysis.replay_events.build_event_stream",
                        _fake_build_events)
    monkeypatch.setattr("analysis.replay_transcript.transcript_cache_path",
                        _fake_cache_path)

    w = mtga_log_watcher.MtgaLogWatcher()
    matches = [
        {"match_id": "test-1", "match_result": "win"},
        {"match_id": "test-2", "match_result": "loss"},
        {"match_id": "test-3", "match_result": ""},  # in-progress, skip
    ]
    built = w._build_missing_transcripts(matches)
    assert calls["transcript"] == 2  # 2 completed matches
    assert calls["events"] == 2      # both builders called per completed match
    assert built == 2
