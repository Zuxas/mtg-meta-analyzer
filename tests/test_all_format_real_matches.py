"""#27: "all" must mean the supported formats in real-match and trend queries.

db/formats.py's rule is that every format filter goes through format_clause,
because "all" is a sentinel, not a format. The real-match win-rate and
matchup queries and the trend denominator compared lower(format) to the
literal "all", so the Dashboard's "all" view got {} and 0% shares.
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def standard_data(tmp_path, monkeypatch):
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setattr(dbm, "ARCHIVE_PATH", str(tmp_path / "a_arch.db"))
    dbm.init_db()
    from db.matches_queries import _ensure_table
    _ensure_table()
    from analysis import win_rates as wr
    wr._query_cache.clear()

    con = sqlite3.connect(dbm.DB_PATH)
    for i in range(20):
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e1", i, f"p{i}", f"q{i}", "Deck A", "Deck B",
             "player1" if i < 12 else "player2", "Standard", "2026-10-01",
             "mtgmelee"))
    con.execute(
        "INSERT INTO events (source_id, source, name, date, format, event_type, url)"
        " VALUES ('e1','mtgtop8','E',?,'standard','mtgo_challenge_32','http://e')",
        (datetime.now().strftime("%Y-%m-%d"),))
    eid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    for k, arch in enumerate(["Deck A"] * 4 + ["Deck B"] * 4):
        con.execute("INSERT INTO decks (event_id, source_id, player, archetype,"
                    " placement, url) VALUES (?,?,?,?,?,?)",
                    (eid, f"d{k}", f"P{k}", arch, k + 1, f"http://d/{k}"))
    con.commit()
    con.close()


def test_real_archetype_winrates_all_includes_standard(standard_data):
    from analysis.win_rates import get_real_archetype_winrates
    one = get_real_archetype_winrates("standard", min_matches=1)
    every = get_real_archetype_winrates("all", min_matches=1)
    assert one and every["Deck A"]["wins"] == one["Deck A"]["wins"] == 12


def test_real_matchup_winrates_all_includes_standard(standard_data):
    from analysis.win_rates import get_real_matchup_winrates
    every = get_real_matchup_winrates("all", min_matches=1, min_arch_appearances=1)
    assert every["Deck A"]["Deck B"]["total"] == 20


def test_trend_share_for_all_is_not_zero(standard_data):
    from analysis.win_rates import get_archetype_trend
    weeks = [w for w in get_archetype_trend("Deck A", "all", weeks=2) if w["appearances"]]
    assert weeks and all(w["meta_share"] == 0.5 for w in weeks)


def test_all_unions_formats_not_alias_for_standard(standard_data):
    """'all' must add Modern rows to the Standard ones, mirrors included."""
    import db.database as dbm
    from analysis import win_rates as wr
    con = sqlite3.connect(dbm.DB_PATH)
    for i, (p2, res) in enumerate([("Deck B", "player1")] * 5 + [("Deck A", "player1")] * 2):
        con.execute(
            "INSERT INTO matches (event_id, round, player1, player2, player1_arch,"
            " player2_arch, result, format, event_date, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e2", i, f"m{i}", f"n{i}", "Deck A", p2, res, "modern", "2026-10-01",
             "mtgmelee"))
    con.commit()
    con.close()
    wr._query_cache.clear()
    every = wr.get_real_archetype_winrates("all", min_matches=1)["Deck A"]
    assert (every["wins"], every["total"], every["mirrors"]) == (17, 25, 2)
    assert wr.get_real_archetype_winrates("standard", min_matches=1)["Deck A"]["mirrors"] == 0


def test_win_rates_has_no_literal_format_compare():
    """Lint: every format filter in win_rates.py goes through format_clause."""
    src = Path(__file__).resolve().parents[1] / "analysis" / "win_rates.py"
    code = [ln for ln in src.read_text(encoding="utf-8").splitlines()
            if not ln.strip().startswith("#")]
    bad = [ln.strip() for ln in code
           if re.search(r"lower\((\w+\.)?format\)\s*=\s*lower\(\?\)", ln)]
    assert bad == []
