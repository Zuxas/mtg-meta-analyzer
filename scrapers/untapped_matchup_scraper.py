"""
untapped_matchup_scraper.py
============================

Pulls archetype matchup matrix from the public archetype_matchups_showcase
endpoint. This is the only matchup endpoint that doesn't require premium auth.

Caveats:
  - Endpoint takes NO parameters - returns whatever Untapped curates
  - Currently scoped to ONE meta_period (the previous Standard Bo1 release period)
  - Only 7 "showcase" opponents (the meta-defining decks)
  - 70-90 friendly archetypes get matchup data vs those 7 opponents
  - Sample sizes are huge (typically 1k-19k matches per cell)

Despite these caveats, this gives you REAL win rates per matchup that the
free meta endpoint does not. Useful for directional gauntlet calibration
even though the format/period is constrained.

Usage:
    python scrapers\\untapped_matchup_scraper.py
    python scrapers\\untapped_matchup_scraper.py --archetype "Azorius Tempo"
    python scrapers\\untapped_matchup_scraper.py --opponent "Mono-Green Landfall"
"""

import sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import json
import argparse
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict


API_BASE = "https://api.mtga.untapped.gg"
UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "mtg_meta.db")
DEFAULT_ARCHIVE = str(ROOT / "data" / "untapped")


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_matchup_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at_utc TEXT NOT NULL,
        meta_period_id INTEGER NOT NULL,
        n_pairs INTEGER NOT NULL,
        n_friendly INTEGER NOT NULL,
        n_opponents INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_matchups (
        snapshot_id INTEGER NOT NULL REFERENCES untapped_matchup_snapshots(id) ON DELETE CASCADE,
        meta_period_id INTEGER NOT NULL,
        friendly_pgid INTEGER NOT NULL,
        opponent_pgid INTEGER NOT NULL,
        observed_match_count INTEGER NOT NULL,
        matches_won INTEGER NOT NULL,
        win_rate REAL NOT NULL,
        PRIMARY KEY (snapshot_id, friendly_pgid, opponent_pgid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_matchups_friendly ON untapped_matchups(friendly_pgid)",
    "CREATE INDEX IF NOT EXISTS idx_matchups_opponent ON untapped_matchups(opponent_pgid)",
    "DROP VIEW IF EXISTS v_untapped_matchups_named",
    """
    CREATE VIEW v_untapped_matchups_named AS
    SELECT
        m.meta_period_id,
        s.captured_at_utc,
        m.friendly_pgid,
        f_arch.archetype_name AS friendly_archetype,
        f_arch.colors_str AS friendly_colors,
        m.opponent_pgid,
        o_arch.archetype_name AS opponent_archetype,
        o_arch.colors_str AS opponent_colors,
        m.observed_match_count,
        m.matches_won,
        m.win_rate
    FROM untapped_matchups m
    JOIN untapped_matchup_snapshots s ON m.snapshot_id = s.id
    LEFT JOIN (
        SELECT primary_tag_group_id, archetype_name, colors_str
        FROM untapped_meta_archetypes
        WHERE archetype_name IS NOT NULL
        GROUP BY primary_tag_group_id
    ) f_arch ON m.friendly_pgid = f_arch.primary_tag_group_id
    LEFT JOIN (
        SELECT primary_tag_group_id, archetype_name, colors_str
        FROM untapped_meta_archetypes
        WHERE archetype_name IS NOT NULL
        GROUP BY primary_tag_group_id
    ) o_arch ON m.opponent_pgid = o_arch.primary_tag_group_id
    WHERE s.id = (SELECT MAX(id) FROM untapped_matchup_snapshots)
    """,
]


def fetch_json(path):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Origin": "https://mtga.untapped.gg",
        "Referer": "https://mtga.untapped.gg/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def init_schema(con):
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    con.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--archetype", default=None,
                    help="Filter friendly archetype (substring match) on output")
    ap.add_argument("--opponent", default=None,
                    help="Filter opponent archetype (substring match) on output")
    ap.add_argument("--min-matches", type=int, default=0,
                    help="Hide matchups with fewer than N observed matches")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        ap.error(f"DB not found: {db_path}")

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    init_schema(con)

    print(f"[+] Fetching archetype_matchups_showcase ...")
    data = fetch_json("/api/v1/analytics/query/archetype_matchups_showcase")
    print(f"    -> {len(data)} matchup pairs")

    # Compute summary
    friendly = set(r["friendly_archetype"] for r in data)
    opponents = set(r["opponent_archetype"] for r in data)
    meta_periods = set(r["meta_period_id"] for r in data)
    pid = next(iter(meta_periods)) if len(meta_periods) == 1 else None

    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_matchup_snapshots
            (captured_at_utc, meta_period_id, n_pairs, n_friendly, n_opponents)
        VALUES (?,?,?,?,?)
    """, (datetime.now(timezone.utc).isoformat(timespec="seconds"),
          pid or 0, len(data), len(friendly), len(opponents)))
    snapshot_id = cur.lastrowid

    rows = []
    for r in data:
        n = int(r["observed_match_count"])
        w = int(r["matches_won"])
        wr = (w / n * 100) if n else 0.0
        rows.append((
            snapshot_id, r["meta_period_id"],
            r["friendly_archetype"], r["opponent_archetype"],
            n, w, round(wr, 2),
        ))
    cur.executemany("""
        INSERT INTO untapped_matchups
            (snapshot_id, meta_period_id, friendly_pgid, opponent_pgid,
             observed_match_count, matches_won, win_rate)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    con.commit()

    print(f"[+] DB: snapshot id={snapshot_id}, {len(data)} matchup rows inserted")

    if not args.no_archive:
        archive_dir = Path(args.archive) / "matchups"
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        ap_path = archive_dir / f"matchups_showcase_pid{pid}_{stamp}.json"
        with open(ap_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[+] Archive: {ap_path}")

    # Lookup the meta period info
    cur.execute("""
        SELECT id, event_name, description, start_ts, end_ts
        FROM untapped_meta_periods WHERE id = ?
    """, (pid,))
    mp = cur.fetchone()
    if mp:
        print(f"[+] Meta period: id={mp[0]} event={mp[1]} desc={mp[2]!r} {mp[3][:10]} -> {mp[4][:10]}")

    # Summary table
    print()
    if args.archetype:
        print(f"=== Matchups for archetypes matching '{args.archetype}' ===")
        sql = """
            SELECT friendly_archetype, friendly_colors, opponent_archetype, opponent_colors,
                   observed_match_count, win_rate
            FROM v_untapped_matchups_named
            WHERE LOWER(friendly_archetype) LIKE ?
              AND observed_match_count >= ?
            ORDER BY friendly_archetype, observed_match_count DESC
        """
        cur.execute(sql, (f"%{args.archetype.lower()}%", args.min_matches))
    elif args.opponent:
        print(f"=== Matchups vs opponents matching '{args.opponent}' ===")
        sql = """
            SELECT friendly_archetype, friendly_colors, opponent_archetype, opponent_colors,
                   observed_match_count, win_rate
            FROM v_untapped_matchups_named
            WHERE LOWER(opponent_archetype) LIKE ?
              AND observed_match_count >= ?
            ORDER BY win_rate ASC, observed_match_count DESC
        """
        cur.execute(sql, (f"%{args.opponent.lower()}%", args.min_matches))
    else:
        # Default: top 20 most-played friendly archetypes, all 7 opponents
        print(f"=== Top friendly archetypes vs the 7 showcase opponents ===")
        sql = """
            SELECT friendly_archetype, friendly_colors, opponent_archetype, opponent_colors,
                   observed_match_count, win_rate
            FROM v_untapped_matchups_named
            WHERE friendly_archetype IS NOT NULL
              AND observed_match_count >= ?
            ORDER BY friendly_archetype, observed_match_count DESC
        """
        cur.execute(sql, (max(args.min_matches, 500),))

    last_friendly = None
    for r in cur.fetchall():
        f_arch, f_col, o_arch, o_col, n, wr = r
        if last_friendly != f_arch:
            print(f"\n  {f_arch} ({f_col}):")
            last_friendly = f_arch
        marker = "++" if wr >= 55 else ("--" if wr <= 45 else "  ")
        print(f"    {marker} vs {o_arch:<25s} ({o_col:<5s})  n={n:>5}  WR={wr:>5.1f}%")

    con.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
