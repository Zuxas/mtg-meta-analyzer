"""Relabel Melee `matches` rows stored with fuzzy-guessed archetypes (before 2026-10-01).

Until 00a4f54 the Melee scraper called normalize(deck_name, fmt): the format string landed in
normalize's positional `fuzzy` flag, so every stored Melee label since the pipeline began
(98dd83c, 2026-03-21) went through fuzzy matching ('Mono-Green Broodscale' -> 'Mono Red Aggro').
The raw published deck names were never stored, so they are recovered by re-reading the pairings.

  python -m scripts.relabel_melee_history fetch  [--format modern]   # resumable, read-only on the DB
  python -m scripts.relabel_melee_history plan   [--format modern]   # dry-run manifest + report
  python -m scripts.relabel_melee_history apply  --manifest M --buckets fuzzy_fix,...   # one transaction

Every command refuses to run from a checkout with uncommitted changes to the code it depends on,
and records that commit in the cache files / manifest; apply requires the manifest's commit.

Scope: source='mtgmelee' AND id <= CUTOFF_ID (the max matches.id in the pre-backfill backup
mtg_meta.backup-2026-10-01-pre-melee-backfill.db; every later row was stored by the fixed mapper).
A row is joined to the re-scrape on its UNIQUE key (event_id, round, player1, player2). Rows that
cannot be joined with certainty are reported and never touched; nothing is inserted or deleted.
The new label is the fixed scraper's own `_map_archetype` (exact canonical / alias, else the
published name, pre-normalized) -- no fuzzy, no inventing.

Row buckets (a matched row takes its worst slot, in BUCKET_ORDER):
  unlabelled   a recovered deck name maps to "" (blank / junk such as 'Decklist'); the fixed scraper
               would not have stored the row -- left unchanged, reported for a later decision
  other        any other difference (e.g. an alias target changed)
  fuzzy_guess  raw name has no exact alias and the stored label differs: a fuzzy guess that today's
               fuzzy normalize does not reproduce
  fuzzy_fix    stored label is one of the best-scoring fuzzy matches for the raw name today (the bug
               reproduced; the whole tie set counts, normalize() picks among ties by hash order)
  alias_drift  raw name has an exact alias (added later); stored label == the pre-normalized raw name
  unchanged
Unresolved (never applied):
  unmatched    no pairing with the row's key in a complete re-scrape (cause unknown -- not presumed)
  ambiguous    the key occurs more than once in the re-scrape
  unrecovered  the event has no complete re-scrape (missing cache, failed or zero rounds)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CUTOFF_ID = 7812278
CACHE_DIR = Path(r"E:\mtg-data\raw\melee_relabel")
OUT_DIR = Path(r"E:\mtg-data\reports\melee_relabel")
SCOPE_SQL = "source = 'mtgmelee' AND id <= ?"
BUCKET_ORDER = ("unlabelled", "other", "fuzzy_guess", "fuzzy_fix", "alias_drift", "unchanged")
UNRESOLVED = ("unmatched", "ambiguous", "unrecovered")
APPLYABLE = ("fuzzy_fix", "fuzzy_guess", "alias_drift", "other")
CODE_FILES = ("scripts/relabel_melee_history.py", "scrapers/mtgmelee_scraper.py",
              "analysis/archetypes.py", "scrapers/constants.py")
SAMPLES_PER_BUCKET = 15


def _db_path(arg) -> Path:
    from db.database import DB_PATH
    return Path(arg or DB_PATH)


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _code_commit() -> str:
    """HEAD of this checkout; refuses if the code this script depends on has uncommitted changes."""
    git = ["git", "-C", str(REPO)]
    dirty = subprocess.run(git + ["status", "--porcelain", "--", *CODE_FILES],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise SystemExit(f"uncommitted changes in the relabel code -- commit first:\n{dirty}")
    return subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _mapping_version() -> str:
    """Content hash of the alias table the new labels come from."""
    from analysis.archetypes import ALIASES
    return _sha(sorted(ALIASES.items()))


# ---------------------------------------------------------------------------
# fetch: recover raw published deck names (network; never writes the DB)
# ---------------------------------------------------------------------------

def _fetch_event(tid: str) -> dict:
    """All decided pairings of one tournament with their raw deck names. Unlike
    fetch_tournament_pairings, a failed or truncated round is recorded, not swallowed."""
    from scrapers import mtgmelee_scraper as ms
    session = ms._session()
    rounds = ms._get_round_ids(session, tid)
    out = {"tid": tid, "fetched_at": _now(), "rounds": len(rounds), "failed_rounds": [],
           "pairings": []}
    for rid, rname in rounds:
        rnd = ms._round_number(rname)
        start, rows = 0, []
        try:
            while True:
                resp = session.post(
                    ms._ROUND_URL.format(rid=rid), data=ms._pairing_dt_payload(start, 500),
                    headers={"X-Requested-With": "XMLHttpRequest",
                             "Referer": ms._VIEW_URL.format(tid=tid),
                             "Accept": "application/json, text/javascript, */*; q=0.01"},
                    timeout=30)
                resp.raise_for_status()
                payload = resp.json()
                page = payload.get("data", [])
                rows += page
                total = payload.get("recordsTotal", len(rows))
                time.sleep(ms._SLEEP)
                if not page or len(rows) >= total:
                    break
                start += len(page)
        except Exception as exc:                                   # noqa: BLE001
            out["failed_rounds"].append({"round": rname, "error": str(exc)[:200]})
            time.sleep(ms._SLEEP)
            continue
        for row in rows:
            m = ms._parse_pairing_row(row, rnd)
            if m:
                out["pairings"].append(m)
    return out


def _complete(d: dict | None) -> bool:
    return bool(d) and d.get("rounds", 0) > 0 and not d.get("failed_rounds") and "code_commit" in d


def _load_cache(tid: str) -> dict | None:
    path = CACHE_DIR / f"{tid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cmd_fetch(a) -> int:
    commit = _code_commit()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    con = _ro(_db_path(a.db))
    q = (f"SELECT event_id, format, COUNT(*) FROM matches WHERE {SCOPE_SQL}"
         + (" AND format = ?" if a.format else "") + " GROUP BY event_id ORDER BY format, event_id")
    events = con.execute(q, (CUTOFF_ID, a.format) if a.format else (CUTOFF_ID,)).fetchall()
    todo = [(e, f, n) for e, f, n in events
            if a.refetch or not _complete(_load_cache(e.removeprefix("mtgmelee_")))]
    print(f"{len(events)} events in scope, {len(todo)} to fetch (code {commit[:10]})", flush=True)
    for i, (eid, fmt, n) in enumerate(todo, 1):
        tid = eid.removeprefix("mtgmelee_")
        try:
            data = _fetch_event(tid)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  [{i}/{len(todo)}] {eid} FAILED: {exc}", flush=True)
            continue
        data["format"] = fmt
        data["code_commit"] = commit
        tmp = CACHE_DIR / f"{tid}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_DIR / f"{tid}.json")
        print(f"  [{i}/{len(todo)}] {eid} {fmt}: stored {n}, recovered {len(data['pairings'])}, "
              f"rounds {data['rounds']}, failed {len(data['failed_rounds'])}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# plan: pure, deterministic -- the same function runs inside apply
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _fuzzy_candidates(stripped: str) -> frozenset:
    """Every label the buggy fuzzy step could have returned for this name today: all canonical
    names tied at the best score >= 85. normalize() takes the first of a tie in set order, which
    varies with PYTHONHASHSEED -- so 'the' fuzzy answer is not reproducible, the tie set is."""
    from thefuzz import process as fuzz_process
    from analysis.archetypes import _CANONICAL_NAMES
    scored = fuzz_process.extract(stripped, sorted(_CANONICAL_NAMES), limit=None)
    best = max((s for _, s in scored), default=0)
    return frozenset(n for n, s in scored if s == best) if best >= 85 else frozenset()


@lru_cache(maxsize=None)
def _slot(stored: str, raw: str) -> tuple[str, str]:
    """(new label, bucket) for one deck slot."""
    from analysis.archetypes import ALIASES, _CANONICAL_NAMES, pre_normalize
    from scrapers.mtgmelee_scraper import _map_archetype
    new = _map_archetype(raw, "")
    if new == "":
        return "", "unlabelled"
    if new == stored:
        return new, "unchanged"
    stripped = pre_normalize(raw.strip())
    exact_hit = stripped in _CANONICAL_NAMES or bool(ALIASES.get(stripped.lower()))
    if not exact_hit and stored in _fuzzy_candidates(stripped):
        return new, "fuzzy_fix"
    if not exact_hit:
        return new, "fuzzy_guess"
    if stored == stripped:
        return new, "alias_drift"
    return new, "other"


def _winner(result: str, a1: str, a2: str):
    return a1 if result == "player1" else a2 if result == "player2" else None


def build_plan(con: sqlite3.Connection, fmt: str | None = None, code_commit: str = "") -> dict:
    q = (f"SELECT id, event_id, round, player1, player2, player1_arch, player2_arch, winner_arch, "
         f"result, format, event_date, source FROM matches WHERE {SCOPE_SQL}"
         + (" AND format = ?" if fmt else "") + " ORDER BY id")
    rows = con.execute(q, (CUTOFF_ID, fmt) if fmt else (CUTOFF_ID,)).fetchall()
    db_hash = hashlib.sha256()
    caches, cache_hashes = {}, {}
    changes, held = [], defaultdict(list)          # held: unlabelled + unresolved rows
    per_event = defaultdict(Counter)
    transitions = Counter()
    for row in rows:
        (rid, eid, rnd, p1, p2, a1, a2, win, result, f, _date, _src) = row
        db_hash.update(json.dumps(row, ensure_ascii=False).encode())
        tid = eid.removeprefix("mtgmelee_")
        if tid not in caches:
            d = _load_cache(tid)
            cache_hashes[tid] = _sha(d) if d is not None else None
            if _complete(d):
                index = defaultdict(list)
                for m in d["pairings"]:
                    index[(m["round"], m["player1"], m["player2"])].append(m)
                caches[tid] = index
            else:
                caches[tid] = None
        index = caches[tid]
        base = {"id": rid, "event_id": eid, "format": f, "result": result, "old": [a1, a2, win]}
        if index is None:
            bucket, hits = "unrecovered", []
        else:
            hits = index.get((rnd, p1, p2), [])
            bucket = "unmatched" if not hits else "ambiguous" if len(hits) > 1 else None
        if bucket:
            per_event[eid][bucket] += 1
            held[bucket].append(base)
            continue
        m = hits[0]
        (n1, b1), (n2, b2) = _slot(a1, m["player1_deck"]), _slot(a2, m["player2_deck"])
        bucket = min((b1, b2), key=BUCKET_ORDER.index)
        per_event[eid][bucket] += 1
        if bucket == "unchanged":
            continue
        rec = {**base, "bucket": bucket, "raw": [m["player1_deck"], m["player2_deck"]],
               "slot_buckets": [b1, b2]}
        if bucket == "unlabelled":
            held[bucket].append(rec)
            continue
        rec["new"] = [n1, n2, _winner(result, n1, n2)]
        changes.append(rec)
        for old, new, b in ((a1, n1, b1), (a2, n2, b2)):
            if old != new:
                transitions[(f, b, old, new)] += 1
    totals = Counter()
    for c in per_event.values():
        totals.update(c)
    events = {e: dict(c) for e, c in sorted(per_event.items())}
    coverage = {"events": len(events),
                "events_complete": sum(1 for t in caches.values() if t is not None),
                "events_unrecovered": sorted(e for e, c in events.items() if c.get("unrecovered"))}
    inputs = {"cutoff_id": CUTOFF_ID, "format": fmt or "all", "code_commit": code_commit,
              "mapping_version": _mapping_version(), "db_rows_sha256": db_hash.hexdigest(),
              "cache_sha256": _sha(sorted(cache_hashes.items())),
              "changes_sha256": _sha([(c["id"], c["bucket"], c["raw"], c["old"], c["new"])
                                      for c in changes]),
              "held_sha256": _sha({b: [h["id"] for h in v] for b, v in sorted(held.items())})}
    return {"generated_at": _now(), **inputs, "manifest_sha256": _sha(inputs),
            "rows_in_scope": len(rows), "totals": dict(totals), "coverage": coverage,
            "per_event": events,
            "transitions": [{"format": f, "bucket": b, "old": o, "new": n, "slots": k}
                            for (f, b, o, n), k in transitions.most_common()],
            "changes": changes, "held": dict(held)}


def _samples(recs: list[dict], k: int = SAMPLES_PER_BUCKET) -> list[dict]:
    """Deterministic spread-out sample (by hashed id), so it is not just the oldest event."""
    return sorted(recs, key=lambda c: hashlib.sha256(str(c["id"]).encode()).hexdigest())[:k]


def _report_md(p: dict, applied: dict | None = None) -> str:
    """Human summary. No player names (the manifest JSON carries row ids only, too)."""
    cov = p["coverage"]
    L = [f"# Melee relabel {'APPLIED' if applied else 'dry run'} -- {p['format']} -- {p['generated_at']}",
         "", f"- Scope: source='mtgmelee' AND id <= {p['cutoff_id']} -> **{p['rows_in_scope']:,} rows**, "
         f"{cov['events']} events",
         f"- Event coverage: {cov['events_complete']} of {cov['events']} events fully re-scraped; "
         f"{len(cov['events_unrecovered'])} unrecovered",
         f"- Code `{p['code_commit'][:10]}`, mapping `{p['mapping_version'][:12]}`, "
         f"DB rows `{p['db_rows_sha256'][:12]}`, cache `{p['cache_sha256'][:12]}`",
         f"- **Manifest sha256 `{p['manifest_sha256']}`**", "",
         "| bucket | rows | applied? |", "|---|---:|---|"]
    for b in (*BUCKET_ORDER, *UNRESOLVED):
        note = ("never (left unchanged)" if b in ("unlabelled", *UNRESOLVED)
                else "-" if b == "unchanged" else "only if approved")
        L.append(f"| {b} | {p['totals'].get(b, 0):,} | {note} |")
    matched = sum(p["totals"].get(b, 0) for b in BUCKET_ORDER)
    L += ["", f"Matched {matched:,} / unmatched {p['totals'].get('unmatched', 0):,} / "
          f"ambiguous {p['totals'].get('ambiguous', 0):,} / unrecovered "
          f"{p['totals'].get('unrecovered', 0):,}"]
    by_fmt = Counter(c["format"] for c in p["changes"])
    L += ["", "Rows with a proposed change, by format: "
          + (", ".join(f"{k} {v:,}" for k, v in sorted(by_fmt.items())) or "none")]
    L += ["", "## Top label transitions (deck slots)", "", "| format | bucket | old | new | slots |",
          "|---|---|---|---|---:|"]
    for t in p["transitions"][:60]:
        L.append(f"| {t['format']} | {t['bucket']} | {t['old']} | {t['new']} | {t['slots']:,} |")
    L += ["", f"## Samples ({SAMPLES_PER_BUCKET} per bucket; row id, event, published names, old -> new)"]
    for b in APPLYABLE:
        recs = [c for c in p["changes"] if c["bucket"] == b]
        if recs:
            L += ["", f"### {b} ({len(recs):,} rows)", "", "| id | event | published | old | new |",
                  "|---:|---|---|---|---|"]
            for c in _samples(recs):
                L.append(f"| {c['id']} | {c['event_id']} | {c['raw'][0]} / {c['raw'][1]} | "
                         f"{c['old'][0]} / {c['old'][1]} | {c['new'][0]} / {c['new'][1]} |")
    for b, recs in sorted(p["held"].items()):
        L += ["", f"### {b} ({len(recs):,} rows, left unchanged)", "",
              "| id | event | published | stored |", "|---:|---|---|---|"]
        for c in _samples(recs):
            pub = " / ".join(c["raw"]) if "raw" in c else "(no re-scraped pairing)"
            L.append(f"| {c['id']} | {c['event_id']} | {pub} | {c['old'][0]} / {c['old'][1]} |")
    L += ["", "## Per event (events with anything other than unchanged rows)", "",
          "| event | " + " | ".join((*BUCKET_ORDER, *UNRESOLVED)) + " |",
          "|---|" + "---:|" * (len(BUCKET_ORDER) + len(UNRESOLVED))]
    for e, c in p["per_event"].items():
        if any(v for k, v in c.items() if k != "unchanged"):
            L.append(f"| {e} | " + " | ".join(str(c.get(b, 0)) for b in (*BUCKET_ORDER, *UNRESOLVED))
                     + " |")
    if applied:
        L += ["", "## Applied", "", "```", json.dumps(applied, indent=2), "```"]
    return "\n".join(L) + "\n"


def cmd_plan(a) -> int:
    p = build_plan(_ro(_db_path(a.db)), a.format, _code_commit())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"dryrun-{p['format']}-{datetime.now():%Y%m%d-%H%M%S}"
    stem.with_suffix(".json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    stem.with_suffix(".md").write_text(_report_md(p), encoding="utf-8")
    print(json.dumps(p["totals"]), f"changes={len(p['changes'])}", f"manifest={p['manifest_sha256'][:16]}")
    print(f"manifest: {stem.with_suffix('.json')}")
    return 0


# ---------------------------------------------------------------------------
# apply: integrity -> BEGIN IMMEDIATE -> backup -> re-plan + hash check -> update -> checks -> COMMIT
# ---------------------------------------------------------------------------

_INCONSISTENT = """SELECT COUNT(*) FROM matches WHERE NOT (
    (result='player1' AND winner_arch=player1_arch) OR (result='player2' AND winner_arch=player2_arch)
    OR (result='draw' AND winner_arch IS NULL))"""


def cmd_apply(a) -> int:
    db = _db_path(a.db)
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    buckets = set(a.buckets.split(","))
    if not buckets <= set(APPLYABLE):
        raise SystemExit(f"--buckets must be a subset of {APPLYABLE}")
    commit = _code_commit()
    if commit != manifest["code_commit"]:
        raise SystemExit(f"manifest was built by {manifest['code_commit'][:10]}, this is {commit[:10]}")
    fmt = None if manifest["format"] == "all" else manifest["format"]
    backup = db.with_name(f"mtg_meta.backup-{datetime.now():%Y-%m-%d}-pre-melee-relabel.db")
    if backup.exists():
        raise SystemExit(f"backup {backup} already exists -- refusing to overwrite")
    ok = _ro(db).execute("PRAGMA integrity_check").fetchone()[0]
    if ok != "ok":
        raise SystemExit(f"integrity_check failed on the live DB: {ok}")

    con = sqlite3.connect(db, timeout=60)
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")                  # no other writer from here to COMMIT
    try:
        # Backup through a second, read-only connection: it sees the last committed state, and no
        # writer can commit while we hold the write lock -> the exact pre-image of this transaction.
        # (Backing up from `con` itself spins forever on the lock it holds.)
        dst = sqlite3.connect(backup)
        _ro(db).backup(dst)
        dst.close()
        ok = _ro(backup).execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"backup integrity_check: {ok}")
        p = build_plan(con, fmt, commit)
        if p["manifest_sha256"] != manifest["manifest_sha256"]:
            diff = [k for k in ("mapping_version", "db_rows_sha256", "cache_sha256", "changes_sha256",
                                "held_sha256") if p[k] != manifest.get(k)]
            raise RuntimeError(f"plan differs from the reviewed manifest ({', '.join(diff)}) -- "
                               "re-run `plan` and review")
        before = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        bad_before = con.execute(_INCONSISTENT).fetchone()[0]
        todo = [c for c in p["changes"] if c["bucket"] in buckets]
        n = 0
        for c in todo:
            (o1, o2, ow), (n1, n2, nw) = c["old"], c["new"]
            n += con.execute(
                "UPDATE matches SET player1_arch=?, player2_arch=?, winner_arch=? "
                "WHERE id=? AND player1_arch=? AND player2_arch=? AND winner_arch IS ? AND result=?",
                (n1, n2, nw, c["id"], o1, o2, ow, c["result"])).rowcount
        if n != len(todo):
            raise RuntimeError(f"updated {n} rows, expected {len(todo)}")
        after = dict(con.execute("SELECT format, COUNT(*) FROM matches GROUP BY format").fetchall())
        if before != after:
            raise RuntimeError(f"row counts moved: {before} -> {after}")
        bad = con.execute(_INCONSISTENT).fetchone()[0]
        if bad != bad_before:
            raise RuntimeError(f"winner/result inconsistencies {bad_before} -> {bad}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    rerun = build_plan(con, fmt, commit)
    left = sum(1 for c in rerun["changes"] if c["bucket"] in buckets)
    applied = {"applied_at": _now(), "manifest_sha256": manifest["manifest_sha256"],
               "backup": str(backup), "buckets": sorted(buckets), "rows_updated": n,
               "row_counts_by_format": after, "integrity_check": ok,
               "rerun_changes_in_applied_buckets": left, "rerun_totals": rerun["totals"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"applied-{manifest['format']}-{datetime.now():%Y%m%d-%H%M%S}"
    stem.with_suffix(".json").write_text(json.dumps(applied, indent=1), encoding="utf-8")
    stem.with_suffix(".md").write_text(_report_md(p, applied), encoding="utf-8")
    print(json.dumps(applied, indent=1))
    return 0 if ok == "ok" and left == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "plan", "apply"):
        s = sub.add_parser(name)
        s.add_argument("--db", type=Path)
        if name != "apply":
            s.add_argument("--format")
        if name == "fetch":
            s.add_argument("--refetch", action="store_true")
        if name == "apply":
            s.add_argument("--manifest", required=True)
            s.add_argument("--buckets", required=True)
    a = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "plan": cmd_plan, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
