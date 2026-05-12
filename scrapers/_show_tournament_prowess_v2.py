"""Pull most recent Standard Izzet Prowess decklist (correctly date-sorted)."""
import sys, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Pull all events with Izzet Prowess Standard, parse dates DD/MM/YY -> proper date
cur.execute("""
    SELECT d.id, d.player, d.placement, e.name, e.date, e.source
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Izzet Prowess' AND LOWER(e.format) = 'standard'
""")
rows = cur.fetchall()

def parse_date(s):
    try:
        # DD/MM/YY format
        return datetime.strptime(s, '%d/%m/%y')
    except: return datetime.min

rows = sorted(rows, key=lambda r: parse_date(r[4]), reverse=True)

print("=== 10 MOST RECENT Standard Izzet Prowess decks (proper date sort) ===")
for r in rows[:10]:
    d = parse_date(r[4])
    print(f"  {d.strftime('%Y-%m-%d')}  deck_id={r[0]:>5}  place={r[2]:>2}  {r[1]:<25s}  {r[3]} ({r[5]})")

# Use most-recent 5 to build consensus
top5_ids = [r[0] for r in rows[:5]]
print(f"\n=== CONSENSUS LIST from top 5 most recent ===")
print(f"Deck IDs: {top5_ids}")

# Pull cards
placeholders = ','.join('?' * len(top5_ids))
cur.execute(f"""
    SELECT dc.deck_id, c.name, dc.quantity, dc.is_sideboard
    FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id IN ({placeholders})
""", top5_ids)

# Aggregate
main_per_deck = {}
sb_per_deck = {}
for deck_id, cname, qty, is_sb in cur.fetchall():
    if is_sb:
        sb_per_deck.setdefault(deck_id, Counter())[cname] += qty
    else:
        main_per_deck.setdefault(deck_id, Counter())[cname] += qty

# Compute average copies per pilot
all_main_cards = set()
for d in main_per_deck.values(): all_main_cards.update(d.keys())
all_sb_cards = set()
for d in sb_per_deck.values(): all_sb_cards.update(d.keys())

n = len(main_per_deck)
print(f"\nMAIN consensus (across {n} pilots, sorted by avg copies):")
main_avg = []
for c in all_main_cards:
    total = sum(main_per_deck.get(d, {}).get(c, 0) for d in main_per_deck)
    pilots_running = sum(1 for d in main_per_deck if main_per_deck.get(d, {}).get(c, 0) > 0)
    main_avg.append((c, total/n, pilots_running))
main_avg.sort(key=lambda x: (-x[1], x[0]))
for cname, avg, runs in main_avg:
    if avg >= 0.6:
        print(f"  {avg:>4.1f}  ({runs}/{n})  {cname}")

print(f"\nSIDEBOARD consensus:")
sb_avg = []
for c in all_sb_cards:
    total = sum(sb_per_deck.get(d, {}).get(c, 0) for d in sb_per_deck)
    pilots_running = sum(1 for d in sb_per_deck if sb_per_deck.get(d, {}).get(c, 0) > 0)
    sb_avg.append((c, total/len(sb_per_deck), pilots_running))
sb_avg.sort(key=lambda x: (-x[1], x[0]))
for cname, avg, runs in sb_avg:
    if avg >= 0.4:
        print(f"  {avg:>4.1f}  ({runs}/{len(sb_per_deck)})  {cname}")

# Show one specific deck (most recent, top placement)
print(f"\n=== Single decklist: {rows[0][1]} - {rows[0][3]} ({parse_date(rows[0][4]).strftime('%Y-%m-%d')}) ===")
top_deck_id = rows[0][0]
print(f"\nMAIN:")
for cname, qty in sorted(main_per_deck.get(top_deck_id, {}).items(), key=lambda x: (-x[1], x[0])):
    print(f"  {qty}  {cname}")
print(f"\nSIDEBOARD:")
for cname, qty in sorted(sb_per_deck.get(top_deck_id, {}).items(), key=lambda x: (-x[1], x[0])):
    print(f"  {qty}  {cname}")

con.close()
