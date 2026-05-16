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
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
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


def test_puzzles_table_shape_via_smoke_insert(tmp_db):
    """Insert + read-back via raw SQL to catch typos in column names / NOT NULLs."""
    from db import puzzles
    puzzles._ensure_tables()
    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "INSERT INTO puzzles "
            "(deck_id, arena_match_id, game_num, turn_num, category, "
            " difficulty, question, solution_text, solution_keywords_json, "
            " grading_mode, author, notes, scene_json, created_at, updated_at) "
            "VALUES (NULL, 'm-1', 1, 3, 'find_lethal', "
            "        2, 'q', 's', '[]', 'self', 'seeder', '', '{}', "
            "        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        row = conn.execute(
            "SELECT category, question, scene_json FROM puzzles WHERE id=1"
        ).fetchone()
    assert row[0] == "find_lethal"
    assert row[1] == "q"
    assert row[2] == "{}"
