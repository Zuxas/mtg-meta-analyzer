"""Show Standard Bo3 meta share at platinum tier (most relevant for RC prep)."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Get total platinum matches for share calculation
cur.execute("""
    SELECT SUM(total_matches) FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
""")
total = cur.fetchone()[0] or 1

print("=" * 90)
print(f"STANDARD BO3 META — platinum tier — total {total:,} matches")
print("=" * 90)
print(f"  {'archetype':<30s}  {'colors':<6s}  {'matches':>7s}  {'share%':>7s}  {'tier_val':>8s}")
print("  " + "-" * 70)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches, tier_val
    FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
    ORDER BY total_matches DESC
""")
rank = 0
for r in cur.fetchall():
    rank += 1
    arch = (r[0] or "?")[:30]
    matches = r[2] or 0
    share = matches / total * 100
    tv = f"{r[3]:.2f}" if r[3] is not None else "-"
    marker = "  "
    if "Azorius" in arch: marker = "→ "
    if matches < 100: continue  # skip the long tail
    print(f"  {marker}{arch:<28s}  {r[1]:<6s}  {matches:>7,}  {share:>6.2f}%  {tv:>8}")

# What's the ramp threat density specifically?
print()
print("=" * 90)
print(f"  RAMP THREATS at platinum (decks that punish slow draws)")
print("=" * 90)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches
    FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
      AND (archetype_name LIKE '%Landfall%'
           OR archetype_name LIKE '%Ouroboroid%'
           OR archetype_name LIKE '%Rhythm%'
           OR archetype_name LIKE '%Ramp%'
           OR archetype_name LIKE '%Reanimator%')
    ORDER BY total_matches DESC
""")
ramp_total = 0
for r in cur.fetchall():
    arch = (r[0] or "?")[:30]
    matches = r[2] or 0
    ramp_total += matches
    share = matches / total * 100
    print(f"  {arch:<30s}  {r[1]:<6s}  {matches:>5,} matches  ({share:.2f}% of meta)")
print(f"  {'TOTAL RAMP/REANIMATOR':<30s}  {'':<6s}  {ramp_total:>5,} matches  ({ramp_total/total*100:.2f}% of meta)")

# Aggressive threats
print()
print("=" * 90)
print(f"  AGGRESSIVE THREATS at platinum (decks that punish slow setup)")
print("=" * 90)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches
    FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
      AND (archetype_name LIKE '%Prowess%'
           OR archetype_name LIKE '%Aggro%'
           OR archetype_name LIKE '%Mice%'
           OR archetype_name LIKE '%Burn%'
           OR archetype_name LIKE '%Skeletons%')
    ORDER BY total_matches DESC
""")
aggro_total = 0
for r in cur.fetchall():
    arch = (r[0] or "?")[:30]
    matches = r[2] or 0
    aggro_total += matches
    share = matches / total * 100
    print(f"  {arch:<30s}  {r[1]:<6s}  {matches:>5,} matches  ({share:.2f}% of meta)")
print(f"  {'TOTAL AGGRO':<30s}  {'':<6s}  {aggro_total:>5,} matches  ({aggro_total/total*100:.2f}% of meta)")

# Control threats
print()
print("=" * 90)
print(f"  CONTROL/MIDRANGE at platinum")
print("=" * 90)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches
    FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
      AND (archetype_name LIKE '%Control%'
           OR archetype_name LIKE '%Midrange%'
           OR archetype_name LIKE '%Lessons%')
    ORDER BY total_matches DESC LIMIT 12
""")
ctrl_total = 0
for r in cur.fetchall():
    arch = (r[0] or "?")[:30]
    matches = r[2] or 0
    ctrl_total += matches
    share = matches / total * 100
    print(f"  {arch:<30s}  {r[1]:<6s}  {matches:>5,} matches  ({share:.2f}% of meta)")
print(f"  {'TOTAL CONTROL/MIDRANGE':<30s}  {'':<6s}  {ctrl_total:>5,} matches  ({ctrl_total/total*100:.2f}% of meta)")

con.close()
