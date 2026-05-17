# Puzzle Tool Phase 3 — Keyword + LLM Graders Design Spec

**Date:** 2026-05-16
**Status:** Approved (pre-implementation)

---

## Problem

Phase 2 of the puzzle tool ships the full Solve | Inbox | Author flow but only ever uses **self-grade** (the user clicks ✓ or ✗ after revealing the author's solution). The puzzles table already has a `grading_mode` column ('self' | 'keyword' | 'llm') from Phase 1, and the puzzle attempts table already has a `grader_used` column — but the actual grading logic for `keyword` and `llm` modes doesn't exist, so puzzles authored with those modes silently fall back to self-grade.

Phase 3 fills in the two missing graders + a dispatcher with a fallback chain.

## Goal

Implement `keyword` and `llm` grading. Wire the existing `grading_mode` field through a dispatcher so a puzzle authored with `grading_mode='llm'` actually invokes the LLM grader (and shows verdict + explanation) instead of falling silently back to self-grade.

**Non-goals:**
- New abstraction layer for Anthropic API (the existing inline pattern from `gui/tabs/ask_claude.py` is fine; copying 3 lines is cheaper than refactoring)
- New database columns (Phase 1 already shipped the schema)
- Multi-shot LLM grading (single API call per attempt; no retries on disagreement)
- Tuning the LLM prompt by puzzle category (one universal prompt for v1)
- Cost dashboards / API spend tracking (use Anthropic's own console)

## Architecture

One new module + one small UI hook.

```
analysis/puzzles/graders.py
  ├─ GraderUnavailable (exception)
  ├─ grade_keyword(puzzle, user_answer) -> dict
  ├─ grade_llm(puzzle, user_answer) -> dict   (raises GraderUnavailable on API key missing)
  └─ grade(puzzle, user_answer) -> dict       (dispatcher with fallback chain)

gui/tabs/puzzles.py::_on_reveal  (modify)
  └─ After existing "show author's solution" code:
       result = analysis.puzzles.graders.grade(self._current_puzzle, user_answer)
       _render_verdict_chip(result)            # new small UI helper
       # ✓/✗ self-grade buttons still appear as override
```

## Module contract

```python
class GraderUnavailable(Exception):
    """LLM grader couldn't run (no API key, API error, malformed response)."""


def grade_keyword(puzzle: dict, user_answer: str) -> dict:
    """Returns {'verdict': str, 'explanation': str, 'grader_used': 'keyword'}.

    Uses rapidfuzz.partial_ratio with threshold 80 for fuzzy keyword
    matching (handles typos and case differences).
    - All keywords matched (>=100%): 'correct'
    - >=50% matched: 'partial'
    - Below 50%: 'incorrect'
    Explanation lists hits + misses."""


def grade_llm(puzzle: dict, user_answer: str) -> dict:
    """Returns {'verdict': str, 'explanation': str, 'grader_used': 'llm'}.

    Raises GraderUnavailable if:
      - anthropic_api_key not in preferences
      - anthropic.Anthropic.messages.create raises any exception
      - response can't be parsed as the expected JSON shape

    Uses claude-haiku-4-5-20251001 (cost-conscious; ~$0.001 per grading).
    max_tokens=200. Single message, no streaming."""


def grade(puzzle: dict, user_answer: str) -> dict:
    """Dispatcher with fallback chain. Returns the same dict shape.

    Picks based on puzzle['grading_mode']:
      - 'llm':     try grade_llm → fallback to keyword (if keywords) → fallback to self
      - 'keyword': try grade_keyword → fallback to self
      - 'self':    return user_marked verdict (caller handles self-grade UI)

    The fallback result has 'grader_used' set to the actual grader that
    ran (NOT the requested one), so the UI can show '(LLM fallback to
    keyword)' messaging."""
```

## LLM prompt template

Single Anthropic API call. Cheap model. Forced JSON output.

```
You are grading an MTG puzzle answer.

Puzzle: {question}

Scene context:
  Turn {turn_num}, play_or_draw={play_or_draw}
  You: life={your_life}, hand={hand_card_names_csv}, battlefield={your_creatures_csv}
  Opp: life={opp_life}, battlefield={opp_creatures_csv}

Author's correct solution:
{solution_text}

User's answer:
{user_answer}

Grade the user's answer. Output ONLY this JSON object, no preamble:

{"verdict": "<correct|partial|incorrect>", "explanation": "<one or two sentences>"}

A "partial" verdict means the user identified the right line but missed
a key detail (e.g., correct spell but wrong target order, missed a
secondary play). "Incorrect" means a fundamentally different line.
```

Scene fields are pulled from `puzzle['scene']` (already a dict in Phase 1's schema). Card lists are comma-joined names. Missing fields default to empty string.

### Response parsing

```python
import json, re
text = resp.content[0].text.strip()
# Strip markdown code fences if model added them despite "no preamble"
text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
parsed = json.loads(text)
verdict = parsed["verdict"]
if verdict not in {"correct", "partial", "incorrect"}:
    raise GraderUnavailable(f"unexpected verdict: {verdict!r}")
return {"verdict": verdict, "explanation": parsed.get("explanation", ""),
        "grader_used": "llm"}
```

Any parse error → `GraderUnavailable` → fallback chain engages.

## Fallback chain truth table

| Puzzle's `grading_mode` | Has keywords? | API key present? | `grade()` returns |
|---|---|---|---|
| `llm` | y | y | LLM (or fallback to keyword if LLM fails) |
| `llm` | y | n | keyword (LLM unavailable) |
| `llm` | n | y | LLM (or self if LLM fails) |
| `llm` | n | n | self (user_marked) |
| `keyword` | y | * | keyword |
| `keyword` | n | * | self (no keywords to match against) |
| `self` | * | * | self (user_marked) |

## UI integration

`gui/tabs/puzzles.py::_on_reveal` — after the existing "show author solution" code:

1. Call `grade(self._current_puzzle, self._answer_edit.toPlainText())`
2. Show a verdict chip below the solution: colored badge ("correct"=green, "partial"=amber, "incorrect"=red, "user_marked"=neutral) with the explanation text
3. If `grader_used != grading_mode`, show a smaller "(fallback from {requested})" tag
4. ✓ "I had it" / ✗ "Missed it" buttons still show — user can override the auto-grade
5. The `record_attempt` call uses the AUTO grader's verdict by default; if the user clicks ✓/✗ AFTER the auto-grade, override the recorded verdict + set `grader_used='self'`

### Visual chip helper

```python
def _verdict_chip_html(result: dict) -> str:
    colors = {
        "correct": "#80c890",
        "partial": "#d4a050",
        "incorrect": "#d88060",
        "user_marked": "#808080",
    }
    color = colors.get(result["verdict"], "#808080")
    fallback_tag = ""
    requested = self._current_puzzle.get("grading_mode") or "self"
    if result["grader_used"] != requested:
        fallback_tag = (
            f" <span style='color:#808080;font-size:9px;'>"
            f"(fallback from {requested})</span>"
        )
    return (
        f"<div style='border-left:3px solid {color};padding:4px 8px;"
        f"background:#1a1a22;color:#e6e6e6;font-size:11px;'>"
        f"<b style='color:{color};'>{result['verdict'].upper()}</b>"
        f"{fallback_tag}<br/>"
        f"<span style='color:#aaa;'>{result['explanation']}</span></div>"
    )
```

## Error handling

| Scenario | Behavior |
|---|---|
| No API key in prefs | `grade_llm` raises GraderUnavailable; chain falls through |
| Anthropic API raises (network, rate limit, auth) | Caught → GraderUnavailable; chain falls through |
| LLM returns non-JSON | Parse error → GraderUnavailable; chain falls through |
| LLM returns JSON with invalid verdict value | GraderUnavailable; chain falls through |
| `solution_keywords` is empty for keyword puzzle | Falls through to self |
| `record_attempt` fails (DB) | Existing Phase 1 error handling — propagates as Exception |

## Testing

`tests/test_graders.py`:

```python
def test_keyword_all_match_returns_correct(...)
def test_keyword_half_match_returns_partial(...)
def test_keyword_zero_match_returns_incorrect(...)
def test_keyword_typo_tolerance_via_rapidfuzz(...)
    # answer with "Slagstom" should match keyword "Slagstorm"
def test_keyword_empty_keywords_returns_incorrect(...)

def test_llm_raises_grader_unavailable_when_no_api_key(monkeypatch, ...)
    # Stub _get_api_key to return ""
def test_llm_parses_well_formed_response(monkeypatch, ...)
    # Mock anthropic.Anthropic to return a fake response
def test_llm_raises_on_malformed_json_response(monkeypatch, ...)
def test_llm_raises_on_invalid_verdict_value(monkeypatch, ...)
def test_llm_strips_markdown_code_fences(monkeypatch, ...)
    # Model wrapped response in ```json ... ``` despite the prompt

def test_grade_dispatcher_uses_llm_when_available(monkeypatch, ...)
def test_grade_dispatcher_falls_back_to_keyword_when_llm_unavailable(...)
def test_grade_dispatcher_falls_back_to_self_when_no_keywords_either(...)
def test_grade_dispatcher_keyword_mode_does_not_call_llm(monkeypatch, ...)
def test_grade_dispatcher_self_mode_returns_user_marked(...)
```

~12-14 tests. LLM tests mock the `anthropic` client via monkeypatch — no real API calls in the test suite.

### Manual smoke

1. Edit (or seed) a puzzle in the DB with `grading_mode='keyword'` and `solution_keywords=['slagstorm', 'each creature']`. Launch GUI → Puzzles → Solve → type "I cast Slagstom targeting each creature" → Reveal → verdict chip should show **PARTIAL** or **CORRECT** with "matched 2/2 keywords" explanation.
2. Same puzzle, type "I attack with everything" → verdict chip should show **INCORRECT** with "matched 0/2 keywords".
3. Set `grading_mode='llm'` on a puzzle. Verify the LLM verdict shows + matches a sensible interpretation of your answer.
4. Remove API key from preferences. Re-run step 3 → should show keyword fallback verdict + "(fallback from llm)" tag.

## File structure

**Create:**
- `analysis/puzzles/graders.py` — grade_keyword + grade_llm + grade dispatcher + GraderUnavailable (~100 lines)
- `tests/test_graders.py` — 12-14 tests (~150 lines)

**Modify:**
- `gui/tabs/puzzles.py` — add `_verdict_chip_html` helper + wire into `_on_reveal` (~30 lines)
- `CLAUDE.md` — note Phase 3 shipping in the Puzzles tab description
- `NEXT_STEPS.md` — strike-through the "Phase 3 (keyword + LLM graders)" mention

## Trade-offs accepted

1. **No shared Anthropic client wrapper.** 3 places now use the inline pattern (ask_claude, set_analysis, graders) — could DRY into `gui/anthropic_client.py`, but touching working tabs has nonzero risk and the inline pattern is small enough. Future refactor if a 4th use case appears.
2. **rapidfuzz threshold 80 is heuristic.** Catches typos and case differences, may occasionally false-positive (e.g., "Lightning Bolt" partial-matches "Lightning Helix"). Tune in Phase 4+ if user reports misclassifications.
3. **Self-grade override always available.** Even after auto-grade, ✓/✗ buttons show. If user clicks one, the recorded attempt is updated. This is intentional — auto-graders are imperfect and the user's own judgment is the source of truth.
4. **Haiku 4.5 over Sonnet/Opus.** Optimizing for cost; nuanced grading may need Opus later. The model ID is a module-level constant (`_LLM_MODEL`), easy to bump.

## Out of scope

- Cost dashboards / API spend tracking
- Per-category prompt tuning (one universal prompt)
- Multi-shot grading or chain-of-thought reasoning
- Sharing graded attempts back to a community pool (Phase 4 if ever)

---

**End of spec.**
