"""Find all Looting decks by Connor Mackenzie / CMack_."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

out_path = str(Path(__file__).parent / '_cmack_looting.txt')
f = open(out_path, 'w', encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# All Looting decks by either name variant
f.write("=" * 80 + "\n")
f.write("All Izzet Looting decks by Connor Mackenzie / CMack_\n")
f.write("=" * 80 + "\n")

cur.execute("""
    SELECT d.id, d.player, d.placement, d.archetype, e.name, e.date, e.format
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE (LOWER(d.player) LIKE '%mackenzie%'
           OR LOWER(d.player) LIKE '%cmack%'
           OR LOWER(d.player) LIKE 'connor m%')
      AND LOWER(d.archetype) LIKE '%looting%'
    ORDER BY e.date DESC
""")
for r in cur.fetchall():
    f.write(f"  {r[5]:<12}  place={r[2]:>4}  {r[1]:<25s}  {r[3]:<20s}  fmt={r[6]:<10s}  {r[4][:55]}\n")

# Also: all his recent Standard decks (post-Worlds) to see if he moved off Looting entirely
f.write("\n")
f.write("=" * 80 + "\n")
f.write("All decks (any archetype) post-Worlds 2025 (Dec 6 2025+)\n")
f.write("=" * 80 + "\n")

cur.execute("""
    SELECT d.id, d.player, d.placement, d.archetype, e.name, e.date, e.format
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE (LOWER(d.player) LIKE '%mackenzie%'
           OR LOWER(d.player) LIKE '%cmack%'
           OR LOWER(d.player) LIKE 'connor m%')
""")
all_rows = cur.fetchall()
from datetime import datetime
def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

post_worlds = []
for r in all_rows:
    d = parse_date(r[5])
    if d >= datetime(2025, 12, 6):
        post_worlds.append((d, r))
post_worlds.sort(key=lambda x: x[0])

for dt, r in post_worlds:
    f.write(f"  {dt.strftime('%Y-%m-%d')}  place={r[2]:>4}  {r[1]:<25s}  {r[3]:<25s}  fmt={r[6]:<10s}  {r[4][:55]}\n")

con.close()
f.close()
print("done")
