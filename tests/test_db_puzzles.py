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


def test_get_puzzles_unsolved_only_excludes_solved(tmp_db):
    """unsolved_only=True must exclude any puzzle with a correct attempt."""
    from db import puzzles
    puzzles._ensure_tables()
    pid_a = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m1", game_num=1, turn_num=1,
        category="stabilize", difficulty=2, question="qa",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    pid_b = puzzles.save_puzzle(
        deck_id=None, arena_match_id="m2", game_num=1, turn_num=1,
        category="stabilize", difficulty=2, question="qb",
        solution_text="s", solution_keywords=[], grading_mode="self",
        author="t", notes="", scene=_sample_scene_dict(),
    )
    puzzles.record_attempt(
        puzzle_id=pid_a, user_answer="x", verdict="correct",
        grader_used="self", time_spent_ms=1000,
    )
    # A missed-only puzzle should still be unsolved
    puzzles.record_attempt(
        puzzle_id=pid_b, user_answer="y", verdict="incorrect",
        grader_used="self", time_spent_ms=1000,
    )
    unsolved = puzzles.get_puzzles(unsolved_only=True)
    unsolved_ids = {p["id"] for p in unsolved}
    assert pid_a not in unsolved_ids   # excluded — correctly attempted
    assert pid_b in unsolved_ids       # still in queue — only missed
