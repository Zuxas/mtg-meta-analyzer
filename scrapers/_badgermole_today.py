"""Track Badgermole Cub usage by archetype over time - is the deck rebranded?"""
import sys, sqlite3
from datetime import datetime
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

# All Standard decks running Badgermole Cub - what archetypes are they tagged as, by month?
cur.execute("""
    SELECT d.archetype, e.date, dc.quantity, dc.is_sideboard
    FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE c.name = 'Badgermole Cub' AND LOWER(e.format) = 'standard'
      AND dc.is_sideboard = 0 AND dc.quantity >= 2
""")
rows = cur.fetchall()
print(f"Total Standard decks running 2+ Badgermole Cub main: {len(rows)}")

# Bin by month + archetype
by_month_arch = defaultdict(lambda: defaultdict(int))
for arch, dstr, qty, sb in rows:
    d = parse_date(dstr)
    if d == datetime.min: continue
    key = (d.year, d.month)
    by_month_arch[key][arch] += 1

# Show how the archetype tags changed
print()
print("=" * 100)
print("Decks running Badgermole Cub — archetype distribution by month")
print("=" * 100)
print(f"  {'Month':<10s}  archetype distribution")
print("  " + "-" * 95)
for ym in sorted(by_month_arch.keys()):
    archs = by_month_arch[ym]
    total = sum(archs.values())
    print(f"\n  {ym[0]}-{ym[1]:02d}  ({total} total):")
    for arch, n in sorted(archs.items(), key=lambda x: -x[1]):
        pct = n/total*100
        if n >= 2:
            print(f"      {n:>4} ({pct:>5.1f}%)  {arch}")

# Also check: what's the modern equivalent? Look at the Nov 2025 Rhythm decks - what other cards did they share?
print()
print("=" * 100)
print("Cards from Nov-Dec 2025 'Rhythm' decks that are still in current Standard")
print("=" * 100)
cur.execute("""
    SELECT DISTINCT c.name
    FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE d.archetype IN ('Simic Rhythm', 'Golgari Rythm', 'Bant Rhythm', 'Simic Jackal')
      AND LOWER(e.format) = 'standard'
      AND dc.is_sideboard = 0 AND dc.quantity >= 3
""")
rhythm_cards = set(r[0] for r in cur.fetchall())
print(f"Cards run 3+ in old Rhythm decks: {len(rhythm_cards)}")

# How many of these are still showing up in any current 2026-04+ Standard deck?
cur.execute("""
    SELECT DISTINCT c.name FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE LOWER(e.format) = 'standard'
      AND (e.date LIKE '%/04/26' OR e.date LIKE '%/05/26' OR e.date LIKE '2026-04%' OR e.date LIKE '2026-05%')
      AND dc.is_sideboard = 0
""")
current_cards = set(r[0] for r in cur.fetchall())

still_legal_and_played = rhythm_cards & current_cards
gone = rhythm_cards - current_cards
print(f"  Still played in 2026-04+ Standard: {len(still_legal_and_played)}")
print(f"  Gone (rotated or unplayed): {len(gone)}")

# Specifically check key Rhythm engine cards
print()
print("Key Rhythm-era cards — still in current Standard?")
key_cards = [
    "Badgermole Cub",
    "Nature's Rhythm",
    "Patchwork Beastie",
    "Ouroboroid",
    "Llanowar Elves",
    "Overprotect",
    "Hunter's Talent",
    "Mossborn Hydra",
    "Bristly Bill, Spine Sower",
    "Tersa Lightshatter",
    "Sazh's Chocobo",
    "Earthbender Ascension",
    "Icetill Explorer",
    "Sapling Nursery",
    "Ba Sing Se",
    "Fabled Passage",
    "Mightform Harmonizer",
]
for c in key_cards:
    in_current = c in current_cards
    marker = "STILL PLAYED" if in_current else "    gone    "
    print(f"  [{marker}]  {c}")

# What archetype is "Badgermole Cub + Nature's Rhythm + Mightform Harmonizer" tagged as now?
print()
print("=" * 100)
print("Current archetype tag for the cub+harmonizer+rhythm shell (2026-04+)")
print("=" * 100)
cur.execute("""
    SELECT d.archetype, e.date, e.name, d.placement
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.id IN (
        SELECT dc1.deck_id FROM deck_cards dc1
        JOIN cards c1 ON dc1.card_id = c1.id
        WHERE c1.name = 'Badgermole Cub' AND dc1.is_sideboard = 0
    )
    AND d.id IN (
        SELECT dc2.deck_id FROM deck_cards dc2
        JOIN cards c2 ON dc2.card_id = c2.id
        WHERE c2.name = 'Mightform Harmonizer' AND dc2.is_sideboard = 0
    )
    AND LOWER(e.format) = 'standard'
    AND (e.date LIKE '%/04/26' OR e.date LIKE '%/05/26' OR e.date LIKE '2026-04%' OR e.date LIKE '2026-05%')
""")
modern_rhythm = cur.fetchall()
print(f"Current decks running Badgermole + Mightform Harmonizer: {len(modern_rhythm)}")
arch_counter = defaultdict(int)
for arch, _, _, _ in modern_rhythm:
    arch_counter[arch] += 1
for arch, n in sorted(arch_counter.items(), key=lambda x: -x[1]):
    print(f"  {arch:<30s}  {n} decks")

con.close()
