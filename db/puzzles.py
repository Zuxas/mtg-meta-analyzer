"""Puzzles + attempts + inbox persistence.

Schema lives here; CRUD helpers below. Phase 1 wires only puzzles + puzzle_attempts
API; the inbox table is created idempotently so Phase 2 doesn't need a migration.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from db.database import get_connection
from db.helpers import utc_now as _utc_now
import db.saved_decks as _saved_decks_mod


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
    _saved_decks_mod._ensure_tables()  # puzzles FK references saved_decks
    with get_connection() as conn:
        conn.executescript(_TABLES_SQL)


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
    now = _utc_now()
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
    if unsolved_only:
        clauses.append(
            "id NOT IN (SELECT DISTINCT puzzle_id FROM puzzle_attempts "
            "WHERE verdict='correct')"
        )
    sql = "SELECT * FROM puzzles"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_puzzle(r) for r in rows]


def delete_puzzle(puzzle_id: int) -> None:
    _ensure_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM puzzles WHERE id = ?", (puzzle_id,))


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
            (puzzle_id, _utc_now(), user_answer, verdict, grader_used, time_spent_ms),
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

