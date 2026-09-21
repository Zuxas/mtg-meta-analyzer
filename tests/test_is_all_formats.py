"""Unit + regression tests for the cross-format sentinel helper."""
from analysis.win_rates import is_all_formats


def test_is_all_formats_none():
    assert is_all_formats(None) is True


def test_is_all_formats_empty_string():
    assert is_all_formats("") is True


def test_is_all_formats_whitespace():
    assert is_all_formats("   ") is True


def test_is_all_formats_all_lowercase():
    assert is_all_formats("all") is True


def test_is_all_formats_all_uppercase():
    assert is_all_formats("ALL") is True


def test_is_all_formats_all_formats_label():
    assert is_all_formats("All Formats") is True


def test_is_all_formats_any_paren_sentinel():
    assert is_all_formats("(any)") is True


def test_is_all_formats_any_bare():
    assert is_all_formats("any") is True


def test_is_all_formats_concrete_format():
    assert is_all_formats("standard") is False
    assert is_all_formats("modern") is False
    assert is_all_formats("Pioneer") is False


def test_regression_archetype_trend_all_returns_data():
    """Before the fix, fmt='all' produced WHERE format='all' which matched zero
    rows. Confirm cross-format trend now returns something."""
    from analysis.win_rates import get_archetype_trend
    rows_all = get_archetype_trend("Izzet Prowess", format_name="all", weeks=4)
    rows_std = get_archetype_trend("Izzet Prowess", format_name="standard", weeks=4)
    if rows_std:
        assert rows_all, (
            "fmt='all' should return at least as much data as fmt='standard' "
            "(since 'all' is a superset). Got 0 rows for 'all'."
        )


def test_matches_fallback_trend_honours_all_formats(monkeypatch):
    """`get_archetype_trend` falls back to `_archetype_trend_from_matches` when
    the decks table has no rows for the archetype. That fallback still filtered
    `format = 'all'` literally, so a thin decks table (Standard, 2026-09) made
    fmt='all' return nothing while fmt='standard' returned buckets."""
    import sqlite3
    from datetime import datetime, timedelta
    import db.database as dbm
    from analysis.win_rates import _archetype_trend_from_matches

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE matches (format TEXT, event_date TEXT, result TEXT,
                                         player1_arch TEXT, player2_arch TEXT)""")
    d1 = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    d2 = (datetime.now() - timedelta(days=5)).strftime("%d/%m/%y")   # mixed shapes on purpose
    con.executemany("INSERT INTO matches VALUES (?,?,?,?,?)", [
        ("standard", d1, "player1", "Izzet Prowess", "Mono Red Aggro"),
        ("modern",   d2, "player2", "Boros Energy",  "Izzet Prowess"),
    ])
    monkeypatch.setattr(dbm, "get_connection", lambda: con)

    std = _archetype_trend_from_matches("Izzet Prowess", "standard", 4, None, None, "weekly")
    every = _archetype_trend_from_matches("Izzet Prowess", "all", 4, None, None, "weekly")

    assert sum(b["appearances"] for b in std) == 1
    assert sum(b["appearances"] for b in every) == 2, "fmt='all' must span every format"
