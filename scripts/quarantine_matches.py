"""Quarantine `matches` rows proven invalid for constructed 1v1 analysis (db/match_exclusions.py).

  python -m scripts.quarantine_matches prove     # read-only: fetch evidence, write a plan
  python -m scripts.quarantine_matches commit --plan P   # backup + ONE transaction: move + register
  python -m scripts.quarantine_matches restore --event mtgmelee_X [--round N]   # reverse, one transaction

  python -m scripts.quarantine_matches retag --plan R    # trios events: per-pairing format fix

Proof comes from Melee's own pairing data (GetRoundMatches, re-fetched read-only and cached under
E:\\mtg-data\\raw\\melee_relabel\\exclusion_evidence\\ -- holds player names, never in git):
  * limited round (quarantined) -- every pairing of the round has match Format Draft/Sealed, so every
    stored row of the round is a Limited match (rows that do not join by player name are proven by
    the round and listed). A round mixing limited and constructed stops the plan. Constructed rounds
    of mixed events are never touched.
  * trios events (re-tagged, NOT quarantined) -- the public pairings are 1v1 seat matches with a
    per-match Format; a row is re-tagged only if it joins exactly one 1v1 pairing on (round, player1,
    player2) whose result equals the stored result. Unjoined rows are held; any result disagreement
    stops the plan. Only `format` changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from db.match_exclusions import MATCH_COLS, ensure_tables  # noqa: E402

EVIDENCE_DIR = Path(r"E:\mtg-data\raw\melee_relabel\exclusion_evidence")
OUT_DIR = Path(r"E:\mtg-data\reports\melee_relabel")
TEAM_EVENTS = ("mtgmelee_437430", "mtgmelee_410427", "mtgmelee_212836", "mtgmelee_352110", "mtgmelee_225979")
MIXED_EVENTS = ("mtgmelee_146430", "mtgmelee_228372", "mtgmelee_303784", "mtgmelee_355905", "mtgmelee_368892",
                "mtgmelee_375961", "mtgmelee_386462", "mtgmelee_394299", "mtgmelee_415628", "mtgmelee_434455")
LIMITED = ("draft", "sealed")
COLS = ", ".join(MATCH_COLS)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _is_limited(fmt: str | None) -> bool:
    return bool(fmt) and any(w in fmt.lower() for w in LIMITED)


# ---------------------------------------------------------------------------
# evidence (network, read-only)
# ---------------------------------------------------------------------------

def _fetch_evidence(tid: str) -> dict:
    from scrapers import mtgmelee_scraper as ms
    s = ms._session()
    rounds = ms._get_round_ids(s, tid)
    out = {"tid": tid, "fetched_at": _now(), "rounds": [], "failed": []}
    for rid, rname in rounds:
        try:
            resp = s.post(ms._ROUND_URL.format(rid=rid), data=ms._pairing_dt_payload(0, 500),
                          headers={"X-Requested-With": "XMLHttpRequest",
                                   "Referer": ms._VIEW_URL.format(tid=tid)}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:                                       # noqa: BLE001
            out["failed"].append({"round": rname, "error": str(exc)[:200]})
            time.sleep(ms._SLEEP)
            continue
        pairings = []
        for row in data.get("data", []):
            comps = row.get("Competitors") or []
            pairings.append({
                "format": row.get("Format") or row.get("FormatDescription"),
                "players": [[p.get("DisplayName", "") for p in (c.get("Team") or {}).get("Players", [])]
                            for c in comps],
                "deck_formats": [[d.get("Format") for d in (c.get("Decklists") or [])] for c in comps],
                "wins": [c.get("GameWins") or 0 for c in comps],
                "draws": row.get("GameDraws") or 0,
                "has_result": bool(row.get("HasResult")),
            })
        out["rounds"].append({"name": rname, "round": ms._round_number(rname),
                              "records_total": data.get("recordsTotal"), "pairings": pairings})
        time.sleep(ms._SLEEP)
    return out


def _evidence(tid: str, refetch: bool) -> dict:
    path = EVIDENCE_DIR / f"{tid}.json"
    if path.exists() and not refetch:
        d = json.loads(path.read_text(encoding="utf-8"))
        if not d["failed"]:
            return d
    d = _fetch_evidence(tid)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# plan (pure over evidence + DB)
# ---------------------------------------------------------------------------

def _pairing_result(p: dict) -> str | None:
    w1, w2 = p["wins"]
    return "player1" if w1 > w2 else "player2" if w2 > w1 else ("draw" if p["draws"] else None)


def build_retag_plan(con, evidence: dict[str, dict]) -> dict:
    """Per-row format corrections for the trios events (1v1 seat pairings, per-match Format).
    A row is changed only if it joins exactly one pairing on (round, player1, player2) with two
    single-player sides, and the pairing's result equals the stored result; unjoined rows are held.
    Any result disagreement is a conflict (the caller stops)."""
    changes, held, conflicts, unchanged = [], [], [], 0
    for eid in TEAM_EVENTS:
        ev = evidence[eid.removeprefix("mtgmelee_")]
        if ev["failed"]:
            conflicts.append(f"{eid}: evidence has failed rounds")
            continue
        index = defaultdict(list)
        for r in ev["rounds"]:
            for p in r["pairings"]:
                if len(p["players"]) == 2 and p["players"][0] and p["players"][1]:
                    index[(r["round"], p["players"][0][0], p["players"][1][0])].append(p)
        for rid, rnd, p1, p2, fmt, result in con.execute(
                "SELECT id, round, player1, player2, format, result FROM matches WHERE event_id = ? ORDER BY id",
                (eid,)):
            hits = index.get((rnd, p1, p2), [])
            if len(hits) != 1:
                held.append({"id": rid, "event_id": eid, "round": rnd, "format": fmt,
                             "why": "no pairing joins" if not hits else "several pairings join"})
                continue
            p = hits[0]
            if max(len(p["players"][0]), len(p["players"][1])) != 1:
                conflicts.append(f"{eid} row {rid}: pairing is not 1v1")
                continue
            if _pairing_result(p) != result:
                conflicts.append(f"{eid} row {rid}: stored result {result} != pairing {_pairing_result(p)}")
                continue
            new = (p["format"] or "").strip().lower()
            if not new or _is_limited(new):
                conflicts.append(f"{eid} row {rid}: pairing format {p['format']!r}")
                continue
            if new == fmt:
                unchanged += 1
            else:
                changes.append({"id": rid, "event_id": eid, "round": rnd, "old": fmt, "new": new})
    plan = {"generated_at": _now(), "changes": changes, "held": held, "conflicts": conflicts,
            "unchanged": unchanged,
            "moves": dict(Counter(f"{c['old']}>{c['new']}" for c in changes)),
            "by_event": {e: dict(Counter(f"{c['old']}>{c['new']}" for c in changes if c["event_id"] == e))
                         for e in TEAM_EVENTS}}
    plan["plan_sha256"] = _sha({"changes": changes, "held": held})
    return plan


def build_plan(con, evidence: dict[str, dict]) -> dict:
    """Registry entries (event + round) for the Limited rounds of the mixed events and the exact
    row ids they cover. Proof is the ROUND: every pairing of the round has a Draft/Sealed match
    Format, so every stored row of that round is a Limited match -- rows that do not join a
    pairing by player name (renames) are listed but are proven by the round."""
    entries, row_ids, unproven, notes = [], {}, [], {}
    for eid in MIXED_EVENTS:
        ev = evidence[eid.removeprefix("mtgmelee_")]
        if ev["failed"]:
            unproven.append(f"{eid}: evidence has failed rounds")
            continue
        by_round = defaultdict(list)                  # several Melee rounds can map to one stored
        for r in ev["rounds"]:                        # round number (two 'Finals' -> -1)
            by_round[r["round"]].append(r)
        for rnd, rs in sorted(by_round.items()):
            pairings = [p for r in rs for p in r["pairings"]]
            fmts = Counter("limited" if _is_limited(p["format"]) else (p["format"] or "?").lower()
                           for p in pairings)
            if "limited" not in fmts:
                continue
            if len(fmts) > 1:
                unproven.append(f"{eid} round {rnd}: mixes {dict(fmts)}")
                continue
            names = {(p["players"][0][0], p["players"][1][0]) for p in pairings
                     if len(p["players"]) == 2 and p["players"][0] and p["players"][1]}
            rows = con.execute("SELECT id, player1, player2 FROM matches WHERE event_id = ? AND round = ?",
                               (eid, rnd)).fetchall()
            unjoined = [rid for rid, p1, p2 in rows if (p1, p2) not in names]
            notes.setdefault(eid, []).append({"round": rnd, "names": [r["name"] for r in rs],
                                              "formats": sorted({p["format"] for p in pairings}),
                                              "pairings": len(pairings), "stored_rows": len(rows),
                                              "round_proven_unjoined_ids": unjoined})
            entries.append({"source": "mtgmelee", "event_id": eid, "round": rnd, "scope": "round",
                            "reason": "limited-round", "rows": len(rows)})
            row_ids[(eid, rnd)] = sorted(x[0] for x in rows)
    all_ids = [i for v in row_ids.values() for i in v]
    if len(all_ids) != len(set(all_ids)):
        unproven.append("row id sets overlap")
    plan = {"generated_at": _now(), "entries": entries,
            "row_ids": {f"{e}|{'*' if r is None else r}": v for (e, r), v in row_ids.items()},
            "rows_total": len(all_ids), "rows_by_reason": dict(Counter(
                e["reason"] for e in entries for _ in range(e["rows"]))),
            "limited_rounds": notes, "unproven": unproven,
            "evidence_sha256": _sha({k: v for k, v in sorted(evidence.items())})}
    plan["plan_sha256"] = _sha({"entries": entries, "row_ids": plan["row_ids"]})
    return plan


def cmd_prove(a) -> int:
    from db.database import DB_PATH
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=60)
    evidence = {}
    for eid in TEAM_EVENTS + MIXED_EVENTS:
        tid = eid.removeprefix("mtgmelee_")
        evidence[tid] = _evidence(tid, a.refetch)
        print(f"  {eid}: {len(evidence[tid]['rounds'])} rounds, failed {len(evidence[tid]['failed'])}", flush=True)
    plan = build_plan(con, evidence)
    retag = build_retag_plan(con, evidence)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    out = OUT_DIR / f"quarantine-plan-{stamp}.json"
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    out2 = OUT_DIR / f"retag-plan-{stamp}.json"
    out2.write_text(json.dumps(retag, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: plan[k] for k in ("rows_total", "rows_by_reason", "unproven", "plan_sha256")}, indent=1))
    print(json.dumps({"changes": len(retag["changes"]), "moves": retag["moves"], "by_event": retag["by_event"],
                      "unchanged": retag["unchanged"], "held": len(retag["held"]),
                      "conflicts": retag["conflicts"], "plan_sha256": retag["plan_sha256"]}, indent=1))
    print(f"plans: {out}  {out2}")
    return 1 if plan["unproven"] or retag["conflicts"] else 0


def retag(con, plan: dict, backup: Path | None) -> dict:
    """Apply a retag plan in one transaction: only `format` changes, guarded by the old value."""
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        if backup is not None:
            dst = sqlite3.connect(backup)
            sqlite3.connect(f"file:{con.execute('PRAGMA database_list').fetchone()[2]}?mode=ro",
                            uri=True).backup(dst)
            dst.close()
            if sqlite3.connect(f"file:{backup}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity_check failed")
        ids = [c["id"] for c in plan["changes"]] + [h["id"] for h in plan["held"]]
        ph = ",".join("?" * len(ids)) or "NULL"
        before = {r[0]: r for r in con.execute(f"SELECT {COLS} FROM matches WHERE id IN ({ph})", ids)}
        totals_before = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        n = 0
        for c in plan["changes"]:
            n += con.execute("UPDATE matches SET format = ? WHERE id = ? AND event_id = ? AND format = ?",
                             (c["new"], c["id"], c["event_id"], c["old"])).rowcount
        if n != len(plan["changes"]):
            raise RuntimeError(f"updated {n}, expected {len(plan['changes'])} (plan stale?)")
        after = {r[0]: r for r in con.execute(f"SELECT {COLS} FROM matches WHERE id IN ({ph})", ids)}
        fi = MATCH_COLS.index("format")
        new_fmt = {c["id"]: c["new"] for c in plan["changes"]}
        for rid, row in before.items():
            exp = list(row)
            if rid in new_fmt:
                exp[fi] = new_fmt[rid]
            if list(after[rid]) != exp:
                raise RuntimeError(f"row {rid}: unexpected change")
        totals_after = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        if sum(totals_before.values()) != sum(totals_after.values()):
            raise RuntimeError("total row count changed")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"rows_updated": n, "format_totals_before": totals_before, "format_totals_after": totals_after}


def cmd_retag(a) -> int:
    from db.database import DB_PATH
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if plan["conflicts"]:
        raise SystemExit("retag plan has conflicts -- refusing")
    if plan["plan_sha256"] != _sha({"changes": plan["changes"], "held": plan["held"]}):
        raise SystemExit("plan file was edited after prove -- refusing")
    db = Path(DB_PATH)
    if sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("integrity_check before failed")
    evidence = {e.removeprefix("mtgmelee_"): json.loads((EVIDENCE_DIR / f"{e.removeprefix('mtgmelee_')}.json")
                                                        .read_text(encoding="utf-8")) for e in TEAM_EVENTS}
    con = sqlite3.connect(db, timeout=60)
    if build_retag_plan(con, evidence)["plan_sha256"] != plan["plan_sha256"]:
        raise SystemExit("DB or evidence moved since prove -- refusing")
    backup = db.with_name(f"mtg_meta.backup-{datetime.now():%Y-%m-%d}-pre-team-format-fix.db")
    if backup.exists():
        raise SystemExit(f"{backup} exists -- refusing to overwrite")
    res = retag(con, plan, backup)
    rerun = build_retag_plan(con, evidence)
    res.update({"integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0], "backup": str(backup),
                "plan_sha256": plan["plan_sha256"], "moves": plan["moves"], "held_ids": [h["id"] for h in plan["held"]],
                "rerun_changes": len(rerun["changes"]), "rerun_held": len(rerun["held"])})
    out = OUT_DIR / f"retag-applied-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "held_ids"}, indent=1))
    return 0 if res["integrity_check"] == "ok" and res["rerun_changes"] == 0 else 1


# ---------------------------------------------------------------------------
# commit / restore (one transaction each)
# ---------------------------------------------------------------------------

def _ids_now(con, entries) -> dict[str, list[int]]:
    out = {}
    for e in entries:
        if e["round"] is None:
            ids = [r[0] for r in con.execute("SELECT id FROM matches WHERE source=? AND event_id=? ORDER BY id",
                                             (e["source"], e["event_id"]))]
        else:
            ids = [r[0] for r in con.execute("SELECT id FROM matches WHERE source=? AND event_id=? AND round=? "
                                             "ORDER BY id", (e["source"], e["event_id"], e["round"]))]
        out[f"{e['event_id']}|{'*' if e['round'] is None else e['round']}"] = ids
    return out


def quarantine(con, plan: dict, backup: Path | None) -> dict:
    """Move the plan's rows into matches_excluded and register the entries, in one transaction.
    Idempotent: rows already moved are not in `matches` any more, registry inserts are OR IGNORE."""
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        if backup is not None:
            dst = sqlite3.connect(backup)
            src = sqlite3.connect(f"file:{con.execute('PRAGMA database_list').fetchone()[2]}?mode=ro", uri=True)
            src.backup(dst)
            dst.close()
            if sqlite3.connect(f"file:{backup}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity_check failed")
        ensure_tables_tx(con)
        now_ids = _ids_now(con, plan["entries"])
        already = all(not v for v in now_ids.values())
        if not already and now_ids != plan["row_ids"]:
            raise RuntimeError("rows in matches differ from the reviewed plan -- re-run prove")
        before = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        moved = 0
        ts = _now()
        for e in plan["entries"]:
            key = f"{e['event_id']}|{'*' if e['round'] is None else e['round']}"
            ids = now_ids[key]
            if ids:
                ph = ",".join("?" * len(ids))
                originals = con.execute(f"SELECT {COLS} FROM matches WHERE id IN ({ph}) ORDER BY id", ids).fetchall()
                con.execute(f"INSERT INTO matches_excluded ({COLS}, excluded_reason, excluded_scope, excluded_at) "
                            f"SELECT {COLS}, ?, ?, ? FROM matches WHERE id IN ({ph})",
                            [e["reason"], e["scope"], ts, *ids])
                copies = con.execute(f"SELECT {COLS} FROM matches_excluded WHERE id IN ({ph}) ORDER BY id",
                                     ids).fetchall()
                if copies != originals:
                    raise RuntimeError(f"{key}: quarantined copies differ from the originals")
                n = con.execute(f"DELETE FROM matches WHERE id IN ({ph})", ids).rowcount
                if n != len(ids):
                    raise RuntimeError(f"{key}: deleted {n}, expected {len(ids)}")
                moved += n
            con.execute("INSERT OR IGNORE INTO excluded_events (source, event_id, round, scope, reason, evidence, "
                        "created_at) VALUES (?,?,?,?,?,?,?)",
                        (e["source"], e["event_id"], e["round"], e["scope"], e["reason"],
                         f"plan {plan['plan_sha256'][:16]}", ts))
        after = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        if before != after + moved:
            raise RuntimeError(f"matches {before} != {after} + {moved}")
        both = con.execute("SELECT COUNT(*) FROM matches m JOIN matches_excluded x ON x.id = m.id").fetchone()[0]
        if both:
            raise RuntimeError(f"{both} ids in both tables")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"matches_before": before, "matches_after": after, "moved": moved, "already_done": already}


def ensure_tables_tx(con) -> None:
    """ensure_tables without executescript (which would COMMIT our open transaction)."""
    from db.match_exclusions import CREATE_SQL
    for stmt in [s.strip() for s in CREATE_SQL.split(";") if s.strip()]:
        con.execute(stmt)


def restore(con, event_id: str, rnd=None) -> int:
    """Move one registry entry's rows back into `matches` and drop the entry (one transaction)."""
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        cond = "event_id = ?" + ("" if rnd is None else " AND round = ?")
        args = [event_id] + ([] if rnd is None else [rnd])
        n = con.execute(f"INSERT INTO matches ({COLS}) SELECT {COLS} FROM matches_excluded WHERE {cond}",
                        args).rowcount
        con.execute(f"DELETE FROM matches_excluded WHERE {cond}", args)
        con.execute("DELETE FROM excluded_events WHERE event_id = ? AND " +
                    ("round IS NULL" if rnd is None else "round = ?"), args)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def cmd_commit(a) -> int:
    from db.database import DB_PATH
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    if plan["unproven"]:
        raise SystemExit("plan has unproven rows -- refusing")
    if plan["plan_sha256"] != _sha({"entries": plan["entries"], "row_ids": plan["row_ids"]}):
        raise SystemExit("plan file was edited after prove -- refusing")
    db = Path(DB_PATH)
    ok = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check before: {ok}")
    backup = db.with_name(f"mtg_meta.backup-{datetime.now():%Y-%m-%d}-pre-quarantine.db")
    if backup.exists():
        raise SystemExit(f"{backup} exists -- refusing to overwrite")
    con = sqlite3.connect(db, timeout=60)
    res = quarantine(con, plan, backup)
    res["integrity_check"] = con.execute("PRAGMA integrity_check").fetchone()[0]
    res["backup"] = str(backup)
    res["plan_sha256"] = plan["plan_sha256"]
    out = OUT_DIR / f"quarantine-applied-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0 if res["integrity_check"] == "ok" else 1


def cmd_restore(a) -> int:
    from db.database import DB_PATH
    n = restore(sqlite3.connect(DB_PATH, timeout=60), a.event, a.round)
    print(f"restored {n} rows of {a.event}" + ("" if a.round is None else f" round {a.round}"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prove")
    p.add_argument("--refetch", action="store_true")
    c = sub.add_parser("commit")
    c.add_argument("--plan", required=True)
    t = sub.add_parser("retag")
    t.add_argument("--plan", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--event", required=True)
    r.add_argument("--round", type=int)
    a = ap.parse_args(argv)
    return {"prove": cmd_prove, "commit": cmd_commit, "retag": cmd_retag, "restore": cmd_restore}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
