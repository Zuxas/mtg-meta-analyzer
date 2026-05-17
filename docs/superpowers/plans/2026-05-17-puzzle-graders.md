# Puzzle Graders (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill in the two missing puzzle grading paths (keyword + LLM) so puzzles authored with `grading_mode='keyword'` or `'llm'` actually invoke the right grader instead of silently falling back to self-grade.

**Architecture:** New `analysis/puzzles/graders.py` with `grade_keyword`, `grade_llm`, and a `grade` dispatcher that picks per puzzle's `grading_mode` field and falls back gracefully when the preferred grader is unavailable. Small UI hook in `gui/tabs/puzzles.py::_on_reveal` calls the dispatcher and renders a verdict chip below the author's solution. Self-grade ✓/✗ buttons remain as user override.

**Tech Stack:** Python 3.13, `rapidfuzz` (already in deps for keyword fuzzy matching), `anthropic` SDK (already used inline in `gui/tabs/ask_claude.py`), PyQt6, pytest.

**Spec:** `docs/superpowers/specs/2026-05-16-puzzle-graders-design.md` (commit `7abf3d3`)

**Baseline:** commit `f9d7744`, 194/194 tests green after crash-handler fix.

**Ship target:** tonight/tomorrow morning. 3 tasks, ~1.5-2h total.

---

## Critical facts verified during plan-writing

1. **Inline Anthropic pattern exists at `gui/tabs/ask_claude.py:36-50`** — `anthropic.Anthropic(api_key=...)` instantiated in a QThread, no shared wrapper class. We copy that pattern, not refactor it.
2. **API key read pattern** at `ask_claude.py:236-239` — `prefs.get("anthropic_api_key", "").strip()` via `gui.state.UIState`-equivalent prefs accessor. Copy ~3 lines.
3. **`grading_mode` and `grader_used` columns already exist** in `db/puzzles.py` (Phase 1 schema). No new migrations.
4. **`db_puzzles.record_attempt(grader_used=...)` already takes the kwarg** at `db/puzzles.py:159`. Just pass the right value.
5. **`rapidfuzz`** is in `requirements.txt` (added Phase 1 for palette `c:` card-search). `from rapidfuzz import fuzz` then `fuzz.partial_ratio(needle, haystack)` returns 0-100.
6. **No existing `def grade_*` or `def grader_*`** anywhere in the codebase — confirmed via grep. Building fresh.
7. **Puzzle scenes are dicts with `you`/`opp` keys** holding `life`, `hand`, `battlefield_creatures`, etc. Pull fields safely via `.get()` since not all puzzles populate every field.

---

## File structure

**Create:**
- `analysis/puzzles/graders.py` — `GraderUnavailable` + `grade_keyword` + `grade_llm` + `grade` (~120 lines)
- `tests/test_graders.py` — 12-14 tests covering keyword logic, LLM mock, dispatcher fallback chain (~180 lines)

**Modify:**
- `gui/tabs/puzzles.py` — modify `_on_reveal` to call `grade()` + render a verdict chip below the author's solution (~25 lines added). Self-grade buttons stay.
- `CLAUDE.md` — bump "Last updated" + add a line noting Phase 3 shipped
- `NEXT_STEPS.md` — strike-through the Phase 3 scheduled-for-5/22 note

---

## Task 1: `analysis/puzzles/graders.py` + 12 tests

**Files:**
- Create: `analysis/puzzles/graders.py`
- Create: `tests/test_graders.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graders.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_graders.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'analysis.puzzles.graders'`.

- [ ] **Step 3: Implement `analysis/puzzles/graders.py`**

Create the file:

```python
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
    """Read Anthropic API key from preferences. Copy of the pattern from
    gui/tabs/ask_claude.py:236-239."""
    try:
        from gui.state import UIState
        prefs = UIState.load_raw()  # raw prefs dict, not just ui_state slice
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

    'llm':     try grade_llm → fallback to keyword (if keywords) → fallback to self
    'keyword': try grade_keyword (returns 'incorrect' if no keywords) → fallback to self
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
        "explanation": "Self-grade required (use ✓ / ✗ buttons).",
        "grader_used": "self",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_graders.py -v
```

Expected: PASS (all ~15 tests).

If `_get_api_key` fails because `UIState.load_raw` isn't the actual method name (verify in `gui/state.py`), substitute the right call (e.g., `UIState.load()` or whatever returns the merged prefs dict). The test for "no API key" monkeypatches `_get_api_key` directly so the test passes regardless of the internal mechanism.

