"""Deep-dive Izzet Prowess vs UW Flash for RC DC Bo3."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Get meta share
cur.execute("""
    SELECT archetype_name, total_matches FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND rank_tier='platinum' AND last_7_days=0
""")
share_map = {r[0]: r[1] for r in cur.fetchall() if r[0]}
total = sum(share_map.values()) or 1

def show_matchups(deck_name, title):
    print(f"\n{'='*78}")
    print(f"  {title}")
    print(f"{'='*78}")
    cur.execute("""
        SELECT opponent_archetype, opponent_colors, observed_match_count, win_rate
        FROM v_untapped_premium_matchups_named
        WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
          AND friendly_archetype = ? AND observed_match_count >= 100
        ORDER BY observed_match_count DESC
    """, (deck_name,))
    rows = cur.fetchall()
    if not rows:
        print(f"  No matchups found at platinum for '{deck_name}' with n>=100")
        return None
    print(f"  {'opponent':<28s}  {'meta%':>5s}  {'n':>5s}  {'WR%':>6s}  {'note':>6s}")
    print(f"  {'-'*28}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*6}")
    expected_num = 0
    expected_denom = 0
    n_total = 0
    favorable = 0
    unfavorable = 0
    for opp, opp_col, n, wr in rows:
        opp_share = share_map.get(opp, 0) / total * 100
        marker = "FAVOR" if wr >= 55 else ("UNFAV" if wr <= 45 else "  ~  ")
        if wr >= 55: favorable += 1
        elif wr <= 45: unfavorable += 1
        # Weight by share
        expected_num += wr * share_map.get(opp, 0)
        expected_denom += share_map.get(opp, 0)
        n_total += n
        print(f"  {opp:<28s}  {opp_share:>4.1f}%  {n:>5}  {wr:>5.1f}%  {marker}")
    ewr = expected_num / expected_denom if expected_denom else 0
    cov = expected_denom / total * 100
    print()
    print(f"  Total samples: {n_total:,}")
    print(f"  Favorable matchups (>=55%): {favorable}")
    print(f"  Unfavorable matchups (<=45%): {unfavorable}")
    print(f"  Coverage of meta: {cov:.0f}%")
    print(f"  EXPECTED WR: {ewr:.2f}%")
    return ewr, n_total, favorable, unfavorable

# Run both
show_matchups("Izzet Prowess", "IZZET PROWESS — Bo3 Platinum, Current Meta")
show_matchups("Azorius Tempo", "AZORIUS TEMPO (UW Flash) — Bo3 Platinum, Current Meta")

# Compare head-to-head with skill-curve
print(f"\n{'='*78}")
print("  HEAD-TO-HEAD: how Prowess vs Flash performs across rank tiers")
print(f"{'='*78}")
cur.execute("""
    SELECT rank_tier, friendly_archetype, opponent_archetype, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND last_7_days=0
      AND ((friendly_archetype='Izzet Prowess' AND opponent_archetype='Azorius Tempo')
        OR (friendly_archetype='Azorius Tempo' AND opponent_archetype='Izzet Prowess'))
    ORDER BY rank_tier, friendly_archetype
""")
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]:<10s}  {r[1]:<18s} vs {r[2]:<18s}  n={r[3]:>4}  WR={r[4]}%")

# Last 7 days comparison if any data
print(f"\n{'='*78}")
print("  LAST 7 DAYS only — does the meta look different in the past week?")
print(f"{'='*78}")
cur.execute("""
    SELECT friendly_archetype, opponent_archetype, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=1
      AND friendly_archetype IN ('Izzet Prowess', 'Azorius Tempo')
      AND observed_match_count >= 30
    ORDER BY friendly_archetype, observed_match_count DESC
""")
rows = cur.fetchall()
if not rows:
    print("  No last-7-days data captured. Run: untapped_premium_scraper.py --last-7-days")
else:
    last_friendly = None
    for r in rows:
        if r[0] != last_friendly:
            print(f"\n  {r[0]}:")
            last_friendly = r[0]
        print(f"    vs {r[1]:<25s}  n={r[2]:>3}  WR={r[3]}%")

con.close()
