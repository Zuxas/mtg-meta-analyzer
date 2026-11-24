"""#25: infer_bracket_matches must only fabricate a top-8 bracket for events
that actually had one -- never a League/Preliminary 5-0 list, and once (not
twice) for a tournament scraped from two sources.

Runs against the per-test empty tmp DB (tests/conftest.py::_no_live_db).
"""
import pytest

import db.database as dbmod
from scrapers.mtgmelee_scraper import infer_bracket_matches, cleanup_league_bracket_rows


@pytest.fixture(autouse=True)
def _schema():
    dbmod.init_db()


def _event(eid, name, etype, fp_cs, n_decks, fmt="modern"):
    """Seed one event with n_decks ranked 1..n, archetypes 'A1'..'An'."""
    with dbmod.get_connection() as c:
        c.execute(
            "INSERT INTO events (id, source_id, source, name, date, format, event_type, "
            "url, event_fingerprint, event_fingerprint_cs) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid, str(eid), "mtgtop8", name, "2026-11-01", fmt, etype, "", "", fp_cs),
        )
        for place in range(1, n_decks + 1):
            c.execute(
                "INSERT INTO decks (event_id, source_id, player, archetype, placement) "
                "VALUES (?,?,?,?,?)",
                (eid, f"{eid}-{place}", f"p{place}", f"A{place}", place),
            )
        c.commit()


def _matches(fmt="modern"):
    with dbmod.get_connection() as c:
        return c.execute(
            "SELECT round, source, winner_arch FROM matches WHERE lower(format)=lower(?)",
            (fmt,),
        ).fetchall()


def test_league_event_infers_nothing():
    _event(1, "Modern League 2026-11-01", "mtgo_league", "fp-league", 8)
    assert infer_bracket_matches("modern") == 0
    assert _matches() == []


def test_league_by_name_when_event_type_null():
    # mtgtop8 stores League events with event_type NULL -> classify from name.
    _event(2, "Modern League", None, "fp-league2", 8)
    assert infer_bracket_matches("modern") == 0
    assert _matches() == []


def test_five_oh_list_below_eight_is_skipped():
    _event(3, "Some Paper Event", "paper", "fp-5oh", 5)
    assert infer_bracket_matches("modern") == 0
    assert _matches() == []


def test_real_top8_infers_only_the_final():
    # #19: semifinals are no longer guessed -- only the certain final is recorded.
    _event(4, "Modern Challenge 32", "mtgo_challenge_32", "fp-chal", 8)
    assert infer_bracket_matches("modern") == 1
    rows = _matches()
    finals = [r for r in rows if r["round"] == -1]
    assert len(finals) == 1 and finals[0]["winner_arch"] == "A1"
    assert [r for r in rows if r["round"] == -2] == []
    assert [r for r in rows if r["source"] == "bracket_sf"] == []


def test_cross_source_duplicate_collapses_to_one_final():
    # Same tournament scraped from two sources shares event_fingerprint_cs.
    _event(5, "RC Modern", "paper", "fp-dup", 8)
    _event(6, "RC Modern", "paper", "fp-dup", 8)
    assert infer_bracket_matches("modern") == 1        # one final, not two
    assert len([r for r in _matches() if r["round"] == -1]) == 1


def test_event_with_real_rows_is_not_inferred():
    _event(7, "Modern Challenge 32", "mtgo_challenge_32", "fp-real", 8)
    with dbmod.get_connection() as c:
        c.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch, "
            "player2_arch, winner_arch, result, format, event_date, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("7", 1, "x", "y", "A1", "A2", "A1", "player1", "modern", "2026-11-01", "mtgmelee"),
        )
        c.commit()
    assert infer_bracket_matches("modern") == 0
    assert [r for r in _matches() if r["source"].startswith("bracket")] == []


def test_cleanup_deletes_league_bracket_rows_only():
    _event(8, "Modern League", "mtgo_league", "fp-cl-league", 8)
    _event(9, "Modern Challenge 32", "mtgo_challenge_32", "fp-cl-chal", 8)
    with dbmod.get_connection() as c:
        for eid in ("8", "9"):
            c.execute(
                "INSERT INTO matches (event_id, round, player1, player2, player1_arch, "
                "player2_arch, winner_arch, result, format, event_date, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, -1, "1st", "2nd", "A1", "A2", "A1", "player1", "modern", "2026-11-01", "bracket_finals"),
            )
        c.commit()
    assert cleanup_league_bracket_rows(dry_run=True) == 1     # the league one only
    assert cleanup_league_bracket_rows(dry_run=False) == 1
    left = {r["event_id"] for r in dbmod.get_connection().execute(
        "SELECT event_id FROM matches WHERE source LIKE 'bracket%'").fetchall()}
    assert left == {"9"}                                      # challenge bracket survives