- [ ] **Step 5: Run full suite, confirm no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 194 + ~15 = ~209 passed.

- [ ] **Step 6: Commit**

```bash
git add analysis/puzzles/graders.py tests/test_graders.py
git commit -m "feat(puzzles): graders module — keyword + LLM + dispatcher with fallback"
```

---

## Task 2: GUI hook in puzzles.py — call grader + render verdict chip

**Files:**
- Modify: `gui/tabs/puzzles.py` — hook into `_on_reveal`, add `_render_verdict_chip` method, add chip widget to layout

- [ ] **Step 1: Locate `_on_reveal` and the solution-label area**

Use Read on `gui/tabs/puzzles.py` around lines 218-235 (the existing `_on_reveal` shows the author's solution). Confirm the existing structure:

```python
def _on_reveal(self) -> None:
    if self._current_puzzle is None:
        return
    self._solution_lbl.setText(...)
    self._solution_lbl.show()
    self._got_it_btn.show(); self._missed_btn.show()
    self._reveal_btn.setEnabled(False)
```

Identify the line where `_solution_lbl.show()` is called — we'll add the chip right after.

- [ ] **Step 2: Add a verdict chip QLabel near the solution label**

In `_build_solve_panel`, find where `self._solution_lbl` is created. Right after that block, add:

```python
self._verdict_chip = QLabel("")
self._verdict_chip.setTextFormat(Qt.TextFormat.RichText)
self._verdict_chip.setWordWrap(True)
self._verdict_chip.hide()
right_v.addWidget(self._verdict_chip)
```

(Use the actual layout variable name found in your read.)

- [ ] **Step 3: Add the `_render_verdict_chip` helper method**

Add to the same class (`PuzzlesTab`):

```python
def _render_verdict_chip(self, result: dict) -> None:
    """Show the auto-grader verdict as a colored chip below the
    author's solution. Self-grade buttons remain for user override."""
    requested = (self._current_puzzle or {}).get("grading_mode") or "self"
    colors = {
        "correct":     "#80c890",
        "partial":     "#d4a050",
        "incorrect":   "#d88060",
        "user_marked": "#808080",
    }
    color = colors.get(result.get("verdict"), "#808080")
    fallback_tag = ""
    if result.get("grader_used") != requested and requested != "self":
        fallback_tag = (
            f" <span style='color:#808080;font-size:9px;'>"
            f"(fallback from {requested})</span>"
        )
    self._verdict_chip.setText(
        f"<div style='border-left:3px solid {color};padding:4px 8px;"
        f"background:#1a1a22;color:#e6e6e6;font-size:11px;'>"
        f"<b style='color:{color};'>{result.get('verdict', '?').upper()}</b>"
        f"{fallback_tag}<br/>"
        f"<span style='color:#aaa;'>{result.get('explanation', '')}</span></div>"
    )
    self._verdict_chip.show()
```

- [ ] **Step 4: Wire `grade()` into `_on_reveal`**

Find `_on_reveal`. After `self._solution_lbl.show()`, add:

```python
# Auto-grade if puzzle's grading_mode is keyword or llm
from analysis.puzzles.graders import grade
user_answer = self._answer_edit.toPlainText().strip()
if user_answer:
    try:
        result = grade(self._current_puzzle, user_answer)
        self._render_verdict_chip(result)
    except BaseException:
        # Defensive: grading should never crash the reveal
        pass
else:
    self._verdict_chip.hide()
```

If `_on_reveal` already early-returns when `_current_puzzle is None`, this code is safely below that guard.

- [ ] **Step 5: Hide the verdict chip when loading next puzzle**

Find `_render_puzzle` (the method called when loading a new puzzle). It should already hide `_solution_lbl` and the ✓/✗ buttons. Add one line:

```python
self._verdict_chip.hide()
```

In the same block where `self._solution_lbl.hide(); self._got_it_btn.hide(); self._missed_btn.hide()`.

- [ ] **Step 6: Headless smoke test**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from gui.tabs.puzzles import PuzzlesTab
tab = PuzzlesTab()
print('verdict_chip exists:', hasattr(tab, '_verdict_chip'))
print('render method exists:', hasattr(tab, '_render_verdict_chip'))
"
```

Expected: both print `True`.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: ~209 passing (no new tests in this task; Task 1's tests cover graders).

- [ ] **Step 8: Commit**

```bash
git add gui/tabs/puzzles.py
git commit -m "feat(puzzles): wire grader dispatcher into _on_reveal + verdict chip widget"
```

---

## Task 3: Manual smoke + docs + push

**Files:**
- Modify: `CLAUDE.md` — bump "Last updated" + add Phase 3 line
- Modify: `NEXT_STEPS.md` — strike-through the Phase 3 scheduled-for-5/22 mention

- [ ] **Step 1: Manual smoke test — keyword grading flow**

User runs:
```bash
python run_gui.py
```

Then: PUZZLES tab → Solve → cycle to one of the new ViewtifulYosh/Drosme puzzles (ids 4-8, all `grading_mode='keyword'`) → type an answer that includes the right keywords (e.g., "attack with Slickshot, then Burst Lightning face") → click Reveal solution.

**Expected:** Author solution appears AS BEFORE, and below it a green "CORRECT — Matched 2/3 keywords..." chip appears. ✓ "I had it" / ✗ "Missed it" buttons still show below as override.

Then: type a wrong answer (e.g., "I scoop") and click Reveal again on the next puzzle → red "INCORRECT — Matched 0/3 keywords" chip.

- [ ] **Step 2: Manual smoke test — fallback flow**

Remove Anthropic API key from `data/preferences.json` (or skip if you don't have one set). Then: change a puzzle's `grading_mode` to `'llm'` via SQL:

```bash
sqlite3 data/mtg_meta.db "UPDATE puzzles SET grading_mode='llm' WHERE id=4;"
```

Re-launch GUI → solve puzzle id=4 → Reveal → verdict chip should show keyword fallback with a "(fallback from llm)" tag (since no API key, llm grader unavailable, falls to keyword).

Then revert: `sqlite3 data/mtg_meta.db "UPDATE puzzles SET grading_mode='keyword' WHERE id=4;"`

- [ ] **Step 3: Update CLAUDE.md**

Edit line 3:
```markdown
Last updated: 2026-05-17 (puzzle Phase 3 graders shipped — keyword + LLM dispatcher)
```

Find the Puzzles tab paragraph in §6 (around line 187 — search for "Puzzles tab"). Add a sentence at the end of the existing description:

```markdown
Phase 3 (shipped 2026-05-17): keyword + LLM grader dispatcher (`analysis/puzzles/graders.py`) auto-grades puzzles whose `grading_mode` is set to `'keyword'` or `'llm'`. Fallback chain: llm → keyword → self. Verdict appears as a colored chip below the author's solution on Reveal; self-grade ✓/✗ buttons remain as user override.
```

- [ ] **Step 4: Update NEXT_STEPS.md**

Find the Phase 2 shipping notes (top of file, has "Phase 3 (keyword + LLM graders) scheduled for 5/22"). Replace that sentence with:

```markdown
**Phase 3 shipped 2026-05-17:** keyword + LLM grader dispatcher with fallback chain. Auto-grades the 5 real-data puzzles (all `grading_mode='keyword'`). LLM grader uses claude-haiku-4-5 (~$0.001/grading) when API key is set.
```

- [ ] **Step 5: Commit + push**

```bash
git add CLAUDE.md NEXT_STEPS.md
git commit -m "docs(puzzles): Phase 3 graders shipped notes"
git push
```

---

## Validation gates

Phase 3 graders is "shipped" when ALL of these are true:

- [ ] `python -m pytest tests/test_graders.py -v` → all ~15 pass
- [ ] `python -m pytest tests/` → ~209 pass (was 194)
- [ ] Headless smoke: `PuzzlesTab` constructs with `_verdict_chip` + `_render_verdict_chip`
- [ ] Manual smoke (user): real puzzle + correct answer → green chip; wrong answer → red chip
- [ ] Fallback works: LLM puzzle without API key shows keyword chip with "(fallback from llm)" tag
- [ ] `git push` succeeds

---

## What this does NOT do (intentional scope limits)

- No shared Anthropic client wrapper (3 uses inline now; refactor if a 4th appears)
- No per-category prompt tuning (one universal LLM prompt)
- No cost tracking / budgeting
- No multi-shot / chain-of-thought grading
- No streaming UI (single-call grade-then-show; the chip pops in at once)
- No grader-feedback persistence (the chip is ephemeral; if user clicks ✓ or ✗ that's what gets recorded via existing `record_attempt`)
