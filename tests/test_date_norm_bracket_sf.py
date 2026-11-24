"""#19: date normalization in the melee scraper + date-windowed queries, and
the removal of guessed `bracket_sf` rows.

Runs against the per-test empty tmp DB (tests/conftest.py::_no_live_db).
"""
from datetime import datetime

import pytest

import db.database as dbmod
import scrapers.mtgmelee_scraper as ms
from db.matches_queries import get_matches
from analysis.ratings import compute_archetype_ratings


@pytest.fixture(autouse=True)
def _schema():
    dbmod.init_db()


def _match(eid, p1a, p2a, win, date, fmt="modern", source="mtgmelee"):
    with dbmod.get_connection() as c:
        c.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch, "
            "player2_arch, winner_arch, result, format, event_date, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, 1, "x", "y", p1a, p2a, win,
             "player1" if win == p1a else "player2", fmt, date, source),
        )
        c.commit()


# --- _normalise_date: DD/MM order + two-digit year (was %m/%d-first) ---

def test_normalise_date_reads_day_month_order():
    assert ms._normalise_date("05/03/2026") == "2026-03-05"   # 5 March, not 3 May


def test_normalise_date_two_digit_year():
    assert ms._normalise_date("21/03/24") == "2024-03-21"


def test_normalise_date_iso_passthrough_and_raw_on_failure():
    assert ms._normalise_date("2026-11-01") == "2026-11-01"
    assert ms._normalise_date("not a date") == "not a date"


# --- get_matches: normalized column, so a dd/mm row can't leak into a window ---

def test_get_matches_excludes_old_ddmmyy_row_from_window():
    _match("e1", "A", "B", "A", "21/03/24")          # really 2024-03-21, OLD
    _match("e2", "C", "D", "C", "2026-07-01")         # in window
    got = get_matches("modern", since=datetime(2026, 6, 1))
    dates = {m["event_date"] for m in got}
    assert dates == {"2026-07-01"}                    # the dd/mm row is excluded


# --- ratings: same window guard feeding the Dashboard ---

def test_ratings_window_excludes_old_ddmmyy_row():
    # The only match is an old dd/mm row; a 2026 window must see nothing.
    _match("e3", "A", "B", "A", "21/03/24")
    ratings = compute_archetype_ratings("modern", since=datetime(2026, 6, 1),
                                        min_matches=1)
    assert ratings == []


# --- bracket_sf no longer produced; date_health counts ---

def test_date_health_counts_non_iso_and_bracket():
    _match("e4", "A", "B", "A", "21/03/24")                       # non-ISO
    _match("e5", "C", "D", "C", "2026-07-01")                     # ISO
    _match("e6", "1st", "2nd", "1st", "2026-07-01", source="bracket_finals")
    out = ms.date_health("modern")
    assert out == {"non_iso": 1, "bracket_finals": 1, "bracket_sf": 0}
