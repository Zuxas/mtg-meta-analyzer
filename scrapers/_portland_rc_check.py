"""Find Portland RC event with detailed query."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# All events containing Portland anywhere
cur.execute("""
    SELECT id, name, date, format, source FROM events
    WHERE name LIKE '%ortland%'
    ORDER BY date DESC
""")
print("=== All 'Portland' events ===")
for r in cur.fetchall():
    print(f"  id={r[0]:>5}  {r[2]:<12}  {r[3]:<10s}  {r[1]:<70s}  src={r[4]}")

# Big standalone RC events in early 2026 (when Looting was peaking late)
print()
print("=== Major Standard RC events Oct 2025 - Feb 2026 ===")
cur.execute("""
    SELECT id, name, date, format, source FROM events
    WHERE format='standard' AND (
        LOWER(name) LIKE '%regional championship%'
        OR LOWER(name) LIKE '%spotlight%'
        OR LOWER(name) LIKE '%arena championship%'
        OR LOWER(name) LIKE '%pro tour%'
    )
""")
from datetime import datetime
def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

rows = []
for r in cur.fetchall():
    d = parse_date(r[2])
    if datetime(2025,10,1) <= d <= datetime(2026,3,15):
        rows.append((d, r))
rows.sort(key=lambda x: -x[0].timestamp())
for d, r in rows:
    print(f"  id={r[0]:>5}  {d.strftime('%Y-%m-%d')}  {r[3]:<10s}  {r[1]:<70s}")

# Were there Mono-Green Landfall decks at these events running Sapling Nursery?
print()
print("=== Mono-Green Landfall with Sapling Nursery at major events Oct 2025 - Feb 2026 ===")
event_ids = [r[1][0] for d, r in rows]
if event_ids:
    placeholders = ','.join('?' * len(event_ids))
    cur.execute(f"""
        SELECT d.id, d.player, d.placement, e.name, e.date, dc.quantity, dc.is_sideboard
        FROM decks d JOIN events e ON d.event_id = e.id
        JOIN deck_cards dc ON d.id = dc.deck_id
        JOIN cards c ON dc.card_id = c.id
        WHERE c.name = 'Sapling Nursery' AND d.archetype = 'Mono Green Landfall'
          AND e.id IN ({placeholders})
    """, event_ids)
    nursery_rcs = cur.fetchall()
    print(f"  Found {len(nursery_rcs)} decks")
    for r in nursery_rcs[:10]:
        d = parse_date(r[4])
        sb = 'SB' if r[6] else 'MD'
        print(f"    {d.strftime('%Y-%m-%d')}  place={r[2]:>3}  {r[1]:<25s}  {r[5]}x {sb}  {r[3][:50]}")

# Also check Magic Spotlight events (these are major)
print()
print("=== Magic Spotlight events with full Mono-Green Landfall lists ===")
cur.execute("""
    SELECT id, name, date FROM events
    WHERE LOWER(name) LIKE '%spotlight%' AND format='standard'
    ORDER BY date DESC
""")
for r in cur.fetchall()[:10]:
    d = parse_date(r[2])
    print(f"  id={r[0]:>5}  {d.strftime('%Y-%m-%d')}  {r[1]}")

con.close()
