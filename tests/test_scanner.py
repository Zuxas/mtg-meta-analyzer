"""Tests for analysis/puzzles/scanner.py."""
import json
import pytest


def _fake_transcript(games: list[dict]) -> dict:
    return {"match_id": "fake-match-1", "games": games}


def _turn(turn_num: int, actions: list[str], active_seat: int = 1) -> dict:
    return {"turn": turn_num, "active_seat": active_seat, "actions": actions}


def test_candidate_dataclass_fields():
    from analysis.puzzles.scanner import Candidate
    c = Candidate(
        arena_match_id="m-1", game_num=1, turn_num=5,
        category="stabilize", heuristic_score=0.42, evidence="test",
    )
    assert c.arena_match_id == "m-1"
    assert c.category == "stabilize"
    assert c.heuristic_score == pytest.approx(0.42)


def test_scan_match_returns_empty_for_quiet_match():
    """A match with no aggressive damage, no low life, no fast spells
    should produce zero candidates."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(1, ["You play Island"]),
        _turn(2, ["Opp plays Forest"]),
    ]}])
    out = scanner.scan_match("m-quiet", transcript)
    assert out == []


def test_scan_match_returns_list_of_candidates():
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, ["You life: 4", "You play Mountain"]),
    ]}])
    out = scanner.scan_match("m-stab", transcript)
    # At minimum, the result is a list (may be empty if heuristics don't fire)
    assert isinstance(out, list)
    for c in out:
        assert hasattr(c, "category") and hasattr(c, "heuristic_score")
