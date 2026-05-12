"""Pull Nicholas Odenheimer's PT SOS Izzet Prowess list (deck_id=135165, place 15)."""
import sys, sqlite3
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Pull all PT SOS Izzet Prowess decks (Team Worldly Council members)
print("=" * 80)
print("PT SECRETS OF STRIXHAVEN — All Izzet Prowess pilots (potential Team WC)")
print("=" * 80)
cur.execute("""
    SELECT d.id, d.player, d.placement, d.url, e.name
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE e.name LIKE 'Pro Tour Secrets of Strixhaven'
      AND d.archetype = 'Izzet Prowess'
    ORDER BY d.placement
""")
pt_decks = cur.fetchall()
print(f"\nFound {len(pt_decks)} Izzet Prowess at PT SOS:")
for r in pt_decks:
    print(f"  deck_id={r[0]:>6}  place={r[2]:>3}  {r[1]:<30s}  {r[3] or ''}")

# Get Nick Odenheimer's exact list
target_id = 135165  # Nicholas Odenheimer, PT SOS, place 15
print()
print("=" * 80)
print(f"NICHOLAS ODENHEIMER — Pro Tour Secrets of Strixhaven (May 1, 2026, place 15)")
print("=" * 80)

cur.execute("""
    SELECT c.name, dc.quantity, dc.is_sideboard
    FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id = ?
    ORDER BY dc.is_sideboard, dc.quantity DESC, c.name
""", (target_id,))
main = []
sb = []
for cname, qty, is_sb in cur.fetchall():
    if is_sb: sb.append((qty, cname))
    else: main.append((qty, cname))

print(f"\nMAIN ({sum(q for q, _ in main)}):")
for qty, cname in main:
    print(f"  {qty}  {cname}")
print(f"\nSIDEBOARD ({sum(q for q, _ in sb)}):")
for qty, cname in sb:
    print(f"  {qty}  {cname}")

# Compare across ALL PT SOS Prowess decks - find consensus among the team
print()
print("=" * 80)
print("CONSENSUS: PT SOS Izzet Prowess (all pilots, likely team list)")
print("=" * 80)
deck_ids = [r[0] for r in pt_decks]
placeholders = ','.join('?' * len(deck_ids))
cur.execute(f"""
    SELECT dc.deck_id, c.name, dc.quantity, dc.is_sideboard
    FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id IN ({placeholders})
""", deck_ids)

main_per_deck = {}
sb_per_deck = {}
for deck_id, cname, qty, is_sb in cur.fetchall():
    target_dict = sb_per_deck if is_sb else main_per_deck
    target_dict.setdefault(deck_id, Counter())[cname] += qty

# Aggregate
n = len(main_per_deck)
all_main = set()
for d in main_per_deck.values(): all_main.update(d.keys())
all_sb = set()
for d in sb_per_deck.values(): all_sb.update(d.keys())

print(f"\nMAIN consensus ({n} pilots):")
mavg = []
for c in all_main:
    total = sum(main_per_deck.get(d, {}).get(c, 0) for d in main_per_deck)
    pilots = sum(1 for d in main_per_deck if main_per_deck.get(d, {}).get(c, 0) > 0)
    mavg.append((c, total/n, pilots))
mavg.sort(key=lambda x: (-x[1], x[0]))
for cname, avg, runs in mavg:
    if avg >= 0.3:
        marker = "★" if runs == n else " "
        print(f"  {marker} {avg:>4.1f}  ({runs}/{n})  {cname}")

print(f"\nSIDEBOARD consensus ({len(sb_per_deck)} with SB info):")
savg = []
for c in all_sb:
    total = sum(sb_per_deck.get(d, {}).get(c, 0) for d in sb_per_deck)
    pilots = sum(1 for d in sb_per_deck if sb_per_deck.get(d, {}).get(c, 0) > 0)
    savg.append((c, total/len(sb_per_deck), pilots))
savg.sort(key=lambda x: (-x[1], x[0]))
for cname, avg, runs in savg:
    if avg >= 0.2:
        marker = "★" if runs == len(sb_per_deck) else " "
        print(f"  {marker} {avg:>4.1f}  ({runs}/{len(sb_per_deck)})  {cname}")

# Show URL to Nick's exact list
print()
print("=" * 80)
print("Nick Odenheimer's deck URL (for verification):")
print("=" * 80)
cur.execute("SELECT url FROM decks WHERE id = ?", (target_id,))
url = cur.fetchone()
if url and url[0]:
    print(f"  {url[0]}")

con.close()
