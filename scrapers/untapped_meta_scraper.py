"""
untapped_meta_scraper.py
========================

Pulls the public meta-periods list and the per-rank archetype winrate breakdown
for every active format (Standard Bo1 + Bo3, Historic, Alchemy, Explorer,
Timeless, etc). Results write to mtg_meta.db.

This complements untapped_mythic_scraper.py:
  - mythic_scraper -> top ~98 individual decks, snapshot-in-time
  - meta_scraper   -> archetype-level rollup across ALL ranks (bronze..platinum)
                      from FULL ladder population (hundreds of thousands of matches)

Free-tier endpoint exposes BRONZE_TO_PLATINUM. Mythic data is premium-walled.
But platinum is the largest sample and the most-relevant skill tier for ladder
analysis anyway.

Endpoints used (all public, no auth):
    GET /api/v1/meta-periods/active
    GET /api/v1/analytics/query/archetypes_by_event_scope_and_rank_v2/free
        ?MetaPeriodId={int}&RankingClassScopeFilter=BRONZE_TO_PLATINUM
        &MetaPeriodScopeFilter=LAST_7_DAYS  (optional - last 7 days only)

Tables:
    untapped_meta_periods       active meta periods (Standard, Historic, etc) by event
    untapped_meta_archetypes    one row per (snapshot, format, archetype, rank)

Views:
    v_untapped_meta_latest      latest snapshot, one row per (format, archetype, rank)
    v_untapped_meta_skill_curve archetype WR change from bronze->plat (climb/fall signal)

Usage:
    python scrapers\\untapped_meta_scraper.py                    # all formats
    python scrapers\\untapped_meta_scraper.py --format Ladder    # Standard Bo1 only
    python scrapers\\untapped_meta_scraper.py --format Traditional_Ladder  # Standard Bo3
    python scrapers\\untapped_meta_scraper.py --last-7-days
    python scrapers\\untapped_meta_scraper.py --filter-archetype "Boros" --rank platinum
"""

import sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import json
import argparse
import sqlite3
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict


API_BASE = "https://api.mtga.untapped.gg"
UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "mtg_meta.db")
DEFAULT_ARCHIVE = str(ROOT / "data" / "untapped")

RATE_LIMIT_SLEEP_SEC = 0.5
# Bo3 / "Traditional" formats only — Bo1 is mostly noise for tournament prep
BO3_FORMATS = {
    "Traditional_Ladder",            # Standard Bo3
    "Traditional_Historic_Ladder",   # Historic Bo3
    "Traditional_Alchemy_Ladder",    # Alchemy Bo3
    "Traditional_Explorer_Ladder",   # Explorer Bo3 (Pioneer-ish)
    "Traditional_Timeless_Ladder",   # Timeless Bo3
}

