# Find-the-Line Puzzle Tool — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-extract puzzle candidates from the replay corpus, surface them in an Inbox UI, and let the user promote them into finished puzzles via an in-GUI Author dialog. Removes the need to hand-author every puzzle via the seeder CLI.

**Architecture:** New `analysis/puzzles/scanner.py` walks cached `data/match_replays/*.json` per-category heuristics and writes Candidate rows to the existing `puzzle_inbox` table. The PUZZLES tab gets restructured into `Solve | Inbox | Author` sub-tabs. The Author dialog (reused for Inbox-promote AND for Match-History right-click) shows a `PuzzleSceneWidget` preview plus a form for question/solution/keywords/difficulty.

**Tech Stack:** Python 3.13, PyQt6, SQLite, pytest. Reuses every Phase 1 building block (db/puzzles.py, scene_builder.py, puzzle_scene.py, card_image_cache.py).

**Spec:** `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`

**Phase 1 baseline:** commits `83845c1` through `d326292`, 162/162 tests green, all card-data verified via `_card()` helper in seeder.

**Ship target:** end of 2026-05-20 (Wednesday).

---

## Critical lessons from Phase 1 — bake these in

1. **Every card name must be verified via `db.card_data`** before being persisted. The scanner extracts names from replay transcripts; some will be misspelled, alt-arted, or token-only. Drop or flag any name the lookup misses — never let it through.
2. **Tests must do real round-trips** through the public API, not just smoke for table existence. Inbox tests insert + query + assert ordering / counts.
3. **Use `db.helpers.utc_now`** for all timestamps. Don't re-import `datetime` / `timezone`.
4. **Widget reuse needs both widget AND layout cleanup paths** (see `PuzzleSceneWidget._clear_layout`). Author dialog's scene preview reuses the same widget — if you call `set_scene()` twice on the same instance, the existing `_clear_layout` already handles it. Don't add a parallel cleanup.

---

## File Structure

**Create:**
- `analysis/puzzles/scanner.py` — `Candidate` dataclass + 3 heuristic functions + `scan_match` + `scan_all` orchestrator
- `scripts/scan_for_puzzles.py` — CLI that runs `scan_all()` and saves to inbox
- `gui/widgets/puzzle_author_dialog.py` — `PuzzleAuthorDialog(QDialog)` with form + scene preview
- `tests/test_puzzles_inbox.py` — CRUD tests for `puzzle_inbox` API
- `tests/test_scanner.py` — heuristic tests with fixture transcripts
- `tests/test_puzzle_author_dialog.py` — dialog smoke tests

**Modify:**
- `db/puzzles.py` — append inbox CRUD (`save_inbox_candidates`, `get_inbox`, `dismiss_inbox`, `promote_inbox`)
- `gui/tabs/puzzles.py` — restructure outer layout into Solve | Inbox | Author sub-tabs; add Inbox table widget
- `gui/widgets/deck_match_history.py` — add right-click "📥 Create puzzle from this turn" context menu item on the recent-matches table
- `tests/test_puzzles_tab.py` — add Inbox sub-mode test

---

## Task 1: Inbox CRUD additions

**Files:**
- Modify: `db/puzzles.py` (append after `delete_puzzle`)
- Create: `tests/test_puzzles_inbox.py`

- [ ] **Step 1: Write failing inbox CRUD tests**

Create `tests/test_puzzles_inbox.py`:

```python
"""Tests for puzzle_inbox CRUD in db/puzzles.py."""
import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_mtg_meta.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "archive.db")
    yield db_path


def _sample_candidate(**overrides) -> dict:
    base = {
        "arena_match_id": "m-1",
        "game_num": 1,
        "turn_num": 7,
        "category": "stabilize",
        "heuristic_score": 0.75,
        "evidence": "you life=4, won match",
    }
    base.update(overrides)
    return base


def test_save_inbox_candidates_inserts_rows(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    n = puzzles.save_inbox_candidates([
        _sample_candidate(arena_match_id="m-1", turn_num=5),
        _sample_candidate(arena_match_id="m-2", turn_num=7),
    ])
    assert n == 2
    rows = puzzles.get_inbox()
    assert len(rows) == 2


def test_save_inbox_candidates_dedups_on_match_turn_category(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_inbox_candidates([_sample_candidate(arena_match_id="m-1", turn_num=5)])
    # Same (match, turn, category) — should NOT create a duplicate row
    puzzles.save_inbox_candidates([_sample_candidate(arena_match_id="m-1", turn_num=5)])
    rows = puzzles.get_inbox()
    assert len(rows) == 1


def test_get_inbox_filters_dismissed(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_inbox_candidates([
        _sample_candidate(arena_match_id="m-1"),
        _sample_candidate(arena_match_id="m-2"),
    ])
    rows = puzzles.get_inbox()
    assert len(rows) == 2
    # Dismiss the first row
    puzzles.dismiss_inbox(rows[0]["id"])
    assert len(puzzles.get_inbox()) == 1


def test_get_inbox_orders_by_score_desc(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_inbox_candidates([
        _sample_candidate(arena_match_id="m-low", heuristic_score=0.2),
        _sample_candidate(arena_match_id="m-hi", heuristic_score=0.9),
        _sample_candidate(arena_match_id="m-mid", heuristic_score=0.5),
    ])
    rows = puzzles.get_inbox()
    scores = [r["heuristic_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_get_inbox_filters_by_category(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_inbox_candidates([
        _sample_candidate(arena_match_id="m-1", category="find_lethal"),
        _sample_candidate(arena_match_id="m-2", category="stabilize"),
        _sample_candidate(arena_match_id="m-3", category="tempo"),
    ])
    assert len(puzzles.get_inbox(category="find_lethal")) == 1
    assert len(puzzles.get_inbox(category="stabilize")) == 1
    assert len(puzzles.get_inbox()) == 3


def test_promote_inbox_links_to_puzzle_id(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_inbox_candidates([_sample_candidate(arena_match_id="m-1")])
    inbox_id = puzzles.get_inbox()[0]["id"]
    # Create a fake puzzle to link to
    pid = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m-1", game_num=1, turn_num=7,
        category="stabilize", difficulty=2, question="q",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene={"arena_match_id": "m-1", "game_num": 1,
                                       "turn_num": 7, "play_or_draw": "draw",
                                       "you": {"name": "Y", "life": 4},
                                       "opp": {"name": "O", "life": 12}},
    )
    puzzles.promote_inbox(inbox_id, puzzle_id=pid)
    # After promote, get_inbox should no longer include the promoted row
    # (because get_inbox filters dismissed_at IS NULL AND promoted_puzzle_id IS NULL)
    assert len(puzzles.get_inbox()) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_puzzles_inbox.py -v
```

Expected: FAIL on `puzzles.save_inbox_candidates` (not defined).

