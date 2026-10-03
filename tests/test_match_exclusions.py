"""Excluded Melee rows (db/match_exclusions.py + scripts/quarantine_matches.py), 2026-10-02.

Limited (Draft/Sealed) rounds of mixed events are MOVED to matches_excluded and registered; analytics,
which read `matches` directly in many places, then never see them, and save_matches refuses them.
Trios events are 1v1 seat pairings: their rows are re-tagged per pairing (only `format`), unjoined
rows held. Synthetic data only (tmp DB from conftest's live-DB guard)."""
import sqlite3

import pytest

from analysis import win_rates
from db import matches_queries as mq
from db.database import DB_PATH  # noqa: F401  (patched by conftest)
from db.match_exclusions import excluded_summary, load_registry
from scripts import quarantine_matches as qm


def _db():
    from db import database
    return sqlite3.connect(database.DB_PATH)


def _row(eid, rnd, p1, p2, a1, a2, result, fmt, src="mtgmelee"):
    win = a1 if result == "player1" else a2 if result == "player2" else None
    return {"event_id": eid, "round": rnd, "player1": p1, "player2": p2, "player1_arch": a1,
            "player2_arch": a2, "winner_arch": win, "result": result, "format": fmt,
            "event_date": "2026-01-01", "source": src}


@pytest.fixture
def seeded():
    win_rates._query_cache.clear()
    rows = []
    for i in range(6):                                          # mixed event: draft round 1, modern round 4
        rows.append(_row("mtgmelee_1", 1, f"d{i}", f"e{i}", "Draft 1", "Orzhov", "player1", "modern"))
        rows.append(_row("mtgmelee_1", 4, f"d{i}", f"e{i}", "Boros Energy", "Amulet Titan", "player1", "modern"))
    for i in range(6):                                          # a trios event, Vintage seat stored as legacy
        rows.append(_row("mtgmelee_2", 1, f"v{i}", f"w{i}", "Doomsday", "Oath", "player2", "legacy"))
    rows.append(_row("mtgmelee_2", 1, "lost", "name", "Doomsday", "Oath", "player1", "legacy"))   # unjoined
    mq.save_matches(rows)
    con = _db()
    ids = {k: [r[0] for r in con.execute("SELECT id FROM matches WHERE event_id=? AND round=? ORDER BY id", k)]
           for k in (("mtgmelee_1", 1), ("mtgmelee_1", 4), ("mtgmelee_2", 1))}
    return rows, ids


def _limited_plan(ids):
    entries = [{"source": "mtgmelee", "event_id": "mtgmelee_1", "round": 1, "scope": "round",
                "reason": "limited-round", "rows": len(ids[("mtgmelee_1", 1)])}]
    plan = {"entries": entries, "row_ids": {"mtgmelee_1|1": ids[("mtgmelee_1", 1)]}}
    plan["plan_sha256"] = qm._sha(plan)
    return plan


def _all_rows(con, table="matches"):
    return {r[0]: r for r in con.execute(f"SELECT {qm.COLS} FROM {table}")}


def test_quarantine_moves_rows_exactly_and_analytics_stop_counting_them(seeded):
    rows, ids = seeded
    con = _db()
    before = _all_rows(con)
    assert win_rates.get_real_archetype_winrates("modern", min_matches=1)["Draft 1"]["total"] == 6
    res = qm.quarantine(con, _limited_plan(ids), backup=None)
    assert (res["matches_before"], res["matches_after"], res["moved"]) == (len(before), len(before) - 6, 6)
    moved = set(ids[("mtgmelee_1", 1)])
    excluded = _all_rows(con, "matches_excluded")
    assert {i: excluded[i] for i in moved} == {i: before[i] for i in moved}       # unchanged, original ids
    assert not moved & set(_all_rows(con))                                        # in one table only
    win_rates._query_cache.clear()
    wr = win_rates.get_real_archetype_winrates("modern", min_matches=1)
    assert "Draft 1" not in wr and "Orzhov" not in wr                             # limited rows gone
    assert wr["Boros Energy"]["total"] == 6                                       # constructed round stays
    assert len(mq.get_matches("modern")) == 6
    assert excluded_summary(con)["rows"] == 6                                     # visible in audit output
    assert excluded_summary(con)["by_reason"] == {"limited-round (round)": 6}


def test_quarantine_is_idempotent(seeded):
    _, ids = seeded
    con = _db()
    qm.quarantine(con, _limited_plan(ids), backup=None)
    snap = (_all_rows(con), _all_rows(con, "matches_excluded"))
    res = qm.quarantine(con, _limited_plan(ids), backup=None)
    assert res["moved"] == 0 and res["already_done"]
    assert (_all_rows(con), _all_rows(con, "matches_excluded")) == snap
    assert con.execute("SELECT COUNT(*) FROM excluded_events").fetchone()[0] == 1


