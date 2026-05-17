"""Puzzle graders — keyword (rapidfuzz-fuzzy matching) + LLM (Anthropic
inline call) + dispatcher with fallback chain.

The dispatcher picks the grader for a puzzle's `grading_mode` field and
falls back gracefully when the preferred grader is unavailable. Reuses
the existing Anthropic inline pattern from gui/tabs/ask_claude.py (no
new wrapper module) and the existing rapidfuzz dep.
"""
from __future__ import annotations

import json
import re
from typing import Any

from rapidfuzz import fuzz


_LLM_MODEL = "claude-haiku-4-5-20251001"  # cost-conscious; ~$0.001 per grading
_LLM_MAX_TOKENS = 200
_KEYWORD_FUZZ_THRESHOLD = 80  # rapidfuzz.partial_ratio score, 0-100


class GraderUnavailable(Exception):
    """LLM grader couldn't run (no API key, API error, malformed response)."""


def _get_api_key() -> str:
    """Read Anthropic API key from preferences. Mirrors the pattern from
    gui/tabs/ask_claude.py which uses load_preferences() from gui.tabs.settings."""
    try:
        from gui.tabs.settings import load_preferences
        prefs = load_preferences()
        return (prefs.get("anthropic_api_key") or "").strip()
    except BaseException:
        return ""


def grade_keyword(puzzle: dict[str, Any], user_answer: str) -> dict[str, Any]:
    """Fuzzy-match keywords against the user's answer.

    All keywords matched (100%): 'correct'.
    >=50% matched: 'partial'.
    <50%: 'incorrect'.
    No keywords on puzzle: 'incorrect' with explanation."""
    keywords = puzzle.get("solution_keywords") or []
    if not keywords:
        return {
            "verdict": "incorrect",
            "explanation": "No keywords configured on this puzzle.",
            "grader_used": "keyword",
        }
    answer_lc = (user_answer or "").lower()
    hits, misses = [], []
    for k in keywords:
        score = fuzz.partial_ratio(k.lower(), answer_lc)
        if score >= _KEYWORD_FUZZ_THRESHOLD:
            hits.append(k)
        else:
            misses.append(k)
    ratio = len(hits) / len(keywords)
    if ratio >= 1.0:
        verdict = "correct"
    elif ratio >= 0.5:
        verdict = "partial"
    else:
        verdict = "incorrect"
    explanation = (
        f"Matched {len(hits)}/{len(keywords)} keywords: "
        f"{', '.join(hits) or '(none)'}"
    )
    if misses:
        explanation += f" — missed: {', '.join(misses)}"
    return {"verdict": verdict, "explanation": explanation, "grader_used": "keyword"}


def _build_llm_prompt(puzzle: dict, user_answer: str) -> str:
    """Build the single-message prompt for the LLM grader."""
    scene = puzzle.get("scene") or {}
    you = scene.get("you") or {}
    opp = scene.get("opp") or {}
    hand_names = ", ".join(c.get("name", "?") for c in (you.get("hand") or []))
    your_creatures = ", ".join(
        c.get("name", "?") for c in (you.get("battlefield_creatures") or [])
    )
    opp_creatures = ", ".join(
        c.get("name", "?") for c in (opp.get("battlefield_creatures") or [])
    )
    return (
        f"You are grading an MTG puzzle answer.\n\n"
        f"Puzzle: {puzzle.get('question', '')}\n\n"
        f"Scene context:\n"
        f"  Turn {scene.get('turn_num', '?')}, "
        f"play_or_draw={scene.get('play_or_draw', '?')}\n"
        f"  You: life={you.get('life', '?')}, hand=[{hand_names}], "
        f"battlefield=[{your_creatures}]\n"
        f"  Opp: life={opp.get('life', '?')}, "
        f"battlefield=[{opp_creatures}]\n\n"
        f"Author's correct solution:\n{puzzle.get('solution_text', '')}\n\n"
        f"User's answer:\n{user_answer}\n\n"
        f"Grade the user's answer. Output ONLY this JSON object, "
        f"no preamble:\n\n"
        f'{{"verdict": "<correct|partial|incorrect>", '
        f'"explanation": "<one or two sentences>"}}\n\n'
        f"A \"partial\" verdict means the user identified the right line "
        f"but missed a key detail. \"Incorrect\" means a fundamentally "
        f"different line."
    )


def grade_llm(puzzle: dict[str, Any], user_answer: str) -> dict[str, Any]:
    """Single Anthropic API call. Raises GraderUnavailable on:
      - missing API key
      - any API error
      - malformed JSON response
      - invalid verdict value"""
    api_key = _get_api_key()
    if not api_key:
        raise GraderUnavailable("No anthropic_api_key in preferences")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=_LLM_MAX_TOKENS,
            messages=[
                {"role": "user", "content": _build_llm_prompt(puzzle, user_answer)},
            ],
        )
    except BaseException as e:
        raise GraderUnavailable(f"API call failed: {e}") from e
    try:
        text = resp.content[0].text.strip()
        # Strip markdown code fences if model added them
        text = re.sub(
            r"^```(?:json)?\s*|\s*```$", "",
            text, flags=re.MULTILINE,
        ).strip()
        parsed = json.loads(text)
        verdict = parsed.get("verdict")
        if verdict not in {"correct", "partial", "incorrect"}:
            raise GraderUnavailable(f"Invalid verdict: {verdict!r}")
        return {
            "verdict": verdict,
            "explanation": parsed.get("explanation", ""),
            "grader_used": "llm",
        }
    except GraderUnavailable:
        raise
    except BaseException as e:
        raise GraderUnavailable(f"Response parse failed: {e}") from e


def grade(puzzle: dict[str, Any], user_answer: str) -> dict[str, Any]:
    """Dispatcher with fallback chain per puzzle's grading_mode.

    'llm':     try grade_llm -> fallback to keyword (if keywords) -> fallback to self
    'keyword': try grade_keyword (returns 'incorrect' if no keywords) -> fallback to self
    'self':    return user_marked verdict immediately

    The fallback result's 'grader_used' is set to the actual grader that
    ran, NOT the requested one, so the UI can show '(fallback from X)'."""
    mode = puzzle.get("grading_mode") or "self"
    keywords = puzzle.get("solution_keywords") or []

    if mode == "llm":
        try:
            return grade_llm(puzzle, user_answer)
        except GraderUnavailable:
            pass
        if keywords:
            return grade_keyword(puzzle, user_answer)
        return _self_result()

    if mode == "keyword":
        if keywords:
            return grade_keyword(puzzle, user_answer)
        return _self_result()

    return _self_result()


def _self_result() -> dict[str, Any]:
    return {
        "verdict": "user_marked",
        "explanation": "Self-grade required (use checkmark / X buttons).",
        "grader_used": "self",
    }