- [ ] **Step 3: Implement inbox CRUD in `db/puzzles.py`**

Append to `db/puzzles.py`:

```python
def save_inbox_candidates(candidates: list[dict[str, Any]]) -> int:
    """Bulk-upsert candidates into puzzle_inbox.

    Dedups on (arena_match_id, game_num, turn_num, category) — re-running
    the scanner on the same corpus is idempotent. Returns the count of
    rows actually inserted (skipped duplicates not counted)."""
    _ensure_tables()
    inserted = 0
    with get_connection() as conn:
        for cand in candidates:
            existing = conn.execute(
                "SELECT id FROM puzzle_inbox WHERE "
                "arena_match_id = ? AND game_num IS ? AND turn_num = ? "
                "AND category = ?",
                (cand["arena_match_id"], cand.get("game_num"),
                 cand["turn_num"], cand["category"]),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO puzzle_inbox ("
                "arena_match_id, game_num, turn_num, category, "
                "heuristic_score, evidence, discovered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    cand["arena_match_id"], cand.get("game_num"),
                    cand["turn_num"], cand["category"],
                    cand["heuristic_score"], cand.get("evidence", ""),
                    _utc_now(),
                ),
            )
            inserted += 1
    return inserted


def get_inbox(
    *,
    category: Optional[str] = None,
    top_n: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return undismissed, unpromoted inbox candidates, ranked by
    heuristic_score DESC. Optional category filter + top-N cap."""
    _ensure_tables()
    clauses = [
        "dismissed_at IS NULL",
        "promoted_puzzle_id IS NULL",
    ]
    params: list[Any] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    sql = (
        "SELECT * FROM puzzle_inbox WHERE "
        + " AND ".join(clauses)
        + " ORDER BY heuristic_score DESC, id DESC"
    )
    if top_n is not None:
        sql += " LIMIT ?"
        params.append(top_n)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def dismiss_inbox(inbox_id: int) -> None:
    """Mark a candidate dismissed so it stops appearing in get_inbox()."""
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            "UPDATE puzzle_inbox SET dismissed_at = ? WHERE id = ?",
            (_utc_now(), inbox_id),
        )


def promote_inbox(inbox_id: int, puzzle_id: int) -> None:
    """Link the inbox row to the new puzzle so it stops appearing in
    get_inbox() and we can trace which puzzle came from which candidate."""
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            "UPDATE puzzle_inbox SET promoted_puzzle_id = ? WHERE id = ?",
            (puzzle_id, inbox_id),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_puzzles_inbox.py -v
```

Expected: PASS (6 passed)

- [ ] **Step 5: Run full suite, ensure no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 162 + 6 = 168 passed.

- [ ] **Step 6: Commit**

```bash
git add db/puzzles.py tests/test_puzzles_inbox.py
git commit -m "feat(puzzles): inbox CRUD — save_inbox_candidates + get_inbox + dismiss + promote"
```

---

## Task 2: Scanner — Candidate dataclass + transcript walker

**Files:**
- Create: `analysis/puzzles/scanner.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: Write failing test for the base scanner shape**

Create `tests/test_scanner.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the base scanner module**

Create `analysis/puzzles/scanner.py`:

```python
"""Replay corpus scanner — finds puzzle-worthy turns.

Per-category heuristic functions identify candidate turns based on
text-action patterns in the cached transcript JSON. The orchestrator
walks all replays in data/match_replays/*.json and emits Candidate dicts
that get persisted to the puzzle_inbox table via db.puzzles.

This module is intentionally pure — no DB writes, no GUI. The caller
(scripts/scan_for_puzzles.py) saves results.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "match_replays"


@dataclass
class Candidate:
    """One puzzle-worthy turn extracted from a replay."""
    arena_match_id: str
    game_num: int
    turn_num: int
    category: str           # 'find_lethal' | 'stabilize' | 'tempo'
    heuristic_score: float  # [0.0, 1.0], for ranking
    evidence: str           # short human-readable why-flagged note

    def to_dict(self) -> dict:
        return asdict(self)


# Regex pattern bank — reused by individual heuristics
_LIFE_RE = re.compile(r"(opp|you)\s+life[:\s]+(-?\d+)", re.IGNORECASE)
_YOU_CAST_RE = re.compile(r"^You cast\s+(.+?)(\s+→|\s+\(|$)", re.IGNORECASE)


def _parse_life_from_actions(actions: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Return (your_life, opp_life) parsed from a turn's actions list,
    or (None, None) if neither was logged that turn."""
    you = opp = None
    for a in actions or []:
        m = _LIFE_RE.search(a or "")
        if not m:
            continue
        who, val = m.group(1).lower(), int(m.group(2))
        if who == "you":
            you = val
        elif who == "opp":
            opp = val
    return you, opp


def scan_match(arena_match_id: str, transcript: dict) -> list[Candidate]:
    """Run all 3 category heuristics on one match transcript. Returns
    Candidate list (may be empty). Pure — no I/O."""
    candidates: list[Candidate] = []
    games = transcript.get("games") or []
    for g in games:
        game_num = int(g.get("game_num", 1))
        turns = g.get("turns") or []
        # Each heuristic returns its own candidates for this game
        candidates.extend(_scan_find_lethal(arena_match_id, game_num, turns))
        candidates.extend(_scan_stabilize(arena_match_id, game_num, turns))
        candidates.extend(_scan_tempo(arena_match_id, game_num, turns))
    return candidates


# ── Stub heuristics — filled in by later tasks ────────────────────

def _scan_find_lethal(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    return []


def _scan_stabilize(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    return []


def _scan_tempo(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scanner.py -v
```

Expected: PASS (3 passed) — heuristics are stubs so candidates are empty.

- [ ] **Step 5: Commit**

```bash
git add analysis/puzzles/scanner.py tests/test_scanner.py
git commit -m "feat(puzzles): scanner — Candidate dataclass + scan_match orchestrator"
```

---

## Task 3: Scanner — `find_lethal` heuristic

**Files:**
- Modify: `analysis/puzzles/scanner.py`
- Modify: `tests/test_scanner.py`

- [ ] **Step 1: Add failing find_lethal test**

Append to `tests/test_scanner.py`:

```python
def test_find_lethal_fires_when_opp_dies_after_3_plus_spells():
    """Spec heuristic: cast >= 3 noncreature spells AND opp life
    went from >= 8 to 0 in one turn."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["Opp life: 12"]),
        _turn(7, [
            "Opp life: 12",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "Opp life: 0",
        ]),
    ]}])
    out = scanner.scan_match("m-lethal", transcript)
    lethal = [c for c in out if c.category == "find_lethal"]
    assert len(lethal) >= 1
    c = lethal[0]
    assert c.turn_num == 7
    assert 0.0 < c.heuristic_score <= 1.0


def test_find_lethal_does_not_fire_for_low_spell_count():
    """One spell is not a find-lethal puzzle, even if opp died."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(7, [
            "Opp life: 12",
            "You cast Lightning Bolt → opponent",
            "Opp life: 0",
        ]),
    ]}])
    out = scanner.scan_match("m-one", transcript)
    lethal = [c for c in out if c.category == "find_lethal"]
    assert lethal == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py::test_find_lethal_fires_when_opp_dies_after_3_plus_spells tests/test_scanner.py::test_find_lethal_does_not_fire_for_low_spell_count -v
```

