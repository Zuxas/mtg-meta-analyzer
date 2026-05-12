"""Pull recent tournament Standard Izzet Prowess from existing decks table."""
import sys, sqlite3, json
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Schema check
print("=== Tables related to decks/cards/events ===")
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%deck%' OR name LIKE '%event%' OR name LIKE '%card%')")
for (n,) in cur.fetchall():
    print(f"  {n}")
print()

# Schema of key tables
for tbl in ['decks', 'deck_cards', 'events']:
    cur.execute(f"PRAGMA table_info({tbl})")
    cols = cur.fetchall()
    if cols:
        print(f"=== {tbl} ===")
        for c in cols:
            print(f"  {c[1]:<25s} {c[2]}")
        print()

# Recent Izzet Prowess Standard decks - find an event date column first
print()
print("=== Find most recent tournament event ===")
cur.execute("PRAGMA table_info(events)")
ecols = [c[1] for c in cur.fetchall()]
print(f"  events cols: {ecols}")

cur.execute("SELECT * FROM events LIMIT 1")
row = cur.fetchone()
if row:
    for col, val in zip(ecols, row):
        print(f"    {col}: {val}")

# Find the format col + date col
print()
print("=== Recent Izzet Prowess events (Standard format) ===")
date_col = next((c for c in ecols if 'date' in c.lower() or 'start' in c.lower() or 'end' in c.lower()), None)
fmt_col = next((c for c in ecols if 'format' in c.lower()), None)
print(f"  Using date col: {date_col}, format col: {fmt_col}")

if date_col and fmt_col:
    cur.execute(f"""
        SELECT d.archetype, COUNT(*) as cnt, MAX(e.{date_col}) as latest
        FROM decks d JOIN events e ON d.event_id = e.id
        WHERE d.archetype = 'Izzet Prowess' AND LOWER(e.{fmt_col}) = 'standard'
        GROUP BY d.archetype
    """)
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]} decks, latest={r[2]}")
    
    # Pull most-recent Standard Izzet Prowess deck IDs (top 8 from latest events)
    cur.execute(f"""
        SELECT d.id, d.player, d.placement, e.name as event_name, e.{date_col}
        FROM decks d JOIN events e ON d.event_id = e.id
        WHERE d.archetype = 'Izzet Prowess' AND LOWER(e.{fmt_col}) = 'standard'
        ORDER BY e.{date_col} DESC, d.placement ASC
        LIMIT 10
    """)
    recent = cur.fetchall()
    print(f"\n  Top 10 most recent Standard Izzet Prowess deck IDs:")
    for r in recent:
        print(f"    deck_id={r[0]}  player={r[1]}  place={r[2]}  event={r[3]} ({r[4]})")
    
    # Pull cards for the most recent deck (and aggregate top 10)
    if recent:
        cur.execute("PRAGMA table_info(deck_cards)")
        dccols = [c[1] for c in cur.fetchall()]
        print(f"\n  deck_cards cols: {dccols}")
        
        # Aggregate consensus across top 10 most recent
        deck_ids = [r[0] for r in recent]
        placeholders = ','.join('?' * len(deck_ids))
        cur.execute(f"""
            SELECT * FROM deck_cards WHERE deck_id IN ({placeholders})
        """, deck_ids)
        rows = cur.fetchall()
        print(f"\n  Total deck_card rows for top 10 decks: {len(rows)}")
        if rows:
            print(f"  Sample row: {dict(zip(dccols, rows[0]))}")

con.close()
