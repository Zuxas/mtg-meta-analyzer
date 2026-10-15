"""#29: archetype filters must match the exact name, not a substring.

`LIKE '%name%'` folded "Izzet Prowess Cauldron" into "Izzet Prowess" (and
"Eldrazi Tron" into "Tron"), doubling appearances, inflating trend share
and blending decklists. get_archetype_matchups had the mirror image: its
`NOT LIKE` dropped every opponent whose name contained the archetype's.
"""
import sqlite3
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def x_and_x_variant(tmp_path, monkeypatch):
    """Two events; each has 2 'Izzet Prowess' (card: Opt) and 2
    'Izzet Prowess Cauldron' (card: Cauldron) decks."""
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(dbm, "ARCHIVE_PATH", str(tmp_path / "x_arch.db"))
    dbm.init_db()
    from analysis import win_rates as wr
    wr._query_cache.clear()

    con = sqlite3.connect(dbm.DB_PATH)
    con.execute("INSERT INTO cards (name) VALUES ('Opt'), ('Cauldron')")
    cards = dict(con.execute("SELECT name, id FROM cards"))
    n = 0
    for e in range(2):
        con.execute(
            "INSERT INTO events (source_id, source, name, date, format,"
            " event_type, url) VALUES (?,?,?,?,?,?,?)",
            (f"e{e}", "mtgtop8", f"Event {e}",
             (datetime.now() - timedelta(days=e)).strftime("%Y-%m-%d"),
             "standard", "mtgo_challenge_32", f"http://e/{e}"))
        eid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        for place, arch, card in ((1, "Izzet Prowess", "Opt"),
                                  (2, "Izzet Prowess Cauldron", "Cauldron"),
                                  (3, "Izzet Prowess", "Opt"),
                                  (4, "Izzet Prowess Cauldron", "Cauldron")):
            n += 1
            con.execute(
                "INSERT INTO decks (event_id, source_id, player, archetype,"
                " placement, url) VALUES (?,?,?,?,?,?)",
                (eid, f"d{n}", f"P{n}", arch, place, f"http://d/{n}"))
            did = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO deck_cards (deck_id, card_id, quantity)"
                        " VALUES (?,?,4)", (did, cards[card]))
    con.commit()
    con.close()


def test_stats_count_only_the_exact_archetype(x_and_x_variant):
    from analysis.win_rates import get_archetype_stats
    assert get_archetype_stats("Izzet Prowess", "standard")["appearances"] == 4


def test_match_is_case_insensitive(x_and_x_variant):
    from analysis.win_rates import get_archetype_stats
    assert get_archetype_stats("izzet prowess", "standard")["appearances"] == 4


def test_trend_share_is_not_inflated(x_and_x_variant):
    from analysis.win_rates import get_archetype_trend
    weeks = [w for w in get_archetype_trend("Izzet Prowess", "standard", weeks=4)
             if w["appearances"]]
    assert sum(w["appearances"] for w in weeks) == 4
    assert all(w["meta_share"] == 0.5 for w in weeks)


def test_average_deck_does_not_blend_the_variant(x_and_x_variant):
    from analysis.deck_analysis import get_average_deck
    avg = get_average_deck("Izzet Prowess", "standard", min_inclusion=0.0)
    names = {c["name"] for c in avg["mainboard"]} if isinstance(avg, dict) else set()
    assert names == {"Opt"}


def test_matchups_keep_opponents_whose_name_contains_ours(x_and_x_variant):
    from analysis.win_rates import get_archetype_matchups
    opps = {m["opponent"] for m in get_archetype_matchups(
        "Izzet Prowess", "standard", min_shared_events=1)}
    assert "Izzet Prowess Cauldron" in opps