Expected: FAIL (heuristic still returns []).

- [ ] **Step 3: Implement `_scan_find_lethal`**

Replace the stub in `analysis/puzzles/scanner.py`:

```python
def _scan_find_lethal(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    """Find lethal heuristic: turn N where you cast >= 3 noncreature
    spells AND opp life went from >= 8 down to 0 in that turn.

    Score: 0.6 * (spells_cast / 5) + 0.4 * (1 - opp_final_life / starting_life)
    (per spec; first-pass formula, tunes after real data lands)."""
    out: list[Candidate] = []
    for t in turns:
        actions = t.get("actions") or []
        spells_cast = sum(
            1 for a in actions if _YOU_CAST_RE.search(a or "")
        )
        if spells_cast < 3:
            continue
        # Capture opp life trajectory across this turn
        opp_lives: list[int] = []
        for a in actions:
            m = _LIFE_RE.search(a or "")
            if m and m.group(1).lower() == "opp":
                opp_lives.append(int(m.group(2)))
        if not opp_lives:
            continue
        starting = max(opp_lives)
        final = min(opp_lives)
        if starting < 8 or final > 0:
            continue
        # Score
        spell_term = min(1.0, spells_cast / 5.0) * 0.6
        life_term = (1.0 - final / max(starting, 1)) * 0.4
        score = round(spell_term + life_term, 3)
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="find_lethal",
            heuristic_score=score,
            evidence=f"{spells_cast} spells, opp {starting}→{final}",
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scanner.py -v
```

Expected: PASS (5 passed — 3 from Task 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add analysis/puzzles/scanner.py tests/test_scanner.py
git commit -m "feat(puzzles): scanner — find_lethal heuristic"
```

---

## Task 4: Scanner — `stabilize` heuristic

**Files:**
- Modify: `analysis/puzzles/scanner.py`
- Modify: `tests/test_scanner.py`

- [ ] **Step 1: Add failing stabilize tests**

Append to `tests/test_scanner.py`:

```python
def test_stabilize_fires_when_low_life_and_match_continued():
    """Spec heuristic: turn N where your life <= 5 AND match continued
    past N AND you eventually won."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["You life: 4"]),
        _turn(7, ["You life: 6"]),  # survived the spot
        _turn(8, ["Opp life: 0"]),  # eventually won
    ]}])
    out = scanner.scan_match("m-stab", transcript)
    stab = [c for c in out if c.category == "stabilize"]
    assert len(stab) >= 1
    assert stab[0].turn_num == 6  # the low-life turn


def test_stabilize_does_not_fire_if_match_ended_with_loss():
    """If you died, the low-life turn isn't a stabilize candidate."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["You life: 4"]),
        _turn(7, ["You life: 0"]),  # died
    ]}])
    out = scanner.scan_match("m-lose", transcript)
    stab = [c for c in out if c.category == "stabilize"]
    assert stab == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py::test_stabilize_fires_when_low_life_and_match_continued tests/test_scanner.py::test_stabilize_does_not_fire_if_match_ended_with_loss -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `_scan_stabilize`**

Replace the stub:

```python
def _scan_stabilize(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    """Stabilize heuristic: turn N where your life <= 5 AND match
    continued past N AND you eventually won the match.

    Score: 0.5 * (1 - your_life_at_turn / 20) + 0.5 * (did_win ? 1.0 : 0.5)
    """
    if not turns:
        return []
    # Determine if user eventually won this game (opp life hit 0 last)
    did_win = False
    for t in turns:
        for a in t.get("actions") or []:
            m = _LIFE_RE.search(a or "")
            if m and m.group(1).lower() == "opp" and int(m.group(2)) <= 0:
                did_win = True
                break
        if did_win:
            break

    out: list[Candidate] = []
    for idx, t in enumerate(turns):
        your_life, _ = _parse_life_from_actions(t.get("actions") or [])
        if your_life is None or your_life > 5:
            continue
        # Match must continue past this turn — i.e. there's at least one
        # later turn AND user didn't die during this turn.
        if your_life <= 0:
            continue
        if idx >= len(turns) - 1:
            continue
        win_term = 1.0 if did_win else 0.5
        life_term = 1.0 - (max(your_life, 0) / 20.0)
        score = round(0.5 * life_term + 0.5 * win_term, 3)
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="stabilize",
            heuristic_score=score,
            evidence=f"your life {your_life}, won={did_win}",
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scanner.py -v
```

Expected: PASS (7 passed — 5 from before + 2 new).

- [ ] **Step 5: Commit**

```bash
git add analysis/puzzles/scanner.py tests/test_scanner.py
git commit -m "feat(puzzles): scanner — stabilize heuristic"
```

---

## Task 5: Scanner — `tempo` heuristic (simplified Phase 2 version)

**Files:**
- Modify: `analysis/puzzles/scanner.py`
- Modify: `tests/test_scanner.py`

**Scope note:** The spec lists tempo as "instant cast at sorcery speed (no mana held up) AND opp's next turn could have benefited." That's hard to detect from text actions alone. For Phase 2 we ship a SIMPLER version: flag turns where you cast >= 2 INSTANT cards during your own main phase (instant-spell sorcery-speed use is the most common tempo mis-play). Tuning happens in Phase 3+.

- [ ] **Step 1: Add failing tempo test**

Append to `tests/test_scanner.py`:

