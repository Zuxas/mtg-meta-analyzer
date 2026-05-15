"""Tests for db.match_games -- per-game stats."""
import sqlite3
import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    return db_path


def test_save_and_get_roundtrip(env):
    from db.match_games import save_stats_for_match, get_stats_for_match
    stats = {
        1: {"my_life_min": 5, "my_life_end": 5, "opp_life_min": 0,
            "opp_life_end": 0, "n_turns": 7, "my_mull_to": 7, "opp_mull_to": 6},
        2: {"my_life_min": 0, "my_life_end": 0, "opp_life_min": 12,
            "opp_life_end": 18, "n_turns": 10, "my_mull_to": 6, "opp_mull_to": 7},
    }
    n = save_stats_for_match(123, stats)
    assert n == 2
    rows = get_stats_for_match(123)
    assert len(rows) == 2
    assert rows[0]["game_num"] == 1
    assert rows[0]["my_life_end"] == 5
    assert rows[0]["opp_life_end"] == 0
    assert rows[0]["my_mull_to"] == 7
    assert rows[1]["game_num"] == 2
    assert rows[1]["my_mull_to"] == 6


def test_idempotent_upsert(env):
    from db.match_games import save_stats_for_match, get_stats_for_match
    s = {1: {"my_life_min": 5, "my_life_end": 5, "opp_life_min": 0,
             "opp_life_end": 0, "n_turns": 7, "my_mull_to": 7, "opp_mull_to": 7}}
    save_stats_for_match(50, s)
    s[1]["n_turns"] = 9  # mutate
    save_stats_for_match(50, s)
    rows = get_stats_for_match(50)
    assert len(rows) == 1
    assert rows[0]["n_turns"] == 9


def test_classify_game_blowout(env):
    from db.match_games import classify_game
    # I won, ended at 18, opp at 0 -> blowout
    assert classify_game(
        {"my_life_end": 18, "opp_life_end": 0}, my_won=True
    ) == "blowout"


def test_classify_game_close(env):
    from db.match_games import classify_game
    # I won at 2 life -- nailbiter (close)
    assert classify_game(
        {"my_life_end": 2, "opp_life_end": 0}, my_won=True
    ) == "close"
    # I lost at 2 hp opponent left -- still my loss; opponent had close win
    assert classify_game(
        {"my_life_end": 0, "opp_life_end": 1}, my_won=False
    ) == "close"


def test_classify_game_normal(env):
    from db.match_games import classify_game
    # I won 14 -> 8 (mid-range) -> normal
    assert classify_game(
        {"my_life_end": 8, "opp_life_end": 6}, my_won=True
    ) == "normal"


def test_keep_stats_for_deck(env):
    """Mulligan-bucket aggregation across multiple games."""
    import db.match_log
    db.match_log._ensure_table()

    from db.database import get_connection
    with get_connection() as c:
        # Insert match #1 with g1 won, g2 lost
        c.execute(
            "INSERT INTO match_log (event_date, format, my_deck_id, result, "
            "g1_result, g2_result, created_at) "
            "VALUES ('2026-05-14', 'standard', 7, 'win', 'win', 'loss', '2026-05-14T00:00:00')"
        )
        m1 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO match_log (event_date, format, my_deck_id, result, "
            "g1_result, g2_result, created_at) "
            "VALUES ('2026-05-14', 'standard', 7, 'loss', 'loss', 'win', '2026-05-14T00:00:00')"
        )
        m2 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.commit()

    from db.match_games import save_stats_for_match, keep_stats_for_deck
    # match 1: g1 kept 7 (won), g2 mull-to-6 (lost)
    save_stats_for_match(m1, {
        1: {"my_mull_to": 7},
        2: {"my_mull_to": 6},
    })
    # match 2: g1 kept 7 (lost), g2 kept 7 (won)
    save_stats_for_match(m2, {
        1: {"my_mull_to": 7},
        2: {"my_mull_to": 7},
    })

    agg = keep_stats_for_deck(7)
    assert agg["n_games"] == 4
    assert agg["keep_7"]["games"] == 3
    assert agg["keep_7"]["wins"] == 2  # m1g1 + m2g2
    assert agg["mull_to_6"]["games"] == 1
    assert agg["mull_to_6"]["wins"] == 0
