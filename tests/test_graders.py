"""Tests for analysis/puzzles/graders.py — keyword + LLM grading
with fallback dispatcher."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _puzzle(grading_mode: str = "keyword", keywords=None,
            scene_extras: dict = None) -> dict:
    scene = {
        "arena_match_id": "test-m", "game_num": 1, "turn_num": 5,
        "play_or_draw": "draw",
        "you": {"name": "You", "life": 12, "hand": []},
        "opp": {"name": "Opp", "life": 8},
    }
    if scene_extras:
        scene.update(scene_extras)
    return {
        "id": 99,
        "question": "Find lethal — opp at 8",
        "solution_text": "Cast Burst Lightning twice + attack with Slickshot",
        "solution_keywords": keywords if keywords is not None else
            ["burst lightning", "attack", "slickshot"],
        "grading_mode": grading_mode,
        "scene": scene,
    }


# ── Keyword grader ──

def test_keyword_all_match_returns_correct():
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=["burst", "attack", "slickshot"])
    result = grade_keyword(
        puzzle, "I cast Burst Lightning then attack with Slickshot"
    )
    assert result["verdict"] == "correct"
    assert result["grader_used"] == "keyword"
    assert "3/3" in result["explanation"]


def test_keyword_half_match_returns_partial():
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=["burst", "attack", "slickshot", "boomerang"])
    result = grade_keyword(puzzle, "Burst Lightning then attack")
    # 2/4 matched = 50% = partial
    assert result["verdict"] == "partial"


def test_keyword_zero_match_returns_incorrect():
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=["burst", "slickshot"])
    result = grade_keyword(puzzle, "I cast Counterspell and pass")
    assert result["verdict"] == "incorrect"
    assert "0/2" in result["explanation"]


def test_keyword_typo_tolerance_via_rapidfuzz():
    """'Slagstom' (typo) should still match keyword 'Slagstorm' due to
    rapidfuzz partial_ratio threshold 80."""
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=["slagstorm"])
    result = grade_keyword(puzzle, "I cast Slagstom on each creature")
    assert result["verdict"] == "correct"  # 1/1 with typo tolerance


def test_keyword_empty_keywords_returns_incorrect():
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=[])
    result = grade_keyword(puzzle, "anything goes here")
    assert result["verdict"] == "incorrect"
    assert "no keywords" in result["explanation"].lower()


def test_keyword_case_insensitive():
    from analysis.puzzles.graders import grade_keyword
    puzzle = _puzzle(keywords=["BURST", "Attack"])
    result = grade_keyword(puzzle, "burst lightning, then ATTACK")
    assert result["verdict"] == "correct"


# ── LLM grader (mocked) ──

def test_llm_raises_grader_unavailable_when_no_api_key(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "")
    with pytest.raises(graders.GraderUnavailable):
        graders.grade_llm(_puzzle(), "anything")


def test_llm_parses_well_formed_response(monkeypatch):
    """Mock the anthropic client to return a properly-formed JSON verdict."""
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_text = '{"verdict": "correct", "explanation": "Found the line."}'
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text=fake_text)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    fake_anthropic_module = MagicMock()
    fake_anthropic_module.Anthropic.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic_module)

    result = graders.grade_llm(_puzzle(), "I attack with Slickshot")
    assert result["verdict"] == "correct"
    assert result["explanation"] == "Found the line."
    assert result["grader_used"] == "llm"


def test_llm_strips_markdown_code_fences(monkeypatch):
    """Model sometimes wraps response in ```json ... ``` despite the
    prompt saying 'no preamble'. Strip those before json.loads."""
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_text = '```json\n{"verdict": "partial", "explanation": "Close."}\n```'
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text=fake_text)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    result = graders.grade_llm(_puzzle(), "partial answer")
    assert result["verdict"] == "partial"


def test_llm_raises_on_malformed_json(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="not json at all just prose")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    with pytest.raises(graders.GraderUnavailable):
        graders.grade_llm(_puzzle(), "anything")


def test_llm_raises_on_invalid_verdict_value(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_text = '{"verdict": "maybe_correct_idk", "explanation": "..."}'
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text=fake_text)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    with pytest.raises(graders.GraderUnavailable):
        graders.grade_llm(_puzzle(), "anything")


# ── Dispatcher fallback chain ──

def test_grade_dispatcher_uses_llm_when_requested_and_available(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_text = '{"verdict": "correct", "explanation": "ok"}'
    fake_resp = MagicMock(); fake_resp.content = [MagicMock(text=fake_text)]
    fake_client = MagicMock(); fake_client.messages.create.return_value = fake_resp
    fake_anthropic = MagicMock(); fake_anthropic.Anthropic.return_value = fake_client
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    result = graders.grade(_puzzle(grading_mode="llm"), "my answer")
    assert result["grader_used"] == "llm"


def test_grade_dispatcher_falls_back_to_keyword_when_llm_unavailable(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "")  # no API key
    result = graders.grade(_puzzle(grading_mode="llm",
                                    keywords=["burst", "attack"]),
                           "I cast Burst Lightning and attack")
    assert result["grader_used"] == "keyword"
    assert result["verdict"] == "correct"


def test_grade_dispatcher_falls_back_to_self_when_no_keywords(monkeypatch):
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "")
    result = graders.grade(_puzzle(grading_mode="llm", keywords=[]),
                           "user's answer text")
    assert result["grader_used"] == "self"
    assert result["verdict"] == "user_marked"


def test_grade_dispatcher_keyword_mode_does_not_call_llm(monkeypatch):
    """If puzzle requests keyword mode, dispatcher must NOT make an
    API call even if a key is present."""
    from analysis.puzzles import graders
    monkeypatch.setattr(graders, "_get_api_key", lambda: "fake-key")

    fake_anthropic = MagicMock()  # whose .Anthropic is also a MagicMock
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)

    graders.grade(_puzzle(grading_mode="keyword",
                          keywords=["burst", "attack"]),
                  "cast Burst Lightning, attack")
    # Confirm: Anthropic constructor was NOT called
    fake_anthropic.Anthropic.assert_not_called()


def test_grade_dispatcher_self_mode_returns_user_marked():
    from analysis.puzzles.graders import grade
    result = grade(_puzzle(grading_mode="self"), "anything")
    assert result["grader_used"] == "self"
    assert result["verdict"] == "user_marked"