```python
def test_tempo_fires_when_multiple_instants_cast_on_own_turn(monkeypatch):
    """Simplified Phase 2 heuristic: 2+ instants cast on your own turn.

    Patches card_data lookup so the test doesn't depend on prod DB."""
    from analysis.puzzles import scanner

    def _fake_is_instant(name: str) -> bool:
        return name.strip() in {"Burst Lightning", "Boomerang Basics"}

    monkeypatch.setattr(scanner, "_is_instant_card", _fake_is_instant)
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, [
            "You cast Burst Lightning → opp creature",
            "You cast Boomerang Basics → opp permanent",
        ], active_seat=1),
    ]}])
    out = scanner.scan_match("m-tempo", transcript)
    tempo = [c for c in out if c.category == "tempo"]
    assert len(tempo) >= 1
    assert tempo[0].turn_num == 5


def test_tempo_does_not_fire_on_opp_turn(monkeypatch):
    """Instants cast on opp's turn are reactive, not tempo mis-plays."""
    from analysis.puzzles import scanner
    monkeypatch.setattr(scanner, "_is_instant_card",
                         lambda n: n.strip() in {"Burst Lightning"})
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, [
            "You cast Burst Lightning → opp creature",
            "You cast Burst Lightning → opp creature",
        ], active_seat=2),  # opp's turn
    ]}])
    out = scanner.scan_match("m-tempo-opp", transcript)
    tempo = [c for c in out if c.category == "tempo"]
    assert tempo == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py::test_tempo_fires_when_multiple_instants_cast_on_own_turn tests/test_scanner.py::test_tempo_does_not_fire_on_opp_turn -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `_scan_tempo` + `_is_instant_card` helper**

Replace the stub and add the helper at module-bottom:

```python
def _scan_tempo(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    """Simplified Phase 2 tempo heuristic: turn N (your turn) where
    you cast >= 2 INSTANT-typed cards. Instant-speed cards used at
    sorcery speed often represent missed tempo (could have held them
    for opp's turn for more info).

    Score: 0.5 * (instants_cast / 3) + 0.5 (constant for "interesting"
    until we have richer data to differentiate)."""
    out: list[Candidate] = []
    for t in turns:
        if int(t.get("active_seat", 0)) != 1:
            continue  # only your turns
        actions = t.get("actions") or []
        instant_names: list[str] = []
        for a in actions:
            m = _YOU_CAST_RE.search(a or "")
            if not m:
                continue
            name = m.group(1).strip()
            if _is_instant_card(name):
                instant_names.append(name)
        if len(instant_names) < 2:
            continue
        score = round(
            0.5 * min(1.0, len(instant_names) / 3.0) + 0.5, 3
        )
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="tempo",
            heuristic_score=score,
            evidence=f"{len(instant_names)} instants on own turn: "
                     + ", ".join(instant_names[:3]),
        ))
    return out


def _is_instant_card(card_name: str) -> bool:
    """Cheap card_data lookup for the 'is this an Instant?' check.

    Returns False on lookup miss — don't flag cards we can't identify
    (avoids false positives for fabricated / token / split-card names)."""
    try:
        from db.database import get_connection
        with get_connection() as c:
            row = c.execute(
                "SELECT type_line FROM card_data WHERE name = ?",
                (card_name,),
            ).fetchone()
        if row is None:
            return False
        return "instant" in (row["type_line"] or "").lower()
    except Exception:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scanner.py -v
```

Expected: PASS (9 passed — 7 from before + 2 new).

- [ ] **Step 5: Commit**

```bash
git add analysis/puzzles/scanner.py tests/test_scanner.py
git commit -m "feat(puzzles): scanner — tempo heuristic (simplified Phase 2 version)"
```

---

## Task 6: Scanner orchestrator + CLI

**Files:**
- Modify: `analysis/puzzles/scanner.py` (add `scan_all` orchestrator)
- Create: `scripts/scan_for_puzzles.py`
- Modify: `tests/test_scanner.py` (orchestrator test)

- [ ] **Step 1: Add failing orchestrator test**

Append to `tests/test_scanner.py`:

```python
def test_scan_all_walks_cache_dir(tmp_path, monkeypatch):
    """scan_all() walks every *.json in CACHE_DIR and aggregates Candidates."""
    from analysis.puzzles import scanner
    monkeypatch.setattr(scanner, "CACHE_DIR", tmp_path)
    # Drop one stabilize-shaped match + one quiet match
    (tmp_path / "stab.json").write_text(json.dumps(_fake_transcript([
        {"game_num": 1, "turns": [
            _turn(6, ["You life: 4"]),
            _turn(7, ["You life: 6"]),
            _turn(8, ["Opp life: 0"]),
        ]},
    ])))
    (tmp_path / "quiet.json").write_text(json.dumps(_fake_transcript([
        {"game_num": 1, "turns": [_turn(1, ["You play Island"])]},
    ])))
    out = scanner.scan_all()
    # At least the stabilize one
    cats = [c.category for c in out]
    assert "stabilize" in cats


def test_scan_all_returns_empty_for_missing_cache_dir(tmp_path, monkeypatch):
    from analysis.puzzles import scanner
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(scanner, "CACHE_DIR", missing)
    assert scanner.scan_all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py::test_scan_all_walks_cache_dir tests/test_scanner.py::test_scan_all_returns_empty_for_missing_cache_dir -v
```

Expected: FAIL (`scan_all` not defined).

- [ ] **Step 3: Add `scan_all` orchestrator to `analysis/puzzles/scanner.py`**

Append:

```python
def scan_all() -> list[Candidate]:
    """Walk every transcript in CACHE_DIR and aggregate Candidates."""
    if not CACHE_DIR.exists():
        return []
    out: list[Candidate] = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = path.stem  # filename minus .json
        out.extend(scan_match(match_id, data))
    return out
```

- [ ] **Step 4: Create the CLI**

Create `scripts/scan_for_puzzles.py`:

```python
"""CLI: run the scanner over data/match_replays/*.json and save
candidates to puzzle_inbox.

Usage:
    python scripts/scan_for_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.puzzles import scanner
from db import puzzles as db_puzzles


def main() -> None:
    print("[scan] walking data/match_replays/ ...")
    candidates = scanner.scan_all()
    if not candidates:
        print("[scan] no candidates found")
        return
    by_cat: dict[str, int] = {}
    for c in candidates:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    print(f"[scan] {len(candidates)} candidates found:")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<14} {n}")

    inserted = db_puzzles.save_inbox_candidates(
        [c.to_dict() for c in candidates]
    )
    print(f"[scan] inserted {inserted} new rows into puzzle_inbox "
          f"(rest were dedup'd)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests + verify**

```bash
python -m pytest tests/test_scanner.py -v
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: scanner tests all green; full suite 168 + 4 new scanner = 172 + 1 base = should be 173. (Adjust based on actual count; just confirm no regressions.)

- [ ] **Step 6: Commit**

```bash
git add analysis/puzzles/scanner.py scripts/scan_for_puzzles.py tests/test_scanner.py
git commit -m "feat(puzzles): scanner — scan_all orchestrator + scan_for_puzzles CLI"
```

---

## Task 7: PuzzleAuthorDialog widget

**Files:**
- Create: `gui/widgets/puzzle_author_dialog.py`
- Create: `tests/test_puzzle_author_dialog.py`

- [ ] **Step 1: Write failing dialog smoke tests**

Create `tests/test_puzzle_author_dialog.py`:

```python
"""Smoke tests for gui/widgets/puzzle_author_dialog.py."""
import os
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "p.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    yield db_path


def _sample_scene_dict() -> dict:
    return {
        "arena_match_id": "test-m", "game_num": 1, "turn_num": 7,
        "play_or_draw": "draw",
        "you": {"name": "You", "life": 4},
        "opp": {"name": "Opp", "life": 12},
    }


def test_dialog_constructs_with_scene(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene)
    # Form fields exist
    assert dlg._question_edit is not None
    assert dlg._solution_edit is not None
    assert dlg._category_combo is not None


def test_dialog_save_writes_puzzle_to_db(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    from db import puzzles
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene)
    dlg._question_edit.setText("Test Q")
    dlg._solution_edit.setPlainText("Test solution")
    dlg._category_combo.setCurrentIndex(0)  # first category
    pid = dlg._save_and_return_id()
    assert pid is not None
    assert pid >= 1
    p = puzzles.get_puzzle(pid)
    assert p["question"] == "Test Q"
    assert p["solution_text"] == "Test solution"


def test_dialog_inbox_promotion_links_id(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    from db import puzzles
    # Seed an inbox candidate
    puzzles.save_inbox_candidates([{
        "arena_match_id": "m-1", "game_num": 1, "turn_num": 7,
        "category": "stabilize", "heuristic_score": 0.5,
        "evidence": "test",
    }])
    inbox_id = puzzles.get_inbox()[0]["id"]
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene, inbox_id=inbox_id)
    dlg._question_edit.setText("Q")
    dlg._solution_edit.setPlainText("S")
    pid = dlg._save_and_return_id()
    # After save with inbox_id, the inbox row should be promoted
    assert pid is not None
    assert len(puzzles.get_inbox()) == 0  # promoted out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_puzzle_author_dialog.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `gui/widgets/puzzle_author_dialog.py`**

```python
"""PuzzleAuthorDialog — form + scene preview for creating a new puzzle.

