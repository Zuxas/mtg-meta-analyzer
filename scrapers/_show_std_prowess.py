"""
Bo3 Standard Izzet Prowess - filter to Standard-only pilots (TLA/SOA/EOE era cards)
and check meta-analyzer DB for tournament Standard Prowess lists.
"""
import sys, sqlite3, json, gzip
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Standard 2026 sets (post-rotation)
STANDARD_SETS = {'TLA','SOA','SOS','OM1','BIG','BLB','DSK','FDN','DFT','TDM','FIN','EOE','TMT','ECL','OTJ'}

cur.execute("SELECT grpid, name, set_code FROM untapped_card_db")
name_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

# Filter Bo3 Izzet replays to Standard-only (>80% of cards from Standard sets)
cur.execute("""
    SELECT e.player_name, r.deck_name, e.matches_count, e.win_rate, r.file_path, r.n_games, e.short_id
    FROM untapped_entries e
    JOIN untapped_replays r ON e.short_id = r.short_id
    WHERE e.archetype_primary = 'Izzet' AND r.n_games >= 2
    ORDER BY e.matches_count DESC
""")

print("=" * 80)
print("STANDARD-LEGAL Izzet Prowess Bo3 pilots (>80% Standard-set cards)")
print("=" * 80)

standard_pilots = []
for player, dname, n, wr, fpath, ng, short_id in cur.fetchall():
    with gzip.open(fpath, 'rb') as f:
        data = json.loads(f.read())
    main = data['decks'][0].get('deck', {}).get('mainDeck', [])
    main_count = Counter(main)
    
    std = sum(c for grpid, c in main_count.items() 
              if name_map.get(grpid, ('', ''))[1] in STANDARD_SETS)
    total = sum(main_count.values())
    pct = std / total * 100 if total else 0
    
    label = "STANDARD" if pct >= 80 else ("MIXED" if pct >= 50 else "NON-STD")
    print(f"  [{label:<8s}] {player:<22s} {dname!r:<35s}  Std={pct:5.1f}%  n={n}")
    if pct >= 80:
        standard_pilots.append((player, dname, n, wr, fpath, short_id))

# Now show consensus mainboard + sideboard from Standard Prowess pilots
print()
print("=" * 80)
print(f"CONSENSUS for {len(standard_pilots)} Standard Bo3 Izzet pilots")
print("=" * 80)

main_total = Counter()
sb_total = Counter()
n_pilots = 0

for player, dname, matches, wr, fpath, sid in standard_pilots:
    with gzip.open(fpath, 'rb') as f:
        data = json.loads(f.read())
    main = data['decks'][0].get('deck', {}).get('mainDeck', [])
    sb = data['decks'][0].get('deck', {}).get('sideboard', [])
    for grpid in main:
        main_total[grpid] += 1
    for grpid in sb:
        sb_total[grpid] += 1
    n_pilots += 1

print(f"\n  Avg copies (across {n_pilots} pilots) — main cards run by 2+ pilots:")
for grpid, total_copies in sorted(main_total.items(), key=lambda x: -x[1]):
    nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
    avg = total_copies / n_pilots
    if avg >= 0.5:
        print(f"    {avg:>4.1f}  {nm:<35s}  ({sc})")

print(f"\n  Avg SB copies — cards run by any pilot:")
for grpid, total_copies in sorted(sb_total.items(), key=lambda x: -x[1]):
    nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
    avg = total_copies / n_pilots
    if avg >= 0.3:
        print(f"    {avg:>4.1f}  {nm:<35s}  ({sc})")

# Now check the meta-analyzer's existing tournament data for Izzet/Prowess Standard lists
print()
print("=" * 80)
print("Tournament Standard Prowess in existing decks table (mtg_meta.db)")
print("=" * 80)

# Look at tables  
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decks'")
if cur.fetchone():
    cur.execute("PRAGMA table_info(decks)")
    cols = [c[1] for c in cur.fetchall()]
    print(f"  decks table columns: {cols[:15]}")
    
    # Try to find Izzet Prowess decks
    if 'archetype' in cols:
        cur.execute("""
            SELECT COUNT(*), archetype FROM decks
            WHERE LOWER(archetype) LIKE '%prowess%' OR LOWER(archetype) LIKE '%izzet%'
            GROUP BY archetype ORDER BY COUNT(*) DESC LIMIT 10
        """)
        for r in cur.fetchall():
            print(f"    {r[0]:>4}  {r[1]}")

# Also find SB plans for Standard Izzet only
print()
print("=" * 80)
print("Standard Bo3 Izzet sideboard plans (filtered)")  
print("=" * 80)
std_short_ids = [p[5] for p in standard_pilots]
if std_short_ids:
    placeholders = ','.join('?' * len(std_short_ids))
    cur.execute(f"""
        SELECT replay_short_id, from_game, to_game, n_cards_swapped, cards_in_json, cards_out_json
        FROM untapped_sideboard_plans
        WHERE replay_short_id IN ({placeholders})
        ORDER BY replay_short_id, from_game
    """, std_short_ids)
    for r in cur.fetchall():
        sid, fg, tg, ns, cin, cout = r
        # Find player
        player = next((p[0] for p in standard_pilots if p[5] == sid), '?')
        print(f"\n  {player} ({sid}) game {fg}->{tg}, swapped {ns}:")
        cin_l = json.loads(cin)
        cout_l = json.loads(cout)
        in_str = ', '.join("{}x {}".format(c['count'], c['name']) for c in cin_l)
        out_str = ', '.join("{}x {}".format(c['count'], c['name']) for c in cout_l)
        print(f"    IN:  {in_str}")
        print(f"    OUT: {out_str}")

con.close()
