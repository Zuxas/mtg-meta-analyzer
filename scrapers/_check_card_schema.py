import sys, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

for tbl in ['cards', 'card_data']:
    print(f"=== {tbl} schema ===")
    cur.execute(f"PRAGMA table_info({tbl})")
    cols = cur.fetchall()
    for c in cols:
        print(f"  {c[1]:30s}  {c[2]}")
    cur.execute(f"SELECT * FROM {tbl} LIMIT 1")
    row = cur.fetchone()
    if row:
        col_names = [c[1] for c in cols]
        print("  --- sample row ---")
        for cn, val in zip(col_names, row):
            v = str(val)
            if len(v) > 80: v = v[:80] + '...'
            print(f"    {cn:30s} = {v}")
    print()

# Search for an arena_id / grpid column
print("=== Search columns containing 'arena' or 'grp' ===")
for tbl in ['cards', 'card_data']:
    cur.execute(f"PRAGMA table_info({tbl})")
    for c in cur.fetchall():
        if 'arena' in c[1].lower() or 'grp' in c[1].lower() or 'mtga' in c[1].lower():
            print(f"  {tbl}.{c[1]}  ({c[2]})")

# Test a known grpid lookup: 51307 was in Piccirko's Boros deck (probably an Aura)
# 72178 was the deck_tile_id we saw on his leaderboard entry
print()
print("=== Try lookup of grpid 51307 (sample card from Piccirko's deck) ===")
for tbl in ['cards', 'card_data']:
    cur.execute(f"PRAGMA table_info({tbl})")
    cols = [c[1] for c in cur.fetchall()]
    for col in cols:
        if 'arena' in col.lower() or 'grp' in col.lower() or 'mtga' in col.lower():
            try:
                cur.execute(f"SELECT * FROM {tbl} WHERE {col} = 51307 LIMIT 3")
                rows = cur.fetchall()
                if rows:
                    print(f"  Found in {tbl}.{col}:")
                    for r in rows:
                        for cn, val in zip(cols, r):
                            v = str(val)
                            if len(v) > 80: v = v[:80] + '...'
                            print(f"    {cn:30s} = {v}")
                        print("    ---")
            except Exception as e:
                pass
con.close()
