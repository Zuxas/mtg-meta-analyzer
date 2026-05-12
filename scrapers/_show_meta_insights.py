import sys, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 95)
print("STANDARD BO1 (Ladder, pid=701) - PLATINUM TIER - top 30 archetypes by match volume")
print("=" * 95)
print(f"  {'archetype':<35s}  {'colors':<6s}  {'matches':>8s}  {'WR%':>6s}  {'avg_s':>6s}")
print("  " + "-" * 75)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches, win_rate, avg_seconds
    FROM v_untapped_meta_latest
    WHERE format = 'Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
    ORDER BY total_matches DESC LIMIT 30
""")
for r in cur.fetchall():
    arch = (r[0] or "?")[:35]
    matches = r[2] or 0
    wr = f"{r[3]:.2f}" if r[3] is not None else "-"
    avg = r[4] or 0
    print(f"  {arch:<35s}  {r[1]:<6s}  {matches:>8}  {wr:>6}  {avg:>6}")

print()
print("=" * 95)
print("STANDARD BO1 - SKILL CURVE: archetypes that gain WR going bronze -> platinum")
print("=" * 95)
print(f"  {'archetype':<35s}  {'colors':<6s}  {'bronze':>7s}  {'silver':>7s}  {'gold':>7s}  {'plat':>7s}  {'climb':>6s}")
print("  " + "-" * 95)
cur.execute("""
    SELECT archetype_name, colors_str, bronze_wr, silver_wr, gold_wr, plat_wr, climb_delta_wr, plat_matches
    FROM v_untapped_meta_skill_curve
    WHERE format = 'Ladder' AND last_7_days = 0
      AND plat_matches > 1000
      AND climb_delta_wr IS NOT NULL
    ORDER BY climb_delta_wr DESC LIMIT 15
""")
for r in cur.fetchall():
    arch = (r[0] or "?")[:35]
    fmt = lambda v: f"{v:.1f}" if v is not None else "-"
    print(f"  {arch:<35s}  {r[1]:<6s}  {fmt(r[2]):>7}  {fmt(r[3]):>7}  {fmt(r[4]):>7}  {fmt(r[5]):>7}  {r[6]:+.2f}")

print()
print("=" * 95)
print("STANDARD BO1 - SKILL CURVE (decks that LOSE WR at higher ranks - skill traps)")
print("=" * 95)
print(f"  {'archetype':<35s}  {'colors':<6s}  {'bronze':>7s}  {'silver':>7s}  {'gold':>7s}  {'plat':>7s}  {'climb':>6s}")
print("  " + "-" * 95)
cur.execute("""
    SELECT archetype_name, colors_str, bronze_wr, silver_wr, gold_wr, plat_wr, climb_delta_wr, plat_matches
    FROM v_untapped_meta_skill_curve
    WHERE format = 'Ladder' AND last_7_days = 0
      AND plat_matches > 1000
      AND climb_delta_wr IS NOT NULL
    ORDER BY climb_delta_wr ASC LIMIT 15
""")
for r in cur.fetchall():
    arch = (r[0] or "?")[:35]
    fmt = lambda v: f"{v:.1f}" if v is not None else "-"
    print(f"  {arch:<35s}  {r[1]:<6s}  {fmt(r[2]):>7}  {fmt(r[3]):>7}  {fmt(r[4]):>7}  {fmt(r[5]):>7}  {r[6]:+.2f}")

# Specifically: Azorius variants (UW Flash)
print()
print("=" * 95)
print("AZORIUS / UW FLASH - all variants in Standard Bo1 across ranks")
print("=" * 95)
cur.execute("""
    SELECT archetype_name, rank_tier, total_matches, win_rate
    FROM v_untapped_meta_latest
    WHERE format = 'Ladder' AND archetype_name LIKE '%Azorius%' AND last_7_days = 0
    ORDER BY archetype_name, CASE rank_tier
        WHEN 'bronze' THEN 1 WHEN 'silver' THEN 2 WHEN 'gold' THEN 3 WHEN 'platinum' THEN 4 END
""")
last = None
for r in cur.fetchall():
    arch = r[0]
    if arch != last:
        print(f"\n  {arch}")
        last = arch
    wr = f"{r[3]:.2f}" if r[3] is not None else "-"
    print(f"    {r[1]:<10s}  matches={r[2]:>5}  WR={wr}")

# Standard Bo3 - just match volume since no WR
print()
print("=" * 95)
print("STANDARD BO3 (Traditional_Ladder) - PLATINUM TIER - top 20 by volume (no WR available, free tier)")
print("=" * 95)
print(f"  {'archetype':<35s}  {'colors':<6s}  {'matches':>8s}  {'tier_val':>8s}")
print("  " + "-" * 70)
cur.execute("""
    SELECT archetype_name, colors_str, total_matches, tier_val
    FROM v_untapped_meta_latest
    WHERE format = 'Traditional_Ladder' AND rank_tier = 'platinum' AND last_7_days = 0
    ORDER BY total_matches DESC LIMIT 20
""")
for r in cur.fetchall():
    arch = (r[0] or "?")[:35]
    matches = r[2] or 0
    tv = f"{r[3]:.2f}" if r[3] is not None else "-"
    print(f"  {arch:<35s}  {r[1]:<6s}  {matches:>8}  {tv:>8}")

con.close()
