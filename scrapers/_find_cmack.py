"""Find Connor McKenzie's Pro Tour decks."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

# Write output to a file we can read
out_path = str(Path(__file__).parent / '_cmack_results.txt')
f = open(out_path, 'w', encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

f.write("=" * 80 + "\n")
f.write("Search variants for Connor McKenzie\n")
f.write("=" * 80 + "\n")

patterns = ['%mckenzie%', '%cmack%', 'connor m%', '%c mack%']
for pat in patterns:
    cur.execute("""
        SELECT d.id, d.player, d.placement, d.archetype, e.name, e.date, e.format
        FROM decks d JOIN events e ON d.event_id = e.id
        WHERE LOWER(d.player) LIKE ?
        ORDER BY e.date DESC LIMIT 30
    """, (pat,))
    rows = cur.fetchall()
    if rows:
        f.write(f"\nPattern: '{pat}'  ({len(rows)} matches)\n")
        for r in rows:
            f.write(f"  deck_id={r[0]:>6}  place={r[2]:>3}  {r[1]:<25s}  {r[3]:<25s}  fmt={r[6]:<10s}  {r[4][:50]}  {r[5]}\n")

# Also search Pro Tour events for any player matching - sometimes spelling varies
f.write("\n")
f.write("=" * 80 + "\n")
f.write("All PT events in DB\n")
f.write("=" * 80 + "\n")
cur.execute("""
    SELECT id, name, date FROM events WHERE LOWER(name) LIKE '%pro tour%'
    ORDER BY date DESC LIMIT 10
""")
for r in cur.fetchall():
    f.write(f"  id={r[0]:<6}  {r[2]:<12}  {r[1]}\n")

con.close()
f.close()
print("DONE - wrote to", out_path)
