import sys, sqlite3, json, gzip
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

print("=" * 80)
print("REPLAY FETCH VERIFICATION")
print("=" * 80)

# Tables
print("\n=== Replay tables/views in DB ===")
cur.execute("""
    SELECT name, type FROM sqlite_master
    WHERE type IN ('table', 'view')
      AND (name LIKE '%untapped_replay%' OR name LIKE '%v_untapped_replay%')
    ORDER BY type, name
""")
for name, ttype in cur.fetchall():
    cur.execute(f"SELECT COUNT(*) FROM {name}")
    print(f"  [{ttype:5s}] {name:38s}  rows={cur.fetchone()[0]}")

# Indexed replays
print("\n=== Indexed replays ===")
cur.execute("""
    SELECT short_id, player_name, archetype_primary, deck_name, n_games,
           log_size_bytes, gz_size_bytes, file_path
    FROM v_untapped_replays_with_meta
    ORDER BY fetched_at_utc DESC
""")
for r in cur.fetchall():
    print(f"  short_id={r[0]}")
    print(f"    player={r[1]}  archetype={r[2]}  deck_name={r[3]!r}  games={r[4]}")
    print(f"    log={r[5]/1024:.0f}KB  gz={r[6]/1024:.0f}KB")
    print(f"    file={r[7]}")
    p = Path(r[7])
    print(f"    file_exists={p.exists()}  on_disk_size={p.stat().st_size if p.exists() else 'N/A'}")
    print()

# Pick the smallest replay and show a teaser
print("=== Sample replay content ===")
cur.execute("""
    SELECT file_path, short_id, player_name, archetype_primary
    FROM v_untapped_replays_with_meta
    WHERE status = 'ok'
    ORDER BY log_size_bytes ASC LIMIT 1
""")
row = cur.fetchone()
if row:
    fpath, sid, player, arch = row
    print(f"  Loading {sid} ({player}, {arch})")
    with gzip.open(fpath, 'rb') as f:
        data = json.loads(f.read())
    print(f"  Top-level keys: {list(data.keys())}")
    print(f"  decks: {len(data['decks'])} games")
    print(f"  log: {len(data['log']):,} chars")
    print()
    print("  --- log lines 100-110 (mid-game sample) ---")
    log_lines = data['log'].split('\n')
    for ln in log_lines[100:110]:
        print(f"    {ln[:160]}")

# Unfetched count
print()
print("=== Unfetched short_ids remaining ===")
cur.execute("SELECT COUNT(*) FROM v_untapped_replays_unfetched")
remaining = cur.fetchone()[0]
print(f"  {remaining} short_ids in untapped_entries not yet fetched")

# Storage check
print()
print("=== On-disk replay storage ===")
replay_dir = ROOT / 'data' / 'untapped' / 'replays'
if replay_dir.exists():
    files = list(replay_dir.glob("*.json.gz"))
    total = sum(f.stat().st_size for f in files)
    print(f"  files: {len(files)}")
    print(f"  total: {total/1024/1024:.2f} MB")
    print(f"  avg:   {total/len(files)/1024:.0f} KB/replay" if files else "")

con.close()
