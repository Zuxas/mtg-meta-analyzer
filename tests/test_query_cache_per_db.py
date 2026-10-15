"""#12: win_rates._cached served one database's results for another.

The cache key was only the query parameters, so within the 60 s TTL a call
against database B returned what an earlier call computed against database
A. In the suite that meant the meta-share standings tests got the real DB's
cached real-match standings instead of their tmp fixture's.
"""
import sqlite3


def _db_with_matches(path, wins_for_a):
    import db.database as dbm
    dbm.DB_PATH = str(path)
    dbm.init_db()
    from db.matches_queries import _ensure_table
    _ensure_table()
    con = sqlite3.connect(str(path))
    for i in range(20):
        result = "player1" if i < wins_for_a else "player2"
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e1", i, f"p{i}", f"q{i}", "Deck A", "Deck B", result,
             "standard", "2026-10-01", "mtgmelee"))
    con.commit()
    con.close()


def test_cached_results_are_per_database(tmp_path, monkeypatch):
    import db.database as dbm
    from analysis import win_rates as wr
    monkeypatch.setattr(dbm, "DB_PATH", dbm.DB_PATH)
    wr._query_cache.clear()

    _db_with_matches(tmp_path / "a.db", wins_for_a=15)
    first = wr.get_real_archetype_winrates("standard", min_matches=1)
    assert first["Deck A"]["wins"] == 15

    # Same query parameters, different database, well inside the TTL.
    _db_with_matches(tmp_path / "b.db", wins_for_a=5)
    second = wr.get_real_archetype_winrates("standard", min_matches=1)
    assert second["Deck A"]["wins"] == 5
