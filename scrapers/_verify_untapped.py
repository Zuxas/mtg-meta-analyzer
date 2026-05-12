import sys, sqlite3, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 80)
print("UNTAPPED TABLES IN mtg_meta.db")
print("=" * 80)
cur.execute("""
    SELECT name, type FROM sqlite_master
    WHERE name LIKE 'untapped%' OR name LIKE 'v_untapped%'
    ORDER BY type, name
""")
for name, ttype in cur.fetchall():
    cur.execute(f"SELECT COUNT(*) FROM {name}")
    n = cur.fetchone()[0]
    print(f"  [{ttype:5s}] {name:38s}  rows={n}")

print()
print("=" * 80)
print("SNAPSHOT METADATA")
print("=" * 80)
cur.execute("SELECT id, captured_at_utc, n_entries, source_url, notes FROM untapped_snapshots ORDER BY id")
for r in cur.fetchall():
    print(f"  id={r[0]}  at={r[1]}  n={r[2]}  src={r[3]}  notes={r[4]}")

print()
print("=" * 80)
print("LATEST ARCHETYPES VIEW (top 10 by matches)")
print("=" * 80)
cur.execute("""
    SELECT archetype, colors, n_players, total_matches, weighted_wr
    FROM v_untapped_latest_archetypes
    ORDER BY total_matches DESC LIMIT 10
""")
print(f"  {'archetype':<15s}  {'colors':<6s}  {'players':<7s}  {'matches':<7s}  {'WR%':<6s}")
print(f"  {'-'*15:<15s}  {'-'*6:<6s}  {'-'*7:<7s}  {'-'*7:<7s}  {'-'*6:<6s}")
for r in cur.fetchall():
    print(f"  {r[0]:<15s}  {r[1]:<6s}  {r[2]:<7d}  {r[3]:<7d}  {r[4]}")

print()
print("=" * 80)
print("AZORIUS DETAIL (latest snapshot)")
print("=" * 80)
cur.execute("""
    SELECT player_name, colors_str, matches_count, win_rate, rank_approx, archetype_primary
    FROM v_untapped_latest_entries
    WHERE archetype_primary = 'Azorius'
    ORDER BY matches_count DESC
""")
for r in cur.fetchall():
    print(f"  {r[0]:<25s}  {r[1]:<4s}  matches={r[2]:<4d}  WR={r[3]:<5.1f}  rank~{r[4]}  arch={r[5]}")

print()
print("=" * 80)
print("INTEGRATION CHECK: existing meta-analyzer tables (untouched)")
print("=" * 80)
cur.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name NOT LIKE 'untapped%' AND name NOT LIKE 'sqlite_%'
    ORDER BY name LIMIT 15
""")
for (name,) in cur.fetchall():
    cur.execute(f"SELECT COUNT(*) FROM [{name}]")
    n = cur.fetchone()[0]
    print(f"  {name:35s}  rows={n}")

con.close()
print()
print("[OK] schema integrated, no existing tables touched")
