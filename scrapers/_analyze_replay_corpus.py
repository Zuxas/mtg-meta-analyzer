"""Analyze the replay corpus to see what's actually in there."""
import sys, sqlite3, json, gzip
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 80)
print("REPLAY CORPUS ANALYSIS")
print("=" * 80)

# 1. n_games distribution
print("\n=== n_games distribution (Bo1 vs Bo3 etc) ===")
cur.execute("""
    SELECT n_games, COUNT(*) AS cnt
    FROM untapped_replays
    WHERE status='ok'
    GROUP BY n_games
    ORDER BY n_games
""")
total_replays = 0
for n, cnt in cur.fetchall():
    print(f"  {n} games: {cnt} replays")
    total_replays += cnt
print(f"  TOTAL: {total_replays} replays")

# 2. Storage check
print("\n=== Storage ===")
cur.execute("""
    SELECT COUNT(*), SUM(log_size_bytes), SUM(gz_size_bytes)
    FROM untapped_replays WHERE status='ok'
""")
n, raw, gz = cur.fetchone()
print(f"  {n} replays, {raw/1024/1024:.1f} MB raw, {gz/1024/1024:.1f} MB gzipped ({gz/raw*100:.0f}% compression)")

# 3. By archetype
print("\n=== Replays by archetype ===")
cur.execute("""
    SELECT archetype_primary, COUNT(*) AS cnt, AVG(n_games) AS avg_games
    FROM v_untapped_replays_with_meta
    WHERE status='ok'
    GROUP BY archetype_primary
    ORDER BY cnt DESC
""")
for arch, cnt, avg_g in cur.fetchall():
    print(f"  {arch:<15s}  {cnt:3d} replays  avg_games={avg_g:.2f}")

# 4. Pull a multi-game replay if any exist, examine the deck diff
print("\n=== Multi-game replay structure (if any) ===")
cur.execute("""
    SELECT short_id, file_path, deck_name, n_games
    FROM untapped_replays
    WHERE status='ok' AND n_games > 1
    ORDER BY n_games DESC LIMIT 3
""")
multi = cur.fetchall()
if not multi:
    print("  NO multi-game replays found - all are Bo1.")
    print("  Sideboard plan extraction not viable from this data.")
else:
    print(f"  Found {len(multi)} multi-game replays:")
    for sid, fpath, name, ng in multi:
        print(f"\n  short_id={sid} deck={name!r} games={ng}")
        with gzip.open(fpath, 'rb') as f:
            data = json.loads(f.read())
        for game in data['decks']:
            d = game.get('deck', {})
            print(f"    game={game.get('game')}  main={len(d.get('mainDeck', []))}  sb={len(d.get('sideboard', []))}")

# 5. Event types — what game format are these from?
print("\n=== Event types (parsing first few logs) ===")
cur.execute("""
    SELECT short_id, file_path FROM untapped_replays
    WHERE status='ok' ORDER BY RANDOM() LIMIT 10
""")
event_counter = Counter()
for sid, fpath in cur.fetchall():
    with gzip.open(fpath, 'rb') as f:
        log_head = f.read()[:2500].decode('utf-8', errors='replace')
    # The reservedPlayers entries have eventId
    import re
    m = re.search(r'"eventId":\s*"([^"]+)"', log_head)
    if m:
        event_counter[m.group(1)] += 1

for ev, cnt in event_counter.most_common():
    print(f"  {ev}: {cnt}/10 sampled")

# 6. Sideboard sizes (Bo1 has tracker-injected SB usually 0-7, Bo3 is real 15)
print("\n=== Sideboard size distribution (game 1 only) ===")
cur.execute("""
    SELECT short_id, file_path FROM untapped_replays
    WHERE status='ok'
""")
sb_size_counter = Counter()
for sid, fpath in cur.fetchall():
    try:
        with gzip.open(fpath, 'rb') as f:
            data = json.loads(f.read())
        sb = data['decks'][0]['deck'].get('sideboard') or []
        # Sum quantities (sideboard format: alternating grpid, qty? or just grpids?)
        # We saw earlier: [85569, 85569] means 2 copies of 85569 — flat list of grpid repeats
        sb_size_counter[len(sb)] += 1
    except Exception:
        pass
for size, cnt in sorted(sb_size_counter.items()):
    print(f"  sb={size:2d}: {cnt} replays")

con.close()