Reused by:
  - PUZZLES tab Inbox sub-mode: "promote candidate" flow (pass inbox_id)
  - Match History sub-tab right-click: "Create puzzle from this turn"
    (no inbox_id; pure manual authoring)

On save: writes via db.puzzles.save_puzzle, and if inbox_id was provided,
calls db.puzzles.promote_inbox to link the candidate row.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QTextEdit,
    QComboBox, QSpinBox, QPushButton, QLabel, QSplitter, QFrame,
)

from analysis.puzzles.scene_builder import Scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("🎯 Find lethal", "find_lethal"),
    ("🛡 Stabilize", "stabilize"),
    ("⚡ Tempo / Race", "tempo"),
]
_GRADING_OPTIONS = [
    ("Self-grade (reveal + Got it / Missed it)", "self"),
    ("Tagged keywords", "keyword"),
    ("LLM-graded (Claude API)", "llm"),
]


class PuzzleAuthorDialog(QDialog):
    """Author / edit one puzzle. Scene is locked at dialog-open time."""

    def __init__(
        self,
        scene: Scene,
        *,
        inbox_id: Optional[int] = None,
        suggested_category: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._scene = scene
        self._inbox_id = inbox_id
        self.setWindowTitle("New puzzle" if inbox_id is None
                            else f"Promote candidate (inbox #{inbox_id})")
        self.setMinimumSize(960, 640)
        self._build_ui()
        if suggested_category:
            self._set_category(suggested_category)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: scene preview (read-only PuzzleSceneWidget)
        self._scene_widget = PuzzleSceneWidget(self._scene)
        splitter.addWidget(self._scene_widget)

        # Right: form
        right = QFrame()
        form_layout = QVBoxLayout(right)
        form = QFormLayout()
        self._category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._category_combo.addItem(label, value)
        form.addRow("Category:", self._category_combo)

        self._difficulty_spin = QSpinBox()
        self._difficulty_spin.setRange(1, 5)
        self._difficulty_spin.setValue(3)
        form.addRow("Difficulty (1-5):", self._difficulty_spin)

        self._question_edit = QLineEdit()
        self._question_edit.setPlaceholderText("e.g. Find lethal — opp at 8")
        form.addRow("Question:", self._question_edit)

        self._solution_edit = QTextEdit()
        self._solution_edit.setPlaceholderText("Step-by-step...")
        self._solution_edit.setMinimumHeight(120)
        form.addRow("Solution:", self._solution_edit)

        self._keywords_edit = QLineEdit()
        self._keywords_edit.setPlaceholderText("comma,separated,tags")
        form.addRow("Keywords (optional):", self._keywords_edit)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText(
            "Hints, alternate lines, primer references..."
        )
        self._notes_edit.setMinimumHeight(60)
        form.addRow("Notes:", self._notes_edit)

        self._grading_combo = QComboBox()
        for label, value in _GRADING_OPTIONS:
            self._grading_combo.addItem(label, value)
        form.addRow("Grading mode:", self._grading_combo)

        form_layout.addLayout(form)
        form_layout.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save puzzle")
        save.clicked.connect(self._on_save)
        save.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; "
            f"color: {theme.BTN_FG}; font-weight: bold; padding: 6px 14px; "
            "border-radius: 4px; }}"
        )
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        form_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([640, 320])
        outer.addWidget(splitter, 1)

    def _set_category(self, value: str) -> None:
        for i in range(self._category_combo.count()):
            if self._category_combo.itemData(i) == value:
                self._category_combo.setCurrentIndex(i)
                break

    def _save_and_return_id(self) -> Optional[int]:
        """Persist the puzzle. Returns the new puzzle id, or None on cancel
        (currently never cancels mid-save, but kept for symmetry)."""
        keywords = [
            k.strip() for k in (self._keywords_edit.text() or "").split(",")
            if k.strip()
        ]
        pid = db_puzzles.save_puzzle(
            deck_id=None,
            arena_match_id=self._scene.arena_match_id or None,
            game_num=self._scene.game_num or None,
            turn_num=self._scene.turn_num or None,
            category=self._category_combo.currentData() or "stabilize",
            difficulty=self._difficulty_spin.value(),
            question=self._question_edit.text() or "(no question)",
            solution_text=self._solution_edit.toPlainText() or "(no solution)",
            solution_keywords=keywords,
            grading_mode=self._grading_combo.currentData() or "self",
            author="user",
            notes=self._notes_edit.toPlainText() or "",
            scene=self._scene.to_dict(),
        )
        if self._inbox_id is not None:
            db_puzzles.promote_inbox(self._inbox_id, puzzle_id=pid)
        return pid

    def _on_save(self) -> None:
        self._save_and_return_id()
        self.accept()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_puzzle_author_dialog.py -v
