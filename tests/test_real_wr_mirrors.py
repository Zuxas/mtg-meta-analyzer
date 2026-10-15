"""#26: mirror matches must not count toward an archetype's real win rate.

A mirror (A vs A) was one win and one loss for A, so A's win rate was pulled
toward 50% by how often it played itself: 30-10 vs B plus 20 mirrors read as
62.5% (50-30) instead of 75% (30-10).
"""
import sqlite3

import pytest


@pytest.fixture
def a_vs_b_with_mirrors(tmp_path, monkeypatch):
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "m.db"))
    dbm.init_db()
    from db.matches_queries import _ensure_table
    _ensure_table()
    from analysis import win_rates as wr
    wr._query_cache.clear()

    rows = ([("Deck A", "Deck B", "player1")] * 30
            + [("Deck A", "Deck B", "player2")] * 10
            + [("Deck A", "Deck A", "player1")] * 20)
    con = sqlite3.connect(dbm.DB_PATH)
    for i, (p1, p2, res) in enumerate(rows):
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e1", i, f"p{i}", f"q{i}", p1, p2, res, "standard", "2026-10-01",
             "mtgmelee"))
    con.commit()
    con.close()


def test_mirrors_are_excluded_from_win_rate(a_vs_b_with_mirrors):
    from analysis.win_rates import get_real_archetype_winrates
    a = get_real_archetype_winrates("standard", min_matches=1)["Deck A"]
    assert (a["wins"], a["losses"], a["total"]) == (30, 10, 40)
    assert a["win_rate"] == 0.75
    assert a["mirrors"] == 20


def test_matchups_have_no_self_pairs(a_vs_b_with_mirrors):
    from analysis.win_rates import get_real_matchup_winrates
    m = get_real_matchup_winrates("standard", min_matches=1)
    assert all(a != b for a, opps in m.items() for b in opps)
    assert m["Deck A"]["Deck B"]["total"] == 40


def test_fallback_share_still_counts_both_mirror_seats(a_vs_b_with_mirrors):
    """Meta share is about seats in the field: a mirror is two decks."""
    from analysis.win_rates import _meta_standings_from_matches
    rows = {r["archetype"]: r for r in _meta_standings_from_matches("standard",
                                                                    min_appearances=1)}
    assert rows["Deck A"]["appearances"] == 80   # 40 vs B + 2 seats x 20 mirrors
    assert rows["Deck B"]["appearances"] == 40
    assert rows["Deck A"]["meta_share"] == round(80 / 120, 4)


def test_mirror_only_archetype_stays_in_fallback(a_vs_b_with_mirrors):
    """An archetype that only played itself has no real-WR row but still sits
    in the field: it must keep its seats, with the mirror rate (50%) as WR."""
    import db.database as dbm
    from analysis import win_rates as wr
    con = sqlite3.connect(dbm.DB_PATH)
    for i in range(3):
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e2", i, f"m{i}", f"n{i}", "Deck C", "Deck C", "player1", "standard",
             "2026-10-01", "mtgmelee"))
    con.commit()
    con.close()
    wr._query_cache.clear()

    assert "Deck C" not in wr.get_real_archetype_winrates("standard", min_matches=1)
    rows = {r["archetype"]: r for r in wr._meta_standings_from_matches(
        "standard", min_appearances=1)}
    assert rows["Deck C"]["appearances"] == 6
    assert rows["Deck C"]["meta_share"] == round(6 / 126, 4)
    assert rows["Deck C"]["est_match_winpct"] == 0.5
    assert rows["Deck C"]["non_mirror_matches"] == 0
    assert rows["Deck A"]["non_mirror_matches"] == 40
    assert rows["Deck A"]["est_match_winpct"] == 0.75
