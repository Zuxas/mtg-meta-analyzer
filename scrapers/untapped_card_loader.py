"""
untapped_card_loader.py
=======================

Fetches Untapped's official MTGA card database + English localization JSON
and builds a `untapped_card_db` table mapping grpid -> name + metadata.

This is the lookup table needed to interpret the integer grpids that appear
in replay deck data (decks[*].deck.mainDeck / .sideboard).

Source URLs (public, no auth):
    https://mtgajson.untapped.gg/v1/latest/cards.json    (~12 MB, 24k cards)
    https://mtgajson.untapped.gg/v1/latest/loc_en.json   (~4.6 MB, 49k strings)

Run when:
    - First-time setup
    - After new set releases (cards.json gets updated; check Last-Modified)

Usage:
    python scrapers\\untapped_card_loader.py
    python scrapers\\untapped_card_loader.py --force   # re-download even if cached
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

CARDS_URL = "https://mtgajson.untapped.gg/v1/latest/cards.json"
LOC_URL = "https://mtgajson.untapped.gg/v1/latest/loc_en.json"

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.database import DB_PATH as CENTRAL_DB_PATH

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(CENTRAL_DB_PATH)
UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_card_db (
        grpid INTEGER PRIMARY KEY,
        title_id INTEGER,
        name TEXT,
        set_code TEXT,
        collector_number TEXT,
        rarity INTEGER,
        casting_cost TEXT,
        cmc REAL,
        types TEXT,
        last_refreshed_utc TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_untapped_card_db_name ON untapped_card_db(name)",
]


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if table is populated")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    con.commit()

    cur.execute("SELECT COUNT(*), MAX(last_refreshed_utc) FROM untapped_card_db")
    n, last = cur.fetchone()
    if n and not args.force:
        print(f"[+] untapped_card_db has {n} rows, last refreshed {last}")
        print(f"    Use --force to re-download")
        return 0

    print(f"[+] Fetching cards.json ({CARDS_URL}) ...")
    cards = fetch_url(CARDS_URL)
    print(f"    -> {len(cards)} cards")
    print(f"[+] Fetching loc_en.json ({LOC_URL}) ...")
    loc = fetch_url(LOC_URL)
    print(f"    -> {len(loc)} loc strings")

    loc_map = {entry["id"]: entry.get("text", "") for entry in loc}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for c in cards:
        grpid = c.get("grpid")
        if grpid is None:
            continue
        title_id = c.get("titleId")
        name = loc_map.get(title_id, "") if title_id else ""
        # Some cards have multi-piece names (split, adventure, dfc) - we just use
        # the front face name from titleId. That's what shows on the leaderboard.
        rows.append((
            grpid,
            title_id,
            name,
            c.get("set"),
            c.get("collectorNumber"),
            c.get("rarity"),
            c.get("castingcost"),
            c.get("cmc"),
            json.dumps(c.get("types") or []),
            now,
        ))

    print(f"[+] Inserting {len(rows)} rows ...")
    cur.executemany("""
        INSERT INTO untapped_card_db (
            grpid, title_id, name, set_code, collector_number,
            rarity, casting_cost, cmc, types, last_refreshed_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(grpid) DO UPDATE SET
            title_id=excluded.title_id,
            name=excluded.name,
            set_code=excluded.set_code,
            collector_number=excluded.collector_number,
            rarity=excluded.rarity,
            casting_cost=excluded.casting_cost,
            cmc=excluded.cmc,
            types=excluded.types,
            last_refreshed_utc=excluded.last_refreshed_utc
    """, rows)
    con.commit()

    cur.execute("SELECT COUNT(*) FROM untapped_card_db WHERE name IS NOT NULL AND name != ''")
    named = cur.fetchone()[0]
    print(f"[+] Inserted/updated {len(rows)} cards, {named} have names")

    # Spot-check a few well-known grpids
    print("\n[+] Spot-check lookups:")
    for grpid in [51307, 68735, 70547, 71588, 72178, 75021]:
        cur.execute("SELECT grpid, name, set_code FROM untapped_card_db WHERE grpid=?", (grpid,))
        row = cur.fetchone()
        if row:
            print(f"    grpid={row[0]:6d}  name={row[1]!r}  set={row[2]}")
        else:
            print(f"    grpid={grpid:6d}  NOT FOUND")

    con.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
