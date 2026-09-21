"""Per-format data freshness guard (CHAPIN_METRICS.md Task 1 / Bug 3, 2026-09-20).

`data/scrape_state.json` held one global `last_status: ok` while the `matches`
table had had zero Modern rows for ten weeks. A format-specific stall was
invisible on the format used for RC prep. Two defects, both covered here:

1. `matches.event_date` / `events.date` mix `YYYY-MM-DD` and `dd/mm/yy`, so any
   MAX() or `>=` string comparison spanning both is wrong.
2. Freshness must be derived PER FORMAT from the rows that actually exist.
"""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from db.helpers import SQL_NORM_DATE, normalize_event_date


# ---------------------------------------------------------------------------
# normalize_event_date -- Python side
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("2026-03-14", "2026-03-14"),
    ("2026-03-14T18:30:00", "2026-03-14"),      # ISO with time suffix
    ("18/03/26", "2026-03-18"),                  # MTGTop8 dd/mm/yy
    ("01/02/24", "2024-02-01"),                  # day/month, NOT month/day
    ("18/03/2026", "2026-03-18"),                # dd/mm/yyyy tolerated
    ("31/13/24", None),                          # impossible month
    ("2026-13-40", None),
    ("garbage", None),
    ("", None),
    (None, None),
    (20260314, None),                            # wrong type is junk, not a crash
])
def test_normalize_event_date(raw, expected):
    assert normalize_event_date(raw) == expected


# ---------------------------------------------------------------------------
# SQL_NORM_DATE -- SQLite side, must agree with the Python side
# ---------------------------------------------------------------------------

def test_sql_norm_date_yields_iso_for_both_shapes_and_orders_correctly():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (d TEXT)")
    con.executemany("INSERT INTO t VALUES (?)",
                    [("2026-03-14",), ("18/03/26",), ("01/02/24",), ("2024-10-12",)])
    expr = SQL_NORM_DATE.format(col="d")
    rows = con.execute(f"SELECT d, {expr} FROM t").fetchall()
    assert dict(rows) == {
        "2026-03-14": "2026-03-14", "18/03/26": "2026-03-18",
        "01/02/24": "2024-02-01", "2024-10-12": "2024-10-12",
    }
    # The whole point: MAX/ordering across mixed shapes is right.
    assert con.execute(f"SELECT MAX({expr}) FROM t").fetchone()[0] == "2026-03-18"
    # A raw string MAX gets it wrong ('2026-03-14' > '18/03/26' lexically),
    # which is the bug this constant exists to kill.
    assert con.execute("SELECT MAX(d) FROM t").fetchone()[0] == "2026-03-14"
    for raw, norm in rows:
        assert normalize_event_date(raw) == norm


# ---------------------------------------------------------------------------
# format_freshness
# ---------------------------------------------------------------------------

TODAY = date(2026, 9, 20)


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _slash(days_ago: int) -> str:
    d = TODAY - timedelta(days=days_ago)
    return d.strftime("%d/%m/%y")


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE matches (format TEXT, event_date TEXT, result TEXT)")
    con.execute("CREATE TABLE events (format TEXT, date TEXT)")
    return con


def _seed(con, fmt, match_days, event_days=(), slash=False):
    f = _slash if slash else _iso
    con.executemany("INSERT INTO matches VALUES (?,?,?)",
                    [(fmt, f(d), "player1") for d in match_days])
    con.executemany("INSERT INTO events VALUES (?,?)",
                    [(fmt, f(d)) for d in event_days])


def test_format_freshness_classifies_fresh_stale_dead(con):
    from analysis.data_health import format_freshness
    _seed(con, "modern",   match_days=[3, 5, 8, 12, 40, 45], event_days=[2])
    _seed(con, "standard", match_days=[15, 20, 35], event_days=[14], slash=True)  # dd/mm/yy only
    _seed(con, "pioneer",  match_days=[120, 130], event_days=[118])
    _seed(con, "legacy",   match_days=[], event_days=[4])                         # events but no matches

    fr = format_freshness(con=con, today=TODAY)

    m = fr["modern"]
    assert m["status"] == "fresh"
    assert m["last_match_date"] == _iso(3)
    assert m["last_event_date"] == _iso(2)
    assert m["days_stale"] == 3
    assert m["matches_30d"] == 4
    assert m["matches_prev_30d"] == 2

    s = fr["standard"]
    assert s["status"] == "stale"
    assert s["last_match_date"] == _iso(15)       # normalized, never '15/09/26'
    assert s["days_stale"] == 15
    assert s["matches_30d"] == 2 and s["matches_prev_30d"] == 1

    p = fr["pioneer"]
    assert p["status"] == "dead"
    assert p["days_stale"] == 120
    assert p["matches_30d"] == 0 and p["matches_prev_30d"] == 0

    lg = fr["legacy"]
    assert lg["status"] == "dead"
    assert lg["last_match_date"] is None
    assert lg["last_event_date"] == _iso(4)
    assert lg["days_stale"] is None


def test_format_freshness_ignores_row_with_junk_date_for_max(con):
    from analysis.data_health import format_freshness
    _seed(con, "modern", match_days=[9])
    con.execute("INSERT INTO matches VALUES ('modern', 'not a date', 'player1')")
    con.execute("INSERT INTO matches VALUES ('modern', '99/99/99', 'player1')")
    fr = format_freshness(con=con, today=TODAY)
    assert fr["modern"]["last_match_date"] == _iso(9)
    assert fr["modern"]["status"] == "fresh"


