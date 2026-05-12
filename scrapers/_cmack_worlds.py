"""Pull Connor Mackenzie's Worlds 2025 Izzet Looting list (deck_id=2467)."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

out_path = str(Path(__file__).parent / '_cmack_worlds_results.txt')
f = open(out_path, 'w', encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Deck metadata
cur.execute("""
    SELECT d.id, d.player, d.placement, d.archetype, d.url, e.name, e.date
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.id = 2467
""")
r = cur.fetchone()
f.write(f"DECK_ID: {r[0]}\n")
f.write(f"PLAYER: {r[1]}\n")
f.write(f"PLACEMENT: {r[2]}\n")
f.write(f"ARCHETYPE: {r[3]}\n")
f.write(f"URL: {r[4]}\n")
f.write(f"EVENT: {r[5]} ({r[6]})\n\n")

# Mainboard
cur.execute("""
    SELECT c.name, dc.quantity FROM deck_cards dc
    JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id = 2467 AND dc.is_sideboard = 0
    ORDER BY dc.quantity DESC, c.name
""")
f.write("MAINBOARD\n")
total = 0
for cn, q in cur.fetchall():
    f.write(f"  {q}  {cn}\n")
    total += q
f.write(f"  ---\n  Total: {total}\n\n")

# Sideboard
cur.execute("""
    SELECT c.name, dc.quantity FROM deck_cards dc
    JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id = 2467 AND dc.is_sideboard = 1
    ORDER BY dc.quantity DESC, c.name
""")
f.write("SIDEBOARD\n")
total = 0
for cn, q in cur.fetchall():
    f.write(f"  {q}  {cn}\n")
    total += q
f.write(f"  ---\n  Total: {total}\n")

# Also: any other Looting decks at Worlds 2025? to see the rest of the field
f.write("\n\n=== Other Worlds 2025 results (same event) ===\n")
cur.execute("""
    SELECT id, player, placement, archetype FROM decks
    WHERE event_id = (SELECT event_id FROM decks WHERE id = 2467)
    ORDER BY placement LIMIT 30
""")
for row in cur.fetchall():
    f.write(f"  place={row[2]:>3}  {row[1]:<28s}  {row[3]}  (deck_id={row[0]})\n")

con.close()
f.close()
print("Done")
