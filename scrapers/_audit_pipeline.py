"""End-to-end audit of the Untapped pipeline. Verifies every table is populated,
every view returns sensible data, and the data agrees across sources."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 80)
print("UNTAPPED PIPELINE AUDIT")
print("=" * 80)

# 1. All tables exist + populated
print("\n=== Tables (data tier) ===")
for tbl in [
    'untapped_snapshots', 'untapped_entries', 'untapped_tags',
    'untapped_card_db',
    'untapped_replays', 'untapped_sideboard_plans',
    'untapped_meta_periods', 'untapped_meta_snapshots', 'untapped_meta_archetypes',
    'untapped_matchup_snapshots', 'untapped_matchups',
    'untapped_premium_matchup_snapshots', 'untapped_premium_matchups',
]:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cur.fetchone()[0]
        status = "OK" if n > 0 else "EMPTY"
        print(f"  [{status:5s}] {tbl:42s} rows={n}")
    except sqlite3.OperationalError as e:
        print(f"  [ERROR] {tbl:42s} {e}")

print("\n=== Views ===")
cur.execute("""
    SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'v_untapped%'
    ORDER BY name
""")
for (name,) in cur.fetchall():
    try:
        cur.execute(f"SELECT COUNT(*) FROM {name}")
        n = cur.fetchone()[0]
        print(f"  [OK   ] {name:42s} rows={n}")
    except Exception as e:
        print(f"  [ERROR] {name:42s} {e}")

# 2. Cross-source agreement on Izzet Prowess
print("\n=== Izzet Prowess cross-source check ===")

# Mythic leaderboard view
cur.execute("""
    SELECT n_players, total_matches, weighted_wr
    FROM v_untapped_latest_archetypes
    WHERE archetype = 'Izzet'
""")
row = cur.fetchone()
if row:
    print(f"  Mythic leaderboard:    {row[0]} pilots, {row[1]} matches, {row[2]}% weighted WR")

# Meta scraper Bo3 plat
cur.execute("""
    SELECT total_matches, win_rate, tier_val
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND archetype_name='Izzet Prowess' AND rank_tier='platinum' AND last_7_days=0
""")
row = cur.fetchone()
if row:
    print(f"  Meta Bo3 Plat (free):  {row[0]:>5} matches  WR={row[1]}  tier_val={row[2]}")

# Premium matchups Bo3 plat -- if Prowess is friendly, average its WR
cur.execute("""
    SELECT SUM(observed_match_count) AS total_n,
           ROUND(SUM(observed_match_count * win_rate) / SUM(observed_match_count), 2) AS weighted_wr,
           COUNT(*) AS n_matchups
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND friendly_archetype='Izzet Prowess' AND rank_tier='Platinum' AND last_7_days=0
""")
row = cur.fetchone()
if row and row[0]:
    print(f"  Premium matchup matrix: {row[0]:>5} matches across {row[2]} matchups, weighted WR = {row[1]}%")

# 3. Compare UW Flash (Azorius Tempo) and Izzet Prowess head-to-head
print("\n=== Head-to-head (UW Flash vs Izzet Prowess at platinum) ===")
cur.execute("""
    SELECT friendly_archetype, opponent_archetype, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
      AND ((friendly_archetype='Azorius Tempo' AND opponent_archetype='Izzet Prowess')
        OR (friendly_archetype='Izzet Prowess' AND opponent_archetype='Azorius Tempo'))
""")
for r in cur.fetchall():
    print(f"  {r[0]} vs {r[1]:25s}  n={r[2]:>4}  WR={r[3]}%")

# 4. Premium expected WR for the top contender decks (re-compute fresh)
print("\n=== Expected WR for top archetypes at platinum (matches >= 100, weighted by opponent meta share) ===")

cur.execute("""
    SELECT archetype_name, total_matches
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND rank_tier='platinum' AND last_7_days=0
""")
share_map = {r[0]: r[1] for r in cur.fetchall() if r[0]}
total_meta_matches = sum(share_map.values()) or 1

# All friendlies
cur.execute("""
    SELECT DISTINCT friendly_archetype FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
      AND friendly_archetype IS NOT NULL
""")
friendlies = [r[0] for r in cur.fetchall()]

results = []
for f in friendlies:
    cur.execute("""
        SELECT opponent_archetype, observed_match_count, win_rate
        FROM v_untapped_premium_matchups_named
        WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
          AND friendly_archetype = ? AND observed_match_count >= 100
    """, (f,))
    rows = cur.fetchall()
    if not rows: continue
    weighted_wr_num = 0
    weighted_share_denom = 0
    coverage_n = 0
    for opp, n, wr in rows:
        opp_share = share_map.get(opp, 0)
        weighted_wr_num += wr * opp_share
        weighted_share_denom += opp_share
        coverage_n += n
    ewr = weighted_wr_num / weighted_share_denom if weighted_share_denom else 0
    coverage = weighted_share_denom / total_meta_matches * 100
    f_share = share_map.get(f, 0) / total_meta_matches * 100
    results.append((f, share_map.get(f, 0), f_share, ewr, coverage, coverage_n))

results.sort(key=lambda x: -x[3])  # by expected WR desc
print(f"  {'archetype':<28s}  {'meta%':>6s}  {'exp WR%':>7s}  {'covers%':>7s}  {'sample n':>9s}")
print("  " + "-" * 72)
for arch, n_m, share, ewr, cov, sn in results:
    print(f"  {arch:<28s}  {share:>5.1f}%  {ewr:>6.2f}%  {cov:>6.0f}%  {sn:>9}")

# 5. Confirm sideboard plans table works
print("\n=== Sideboard plans by archetype (top 10 by replay count) ===")
cur.execute("""
    SELECT archetype_primary, COUNT(DISTINCT replay_short_id) AS n_replays, COUNT(*) AS n_transitions
    FROM v_untapped_sideboard_plans_with_meta
    GROUP BY archetype_primary
    ORDER BY n_transitions DESC LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r[0] or '?':<28s} {r[1]:>3} unique replays, {r[2]:>3} game-to-game SB transitions")

# 6. Card db sanity check
print("\n=== Card db sanity ===")
cur.execute("SELECT COUNT(*) FROM untapped_card_db WHERE name IS NOT NULL AND name != ''")
named = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM untapped_card_db")
total = cur.fetchone()[0]
print(f"  {named:,}/{total:,} cards have names ({named/total*100:.1f}%)")

# Spot-check known recent cards
print("  Spot checks:")
for name in ["Aven Interrupter", "Beza, the Bounding Spring", "Aang, Swift Savior", "Wan Shi Tong, Librarian", "Erode"]:
    cur.execute("SELECT grpid, set_code FROM untapped_card_db WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        print(f"    [OK] {name!r}: grpid={row[0]} set={row[1]}")
    else:
        print(f"    [MISS] {name!r}: NOT FOUND")

# 7. Replay file sanity
print("\n=== Replay file sanity ===")
cur.execute("""
    SELECT COUNT(*), SUM(log_size_bytes), SUM(gz_size_bytes)
    FROM untapped_replays WHERE status='ok'
""")
n, raw, gz = cur.fetchone()
print(f"  {n} replays indexed, {raw/1024/1024:.1f}MB raw, {gz/1024/1024:.1f}MB gz on disk")

# Verify each file actually exists
import os
cur.execute("SELECT short_id, file_path FROM untapped_replays WHERE status='ok' LIMIT 100")
missing = 0
for sid, fp in cur.fetchall():
    if not os.path.exists(fp):
        missing += 1
print(f"  {missing} files missing from disk (out of first 100 sampled)")

con.close()
print("\n[OK] Audit complete")
