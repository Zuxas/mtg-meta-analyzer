"""Tests for analysis/puzzles/scene_builder.py."""
import json
from pathlib import Path

import pytest


def _fake_transcript() -> dict:
    """A minimal transcript dict shaped like analysis.replay_transcript output."""
    return {
        "match_id": "fake-1",
        "games": [
            {"game_num": 1, "turns": [
                {"turn": 1, "active_seat": 1, "actions": [
                    "You play Island",
                    "Opening hand (kept on 7): Island, Mountain, Burst Lightning, Eddymurk Crab, Slickshot Show-Off, Boomerang Basics, Get Out",
                ]},
                {"turn": 7, "active_seat": 1, "actions": [
                    "Opp life: 12",
                    "You life: 4",
                    "You play Mountain",
                ]},
            ]},
        ],
    }


def test_scene_dataclass_can_be_constructed():
    from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
    you = PlayerState(name="Z", archetype="Tokyo Prowess", life=4)
    opp = PlayerState(name="M", archetype="Mono Green Landfall", life=12)
    s = Scene(arena_match_id="m1", game_num=1, turn_num=7,
              play_or_draw="draw", you=you, opp=opp, notes="")
    assert s.you.life == 4 and s.opp.life == 12
    assert s.turn_num == 7


def test_scene_to_dict_round_trip():
    from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
    s = Scene(
        arena_match_id="m1", game_num=1, turn_num=7, play_or_draw="draw",
        you=PlayerState(name="Z", archetype="Tokyo", life=4,
                        hand=[CardInZone(name="Burst Lightning", grpid=12345)]),
        opp=PlayerState(name="M", archetype="MGL", life=12),
        notes="",
    )
    d = s.to_dict()
    assert d["you"]["hand"][0]["name"] == "Burst Lightning"
    s2 = Scene.from_dict(d)
    assert s2.you.hand[0].name == "Burst Lightning"


def test_build_scene_returns_none_for_unknown_match(tmp_path, monkeypatch):
    from analysis.puzzles import scene_builder
    monkeypatch.setattr(scene_builder, "CACHE_DIR", tmp_path)
    out = scene_builder.build_scene(arena_match_id="missing", game_num=1, turn_num=7)
    assert out is None


def test_build_scene_returns_scene_for_cached_transcript(tmp_path, monkeypatch):
    from analysis.puzzles import scene_builder
    monkeypatch.setattr(scene_builder, "CACHE_DIR", tmp_path)
    (tmp_path / "fake-1.json").write_text(json.dumps(_fake_transcript()))
    s = scene_builder.build_scene(arena_match_id="fake-1", game_num=1, turn_num=7)
    assert s is not None
    assert s.turn_num == 7
    assert s.you.life == 4
    assert s.opp.life == 12