def test_format_freshness_boundaries(con):
    from analysis.data_health import format_freshness
    _seed(con, "a", match_days=[9])     # < 10  -> fresh
    _seed(con, "b", match_days=[10])    # 10..30 -> stale
    _seed(con, "c", match_days=[30])
    _seed(con, "d", match_days=[31])    # > 30 -> dead
    fr = format_freshness(con=con, today=TODAY)
    assert [fr[k]["status"] for k in "abcd"] == ["fresh", "stale", "stale", "dead"]


def test_format_freshness_default_formats_are_union_of_both_tables(con):
    from analysis.data_health import format_freshness
    _seed(con, "Modern", match_days=[1])          # mixed case in the DB
    _seed(con, "legacy", match_days=[], event_days=[1])
    assert set(format_freshness(con=con, today=TODAY)) == {"modern", "legacy"}


def test_format_freshness_explicit_formats_include_ones_with_no_rows(con):
    from analysis.data_health import format_freshness
    _seed(con, "modern", match_days=[1])
    fr = format_freshness(["modern", "pioneer"], con=con, today=TODAY)
    assert fr["pioneer"] == {
        "last_match_date": None, "last_event_date": None,
        "matches_30d": 0, "matches_prev_30d": 0,
        "days_stale": None, "status": "dead",
    }


def test_format_freshness_empty_tables(con):
    from analysis.data_health import format_freshness
    assert format_freshness(con=con, today=TODAY) == {}


def test_describe_freshness_is_human_readable():
    from analysis.data_health import describe_freshness
    txt = describe_freshness("modern", {
        "last_match_date": "2026-09-17", "last_event_date": "2026-09-18",
        "matches_30d": 11218, "matches_prev_30d": 2910, "days_stale": 3, "status": "fresh",
    })
    assert "modern" in txt.lower() and "2026-09-17" in txt and "3 days" in txt
    assert "11,218" in txt
    none_txt = describe_freshness("pioneer", {
        "last_match_date": None, "last_event_date": None,
        "matches_30d": 0, "matches_prev_30d": 0, "days_stale": None, "status": "dead",
    })
    assert "no match data" in none_txt.lower()


# ---------------------------------------------------------------------------
# scrape_state.json -- per-format, backwards compatible
# ---------------------------------------------------------------------------

@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "scrape_state.json"


def test_old_shape_scrape_state_still_reads_and_serves_as_fallback(state_path):
    from db.scrape_state import format_scrape_state, read_scrape_state
    state_path.write_text(json.dumps({
        "last_updated": "2026-08-29T20:15:50", "last_status": "ok", "balloon_shown": True,
    }), encoding="utf-8")
    assert read_scrape_state(path=state_path)["last_status"] == "ok"
    fs = format_scrape_state("modern", path=state_path)
    assert fs["last_updated"] == "2026-08-29T20:15:50"
    assert fs["last_status"] == "ok"
    assert fs["scope"] == "global"     # caller can tell it is NOT format-specific


def test_write_scrape_state_per_format_keeps_global_keys(state_path):
    from db.scrape_state import format_scrape_state, read_scrape_state, write_scrape_state
    state_path.write_text(json.dumps({"balloon_shown": True, "last_status": "ok",
                                      "last_updated": "2026-08-29T20:15:50"}), encoding="utf-8")
    write_scrape_state(status="error", error="melee 503", fmt="modern", path=state_path)
    write_scrape_state(status="ok", fmt="legacy", path=state_path)

    raw = read_scrape_state(path=state_path)
    assert raw["balloon_shown"] is True                      # untouched
    assert raw["formats"]["modern"]["last_status"] == "error"
    assert raw["formats"]["modern"]["last_error"] == "melee 503"
    assert raw["formats"]["legacy"]["last_status"] == "ok"
    assert "last_error" not in raw["formats"]["legacy"]

    m = format_scrape_state("modern", path=state_path)
    assert m["scope"] == "format" and m["last_status"] == "error"
    # a format with no entry falls back to the global fields
    p = format_scrape_state("pioneer", path=state_path)
    assert p["scope"] == "global" and p["last_updated"] == "2026-08-29T20:15:50"

    # a later ok run clears the per-format error
    write_scrape_state(status="ok", fmt="modern", path=state_path)
    assert "last_error" not in read_scrape_state(path=state_path)["formats"]["modern"]


def test_write_scrape_state_without_fmt_updates_global_only(state_path):
    from db.scrape_state import read_scrape_state, write_scrape_state
    write_scrape_state(status="ok", fmt="modern", path=state_path)
    write_scrape_state(status="error", error="boom", path=state_path)
    raw = read_scrape_state(path=state_path)
    assert raw["last_status"] == "error" and raw["last_error"] == "boom"
    assert raw["formats"]["modern"]["last_status"] == "ok"


def test_missing_state_file_reads_as_empty(state_path):
    from db.scrape_state import format_scrape_state, read_scrape_state
    assert read_scrape_state(path=state_path) == {}
    assert format_scrape_state("modern", path=state_path) == {"scope": "global"}
