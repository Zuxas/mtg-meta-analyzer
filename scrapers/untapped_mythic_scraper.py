"""
untapped_mythic_scraper.py
==========================

Scrapes the public mtga.untapped.gg mythic leaderboard + archetype tag
dictionary, joins them, and writes both files (CSV/JSON archive) and rows
into the meta-analyzer SQLite database.

Both API endpoints are unauthenticated. No session cookies needed.

Tables written (all prefixed `untapped_*` - kept separate from the main
tournament-data tables, joinable by archetype name + date):

    untapped_snapshots    one row per scrape run
    untapped_entries      one row per (snapshot, short_id) - the per-player data
    untapped_tags         tag dictionary, refreshed when stale (>7 days)

Views created (so the GUI can read these alongside tournament data):

    v_untapped_latest_entries        latest snapshot, decoded
    v_untapped_latest_archetypes     archetype rollup with weighted WR
    v_untapped_archetype_history     time-series of archetype share + WR

Usage (Windows):
    python scrapers\\untapped_mythic_scraper.py
    python scrapers\\untapped_mythic_scraper.py --db "<repo-root>\\data\\mtg_meta.db"
    python scrapers\\untapped_mythic_scraper.py --no-archive
    python scrapers\\untapped_mythic_scraper.py --filter-archetype "Azorius"

Default DB path:
    <repo-root>/data/mtg_meta.db

Default archive path:
    <repo-root>/data/untapped/
"""

import sys
# UTF-8 stdout for Windows + emoji-safe logging
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import argparse
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict


API_BASE = "https://api.mtga.untapped.gg"
UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "mtg_meta.db")
DEFAULT_ARCHIVE = str(ROOT / "data" / "untapped")

# WUBRG bitmask used by Untapped's deck_colors field
COLOR_BITS = [(1, "W"), (2, "U"), (4, "B"), (8, "R"), (16, "G")]

TAGS_REFRESH_DAYS = 7


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def fetch_json(path):
    """GET an API path and return parsed JSON. Raises on HTTP error."""
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://mtga.untapped.gg",
        "Referer": "https://mtga.untapped.gg/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read()[:300] if hasattr(e, "read") else b""
        raise RuntimeError(f"HTTP {e.code} on {path}: {body!r}")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def decode_colors(bitmask):
    """Bitmask -> color string like 'WU' or '-' for colorless."""
    cs = "".join(c for bit, c in COLOR_BITS if bitmask & bit)
    return cs or "-"


