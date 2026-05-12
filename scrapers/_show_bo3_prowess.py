"""Pull Bo3 Izzet Prowess decklists - need n_games >= 2."""
import sys, sqlite3, json, gzip
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

cur.execute("SELECT grpid, name, set_code FROM untapped_card_db")
name_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

# Find all Izzet pilots with multi-game replays
cur.execute("""
    SELECT e.player_name, r.deck_name, e.matches_count, e.win_rate, r.file_path, r.n_games
    FROM untapped_entries e
    JOIN untapped_replays r ON e.short_id = r.short_id
    WHERE e.archetype_primary = 'Izzet' AND r.n_games >= 2
    ORDER BY e.matches_count DESC
""")
candidates = cur.fetchall()
print(f"Found {len(candidates)} Bo3 Izzet pilots\n")

# Show each pilot's deck/SB
from collections import Counter
for player, dname, n, wr, fpath, ng in candidates[:5]:
    print("=" * 80)
    print(f"PILOT: {player}  ({dname!r})")
    print(f"  matches={n}  WR={wr}%  games_in_replay={ng}")
    print("=" * 80)
    with gzip.open(fpath, 'rb') as f:
        data = json.loads(f.read())
    
    # Game 1 main + sideboard
    g1 = data['decks'][0]
    deck = g1.get('deck', {})
    main = Counter(deck.get('mainDeck', []))
    sb = Counter(deck.get('sideboard', []))
    
    print(f"\n  GAME 1 MAINBOARD ({sum(main.values())}):")
    for grpid, cnt in sorted(main.items(), key=lambda x: (-x[1], name_map.get(x[0], ('?', ''))[0])):
        nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
        print(f"    {cnt}  {nm}")
    
    print(f"\n  SIDEBOARD ({sum(sb.values())}):")
    for grpid, cnt in sorted(sb.items(), key=lambda x: (-x[1], name_map.get(x[0], ('?', ''))[0])):
        nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
        print(f"    {cnt}  {nm}")
    print()

con.close()
