"""
Two things:
1. Find Portland RC in events table (proper search, not lazy)
2. Verify oracle text + P/T for Ouroboroid, Sear, Abrade, Roaring Furnace
   to confirm user's "predictable removal numbers" logic.
"""
import sys, sqlite3, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Portland RC search - all reasonable variants
print("=" * 80)
print("PORTLAND RC EVENT SEARCH")
print("=" * 80)
patterns = ['%ortland%', '%PNW%', '%Pacific Northwest%']
for pat in patterns:
    cur.execute(f"""
        SELECT id, name, date, format, source, event_type
        FROM events WHERE name LIKE ? OR source LIKE ?
        ORDER BY date DESC
    """, (pat, pat))
    rows = cur.fetchall()
    if rows:
        print(f"\nMatch on '{pat}': {len(rows)} events")
        for r in rows:
            print(f"  id={r[0]:>6}  date={r[2]:<12}  fmt={r[3]:<10}  {r[1][:60]}  src={r[4]}  type={r[5]}")

# Also look at Feb-Mar 2026 RCs broadly to find what was called "Portland RC"
print()
print("=" * 80)
print("All RCs in Feb-Mar 2026 (Standard format)")
print("=" * 80)
from datetime import datetime
def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

cur.execute("""
    SELECT id, name, date, source, event_type
    FROM events
    WHERE LOWER(format) = 'standard'
      AND (LOWER(name) LIKE '%regional%' OR LOWER(name) LIKE '%rc %' OR LOWER(name) LIKE '%spotlight%')
""")
rcs = []
for r in cur.fetchall():
    d = parse_date(r[2])
    if datetime(2026, 2, 1) <= d <= datetime(2026, 3, 31):
        rcs.append((d,) + tuple(r))
rcs.sort(key=lambda x: x[0])
for r in rcs:
    print(f"  {r[0].strftime('%Y-%m-%d')}  id={r[1]:<6}  {r[2]:<55s}  src={r[4]}  type={r[5]}")

# Card audit for the "predictable removal" logic
print()
print("=" * 80)
print("REMOVAL CARDS - oracle text + P/T for the predictability argument")
print("=" * 80)

spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
db = m.CardDB()

def show(name):
    c = db.get(name)
    if not c:
        print(f"\n[NOT FOUND] {name}")
        return
    print(f"\n{name}  {c.get('mana_cost','?')}  cmc={c.get('cmc')}  set={c.get('set','?')}")
    print(f"  Type: {c.get('type_line','?')}", end='')
    if c.get('power'):
        print(f"   P/T: {c.get('power')}/{c.get('toughness')}", end='')
    print()
    for line in (c.get('oracle_text') or '').split('\n'):
        print(f"    {line}")

# Removal options
for c in ["Abrade", "Sear", "Roaring Furnace", "Steaming Sauna",
          "Roaring Furnace // Steaming Sauna",
          "Torch the Tower", "Burst Lightning"]:
    show(c)

# The target it has to kill
print()
print("=" * 80)
print("KEY TARGETS (verify P/T for predictable removal math)")
print("=" * 80)
for c in ["Ouroboroid", "Slickshot Show-Off", "Eddymurk Crab",
          "Sazh's Chocobo", "Badgermole Cub", "Mossborn Hydra",
          "Mightform Harmonizer", "Llanowar Elves", "Bristly Bill",
          "Bristly Bill, Spine Sower", "Icetill Explorer",
          "Stormchaser's Talent", "Cori-Steel Cutter"]:
    show(c)

con.close()
