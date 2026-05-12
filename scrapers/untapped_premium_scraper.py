"""
untapped_premium_scraper.py
============================

Pulls premium-tier matchup matrix data using your Untapped account session.
Requires session cookies in untapped_cookies.txt (or env vars).

Endpoint:
    GET /api/v1/analytics/query/archetype_matchups_by_event_scope_and_rank
        ?MetaPeriodId={int}&RankingClassScopeFilter={ALL|BRONZE_TO_PLATINUM|BRONZE_TO_MYTHIC}
        [&MetaPeriodScopeFilter=LAST_7_DAYS]

This complements untapped_matchup_scraper.py (which uses the public showcase
endpoint, limited to ONE prev period and 7 opponents). The premium endpoint:
  - Works on any active meta period (current Standard Bo3, Bo1, Historic, etc)
  - Returns matchup data for ALL archetype pairs (~50+ pairs typical)
  - Per-rank breakdown (Silver, Gold, Platinum, Diamond, Mythic)
  - Per-cell sample sizes 100-500+ matches

Tables:
    untapped_premium_matchup_snapshots
    untapped_premium_matchups

Cookie storage:
    Looks for cookies in (in order):
      1. UNTAPPED_SESSIONID + UNTAPPED_CSRFTOKEN env vars
      2. {script_dir}/untapped_cookies.txt   (Netscape format OR "key=value" lines)
    NEVER commit cookies. Add untapped_cookies.txt to .gitignore.

Usage:
    # First time: create cookies file
    python scrapers\\untapped_premium_scraper.py --setup
    # Then edit data\\untapped\\untapped_cookies.txt with your sessionid + csrftoken

    # All formats current period
    python scrapers\\untapped_premium_scraper.py
    # Just Standard Bo3
    python scrapers\\untapped_premium_scraper.py --format Traditional_Ladder
    # Last 7 days
    python scrapers\\untapped_premium_scraper.py --last-7-days
    # Show one archetype's matchups
    python scrapers\\untapped_premium_scraper.py --archetype "Azorius Tempo" --rank Platinum
"""

import sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import os
import re
import json
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
DEFAULT_ARCHIVE = str(ROOT / "data" / "untapped")
DEFAULT_COOKIES_PATH = str(ROOT / "data" / "untapped" / "untapped_cookies.txt")

RATE_LIMIT_SLEEP_SEC = 0.5

# Bo3 only by default
BO3_FORMATS = {
    "Traditional_Ladder",            # Standard Bo3
    "Traditional_Historic_Ladder",
    "Traditional_Alchemy_Ladder",
    "Traditional_Explorer_Ladder",
    "Traditional_Timeless_Ladder",
}
BO1_FORMATS = {
    "Ladder", "Historic_Ladder", "Alchemy_Ladder",
    "Explorer_Ladder", "Timeless_Ladder",
}

