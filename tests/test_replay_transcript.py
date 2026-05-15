"""Tests for analysis.replay_transcript -- on-demand match transcript.

These tests don't exercise the full Player.log parser (it's a slow,
environment-dependent path). They cover:
  - transcript_cache_path is deterministic and under data/match_replays/
  - build_transcript returns the cached JSON when present and not forced
  - build_transcript returns None when the match isn't in any log file
"""
import json
from pathlib import Path

import pytest


def test_transcript_cache_path_under_data_dir():
    from analysis.replay_transcript import transcript_cache_path
    p = transcript_cache_path("abc-123")
    assert p.name == "abc-123.json"
    assert "match_replays" in str(p)


def test_build_transcript_returns_cached_json(tmp_path, monkeypatch):
    from analysis import replay_transcript as rt
    monkeypatch.setattr(rt, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rt, "PLAYER_LOG", tmp_path / "nope.log")
    monkeypatch.setattr(rt, "PLAYER_PREV_LOG", tmp_path / "nope2.log")

    payload = {
        "arena_match_id": "fake-1",
        "opp_name": "TestPlayer",
        "games": [{"game_num": 1, "turns": [{"turn": 1, "actions": ["a"]}]}],
    }
    (tmp_path / "fake-1.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = rt.build_transcript("fake-1")
    assert result == payload


def test_build_transcript_returns_none_for_unknown_match(tmp_path, monkeypatch):
    from analysis import replay_transcript as rt
    monkeypatch.setattr(rt, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rt, "PLAYER_LOG", tmp_path / "nope.log")
    monkeypatch.setattr(rt, "PLAYER_PREV_LOG", tmp_path / "nope2.log")
    # Logs don't exist; cache empty -> None
    assert rt.build_transcript("never-existed") is None


def test_build_transcript_rebuilds_when_forced(tmp_path, monkeypatch):
    """With force_refresh=True and no logs to re-parse, returns None
    (re-build attempted, can't find match, no cache fallback)."""
    from analysis import replay_transcript as rt
    monkeypatch.setattr(rt, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rt, "PLAYER_LOG", tmp_path / "nope.log")
    monkeypatch.setattr(rt, "PLAYER_PREV_LOG", tmp_path / "nope2.log")

    # Seed cache with bogus data
    (tmp_path / "fake.json").write_text(
        json.dumps({"games": []}), encoding="utf-8"
    )
    # Without force: returns the cached bogus payload
    cached = rt.build_transcript("fake", force_refresh=False)
    assert cached == {"games": []}
    # With force + no logs: returns None (re-parse failed)
    assert rt.build_transcript("fake", force_refresh=True) is None
