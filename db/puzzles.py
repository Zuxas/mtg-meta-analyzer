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


