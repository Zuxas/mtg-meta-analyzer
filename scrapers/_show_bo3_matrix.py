"""Show full Bo3 platinum matchup matrix - what's actually matters tomorrow."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Get meta share for context
cur.execute("""
    SELECT archetype_name, total_matches
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND rank_tier='platinum' AND last_7_days=0
""")
share_map = {r[0]: r[1] for r in cur.fetchall() if r[0]}
total = sum(share_map.values())

# Pull all Bo3 plat matchups
cur.execute("""
    SELECT friendly_archetype, friendly_colors,
           opponent_archetype, opponent_colors,
           observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
      AND observed_match_count >= 100
    ORDER BY friendly_archetype, observed_match_count DESC
""")
rows = cur.fetchall()

# Group by friendly
from collections import defaultdict
by_friendly = defaultdict(list)
for r in rows:
    by_friendly[(r[0], r[1])].append(r)

# Show ranked by friendly's meta share
ordered = sorted(by_friendly.keys(), key=lambda k: -share_map.get(k[0], 0))

print("=" * 90)
print("STANDARD BO3 - PLATINUM MATCHUP MATRIX (n>=100, current meta period)")
print("=" * 90)
for (f_arch, f_col) in ordered:
    f_share = share_map.get(f_arch, 0) / total * 100 if total else 0
    print(f"\n  {f_arch} ({f_col})  [{f_share:.1f}% of meta]")
    for r in by_friendly[(f_arch, f_col)]:
        opp = r[2] or "?"
        opp_col = r[3] or "?"
        n = r[4]
        wr = r[5]
        marker = "++" if wr >= 55 else ("--" if wr <= 45 else "  ")
        opp_share = share_map.get(opp, 0) / total * 100 if total else 0
        print(f"    {marker} vs {opp + ' (' + opp_col + ')':<35s}  n={n:>4}  WR={wr:>5.1f}%   [opp: {opp_share:>4.1f}% of meta]")

# Specifically: weighted expected WR for each archetype in current meta
print()
print("=" * 90)
print("EXPECTED WR if you played each deck across the current Bo3 meta")
print("(weighted by opponent meta share, only matchups with n>=100)")
print("=" * 90)

for (f_arch, f_col) in ordered:
    matchups = by_friendly[(f_arch, f_col)]
    weighted_wr = 0
    weighted_share = 0
    for r in matchups:
        opp = r[2]
        wr = r[5]
        opp_share = share_map.get(opp, 0)
        weighted_wr += wr * opp_share
        weighted_share += opp_share
    ewr = weighted_wr / weighted_share if weighted_share else 0
    coverage = weighted_share / total * 100 if total else 0
    print(f"  {f_arch:<28s} ({f_col:<5s})  expected WR ≈ {ewr:5.2f}%  (covers {coverage:.0f}% of meta)")

con.close()
