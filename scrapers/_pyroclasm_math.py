"""
Can 2 main Pyroclasm fix Looting vs Mono-Green Landfall?
Verify oracle text and run the math: probability of hitting Pyroclasm by relevant turns
against the current MGL threat density.
"""
import sys, sqlite3, importlib.util
from math import comb
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
db = card_db.CardDB()

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Step 1: Pyroclasm oracle text
print("=" * 80)
print("PYROCLASM - verified oracle text")
print("=" * 80)
card = db.get("Pyroclasm")
print(f"  Cost: {card.get('mana_cost')}  cmc: {card.get('cmc')}")
print(f"  Type: {card.get('type_line')}")
for line in (card.get('oracle_text') or '').split('\n'):
    print(f"  {line}")

# Step 2: What threats does Pyroclasm hit in current MGL?
print()
print("=" * 80)
print("MGL threats — toughness analysis vs Pyroclasm (2 damage to each creature)")
print("=" * 80)
mgl_threats = [
    "Llanowar Elves",
    "Sazh's Chocobo",
    "Badgermole Cub",
    "Icetill Explorer",
    "Earthbender Ascension",
    "Sapling Nursery",
    "Mightform Harmonizer",
    "Ouroboroid",
    "Fecund Greenshell",
    "Mossborn Hydra",
    "Bristly Bill, Spine Sower",
]
for cname in mgl_threats:
    c = db.get(cname)
    if not c: continue
    tl = c.get('type_line', '?')
    pt = ''
    if c.get('power'):
        try:
            tough = int(c.get('toughness', '0'))
            survives = "SURVIVES" if tough >= 3 else "DIES"
        except:
            survives = "VARIABLE"
        pt = f"  {c.get('power')}/{c.get('toughness')}  [{survives}]"
    else:
        pt = "  (not a creature)"
    print(f"  {cname:<28s}  cmc={c.get('cmc','?'):<5}  {tl[:30]:<30s}{pt}")

# Step 3: Hypergeometric math - chance of hitting 2 Pyroclasm by turn N
def p_at_least_one(deck_size, copies, cards_seen):
    """P(>=1 copy in cards_seen drawn from a deck of deck_size with `copies` copies)."""
    if cards_seen <= 0: return 0
    if cards_seen >= deck_size: return 1
    # P(0 copies) = C(deck-copies, seen) / C(deck, seen)
    p_zero = comb(deck_size - copies, cards_seen) / comb(deck_size, cards_seen)
    return 1 - p_zero

print()
print("=" * 80)
print("Probability of finding Pyroclasm by turn N (60-card deck, 2 copies)")
print("=" * 80)
print(f"  Opening hand (7 cards):       {p_at_least_one(60, 2, 7)*100:.1f}%")
print(f"  By turn 2 (8 cards seen):     {p_at_least_one(60, 2, 8)*100:.1f}%")
print(f"  By turn 3 (9 cards seen):     {p_at_least_one(60, 2, 9)*100:.1f}%")
print(f"  By turn 4 (10 cards seen):    {p_at_least_one(60, 2, 10)*100:.1f}%")
print(f"  By turn 5 (11 cards seen):    {p_at_least_one(60, 2, 11)*100:.1f}%")

# With Looting's draw engine - rough estimate: Stormchaser, FOMO, Duelist looting,
# Frostcliff Siege Jeskai, etc. effectively see ~2-3 extra cards/turn after t3
print()
print("Looting draws extra cards via Stormchaser + FOMO + Duelist + Frostcliff Siege.")
print("Approximate cards seen by turn N with looting active:")
print(f"  By turn 3 with 1 looting effect online:    {p_at_least_one(60, 2, 9+1)*100:.1f}% (10 cards)")
print(f"  By turn 4 with 2 looting effects online:   {p_at_least_one(60, 2, 10+3)*100:.1f}% (13 cards)")
print(f"  By turn 5 with 2 looting effects online:   {p_at_least_one(60, 2, 11+5)*100:.1f}% (16 cards)")

# Step 4: Compare to MGL's clock - how fast does MGL kill on average?
# Use untapped meta data: avg_seconds is rough proxy for game length
print()
print("=" * 80)
print("MGL game speed proxy (avg_seconds from Untapped Bo3 plat)")
print("=" * 80)
cur.execute("""
    SELECT archetype_name, total_matches, avg_seconds
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND rank_tier='platinum' AND last_7_days=0
      AND archetype_name IN ('Mono-Green Landfall', 'Izzet Prowess', 'Azorius Tempo', 'Izzet Spellementals', 'Jeskai Control')
    ORDER BY avg_seconds ASC
""")
for r in cur.fetchall():
    n = r[1] or 0
    s = r[2] or 0
    print(f"  {r[0]:<28s}  matches={n:>5}  avg_seconds={s}")

# Step 5: The hidden problem - Pyroclasm only solves part of the matchup
print()
print("=" * 80)
print("What Pyroclasm DOES and DOES NOT solve")
print("=" * 80)
print("""
  SOLVES (2 damage to each creature):
    - Llanowar Elves (1/1) — yes
    - Badgermole Cub (1/2 base) — yes, before it gets to 3/4
    - Sazh's Chocobo (0/1 base) — yes, before landfall pumps it
    - Bristly Bill, Spine Sower — depends on counters

  DOES NOT SOLVE:
    - Earthbender Ascension (Enchantment — Pyroclasm doesn't touch enchantments)
    - Sapling Nursery (Enchantment — Pyroclasm doesn't touch enchantments)
    - 3/4 Treefolk reach tokens from Sapling Nursery (toughness 4 > 2 damage)
    - Mightform Harmonizer (4/4 — survives Pyroclasm)
    - Icetill Explorer (2/2 — wait, dies to Pyroclasm. Actually...)
""")

c = db.get("Icetill Explorer")
print(f"  Verifying Icetill Explorer: {c.get('power')}/{c.get('toughness')}")

# Step 6: Tempo cost of Pyroclasm
print()
print("=" * 80)
print("Tempo cost of casting Pyroclasm on the play vs MGL")
print("=" * 80)
print("""
  Turn 2: MGL plays Llanowar Elves
  Turn 3: MGL plays Earthbender Ascension + Badgermole Cub
  Turn 3 Looting Pyroclasm: kills Llanowar Elves + base Cub. 
    Result: opp has Earthbender Ascension on board with 0 quest counters yet, lost 2 creatures.
    Cost to Looting: skipped t3 development.

  Turn 4: MGL plays Sapling Nursery (with 4+ Forests = costs 2-4 mana)
    Sapling Nursery now makes a 3/4 reach Treefolk every land drop.
    Pyroclasm doesn't kill 3/4 reach.
  Turn 5+: MGL plays Icetill Explorer + extra lands per turn
    Each fetch/Promising Vein = +1 reach token + +1 quest counter

  So Pyroclasm gets ~2-3 creatures killed on turn 3, but:
    - Doesn't touch the enchantments
    - Doesn't touch Mightform Harmonizer
    - Doesn't touch the 3/4 reach tokens
    - You spent your turn 3 not deploying threats
""")

con.close()
