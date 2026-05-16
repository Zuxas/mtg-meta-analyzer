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