BO1_FORMATS = {
    "Ladder",
    "Historic_Ladder",
    "Alchemy_Ladder",
    "Explorer_Ladder",
    "Timeless_Ladder",
    "Play_Brawl_Historic",
}


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_meta_periods (
        id INTEGER PRIMARY KEY,
        predecessor_id INTEGER,
        event_name TEXT NOT NULL,
        description TEXT,
        start_ts TEXT,
        end_ts TEXT,
        legal_sets TEXT,
        last_refreshed_utc TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_meta_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at_utc TEXT NOT NULL,
        meta_period_id INTEGER NOT NULL,
        event_name TEXT NOT NULL,
        scope_filter TEXT NOT NULL,
        last_7_days INTEGER NOT NULL DEFAULT 0,
        n_archetypes INTEGER NOT NULL,
        FOREIGN KEY (meta_period_id) REFERENCES untapped_meta_periods(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_meta_archetypes (
        snapshot_id INTEGER NOT NULL REFERENCES untapped_meta_snapshots(id) ON DELETE CASCADE,
        primary_tag_group_id INTEGER NOT NULL,
        primary_tags TEXT,
        archetype_name TEXT,
        color_byte INTEGER,
        colors_str TEXT,
        color_distribution TEXT,
        key_cards TEXT,
        rank_tier TEXT NOT NULL,
        total_matches INTEGER,
        win_rate REAL,
        avg_seconds INTEGER,
        tier_val REAL,
        PRIMARY KEY (snapshot_id, primary_tag_group_id, rank_tier)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_meta_archetypes_arch ON untapped_meta_archetypes(archetype_name, rank_tier)",
    "CREATE INDEX IF NOT EXISTS idx_meta_archetypes_snap ON untapped_meta_archetypes(snapshot_id)",
    "DROP VIEW IF EXISTS v_untapped_meta_latest",
    """
    CREATE VIEW v_untapped_meta_latest AS
    SELECT
        s.event_name AS format,
        s.captured_at_utc AS as_of,
        s.last_7_days,
        a.archetype_name,
        a.colors_str,
        a.rank_tier,
        a.total_matches,
        a.win_rate,
        a.avg_seconds,
        a.tier_val,
        a.primary_tag_group_id,
        a.color_distribution,
        a.key_cards
    FROM untapped_meta_archetypes a
    JOIN untapped_meta_snapshots s ON a.snapshot_id = s.id
    WHERE s.id IN (
        SELECT MAX(id) FROM untapped_meta_snapshots GROUP BY event_name, last_7_days
    )
    """,
    "DROP VIEW IF EXISTS v_untapped_meta_skill_curve",
    """
    CREATE VIEW v_untapped_meta_skill_curve AS
    SELECT
        l.format,
        l.archetype_name,
        l.colors_str,
        l.last_7_days,
        MAX(CASE WHEN l.rank_tier='bronze'   THEN l.win_rate END) AS bronze_wr,
        MAX(CASE WHEN l.rank_tier='silver'   THEN l.win_rate END) AS silver_wr,
        MAX(CASE WHEN l.rank_tier='gold'     THEN l.win_rate END) AS gold_wr,
        MAX(CASE WHEN l.rank_tier='platinum' THEN l.win_rate END) AS plat_wr,
        MAX(CASE WHEN l.rank_tier='bronze'   THEN l.total_matches END) AS bronze_matches,
        MAX(CASE WHEN l.rank_tier='platinum' THEN l.total_matches END) AS plat_matches,
        ROUND(
            MAX(CASE WHEN l.rank_tier='platinum' THEN l.win_rate END) -
            MAX(CASE WHEN l.rank_tier='bronze' THEN l.win_rate END), 2
        ) AS climb_delta_wr
    FROM v_untapped_meta_latest l
    GROUP BY l.format, l.archetype_name, l.colors_str, l.last_7_days
    """,
]

COLOR_BITS = [(1, "W"), (2, "U"), (4, "B"), (8, "R"), (16, "G")]


def fetch_json(path):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Origin": "https://mtga.untapped.gg",
        "Referer": "https://mtga.untapped.gg/",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        if not body or len(body) < 2:
            return None
        return json.loads(body.decode("utf-8"))


def decode_colors(bitmask):
    cs = "".join(c for bit, c in COLOR_BITS if bitmask & bit)
    return cs or "-"


def utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_schema(con):
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    con.commit()


def refresh_meta_periods(con, raw_periods):
    cur = con.cursor()
    now = utc_iso()
    rows = []
    for p in raw_periods:
        rows.append((
            p["id"], p.get("predecessor_id"), p.get("event_name"),
            p.get("description"), p.get("start_ts"), p.get("end_ts"),
            json.dumps(p.get("legal_sets") or []),
            now,
        ))
    cur.executemany("""
        INSERT INTO untapped_meta_periods
            (id, predecessor_id, event_name, description, start_ts, end_ts, legal_sets, last_refreshed_utc)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            predecessor_id=excluded.predecessor_id,
            event_name=excluded.event_name,
            description=excluded.description,
            start_ts=excluded.start_ts,
            end_ts=excluded.end_ts,
            legal_sets=excluded.legal_sets,
            last_refreshed_utc=excluded.last_refreshed_utc
    """, rows)
    con.commit()


def lookup_archetype_name(con, primary_tags, color_byte):
    """Use untapped_tags + decode_colors to render a friendly archetype name."""
    if not primary_tags:
        return None
    cur = con.cursor()
    names = []
    for tid in primary_tags:
        cur.execute("SELECT name FROM untapped_tags WHERE id = ?", (tid,))
        row = cur.fetchone()
        if row:
            names.append(row[0])
    if not names:
        return None
    # Convention: color tag + theme tag, e.g. "Boros Auras"
    return " ".join(names)


def insert_snapshot(con, raw_archetypes, period_id, event_name, scope_filter,
                    last_7_days):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_meta_snapshots
            (captured_at_utc, meta_period_id, event_name, scope_filter, last_7_days, n_archetypes)
        VALUES (?,?,?,?,?,?)
    """, (utc_iso(), period_id, event_name, scope_filter,
          1 if last_7_days else 0, len(raw_archetypes)))
    snapshot_id = cur.lastrowid

    rows = []
    for entry in raw_archetypes:
        pgid = entry.get("primary_tag_group_id")
        ptags = entry.get("primary_tags") or []
        color_byte = entry.get("color_byte") or 0
        colors_str = decode_colors(color_byte)
        archetype_name = lookup_archetype_name(con, ptags, color_byte)

        stats = entry.get("stats") or {}
        for rank, st in stats.items():
            if not isinstance(st, dict):
                continue
            rows.append((
                snapshot_id,
                pgid,
                json.dumps(ptags),
                archetype_name,
                color_byte,
                colors_str,
                json.dumps(entry.get("color_distribution") or {}),
                json.dumps(entry.get("key_cards") or []),
                rank,
                st.get("total_matches"),
                st.get("winrate"),
                st.get("avg_seconds"),
                st.get("tier_val"),
            ))

    cur.executemany("""
        INSERT OR IGNORE INTO untapped_meta_archetypes (
            snapshot_id, primary_tag_group_id, primary_tags, archetype_name,
            color_byte, colors_str, color_distribution, key_cards,
            rank_tier, total_matches, win_rate, avg_seconds, tier_val
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    con.commit()
    return snapshot_id, len(rows)


def archive_archetypes(out_dir, raw_archetypes, period_id, event_name, last_7_days, stamp):
    """Write a JSON snapshot to disk for portability/diff."""
    out_dir = Path(out_dir) / "meta"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_7d" if last_7_days else ""
    fname = f"meta_{event_name}_pid{period_id}{suffix}_{stamp}.json"
    fpath = out_dir / fname
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(raw_archetypes, f, indent=2)
    return fpath


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--format", default=None,
                    help="event_name to filter (e.g. Traditional_Ladder, Historic_Ladder). "
                         "Default: pull all Bo3 formats only")
    ap.add_argument("--include-bo1", action="store_true",
                    help="Also pull Bo1 (single-game ladder) formats. Default: Bo3 only.")
    ap.add_argument("--all-formats", action="store_true",
                    help="Pull every format (Bo1 + Bo3 + Brawl)")
    ap.add_argument("--last-7-days", action="store_true",
                    help="Pull LAST_7_DAYS slice instead of full meta period")
    ap.add_argument("--filter-archetype", default=None,
                    help="Print only matching archetype on console")
    ap.add_argument("--rank", default=None, choices=["bronze", "silver", "gold", "platinum"],
                    help="Print only this rank tier on console")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        ap.error(f"DB not found: {db_path}. Run untapped_mythic_scraper.py first to create it.")

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    init_schema(con)

    # 1. Pull active periods
    print(f"[+] Fetching active meta periods ...")
    periods = fetch_json("/api/v1/meta-periods/active")
    print(f"    -> {len(periods)} periods across {len(set(p['event_name'] for p in periods))} formats")
    refresh_meta_periods(con, periods)

    # 2. Determine which periods to pull archetypes for
    targets = {}  # event_name -> latest period id
    for p in periods:
        ev = p["event_name"]
        if ev not in targets or p["id"] > targets[ev]:
            targets[ev] = p["id"]

    # Filter by Bo3-only / Bo1+Bo3 / all
    if args.format:
        if args.format not in targets:
            ap.error(f"Unknown format: {args.format}. Available: {sorted(targets.keys())}")
        targets = {args.format: targets[args.format]}
    elif args.all_formats:
        pass  # keep everything
    elif args.include_bo1:
        # keep Bo1 + Bo3, drop only Brawl
        targets = {ev: pid for ev, pid in targets.items()
                   if ev in BO3_FORMATS or ev in BO1_FORMATS - {"Play_Brawl_Historic"}}
    else:
        # default: Bo3 only
        targets = {ev: pid for ev, pid in targets.items() if ev in BO3_FORMATS}

    print(f"[+] Targets to pull: {list(targets.keys())}")

    # 3. Pull each
    scope = "BRONZE_TO_PLATINUM"
    all_summaries = []
    for ev, pid in targets.items():
        params = f"MetaPeriodId={pid}&RankingClassScopeFilter={scope}"
        if args.last_7_days:
            params += "&MetaPeriodScopeFilter=LAST_7_DAYS"
        path = f"/api/v1/analytics/query/archetypes_by_event_scope_and_rank_v2/free?{params}"
        try:
            data = fetch_json(path)
        except urllib.error.HTTPError as e:
            print(f"  ! {ev:30s} pid={pid}  HTTP {e.code}")
            continue
        if not data:
            print(f"  - {ev:30s} pid={pid}  (no data / empty)")
            continue
        snap_id, n_rows = insert_snapshot(con, data, pid, ev, scope, args.last_7_days)
        plat = sum((e.get("stats") or {}).get("platinum", {}).get("total_matches") or 0 for e in data)
        print(f"  + {ev:30s} pid={pid}  archetypes={len(data):3d}  plat_matches={plat:>10,}  rows={n_rows}")
        all_summaries.append((ev, pid, len(data), plat))

        if not args.no_archive:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            apath = archive_archetypes(Path(args.archive), data, pid, ev, args.last_7_days, stamp)

        time.sleep(RATE_LIMIT_SLEEP_SEC)

    # 4. Summary
    if args.filter_archetype or args.rank:
        cur = con.cursor()
        where = []
        params = []
        if args.format:
            where.append("format = ?"); params.append(args.format)
        if args.filter_archetype:
            where.append("LOWER(archetype_name) LIKE ?"); params.append(f"%{args.filter_archetype.lower()}%")
        if args.rank:
            where.append("rank_tier = ?"); params.append(args.rank)
        if args.last_7_days:
            where.append("last_7_days = 1")
        else:
            where.append("last_7_days = 0")
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        sql = f"""
            SELECT format, archetype_name, colors_str, rank_tier, total_matches, win_rate
            FROM v_untapped_meta_latest
            {where_sql}
            ORDER BY format, total_matches DESC NULLS LAST
        """
        cur.execute(sql, params)
        print()
        print(f"=== Filtered results ===")
        print(f"  {'format':<28s} {'archetype':<35s} {'colors':<6s} {'rank':<10s} {'matches':>8s} {'WR%':>6s}")
        print("  " + "-" * 96)
        for r in cur.fetchall():
            arch = (r[1] or "?")[:35]
            colors = r[2] or "-"
            rank = r[3] or "-"
            matches = r[4] if r[4] is not None else 0
            wr = r[5] if r[5] is not None else 0
            print(f"  {r[0]:<28s} {arch:<35s} {colors:<6s} {rank:<10s} {matches:>8} {wr:>6}")

    con.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