RANK_ORDER = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Mythic"]


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_premium_matchup_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at_utc TEXT NOT NULL,
        meta_period_id INTEGER NOT NULL,
        event_name TEXT NOT NULL,
        scope_filter TEXT NOT NULL,
        last_7_days INTEGER NOT NULL DEFAULT 0,
        n_pairs INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS untapped_premium_matchups (
        snapshot_id INTEGER NOT NULL REFERENCES untapped_premium_matchup_snapshots(id) ON DELETE CASCADE,
        meta_period_id INTEGER NOT NULL,
        ranking_class_before TEXT NOT NULL,
        friendly_pgid INTEGER NOT NULL,
        opponent_pgid INTEGER NOT NULL,
        observed_match_count INTEGER NOT NULL,
        matches_won REAL NOT NULL,
        win_rate REAL NOT NULL,
        PRIMARY KEY (snapshot_id, ranking_class_before, friendly_pgid, opponent_pgid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pm_friendly ON untapped_premium_matchups(friendly_pgid, ranking_class_before)",
    "CREATE INDEX IF NOT EXISTS idx_pm_opponent ON untapped_premium_matchups(opponent_pgid, ranking_class_before)",
    "DROP VIEW IF EXISTS v_untapped_premium_matchups_named",
    """
    CREATE VIEW v_untapped_premium_matchups_named AS
    SELECT
        s.event_name AS format,
        s.captured_at_utc AS as_of,
        s.last_7_days,
        m.ranking_class_before AS rank_tier,
        m.friendly_pgid,
        f_arch.archetype_name AS friendly_archetype,
        f_arch.colors_str AS friendly_colors,
        m.opponent_pgid,
        o_arch.archetype_name AS opponent_archetype,
        o_arch.colors_str AS opponent_colors,
        m.observed_match_count,
        m.matches_won,
        m.win_rate
    FROM untapped_premium_matchups m
    JOIN untapped_premium_matchup_snapshots s ON m.snapshot_id = s.id
    LEFT JOIN (
        SELECT primary_tag_group_id, archetype_name, colors_str
        FROM untapped_meta_archetypes WHERE archetype_name IS NOT NULL
        GROUP BY primary_tag_group_id
    ) f_arch ON m.friendly_pgid = f_arch.primary_tag_group_id
    LEFT JOIN (
        SELECT primary_tag_group_id, archetype_name, colors_str
        FROM untapped_meta_archetypes WHERE archetype_name IS NOT NULL
        GROUP BY primary_tag_group_id
    ) o_arch ON m.opponent_pgid = o_arch.primary_tag_group_id
    WHERE s.id IN (
        SELECT MAX(id) FROM untapped_premium_matchup_snapshots
        GROUP BY event_name, last_7_days
    )
    """,
]


def load_cookies(path_str):
    """Load sessionid + csrftoken from env vars OR a cookies file.

    File format options:
      Netscape:    .domain  TRUE  /  TRUE  EXPIRY  KEY  VALUE
      Simple:      sessionid=xxx
                   csrftoken=yyy
    """
    sid = os.environ.get("UNTAPPED_SESSIONID")
    csrf = os.environ.get("UNTAPPED_CSRFTOKEN")
    if sid and csrf:
        return sid, csrf

    path = Path(path_str)
    if not path.exists():
        return None, None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Netscape format: tab-separated
            if "\t" in line:
                parts = line.split("\t")
                if len(parts) >= 7:
                    name, value = parts[5], parts[6]
                    if name == "sessionid": sid = value
                    elif name == "csrftoken": csrf = value
            # Simple key=value format
            elif "=" in line:
                key, _, val = line.partition("=")
                key = key.strip().lower()
                val = val.strip()
                if key == "sessionid": sid = val
                elif key == "csrftoken": csrf = val
    return sid, csrf


def fetch_json(path, sessionid, csrftoken):
    url = f"{API_BASE}{path}"
    cookie_str = f"sessionid={sessionid}; csrftoken={csrftoken}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Origin": "https://mtga.untapped.gg",
        "Referer": "https://mtga.untapped.gg/",
        "Cookie": cookie_str,
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        if not body or len(body) < 2:
            return None
        return json.loads(body.decode("utf-8"))


def init_schema(con):
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    con.commit()


def insert_matchup_snapshot(con, raw, meta_period_id, event_name, scope, last_7_days):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO untapped_premium_matchup_snapshots
            (captured_at_utc, meta_period_id, event_name, scope_filter, last_7_days, n_pairs)
        VALUES (?,?,?,?,?,?)
    """, (datetime.now(timezone.utc).isoformat(timespec="seconds"),
          meta_period_id, event_name, scope, 1 if last_7_days else 0, len(raw)))
    snap_id = cur.lastrowid

    rows = []
    for r in raw:
        n = int(r["observed_match_count"])
        w = float(r["matches_won"])
        wr = (w / n * 100) if n else 0.0
        rows.append((
            snap_id, r["meta_period_id"], r["ranking_class_before"],
            r["friendly_archetype"], r["opponent_archetype"],
            n, w, round(wr, 2),
        ))
    cur.executemany("""
        INSERT OR IGNORE INTO untapped_premium_matchups
            (snapshot_id, meta_period_id, ranking_class_before,
             friendly_pgid, opponent_pgid,
             observed_match_count, matches_won, win_rate)
        VALUES (?,?,?,?,?,?,?,?)
    """, rows)
    con.commit()
    return snap_id, len(rows)


def setup_cookies_file(path_str):
    """Create a template cookies file with instructions."""
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    template = """# Untapped.gg session cookies for premium endpoints
# Get these from your browser:
#   1. Log in at https://mtga.untapped.gg
#   2. Open DevTools (F12) -> Application -> Cookies -> .mtga.untapped.gg
#   3. Copy values for sessionid and csrftoken below
#
# WARNING: These are session credentials. Never commit this file to git.
# Add to .gitignore.

sessionid=PASTE_YOUR_SESSIONID_HERE
csrftoken=PASTE_YOUR_CSRFTOKEN_HERE
"""
    if path.exists():
        print(f"[+] Cookies file already exists at {path}")
    else:
        path.write_text(template, encoding="utf-8")
        print(f"[+] Created template cookies file: {path}")
    print(f"[+] Edit it with your sessionid + csrftoken from the browser, then run normally.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--cookies", default=DEFAULT_COOKIES_PATH)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--setup", action="store_true",
                    help="Create a template cookies file and exit")
    ap.add_argument("--format", default=None,
                    help="event_name (e.g. Traditional_Ladder, Ladder)")
    ap.add_argument("--include-bo1", action="store_true",
                    help="Pull Bo1 formats too (default: Bo3 only)")
    ap.add_argument("--all-formats", action="store_true",
                    help="Pull every format")
    ap.add_argument("--scope", default="BRONZE_TO_MYTHIC",
                    choices=["ALL", "BRONZE_TO_PLATINUM", "BRONZE_TO_MYTHIC"])
    ap.add_argument("--last-7-days", action="store_true")
    ap.add_argument("--archetype", default=None,
                    help="Print matchups where friendly_archetype matches (substring)")
    ap.add_argument("--rank", default="Platinum",
                    choices=RANK_ORDER + ["all"],
                    help="Filter output to this rank tier (default: Platinum)")
    ap.add_argument("--min-matches", type=int, default=50,
                    help="Hide matchups below this match count (default: 50)")
    args = ap.parse_args()

    if args.setup:
        setup_cookies_file(args.cookies)
        return 0

    sessionid, csrftoken = load_cookies(args.cookies)
    if not sessionid or not csrftoken:
        print(f"[!] No cookies found. Run with --setup, or set UNTAPPED_SESSIONID + UNTAPPED_CSRFTOKEN env vars.")
        print(f"    Cookie path tried: {args.cookies}")
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[!] DB not found: {db_path}. Run untapped_meta_scraper.py first.")
        return 2
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    init_schema(con)

    # Verify auth + premium
    print(f"[+] Verifying auth ...")
    try:
        acct = fetch_json("/api/v1/account", sessionid, csrftoken)
    except urllib.error.HTTPError as e:
        print(f"[!] Auth failed: HTTP {e.code}. Refresh cookies via --setup")
        return 2
    ents = acct.get("entitlements", []) if acct else []
    matchups_ok = "mtga-global-stats-constructed-matchups" in ents
    print(f"    -> logged in as {acct.get('email')}")
    print(f"    -> matchups entitlement: {'YES' if matchups_ok else 'NO'}")
    if not matchups_ok:
        print(f"[!] Account does not have premium matchups entitlement. Aborting.")
        return 2

    # Get active periods
    print(f"[+] Fetching active meta periods ...")
    periods = fetch_json("/api/v1/meta-periods/active", sessionid, csrftoken)

    # Determine targets
    targets = {}
    for p in periods:
        ev = p["event_name"]
        if ev not in targets or p["id"] > targets[ev]:
            targets[ev] = p["id"]

    if args.format:
        if args.format not in targets:
            print(f"[!] Unknown format: {args.format}. Available: {sorted(targets.keys())}")
            return 2
        targets = {args.format: targets[args.format]}
    elif args.all_formats:
        pass
    elif args.include_bo1:
        targets = {ev: pid for ev, pid in targets.items()
                   if ev in BO3_FORMATS or ev in BO1_FORMATS}
    else:
        targets = {ev: pid for ev, pid in targets.items() if ev in BO3_FORMATS}

    print(f"[+] Targets: {list(targets.keys())}")
    print(f"[+] Scope: {args.scope}{' + LAST_7_DAYS' if args.last_7_days else ''}")

    for ev, pid in targets.items():
        params = f"MetaPeriodId={pid}&RankingClassScopeFilter={args.scope}"
        if args.last_7_days:
            params += "&MetaPeriodScopeFilter=LAST_7_DAYS"
        path = f"/api/v1/analytics/query/archetype_matchups_by_event_scope_and_rank?{params}"
        try:
            data = fetch_json(path, sessionid, csrftoken)
        except urllib.error.HTTPError as e:
            print(f"  ! {ev:30s} pid={pid}  HTTP {e.code}")
            continue
        if not data:
            print(f"  - {ev:30s} pid={pid}  (no data / 202)")
            continue
        snap_id, n = insert_matchup_snapshot(con, data, pid, ev, args.scope, args.last_7_days)

        plat = sum(1 for r in data if r.get("ranking_class_before") == "Platinum")
        mythic = sum(1 for r in data if r.get("ranking_class_before") == "Mythic")
        print(f"  + {ev:30s} pid={pid}  rows={len(data)}  plat={plat}  mythic={mythic}")

        if not args.no_archive:
            arch_dir = Path(args.archive) / "premium_matchups"
            arch_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            suffix = "_7d" if args.last_7_days else ""
            ap_path = arch_dir / f"matchups_{ev}_pid{pid}_{args.scope}{suffix}_{stamp}.json"
            with open(ap_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        time.sleep(RATE_LIMIT_SLEEP_SEC)

    # Output
    if args.archetype:
        cur = con.cursor()
        where = ["LOWER(friendly_archetype) LIKE ?"]
        params = [f"%{args.archetype.lower()}%"]
        if args.rank != "all":
            where.append("rank_tier = ?")
            params.append(args.rank)
        if args.last_7_days:
            where.append("last_7_days = 1")
        else:
            where.append("last_7_days = 0")
        where.append("observed_match_count >= ?")
        params.append(args.min_matches)
        sql = f"""
            SELECT format, friendly_archetype, friendly_colors,
                   opponent_archetype, opponent_colors,
                   rank_tier, observed_match_count, win_rate
            FROM v_untapped_premium_matchups_named
            WHERE {' AND '.join(where)}
            ORDER BY format, friendly_archetype, rank_tier, observed_match_count DESC
        """
        cur.execute(sql, params)
        print()
        print(f"=== Matchups for friendly archetype matching '{args.archetype}' (rank={args.rank}, n>={args.min_matches}) ===")
        last = None
        for r in cur.fetchall():
            fmt, f_arch, f_col, o_arch, o_col, rank, n, wr = r
            key = (fmt, f_arch, rank)
            if key != last:
                print(f"\n  [{fmt}] {f_arch} ({f_col}) at {rank}:")
                last = key
            marker = "++" if wr >= 55 else ("--" if wr <= 45 else "  ")
            opp_label = f"{o_arch or '?'} ({o_col or '?'})"
            print(f"    {marker} vs {opp_label:<35s}  n={n:>4}  WR={wr:>5.1f}%")

    con.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
