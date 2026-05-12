"""
Why isn't Looting good now? Investigate by looking at:
1. What's actually in the current Bo3 plat meta (Untapped data)
2. How those decks would attack Looting (with verified oracle text)
3. What anti-Looting threats are in the field
"""
import sys, sqlite3, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

# Load card_db.py directly
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
db = card_db.CardDB()

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print()
print("=" * 90)
print("CURRENT BO3 PLATINUM META — what Looting would face if registered tomorrow")
print("=" * 90)

cur.execute("""
    SELECT archetype_name, total_matches
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND last_7_days=0 AND rank_tier='platinum'
      AND total_matches >= 100
    ORDER BY total_matches DESC
""")
rows = cur.fetchall()
total = sum(r[1] for r in rows)
print(f"  Top archetypes (n>=100 matches at plat):")
for arch, n in rows[:20]:
    pct = n/total*100
    print(f"    {arch:<30s}  {n:>6,}  ({pct:5.2f}%)")

# Now look at what specific signature cards from these decks would punish Looting
# Get the top played cards in each archetype from the tournament data, current sets only
print()
print("=" * 90)
print("KEY THREATS in current Bo3 meta that punish Looting's plan")
print("=" * 90)

# What threats does Looting fold to? Looting plays:
# - Tiger-Seal (3/3 for 1U), Duelist of the Mind (X/3 flier), FOMO (2/3)
# - Quantum Riddler (4/6 flier), Stormchaser Otter (1/1 prowess)
# So Looting is a TEMPO deck with smallish creatures and instant/sorcery payoffs
# Things that hurt it: cheap removal, faster aggro, hard counterspells in dedicated control

# Find the top cards across decks from the current dominant archetypes
print()
print("=== What's in Izzet Prowess (15.7% of meta) - tournament list signature cards ===")
cur.execute("""
    SELECT c.name, COUNT(DISTINCT d.id) as decks, SUM(dc.quantity) as copies
    FROM decks d
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Izzet Prowess'
      AND LOWER(e.format) = 'standard'
      AND e.date LIKE '%/04/26'
      AND dc.is_sideboard = 0
    GROUP BY c.name
    ORDER BY decks DESC
    LIMIT 15
""")
for r in cur.fetchall():
    cname, decks, copies = r
    card = db.get(cname)
    cost = card.get('mana_cost', '?') if card else '?'
    otext = (card.get('oracle_text') or '')[:80] if card else ''
    print(f"  {cname:<28s}  {cost:<10s}  ({decks} decks, {copies} copies)")

print()
print("=" * 90)
print("HOW PROWESS BEATS LOOTING (mechanics-verified)")
print("=" * 90)

# Show why Prowess beats Looting head to head
prowess_threats = ['Slickshot Show-Off', "Stormchaser's Talent", "Cori-Steel Cutter", "Eddymurk Crab", "Boomerang Basics", "Burst Lightning"]
print("\nKey Prowess threats and how they interact with Looting:")
for cname in prowess_threats:
    card = db.get(cname)
    if not card:
        print(f"  {cname}: NOT FOUND in DB")
        continue
    cost = card.get('mana_cost', '?')
    tl = card.get('type_line', '?')
    pt = ''
    if card.get('power'):
        pt = f" [{card.get('power')}/{card.get('toughness')}]"
    otext = card.get('oracle_text', '') or ''
    print(f"\n  {cname} {cost}{pt}")
    print(f"    {tl}")
    for line in otext.split('\n'):
        print(f"    {line}")

print()
print("=" * 90)
print("HOW MONO-GREEN LANDFALL ATTACKS LOOTING (mechanics-verified)")
print("=" * 90)
green_threats = ["Sapling Nursery", "Earthbender Ascension", "Llanowar Elves", "Icetill Explorer", "Petrified Hamlet"]
for cname in green_threats:
    card = db.get(cname)
    if not card:
        # Try alt name
        print(f"  {cname}: NOT FOUND, skipping")
        continue
    cost = card.get('mana_cost', '?')
    tl = card.get('type_line', '?')
    otext = (card.get('oracle_text') or '')[:300]
    print(f"\n  {cname} {cost}  ({tl})")
    for line in otext.split('\n'):
        print(f"    {line}")

con.close()
