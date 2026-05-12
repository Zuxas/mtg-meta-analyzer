"""
Pull the actual Izzet Prowess decklist from the highest-volume top mythic pilot.
Look at Ultraman_1's 'Izzet Prowess 1' since it's literally named that.
"""
import sys, sqlite3, json, gzip
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

# Find the best Prowess pilot's replay
print("=" * 80)
print("ALL Izzet pilots in mythic top 98 (with Prowess subtype if any)")
print("=" * 80)
cur.execute("""
    SELECT e.player_name, r.deck_name, e.matches_count, e.win_rate, e.short_id, r.file_path, r.n_games
    FROM untapped_entries e
    JOIN untapped_replays r ON e.short_id = r.short_id
    WHERE e.archetype_primary = 'Izzet'
    ORDER BY e.matches_count DESC
""")
prowess_replays = []
for r in cur.fetchall():
    print(f"  {r[0]:<25s}  deck={r[1]!r:<35s}  matches={r[2]:>3}  WR={r[3]:>5.1f}  games={r[6]}")
    # Filter to Prowess-like
    if r[1] and ('prowess' in r[1].lower() or 'delver' in r[1].lower() or r[1] == '[P] UR' or r[1] == 'UR'):
        prowess_replays.append((r[0], r[1], r[2], r[3], r[5]))

# Pick the highest-volume Prowess-named replay
print()
print("=" * 80)
print("DECKLIST for the top-volume Izzet Prowess pilot")
print("=" * 80)

# Look up grpid -> name
cur.execute("SELECT grpid, name, set_code FROM untapped_card_db")
name_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

# Pick Ultraman_1 since deck is called "Izzet Prowess 1"
target = next((p for p in prowess_replays if 'prowess' in (p[1] or '').lower()), None)
if not target:
    target = prowess_replays[0] if prowess_replays else None
if not target:
    print("No Prowess replay found")
    sys.exit(0)

player, dname, n, wr, fpath = target
print(f"  Pilot: {player}")
print(f"  Deck: {dname!r}")
print(f"  Matches: {n}, WR: {wr}%")
print(f"  Source: {fpath}")
print()

with gzip.open(fpath, 'rb') as f:
    data = json.loads(f.read())

# Show game 1 (pre-board) and game 2 (post-board) decks
from collections import Counter
for game in data['decks']:
    g = game.get('game', '?')
    deck = game.get('deck', {})
    main = deck.get('mainDeck', [])
    sb = deck.get('sideboard', [])
    print(f"  --- GAME {g} ({deck.get('name', '?')}) ---")
    main_count = Counter(main)
    sb_count = Counter(sb)
    print(f"  MAIN ({sum(main_count.values())}):")
    # Group by type using set codes
    sorted_main = sorted(main_count.items(), key=lambda x: (-x[1], name_map.get(x[0], ('?', ''))[0]))
    for grpid, cnt in sorted_main:
        nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
        print(f"    {cnt}  {nm}  ({sc})")
    print(f"  SIDEBOARD ({sum(sb_count.values())}):")
    sorted_sb = sorted(sb_count.items(), key=lambda x: (-x[1], name_map.get(x[0], ('?', ''))[0]))
    for grpid, cnt in sorted_sb:
        nm, sc = name_map.get(grpid, (f'grpid:{grpid}', '?'))
        print(f"    {cnt}  {nm}  ({sc})")
    print()

con.close()
