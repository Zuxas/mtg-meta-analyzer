# Find-the-Line Puzzle Tool — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working solo solve loop — user can solve hand-authored puzzles end-to-end in a new PUZZLES tab.

**Architecture:** SQLite-backed puzzles via `db/puzzles.py` (3 tables); per-puzzle Scene snapshot built by `analysis/puzzles/scene_builder.py` from cached replay JSON; rendered by `gui/widgets/puzzle_scene.py` in MTGA-style layout (real Scryfall images, corner avatars, centered life, fanned hand); driven by `gui/tabs/puzzles.py` Solve sub-tab; seeded by `scripts/seed_puzzles.py` CLI.

**Tech Stack:** Python 3.13, PyQt6, SQLite, Scryfall API for card images, pytest.

**Spec:** `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`

**Ship target:** end of 2026-05-18 (Monday), 13 days before RC DC.

---

## File Structure

**Create:**
- `analysis/puzzles/__init__.py` — package marker
- `analysis/puzzles/scene_builder.py` — `Scene` / `PlayerState` / `CardInZone` dataclasses + `build_scene()` function
- `db/puzzles.py` — schema + CRUD for `puzzles`, `puzzle_attempts`, `puzzle_inbox` tables (Phase 1 only wires puzzles + puzzle_attempts API)
- `gui/widgets/card_image_cache.py` — fetch + disk-cache Scryfall card images
- `gui/widgets/puzzle_scene.py` — MTGA-style scene render widget
- `gui/tabs/puzzles.py` — PUZZLES top-level tab with Solve mode only
- `scripts/seed_puzzles.py` — CLI seeder for hand-authored puzzles
- `tests/test_db_puzzles.py` — schema + CRUD round-trip
- `tests/test_scene_builder.py` — scene reconstruction from fixture replay JSON
- `tests/test_card_image_cache.py` — fetch + cache path logic
- `tests/test_puzzles_tab.py` — tab integration smoke test
- `data/card_images/.gitkeep` — directory for cached images

**Modify:**
- `gui/main_window.py` — add PUZZLES tab to top-level tab list
- `.gitignore` — add `data/card_images/*.jpg` (keep `.gitkeep`)

---

## Task 1: Package structure + DB schema

**Files:**
- Create: `analysis/puzzles/__init__.py`
- Create: `db/puzzles.py`
- Create: `tests/test_db_puzzles.py`

- [ ] **Step 1: Create the empty package marker**

```bash
mkdir -p "analysis/puzzles"
echo "" > "analysis/puzzles/__init__.py"
```

- [ ] **Step 2: Write the failing schema test**

Create `tests/test_db_puzzles.py`:

```python
"""Tests for db/puzzles.py — schema creation + CRUD round-trip."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Patch db.database to use a temp SQLite file so tests don't touch prod."""
    db_path = tmp_path / "test_mtg_meta.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_DB_PATH", tmp_path / "archive.db")
    yield db_path


def test_ensure_tables_creates_all_three(tmp_db):
    """First call to _ensure_tables() must create puzzles, puzzle_attempts, puzzle_inbox."""
    from db import puzzles
    puzzles._ensure_tables()

    with sqlite3.connect(tmp_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('puzzles', 'puzzle_attempts', 'puzzle_inbox')"
        ).fetchall()
    table_names = {r[0] for r in rows}
    assert table_names == {"puzzles", "puzzle_attempts", "puzzle_inbox"}


def test_ensure_tables_is_idempotent(tmp_db):
    """Calling _ensure_tables() twice must not raise."""
    from db import puzzles
    puzzles._ensure_tables()
    puzzles._ensure_tables()  # no-op second call
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd "E:/vscode ai project/mtg-meta-analyzer"
python -m pytest tests/test_db_puzzles.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'db.puzzles'`

- [ ] **Step 4: Implement the schema in `db/puzzles.py`**

```python
"""Puzzles + attempts + inbox persistence.

Schema lives here; CRUD helpers below. Phase 1 wires only puzzles + puzzle_attempts
API; the inbox table is created idempotently so Phase 2 doesn't need a migration.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from db.database import get_connection


_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS puzzles (
    id              INTEGER PRIMARY KEY,
    deck_id         INTEGER REFERENCES saved_decks(id) ON DELETE CASCADE,
    arena_match_id  TEXT,
    game_num        INTEGER,
    turn_num        INTEGER,
    category        TEXT NOT NULL,
    difficulty      INTEGER NOT NULL,
    question        TEXT NOT NULL,
    solution_text   TEXT NOT NULL,
    solution_keywords_json TEXT,
    grading_mode    TEXT NOT NULL,
    author          TEXT,
    notes           TEXT,
    scene_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS puzzle_attempts (
    id              INTEGER PRIMARY KEY,
    puzzle_id       INTEGER NOT NULL REFERENCES puzzles(id) ON DELETE CASCADE,
    attempted_at    TEXT NOT NULL,
    user_answer     TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    grader_used     TEXT NOT NULL,
    time_spent_ms   INTEGER
);

CREATE TABLE IF NOT EXISTS puzzle_inbox (
    id              INTEGER PRIMARY KEY,
    arena_match_id  TEXT NOT NULL,
    game_num        INTEGER,
    turn_num        INTEGER NOT NULL,
    category        TEXT NOT NULL,
    heuristic_score REAL NOT NULL,
    evidence        TEXT,
    discovered_at   TEXT NOT NULL,
    dismissed_at    TEXT,
    promoted_puzzle_id INTEGER REFERENCES puzzles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_puzzles_deck ON puzzles(deck_id);
CREATE INDEX IF NOT EXISTS idx_puzzles_category ON puzzles(category);
CREATE INDEX IF NOT EXISTS idx_attempts_puzzle ON puzzle_attempts(puzzle_id);
CREATE INDEX IF NOT EXISTS idx_inbox_undismissed ON puzzle_inbox(dismissed_at, heuristic_score DESC);
"""


def _ensure_tables() -> None:
    """Idempotent table creation. Safe to call on every module use."""
    with get_connection() as conn:
        conn.executescript(_TABLES_SQL)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_db_puzzles.py -v
```

Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add analysis/puzzles/__init__.py db/puzzles.py tests/test_db_puzzles.py
git commit -m "feat(puzzles): schema + ensure_tables for puzzles / attempts / inbox"
```

---

## Task 2: DB CRUD — puzzles

**Files:**
- Modify: `db/puzzles.py` (append CRUD)
- Modify: `tests/test_db_puzzles.py` (append round-trip tests)

- [ ] **Step 1: Add failing round-trip test**

Append to `tests/test_db_puzzles.py`:

```python
def _sample_scene_dict() -> dict:
    """Minimal scene dict for puzzle.scene_json."""
    return {
        "arena_match_id": "test-match-1",
        "game_num": 1,
        "turn_num": 7,
        "play_or_draw": "draw",
        "you": {"name": "Z", "life": 4, "hand": []},
        "opp": {"name": "M", "life": 12, "hand": []},
    }


