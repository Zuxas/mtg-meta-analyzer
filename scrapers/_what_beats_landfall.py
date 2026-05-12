"""Sanity check: how do various Izzet/UW decks fare against current Mono-Green Landfall?
Establish a baseline for what kinds of decks beat the Cub-Landfall shell now."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 90)
print("All decks vs Mono-Green Landfall at Bo3 platinum (current meta, n>=100)")
print("=" * 90)
cur.execute("""
    SELECT friendly_archetype, friendly_colors, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
      AND opponent_archetype = 'Mono-Green Landfall' AND observed_match_count >= 100
    ORDER BY win_rate DESC
""")
print(f"  {'friendly archetype':<28s}  {'colors':<6s}  {'n':>4s}  {'WR':>6s}")
print("  " + "-" * 60)
for r in cur.fetchall():
    arch, col, n, wr = r
    marker = "++" if wr >= 55 else ("--" if wr <= 45 else "  ")
    print(f"  {arch:<28s}  {col:<6s}  {n:>4}  {wr:>5.1f}%  {marker}")

# Now reverse: what does Mono-Green Landfall lose to?
print()
print("=" * 90)
print("Mono-Green Landfall as friendly — what does IT lose to? (n>=100)")
print("=" * 90)
cur.execute("""
    SELECT opponent_archetype, opponent_colors, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
      AND friendly_archetype = 'Mono-Green Landfall' AND observed_match_count >= 100
    ORDER BY win_rate ASC
""")
print(f"  {'opponent':<28s}  {'colors':<6s}  {'n':>4s}  {'WR for MGL':>10s}")
print("  " + "-" * 60)
for r in cur.fetchall():
    opp, col, n, wr = r
    marker = "MGL WINS" if wr >= 55 else ("MGL LOSES" if wr <= 45 else "EVEN")
    print(f"  {opp:<28s}  {col:<6s}  {n:>4}  {wr:>5.1f}%  {marker}")

con.close()
