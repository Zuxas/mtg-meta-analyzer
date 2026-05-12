"""Just Portland search - no card_db dependency."""
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

# Portland RC searches - try every possible naming
print("=" * 80)
print("PORTLAND RC EVENT SEARCH (every reasonable pattern)")
print("=" * 80)

patterns = ['%ortland%', '%PNW%', '%Pacific Northwest%', '%Oregon%', '%OR%']
for pat in patterns:
    cur.execute("""
        SELECT id, name, date, format, source, event_type
        FROM events WHERE name LIKE ? OR COALESCE(source, '') LIKE ?
    """, (pat, pat))
    rows = cur.fetchall()
    if rows:
        print(f"\n[Pattern: '{pat}']  {len(rows)} events")
        for r in rows[:20]:
            print(f"  id={r[0]:>6}  date={r[2]:<12}  fmt={r[3]:<10}  {r[1][:60]}  src={r[4]}")

print()
print("=" * 80)
print("All RCs/Spotlights/major Standard events Feb-Mar 2026")
print("=" * 80)
cur.execute("""
    SELECT id, name, date, source, event_type
    FROM events
    WHERE LOWER(format) = 'standard'
""")
all_rows = cur.fetchall()
rcs = []
for r in all_rows:
    d = parse_date(r[2])
    if datetime(2026, 2, 1) <= d <= datetime(2026, 3, 31):
        name_lower = (r[1] or '').lower()
        if any(kw in name_lower for kw in ['regional', 'championship', 'spotlight', 'rc', 'pt ', 'series']):
            rcs.append((d,) + tuple(r))
rcs.sort(key=lambda x: x[0])
for r in rcs:
    print(f"  {r[0].strftime('%Y-%m-%d')}  id={r[1]:<7}  {r[2][:55]:<55s}  src={r[4]}  type={r[5]}")

# Specifically: Spotlight in late Feb? RC Atlanta? RC Lyon? Series Portland?
# McNamara's update sections were "Spotlight Series Atlanta/Lyon"
# These were probably Jan-Feb 2026
print()
print("=" * 80)
print("Magic Spotlight events (any date)")
print("=" * 80)
cur.execute("""
    SELECT id, name, date, format, source, event_type
    FROM events WHERE LOWER(name) LIKE '%spotlight%'
""")
sps = cur.fetchall()
for r in sps:
    d = parse_date(r[2])
    print(f"  {d.strftime('%Y-%m-%d') if d != datetime.min else '?':<12}  id={r[0]:<7}  fmt={r[3]:<10}  {r[1][:60]}  src={r[4]}")

# Maybe call it 'RC Portland 2026' in melee.gg or starcitygames vernacular
# Search melee references
print()
print("=" * 80)
print("Events from source 'melee.gg' or 'melee' in Standard Feb-Mar 2026")
print("=" * 80)
cur.execute("""
    SELECT id, name, date, source, event_type FROM events
    WHERE LOWER(format) = 'standard' AND (LOWER(source) LIKE '%melee%')
""")
mr = cur.fetchall()
for r in mr:
    d = parse_date(r[2])
    if datetime(2026, 2, 1) <= d <= datetime(2026, 4, 30):
        print(f"  {d.strftime('%Y-%m-%d')}  id={r[0]:<7}  {r[1][:60]}  src={r[3]}  type={r[4]}")

con.close()
