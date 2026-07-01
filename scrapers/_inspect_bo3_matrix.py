"""Inspect the Bo3 matchup matrix raw response."""
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

_cookies_path = ROOT / 'data' / 'untapped' / 'untapped_cookies.txt'
_cookie_pairs = {}
if _cookies_path.exists():
    for line in _cookies_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        _cookie_pairs[k.strip()] = v.strip()
_cookie_header = "; ".join(f"{k}={v}" for k, v in _cookie_pairs.items())
if not _cookie_header:
    sys.exit(f"missing cookies: populate {_cookies_path} (see scrapers/untapped_premium_scraper.py docstring)")

import urllib.request
req = urllib.request.Request(
    "https://api.mtga.untapped.gg/api/v1/analytics/query/archetype_matchups_by_event_scope_and_rank?MetaPeriodId=702&RankingClassScopeFilter=BRONZE_TO_MYTHIC",
    headers={"User-Agent":"mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)",
             "Accept":"application/json",
             "Origin":"https://mtga.untapped.gg","Referer":"https://mtga.untapped.gg/",
             "Cookie": _cookie_header})
data = json.loads(urllib.request.urlopen(req).read())
print(f"Total rows: {len(data)}")
print(f"\nFirst 3 rows:")
for r in data[:3]:
    print(json.dumps(r, indent=2))

ranks = sorted(set(r['ranking_class_before'] for r in data))
print(f"\nRank tiers: {ranks}")

pairs = set((r['friendly_archetype'], r['opponent_archetype']) for r in data)
fr = set(r['friendly_archetype'] for r in data)
op = set(r['opponent_archetype'] for r in data)
print(f"Unique pairs: {len(pairs)}, friendlies: {len(fr)}, opponents: {len(op)}")

# Tier counts
from collections import Counter
tc = Counter(r['ranking_class_before'] for r in data)
for t, n in sorted(tc.items()):
    print(f"  {t}: {n} rows")

# Pull names from DB
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()
cur.execute("""
    SELECT primary_tag_group_id, archetype_name, colors_str
    FROM untapped_meta_archetypes WHERE archetype_name IS NOT NULL
    GROUP BY primary_tag_group_id
""")
pgid_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
con.close()

# Find Azorius Tempo
print(f"\n=== Azorius Tempo (pgid=1164) Bo3 PLATINUM matchups ===")
plat_azt = [r for r in data if r['friendly_archetype']==1164 and r['ranking_class_before']=='Platinum']
plat_azt.sort(key=lambda r: -r['observed_match_count'])
for r in plat_azt:
    opp_name, opp_col = pgid_map.get(r['opponent_archetype'], ('?', '?'))
    n = r['observed_match_count']
    w = r['matches_won']
    wr = w/n*100 if n else 0
    marker = "++" if wr >= 55 else ("--" if wr <= 45 else "  ")
    print(f"  {marker} vs {opp_name:<28s} ({opp_col:<5s})  n={int(n):>4}  WR={wr:5.1f}%")

print(f"\n=== Azorius Tempo all ranks vs same opponents (skill curve) ===")
opps_seen = set(r['opponent_archetype'] for r in plat_azt)
ranks_order = ['Bronze','Silver','Gold','Platinum','Diamond','Mythic']
for opp in opps_seen:
    opp_name, _ = pgid_map.get(opp, ('?', '?'))
    print(f"\n  vs {opp_name}:")
    for tier in ranks_order:
        row = [r for r in data if r['friendly_archetype']==1164 and r['opponent_archetype']==opp and r['ranking_class_before']==tier]
        if row:
            r = row[0]
            n = r['observed_match_count']
            w = r['matches_won']
            wr = w/n*100 if n else 0
            print(f"    {tier:<10s}  n={int(n):>4}  WR={wr:5.1f}%")
