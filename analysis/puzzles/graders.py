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


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_NUMBER_TOL_PP = 3.0  # accept band half-width, percentage points


def grade_number(
    puzzle: dict[str, Any], user_answer: str, *, tol: float = _NUMBER_TOL_PP
) -> dict[str, Any]:
    """Exact-number grader for math drills (outs %, EV, etc.).

    Fuzzy keyword matching false-positives on short numbers
    (``partial_ratio("38.7", "...8.7%")`` -> 100), so numeric puzzles route
    here instead. ``solution_keywords`` holds the canonical numeric answer(s)
    as strings; when a puzzle stores TWO (e.g. the exact hypergeometric value
    AND the looks*outs shorthand it teaches), we accept the whole *span*
    between them widened by ``tol`` on each side. This is deliberate: a
    student who correctly applies the shorthand the drill just taught (which
    overshoots the exact answer) must not be marked wrong. Because we treat
    the numbers as an interval [min, max], not discrete points, there is no
    dead zone in the middle.

    Verdicts: in-band -> correct; within one more ``tol`` of the band ->
    partial; else incorrect. A fraction (0-1) answer is also tried *100 so
    "0.39" grades the same as "39"."""
    kws = puzzle.get("solution_keywords") or []
    canon = [float(m) for k in kws for m in _NUM_RE.findall(str(k))]
    if not canon:
        return {
            "verdict": "incorrect",
            "explanation": "No numeric answer configured on this puzzle.",
            "grader_used": "number",
        }
    lo, hi = min(canon) - tol, max(canon) + tol
    raw = [float(m) for m in _NUM_RE.findall(user_answer or "")]
    if not raw:
        return {
            "verdict": "incorrect",
            "explanation": (
                f"No number found in your answer "
                f"(expected ~{min(canon):.1f}-{max(canon):.1f}%)."
            ),
            "grader_used": "number",
        }
    # Try each user number as-is and, if it looks like a fraction, *100.
    cands: list[float] = []
    for u in raw:
        cands.append(u)
        if 0.0 <= u <= 1.0:
            cands.append(u * 100.0)
    dist = min(0.0 if lo <= c <= hi else min(abs(c - lo), abs(c - hi)) for c in cands)
    target = (
        f"{min(canon):.1f}%"
        if len(canon) == 1
        else f"{min(canon):.1f}-{max(canon):.1f}%"
    )
    if dist <= 0.0:
        verdict, why = "correct", f"In range ({target})."
    elif dist <= tol:
        verdict, why = "partial", f"Close — off by ~{dist:.1f}pp from {target}."
    else:
        verdict, why = "incorrect", f"Off by ~{dist:.1f}pp from {target}."
    return {"verdict": verdict, "explanation": why, "grader_used": "number"}


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

    if mode == "number":
        # Deterministic, no external dep, no fallback needed.
        return grade_number(puzzle, user_answer)

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
