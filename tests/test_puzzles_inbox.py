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
