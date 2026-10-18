"""#9: testing gauntlet from the current metagame -- deterministic selection,
weight normalization, alias merging, representative-list policy and the
saved snapshot."""
import json
from datetime import date, datetime, timedelta

import pytest

from analysis import gauntlet as gt

TODAY = date(2026, 10, 17)


@pytest.fixture
def con():
    from db.database import get_connection, init_db
    init_db()
    c = get_connection()
    yield c
    c.close()


_ids = {"event": 0, "deck": 0}


def _deck(c, arch, days_ago, placement=1, main=60, side=15, fmt="modern"):
    """One event holding one deck with `main` / `side` cards."""
    _ids["event"] += 1
    _ids["deck"] += 1
    d = (TODAY - timedelta(days=days_ago)).isoformat()
    ev = c.execute("INSERT INTO events (source_id, source, name, date, format, url) "
                   "VALUES (?, 'test', ?, ?, ?, ?)",
                   (f"e{_ids['event']}", f"Event {_ids['event']}", d, fmt,
                    f"https://example.test/e{_ids['event']}")).lastrowid
    dk = c.execute("INSERT INTO decks (event_id, source_id, player, archetype, placement, url) "
                   "VALUES (?, ?, ?, ?, ?, ?)",
                   (ev, f"d{_ids['deck']}", f"P{_ids['deck']}", arch, placement,
                    f"https://example.test/d{_ids['deck']}")).lastrowid
    for qty, sb, name in ((main, 0, f"{arch} Main Card"), (side, 1, f"{arch} Side Card")):
        if qty:
            c.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (name,))
            cid = c.execute("SELECT id FROM cards WHERE name = ?", (name,)).fetchone()[0]
            c.execute("INSERT INTO deck_cards VALUES (?, ?, ?, ?)", (dk, cid, qty, sb))
    c.commit()
    return dk


def _field(c, counts, days_ago=3):
    for arch, n in counts.items():
        for i in range(n):
            _deck(c, arch, days_ago + (i % 5), placement=i + 1)


def _build(c, **kw):
    kw.setdefault("today", TODAY)
    return gt.build_gauntlet("modern", con=c, **kw)


def _sel(g):
    return [e["archetype"] for e in g["entries"] if e["selected"]]


# --- selection ---------------------------------------------------------------

def test_top_by_share_with_deterministic_ties(con):
    _field(con, {"Boros Energy": 40, "Zoo": 25, "Amulet Titan": 25, "Alpha Deck": 25, "Tron": 10})
    g = _build(con, size=3, min_share=0.0)
    assert _sel(g) == ["Boros Energy", "Alpha Deck", "Amulet Titan"]   # ties by name
    again = _build(con, size=3, min_share=0.0)
    assert json.dumps(again, sort_keys=True) == json.dumps(g, sort_keys=True)


def test_min_share_and_excludes_fill_from_the_rest(con):
    _field(con, {"Boros Energy": 60, "Zoo": 30, "Tron": 9, "Beta Deck": 1})
    g = _build(con, size=3, min_share=0.05, exclude=["boros energy"])
    assert _sel(g) == ["Zoo", "Tron"]          # Beta Deck is under 5%, Boros excluded
    assert len(g["entries"]) == 4              # the full pool stays available


def test_includes_go_first_and_may_exceed_size(con):
    _field(con, {"Boros Energy": 60, "Zoo": 30, "Tron": 10})
    g = _build(con, size=2, include=["Tron", "Living End", "Zoo"], exclude=["Zoo"])
    assert set(_sel(g)) == {"Tron", "Living End", "Zoo"}   # include beats exclude
    absent = next(e for e in g["entries"] if e["archetype"] == "Living End")
    assert absent["share"] == 0 and "not in the field data" in absent["warnings"][0]
    assert any("exceed the field size" in w for w in g["warnings"])


# --- weights -----------------------------------------------------------------

def test_weights_normalize_and_overrides_are_relative(con):
    _field(con, {"Boros Energy": 60, "Zoo": 30, "Tron": 10})
    g = _build(con, size=3, min_share=0.0)
    w = {e["archetype"]: e["weight"] for e in g["entries"]}
    assert w == pytest.approx({"Boros Energy": 0.6, "Zoo": 0.3, "Tron": 0.1})
    assert sum(g["field"].values()) == pytest.approx(100, abs=0.2)
    assert list(g["field"]) == ["Boros Energy", "Zoo", "Tron"]       # mtg-sim get_field shape

    gt.reweight(g, weights={"Tron": 0.6})       # Tron 0.6 vs Boros 0.6 vs Zoo 0.3
    assert g["field"]["Tron"] == g["field"]["Boros Energy"] == pytest.approx(40.0)
    assert g["observed_field"]["Tron"] == pytest.approx(10.0)

    gt.reweight(g, selected=["Zoo", "Tron"], weights={"Zoo": 0, "Tron": 0})
    assert g["field"] == {"Tron": 50.0, "Zoo": 50.0}                   # all zero -> equal
    assert next(e for e in g["entries"] if e["archetype"] == "Boros Energy")["weight"] == 0


# --- alias merging -----------------------------------------------------------