def utc_iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Schema setup - idempotent
# --------------------------------------------------------------------------

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at_utc TEXT NOT NULL,
        n_entries INTEGER NOT NULL,
        source_url TEXT NOT NULL DEFAULT 'api.mtga.untapped.gg/api/v1/leaderboard/mythic',
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_entries (
        snapshot_id INTEGER NOT NULL REFERENCES untapped_snapshots(id) ON DELETE CASCADE,
        short_id TEXT NOT NULL,
        player_name TEXT,
        player_id TEXT,
        user_id TEXT,
        deck_id TEXT,
        deck_tile_id INTEGER,
        deck_colors INTEGER,
        colors_str TEXT,
        matches_count INTEGER,
        win_rate REAL,
        rank_approx INTEGER,
        season_ordinal INTEGER,
        meta_period_id INTEGER,
        primary_tags TEXT,
        archetype_primary TEXT,
        timestamp_unix INTEGER,
        PRIMARY KEY (snapshot_id, short_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_tags (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        type INTEGER,
        color INTEGER,
        default_ptg INTEGER,
        display_name TEXT,
        created TEXT,
        last_refreshed_utc TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_entries_archetype
    ON untapped_entries(archetype_primary, snapshot_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_entries_player
    ON untapped_entries(player_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_entries_short_id
    ON untapped_entries(short_id)
    """,
]

VIEWS = [
    "DROP VIEW IF EXISTS v_untapped_latest_entries",
    """
    CREATE VIEW v_untapped_latest_entries AS
    SELECT e.*, s.captured_at_utc
    FROM untapped_entries e
    JOIN untapped_snapshots s ON e.snapshot_id = s.id
    WHERE e.snapshot_id = (SELECT MAX(id) FROM untapped_snapshots)
    """,
    "DROP VIEW IF EXISTS v_untapped_latest_archetypes",
    """
    CREATE VIEW v_untapped_latest_archetypes AS
    SELECT
        archetype_primary AS archetype,
        colors_str AS colors,
        COUNT(*) AS n_players,
        SUM(matches_count) AS total_matches,
        ROUND(SUM(matches_count * win_rate) / NULLIF(SUM(matches_count), 0), 2) AS weighted_wr,
        MAX(captured_at_utc) AS as_of_utc
    FROM v_untapped_latest_entries
    GROUP BY archetype_primary, colors_str
    """,
    "DROP VIEW IF EXISTS v_untapped_archetype_history",
    """
    CREATE VIEW v_untapped_archetype_history AS
    SELECT
        s.captured_at_utc,
        s.id AS snapshot_id,
        e.archetype_primary AS archetype,
        e.colors_str AS colors,
        COUNT(*) AS n_players,
        SUM(e.matches_count) AS total_matches,
        ROUND(SUM(e.matches_count * e.win_rate) / NULLIF(SUM(e.matches_count), 0), 2) AS weighted_wr
    FROM untapped_entries e
    JOIN untapped_snapshots s ON e.snapshot_id = s.id
    GROUP BY s.id, e.archetype_primary, e.colors_str
    """,
]


def init_schema(con):
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    for ddl in VIEWS:
        cur.execute(ddl)
    con.commit()


# --------------------------------------------------------------------------
# Data ops
# --------------------------------------------------------------------------

def tags_are_stale(con):
    cur = con.cursor()
    cur.execute("SELECT MAX(last_refreshed_utc) FROM untapped_tags")
    row = cur.fetchone()
    if not row or not row[0]:
        return True
    try:
        last = datetime.fromisoformat(row[0])
    except Exception:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) > timedelta(days=TAGS_REFRESH_DAYS)


def refresh_tags(con, raw_tags):
    cur = con.cursor()
    now = utc_iso()
    rows = []
    for t in raw_tags:
        meta = t.get("metadata") or {}
        rows.append((
            t["id"],
            t.get("name") or "",
            meta.get("type"),
            meta.get("color"),
            meta.get("default_ptg"),
            meta.get("display_name"),
            t.get("created"),
            now,
        ))
    cur.executemany("""
        INSERT INTO untapped_tags
            (id, name, type, color, default_ptg, display_name, created, last_refreshed_utc)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            type=excluded.type,
            color=excluded.color,
            default_ptg=excluded.default_ptg,
            display_name=excluded.display_name,
            created=excluded.created,
            last_refreshed_utc=excluded.last_refreshed_utc
    """, rows)
    con.commit()


def load_tag_map_from_db(con):
    cur = con.cursor()
    cur.execute("SELECT id, name FROM untapped_tags")
    return dict(cur.fetchall())


def insert_snapshot(con, raw_entries, tag_map, notes=None):
    """Insert a new snapshot row + all its entries. Returns snapshot_id."""
    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_snapshots (captured_at_utc, n_entries, notes)
        VALUES (?, ?, ?)
    """, (utc_iso(), len(raw_entries), notes))
    snapshot_id = cur.lastrowid

    rows = []
    for e in raw_entries:
        primary_tags = e.get("primary_tags") or []
        archetype_primary = None
        for tid in primary_tags:
            name = tag_map.get(tid)
            if name:
                archetype_primary = name
                break
        rows.append((
            snapshot_id,
            e.get("short_id"),
            e.get("player_name"),
            e.get("player_id"),
            e.get("user_id"),
            e.get("deck_id"),
            e.get("deck_tile_id"),
            e.get("deck_colors"),
            decode_colors(e.get("deck_colors") or 0),
            e.get("matches_count", 0),
            e.get("win_rate", 0.0),
            e.get("mythic_leaderboard_place_after"),
            e.get("season_ordinal"),
            e.get("meta_period_id"),
            json.dumps(primary_tags),
            archetype_primary,
            e.get("timestamp"),
        ))

    cur.executemany("""
        INSERT INTO untapped_entries (
            snapshot_id, short_id, player_name, player_id, user_id,
            deck_id, deck_tile_id, deck_colors, colors_str,
            matches_count, win_rate, rank_approx,
            season_ordinal, meta_period_id,
            primary_tags, archetype_primary, timestamp_unix
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    con.commit()
    return snapshot_id


# --------------------------------------------------------------------------
# Archive (CSV/JSON files for portability + diff sanity-check)
# --------------------------------------------------------------------------

def write_csv(path, rows, columns):
    def esc(v):
        s = "" if v is None else str(v)
        if "," in s or '"' in s or "\n" in s:
            s = '"' + s.replace('"', '""') + '"'
        return s
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(columns) + "\n")
        for r in rows:
            f.write(",".join(esc(r.get(c)) for c in columns) + "\n")


def archive_snapshot(out_dir, raw_entries, raw_tags, tag_map, stamp):
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_path = out_dir / f"mythic_{stamp}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(raw_entries, f, indent=2)
    if raw_tags is not None:
        tags_path = out_dir / f"tags_{stamp}.json"
        with open(tags_path, "w", encoding="utf-8") as f:
            json.dump(raw_tags, f, indent=2)

    decorated = []
    for e in raw_entries:
        tags = e.get("primary_tags") or []
        names = [tag_map.get(t, f"#{t}") for t in tags]
        decorated.append({
            "rank_approx": e.get("mythic_leaderboard_place_after"),
            "player": e.get("player_name"),
            "colors": decode_colors(e.get("deck_colors") or 0),
            "matches": e.get("matches_count", 0),
            "win_rate": e.get("win_rate", 0.0),
            "archetype_names": "|".join(names),
            "short_id": e.get("short_id"),
            "player_id": e.get("player_id"),
            "user_id": e.get("user_id"),
        })
    decorated.sort(key=lambda r: (r["rank_approx"] is None, r["rank_approx"] or 1e9, -r["matches"]))

    groups = defaultdict(list)
    for r in decorated:
        primary = r["archetype_names"].split("|")[0] if r["archetype_names"] else "Unknown"
        groups[(primary, r["colors"])].append(r)
    rollup = []
    for (arch, colors), rows in groups.items():
        tm = sum(r["matches"] for r in rows)
        tw = sum(r["matches"] * (r["win_rate"] / 100.0) for r in rows)
        rollup.append({
            "archetype": arch,
            "colors": colors,
            "n_players": len(rows),
            "total_matches": tm,
            "weighted_win_rate": round((tw / tm * 100.0) if tm else 0.0, 2),
            "best_player": max(rows, key=lambda r: r["matches"])["player"],
            "best_player_matches": max(r["matches"] for r in rows),
            "best_short_id": max(rows, key=lambda r: r["matches"])["short_id"],
        })
    rollup.sort(key=lambda r: (-r["total_matches"], -r["weighted_win_rate"]))

    write_csv(out_dir / "archetype_summary.csv", rollup, [
        "archetype", "colors", "n_players", "total_matches",
        "weighted_win_rate", "best_player", "best_player_matches", "best_short_id",
    ])
    write_csv(out_dir / "leaderboard_decoded.csv", decorated, [
        "rank_approx", "player", "colors", "matches", "win_rate",
        "archetype_names", "short_id", "player_id", "user_id",
    ])
    return snap_path, decorated, rollup


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB,
                    help=f"SQLite database path (default: {DEFAULT_DB})")
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE,
                    help=f"Archive directory (default: {DEFAULT_ARCHIVE})")
    ap.add_argument("--no-archive", action="store_true",
                    help="Skip writing archive files (DB only)")
    ap.add_argument("--no-db", action="store_true",
                    help="Skip writing to the DB (archive only)")
    ap.add_argument("--force-tags-refresh", action="store_true",
                    help="Refresh the tags table even if not stale")
    ap.add_argument("--filter-archetype", default=None,
                    help="Print only this archetype on console")
    ap.add_argument("--notes", default=None,
                    help="Notes attached to this snapshot row")
    args = ap.parse_args()

    print(f"[+] Fetching mythic leaderboard ...")
    raw_entries = fetch_json("/api/v1/leaderboard/mythic")
    print(f"    -> {len(raw_entries)} entries")

    tag_map = {}
    raw_tags = None
    con = None
    snapshot_id = None

    if not args.no_db:
        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_path))
        con.execute("PRAGMA foreign_keys = ON")
        init_schema(con)

        need_tag_refresh = args.force_tags_refresh or tags_are_stale(con)
        if need_tag_refresh:
            print(f"[+] Tags stale (or forced) - fetching tag dictionary ...")
            raw_tags = fetch_json("/api/v1/tags")
            print(f"    -> {len(raw_tags)} tags")
            refresh_tags(con, raw_tags)
        else:
            print(f"[+] Tags fresh, skipping pull")

        tag_map = load_tag_map_from_db(con)
        snapshot_id = insert_snapshot(con, raw_entries, tag_map, notes=args.notes)
        print(f"[+] DB: inserted snapshot id={snapshot_id} into {db_path}")

    else:
        print(f"[+] Fetching tags (archive-only mode) ...")
        raw_tags = fetch_json("/api/v1/tags")
        tag_map = {t["id"]: t["name"] for t in raw_tags}
        print(f"    -> {len(tag_map)} tags")

    decorated, rollup = None, None
    if not args.no_archive:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        out_dir = Path(args.archive)
        if raw_tags is None:
            cur = con.cursor()
            cur.execute("""
                SELECT id, name, type, color, default_ptg, display_name, created
                FROM untapped_tags
            """)
            raw_tags = [
                {"id": r[0], "name": r[1], "metadata": {
                    "type": r[2], "color": r[3],
                    "default_ptg": r[4], "display_name": r[5],
                }, "created": r[6]}
                for r in cur.fetchall()
            ]
        snap_path, decorated, rollup = archive_snapshot(
            out_dir, raw_entries, raw_tags, tag_map, stamp,
        )
        print(f"[+] Archive: {snap_path.name} + archetype_summary.csv + "
              f"leaderboard_decoded.csv -> {out_dir}")

    if con is not None:
        con.close()

    if rollup is None:
        groups = defaultdict(list)
        for e in raw_entries:
            tags = e.get("primary_tags") or []
            names = [tag_map.get(t, f"#{t}") for t in tags]
            primary = names[0] if names else "Unknown"
            groups[(primary, decode_colors(e.get("deck_colors") or 0))].append(e)
        rollup = []
        for (arch, colors), rows in groups.items():
            tm = sum(e.get("matches_count", 0) for e in rows)
            tw = sum(e.get("matches_count", 0) * (e.get("win_rate", 0.0) / 100.0) for e in rows)
            rollup.append({
                "archetype": arch, "colors": colors,
                "n_players": len(rows), "total_matches": tm,
                "weighted_win_rate": round((tw / tm * 100.0) if tm else 0.0, 2),
            })
        rollup.sort(key=lambda r: (-r["total_matches"], -r["weighted_win_rate"]))

    print("\n=== Archetype rollup (sorted by total matches) ===")
    print(f"{'archetype':<40}  {'colors':<6}  {'players':<7}  {'matches':<7}  {'WR%':<6}")
    print("-" * 80)
    for r in rollup:
        if args.filter_archetype and args.filter_archetype.lower() not in r["archetype"].lower():
            continue
        print(f"{r['archetype'][:40]:<40}  {r['colors']:<6}  {r['n_players']:<7}  "
              f"{r['total_matches']:<7}  {r['weighted_win_rate']:<6}")


if __name__ == "__main__":
    sys.exit(main())
