"""Cross-check Zevin's matchup claims against Untapped premium Bo3 plat data."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Zevin's stated matchup verdicts
zevin_reads = [
    ("Cub",                "Mono-Green Stompy",        "FAVORED"),
    ("Cub-alt",            "Mono-Green Landfall",      "FAVORED"),
    ("Airbending",         "Bant Airbending",          "FAVORED"),
    ("Lessons",            "Izzet Lessons",            "FAVORED"),
    ("Control-Jeskai",     "Jeskai Control",           "FAVORED"),
    ("Control-Dimir",      "Dimir Control",            "FAVORED"),
    ("Reanimator",         "Sultai Reanimator",        "EVEN"),
    ("Reanimator-alt",     "Glint-Eye Reanimator",     "EVEN"),
    ("Dimir Midrange",     "Dimir Midrange",           "UNFAV"),
    ("Landfall",           "Mono-Green Landfall",      "FAVORED"),
    ("Rakdos Monument",    "Rakdos Monument",          "FAVORED"),
    ("Excruciator",        "Dimir Excruciator",        "EVEN"),
    ("Spelementals",       "Izzet Spellementals",      "UNFAV"),
    ("Prowess",            "Izzet Prowess",            "FAVORED-by-data"),  # Zevin doesn't list, but data shows it
]

print("=" * 95)
print("ZEVIN'S READ vs UNTAPPED PLATINUM BO3 DATA (Azorius Tempo as friendly)")
print("=" * 95)
print(f"  {'Zevin label':<22s}  {'Opp archetype':<25s}  {'Zevin says':<12s}  {'Plat n':>6s}  {'Plat WR':>7s}  {'Verdict':<10s}")
print("  " + "-" * 90)

for zlabel, archname, zread in zevin_reads:
    cur.execute("""
        SELECT observed_match_count, win_rate
        FROM v_untapped_premium_matchups_named
        WHERE format='Traditional_Ladder' AND rank_tier='Platinum' AND last_7_days=0
          AND friendly_archetype='Azorius Tempo' AND opponent_archetype = ?
    """, (archname,))
    row = cur.fetchone()
    if row:
        n, wr = row
        actual = "FAVORED" if wr >= 53 else ("UNFAV" if wr <= 47 else "EVEN")
        agree = "✓" if zread.startswith(actual[:5]) or actual.startswith(zread[:5]) else ("?" if zread == "FAVORED-by-data" else "≠")
        print(f"  {zlabel:<22s}  {archname:<25s}  {zread:<12s}  {n:>6}  {wr:>6.1f}%  {actual} {agree}")
    else:
        print(f"  {zlabel:<22s}  {archname:<25s}  {zread:<12s}  {'(no data, n<100)':>20s}")

# Also check the head-to-head Prowess number to see what Zevin doesn't say
print()
print("=" * 95)
print("THE ELEPHANT — Zevin doesn't list Prowess as a matchup. Why?")
print("=" * 95)
cur.execute("""
    SELECT rank_tier, observed_match_count, win_rate
    FROM v_untapped_premium_matchups_named
    WHERE format='Traditional_Ladder' AND last_7_days=0
      AND friendly_archetype='Azorius Tempo' AND opponent_archetype='Izzet Prowess'
    ORDER BY rank_tier
""")
for r in cur.fetchall():
    print(f"  Azorius Tempo vs Izzet Prowess at {r[0]:<10s}  n={r[1]:>4}  WR={r[2]:>5.1f}%")

# Check Zevin's PT field comp claim - "40% Cub"
print()
print("=" * 95)
print("ZEVIN'S CLAIM: 'PT field was about 40% Cub decks' — verify with PT SOS data")
print("=" * 95)
cur.execute("""
    SELECT d.archetype, COUNT(*) AS n
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE e.name LIKE 'Pro Tour Secrets of Strixhaven%'
    GROUP BY d.archetype ORDER BY n DESC LIMIT 15
""")
total_pt = 0
arch_counts = []
for r in cur.fetchall():
    arch_counts.append((r[0], r[1]))
    total_pt += r[1]
print(f"\n  Total PT SOS decks: {total_pt}")
for arch, n in arch_counts:
    pct = n/total_pt*100
    cub_marker = "  ← Cub" if 'Landfall' in arch or 'Stompy' in arch or 'Ouroboroid' in arch else ""
    print(f"    {arch:<28s}  {n:>3}  ({pct:5.1f}%){cub_marker}")

con.close()
