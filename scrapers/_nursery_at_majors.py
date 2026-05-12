"""Check Mono-Green Landfall lists at the major events around Looting's peak."""
import sys, sqlite3
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Target events
event_ids = {
    237: "Magic Spotlight Fanfinity (Nov 1 2025)",
    238: "Magic Spotlight Spider-Man (Oct 25 2025)",
    146: "Regional Championship (Feb 21 2026) - id 146",
    147: "Regional Championship (Feb 21 2026) - id 147",
    148: "Arena Championship 11 (Feb 21 2026)",
    198: "South America RC Santiago (Feb 14 2026)",
    7202: "Vancouver Round 11 RC (Feb 21 2026)",
}

for eid, label in event_ids.items():
    print()
    print("=" * 90)
    print(f"{label}  (event_id={eid})")
    print("=" * 90)
    
    # Get Mono-Green Landfall decks at this event
    cur.execute("""
        SELECT d.id, d.player, d.placement
        FROM decks d
        WHERE d.event_id = ? AND d.archetype = 'Mono Green Landfall'
        ORDER BY d.placement LIMIT 3
    """, (eid,))
    mg_decks = cur.fetchall()
    if not mg_decks:
        print("  No Mono-Green Landfall decks at this event")
        continue
    
    print(f"  Found {len(mg_decks)} Mono-Green Landfall decks (showing top 3)")
    
    for did, player, place in mg_decks:
        print(f"\n  --- {player} (place {place}, deck_id={did}) ---")
        cur.execute("""
            SELECT c.name, dc.quantity, dc.is_sideboard
            FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
            WHERE dc.deck_id = ? AND dc.is_sideboard = 0
            ORDER BY dc.quantity DESC, c.name
        """, (did,))
        for cn, qty, _ in cur.fetchall():
            marker = "  <-- NURSERY" if cn == 'Sapling Nursery' else ""
            print(f"    {qty}  {cn}{marker}")

# Now check broader: were ANY Mono-Green decks in Nov 2025 running Nursery?
print()
print("=" * 90)
print("Sapling Nursery in any Standard deck Oct-Dec 2025 (across all archetypes)")
print("=" * 90)
cur.execute("""
    SELECT d.id, d.player, d.placement, d.archetype, e.name, e.date, dc.quantity, dc.is_sideboard
    FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE c.name = 'Sapling Nursery'
      AND LOWER(e.format) = 'standard'
""")
all_nursery = cur.fetchall()
print(f"Total decks with Sapling Nursery (any time, any archetype): {len(all_nursery)}")

# Filter to Oct-Dec 2025
def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

oct_dec_2025 = []
for r in all_nursery:
    d = parse_date(r[5])
    if datetime(2025,10,1) <= d <= datetime(2025,12,31):
        oct_dec_2025.append((d,) + tuple(r))

print(f"Oct-Dec 2025 specifically: {len(oct_dec_2025)} decks")
for r in oct_dec_2025[:10]:
    print(f"  {r[0].strftime('%Y-%m-%d')}  arch={r[4]:<25s}  place={r[3]:>3}  qty={r[7]} {'SB' if r[8] else 'MD'}")

# Look at the first month Nursery ever appears
print()
print("=== First month Sapling Nursery appeared in Standard ===")
all_dates = sorted([parse_date(r[5]) for r in all_nursery if parse_date(r[5]) != datetime.min])
if all_dates:
    print(f"  Earliest: {all_dates[0].strftime('%Y-%m-%d')}")
    print(f"  Latest:   {all_dates[-1].strftime('%Y-%m-%d')}")

con.close()
