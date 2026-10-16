"""#28: matches-based fallbacks count seats and respect `until`."""
import sqlite3
from datetime import datetime

import pytest


def _add(con, p1, p2, res, date, n):
    for i in range(n):
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"e-{date}", i, f"p{i}{p1}{date}", f"q{i}{p2}{date}", p1, p2, res, "standard",
             date, "mtgmelee"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "s.db"))
    dbm.init_db()
    from db.matches_queries import _ensure_table
    _ensure_table()
    from analysis import win_rates as wr
    wr._query_cache.clear()
    con = sqlite3.connect(dbm.DB_PATH)
    yield con
    con.close()


def test_trend_shares_are_seat_shares_and_sum_to_one(db):
    from analysis.win_rates import _archetype_trend_from_matches
    _add(db, "A", "B", "player1", "2026-10-07", 40)
    _add(db, "A", "A", "player1", "2026-10-07", 20)
    db.commit()
    end = datetime(2026, 10, 10)
    a = [w for w in _archetype_trend_from_matches("A", "standard", 1, None, end) if w["appearances"]]
    b = [w for w in _archetype_trend_from_matches("B", "standard", 1, None, end) if w["appearances"]]
    assert a[0]["meta_share"] == pytest.approx(80 / 120, abs=1e-3)   # 40 + 2*20 of 120 seats
    assert b[0]["meta_share"] == pytest.approx(40 / 120, abs=1e-3)
    assert a[0]["meta_share"] + b[0]["meta_share"] == pytest.approx(1.0, abs=1e-3)


def test_fallback_standings_respect_until(db):
    from analysis import win_rates as wr
    _add(db, "Old", "Other", "player1", "2026-09-01", 10)
    _add(db, "New", "Other", "player1", "2026-10-05", 10)
    db.commit()
    prior = {r["archetype"] for r in wr._meta_standings_from_matches(
        "standard", since=datetime(2026, 8, 1), until=datetime(2026, 10, 1), min_appearances=1)}
    assert "Old" in prior and "New" not in prior
    # until is exclusive: a match on the boundary day belongs to the next window
    assert "New" not in wr.get_real_archetype_winrates(
        "standard", since=datetime(2026, 8, 1), until=datetime(2026, 10, 5), min_matches=1)
