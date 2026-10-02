"""Historical Melee relabel: plan buckets, the manifest hash, the one-transaction apply and the
zero-change re-run.

Synthetic fixture only (tmp DB + tmp pairing cache); player names are placeholders."""
import json
import sqlite3
from argparse import Namespace

import pytest

from analysis.archetypes import normalize, pre_normalize
from scrapers.mtgmelee_scraper import _map_archetype
from scripts import relabel_melee_history as r

SCHEMA = """CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
    round INTEGER, player1 TEXT, player2 TEXT, player1_arch TEXT NOT NULL, player2_arch TEXT NOT NULL,
    winner_arch TEXT, result TEXT, format TEXT NOT NULL, event_date TEXT,
    source TEXT NOT NULL DEFAULT 'mtgmelee', UNIQUE(event_id, round, player1, player2))"""

BROOD = "Mono-Green Broodscale"          # stored 'Mono Red Aggro' by the fuzzy bug
KAHEERA = "Azorius Control (Kaheera)"    # fuzzy today folds it into 'Azorius Control'


def _row(con, rid, p1, p2, a1, a2, result, rnd=1, eid="mtgmelee_1", src="mtgmelee"):
    win = a1 if result == "player1" else a2 if result == "player2" else None
    con.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, eid, rnd, p1, p2, a1, a2, win, result, "modern", "2026-01-01", src))


def _pairing(rnd, p1, p2, d1, d2):
    return {"round": rnd, "player1": p1, "player2": p2, "player1_deck": d1, "player2_deck": d2}


