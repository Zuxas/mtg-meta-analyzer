"""Correct the `format` tag of one Melee event's `matches` rows, round by round.

Only `format` changes. Built for mtgmelee_391510 (2026-10-02): its page says rounds 1-3 Standard,
4-6 Pauper, top 8 Draft (page saved in E:\\mtg-data\\raw\\melee_relabel\\event_meta\\), and the
re-scraped deck names per round agree; the stored rows had rounds 4-6 tagged standard and one row
per round tagged pauper.

  python -m scripts.fix_melee_event_format --event mtgmelee_391510 --rounds 1-3:standard,4-6:pauper \\
         --expect standard>pauper:47,pauper>standard:3            # dry run
  ... --commit                                                     # backup + one transaction
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT_DIR = Path(r"E:\mtg-data\reports\melee_relabel")
COLS = "id, event_id, round, player1, player2, player1_arch, player2_arch, winner_arch, result, " \
       "format, event_date, source"


def _round_map(spec: str) -> dict[int, str]:
    out = {}
    for part in spec.split(","):
        rng, fmt = part.split(":")
        lo, _, hi = rng.partition("-")
        for rnd in range(int(lo), int(hi or lo) + 1):
            out[rnd] = fmt.strip()
    return out


def _expect(spec: str) -> Counter:
    out = Counter()
    for part in spec.split(","):
        move, n = part.split(":")
        old, new = move.split(">")
        out[(old.strip(), new.strip())] = int(n)
    return out


def plan(con, event_id: str, rounds: dict[int, str]) -> list[tuple]:
    """(id, round, old format, new format) for every row of the event whose format is wrong.
    A stored round that the map does not cover is an error, not a skip."""
    rows = con.execute("SELECT id, round, format FROM matches WHERE event_id = ? AND source = 'mtgmelee' "
                       "ORDER BY id", (event_id,)).fetchall()
    missing = sorted({r for _, r, _ in rows if r not in rounds})
    if missing:
        raise SystemExit(f"rounds {missing} of {event_id} are not in the round map")
    return [(i, r, f, rounds[r]) for i, r, f in rows if f != rounds[r]]


def _snapshot(con, event_id):
    return {r[0]: r for r in con.execute(f"SELECT {COLS} FROM matches WHERE event_id = ?", (event_id,))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", required=True)
    ap.add_argument("--rounds", required=True)
    ap.add_argument("--expect", required=True)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--db", type=Path)
    a = ap.parse_args(argv)
    from db.database import DB_PATH
    db = Path(a.db or DB_PATH)
    rounds, expect = _round_map(a.rounds), _expect(a.expect)

    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    todo = plan(ro, a.event, rounds)
    got = Counter((old, new) for _, _, old, new in todo)
    print(f"{a.event}: {len(todo)} rows to retag {dict(got)}")
    if got != expect:
        raise SystemExit(f"planned moves {dict(got)} != expected {dict(expect)} -- refusing")
    if not a.commit:
        return 0

    ok = ro.execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check before: {ok}")
    stamp = datetime.now().strftime("%Y-%m-%d")
    backup = db.with_name(f"mtg_meta.backup-{stamp}-pre-melee-format-fix.db")
    if backup.exists():
        raise SystemExit(f"{backup} exists -- refusing to overwrite")
    con = sqlite3.connect(db, timeout=60)
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        dst = sqlite3.connect(backup)
        sqlite3.connect(f"file:{db}?mode=ro", uri=True).backup(dst)   # pre-image (we hold the lock)
        dst.close()
        if sqlite3.connect(f"file:{backup}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup integrity_check failed")
        if plan(con, a.event, rounds) != todo:
            raise RuntimeError("plan changed since the dry run")
        before = _snapshot(con, a.event)
        totals_before = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        n = 0
        for rid, _, old, new in todo:
            n += con.execute("UPDATE matches SET format = ? WHERE id = ? AND event_id = ? AND format = ?",
                             (new, rid, a.event, old)).rowcount
        if n != len(todo):
            raise RuntimeError(f"updated {n}, expected {len(todo)}")
        after = _snapshot(con, a.event)
        if set(before) != set(after):
            raise RuntimeError("row set changed")
        fmt_i = COLS.split(", ").index("format")
        for rid in before:
            b, f = list(before[rid]), list(after[rid])
            b[fmt_i] = f[fmt_i] = None
            if b != f:
                raise RuntimeError(f"row {rid}: a column other than format changed")
        totals_after = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        if sum(totals_before.values()) != sum(totals_after.values()):
            raise RuntimeError("total row count changed")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    rerun = plan(con, a.event, rounds)
    per_round = con.execute("SELECT round, format, COUNT(*) FROM matches WHERE event_id = ? "
                            "GROUP BY round, format ORDER BY round", (a.event,)).fetchall()
    report = {"applied_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "event": a.event, "backup": str(backup), "rows_updated": n,
              "moves": {f"{o}>{nw}": k for (o, nw), k in got.items()},
              "format_totals_before": totals_before, "format_totals_after": totals_after,
              "event_rows_by_round_format_after": per_round, "integrity_check": ok,
              "rerun_rows_to_change": len(rerun),
              "evidence": r"E:\mtg-data\raw\melee_relabel\event_meta" + "\\" + a.event.removeprefix("mtgmelee_") + ".html",
              "evidence_sha256": hashlib.sha256(
                  (Path(r"E:\mtg-data\raw\melee_relabel\event_meta") / f"{a.event.removeprefix('mtgmelee_')}.html")
                  .read_bytes()).hexdigest()}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"format-fix-{a.event}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0 if ok == "ok" and not rerun else 1


if __name__ == "__main__":
    sys.exit(main())
