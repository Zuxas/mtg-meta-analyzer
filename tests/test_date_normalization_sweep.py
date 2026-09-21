"""Date-normalization sweep (NEXT_STEPS #6, 2026-09-21).

`events.date` and `matches.event_date` mix `YYYY-MM-DD` and `dd/mm/yy` (the
guides sheet writes `dd/mm/yyyy`). Until this sweep every query site carried
its own inline `CASE WHEN instr(date,'/')>0 ...` copy emitting compact
`YYYYMMDD`, and every `since` literal next to it was `strftime("%Y%m%d")`.
`db.helpers.SQL_NORM_DATE` (ISO out, all three shapes) is now the ONE
expression; each site here is exercised end-to-end against a seeded DB so a
half-migration (ISO key, compact literal -> silently empty result) cannot
land.

Two kinds of assertion:
* characterization -- ISO + dd/mm/yy rows filter/order correctly (true before
  and after the sweep);
* the `dd/mm/yyyy` row -- the inline copies read its year as `'20'+'20'`
  (2020) and dropped or mis-sorted it, while `win_rates._parse_date` on the
  Python side accepts that shape. Real defect, small today (no such rows in
  events/matches yet), and the guides sheet already writes 4-digit years.

Every test runs against a tmp DB (`db.database.DB_PATH` monkeypatched); the
live DB is never opened.
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

TODAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _ago(days):
    return TODAY - timedelta(days=days)


def _iso(days):
    return _ago(days).strftime("%Y-%m-%d")


def _dmy(days):
    return _ago(days).strftime("%d/%m/%y")


def _dmY(days):
    return _ago(days).strftime("%d/%m/%Y")


# name -> (days ago, stored date string).  Newest first.
EVENTS = [
    ("A", 2,  _iso(2)),     # ISO
    ("B", 5,  _dmy(5)),     # dd/mm/yy
    ("C", 8,  _dmY(8)),     # dd/mm/yyyy  <- the defect row
    ("D", 40, _iso(40)),
    ("E", 45, _dmy(45)),
]
IN_10D = ["A", "B", "C"]


@pytest.fixture
def mixed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mixed.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    monkeypatch.setattr("analysis.scout.CENTRAL_DB_PATH", str(db_path))
    from db.database import init_db, upsert_event, upsert_deck, insert_deck_cards, get_connection
    from db.matches_queries import _ensure_table
    init_db()
    _ensure_table()

    ids = {}
    decks = {}
    for i, (name, days, date_str) in enumerate(EVENTS):
        eid = upsert_event(source="mtgtop8", source_id=f"ev{name}", name=f"Modern Challenge {name}",
                           date=date_str, fmt="modern", url=f"http://x/{name}",
                           event_type="mtgo_challenge_32")
        ids[name] = eid
        for placement, arch in ((1, "Prowess"), (2, "Energy")):
            did = upsert_deck(event_id=eid, source_id=f"dk{name}{placement}", player=f"pilot_{name}{placement}",
                              archetype=arch, placement=placement, url=f"http://x/{name}/{placement}")
            decks[(name, arch)] = did
            # quantities vary per deck so the deck-fingerprint dedup stays quiet
            insert_deck_cards(did, {"Lightning Bolt": 4, "Mountain": 10 + i + placement}, {})

    with get_connection() as con:
        # matches: same five dates shifted by one day, Prowess beats Energy
        con.executemany(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch, player2_arch, "
            "winner_arch, result, format, event_date, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(f"m{name}", 1, "p1", "p2", "Prowess", "Energy", "Prowess", "player1", "modern", d, "mtgmelee")
             for name, d in (("A", _iso(3)), ("B", _dmy(6)), ("C", _dmY(9)), ("D", _iso(41)), ("E", _dmy(46)))])
        # guides: the sheet writes dd/mm/yyyy; one ISO row to prove both sort together
        con.executemany(
            "INSERT INTO guides (date, url, format, archetype, type, author, source, comment, added_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(_dmY(1),  "http://g/new", "modern", "Prowess", "primer", "new",  "sheet", "", _iso(0)),
             (_iso(10), "http://g/mid", "modern", "Prowess", "primer", "mid",  "sheet", "", _iso(0)),
             (_dmY(30), "http://g/old", "modern", "Prowess", "primer", "old",  "sheet", "", _iso(0))])
        # two sources, same fingerprint -> a cross-source duplicate group
        con.execute("UPDATE events SET event_fingerprint_cs='dup1' WHERE id IN (?,?)", (ids["A"], ids["B"]))
        con.execute("INSERT INTO events (source_id, source, name, date, format, event_type, url, event_fingerprint_cs) "
                    "VALUES ('mdA','mtgdecks','Modern Challenge A',?,'modern','mtgo_challenge_32','http://y/A','dup1')",
                    (_dmy(2),))
        ids["A_dup"] = con.execute("SELECT id FROM events WHERE source_id='mdA'").fetchone()[0]
    return {"path": db_path, "ids": ids, "decks": decks}


def _event_names(rows, key="event_name"):
    return [r[key][-1] for r in rows]


# ---------------------------------------------------------------------------
# analysis/win_rates.py  (_DATE_KEY / _MATCH_DATE_KEY / _dt_to_db_str)
# ---------------------------------------------------------------------------

def test_archetype_stats_window_spans_all_date_shapes(mixed_db):
    from analysis.win_rates import get_archetype_stats
    s = get_archetype_stats("Prowess", "modern", since=_ago(10))
    assert s["appearances"] == 3 and s["unique_events"] == 3
    s = get_archetype_stats("Prowess", "modern", since=_ago(10), until=_ago(4))
    assert s["appearances"] == 2                       # B (dd/mm/yy) + C (dd/mm/yyyy)


def test_fetch_appearances_orders_newest_first_across_shapes(mixed_db):
    from analysis.win_rates import _fetch_appearances
    from db.database import get_connection
    with get_connection() as con:
        rows = _fetch_appearances(con, "Prowess", "modern", None, None, None)
    assert [r["event_name"][-1] for r in rows] == ["A", "B", "C", "D", "E"]


def test_real_archetype_and_matchup_winrates_since_spans_all_shapes(mixed_db):
    from analysis.win_rates import get_real_archetype_winrates, get_real_matchup_winrates
    wr = get_real_archetype_winrates("modern", since=_ago(10), min_matches=1)
    assert wr["Prowess"]["total"] == 3 and wr["Prowess"]["wins"] == 3
    mm = get_real_matchup_winrates("modern", since=_ago(10), min_matches=1, min_arch_appearances=1)
    assert mm["Energy"]["Prowess"]["total"] == 3          # keyed arch_a < arch_b


def test_parse_match_date_handles_all_shapes():
    from analysis.win_rates import _parse_match_date
    assert _parse_match_date("2026-03-14") == datetime(2026, 3, 14)
    assert _parse_match_date("18/03/26") == datetime(2026, 3, 18)
    assert _parse_match_date("18/03/2026") == datetime(2026, 3, 18)
    assert _parse_match_date("garbage") is None and _parse_match_date("") is None


# ---------------------------------------------------------------------------
# analysis/card_adoption.py  (SQL key escapes into Python bucket comparisons)
# ---------------------------------------------------------------------------

def test_card_adoption_buckets_all_shapes(mixed_db):
    from analysis.card_adoption import get_card_adoption
    out = get_card_adoption("Prowess", "modern", weeks=2, min_inclusion=0.0)
    # bucket [14d..7d) holds only C (dd/mm/yyyy); [7d..0) holds A + B -> 2 buckets
    assert len(out["weeks"]) == 2
    bolt = next(c for c in out["cards"] if c["name"] == "Lightning Bolt")
    assert bolt["rates"] == [1.0, 1.0]


def test_card_trend_counts_all_shapes(mixed_db):
    from analysis.card_adoption import get_card_trend
    out = get_card_trend("Lightning Bolt", "modern", weeks=2)
    assert out["total_decks"] == 6 and out["total_inclusions"] == 6
    assert out["deck_counts"] == [2, 4]


# ---------------------------------------------------------------------------
# analysis/scout.py
# ---------------------------------------------------------------------------

def test_scout_priority_finishers_window_and_order(mixed_db):
    from analysis.scout import get_priority_finishers
    rows = get_priority_finishers(["Prowess"], days=10, format_name="modern", db_path=mixed_db["path"])
    assert [r["event_name"][-1] for r in rows] == ["A", "B", "C"]


def test_scout_pilot_history_window(mixed_db):
    from analysis.scout import get_pilot_history
    rows = get_pilot_history("pilot_C1", format_name="modern", days=10, db_path=mixed_db["path"])
    assert len(rows) == 1 and rows[0]["event_name"].endswith("C")
    assert get_pilot_history("pilot_D1", format_name="modern", days=10, db_path=mixed_db["path"]) == []


# ---------------------------------------------------------------------------
# GUI loaders (pure functions, no widgets)
# ---------------------------------------------------------------------------

def test_dashboard_recent_finishes_window_and_order(mixed_db):
    from gui.tabs.dashboard import _load_panel_data
    recent = _load_panel_data("modern", since_dt=_ago(10), top=10)["recent"]
    assert [(r["event_name"][-1], r["placement"]) for r in recent] == \
        [("A", 1), ("A", 2), ("B", 1), ("B", 2), ("C", 1), ("C", 2)]


def test_archetype_detail_decks_window_and_guides_order(mixed_db):
    from gui.widgets.archetype_detail import _load_archetype_data
    data = _load_archetype_data("Prowess", "modern", since_dt=_ago(10))
    assert data["deck_count"] == 3
    guides = [r["title"] for r in data["resources"] if r["origin"] == "guide"]
    assert guides == ["new", "mid", "old"]


def test_ask_claude_meta_context_counts_all_shapes(mixed_db):
    from gui.tabs.ask_claude import _fetch_meta_context
    txt = _fetch_meta_context("modern")
    assert "**Prowess** — 3 top finishes" in txt


def test_set_analysis_meta_context_counts_all_shapes(mixed_db):
    from gui.tabs.set_analysis import _build_meta_context
    txt = _build_meta_context("modern")
    assert "**Prowess** — 3 appearances" in txt


def test_search_deck_sql_accepts_iso_bounds(mixed_db):
    from gui.tabs.search import _deck_search_sql
    from db.database import get_connection
    sql, params = _deck_search_sql("modern", query="Prowess", max_placement=None,
                                   date_from=_iso(10), date_to=_iso(4),
                                   player_q="", card_names=[], any_card_names=[])
    with get_connection() as con:
        rows = con.execute(sql, params).fetchall()
    assert [r["event_name"][-1] for r in rows] == ["B", "C"]


# ---------------------------------------------------------------------------
# ORDER BY-only sites
# ---------------------------------------------------------------------------

def test_deck_analysis_recent_event_and_search_order(mixed_db):
    from analysis.deck_analysis import get_recent_event, search_decks
    assert get_recent_event("modern")["name"].endswith("A")
    rows = search_decks(archetype="Prowess", format_name="modern", limit=10)
    assert [r["event_name"][-1] for r in rows] == ["A", "B", "C", "D", "E"]


def test_challenges_latest_is_newest_across_shapes(mixed_db):
    from scrapers.challenges import get_latest_challenge
    assert get_latest_challenge("modern", "mtgo_challenge_32")["name"].endswith("A")


def test_cross_source_dedup_lists_newest_event_first_in_group(mixed_db):
    from analysis.cross_source_dedup import find_duplicate_events
    groups = find_duplicate_events("modern", min_confidence=0.0)
    assert len(groups) == 1
    # A (ISO, 2d) and its mtgdecks twin (dd/mm/yy, 2d) precede B (dd/mm/yy, 5d)
    assert [e["id"] for e in groups[0]["events"]][-1] == mixed_db["ids"]["B"]


def test_generate_site_data_guides_newest_first(mixed_db):
    import scripts.generate_site_data as gsd
    from db.database import get_connection
    with get_connection() as con:
        out = gsd.generate_guides(con)
    assert [g["author"] for g in out["guides"]["Prowess"]] == ["new", "mid", "old"]


# ---------------------------------------------------------------------------
# No inline copies left
# ---------------------------------------------------------------------------

def test_no_inline_date_case_expressions_remain():
    """The whole point of the sweep: one expression, `db.helpers.SQL_NORM_DATE`."""
    import os, re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pat = re.compile(r"instr\(\s*[\w.]*date[\w.]*\s*,\s*'/'\s*\)")
    offenders = []
    for base, _dirs, files in os.walk(root):
        if any(part in base for part in ("tests", ".git", "__pycache__", "venv", ".venv", "node_modules")):
            continue
        for fn in files:
            if not fn.endswith(".py") or fn == "helpers.py":
                continue
            p = os.path.join(base, fn)
            with open(p, encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if "CASE WHEN" in line and pat.search(line):
                        offenders.append(f"{os.path.relpath(p, root)}:{n}")
    assert offenders == [], f"inline date CASE copies remain: {offenders}"
