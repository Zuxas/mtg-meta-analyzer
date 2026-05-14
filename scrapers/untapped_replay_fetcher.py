"""
untapped_replay_fetcher.py
==========================

Fetches game replay logs from mtga.untapped.gg's public upload-log endpoint.
Stores them gzipped on disk under data/untapped/replays/, indexes them in
the meta-analyzer SQLite database.

Each replay is ~1.3 MB raw / ~250-400 KB gzipped, containing:
  - decks: one entry per game with mainDeck/sideboard grpids
  - log: raw MTGA UnityCrossThreadLogger output (turn-by-turn)
  - userId, playerId, deckId, timestamp

The endpoint is fully PUBLIC - no authentication required. The short_id
in untapped_entries.short_id IS the replay short_id.

Tables added (or extended):

    untapped_replays        index of fetched replays + metadata
                            stores file path + size, NOT the log itself
                            (logs live as gzip files on disk)

Usage (Windows):
    # Fetch all unfetched short_ids that are in untapped_entries
    python scrapers\\untapped_replay_fetcher.py --all-unfetched

    # Fetch a specific short_id
    python scrapers\\untapped_replay_fetcher.py --short-id am2YF629FnPnD2jyAT5o9J

    # Fetch top N by matches_count (most-played decks first)
    python scrapers\\untapped_replay_fetcher.py --top 10

    # Limit + filter by archetype
    python scrapers\\untapped_replay_fetcher.py --top 5 --archetype Azorius

    # Dry run (show what would be fetched, don't actually pull)
    python scrapers\\untapped_replay_fetcher.py --top 5 --dry-run

Default storage:
    Files: <repo-root>/data/untapped/replays/{short_id}.json.gz
    Index: untapped_replays table in mtg_meta.db
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import gzip
import argparse
import sqlite3
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone
from pathlib import Path


API_BASE = "https://api.mtga.untapped.gg"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "mtg_meta.db")
DEFAULT_REPLAY_DIR = str(ROOT / "data" / "untapped" / "replays")

# Be polite to a public endpoint
RATE_LIMIT_SLEEP_SEC = 0.5  # ~2 req/s
TIMEOUT_SEC = 60


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

REPLAYS_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_replays (
        short_id TEXT PRIMARY KEY,
        fetched_at_utc TEXT NOT NULL,
        user_id TEXT,
        player_id TEXT,
        deck_id TEXT,
        match_timestamp TEXT,
        n_games INTEGER,
        deck_name TEXT,
        log_size_bytes INTEGER,
        gz_size_bytes INTEGER,
        file_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_replays_player
    ON untapped_replays(player_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_replays_deck
    ON untapped_replays(deck_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_untapped_replays_fetched_at
    ON untapped_replays(fetched_at_utc)
    """,
    "DROP VIEW IF EXISTS v_untapped_replays_unfetched",
    """
    CREATE VIEW v_untapped_replays_unfetched AS
    SELECT DISTINCT
        e.short_id,
        e.player_name,
        e.archetype_primary,
        e.colors_str,
        e.matches_count,
        e.win_rate,
        e.snapshot_id
    FROM untapped_entries e
    LEFT JOIN untapped_replays r ON e.short_id = r.short_id
    WHERE r.short_id IS NULL
    """,
    "DROP VIEW IF EXISTS v_untapped_replays_with_meta",
    """
    CREATE VIEW v_untapped_replays_with_meta AS
    SELECT
        r.*,
        e.player_name,
        e.archetype_primary,
        e.colors_str,
        e.matches_count AS player_total_matches,
        e.win_rate AS player_win_rate
    FROM untapped_replays r
    LEFT JOIN untapped_entries e ON r.short_id = e.short_id
    """,
]


def init_replay_schema(con):
    cur = con.cursor()
    for ddl in REPLAYS_SCHEMA:
        cur.execute(ddl)
    con.commit()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def fetch_replay(short_id, max_retries=3):
    """Fetch a replay. Returns (status_code, data_or_None).

    status 200 -> data dict
    status 204 -> None (no replay for this short_id)
    status 429 -> retried up to max_retries with backoff from Retry-After / body hint
    other       -> raises
    """
    url = f"{API_BASE}/api/v1/upload-log/{short_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Origin": "https://mtga.untapped.gg",
        "Referer": f"https://mtga.untapped.gg/replay/{short_id}",
    })
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
                code = r.getcode()
                if code == 204:
                    return 204, None
                return code, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read()[:300] if hasattr(e, "read") else b""
            if e.code == 429 and attempt < max_retries:
                # Try Retry-After header first, fall back to parsing body "available in N seconds"
                wait = 0
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra:
                    try: wait = int(ra)
                    except Exception: pass
                if not wait:
                    import re
                    m = re.search(rb"available in (\d+)", body)
                    if m: wait = int(m.group(1))
                wait = max(wait, 5) + 2  # cushion
                print(f"      [429 throttled, sleeping {wait}s and retrying]")
                time.sleep(wait)
                last_err = e
                continue
            raise RuntimeError(f"HTTP {e.code} on /upload-log/{short_id}: {body!r}")
    raise RuntimeError(f"HTTP 429 after {max_retries} retries on /upload-log/{short_id}")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def store_replay(short_id, data, replay_dir):
    """Write replay to gzipped JSON. Returns (file_path, raw_bytes, gz_bytes)."""
    replay_dir.mkdir(parents=True, exist_ok=True)
    file_path = replay_dir / f"{short_id}.json.gz"
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    with gzip.open(file_path, "wb", compresslevel=6) as f:
        f.write(raw)
    return file_path, len(raw), file_path.stat().st_size