def test_save_and_get_puzzle_round_trip(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    pid = puzzles.save_puzzle(
        deck_id=None,
        arena_match_id="test-match-1",
        game_num=1,
        turn_num=7,
        category="stabilize",
        difficulty=3,
        question="Survive opp's T8",
        solution_text="Cast Slagstorm, keep Crab to block",
        solution_keywords=["slagstorm", "block_crab"],
        grading_mode="self",
        author="seeder",
        notes="See primer notes",
        scene=_sample_scene_dict(),
    )
    assert pid >= 1
    got = puzzles.get_puzzle(pid)
    assert got["category"] == "stabilize"
    assert got["question"] == "Survive opp's T8"
    assert got["scene"]["turn_num"] == 7  # scene was JSON-deserialized
    assert got["solution_keywords"] == ["slagstorm", "block_crab"]


def test_get_puzzles_filters_by_category(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    puzzles.save_puzzle(
        deck_id=None, arena_match_id="m1", game_num=1, turn_num=5,
        category="find_lethal", difficulty=2, question="q1",
        solution_text="s1", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    puzzles.save_puzzle(
        deck_id=None, arena_match_id="m2", game_num=1, turn_num=5,
        category="stabilize", difficulty=2, question="q2",
        solution_text="s2", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    assert len(puzzles.get_puzzles(category="find_lethal")) == 1
    assert len(puzzles.get_puzzles(category="stabilize")) == 1
    assert len(puzzles.get_puzzles()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_db_puzzles.py -v
```

Expected: FAIL on `puzzles.save_puzzle` / `puzzles.get_puzzle` (not defined).

- [ ] **Step 3: Add CRUD helpers to `db/puzzles.py`**

Append to `db/puzzles.py`:

```python
def save_puzzle(
    *,
    deck_id: Optional[int],
    arena_match_id: Optional[str],
    game_num: Optional[int],
    turn_num: Optional[int],
    category: str,
    difficulty: int,
    question: str,
    solution_text: str,
    solution_keywords: list[str],
    grading_mode: str,
    author: Optional[str],
    notes: Optional[str],
    scene: dict,
) -> int:
    """Insert a new puzzle. Returns the new row id."""
    _ensure_tables()
    now = _utc_now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO puzzles ("
            "deck_id, arena_match_id, game_num, turn_num, category, difficulty, "
            "question, solution_text, solution_keywords_json, grading_mode, "
            "author, notes, scene_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                deck_id, arena_match_id, game_num, turn_num, category, difficulty,
                question, solution_text, json.dumps(solution_keywords or []),
                grading_mode, author, notes,
                json.dumps(scene), now, now,
            ),
        )
        return int(cur.lastrowid)


def _row_to_puzzle(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["solution_keywords"] = json.loads(d.pop("solution_keywords_json") or "[]")
    d["scene"] = json.loads(d.pop("scene_json") or "{}")
    return d


def get_puzzle(puzzle_id: int) -> Optional[dict[str, Any]]:
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)
        ).fetchone()
    return _row_to_puzzle(row) if row else None


def get_puzzles(
    *,
    category: Optional[str] = None,
    deck_id: Optional[int] = None,
    unsolved_only: bool = False,
) -> list[dict[str, Any]]:
    """Return puzzles, optionally filtered. Newest first."""
    _ensure_tables()
    clauses, params = [], []
    if category:
        clauses.append("category = ?"); params.append(category)
    if deck_id is not None:
        clauses.append("deck_id = ?"); params.append(deck_id)
    sql = "SELECT * FROM puzzles"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    puzzles_list = [_row_to_puzzle(r) for r in rows]
    if unsolved_only:
        with get_connection() as conn:
            solved_ids = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT puzzle_id FROM puzzle_attempts "
                    "WHERE verdict = 'correct'"
                ).fetchall()
            }
        puzzles_list = [p for p in puzzles_list if p["id"] not in solved_ids]
    return puzzles_list


def delete_puzzle(puzzle_id: int) -> None:
    _ensure_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM puzzles WHERE id = ?", (puzzle_id,))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_db_puzzles.py -v
```

Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add db/puzzles.py tests/test_db_puzzles.py
git commit -m "feat(puzzles): save_puzzle / get_puzzle / get_puzzles / delete_puzzle"
```

---

## Task 3: DB CRUD — puzzle_attempts + session stats

**Files:**
- Modify: `db/puzzles.py`
- Modify: `tests/test_db_puzzles.py`

- [ ] **Step 1: Add failing attempt-tracking tests**

Append to `tests/test_db_puzzles.py`:

```python
def test_record_attempt_and_get_attempts(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    pid = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m1", game_num=1, turn_num=5,
        category="stabilize", difficulty=3, question="q",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    aid = puzzles.record_attempt(
        puzzle_id=pid, user_answer="block with Crab",
        verdict="correct", grader_used="self", time_spent_ms=42000,
    )
    assert aid >= 1
    attempts = puzzles.get_attempts(pid)
    assert len(attempts) == 1
    assert attempts[0]["verdict"] == "correct"


def test_session_stats_wr_by_category(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    pid_a = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m1", game_num=1, turn_num=1,
        category="find_lethal", difficulty=2, question="q1",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    pid_b = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m2", game_num=1, turn_num=1,
        category="stabilize", difficulty=2, question="q2",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    puzzles.record_attempt(puzzle_id=pid_a, user_answer="x", verdict="correct", grader_used="self", time_spent_ms=1000)
    puzzles.record_attempt(puzzle_id=pid_a, user_answer="y", verdict="incorrect", grader_used="self", time_spent_ms=2000)
    puzzles.record_attempt(puzzle_id=pid_b, user_answer="z", verdict="correct", grader_used="self", time_spent_ms=3000)

    stats = puzzles.get_session_stats()
    assert stats["n_solved"] == 2
    assert stats["n_missed"] == 1
    assert stats["wr_overall"] == pytest.approx(2 / 3)
    assert stats["wr_by_category"]["find_lethal"] == pytest.approx(0.5)
    assert stats["wr_by_category"]["stabilize"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_db_puzzles.py::test_record_attempt_and_get_attempts tests/test_db_puzzles.py::test_session_stats_wr_by_category -v
```

Expected: FAIL on missing functions.

- [ ] **Step 3: Add attempt + stats helpers to `db/puzzles.py`**

Append:

```python
def record_attempt(
    *,
    puzzle_id: int,
    user_answer: str,
    verdict: str,
    grader_used: str,
    time_spent_ms: Optional[int] = None,
) -> int:
    _ensure_tables()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO puzzle_attempts ("
            "puzzle_id, attempted_at, user_answer, verdict, grader_used, time_spent_ms"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (puzzle_id, _utc_now_iso(), user_answer, verdict, grader_used, time_spent_ms),
        )
        return int(cur.lastrowid)


def get_attempts(puzzle_id: int) -> list[dict[str, Any]]:
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM puzzle_attempts WHERE puzzle_id = ? ORDER BY id DESC",
            (puzzle_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_stats(*, since: Optional[str] = None) -> dict[str, Any]:
    """Aggregate solve stats. `since` is ISO timestamp; None = all-time."""
    _ensure_tables()
    where = ""; params = []
    if since:
        where = "WHERE a.attempted_at >= ?"; params.append(since)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT p.category, a.verdict "
            f"FROM puzzle_attempts a JOIN puzzles p ON p.id = a.puzzle_id "
            f"{where}",
            params,
        ).fetchall()
    n_solved = sum(1 for r in rows if r[1] == "correct")
    n_missed = sum(1 for r in rows if r[1] == "incorrect")
    total = n_solved + n_missed
    by_cat: dict[str, dict[str, int]] = {}
    for cat, verdict in rows:
        b = by_cat.setdefault(cat, {"solved": 0, "missed": 0})
        if verdict == "correct":
            b["solved"] += 1
        elif verdict == "incorrect":
            b["missed"] += 1
    wr_by_category = {
        cat: (b["solved"] / (b["solved"] + b["missed"]))
        for cat, b in by_cat.items() if (b["solved"] + b["missed"]) > 0
    }
    return {
        "n_solved": n_solved,
        "n_missed": n_missed,
        "wr_overall": (n_solved / total) if total else 0.0,
        "wr_by_category": wr_by_category,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_db_puzzles.py -v
```

Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add db/puzzles.py tests/test_db_puzzles.py
git commit -m "feat(puzzles): record_attempt + get_attempts + get_session_stats"
```

---

## Task 4: Scene dataclasses + builder

**Files:**
- Create: `analysis/puzzles/scene_builder.py`
- Create: `tests/test_scene_builder.py`

- [ ] **Step 1: Write failing tests for Scene dataclasses + builder**

Create `tests/test_scene_builder.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scene_builder.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `analysis/puzzles/scene_builder.py`**

```python
"""Scene reconstruction for puzzle scenarios.

Given an (arena_match_id, game_num, turn_num), rebuilds the full board state
from the cached replay transcript. Returns a Scene dataclass that the puzzle
widget can render and that gets serialized into puzzles.scene_json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional

# Same cache dir the Watch Replay viewer writes to
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "match_replays"


@dataclass
class CardInZone:
    name: str
    grpid: Optional[int] = None
    scryfall_image_url: Optional[str] = None
    tapped: bool = False
    power: Optional[int] = None
    toughness: Optional[int] = None
    counters: dict[str, int] = field(default_factory=dict)
    is_face_down: bool = False


@dataclass
class PlayerState:
    name: str
    archetype: str = "?"
    life: int = 20
    hand: list[CardInZone] = field(default_factory=list)
    battlefield_lands: list[CardInZone] = field(default_factory=list)
    battlefield_creatures: list[CardInZone] = field(default_factory=list)
    battlefield_other: list[CardInZone] = field(default_factory=list)
    graveyard_count: int = 0
    library_count: int = 60
    mana_available: dict[str, int] = field(default_factory=dict)


@dataclass
class Scene:
    arena_match_id: str
    game_num: int
    turn_num: int
    play_or_draw: Literal["play", "draw"]
    you: PlayerState
    opp: PlayerState
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        you = _player_from_dict(d["you"])
        opp = _player_from_dict(d["opp"])
        return cls(
            arena_match_id=d["arena_match_id"],
            game_num=d["game_num"],
            turn_num=d["turn_num"],
            play_or_draw=d["play_or_draw"],
            you=you, opp=opp,
            notes=d.get("notes", ""),
        )


def _player_from_dict(d: dict) -> PlayerState:
    def _cards(key):
        return [CardInZone(**c) for c in d.get(key, [])]
    return PlayerState(
        name=d["name"],
        archetype=d.get("archetype", "?"),
        life=d.get("life", 20),
        hand=_cards("hand"),
        battlefield_lands=_cards("battlefield_lands"),
        battlefield_creatures=_cards("battlefield_creatures"),
        battlefield_other=_cards("battlefield_other"),
        graveyard_count=d.get("graveyard_count", 0),
        library_count=d.get("library_count", 60),
        mana_available=d.get("mana_available", {}),
    )


_LIFE_RE = re.compile(r"(opp|you)\s+life[:\s]+(-?\d+)", re.IGNORECASE)


def build_scene(
    arena_match_id: str, game_num: int, turn_num: int
) -> Optional[Scene]:
    """Walk the cached transcript up to turn_num, return a Scene snapshot.

    Phase 1 implementation is intentionally minimal: extracts life totals
    from the transcript's text actions and a hand snapshot from any
    'Opening hand' line in the target game's earliest turn. Battlefield /
    mana / tap state are left empty for Phase 1 — the seeder script will
    let the puzzle author fill those in. Phase 2 will mine the full
    gameStateMessage.zones for an authoritative snapshot.
    """
    path = CACHE_DIR / f"{arena_match_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    games = data.get("games", [])
    game = next((g for g in games if g.get("game_num") == game_num), None)
    if game is None:
        return None

    you = PlayerState(name="You", archetype="?", life=20)
    opp = PlayerState(name="Opp", archetype="?", life=20)

    # Walk turns up to and including turn_num
    for t in game.get("turns", []):
        if t.get("turn", 0) > turn_num:
            break
        for action in t.get("actions", []) or []:
            m = _LIFE_RE.search(action)
            if m:
                who, val = m.group(1).lower(), int(m.group(2))
                if who == "you":
                    you.life = val
                else:
                    opp.life = val
            if action.lower().startswith("opening hand"):
                # "Opening hand (kept on 7): Card A, Card B, ..."
                _, _, rest = action.partition(":")
                names = [n.strip() for n in rest.split(",") if n.strip()]
                you.hand = [CardInZone(name=n) for n in names]

    return Scene(
        arena_match_id=arena_match_id,
        game_num=game_num,
        turn_num=turn_num,
        play_or_draw="draw",  # Phase 1 default; seeder script can override
        you=you,
        opp=opp,
        notes=f"Scene built from {path.name} at T{turn_num}.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scene_builder.py -v
```

Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add analysis/puzzles/scene_builder.py tests/test_scene_builder.py
git commit -m "feat(puzzles): Scene dataclasses + build_scene from cached transcript"
```

---

## Task 5: Card image cache helper

**Files:**
- Create: `gui/widgets/card_image_cache.py`
- Create: `tests/test_card_image_cache.py`
- Create: `data/card_images/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing tests**

Create `tests/test_card_image_cache.py`:

```python
"""Tests for gui/widgets/card_image_cache.py — path logic + cache hits."""
from pathlib import Path
import pytest


def test_cache_path_uses_grpid_when_available(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Eddymurk Crab", grpid=12345)
    assert p == tmp_path / "12345.jpg"


def test_cache_path_falls_back_to_slug_when_no_grpid(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Eddymurk Crab", grpid=None)
    assert p == tmp_path / "eddymurk_crab.jpg"


def test_cache_path_handles_split_names(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Roaring Furnace // Steaming Sauna", grpid=None)
    assert p == tmp_path / "roaring_furnace.jpg"  # first half only


def test_load_pixmap_returns_none_for_missing_card_when_no_network(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    # Don't allow real network. fetch_url returns None.
    monkeypatch.setattr(cic, "_fetch_url_bytes", lambda url: None)
    px = cic.load_pixmap(card_name="No-Such-Card-1234", grpid=None)
    assert px is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_card_image_cache.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `gui/widgets/card_image_cache.py`**

```python
"""Disk-cached Scryfall card image fetcher.

cache_path() returns the on-disk JPEG path for a given (name, grpid).
load_pixmap() returns a QPixmap, fetching from Scryfall on cache miss.

Phase 1 keeps this simple and blocking. Phase 2/3 may wrap in a worker.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "card_images"
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"


def _slugify(name: str) -> str:
    """Normalize a card name to a filesystem-safe slug. Split cards keep only
    the front half so 'Roaring Furnace // Steaming Sauna' -> 'roaring_furnace'."""
    front, _, _ = name.partition("//")
    s = front.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


def cache_path(*, card_name: str, grpid: Optional[int]) -> Path:
    """Where this card's JPEG would live on disk."""
    if grpid:
        return CACHE_DIR / f"{grpid}.jpg"
    return CACHE_DIR / f"{_slugify(card_name)}.jpg"


def _fetch_url_bytes(url: str) -> Optional[bytes]:
    """Return raw bytes from a URL, or None on any failure."""
    if requests is None:
        return None
    try:
        resp = requests.get(url, timeout=8, allow_redirects=True)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        return None
    return None


def fetch_to_cache(*, card_name: str, grpid: Optional[int]) -> Optional[Path]:
    """Download the small Scryfall image for card_name; write to cache.

    Returns the cache path on success, None on failure (no Scryfall match,
    network error, etc.)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(card_name=card_name, grpid=grpid)
    if path.exists() and path.stat().st_size > 0:
        return path
    front, _, _ = card_name.partition("//")
    params = urllib.parse.urlencode({
        "exact": front.strip(),
        "format": "image",
        "version": "small",
    })
    blob = _fetch_url_bytes(f"{SCRYFALL_NAMED_URL}?{params}")
    if blob is None:
        return None
    try:
        path.write_bytes(blob)
    except OSError:
        return None
    return path


def load_pixmap(*, card_name: str, grpid: Optional[int]):
    """Return a QPixmap for this card, or None if unavailable.

    Imports QPixmap lazily so this module is safe to import in headless tests.
    """
    path = fetch_to_cache(card_name=card_name, grpid=grpid)
    if path is None:
        return None
    try:
        from PyQt6.QtGui import QPixmap
    except ImportError:
        return None
    px = QPixmap(str(path))
    return px if not px.isNull() else None
```

- [ ] **Step 4: Add gitignore + dir marker**

```bash
mkdir -p "data/card_images"
echo "" > "data/card_images/.gitkeep"
```

Append to `.gitignore` (under the existing `data/*.png` section):

```
# Card image cache (fetched from Scryfall on demand)
data/card_images/*.jpg
!data/card_images/.gitkeep
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_card_image_cache.py -v
```

Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add gui/widgets/card_image_cache.py tests/test_card_image_cache.py data/card_images/.gitkeep .gitignore
git commit -m "feat(puzzles): Scryfall card image cache helper"
```

---

## Task 6: PuzzleSceneWidget — MTGA-style render

**Files:**
- Create: `gui/widgets/puzzle_scene.py`

**Note:** widget is harder to unit-test cleanly; smoke test happens in Task 8 (PuzzlesTab) and the manual smoke in Task 10. We use offscreen Qt construction here to verify it doesn't raise on a real Scene.

- [ ] **Step 1: Implement `gui/widgets/puzzle_scene.py`**

```python
"""MTGA-style render widget for a puzzle Scene.

Layout (top → bottom):
  1. Opp hand (face-down row, small)
  2. Opp avatar (top-left, absolute) + Opp life circle (top-center, absolute)
  3. Opp lands row (their back)
  4. Opp creatures row (closer to center)
  5. Stack divider
  6. Your creatures row (closer to center)
  7. Your lands row (your back)
  8. Your avatar (bottom-left, absolute) + Your life circle (bottom-center, absolute)
  9. Your hand (fanned, bottom)

Cards render via gui/widgets/card_image_cache. Cards with no Scryfall hit
fall back to a text-placeholder QFrame.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
)

