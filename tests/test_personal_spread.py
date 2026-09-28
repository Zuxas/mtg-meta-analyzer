import sqlite3

import pytest

from analysis import personal_spread as ps


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE saved_decks (id INTEGER PRIMARY KEY, name TEXT, archetype TEXT);
        CREATE TABLE match_log (id INTEGER PRIMARY KEY, my_deck TEXT, my_deck_id INT,
            opp_deck TEXT, result TEXT, play_draw TEXT, format TEXT, event_name TEXT);
        INSERT INTO saved_decks VALUES (2, 'Boros Energy', 'Boros Energy');
    """)
    rows = []
    # 6 games vs Tron (1-5), mixed events; 2 vs Amulet (2-0); 3 unknown (2-1)
    for i, (res, pd) in enumerate([("loss", "play"), ("loss", "draw"), ("loss", "draw"),
                                    ("win", "play"), ("loss", "play"), ("loss", "draw")]):
        rows.append(("Boros Energy", None, "Green Tron", res, pd, "modern",
                     "MTGO Casual" if i < 2 else "Modern Challenge 32"))
    rows += [("", 2, "Amulet Titan", "win", "play", "modern", "MTGO Modern League")] * 2
    rows += [("Boros Energy", None, "", r, "play", "modern", "MTGO Casual") for r in ("win", "win", "loss")]
    rows += [("Boros Energy", None, "Burn", "win", "play", "pioneer", "x")]
    rows += [("5C Humans", None, "Burn", "win", "play", "pioneer", "x")]
    rows += [("Boros Energy", None, "Burn", "incomplete", "play", "modern", "x")]
    c.executemany("INSERT INTO match_log (my_deck, my_deck_id, opp_deck, result, play_draw, format, event_name) "
                  "VALUES (?,?,?,?,?,?,?)", rows)
    return c


def test_kpis_count_text_and_id_linked_rows(con):
    s = ps.matchup_spread(con, "Boros Energy", "modern", meta_wrs={})
    k = s["kpis"]
    assert (k["wins"], k["losses"], k["matches"]) == (5, 6, 11)   # incomplete excluded
    assert k["play_n"] == 8 and k["draw_n"] == 3


def test_unknown_opponents_are_separate_and_never_rated(con):
    s = ps.matchup_spread(con, "Boros Energy", "modern", meta_wrs={})
    assert s["unknown"] == {"wins": 2, "losses": 1, "n": 3, "wr": 2 / 3}
    assert all(r["opponent"] for r in s["rows"])


def test_advice_only_with_enough_games(con):
    s = ps.matchup_spread(con, "Boros Energy", "modern", meta_wrs={})
    rows = {r["opponent"]: r for r in s["rows"]}
    assert rows["Green Tron"]["severity"] == "low" and "no meta baseline" in rows["Green Tron"]["note"]
    assert rows["Amulet Titan"]["severity"] is None and rows["Amulet Titan"]["note"] == "small sample"
    assert s["rows"][0]["opponent"] == "Green Tron"      # rated rows first


def test_meta_baseline_drives_severity(con):
    s = ps.matchup_spread(con, "Boros Energy", "modern", meta_wrs={"Green Tron": 0.45})
    tron = next(r for r in s["rows"] if r["opponent"] == "Green Tron")
    assert tron["severity"] == "critical" and "vs meta (45%)" in tron["note"]


def test_competitive_only_drops_casual_games(con):
    s = ps.matchup_spread(con, "Boros Energy", "modern", competitive_only=True, meta_wrs={})
    assert s["kpis"]["matches"] == 6          # 2 casual Tron + 3 casual unknown dropped
    assert s["unknown"] is None
    tron = next(r for r in s["rows"] if r["opponent"] == "Green Tron")
    assert tron["n"] == 4 and tron["severity"] is None


def test_all_formats_never_looks_up_meta(con, monkeypatch):
    import analysis.matchup_advisor as ma
    monkeypatch.setattr(ma, "_get_meta_wrs", lambda *a: pytest.fail("meta lookup on 'All'"))
    s = ps.matchup_spread(con, "Boros Energy", None)
    assert s["kpis"]["matches"] == 12 and s["has_meta"] is False


def test_deck_choices_merge_text_and_saved_decks(con):
    assert ps.deck_choices(con) == [("Boros Energy", 12), ("5C Humans", 1)]
