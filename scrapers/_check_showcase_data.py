"""
Check what the public archetype_matchups_showcase endpoint actually contains.
Resolve the friendly+opponent archetype IDs against untapped_tags.
"""
import json, sqlite3, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

# Pull fresh
req = urllib.request.Request(
    "https://api.mtga.untapped.gg/api/v1/analytics/query/archetype_matchups_showcase",
    headers={"User-Agent": "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)",
             "Accept": "application/json",
             "Origin": "https://mtga.untapped.gg", "Referer": "https://mtga.untapped.gg/"})
data = json.loads(urllib.request.urlopen(req).read())
print(f"Total rows: {len(data)}")

# We need to translate primary_tag_group_id -> archetype_name
# The meta scraper stores this in untapped_meta_archetypes
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Build pgid -> archetype_name lookup from any recent snapshot
cur.execute("""
    SELECT primary_tag_group_id, archetype_name, colors_str
    FROM untapped_meta_archetypes
    WHERE archetype_name IS NOT NULL
    GROUP BY primary_tag_group_id
""")
pgid_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
print(f"Loaded {len(pgid_map)} pgid -> archetype mappings")

# What meta_period is this from?
cur.execute("""
    SELECT id, event_name, description, start_ts, end_ts
    FROM untapped_meta_periods
    WHERE id = ?
""", (data[0]["meta_period_id"],))
mp = cur.fetchone()
if mp:
    print(f"Meta period: id={mp[0]} event={mp[1]} desc={mp[2]!r} {mp[3][:10]} -> {mp[4][:10]}")

# What are the 7 opponents?
opponents = sorted(set(r["opponent_archetype"] for r in data))
print()
print(f"=== {len(opponents)} showcase opponents ===")
for opp in opponents:
    name, colors = pgid_map.get(opp, ("?", "?"))
    print(f"  pgid={opp:5d}  {name} ({colors})")

# Find Azorius Tempo (UW Flash) as friendly archetype
print()
print("=== Looking up Azorius Tempo's matchups ===")
target_names = ["Azorius Tempo", "Azorius Flash", "Azorius Control"]
for tname in target_names:
    # Find pgid for this archetype
    target_pgid = None
    for pgid, (name, colors) in pgid_map.items():
        if name == tname:
            target_pgid = pgid
            break
    if not target_pgid:
        print(f"  {tname}: NOT FOUND in mapping")
        continue
    print(f"\n  {tname} (pgid={target_pgid}):")
    rows = [r for r in data if r["friendly_archetype"] == target_pgid]
    if not rows:
        print(f"    no rows for pgid={target_pgid}")
        continue
    rows.sort(key=lambda r: -r["observed_match_count"])
    for r in rows:
        opp_name, opp_col = pgid_map.get(r["opponent_archetype"], ("?", "?"))
        n = r["observed_match_count"]
        w = r["matches_won"]
        wr = w / n * 100 if n else 0
        print(f"    vs {opp_name:<25s}  matches={int(n):>5}  WR={wr:5.1f}%")

# Show all archetypes that appear as friendly with their best/worst matchups
print()
print("=== Sample: best & worst matchups per archetype (top 15 by total matches) ===")
from collections import defaultdict
by_friendly = defaultdict(list)
for r in data:
    by_friendly[r["friendly_archetype"]].append(r)

# Sort archetypes by total matches
arch_volume = [(pgid, sum(r["observed_match_count"] for r in rows)) for pgid, rows in by_friendly.items()]
arch_volume.sort(key=lambda x: -x[1])

for pgid, total in arch_volume[:15]:
    name, colors = pgid_map.get(pgid, (f"pgid:{pgid}", "?"))
    rows = by_friendly[pgid]
    rows.sort(key=lambda r: -(r["matches_won"] / r["observed_match_count"] if r["observed_match_count"] else 0))
    print(f"\n  {name} ({colors}) - {int(total):,} total matches:")
    for r in rows:
        opp_name, _ = pgid_map.get(r["opponent_archetype"], (f"pgid:{r['opponent_archetype']}", "?"))
        n = r["observed_match_count"]
        w = r["matches_won"]
        wr = w / n * 100 if n else 0
        print(f"    vs {opp_name:<25s}  n={int(n):>5}  WR={wr:5.1f}%")

con.close()
