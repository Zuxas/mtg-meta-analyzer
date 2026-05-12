"""Check PT SOS data and Connor's entries."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

out_path = str(Path(__file__).parent / '_pt_sos_check.txt')
f = open(out_path, 'w', encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# PT SOS events
cur.execute("SELECT id, name, date FROM events WHERE LOWER(name) LIKE '%strixhaven%' OR LOWER(name) LIKE '%secrets%'")
pt_events = cur.fetchall()
f.write('PT SOS events in DB:\n')
for r in pt_events:
    f.write(f'  id={r[0]:<6}  date={r[2]:<12}  {r[1]}\n')

ids = [r[0] for r in pt_events]
if ids:
    placeholders = ','.join('?' * len(ids))
    cur.execute(f"""
        SELECT d.player, d.placement, d.archetype, e.name
        FROM decks d JOIN events e ON d.event_id = e.id
        WHERE d.event_id IN ({placeholders})
          AND (LOWER(d.player) LIKE '%mackenzie%'
               OR LOWER(d.player) LIKE '%cmack%'
               OR LOWER(d.player) LIKE 'connor m%')
    """, ids)
    rows = cur.fetchall()
    f.write('\nConnor / Mackenzie at PT SOS:\n')
    if rows:
        for r in rows:
            f.write(f'  {r[0]} place={r[1]} {r[2]} ({r[3]})\n')
    else:
        f.write('  (no matches)\n')

    # Count totals
    f.write('\nTotal decks per PT SOS event:\n')
    for eid in ids:
        cur.execute('SELECT COUNT(*) FROM decks WHERE event_id = ?', (eid,))
        n = cur.fetchone()[0]
        cur.execute('SELECT name FROM events WHERE id = ?', (eid,))
        ename = cur.fetchone()[0]
        f.write(f'  id={eid}  decks={n}  {ename}\n')

# Top 8 by placement at PT SOS for context
f.write('\nPT SOS Top placements (any player):\n')
if ids:
    placeholders = ','.join('?' * len(ids))
    cur.execute(f"""
        SELECT d.player, d.placement, d.archetype
        FROM decks d
        WHERE d.event_id IN ({placeholders}) AND d.placement <= 16
        ORDER BY d.placement
    """, ids)
    for r in cur.fetchall():
        f.write(f'  place={r[1]:>3}  {r[0]:<30}  {r[2]}\n')

con.close()
f.close()
print("done")
