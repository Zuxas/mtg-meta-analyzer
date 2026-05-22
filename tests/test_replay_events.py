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
