"""Daily feed for the puzzle trainer (T1.1, 2026-09-21) -- tmp DB only.

The conftest live-DB guard points db.database.DB_PATH at an empty tmp file;
`puzzle_db` initialises the schema and seeds puzzles + attempts with
controllable dates. Spec: docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

TODAY = date(2026, 9, 21)


def _utc_iso(day: date, hour: int = 12) -> str:
    """A UTC 'Z' timestamp that falls on `day` in LOCAL time (noon local)."""
    local = datetime.combine(day, time(hour)).astimezone()
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scene():
    return {"arena_match_id": "x", "game_num": 1, "turn_num": 1, "play_or_draw": "draw",
            "you": {"name": "You", "life": 20}, "opp": {"name": "Opp", "life": 20}}


@pytest.fixture
def puzzle_db():
    from db.database import init_db, get_connection
    from db import puzzles as db_puzzles
    init_db()
    db_puzzles._ensure_tables()

    def add_puzzle(category="drill_outs", author="seeder"):
        return db_puzzles.save_puzzle(
            deck_id=None, arena_match_id=None, game_num=None, turn_num=1,
            category=category, difficulty=2, question=f"q-{category}",
            solution_text="42", solution_keywords=[], grading_mode="number",
            author=author, notes="", scene=_scene())

    def add_attempt(puzzle_id, day, verdict="correct"):
        with get_connection() as con:
            con.execute(
                "INSERT INTO puzzle_attempts (puzzle_id, attempted_at, user_answer, verdict, grader_used) "
                "VALUES (?,?,?,?,?)", (puzzle_id, _utc_iso(day), "42", verdict, "self"))

    return {"add_puzzle": add_puzzle, "add_attempt": add_attempt}


def test_get_attempt_log_joins_category_and_orders_by_id(puzzle_db):
    from db import puzzles as db_puzzles
    p1 = puzzle_db["add_puzzle"]("drill_outs")
    p2 = puzzle_db["add_puzzle"]("find_lethal")
    puzzle_db["add_attempt"](p2, TODAY - timedelta(days=1), "incorrect")
    puzzle_db["add_attempt"](p1, TODAY, "correct")
    log = db_puzzles.get_attempt_log()
    assert [(r["puzzle_id"], r["verdict"], r["category"]) for r in log] == \
        [(p2, "incorrect", "find_lethal"), (p1, "correct", "drill_outs")]
    assert [r["puzzle_id"] for r in db_puzzles.get_attempt_log(category="drill_outs")] == [p1]
    assert all(r["attempted_at"].endswith("Z") for r in log)


def test_count_puzzles_created_since(puzzle_db):
    from db import puzzles as db_puzzles
    puzzle_db["add_puzzle"]("drill_outs", author="drill_generator")
    puzzle_db["add_puzzle"]("drill_outs", author="drill_generator")
    puzzle_db["add_puzzle"]("drill_outs", author="seeder")
    puzzle_db["add_puzzle"]("find_lethal", author="drill_generator")
    since = "2000-01-01T00:00:00Z"
    assert db_puzzles.count_puzzles_created_since(author="drill_generator", category="drill_outs", since_iso=since) == 2
    assert db_puzzles.count_puzzles_created_since(author="drill_generator", category="drill_outs", since_iso="2999-01-01T00:00:00Z") == 0
