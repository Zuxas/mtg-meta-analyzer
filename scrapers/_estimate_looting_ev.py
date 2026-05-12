"""
Estimate expected WR for the revised meta-fighting Looting build.
Use meta share data (real) + structural matchup analysis (estimated from cards).
"""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Pull current Bo3 plat meta share for all archetypes with n>=100
cur.execute("""
    SELECT archetype_name, total_matches
    FROM v_untapped_meta_latest
    WHERE format='Traditional_Ladder' AND last_7_days=0 AND rank_tier='platinum'
      AND total_matches >= 100
    ORDER BY total_matches DESC
""")
meta = cur.fetchall()
total = sum(r[1] for r in meta)

# Estimated matchup WR for the revised Looting build:
# Base assumptions (drawn from structural analysis of the cards):
# - Original Looting vs MGL was ~30%
# - Adding 2 main Pyroclasm + 2 SB Get Out + 1 SB Iroh's Demo: ~42% (per earlier math)
# - Original Looting vs Prowess was ~40% (lost the race)
# - 2 main Pyroclasm wipes Prowess Monks/Otters: ~46%
# - +Abrade kills Cori-Steel artifact: small bonus
# - Original Looting vs Control: even-ish (~50%) — Riddler good vs them
# - Adding shapeshifters + Get Out + Detect Intrusion vs UW Tempo: ~50% (was ~35%)
# - vs Lessons: still favored (Spell Snare + bounce + sweepers all hit them)

# Conservative estimates, tagged by confidence
estimates = {
    'Mono-Green Landfall':    (42, 'structural: 2 main Pyroclasm covers t2-3, Get Out vs enchantments g2+'),
    'Izzet Prowess':          (45, 'structural: Pyroclasm covers Monks/Otters, but Crab still inevitable'),
    'Azorius Tempo':          (45, 'still bad: Aven/Aang on engine, but shapeshifters help dodge tax'),
    'Izzet Spellementals':    (48, 'Crab and Flock are problems, Pyroclasm helps slightly'),
    'Jeskai Control':         (52, 'Riddler good vs them, more counters in SB now'),
    'Golgari Control':        (52, 'Pyroclasm vs their creature-light builds'),
    'Yore Control':           (50, 'No clear edge, even game'),
    'Dimir Excruciator':      (50, 'Excruciator races you, but Pyroclasm hits its early threats'),
    'Izzet Lessons':          (55, 'You bounce their Crabs, counter their Lessons'),
    'Dimir Midrange':         (45, 'Kaito + discard hurts your engine'),
    'Selesnya Aggro':         (55, 'Pyroclasm is great here, evasion clocks them'),
    'Selesnya Landfall':      (42, 'Similar to MGL, slightly weaker version'),
    'Sultai Reanimator':      (47, 'Pyroclasm + Spell Snare interact some, Ghost Vacuum helps'),
    'Boros Aggro':            (55, 'Pyroclasm + Tiger-Seal is the dream'),
    'Glint-Eye Reanimator':   (45, 'Hard for Looting to interact with reanimation'),
    'Dimir Oculus':           (50, 'Standard control-vs-tempo dynamic'),
}

# Compute EV
print("=" * 90)
print("REVISED LOOTING BUILD - estimated EV vs current Bo3 plat meta")
print("=" * 90)
print(f"  {'archetype':<28s}  {'meta%':>6s}  {'est WR':>7s}  {'confidence':<10s}  notes")
print("  " + "-" * 95)
weighted_wr = 0
weighted_share = 0
covered_decks = 0
unmatched = []
for arch, matches in meta:
    share = matches / total * 100
    est = estimates.get(arch)
    if est:
        wr, note = est
        weighted_wr += wr * matches
        weighted_share += matches
        covered_decks += 1
        marker = '++' if wr >= 55 else ('--' if wr <= 45 else '  ')
        print(f"  {arch:<28s}  {share:>5.1f}%  {wr:>5}%   {marker}          {note[:55]}")
    else:
        unmatched.append((arch, share))

print()
print(f"Covered {covered_decks}/{len(meta)} archetypes ({weighted_share/total*100:.0f}% of plat meta)")
print(f"Expected WR (weighted by meta share):  {weighted_wr/weighted_share:.2f}%")

if unmatched:
    print(f"\nUncovered archetypes (no estimate, would need analysis):")
    for a, s in unmatched[:10]:
        print(f"  {a:<28s} {s:.1f}% of meta")

# Compare with the established decks
print()
print("=" * 90)
print("Comparison: revised Looting vs known decks at platinum")
print("=" * 90)
print(f"  {'deck':<28s}  {'expected WR':>11s}  source")
print("  " + "-" * 70)
print(f"  {'Mono-Green Landfall':<28s}  {'58.56%':>11s}  Untapped premium data")
print(f"  {'Izzet Prowess':<28s}  {'54.65%':>11s}  Untapped premium data")
print(f"  {'Azorius Tempo':<28s}  {'52.35%':>11s}  Untapped premium data")
print(f"  {'Izzet Spellementals':<28s}  {'50.42%':>11s}  Untapped premium data")
print(f"  {'REVISED LOOTING':<28s}  {weighted_wr/weighted_share:>10.2f}%   structural estimate (lower confidence)")

con.close()