from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
from gui.widgets.card_image_cache import load_pixmap

import gui.theme as theme


_CARD_W, _CARD_H = 76, 106


class PuzzleSceneWidget(QWidget):
    """Render a Scene as an MTGA-styled play table."""

    def __init__(self, scene: Optional[Scene] = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"PuzzleSceneWidget {{ background: {theme.BG}; }} "
            f"QLabel {{ color: {theme.TEXT}; }} "
        )
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(8, 8, 8, 8)
        self._outer.setSpacing(6)
        self._scene: Optional[Scene] = None
        if scene is not None:
            self.set_scene(scene)

    def set_scene(self, scene: Scene) -> None:
        """Replace the rendered scene."""
        self._scene = scene
        # Clear existing children
        while self._outer.count():
            item = self._outer.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        # Top → bottom
        self._outer.addLayout(self._make_opp_header(scene.opp))
        self._outer.addLayout(self._make_card_row(scene.opp.battlefield_lands, label="opp lands"))
        self._outer.addLayout(self._make_card_row(scene.opp.battlefield_creatures, label="opp creatures"))
        self._outer.addWidget(self._make_divider())
        self._outer.addLayout(self._make_card_row(scene.you.battlefield_creatures, label="your creatures"))
        self._outer.addLayout(self._make_card_row(scene.you.battlefield_lands, label="your lands"))
        self._outer.addLayout(self._make_you_header(scene.you))
        self._outer.addLayout(self._make_hand_row(scene.you.hand, label=f"your hand ({len(scene.you.hand)})"))

    # ── Header builders ────────────────────────────────────────
    def _make_opp_header(self, opp: PlayerState) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(self._make_player_label(opp, is_opp=True))
        h.addStretch(1)
        h.addWidget(self._make_life_circle(opp.life, is_opp=True))
        h.addStretch(1)
        h.addWidget(QLabel(f"hand: {len(opp.hand)}"))
        return h

    def _make_you_header(self, you: PlayerState) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(self._make_player_label(you, is_opp=False))
        h.addStretch(1)
        low = you.life <= 5
        h.addWidget(self._make_life_circle(you.life, is_opp=False, low=low))
        h.addStretch(1)
        h.addWidget(QLabel(f"mana: {_format_mana(you.mana_available)}"))
        return h

    def _make_player_label(self, player: PlayerState, *, is_opp: bool) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(w); v.setContentsMargins(8, 4, 8, 4); v.setSpacing(0)
        name = QLabel(f"<b>{player.name}</b>")
        arch = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>{player.archetype}</span>")
        v.addWidget(name); v.addWidget(arch)
        color = theme.ACCENT if not is_opp else "#d88060"
        w.setStyleSheet(f"QFrame {{ border: 1px solid {color}; border-radius: 6px; }}")
        return w

    def _make_life_circle(self, life: int, *, is_opp: bool, low: bool = False) -> QLabel:
        color = "#f04040" if low else ("#d88060" if is_opp else theme.ACCENT)
        lbl = QLabel(str(life))
        lbl.setFixedSize(64, 64)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; border: 3px solid {color}; "
            f"border-radius: 32px; color: {theme.TEXT}; "
            f"font-size: 22px; font-weight: bold; }}"
        )
        return lbl

    def _make_divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {theme.BORDER};")
        return f

    # ── Card rows ──────────────────────────────────────────────
    def _make_card_row(self, cards: list[CardInZone], *, label: str) -> QHBoxLayout:
        h = QHBoxLayout(); h.setSpacing(3)
        tag = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>{label}</span>")
        tag.setFixedWidth(80)
        h.addWidget(tag)
        h.addStretch(1)
        for c in cards:
            h.addWidget(self._make_card_widget(c))
        h.addStretch(1)
        return h

    def _make_hand_row(self, cards: list[CardInZone], *, label: str) -> QHBoxLayout:
        h = QHBoxLayout(); h.setSpacing(3)
        tag = QLabel(f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>{label}</span>")
        tag.setFixedWidth(80)
        h.addWidget(tag)
        h.addStretch(1)
        for c in cards:
            h.addWidget(self._make_card_widget(c, is_hand=True))
        h.addStretch(1)
        return h

    def _make_card_widget(self, card: CardInZone, *, is_hand: bool = False) -> QWidget:
        """Try Scryfall image; fall back to text placeholder."""
        if card.is_face_down:
            return self._make_face_down()
        px: Optional[QPixmap] = None
        if not is_hand or card.name:
            px = load_pixmap(card_name=card.name, grpid=card.grpid)
        if px is not None:
            lbl = QLabel()
            lbl.setPixmap(px.scaled(_CARD_W, _CARD_H,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lbl.setToolTip(self._tooltip_for(card))
            if card.tapped:
                lbl.setStyleSheet("QLabel { padding: 0; transform: rotate(15deg); }")
            return lbl
        return self._make_placeholder(card)

    def _make_face_down(self) -> QLabel:
        lbl = QLabel("")
        lbl.setFixedSize(_CARD_W, _CARD_H)
        lbl.setStyleSheet(
            "QLabel { background: #3d1a1a; border: 1px solid #7d2a2a; border-radius: 4px; }"
        )
        return lbl

    def _make_placeholder(self, card: CardInZone) -> QLabel:
        lbl = QLabel(f"<b>{card.name}</b>")
        lbl.setFixedSize(_CARD_W, _CARD_H)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; border: 1px dashed {theme.ACCENT}; "
            f"border-radius: 4px; padding: 4px; color: {theme.TEXT}; font-size: 9px; }}"
        )
        lbl.setToolTip(self._tooltip_for(card))
        return lbl

    def _tooltip_for(self, card: CardInZone) -> str:
        parts = [card.name]
        if card.power is not None and card.toughness is not None:
            parts.append(f"{card.power}/{card.toughness}")
        if card.tapped:
            parts.append("(tapped)")
        return " · ".join(parts)


def _format_mana(mana: dict[str, int]) -> str:
    """Render a mana dict as a compact string: {'U': 2, 'R': 1} -> 'UUR'."""
    if not mana:
        return "0"
    parts = []
    for color in "WUBRGC":
        parts.extend([color] * mana.get(color, 0))
    return "".join(parts) or "0"
```

- [ ] **Step 2: Smoke test in offscreen Qt**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys
sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
from gui.widgets.puzzle_scene import PuzzleSceneWidget
scene = Scene(
    arena_match_id='m1', game_num=1, turn_num=7, play_or_draw='draw',
    you=PlayerState(name='You', archetype='Tokyo Prowess', life=4,
        hand=[CardInZone(name='Burst Lightning')]),
    opp=PlayerState(name='M', archetype='Mono Green Landfall', life=12),
    notes='',
)
w = PuzzleSceneWidget(scene)
print('Constructed:', w)
print('Children:', w.layout().count())
"
```

Expected: prints `Constructed: <PuzzleSceneWidget ...>` and a child count > 0 with no exceptions.

- [ ] **Step 3: Run the full suite to ensure nothing broke**

```bash
python -m pytest tests/ -q --tb=line
```

Expected: 143 + 14 new = 157 passed (or 143 if you've been running a stricter delta).

- [ ] **Step 4: Commit**

```bash
git add gui/widgets/puzzle_scene.py
git commit -m "feat(puzzles): PuzzleSceneWidget — MTGA-style render"
```

---

## Task 7: PuzzlesTab — Solve mode

**Files:**
- Create: `gui/tabs/puzzles.py`
- Create: `tests/test_puzzles_tab.py`

- [ ] **Step 1: Write failing tab smoke test**

Create `tests/test_puzzles_tab.py`:

```python
"""Smoke + integration tests for gui/tabs/puzzles.py."""
import os
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


def test_puzzles_tab_constructs_with_empty_db(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_DB_PATH", tmp_path / "p_arc.db")
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    assert tab.windowTitle() == "" or True  # just check no exception
    # Empty state should render some hint label
    text = tab.findChild_text_recursive()  # we'll add this helper below
    assert "no puzzles" in text.lower() or "queue is empty" in text.lower()


def test_puzzles_tab_renders_first_puzzle(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_DB_PATH", tmp_path / "p_arc.db")
    # Seed one puzzle
    from db import puzzles
    pid = puzzles.save_puzzle(
        deck_id=None, arena_match_id=None, game_num=None, turn_num=7,
        category="stabilize", difficulty=3,
        question="Survive opp's T8",
        solution_text="Cast Slagstorm, keep Crab.",
        solution_keywords=[], grading_mode="self",
        author="seeder", notes="",
        scene={
            "arena_match_id": "x", "game_num": 1, "turn_num": 7,
            "play_or_draw": "draw",
            "you": {"name": "You", "life": 4},
            "opp": {"name": "Opp", "life": 12},
        },
    )
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    text = tab.findChild_text_recursive()
    assert "Survive opp's T8" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_puzzles_tab.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `gui/tabs/puzzles.py`**

```python
"""PUZZLES tab — Solve mode (Phase 1).

Loads one unsolved puzzle at a time, renders the scene, takes the user's
typed answer, reveals the author's solution on demand, and records the
self-grade verdict. Author and Inbox modes ship in Phase 2.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QSplitter, QFrame,
)

from analysis.puzzles.scene_builder import Scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("All", ""),
    ("🎯 Find lethal", "find_lethal"),
    ("🛡 Stabilize", "stabilize"),
    ("⚡ Tempo / Race", "tempo"),
]


class PuzzlesTab(QWidget):
    """Solo solve loop. Author / Inbox sub-modes deferred to Phase 2."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_puzzle: Optional[dict] = None
        self._reveal_t0_ms: Optional[int] = None
        self._build_ui()
        self._load_next_puzzle()

    # ── Construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Top bar — category filter + session stats
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
        outer.addLayout(top)

        # Split: scene on left, answer panel on right
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
        outer.addWidget(splitter, 1)

    # ── Data flow ──────────────────────────────────────────────
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
                "No puzzles yet — author one via the seeder script, "
                "or come back after Phase 2 ships the Inbox.</i>"
            )
            self._answer_edit.clear(); self._answer_edit.setEnabled(False)
            self._reveal_btn.setEnabled(False)
            self._solution_lbl.hide()
            self._got_it_btn.hide(); self._missed_btn.hide()
            self._scene_widget.set_scene(_empty_scene())
            return
        puzzle = candidates[-1]  # oldest first (queue style)
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

    # Test helper — returns concatenated text of all visible labels
    def findChild_text_recursive(self) -> str:
        out = []
        for lbl in self.findChildren(QLabel):
            out.append(lbl.text())
        for te in self.findChildren(QTextEdit):
            out.append(te.placeholderText() or "")
            out.append(te.toPlainText() or "")
        return " ".join(out)

    def cleanup(self) -> None:
        """Stop running workers. Phase 1 has none."""
        pass


# ── Module-level helpers ────────────────────────────────────────

def _empty_scene() -> Scene:
    from analysis.puzzles.scene_builder import PlayerState
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

Expected: PASS (2 passed)

- [ ] **Step 5: Run full suite, ensure no regressions**

```bash
python -m pytest tests/ -q --tb=line
```

Expected: 143 + 16 new = 159 passed.

- [ ] **Step 6: Commit**

```bash
git add gui/tabs/puzzles.py tests/test_puzzles_tab.py
git commit -m "feat(puzzles): PUZZLES tab — Solve mode + self-grade flow"
```

---

## Task 8: Wire PUZZLES tab into MainWindow

**Files:**
- Modify: `gui/main_window.py`

- [ ] **Step 1: Find the tab-construction site**

Search for where other top-level tabs are added:

```bash
grep -n "addTab\|_tabs.addTab\|tournament_prep\|TournamentPrepTab" gui/main_window.py | head -20
```

You should see lines like `self._tabs.addTab(self._tourney, "TOURNAMENT")`. The new tab goes in the same neighborhood.

- [ ] **Step 2: Add the import + instantiation**

Modify `gui/main_window.py` — near the top with other tab imports (find the existing `from gui.tabs.tournament_prep import TournamentPrepTab` line and add below it):

```python
from gui.tabs.puzzles import PuzzlesTab
```

Then in the `_build_ui` method, after the existing tabs are added (after `RESOURCES` and before `SETTINGS`), insert:

```python
self._puzzles = PuzzlesTab()
self._tabs.addTab(self._puzzles, "PUZZLES")
```

If the tabs are added by walking a `for label, widget in (...)` tuple, add the tuple entry instead.

- [ ] **Step 3: Add PuzzlesTab to MainWindow.cleanup()**

Find the `def cleanup(self):` block. The existing code walks a tuple of tabs and calls `tab.cleanup()` on each. Add `self._puzzles` to that tuple:

```python
for tab in (
    self._dash, self._deck, self._heatmap, self._charts,
    self._simulate, self._calibration, self._preds,
    self._claude, self._set_analysis, self._search,
    self._my_decks, self._match_log, self._kb,
    self._tourney, self._puzzles, self._settings,
):
```

- [ ] **Step 4: Headless smoke that MainWindow constructs**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from gui.main_window import MainWindow
w = MainWindow()
print('Tabs:', [w._tabs.tabText(i) for i in range(w._tabs.count())])
"
```

Expected output includes `'PUZZLES'` in the tab list.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest tests/ -q --tb=line
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add gui/main_window.py
git commit -m "feat(puzzles): wire PUZZLES top-level tab into MainWindow"
```

---

## Task 9: Seeder script for hand-authored puzzles

**Files:**
- Create: `scripts/seed_puzzles.py`

The seeder produces 3 hand-authored puzzles (one per category) so the Solve loop has real content the first time the user opens the tab.

- [ ] **Step 1: Write the seeder**

Create `scripts/seed_puzzles.py`:

```python
"""CLI seeder: insert 3 hand-authored puzzles (one per category) for Phase 1
manual smoke. Re-runnable; deduplicates on (question, category).

Usage:
    python scripts/seed_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import puzzles as db_puzzles


# ── Scene builders (defined first so _SEED_PUZZLES below can call them) ──

def _stabilize_scene() -> dict:
    """Tokyo Prowess vs MGL, T7, you at 4, opp at 12, see the v5 mockup."""
    return {
        "arena_match_id": "seeded-1", "game_num": 1, "turn_num": 7,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 4,
            "hand": [
                {"name": "Burst Lightning"},
                {"name": "Slickshot Show-Off"},
                {"name": "Boomerang Basics"},
                {"name": "Slagstorm"},
                {"name": "Get Out"},
            ],
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island"},
                {"name": "Mountain"}, {"name": "Mountain"},
            ],
            "battlefield_creatures": [
                {"name": "Eddymurk Crab", "power": 4, "toughness": 5},
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "Mestre dos Magos", "archetype": "Mono Green Landfall",
            "life": 12,
            "hand": [{"name": "?", "is_face_down": True}] * 5,
            "battlefield_lands": [
                {"name": "Forest"}, {"name": "Forest"}, {"name": "Forest"},
                {"name": "Forest", "tapped": True},
                {"name": "Forest", "tapped": True},
            ],
            "battlefield_creatures": [
                {"name": "Llanowar Elves", "power": 1, "toughness": 1},
                {"name": "Llanowar Elves", "power": 1, "toughness": 1},
                {"name": "Worldwagon", "power": 4, "toughness": 4},
                {"name": "Dryadine", "power": 2, "toughness": 3},
            ],
        },
        "notes": "Opp has Worldwagon + 2 Elves; can attack for 6+ on T8.",
    }


def _find_lethal_scene() -> dict:
    return {
        "arena_match_id": "seeded-2", "game_num": 1, "turn_num": 8,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 6,
            "hand": [
                {"name": "Burst Lightning"},
                {"name": "Slickshot Show-Off"},
                {"name": "Boomerang Basics"},
            ],
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island"},
                {"name": "Mountain"}, {"name": "Mountain"},
            ],
            "battlefield_creatures": [
                {"name": "Eddymurk Crab", "power": 4, "toughness": 5},
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "Opp", "archetype": "?", "life": 8,
            "hand": [{"name": "?", "is_face_down": True}] * 4,
            "battlefield_lands": [
                {"name": "Plains"}, {"name": "Plains"}, {"name": "Island"},
            ],
            "battlefield_creatures": [
                {"name": "Floodpits Drowner", "power": 1, "toughness": 4},
            ],
        },
        "notes": "Slickshot's prowess + Crab's 4 power can close it.",
    }


def _tempo_scene() -> dict:
    return {
        "arena_match_id": "seeded-3", "game_num": 1, "turn_num": 3,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 20,
            "hand": [
                {"name": "Stormchaser's Talent"},
                {"name": "Disdainful Stroke"},
                {"name": "Eddymurk Crab"},
                {"name": "Burst Lightning"},
            ],
            "battlefield_lands": [{"name": "Island"}, {"name": "Island"}, {"name": "Mountain"}],
            "mana_available": {"U": 2, "R": 1},
        },
        "opp": {
            "name": "Opp", "archetype": "?", "life": 20,
            "hand": [{"name": "?", "is_face_down": True}] * 5,
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island", "tapped": True},
                {"name": "Plains"}, {"name": "Plains"},
            ],
        },
        "notes": "Opp tapped out; you have 3 mana up next turn for Talent + Stroke.",
    }


# ── Puzzle catalog (built AFTER scene helpers above) ────────────

_SEED_PUZZLES = [
    {
        "category": "stabilize",
        "difficulty": 3,
        "question": "Survive opp's T8",
        "solution_text": (
            "Cast Slagstorm (3 dmg to each creature) — kills both Llanowar Elves "
            "and Dryadine. Worldwagon survives at 1 toughness. Crab stays "
            "untapped to block Worldwagon next turn (Crab 4/5 vs 4/4 → Crab "
            "lives, Worldwagon dies). You take 0 in combat; stay at 4."
        ),
        "notes": "Aggressive: -2 to your own face from Slagstorm is the cost.",
        "scene": _stabilize_scene(),
    },
    {
        "category": "find_lethal",
        "difficulty": 4,
        "question": "Find lethal — opp at 8, you at 6",
        "solution_text": (
            "Cast Slickshot Show-Off for R (1 spell). Cast Boomerang Basics "
            "bouncing opp's only blocker (2 spells now, Slickshot is 3/1). "
            "Cast Burst Lightning targeting opp (3 spells, Slickshot is 4/1, "
            "2 damage from Burst). Attack with Slickshot for 4 + Crab for 4. "
            "Total: 2 + 4 + 4 = 10 → opp dead."
        ),
        "notes": "Slickshot's own cast doesn't trigger its prowess.",
        "scene": _find_lethal_scene(),
    },
    {
        "category": "tempo",
        "difficulty": 2,
        "question": "Hold or deploy?",
        "solution_text": (
            "Hold Stormchaser's Talent until end-of-opp-turn — they're tapped "
            "out so they can't punish you for the sorcery-speed cast next "
            "turn. Pass with UU up to threaten Disdainful Stroke on their "
            "next 4+ drop. This gives you more information AND keeps the "
            "Talent as a Bo3 threat without committing too early."
        ),
        "notes": "The tempo principle: don't spend a turn proactively when "
                 "holding mana information-asymmetrically is stronger.",
        "scene": _tempo_scene(),
    },
]


def main() -> None:
    existing = {(p["question"], p["category"]) for p in db_puzzles.get_puzzles()}
    inserted = 0
    for spec in _SEED_PUZZLES:
        key = (spec["question"], spec["category"])
        if key in existing:
            print(f"[skip] already exists: {spec['question']}")
            continue
        pid = db_puzzles.save_puzzle(
            deck_id=None,
            arena_match_id=spec["scene"]["arena_match_id"],
            game_num=spec["scene"]["game_num"],
            turn_num=spec["scene"]["turn_num"],
            category=spec["category"],
            difficulty=spec["difficulty"],
            question=spec["question"],
            solution_text=spec["solution_text"],
            solution_keywords=[],
            grading_mode="self",
            author="seeder",
            notes=spec["notes"],
            scene=spec["scene"],
        )
        inserted += 1
        print(f"[ok] inserted puzzle id={pid} ({spec['category']}): {spec['question']}")
    print(f"\nDone. Inserted {inserted} / Skipped {len(_SEED_PUZZLES) - inserted}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the seeder against the real DB**

```bash
python scripts/seed_puzzles.py
```

Expected output: 3 `[ok] inserted` lines first run; 3 `[skip] already exists` on second run.

- [ ] **Step 3: Verify with a direct DB query**

```bash
python -c "
from db import puzzles
ps = puzzles.get_puzzles()
print(f'{len(ps)} puzzles')
for p in ps:
    print(f'  {p[\"category\"]:<14} {p[\"question\"]}')
"
```

Expected: 3 puzzles listed (stabilize / find_lethal / tempo).

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_puzzles.py
git commit -m "feat(puzzles): seeder script with 3 hand-authored puzzles"
```

---

## Task 10: Manual end-to-end smoke

**Files:** none — driving the GUI by hand.

- [ ] **Step 1: Launch the GUI**

```bash
python run_gui.py
```

- [ ] **Step 2: Open PUZZLES tab**

Click the new `PUZZLES` tab in the top bar. The first puzzle (Tempo — "Hold or deploy?") should render with:
- A scene showing your hand (4 cards), your lands (3), opp hand (5 face-down), opp lands (4)
- Category badge: "⚡ Tempo / Race · ★★☆☆☆"
- Question: "Hold or deploy?"
- Notes line below the question
- An empty answer textarea + "Reveal solution" button

- [ ] **Step 3: Type an answer, hit Reveal**

Type any guess. Click "Reveal solution". Expect the author's solution to appear below, plus two new buttons "✓ I had it" and "✗ Missed it".

- [ ] **Step 4: Self-grade + advance**

Click one of the buttons. Expect the next puzzle to load (Find lethal — "opp at 8, you at 6"). Repeat for the third (Stabilize — "Survive opp's T8").

- [ ] **Step 5: Verify all three solved → empty state**

After grading all 3, the queue should be empty and show the "Queue is empty. No puzzles yet" hint. Session stats top-right should show the count.

- [ ] **Step 6: Verify attempts persisted**

```bash
python -c "
from db import puzzles
print(puzzles.get_session_stats())
"
```

Expected: shows `n_solved + n_missed == 3`.

- [ ] **Step 7: Run full suite one more time**

```bash
python -m pytest tests/ -q --tb=line
```

Expected: all green.

- [ ] **Step 8: Commit any smoke-test fixes**

If anything broke during the manual smoke, fix on the spot and commit as `fix(puzzles): <description>`. Otherwise no commit needed.

---

## Task 11: Push + update CLAUDE.md / NEXT_STEPS

**Files:**
- Modify: `CLAUDE.md`
- Modify: `NEXT_STEPS.md`

- [ ] **Step 1: Add a "Puzzles tab" entry to CLAUDE.md**

Open `CLAUDE.md`. Find Section 6 ("GUI") and its "7 top-level tabs (consolidated from 13): Dashboard, Meta (...), Decks (...), Search, Tournament (...), Resources (...), Settings" line. Change "7 top-level tabs" to "8 top-level tabs" and insert `Puzzles (Solve)` before Settings. Then below the existing per-tab feature paragraphs, add a new paragraph:

```markdown
- **Puzzles tab (Solve mode, Phase 1)**: MTGA-style "find-the-line"
  practice. Renders a saved scene (life circles, mirrored zones, fanned
  hand, Scryfall card images) with a typed-answer + reveal-solution +
  self-grade flow. Records every attempt in `puzzle_attempts`. Hand-
  authored puzzles seeded via `scripts/seed_puzzles.py`. Spec at
  `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`. Phase 2
  (scanner + Inbox + Author dialog + Match-History right-click) scheduled
  for 5/20; Phase 3 (keyword + LLM graders) for 5/22.
```

- [ ] **Step 2: Add a "Phase 1 shipped" entry to NEXT_STEPS.md**

Under the "What shipped" section, add:

```markdown
### Puzzle tool — Phase 1 shipped (2026-05-1X)
- `db/puzzles.py` schema + CRUD for puzzles + puzzle_attempts; puzzle_inbox table created idempotently (wired in Phase 2)
- `analysis/puzzles/scene_builder.py` — Scene / PlayerState / CardInZone dataclasses, build_scene() pulls life from cached transcripts
- `gui/widgets/card_image_cache.py` — Scryfall JPEG cache at `data/card_images/<grpid_or_slug>.jpg`
- `gui/widgets/puzzle_scene.py` — MTGA-style render widget (corner avatars, centered life, mirrored zones, fanned hand)
- `gui/tabs/puzzles.py` — PUZZLES top-level tab, Solve mode with self-grade verification
- `scripts/seed_puzzles.py` — 3 hand-authored puzzles (one per category)
- Spec at `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`; Phase 2 (scanner + Inbox + Author dialog) scheduled by 5/20.
```

- [ ] **Step 3: Commit + push**

```bash
git add CLAUDE.md NEXT_STEPS.md
git commit -m "docs(puzzles): Phase 1 shipped notes in CLAUDE.md + NEXT_STEPS"
git push
```

Expected: push succeeds. If the pre-push hook flags PII, scrub per [[feedback_no-user-handles-in-docs]] and re-commit.

---

## Validation gates (mechanical)

Phase 1 is "shipped" when ALL of these are true:

- [ ] `python -m pytest tests/` shows ≥ 143 + 16 = 159 passed (the new puzzle tests don't regress anything)
- [ ] `python scripts/seed_puzzles.py` produces 3 puzzles on first run, 0 on second (idempotent)
- [ ] Launching GUI, opening PUZZLES tab, solving + self-grading all 3 seeded puzzles works without exceptions
- [ ] `python -c "from db import puzzles; print(puzzles.get_session_stats())"` shows non-zero `n_solved + n_missed`
- [ ] `git push` succeeds without hook block (PII scrubbed in CLAUDE.md / NEXT_STEPS)

---

## What this does NOT do (intentional Phase 1 limits)

- No scanner / Inbox / Author dialog (Phase 2)
- No keyword grader or LLM grader (Phase 3)
- No JSON export / shared DB (Phase 4)
- No right-click integration in Match History sub-tab (Phase 2)
- `build_scene()` only extracts life totals + opening hand — battlefield + mana state are filled in by the seeder, NOT auto-extracted. Phase 2 will mine `gameStateMessage.zones` for a full snapshot.

These are deferred on purpose. The shipped v0 is a working solo solve loop with hand-authored content, which is the smallest scope that delivers real practice value before RC DC.
