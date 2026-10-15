"""#23: meta_share must be a fraction of the whole field, not of the top-N.

get_meta_standings sorted by avg_points, trimmed to `top`, and only then
divided by the trimmed list's appearances. With the 3/3/12 field below,
top=2 reported Z 50% / Y 50% and dropped X (two thirds of the field).
"""
import sqlite3
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def field_3_3_12(tmp_path, monkeypatch):
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "f.db"))
    monkeypatch.setattr(dbm, "ARCHIVE_PATH", str(tmp_path / "f_arch.db"))
    dbm.init_db()
    from analysis import win_rates as wr
    wr._query_cache.clear()

    con = sqlite3.connect(dbm.DB_PATH)
    n = 0
    for e in range(10):
        con.execute(
            "INSERT INTO events (source_id, source, name, date, format,"
            " event_type, url) VALUES (?,?,?,?,?,?,?)",
            (f"e{e}", "mtgtop8", f"Event {e}",
             (datetime.now() - timedelta(days=e)).strftime("%Y-%m-%d"),
             "standard", "mtgo_challenge_32", f"http://e/{e}"))
        eid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Z places 1-3, Y 4-6, X 7-18 in every event.
        for arch, places in (("Z", range(1, 4)), ("Y", range(4, 7)),
                             ("X", range(7, 19))):
            for p in places:
                n += 1
                con.execute(
                    "INSERT INTO decks (event_id, source_id, player, archetype,"
                    " placement, url) VALUES (?,?,?,?,?,?)",
                    (eid, f"d{n}", f"P{n}", arch, p, f"http://d/{n}"))
    con.commit()
    con.close()


def _shares(rows):
    return {r["archetype"]: r["meta_share"] for r in rows}


@pytest.mark.parametrize("top", [1, 2, 3, 20])
@pytest.mark.parametrize("min_appearances", [1, 31])
def test_share_is_independent_of_top_and_min_appearances(field_3_3_12, top,
                                                          min_appearances):
    from analysis.win_rates import get_meta_standings
    rows = get_meta_standings("standard", top=top, min_appearances=min_appearances)
    expected = {"Z": 0.1667, "Y": 0.1667, "X": 0.6667}
    assert rows, "expected at least one archetype"
    for arch, share in _shares(rows).items():
        assert share == expected[arch]
    assert all(r["total_field"] == 180 for r in rows)


def test_sort_by_appearances_ranks_by_popularity(field_3_3_12):
    from analysis.win_rates import get_meta_standings
    by_points = get_meta_standings("standard", top=1, min_appearances=1)
    by_pop = get_meta_standings("standard", top=1, min_appearances=1,
                                sort_by="appearances")
    assert [r["archetype"] for r in by_points] == ["Z"]
    assert [r["archetype"] for r in by_pop] == ["X"]


def test_unknown_sort_by_is_rejected(field_3_3_12):
    from analysis.win_rates import get_meta_standings
    with pytest.raises(ValueError):
        get_meta_standings("standard", sort_by="share")