def _cache(cache, tid, pairings, failed=()):
    (cache / f"{tid}.json").write_text(
        json.dumps({"tid": tid, "rounds": 3, "failed_rounds": list(failed), "code_commit": "c0ffee",
                    "pairings": pairings}), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "mtg_meta.db"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=wal")                                         # as the live DB
    con.execute(SCHEMA)
    _row(con, 1, "p1", "p2", "Jeskai Control", "Boros Energy", "player1")          # fuzzy guess
    _row(con, 2, "p3", "p4", normalize(KAHEERA, fuzzy=True), "Boros Energy", "draw")  # fuzzy_fix, draw
    _row(con, 3, "p5", "p6", "Boros Energy", "Boros Energy", "player2")            # unchanged
    _row(con, 4, "p7", "p8", "Decklist", "Boros Energy", "player1")                # junk -> unlabelled
    _row(con, 5, "p9", "p10", "Mono Red Aggro", "Boros Energy", "player1")         # not in re-scrape
    _row(con, 6, "p1", "p2", "Mono Red Aggro", "Boros Energy", "player1", eid="mtgmelee_2")  # no cache
    _row(con, 8, "p1", "p2", "Mono Red Aggro", "Boros Energy", "player1", rnd=3)   # key twice in scrape
    _row(con, 9, "p1", "p2", "Mono Red Aggro", "Boros Energy", "player1", eid="mtgmelee_3")  # failed round
    _row(con, 99, "p1", "p2", "Mono Red Aggro", "Boros Energy", "player1", rnd=2)  # above the cutoff
    _row(con, 7, "x", "y", "Mono Red Aggro", "Boros Energy", "player1", src="mtgtop8")  # not melee
    con.commit()
    con.close()
    cache, out = tmp_path / "cache", tmp_path / "out"
    cache.mkdir()
    pairings = [
        _pairing(1, "p1", "p2", BROOD, "Boros Energy"),
        _pairing(1, "p3", "p4", KAHEERA, "Boros Energy"),
        _pairing(1, "p5", "p6", "Boros Energy", "Boros Energy"),
        _pairing(1, "p7", "p8", "Decklist", "Boros Energy"),
        _pairing(2, "p1", "p2", "Boros Energy", "Boros Energy"),
        _pairing(3, "p1", "p2", BROOD, "Boros Energy"),
        _pairing(3, "p1", "p2", "Boros Energy", "Boros Energy"),
    ]
    _cache(cache, "1", pairings)
    _cache(cache, "3", [_pairing(1, "p1", "p2", BROOD, "Boros Energy")],
           failed=[{"round": "Round 2", "error": "timeout"}])
    monkeypatch.setattr(r, "_code_commit", lambda: "c0ffee")
    monkeypatch.setattr(r, "CACHE_DIR", cache)
    monkeypatch.setattr(r, "OUT_DIR", out)
    monkeypatch.setattr(r, "CUTOFF_ID", 50)
    return db


def _plan(db):
    return r.build_plan(sqlite3.connect(db))


def _manifest(env, tmp_path):
    r.cmd_plan(Namespace(db=env, format=None))
    return str(next((tmp_path / "out").glob("dryrun-*.json")))


def test_preconditions_of_the_fixture():
    assert _map_archetype(BROOD, "") not in ("", "Mono Red Aggro", "Jeskai Control")
    assert "Jeskai Control" not in r._fuzzy_candidates(pre_normalize(BROOD))
    assert _map_archetype(KAHEERA, "") != normalize(KAHEERA, fuzzy=True)
    assert _map_archetype("Decklist", "") == ""


def test_plan_buckets_and_scope(env):
    p = _plan(env)
    assert p["rows_in_scope"] == 8                          # id 99 (after cutoff) and mtgtop8 excluded
    assert p["totals"] == {"fuzzy_guess": 1, "fuzzy_fix": 1, "unchanged": 1, "unlabelled": 1,
                           "unmatched": 1, "ambiguous": 1, "unrecovered": 2}
    assert p["coverage"]["events_unrecovered"] == ["mtgmelee_2", "mtgmelee_3"]   # no cache / failed round
    assert {b: [h["id"] for h in v] for b, v in p["held"].items()} == {
        "unlabelled": [4], "unmatched": [5], "ambiguous": [8], "unrecovered": [6, 9]}
    by_id = {c["id"]: c for c in p["changes"]}
    assert set(by_id) == {1, 2}
    assert by_id[1]["new"] == [_map_archetype(BROOD, ""), "Boros Energy", _map_archetype(BROOD, "")]
    assert by_id[2]["new"][2] is None                       # draw keeps winner_arch NULL
    assert len(p["manifest_sha256"]) == 64


def test_plan_is_deterministic(env):
    assert _plan(env)["manifest_sha256"] == _plan(env)["manifest_sha256"]


def test_manifest_hash_covers_db_rows_and_cache(env):
    h = _plan(env)["manifest_sha256"]
    con = sqlite3.connect(env)
    con.execute("UPDATE matches SET event_date='2026-01-02' WHERE id=3")   # a column the plan ignores
    con.commit()
    h2 = _plan(env)["manifest_sha256"]
    assert h2 != h
    d = json.loads((r.CACHE_DIR / "1.json").read_text())
    d["fetched_at"] = "later"                                              # cache file moved
    (r.CACHE_DIR / "1.json").write_text(json.dumps(d))
    assert _plan(env)["manifest_sha256"] != h2


def test_report_has_samples_and_no_player_names(env, tmp_path):
    _manifest(env, tmp_path)
    md = next((tmp_path / "out").glob("dryrun-*.md")).read_text(encoding="utf-8")
    assert "### fuzzy_guess (1 rows)" in md and "### unmatched (1 rows, left unchanged)" in md
    assert "Manifest sha256" in md
    assert not any(f"| p{i} " in md or f" p{i} /" in md for i in range(1, 11))


def test_apply_updates_only_reviewed_rows_then_reruns_clean(env, tmp_path):
    manifest = _manifest(env, tmp_path)
    before = {row[0]: row for row in sqlite3.connect(env).execute("SELECT * FROM matches")}
    rc = r.cmd_apply(Namespace(db=env, manifest=manifest, buckets="fuzzy_fix,fuzzy_guess"))
    assert rc == 0
    after = {row[0]: row for row in sqlite3.connect(env).execute("SELECT * FROM matches")}
    assert set(before) == set(after)                         # nothing inserted or deleted
    assert {i for i in before if before[i] != after[i]} == {1, 2}   # held rows untouched
    assert after[1][5:8] == (_map_archetype(BROOD, ""), "Boros Energy", _map_archetype(BROOD, ""))
    assert after[1][8] == before[1][8]                       # result untouched
    backup = next(tmp_path.glob("mtg_meta.backup-*-pre-melee-relabel.db"))
    assert {row[0]: row for row in sqlite3.connect(backup).execute("SELECT * FROM matches")} == before
    again = _plan(env)
    assert not again["changes"]                              # second run: nothing left to change
    assert list((tmp_path / "out").glob("applied-*.md"))


def test_apply_refuses_a_stale_manifest(env, tmp_path):
    manifest = _manifest(env, tmp_path)
    con = sqlite3.connect(env)
    con.execute("UPDATE matches SET player2_arch='Jeskai' WHERE id=5")   # DB moved after review
    con.commit()
    snapshot = list(con.execute("SELECT * FROM matches ORDER BY id"))
    with pytest.raises(RuntimeError, match="db_rows_sha256"):
        r.cmd_apply(Namespace(db=env, manifest=manifest, buckets="fuzzy_guess"))
    assert list(sqlite3.connect(env).execute("SELECT * FROM matches ORDER BY id")) == snapshot


def test_apply_refuses_a_manifest_from_other_code(env, tmp_path, monkeypatch):
    manifest = _manifest(env, tmp_path)
    monkeypatch.setattr(r, "_code_commit", lambda: "deadbeef")
    with pytest.raises(SystemExit, match="built by"):
        r.cmd_apply(Namespace(db=env, manifest=manifest, buckets="fuzzy_fix"))


def test_apply_never_takes_held_buckets(env, tmp_path):
    manifest = _manifest(env, tmp_path)
    for b in ("unlabelled", "unmatched", "ambiguous", "unrecovered"):
        with pytest.raises(SystemExit):
            r.cmd_apply(Namespace(db=env, manifest=manifest, buckets=b))


def test_fuzzy_reproduction_is_the_whole_tie_set():
    """normalize(fuzzy=True) picks among tied names in set order (PYTHONHASHSEED-dependent):
    'Mono-Green Broodscale' came back 'Mono Red Aggro' or 'Green Post' run to run. The bucket must
    not depend on that, so every tied best candidate counts as a reproduction."""
    tie = r._fuzzy_candidates(pre_normalize(BROOD))
    assert {"Mono Red Aggro", "Green Post"} <= tie
    assert r._slot("Mono Red Aggro", BROOD)[1] == r._slot("Green Post", BROOD)[1] == "fuzzy_fix"