```

Expected: PASS (3 passed).

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: no regressions; should be ~176 passing.

- [ ] **Step 6: Commit**

```bash
git add gui/widgets/puzzle_author_dialog.py tests/test_puzzle_author_dialog.py
git commit -m "feat(puzzles): PuzzleAuthorDialog — form + scene preview + save"
```

---

## Task 8: PUZZLES tab Inbox sub-mode

**Files:**
- Modify: `gui/tabs/puzzles.py` (restructure to sub-tabs)
- Modify: `tests/test_puzzles_tab.py` (add Inbox test)

- [ ] **Step 1: Add failing Inbox test**

Append to `tests/test_puzzles_tab.py`:

```python
def test_puzzles_tab_inbox_mode_lists_candidates(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from db import puzzles
    puzzles.save_inbox_candidates([
        {"arena_match_id": "m-a", "game_num": 1, "turn_num": 5,
         "category": "stabilize", "heuristic_score": 0.7,
         "evidence": "life 4"},
        {"arena_match_id": "m-b", "game_num": 1, "turn_num": 7,
         "category": "find_lethal", "heuristic_score": 0.9,
         "evidence": "3 spells"},
    ])
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    # Inbox table should have 2 rows after refresh
    assert tab._inbox_table.rowCount() == 2
```

- [ ] **Step 2: Run test, verify it fails**

```bash
python -m pytest tests/test_puzzles_tab.py::test_puzzles_tab_inbox_mode_lists_candidates -v
```

Expected: FAIL with `AttributeError: ..._inbox_table`.

- [ ] **Step 3: Restructure `gui/tabs/puzzles.py` to sub-tabs**

This is a significant rewrite. Replace `gui/tabs/puzzles.py` with:

```python
"""PUZZLES tab — Solve | Inbox | Author sub-modes (Phase 2)."""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QSplitter, QFrame, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
)

from analysis.puzzles.scene_builder import Scene, PlayerState, build_scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget
from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("All", ""),
    ("🎯 Find lethal", "find_lethal"),
    ("🛡 Stabilize", "stabilize"),
    ("⚡ Tempo / Race", "tempo"),
]


