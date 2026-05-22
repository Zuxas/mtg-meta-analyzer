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
