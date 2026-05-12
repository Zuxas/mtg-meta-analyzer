"""Verify: was Sapling Nursery in Mono-Green Landfall at RC Portland and during Nov-Dec 2025?"""
import sys, sqlite3
from datetime import datetime
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

# Find Portland RC events
print("=" * 90)
print("PORTLAND RC events in DB")
print("=" * 90)
cur.execute("""
    SELECT id, name, date, format FROM events
    WHERE LOWER(name) LIKE '%portland%'
    ORDER BY date DESC
""")
portland_events = cur.fetchall()
for r in portland_events:
    print(f"  id={r[0]:>5}  {r[1]:<60s}  {r[2]}  fmt={r[3]}")

# Also try Regional Championship in Portland
print()
cur.execute("""
    SELECT id, name, date, format FROM events
    WHERE LOWER(name) LIKE '%regional%' AND format='standard'
    ORDER BY date DESC LIMIT 30
""")
print("Recent Regional Championships (Standard):")
for r in cur.fetchall():
    print(f"  id={r[0]:>5}  {r[1]:<60s}  {r[2]}")

# Track Sapling Nursery usage across time in Mono-Green Landfall
print()
print("=" * 90)
print("Sapling Nursery usage in Mono-Green Landfall over time")
print("=" * 90)
cur.execute("""
    SELECT d.id, d.player, d.placement, e.name, e.date, e.format,
           dc.quantity, dc.is_sideboard
    FROM decks d
    JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc ON d.id = dc.deck_id
    JOIN cards c ON dc.card_id = c.id
    WHERE c.name = 'Sapling Nursery'
      AND d.archetype = 'Mono Green Landfall'
      AND LOWER(e.format) = 'standard'
""")
nursery_decks = cur.fetchall()
print(f"Total Mono-Green Landfall decks running Sapling Nursery: {len(nursery_decks)}")

# Bin by month
from collections import defaultdict
by_month = defaultdict(lambda: {'count': 0, 'md': 0, 'sb': 0, 'copies': 0})
for r in nursery_decks:
    d = parse_date(r[4])
    if d == datetime.min: continue
    key = (d.year, d.month)
    by_month[key]['count'] += 1
    by_month[key]['copies'] += r[6]
    if r[7]:
        by_month[key]['sb'] += r[6]
    else:
        by_month[key]['md'] += r[6]

print()
print(f"  {'Month':<10s}  {'Decks':>5s}  {'MD copies':>10s}  {'SB copies':>10s}  {'Total':>6s}")
for ym in sorted(by_month.keys()):
    s = by_month[ym]
    print(f"  {ym[0]}-{ym[1]:02d}     {s['count']:>5}  {s['md']:>10}  {s['sb']:>10}  {s['copies']:>6}")

# Now find: how many Mono-Green Landfall decks TOTAL per month, and what % ran Nursery?
print()
print("=" * 90)
print("% of Mono-Green Landfall running Sapling Nursery by month")
print("=" * 90)
cur.execute("""
    SELECT d.id, e.date FROM decks d
    JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Mono Green Landfall' AND LOWER(e.format) = 'standard'
""")
total_by_month = defaultdict(int)
deck_dates = {}
for did, dstr in cur.fetchall():
    d = parse_date(dstr)
    if d == datetime.min: continue
    key = (d.year, d.month)
    total_by_month[key] += 1
    deck_dates[did] = key

nursery_deck_ids = set(r[0] for r in nursery_decks)
nursery_by_month = defaultdict(int)
for did in nursery_deck_ids:
    if did in deck_dates:
        nursery_by_month[deck_dates[did]] += 1

print(f"  {'Month':<10s}  {'Total MG':>8s}  {'with Nursery':>13s}  {'%':>6s}")
for ym in sorted(set(total_by_month.keys()) | set(nursery_by_month.keys())):
    total = total_by_month.get(ym, 0)
    nurs = nursery_by_month.get(ym, 0)
    pct = nurs/total*100 if total else 0
    print(f"  {ym[0]}-{ym[1]:02d}     {total:>8}  {nurs:>13}  {pct:>5.1f}%")

# Show a sample Mono-Green Landfall list from Portland or Nov 2025
print()
print("=" * 90)
print("Sample Mono-Green Landfall lists from Nov-Dec 2025 (when Looting was peaking)")
print("=" * 90)
cur.execute("""
    SELECT d.id, d.player, d.placement, e.name, e.date
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.archetype = 'Mono Green Landfall' AND LOWER(e.format) = 'standard'
      AND e.date LIKE '%/12/25' OR e.date LIKE '%/11/25'
    ORDER BY d.placement ASC LIMIT 5
""")
sample_decks = cur.fetchall()
for r in sample_decks:
    d = parse_date(r[4])
    print(f"\n  deck_id={r[0]}  place={r[2]:>3}  {r[1]:<25s}  {r[3]}  {d.strftime('%Y-%m-%d')}")
    cur.execute("""
        SELECT c.name, dc.quantity, dc.is_sideboard
        FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
        WHERE dc.deck_id = ? ORDER BY dc.is_sideboard, dc.quantity DESC
    """, (r[0],))
    for cn, qty, is_sb in cur.fetchall():
        marker = "SB" if is_sb else "  "
        print(f"    {marker}  {qty}  {cn}")
    break  # show just one full list

con.close()
