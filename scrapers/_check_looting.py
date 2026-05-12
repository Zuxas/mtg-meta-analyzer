"""Pull all data on Izzet Looting from earlier this year + current state."""
import sys, sqlite3
from datetime import datetime
from collections import Counter
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

# Find archetype tagged as Looting
print("=" * 80)
print("LOOTING-related archetypes in decks table")
print("=" * 80)
cur.execute("""
    SELECT archetype, COUNT(*) as n FROM decks
    WHERE LOWER(archetype) LIKE '%loot%'
    GROUP BY archetype ORDER BY n DESC
""")
for r in cur.fetchall():
    print(f"  {r[0]:<30s}  {r[1]:>4} decks")

# Also try Tiger-Seal / Fear of Missing Out / Duelist of the Mind as the deck signature
print()
print("=" * 80)
print("Decks containing the looting signature cards (Duelist of the Mind + Fear of Missing Out)")
print("=" * 80)
cur.execute("""
    SELECT d.archetype, COUNT(*) as n
    FROM decks d
    JOIN deck_cards dc1 ON d.id = dc1.deck_id
    JOIN cards c1 ON dc1.card_id = c1.id
    JOIN deck_cards dc2 ON d.id = dc2.deck_id
    JOIN cards c2 ON dc2.card_id = c2.id
    WHERE c1.name = 'Duelist of the Mind' AND c2.name = 'Fear of Missing Out'
      AND dc1.is_sideboard = 0 AND dc2.is_sideboard = 0
    GROUP BY d.archetype ORDER BY n DESC
""")
for r in cur.fetchall():
    print(f"  {r[0]:<30s}  {r[1]:>4} decks")

# Timeline of when this deck was relevant
print()
print("=" * 80)
print("Izzet Looting timeline — events by month")
print("=" * 80)
cur.execute("""
    SELECT e.date, e.name, e.format, d.player, d.placement
    FROM decks d JOIN events e ON d.event_id = e.id
    JOIN deck_cards dc1 ON d.id = dc1.deck_id
    JOIN cards c1 ON dc1.card_id = c1.id
    JOIN deck_cards dc2 ON d.id = dc2.deck_id
    JOIN cards c2 ON dc2.card_id = c2.id
    WHERE c1.name = 'Duelist of the Mind' AND c2.name = 'Fear of Missing Out'
      AND dc1.is_sideboard = 0 AND dc2.is_sideboard = 0
      AND LOWER(e.format) = 'standard'
""")
all_rows = cur.fetchall()

# Group by month
from collections import defaultdict
by_month = defaultdict(list)
for r in all_rows:
    d = parse_date(r[0])
    if d == datetime.min: continue
    key = (d.year, d.month)
    by_month[key].append(r)

print(f"  Total Standard Looting (with Duelist + FOMO) decks found: {len(all_rows)}")
print()
for (y, m), rows in sorted(by_month.items()):
    print(f"  {y}-{m:02d}: {len(rows)} decks")

# Most recent appearances (when did this deck stop showing up?)
all_rows.sort(key=lambda r: parse_date(r[0]), reverse=True)
print()
print("=== 10 MOST RECENT Izzet Looting decks ===")
for r in all_rows[:10]:
    d = parse_date(r[0])
    print(f"  {d.strftime('%Y-%m-%d')}  place={r[4]:>3}  {r[3]:<25s}  {r[1]}")

# Check current Untapped Bo3 meta - does this deck still exist?
print()
print("=" * 80)
print("Izzet Looting in CURRENT Bo3 platinum meta (Untapped)")
print("=" * 80)
cur.execute("""
    SELECT archetype_name, total_matches, win_rate, tier_val
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND last_7_days=0
      AND rank_tier='platinum'
      AND LOWER(archetype_name) LIKE '%loot%'
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]:<30s}  matches={r[1]}  WR={r[2]}  tier_val={r[3]}")
else:
    print("  No 'Looting'-tagged archetype in current Bo3 plat meta")

# Check if Untapped tags it as something else - look for Izzet decks with Tiger-Seal or Duelist
# These wouldn't exist in untapped meta data since that's archetype-level not card-level
# But we can check what Izzet archetypes exist
cur.execute("""
    SELECT archetype_name, total_matches, win_rate
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND last_7_days=0 AND rank_tier='platinum'
      AND (colors_str LIKE '%U%' AND colors_str LIKE '%R%')
    ORDER BY total_matches DESC
""")
print()
print("=== All Izzet (UR) archetypes in current Bo3 plat meta ===")
for r in cur.fetchall():
    wr = f"{r[2]:.2f}" if r[2] is not None else "-"
    print(f"  {r[0]:<35s}  matches={r[1]:>5}  WR={wr}")

con.close()