class PuzzlesTab(QWidget):
    """Solo solve loop + Inbox candidate review. Author opens as a dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_puzzle: Optional[dict] = None
        self._reveal_t0_ms: Optional[int] = None
        self._build_ui()
        self._load_next_puzzle()
        self._refresh_inbox()

    # ── Construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self._sub_tabs = QTabWidget()
        self._sub_tabs.addTab(self._build_solve_panel(), "Solve")
        self._sub_tabs.addTab(self._build_inbox_panel(), "Inbox")
        outer.addWidget(self._sub_tabs, 1)

    def _build_solve_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        top = QHBoxLayout()
        self._category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._category_combo.addItem(label, value)
        self._category_combo.currentIndexChanged.connect(self._on_category_changed)
        top.addWidget(QLabel("Category:"))
        top.addWidget(self._category_combo)
        top.addStretch(1)
        self._stats_lbl = QLabel("")
        top.addWidget(self._stats_lbl)
        v.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._scene_widget = PuzzleSceneWidget()
        splitter.addWidget(self._scene_widget)

        right = QFrame()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(8, 8, 8, 8)
        right_v.setSpacing(6)
        self._question_lbl = QLabel("")
        self._question_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._question_lbl.setWordWrap(True)
        right_v.addWidget(self._question_lbl)

        self._answer_edit = QTextEdit()
        self._answer_edit.setPlaceholderText("Step-by-step play...")
        right_v.addWidget(self._answer_edit, 1)

        btn_row = QHBoxLayout()
        self._reveal_btn = QPushButton("Reveal solution")
        self._reveal_btn.clicked.connect(self._on_reveal)
        btn_row.addWidget(self._reveal_btn)
        right_v.addLayout(btn_row)

        self._solution_lbl = QLabel("")
        self._solution_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._solution_lbl.setWordWrap(True)
        self._solution_lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; padding: 6px; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        self._solution_lbl.hide()
        right_v.addWidget(self._solution_lbl)

        verdict_row = QHBoxLayout()
        self._got_it_btn = QPushButton("✓ I had it")
        self._got_it_btn.clicked.connect(lambda: self._record_and_next("correct"))
        self._missed_btn = QPushButton("✗ Missed it")
        self._missed_btn.clicked.connect(lambda: self._record_and_next("incorrect"))
        for b in (self._got_it_btn, self._missed_btn):
            b.hide()
            verdict_row.addWidget(b)
        right_v.addLayout(verdict_row)

        splitter.addWidget(right)
        splitter.setSizes([720, 320])
        v.addWidget(splitter, 1)
        return panel

    def _build_inbox_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        # Toolbar: refresh + category filter
        top = QHBoxLayout()
        self._inbox_category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._inbox_category_combo.addItem(label, value)
        self._inbox_category_combo.currentIndexChanged.connect(self._refresh_inbox)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self._inbox_category_combo)
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._refresh_inbox)
        top.addWidget(refresh_btn)
        top.addStretch(1)
        v.addLayout(top)

        # Table: id / category / score / match / game / turn / evidence
        self._inbox_table = QTableWidget(0, 7)
        self._inbox_table.setHorizontalHeaderLabels(
            ["id", "category", "score", "match", "game", "turn", "evidence"]
        )
        self._inbox_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self._inbox_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._inbox_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        v.addWidget(self._inbox_table, 1)

        # Action buttons
        btns = QHBoxLayout()
        promote_btn = QPushButton("📥 Promote → Author")
        promote_btn.clicked.connect(self._on_promote_selected)
        dismiss_btn = QPushButton("✗ Dismiss")
        dismiss_btn.clicked.connect(self._on_dismiss_selected)
        btns.addWidget(promote_btn)
        btns.addWidget(dismiss_btn)
        btns.addStretch(1)
        v.addLayout(btns)
        return panel

    # ── Solve mode data flow ───────────────────────────────────
    def _on_category_changed(self, _idx: int) -> None:
        self._load_next_puzzle()

    def _load_next_puzzle(self) -> None:
        cat = self._category_combo.currentData() or None
        candidates = db_puzzles.get_puzzles(category=cat, unsolved_only=True)
        self._refresh_stats()
        if not candidates:
            self._current_puzzle = None
            self._question_lbl.setText(
                f"<i style='color:{theme.TEXT_DIM};'>Queue is empty. "
                "Promote a candidate from the Inbox tab or run "
                "scripts/scan_for_puzzles.py to populate it.</i>"
            )
            self._answer_edit.clear(); self._answer_edit.setEnabled(False)
            self._reveal_btn.setEnabled(False)
            self._solution_lbl.hide()
            self._got_it_btn.hide(); self._missed_btn.hide()
            self._scene_widget.set_scene(_empty_scene())
            return
        puzzle = candidates[-1]
        self._current_puzzle = puzzle
        self._render_puzzle(puzzle)

    def _render_puzzle(self, puzzle: dict) -> None:
        self._reveal_t0_ms = int(time.monotonic() * 1000)
        self._answer_edit.clear(); self._answer_edit.setEnabled(True)
        self._reveal_btn.setEnabled(True)
        self._solution_lbl.hide()
        self._got_it_btn.hide(); self._missed_btn.hide()
        cat_label = {
            "find_lethal": "🎯 Find lethal",
            "stabilize": "🛡 Stabilize",
            "tempo": "⚡ Tempo / Race",
        }.get(puzzle["category"], puzzle["category"])
        stars = "★" * puzzle["difficulty"] + "☆" * (5 - puzzle["difficulty"])
        self._question_lbl.setText(
            f"<div style='color:{theme.ACCENT};font-size:11px;'>{cat_label} · {stars}</div>"
            f"<div style='font-size:14px;font-weight:bold;margin-top:4px;'>"
            f"{puzzle['question']}</div>"
            f"<div style='color:{theme.TEXT_DIM};font-size:11px;margin-top:6px;'>"
            f"{puzzle.get('notes', '') or ''}</div>"
        )
        scene = Scene.from_dict(puzzle["scene"])
        self._scene_widget.set_scene(scene)

    def _on_reveal(self) -> None:
        if self._current_puzzle is None:
            return
        self._solution_lbl.setText(
            f"<b>Author's solution:</b><br/>"
            + (self._current_puzzle["solution_text"]
               .replace("\n", "<br/>"))
        )
        self._solution_lbl.show()
        self._got_it_btn.show(); self._missed_btn.show()
        self._reveal_btn.setEnabled(False)

    def _record_and_next(self, verdict: str) -> None:
        if self._current_puzzle is None:
            return
        ms = None
        if self._reveal_t0_ms is not None:
            ms = int(time.monotonic() * 1000) - self._reveal_t0_ms
        db_puzzles.record_attempt(
            puzzle_id=self._current_puzzle["id"],
            user_answer=self._answer_edit.toPlainText(),
            verdict=verdict,
            grader_used="self",
            time_spent_ms=ms,
        )
        self._load_next_puzzle()

    def _refresh_stats(self) -> None:
        stats = db_puzzles.get_session_stats()
        wr_pct = stats["wr_overall"] * 100
        self._stats_lbl.setText(
            f"<span style='color:{theme.TEXT_DIM};'>Session:</span> "
            f"<b style='color:#80c890;'>{stats['n_solved']} ✓</b> · "
            f"<b style='color:#d88060;'>{stats['n_missed']} ✗</b> · "
            f"{wr_pct:.0f}%"
        )

    # ── Inbox mode ─────────────────────────────────────────────
    def _refresh_inbox(self) -> None:
        cat = self._inbox_category_combo.currentData() or None
        rows = db_puzzles.get_inbox(category=cat, top_n=200)
        self._inbox_table.setUpdatesEnabled(False)
        self._inbox_table.setSortingEnabled(False)
        self._inbox_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._inbox_table.setItem(r, 0, QTableWidgetItem(str(row["id"])))
            self._inbox_table.setItem(r, 1, QTableWidgetItem(row["category"]))
            self._inbox_table.setItem(r, 2, QTableWidgetItem(
                f"{row['heuristic_score']:.2f}"))
            self._inbox_table.setItem(r, 3, QTableWidgetItem(row["arena_match_id"]))
            self._inbox_table.setItem(r, 4, QTableWidgetItem(
                str(row["game_num"] or "")))
            self._inbox_table.setItem(r, 5, QTableWidgetItem(str(row["turn_num"])))
            self._inbox_table.setItem(r, 6, QTableWidgetItem(row.get("evidence") or ""))
        self._inbox_table.setSortingEnabled(True)
        self._inbox_table.setUpdatesEnabled(True)

    def _selected_inbox_row(self) -> Optional[dict]:
        sel = self._inbox_table.currentRow()
        if sel < 0:
            return None
        rows = db_puzzles.get_inbox(top_n=200)
        if sel >= len(rows):
            return None
        return rows[sel]

    def _on_promote_selected(self) -> None:
        row = self._selected_inbox_row()
        if row is None:
            QMessageBox.information(self, "No selection", "Pick a candidate row first.")
            return
        scene = build_scene(
            arena_match_id=row["arena_match_id"],
            game_num=int(row["game_num"] or 1),
            turn_num=int(row["turn_num"]),
        )
        if scene is None:
            QMessageBox.warning(
                self, "Scene unavailable",
                f"No cached replay for {row['arena_match_id']}. "
                "Run replay_fetcher or play the match again.",
            )
            return
        dlg = PuzzleAuthorDialog(
            scene=scene, inbox_id=row["id"],
            suggested_category=row["category"], parent=self,
        )
        if dlg.exec():
            self._refresh_inbox()
            self._load_next_puzzle()

    def _on_dismiss_selected(self) -> None:
        row = self._selected_inbox_row()
        if row is None:
            return
        db_puzzles.dismiss_inbox(row["id"])
        self._refresh_inbox()

    # Test helper
    def findChild_text_recursive(self) -> str:
        out = []
        for lbl in self.findChildren(QLabel):
            out.append(lbl.text())
        for te in self.findChildren(QTextEdit):
            out.append(te.placeholderText() or "")
            out.append(te.toPlainText() or "")
        return " ".join(out)

    def cleanup(self) -> None:
        pass


def _empty_scene() -> Scene:
    return Scene(
        arena_match_id="", game_num=0, turn_num=0, play_or_draw="play",
        you=PlayerState(name="You"), opp=PlayerState(name="Opp"),
        notes="",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_puzzles_tab.py -v
```

Expected: PASS (3 — 2 original + 1 new Inbox test).

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: ~177 passing.

- [ ] **Step 6: Commit**

```bash
git add gui/tabs/puzzles.py tests/test_puzzles_tab.py
git commit -m "feat(puzzles): PUZZLES tab — Solve | Inbox sub-tabs + promote dialog wiring"
```

---

## Task 9: Match History right-click integration

**Files:**
- Modify: `gui/widgets/deck_match_history.py`

- [ ] **Step 1: Find the recent-matches table + existing context menu (if any)**

```bash
grep -n "contextMenu\|setContextMenuPolicy\|_rm_tbl" gui/widgets/deck_match_history.py | head -10
```

You'll find `self._rm_tbl` is the recent-matches QTableWidget. Locate either an existing context-menu handler OR a place to add one.

- [ ] **Step 2: Add context menu setup near `_rm_tbl` creation**

Find where `self._rm_tbl = QTableWidget(...)` is constructed in `_build_ui` (or similar). Add right after that line:

```python
self._rm_tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
self._rm_tbl.customContextMenuRequested.connect(self._on_recent_match_context_menu)
```

- [ ] **Step 3: Add the handler method**

Add this method to the same class (DeckMatchHistory or whatever the class is named):

```python
def _on_recent_match_context_menu(self, position) -> None:
    """Right-click on a recent-matches row → context menu with the
    'Create puzzle from this turn' action."""
    from PyQt6.QtWidgets import QMenu, QMessageBox, QInputDialog
    row = self._rm_tbl.rowAt(position.y())
    if row < 0:
        return
    # The date cell carries the match_log id via UserRole (set in _render_recent)
    date_item = self._rm_tbl.item(row, 0)
    if date_item is None:
        return
    match_log_id = date_item.data(Qt.ItemDataRole.UserRole)
    if match_log_id is None:
        return

    # Look up arena_match_id from the match row
    from db.database import get_connection
    with get_connection() as c:
        r = c.execute(
            "SELECT arena_match_id FROM match_log WHERE id = ?",
            (int(match_log_id),),
        ).fetchone()
    arena_match_id = (r and r["arena_match_id"]) or ""

    menu = QMenu(self)
    create_act = menu.addAction("📥 Create puzzle from this turn")
    chosen = menu.exec(self._rm_tbl.viewport().mapToGlobal(position))
    if chosen is not create_act:
        return

    if not arena_match_id:
        QMessageBox.warning(
            self, "No replay",
            "This match has no arena_match_id — can't reconstruct the scene.",
        )
        return

    # Ask the user which turn (default 1; they pick from a number prompt)
    turn_num, ok = QInputDialog.getInt(
        self, "Pick turn", "Which turn to capture?",
        value=5, min=1, max=30,
    )
    if not ok:
        return

    from analysis.puzzles.scene_builder import build_scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    scene = build_scene(
        arena_match_id=arena_match_id, game_num=1, turn_num=turn_num,
    )
    if scene is None:
        QMessageBox.warning(
            self, "Scene unavailable",
            f"No cached replay JSON for {arena_match_id}. "
            "Open Watch Replay first to build the cache, then retry.",
        )
        return
    dlg = PuzzleAuthorDialog(scene=scene, parent=self)
    dlg.exec()
```

- [ ] **Step 4: Smoke test the integration (headless construct)**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from gui.widgets.deck_match_history import DeckMatchHistory
w = DeckMatchHistory()
# Confirm no exception during construction with the new context menu wiring
print('OK', w)
"
```

Expected: prints `OK <DeckMatchHistory ...>` with no exception.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add gui/widgets/deck_match_history.py
git commit -m "feat(puzzles): right-click 'Create puzzle from this turn' in Match History"
```

---

## Task 10: Manual smoke + doc updates + push

**Files:**
- Modify: `CLAUDE.md`
- Modify: `NEXT_STEPS.md`
- (Optional) Modify: `ROADMAP.md`

- [ ] **Step 1: Run the scanner against the real replay corpus**

```bash
python scripts/scan_for_puzzles.py
```

Expected: prints candidate counts per category and rows inserted. If the corpus has > 0 replays, expect > 0 candidates.

- [ ] **Step 2: Launch GUI + smoke the Inbox + promote flow**

```bash
python run_gui.py
```

Manual checklist:
- Open PUZZLES tab → see Solve / Inbox sub-tabs
- Click Inbox → table shows scanner candidates
- Select a row, click "📥 Promote → Author" → dialog opens with scene preview pre-loaded
- Fill question + solution, click Save
- Click Inbox tab again → that row is gone (promoted)
- Click Solve tab → the new puzzle is in the queue
- Solve it, verify the attempt is recorded

Open Match History sub-tab (My Decks → Tokyo Prowess → Match History) → right-click a recent match → "📥 Create puzzle from this turn" → enter a turn number → dialog opens with that scene → save.

- [ ] **Step 3: Update CLAUDE.md**

Find the existing Puzzles paragraph (added in Phase 1 doc update). Replace it with:

```markdown
- **Puzzles tab (Phase 2)**: MTGA-style "find-the-line" practice with
  Solve | Inbox sub-modes. Solve = render saved scenes + self-grade.
  Inbox = scanner-extracted candidates from `data/match_replays/`
  ranked by per-category heuristics; promote opens the Author dialog
  with scene preview pre-loaded. Author dialog also reachable from
  Match History right-click → "Create puzzle from this turn." Scanner
  CLI: `python scripts/scan_for_puzzles.py`. Spec at
  `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`.
  Phase 3 (keyword + LLM graders) scheduled for 5/22.
```

- [ ] **Step 4: Add Phase 2 entry to NEXT_STEPS.md**

Above the existing "Puzzle tool — Phase 1 shipped" entry, add:

```markdown
### Puzzle tool — Phase 2 shipped (2026-05-1X)
- `analysis/puzzles/scanner.py` — Candidate dataclass + 3 heuristic functions (find_lethal / stabilize / tempo simplified) + scan_all orchestrator
- `scripts/scan_for_puzzles.py` — CLI: walks data/match_replays, saves to puzzle_inbox
- `gui/widgets/puzzle_author_dialog.py` — form + scene preview + save (reused from Inbox promote and Match History right-click)
- `gui/tabs/puzzles.py` restructured to Solve | Inbox sub-tabs
- `gui/widgets/deck_match_history.py` — right-click "Create puzzle from this turn" on recent matches
- `db/puzzles.py` — inbox CRUD: save_inbox_candidates, get_inbox, dismiss_inbox, promote_inbox
- Phase 3 (keyword + LLM graders) scheduled by 5/22.
```

- [ ] **Step 5: Commit + push**

```bash
git add CLAUDE.md NEXT_STEPS.md
git commit -m "docs(puzzles): Phase 2 shipped notes in CLAUDE.md + NEXT_STEPS"
git push
```

If push fails on the pre-push PII hook, scrub per `[[feedback_no-user-handles-in-docs]]` and re-commit (NEW commit, not amend).

---

## Validation gates (mechanical)

Phase 2 is "shipped" when ALL of these are true:

- [ ] `python -m pytest tests/` shows the full count green (Phase 1's 162 + Phase 2's new tests, target ~177-180)
- [ ] `python scripts/scan_for_puzzles.py` produces > 0 candidates on the user's real replay corpus (or prints "no candidates found" cleanly if corpus is empty)
- [ ] Inbox sub-tab lists candidates ranked by heuristic_score
- [ ] Promote → Author dialog → Save → puzzle appears in Solve queue
- [ ] Match History right-click → Author dialog opens with pre-loaded scene
- [ ] Dismiss removes a candidate from the Inbox view
- [ ] `git push` succeeds

---

## What this does NOT do (intentional Phase 2 limits)

- No keyword grader or LLM grader (Phase 3)
- No JSON export / shared DB (Phase 4)
- No batch-promote in Inbox (one at a time)
- No inline scene editing in Author dialog (scene is locked at dialog-open; user can edit question / solution / metadata only)
- No heuristic tuning UI — tuning happens by editing `analysis/puzzles/scanner.py` formulas + re-running `scan_for_puzzles.py`
- Tempo heuristic is the simplified "2+ instants on own turn" version, not the full "mana_efficiency_delta" formula from the spec. Tuning + replacement happen in Phase 3+.