def test_stored_aliases_merge_without_double_counting(con):
    _field(con, {"Merfolks": 20, "Merfolk": 30, "Zoo": 50})
    ranked, source, total = gt.field_shares("modern", TODAY - timedelta(days=13), TODAY)
    assert source == "decks" and total == 100
    fish = next(m for m in ranked if m["archetype"] == "Merfolk")
    assert fish["appearances"] == 50 and fish["share"] == pytest.approx(0.5)
    assert fish["aliases"] == ["Merfolks"]
    assert sum(m["share"] for m in ranked) == pytest.approx(1.0)


# --- representative lists ----------------------------------------------------

def test_newest_list_beats_an_older_better_finish(con):
    _field(con, {"Zoo": 120})
    old_win = _deck(con, "Tron", 10, placement=1)
    new_ninth = _deck(con, "Tron", 2, placement=9)
    g = _build(con, include=["Tron"])
    tron = next(e for e in g["entries"] if e["archetype"] == "Tron")
    assert tron["decklist"]["deck_id"] == new_ninth != old_win
    assert tron["decklist"]["text"].startswith("60 Tron Main Card")
    assert "Sideboard\n15 Tron Side Card" in tron["decklist"]["text"]
    assert tron["decklist"]["event_date"] == (TODAY - timedelta(days=2)).isoformat()


def test_old_lists_are_never_used_silently(con):
    _field(con, {"Zoo": 120})
    _deck(con, "Tron", 90)
    tron = lambda g: next(e for e in g["entries"] if e["archetype"] == "Tron")  # noqa: E731
    g = _build(con, include=["Tron"])
    assert tron(g)["decklist"] is None
    assert "no decklist in the window" in tron(g)["warnings"][-1]
    g = _build(con, include=["Tron"], allow_stale=True)
    assert tron(g)["decklist"] is not None
    assert any("outside the window" in w for w in tron(g)["warnings"])
    assert any("90 days old" in w for w in tron(g)["warnings"])


def test_incomplete_and_sideboardless_lists_warn(con):
    _field(con, {"Zoo": 120})
    _deck(con, "Tron", 1, main=40, side=0)
    g = _build(con, include=["Tron"])
    w = next(e for e in g["entries"] if e["archetype"] == "Tron")["warnings"]
    assert "incomplete list: 40 main-deck cards" in w and "no sideboard recorded" in w


# --- snapshot ----------------------------------------------------------------

def test_save_never_overwrites_and_load_checks_the_hash(con, tmp_path):
    _field(con, {"Boros Energy": 60, "Zoo": 40})
    g = _build(con, size=2)
    now = datetime(2026, 10, 17, 21, 5, 0)
    p1 = gt.save_gauntlet(g, str(tmp_path), now=now)
    p2 = gt.save_gauntlet(g, str(tmp_path), now=now)
    assert p1.endswith("modern-20261017-210500.json") and p2.endswith("-2.json")
    loaded = gt.load_gauntlet(p1)
    assert loaded["schema"] == gt.SCHEMA and loaded["field"] == g["field"]
    assert loaded["window"] == {"since": "2026-10-04", "until": "2026-10-17", "days": 14}

    data = json.loads(open(p1, encoding="utf-8").read())
    data["field"]["Zoo"] = 99.0
    open(p1, "w", encoding="utf-8").write(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"):
        gt.load_gauntlet(p1)


def test_default_dir_is_beside_the_database(monkeypatch, tmp_path):
    from db import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "mtg_meta.db"))
    assert gt.default_dir() == str(tmp_path / "gauntlets")


# --- GUI ---------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_tab_edits_reweight_and_save(app, con, tmp_path, monkeypatch):
    from PyQt6.QtCore import Qt
    from gui.tabs.gauntlet import C_PCT, C_TEST, C_WEIGHT, GauntletTab
    _field(con, {"Boros Energy": 60, "Zoo": 30, "Tron": 10})
    monkeypatch.setattr(gt, "default_dir", lambda: str(tmp_path))
    tab = GauntletTab()
    try:
        tab.show_gauntlet(_build(con, size=3, min_share=0.0))
        rows = {tab._table.item(r, 1).text(): r for r in range(tab._table.rowCount())}
        assert tab._table.item(rows["Boros Energy"], C_PCT).text() == "60.0%"

        tab._table.item(rows["Boros Energy"], C_TEST).setCheckState(Qt.CheckState.Unchecked)
        assert tab._table.item(rows["Zoo"], C_PCT).text() == "75.0%"
        assert tab._table.item(rows["Boros Energy"], C_PCT).text() == ""

        tab._table.item(rows["Tron"], C_WEIGHT).setText("30")      # same as Zoo now
        assert tab._table.item(rows["Tron"], C_PCT).text() == "50.0%"

        msg = tab.save()
        assert msg.startswith("Saved: ")
        saved = gt.load_gauntlet(msg[len("Saved: "):])
        assert saved["field"] == {"Tron": 50.0, "Zoo": 50.0}
        assert saved["entries"][0]["archetype"] == "Boros Energy"   # kept, not selected
        assert saved["entries"][0]["selected"] is False
    finally:
        tab.cleanup()
        tab.deleteLater()
        app.processEvents()


def test_tab_is_before_hypotheses_in_tournament_prep(app):
    from gui.tabs.tournament_prep import TournamentPrepTab
    tp = TournamentPrepTab()
    try:
        labels = [tp._inner.tabText(i) for i in range(tp._inner.count())]
        assert labels[-2:] == ["GAUNTLET", "HYPOTHESES"]
    finally:
        tp.cleanup()
        tp.deleteLater()
        app.processEvents()
