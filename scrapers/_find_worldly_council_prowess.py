"""Find Team Worldly Council's PT SOS Izzet Prowess list - Nick O is one of them."""
import sys, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except: return datetime.min

# Find Pro Tour events
print("=== Pro Tour events in DB ===")
cur.execute("""
    SELECT id, name, date, format, source FROM events
    WHERE LOWER(name) LIKE '%pro tour%' OR LOWER(name) LIKE '%pt %' OR LOWER(name) LIKE '%pt-%'
    ORDER BY date DESC LIMIT 20
""")
for r in cur.fetchall():
    print(f"  id={r[0]:>5}  {r[1]:<55s}  {r[2]}  fmt={r[3]}  src={r[4]}")

# Find Nick O - search by player name (try variants: Nick O, Nicholas, etc)
print()
print("=== All Nick/Nicholas players running Izzet Prowess ===")
cur.execute("""
    SELECT DISTINCT d.player, d.archetype, e.name, e.date, e.format, d.placement, d.id
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE (LOWER(d.player) LIKE 'nick%' OR LOWER(d.player) LIKE 'nicholas%')
      AND d.archetype = 'Izzet Prowess'
    ORDER BY e.date DESC LIMIT 30
""")
for r in cur.fetchall():
    print(f"  deck_id={r[6]:>6}  {r[0]:<25s}  place={r[5]:>3}  {r[3]}  {r[4]:<10s}  {r[2]}")

# Pro Tour Sins of Strixhaven dates would be ~March 2026
print()
print("=== All Standard Izzet Prowess from major events Feb-Apr 2026 ===")
cur.execute("""
    SELECT d.id, d.player, d.placement, e.name, e.date, e.source
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Izzet Prowess' AND LOWER(e.format) = 'standard'
""")
all_rows = cur.fetchall()

# Filter to Feb-Apr 2026
recent = []
for r in all_rows:
    d = parse_date(r[4])
    if datetime(2026, 2, 1) <= d <= datetime(2026, 4, 30):
        recent.append((d,) + tuple(r))

recent.sort(key=lambda x: -x[0].timestamp())
print(f"  Found {len(recent)} Standard Izzet Prowess from Feb-Apr 2026")
print()
# Show events grouped
event_groups = {}
for r in recent:
    key = (r[4], r[5])  # event name + date
    event_groups.setdefault(key, []).append(r)

for (ename, edate), rows in sorted(event_groups.items(), key=lambda x: -parse_date(x[0][1]).timestamp()):
    print(f"\n  EVENT: {ename}  ({edate}) [{rows[0][6]}]")
    for r in rows[:8]:
        print(f"    deck_id={r[1]:>6}  place={r[3]:>3}  {r[2]}")

con.close()
