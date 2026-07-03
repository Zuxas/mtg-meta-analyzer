"""Promote-from-embedded-scene path (T2 synthetic candidates).

Sim-mined lethal candidates have no cached MTGA replay; they carry the full
Scene + solution line in the inbox row's `evidence` JSON. These tests cover the
pure helpers that turn that evidence into a pre-filled author form. (Qt dialog
construction is exercised by the headless smoke, not here.)
"""
from __future__ import annotations

import json

from gui.tabs.puzzles import _format_line, _prefill_from_evidence
from analysis.puzzles.scene_builder import Scene, PlayerState


def _scene_dict(opp_life: int = 8) -> dict:
    return Scene(
        arena_match_id="goldfish:boros:3", game_num=3, turn_num=6,
        play_or_draw="play",
        you=PlayerState(name="You", life=19, library_count=40),
        opp=PlayerState(name="Goldfish", life=opp_life),
        notes="mined",
    ).to_dict()


def test_format_line_numbers_and_cards():
    sol, cards = _format_line(["PLAY_LAND:Marsh Flats", "Lightning Bolt"])
    assert "1. Play Marsh Flats" in sol
    assert "2. Cast Lightning Bolt" in sol
    assert sol.strip().endswith("Then attack for lethal.")
    assert cards == ["Marsh Flats", "Lightning Bolt"]


def test_prefill_parses_embedded_scene():
    row = {"evidence": json.dumps({
        "source": "goldfish-miner",
        "solution_line": ["PLAY_LAND:Marsh Flats", "Galvanic Discharge"],
        "greedy_misses": True,
        "scene": _scene_dict(opp_life=7),
    })}
    out = _prefill_from_evidence(row)
    assert out is not None
    scene, kwargs = out
    assert scene.opp.life == 7
    assert "opponent at 7" in kwargs["suggested_question"]
    assert kwargs["suggested_difficulty"] == 4          # greedy_misses -> harder
    assert "Marsh Flats" in kwargs["suggested_keywords"]
    assert kwargs["suggested_grading"] == "self"


def test_prefill_difficulty_easy_when_greedy_finds_it():
    row = {"evidence": json.dumps({
        "solution_line": ["Lightning Bolt"],
        "greedy_misses": False,
        "scene": _scene_dict(),
    })}
    _, kwargs = _prefill_from_evidence(row)
    assert kwargs["suggested_difficulty"] == 2


def test_prefill_returns_none_without_embedded_scene():
    # real-match candidates (rebuilt from a cached replay) have no scene here
    assert _prefill_from_evidence({"evidence": None}) is None
    assert _prefill_from_evidence({"evidence": "not json"}) is None
    assert _prefill_from_evidence({"evidence": json.dumps({"foo": 1})}) is None
    assert _prefill_from_evidence({}) is None
