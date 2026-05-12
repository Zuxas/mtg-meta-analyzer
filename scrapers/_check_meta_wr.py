import sys, sqlite3, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Look at raw rows for Boros Aggro at platinum
cur.execute("""
    SELECT a.archetype_name, a.colors_str, a.rank_tier,
           a.total_matches, a.win_rate, a.avg_seconds,
           s.event_name, s.captured_at_utc
    FROM untapped_meta_archetypes a
    JOIN untapped_meta_snapshots s ON a.snapshot_id = s.id
    WHERE s.event_name = 'Traditional_Ladder'
      AND a.rank_tier = 'platinum'
      AND a.archetype_name LIKE '%Azorius%'
    ORDER BY a.total_matches DESC
""")
print("=== Azorius archetypes in Standard Bo3 (Traditional_Ladder), platinum ===")
print(f"{'archetype':<30s} {'colors':<6s} {'matches':>8s} {'WR%':>7s} {'avg_s':>7s}")
print("-" * 70)
for r in cur.fetchall():
    arch = r[0] or "?"
    matches = r[3] or 0
    wr = r[4] if r[4] is not None else 0
    avg_s = r[5] or 0
    print(f"{arch:<30s} {r[1]:<6s} {matches:>8} {wr:>7} {avg_s:>7}")

# Look at raw stored win_rate type for one row
print()
cur.execute("""
    SELECT typeof(win_rate), win_rate, total_matches
    FROM untapped_meta_archetypes
    WHERE rank_tier = 'platinum'
    LIMIT 5
""")
print("=== Raw type of win_rate column ===")
for r in cur.fetchall():
    print(f"  type={r[0]}  value={r[1]}  matches={r[2]}")

# All rows for one archetype across ranks
print()
cur.execute("""
    SELECT a.archetype_name, a.rank_tier, a.total_matches, a.win_rate
    FROM untapped_meta_archetypes a
    JOIN untapped_meta_snapshots s ON a.snapshot_id = s.id
    WHERE s.event_name = 'Traditional_Ladder' AND a.archetype_name = 'Azorius Tempo'
    ORDER BY a.rank_tier
""")
print("=== Azorius Tempo across all ranks ===")
for r in cur.fetchall():
    print(f"  {r[1]:<10s}  matches={r[2]:>5}  WR={r[3]}")

con.close()
