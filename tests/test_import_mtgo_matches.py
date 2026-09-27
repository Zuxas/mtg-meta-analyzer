import sqlite3
from datetime import datetime

from db.database import get_connection
from scripts import import_mtgo_matches as im


def _rec(mid, result="win", my_deck="Boros Energy", fmt="modern"):
    return {
        "mtgo_match_id": mid, "event_name": "Modern Challenge 32", "event_date": "2026-09-26",
        "started": datetime(2026, 9, 26, 18), "format": fmt, "round": 3, "opp_name": "Bob",
        "result": result, "play_draw": "play", "g": ["win", "loss", "win"],
        "my_deck": my_deck, "my_deck_exact": False, "my_cards": {"Guide of Souls": 2},
        "opp_deck": "Amulet Titan", "opp_conf": 0.6, "opp_cards": {"Amulet of Vigor": 1},
        "per_game": {1: {"n_turns": 5, "my_mull_to": 6, "opp_mull_to": 7},
                     2: {"n_turns": 7, "my_mull_to": 7, "opp_mull_to": 7}},
    }


def _db():
    from db import saved_decks
    from db.database import init_db
    from db.match_games import _ensure_table as ensure_games
    from db.match_log import _ensure_table
    init_db()
    _ensure_table()
    saved_decks._ensure_tables()
    with get_connection() as conn:
        ensure_games(conn)
        conn.execute("INSERT INTO match_log (event_name, result, my_deck, created_at) "
                     "VALUES ('manual', 'loss', 'X', '2026-01-01T00:00:00Z')")
    from db.database import DB_PATH
    return sqlite3.connect(DB_PATH)


def test_write_is_idempotent_and_skips_undecided():
    con = _db()
    recs = [_rec("a"), _rec("b", result="loss"), _rec("c", result="incomplete")]
    with con:
        assert im.write_records(con, recs) == 2
    with con:
        assert im.write_records(con, recs) == 0
    rows = con.execute("SELECT mtgo_match_id, result, source, backfill_status, format "
                       "FROM match_log WHERE source='mtgo_log' ORDER BY 1").fetchall()
    assert rows == [("a", "win", "mtgo_log", "live", "modern"),
                    ("b", "loss", "mtgo_log", "live", "modern")]
    assert con.execute("SELECT COUNT(*) FROM match_log WHERE source='manual' "
                       "OR source IS NULL OR event_name='manual'").fetchone()[0] == 1


def test_unknown_my_deck_goes_to_resolve_backlog():
    con = _db()
    with con:
        im.write_records(con, [_rec("z", my_deck="")])
    assert con.execute("SELECT backfill_status, my_deck_id FROM match_log "
                       "WHERE mtgo_match_id='z'").fetchone() == ("orphan", None)


def test_per_game_rows_and_notes():
    con = _db()
    with con:
        im.write_records(con, [_rec("g")])
    mid, notes = con.execute("SELECT id, notes FROM match_log WHERE mtgo_match_id='g'").fetchone()
    games = con.execute("SELECT game_num, n_turns, my_mull_to, opp_mull_to FROM match_log_games "
                        "WHERE match_log_id=? ORDER BY 1", (mid,)).fetchall()
    assert games == [(1, 5, 6, 7), (2, 7, 7, 7)]
    assert "mull to G1: 6" in notes and "confidence 0.60" in notes


def test_mtgo_rows_visible_to_personal_stats():
    con = _db()
    with con:
        im.write_records(con, [_rec("s"), _rec("t", result="loss")])
    con.close()
    from db.match_log import get_overall_stats
    stats = get_overall_stats(my_deck="Boros Energy")
    assert (stats["wins"], stats["losses"]) == (1, 1)
