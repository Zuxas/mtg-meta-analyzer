"""Check Izzet Looting's historical matchup vs Mono Green / Badgermole decks during its Nov-Dec 2025 peak."""
import sys, sqlite3
from datetime import datetime
from collections import defaultdict, Counter
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

# Pull all Looting decks Nov-Dec 2025 (peak)
print("=" * 90)
print("IZZET LOOTING peak Nov-Dec 2025 — total tournament finishes")
print("=" * 90)
cur.execute("""
    SELECT d.id, d.player, d.placement, e.name, e.date, e.source
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Izzet Looting' AND LOWER(e.format) = 'standard'
""")
all_loot = cur.fetchall()

# Filter Nov-Dec 2025
peak = []
for r in all_loot:
    d = parse_date(r[4])
    if datetime(2025,11,1) <= d <= datetime(2025,12,31):
        peak.append((d,) + tuple(r))

peak.sort(key=lambda x: -x[0].timestamp())
print(f"Total Izzet Looting decks: {len(all_loot)}")
print(f"Nov-Dec 2025 peak window: {len(peak)} decks")

# Placements distribution
print()
print("Placement distribution in peak:")
plc_bins = {'1-4':0, '5-8':0, '9-16':0, '17-32':0, '33+':0}
for r in peak:
    p = r[3]
    if p <= 4: plc_bins['1-4'] += 1
    elif p <= 8: plc_bins['5-8'] += 1
    elif p <= 16: plc_bins['9-16'] += 1
    elif p <= 32: plc_bins['17-32'] += 1
    else: plc_bins['33+'] += 1
for k, v in plc_bins.items():
    print(f"  place {k:>6s}: {v:>3} ({v/len(peak)*100:5.1f}%)")

# What was the field composition Nov-Dec 2025? Look at all archetypes from that window
print()
print("=" * 90)
print("WHAT IZZET LOOTING WAS FACING — Standard meta Nov-Dec 2025 (all archetypes)")
print("=" * 90)
cur.execute("""
    SELECT d.archetype, e.date
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE LOWER(e.format) = 'standard'
""")
field_counter = Counter()
for arch, dstr in cur.fetchall():
    d = parse_date(dstr)
    if datetime(2025,11,1) <= d <= datetime(2025,12,31):
        field_counter[arch] += 1

total_field = sum(field_counter.values())
print(f"Total Standard decks Nov-Dec 2025: {total_field}")
print()
print(f"  {'archetype':<35s}  {'count':>6s}  {'meta%':>7s}")
print("  " + "-" * 55)
for arch, n in field_counter.most_common(20):
    pct = n / total_field * 100
    is_loot = '←' if arch == 'Izzet Looting' else ' '
    is_green = '★' if any(x in (arch or '').lower() for x in ['green','mono green','golgari','selesnya','gruul','simic','badgermole','landfall','stompy']) else ' '
    print(f"  {arch:<35s}  {n:>6}  {pct:>6.2f}%  {is_loot}{is_green}")

# Cards Looting played that target green/Badgermole specifically
print()
print("=" * 90)
print("LOOTING'S anti-creature tools in Nov-Dec 2025 lists")
print("=" * 90)
peak_ids = [r[1] for r in peak]
placeholders = ','.join('?' * len(peak_ids))
cur.execute(f"""
    SELECT c.name, COUNT(DISTINCT dc.deck_id) as decks, SUM(dc.quantity) as total_copies,
           SUM(CASE WHEN dc.is_sideboard = 1 THEN dc.quantity ELSE 0 END) as sb_copies,
           SUM(CASE WHEN dc.is_sideboard = 0 THEN dc.quantity ELSE 0 END) as md_copies
    FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
    WHERE dc.deck_id IN ({placeholders})
    GROUP BY c.name
    HAVING decks >= {len(peak)//4}
    ORDER BY total_copies DESC
""", peak_ids)

print(f"  {'card':<35s}  {'decks':>6s}  {'MD':>5s}  {'SB':>5s}  {'total':>6s}")
print("  " + "-" * 65)
for r in cur.fetchall():
    cname, decks, total, sb, md = r
    pct = decks / len(peak) * 100
    # Highlight anti-green/badgermole cards
    anti_green = ''
    nm = cname.lower()
    if any(x in nm for x in ['torch','burst','lightning','flame','pyroclasm','sear','abrade','frostcliff','ghost vacuum','annul','tidebinder']):
        anti_green = '←anti-creature/anti-perm'
    print(f"  {cname:<35s}  {decks:>6}  {md:>5}  {sb:>5}  {total:>6}  {anti_green}")

# Compare with: same period, what Badgermole-style decks were doing
print()
print("=" * 90)
print("BADGERMOLE/MONO-GREEN decks in same period (Nov-Dec 2025)")
print("=" * 90)
for arch_match in ['Mono Green', 'Mono-Green', 'Mono-Green Landfall', 'Selesnya Landfall', 'Golgari', 'Gruul']:
    cnt = field_counter.get(arch_match, 0)
    if cnt > 0:
        print(f"  {arch_match:<28s}  {cnt:>4} decks  ({cnt/total_field*100:.2f}% of field)")

# Look at signature green cards from that meta to identify it
print()
print("=== Decks containing Badgermole Cub in Nov-Dec 2025 ===")
cur.execute("""
    SELECT d.archetype, COUNT(*) FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE c.name = 'Badgermole Cub' AND LOWER(e.format) = 'standard'
      AND dc.is_sideboard = 0
    GROUP BY d.archetype ORDER BY COUNT(*) DESC LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r[0]:<35s}  {r[1]} decks")

con.close()
