"""M1 acceptance tests for analysis.replay_events.

Each test asserts one of the acceptance gates from the spec at
docs/superpowers/specs/2026-05-22-replay-viewer-design.md.
"""
from __future__ import annotations

import pytest

from analysis import replay_events
from tests.fixtures.replay_events import make_blob_iter
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