def test_repeated_import_cannot_restore_quarantined_rows(seeded):
    rows, ids = seeded
    con = _db()
    qm.quarantine(con, _limited_plan(ids), backup=None)
    n_before = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    mq.save_matches(rows)                                       # the same scrape, again
    assert len(mq.LAST_SAVE_SKIPPED) == 6                       # refused and counted, not silent
    assert {m["round"] for m in mq.LAST_SAVE_SKIPPED} == {1}
    assert con.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == n_before
    assert con.execute("SELECT COUNT(*) FROM matches WHERE event_id='mtgmelee_1' AND round=1").fetchone()[0] == 0
    assert load_registry(con) == (set(), {("mtgmelee", "mtgmelee_1", 1)})


def test_whole_event_registry_entries_also_block_and_skip_rescrape(seeded):
    rows, _ = seeded
    con = _db()
    qm.ensure_tables_tx(con)
    con.execute("INSERT INTO excluded_events (source, event_id, round, scope, reason, created_at) "
                "VALUES ('mtgmelee', 'mtgmelee_9', NULL, 'event', 'test', 'now')")
    con.commit()
    mq.save_matches([_row("mtgmelee_9", 1, "x", "y", "A", "B", "player1", "modern")])
    assert len(mq.LAST_SAVE_SKIPPED) == 1
    assert "mtgmelee_9" in mq.get_stored_event_ids("modern")


def test_restore_returns_rows_exactly(seeded):
    _, ids = seeded
    con = _db()
    before = _all_rows(con)
    qm.quarantine(con, _limited_plan(ids), backup=None)
    assert qm.restore(con, "mtgmelee_1", 1) == 6
    assert _all_rows(con) == before
    assert con.execute("SELECT COUNT(*) FROM matches_excluded").fetchone()[0] == 0
    assert load_registry(con) == (set(), set())


def test_quarantine_refuses_a_stale_plan(seeded):
    _, ids = seeded
    con = _db()
    plan = _limited_plan(ids)
    plan["row_ids"]["mtgmelee_1|1"] = plan["row_ids"]["mtgmelee_1|1"][:-1]
    with pytest.raises(RuntimeError, match="differ from the reviewed plan"):
        qm.quarantine(con, plan, backup=None)
    assert con.execute("SELECT COUNT(*) FROM matches WHERE event_id='mtgmelee_1' AND round=1").fetchone()[0] == 6


def _trios_evidence():
    pairings = [{"format": "Vintage", "players": [[f"v{i}"], [f"w{i}"]], "wins": [0, 2], "draws": 0,
                 "deck_formats": [], "has_result": True} for i in range(6)]
    return {"2": {"failed": [], "rounds": [{"name": "Round 1", "round": 1, "pairings": pairings}]}}


def test_retag_vintage_rows_stay_stored_but_leave_supported_format_stats(seeded, monkeypatch):
    monkeypatch.setattr(qm, "TEAM_EVENTS", ("mtgmelee_2",))
    con = _db()
    before = _all_rows(con)
    plan = qm.build_retag_plan(con, _trios_evidence())
    assert plan["moves"] == {"legacy>vintage": 6} and not plan["conflicts"]
    assert [h["why"] for h in plan["held"]] == ["no pairing joins"]
    qm.retag(con, plan, backup=None)
    after = _all_rows(con)
    assert set(after) == set(before)                                         # nothing removed
    fi = qm.MATCH_COLS.index("format")
    changed = {i for i in before if before[i] != after[i]}
    assert len(changed) == 6
    for i in changed:                                                        # only format moved
        assert before[i][:fi] + before[i][fi + 1:] == after[i][:fi] + after[i][fi + 1:]
    held_id = plan["held"][0]["id"]
    assert after[held_id] == before[held_id]                                 # unresolved row untouched
    win_rates._query_cache.clear()
    for fmt in ("standard", "pioneer", "modern", "legacy", "pauper"):
        assert "Doomsday" not in win_rates.get_real_archetype_winrates(fmt, min_matches=1) or fmt == "legacy"
    assert win_rates.get_real_archetype_winrates("legacy", min_matches=1)["Doomsday"]["total"] == 1   # held row
    assert len(mq.get_matches("vintage")) == 6                              # still stored, as vintage
    assert qm.build_retag_plan(con, _trios_evidence())["changes"] == []     # idempotent


def test_retag_stops_on_a_result_disagreement(seeded, monkeypatch):
    monkeypatch.setattr(qm, "TEAM_EVENTS", ("mtgmelee_2",))
    ev = _trios_evidence()
    ev["2"]["rounds"][0]["pairings"][0]["wins"] = [2, 0]                    # Melee says player1 won
    plan = qm.build_retag_plan(_db(), ev)
    assert any("stored result player2 != pairing player1" in c for c in plan["conflicts"])