def index_replay(con, short_id, data, file_path, raw_bytes, gz_bytes):
    """Upsert a row in untapped_replays."""
    decks = data.get("decks") or []
    deck_name = None
    if decks:
        deck = (decks[0] or {}).get("deck") or {}
        deck_name = deck.get("name")

    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_replays (
            short_id, fetched_at_utc, user_id, player_id, deck_id,
            match_timestamp, n_games, deck_name,
            log_size_bytes, gz_size_bytes, file_path, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(short_id) DO UPDATE SET
            fetched_at_utc=excluded.fetched_at_utc,
            user_id=excluded.user_id,
            player_id=excluded.player_id,
            deck_id=excluded.deck_id,
            match_timestamp=excluded.match_timestamp,
            n_games=excluded.n_games,
            deck_name=excluded.deck_name,
            log_size_bytes=excluded.log_size_bytes,
            gz_size_bytes=excluded.gz_size_bytes,
            file_path=excluded.file_path,
            status=excluded.status
    """, (
        short_id,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        data.get("userId"),
        data.get("playerId"),
        data.get("deckId"),
        data.get("timestamp"),
        len(decks),
        deck_name,
        raw_bytes,
        gz_bytes,
        str(file_path),
        "ok",
    ))
    con.commit()


def fetch_for_short_ids(short_ids, replay_dir=None, db_path=None,
                        rate_sleep=RATE_LIMIT_SLEEP_SEC,
                        progress_callback=None) -> dict:
    """Programmatic counterpart to the CLI. Pulls replays for the given
    short_ids from Untapped, stores .json.gz files, indexes untapped_replays.

    Skips short_ids already in untapped_replays (no_content_204 included --
    don't re-probe nothing).

    progress_callback(i, total, short_id, status_word) is called per fetch
    so a GUI can update a status line / progress bar. status_word is one
    of {"ok", "no_content", "skipped", "error"}.

    Returns stats: {"fetched", "no_content", "skipped", "errors",
                    "total_raw_bytes", "total_gz_bytes"}.
    """
    if replay_dir is None:
        replay_dir = DEFAULT_REPLAY_DIR
    if db_path is None:
        db_path = DEFAULT_DB
    replay_dir = Path(replay_dir)
    short_ids = list(short_ids)

    stats = {"fetched": 0, "no_content": 0, "skipped": 0, "errors": 0,
             "total_raw_bytes": 0, "total_gz_bytes": 0}
    if not short_ids:
        return stats

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    init_replay_schema(con)
    try:
        existing = {
            r[0] for r in con.execute(
                f"SELECT short_id FROM untapped_replays "
                f"WHERE short_id IN ({','.join('?' * len(short_ids))})",
                short_ids,
            ).fetchall()
        }

        total = len(short_ids)
        for i, short_id in enumerate(short_ids, 1):
            if short_id in existing:
                stats["skipped"] += 1
                if progress_callback:
                    progress_callback(i, total, short_id, "skipped")
                continue

            try:
                code, data = fetch_replay(short_id)
                if code == 204:
                    index_no_replay(con, short_id)
                    stats["no_content"] += 1
                    if progress_callback:
                        progress_callback(i, total, short_id, "no_content")
                elif code == 200 and data:
                    file_path, raw, gz = store_replay(short_id, data, replay_dir)
                    index_replay(con, short_id, data, file_path, raw, gz)
                    stats["fetched"] += 1
                    stats["total_raw_bytes"] += raw
                    stats["total_gz_bytes"] += gz
                    if progress_callback:
                        progress_callback(i, total, short_id, "ok")
                else:
                    stats["errors"] += 1
                    if progress_callback:
                        progress_callback(i, total, short_id, "error")
            except Exception:
                stats["errors"] += 1
                if progress_callback:
                    progress_callback(i, total, short_id, "error")

            if i < total and short_id not in existing:
                time.sleep(rate_sleep)
    finally:
        con.close()

    return stats


def index_no_replay(con, short_id):
    """Mark a short_id as having no replay (HTTP 204)."""
    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_replays (
            short_id, fetched_at_utc, file_path, status, log_size_bytes, gz_size_bytes
        ) VALUES (?,?,?,?,0,0)
        ON CONFLICT(short_id) DO UPDATE SET
            fetched_at_utc=excluded.fetched_at_utc,
            status=excluded.status
    """, (
        short_id,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "",
        "no_content_204",
    ))
    con.commit()


# --------------------------------------------------------------------------
# Targeting (which short_ids to pull)
# --------------------------------------------------------------------------

def select_targets(con, args):
    """Return list of (short_id, player_name, archetype) tuples to fetch."""
    cur = con.cursor()
    if args.short_id:
        return [(args.short_id, None, None)]

    where = ["r.short_id IS NULL"]
    params = []
    if args.archetype:
        where.append("LOWER(e.archetype_primary) LIKE ?")
        params.append(f"%{args.archetype.lower()}%")
    if args.player:
        where.append("LOWER(e.player_name) = ?")
        params.append(args.player.lower())
    if args.min_matches:
        where.append("e.matches_count >= ?")
        params.append(args.min_matches)

    where_sql = " AND ".join(where)
    limit_sql = ""
    if args.top:
        limit_sql = "LIMIT ?"
        params.append(args.top)

    sql = f"""
        SELECT DISTINCT e.short_id, e.player_name, e.archetype_primary
        FROM untapped_entries e
        LEFT JOIN untapped_replays r ON e.short_id = r.short_id
        WHERE {where_sql}
        ORDER BY e.matches_count DESC
        {limit_sql}
    """
    cur.execute(sql, params)
    return cur.fetchall()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    ap.add_argument("--replay-dir", default=DEFAULT_REPLAY_DIR,
                    help="Directory to store .json.gz replay files")
    ap.add_argument("--short-id", default=None,
                    help="Fetch a single replay by short_id")
    ap.add_argument("--all-unfetched", action="store_true",
                    help="Fetch every untapped_entries.short_id not yet in untapped_replays")
    ap.add_argument("--top", type=int, default=None,
                    help="Limit to top N short_ids by matches_count")
    ap.add_argument("--archetype", default=None,
                    help="Filter to archetype name substring (case-insensitive)")
    ap.add_argument("--player", default=None,
                    help="Filter to exact player name (case-insensitive)")
    ap.add_argument("--min-matches", type=int, default=None,
                    help="Minimum matches_count for the player entry")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be fetched, don't pull")
    ap.add_argument("--rate-sleep", type=float, default=RATE_LIMIT_SLEEP_SEC,
                    help=f"Seconds between requests (default: {RATE_LIMIT_SLEEP_SEC})")
    args = ap.parse_args()

    if not (args.short_id or args.all_unfetched or args.top):
        ap.error("Must specify --short-id, --all-unfetched, or --top N")

    db_path = Path(args.db)
    if not db_path.exists():
        ap.error(f"DB not found: {db_path}. Run untapped_mythic_scraper.py first.")

    replay_dir = Path(args.replay_dir)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    init_replay_schema(con)

    targets = select_targets(con, args)
    print(f"[+] Targets to fetch: {len(targets)}")
    if not targets:
        print("    Nothing to do (already fetched or no match).")
        con.close()
        return 0

    if args.dry_run:
        print("\n=== DRY RUN ===")
        for sid, player, arch in targets[:50]:
            print(f"  {sid}  player={player}  archetype={arch}")
        if len(targets) > 50:
            print(f"  ... and {len(targets) - 50} more")
        con.close()
        return 0

    print(f"[+] Storing under: {replay_dir}")
    print()

    ok = 0
    no_content = 0
    errors = 0
    total_raw = 0
    total_gz = 0

    for i, (short_id, player, arch) in enumerate(targets, 1):
        try:
            t0 = time.time()
            code, data = fetch_replay(short_id)
            elapsed_ms = int((time.time() - t0) * 1000)

            if code == 204:
                index_no_replay(con, short_id)
                no_content += 1
                print(f"  [{i:3d}/{len(targets)}] {short_id:24s}  204  no replay  ({player})")
            elif code == 200 and data:
                file_path, raw, gz = store_replay(short_id, data, replay_dir)
                index_replay(con, short_id, data, file_path, raw, gz)
                total_raw += raw
                total_gz += gz
                ok += 1
                ratio = (gz / raw * 100) if raw else 0
                print(f"  [{i:3d}/{len(targets)}] {short_id:24s}  200  "
                      f"{raw/1024:6.0f}KB -> {gz/1024:5.0f}KB ({ratio:.0f}%)  "
                      f"{elapsed_ms}ms  player={player} arch={arch}")
            else:
                errors += 1
                print(f"  [{i:3d}/{len(targets)}] {short_id}  unexpected code={code}")
        except Exception as e:
            errors += 1
            print(f"  [{i:3d}/{len(targets)}] {short_id}  ERROR: {e}")

        if i < len(targets):
            time.sleep(args.rate_sleep)

    con.close()
    print()
    print(f"=== Summary ===")
    print(f"  fetched:     {ok}")
    print(f"  no_content:  {no_content}")
    print(f"  errors:      {errors}")
    print(f"  total raw:   {total_raw/1024/1024:.1f} MB")
    print(f"  total gz:    {total_gz/1024/1024:.1f} MB")
    if total_raw:
        print(f"  compression: {total_gz/total_raw*100:.0f}%")


if __name__ == "__main__":
    sys.exit(main() or 0)
