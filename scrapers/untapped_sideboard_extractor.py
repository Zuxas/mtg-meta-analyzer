"""
untapped_sideboard_extractor.py
================================

Extracts sideboard transition plans from multi-game replays in untapped_replays.
For each Bo3 replay, computes the diff between game N's deck and game N+1's deck:
  cards_in  = additions to mainDeck (i.e. cards brought in from sideboard)
  cards_out = removals from mainDeck (i.e. cards sided out)

Stores per-transition rows in `untapped_sideboard_plans` table, then provides
archetype-level aggregations.

Requires:
    untapped_replays   (run untapped_replay_fetcher.py first)
    untapped_card_db   (run untapped_card_loader.py first)

Usage:
    python scrapers\\untapped_sideboard_extractor.py                # extract + summary
    python scrapers\\untapped_sideboard_extractor.py --rebuild      # drop+rebuild plans table
    python scrapers\\untapped_sideboard_extractor.py --archetype Azorius
    python scrapers\\untapped_sideboard_extractor.py --player Piccirko
    python scrapers\\untapped_sideboard_extractor.py --top-cards 30 --archetype Azorius
"""

import sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import json
import gzip
import argparse
import sqlite3
from pathlib import Path
from collections import Counter, defaultdict


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "mtg_meta.db")


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS untapped_sideboard_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        replay_short_id TEXT NOT NULL,
        from_game INTEGER NOT NULL,
        to_game INTEGER NOT NULL,
        cards_in_json TEXT NOT NULL,
        cards_out_json TEXT NOT NULL,
        n_cards_swapped INTEGER NOT NULL,
        UNIQUE (replay_short_id, from_game, to_game),
        FOREIGN KEY (replay_short_id) REFERENCES untapped_replays(short_id)
            ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sb_plans_replay ON untapped_sideboard_plans(replay_short_id)",
    "DROP VIEW IF EXISTS v_untapped_sideboard_plans_with_meta",
    """
    CREATE VIEW v_untapped_sideboard_plans_with_meta AS
    SELECT
        p.*,
        e.player_name,
        e.archetype_primary,
        e.colors_str,
        r.deck_name
    FROM untapped_sideboard_plans p
    LEFT JOIN untapped_entries e ON p.replay_short_id = e.short_id
    LEFT JOIN untapped_replays r ON p.replay_short_id = r.short_id
    """,
]


def diff_decks(deck_a, deck_b):
    """Return (cards_in, cards_out) Counters for the swap from a to b.

    Both decks are lists of grpid integers (with repeats representing copies).
    cards_in  = grpid -> count where deck_b has more than deck_a
    cards_out = grpid -> count where deck_a has more than deck_b
    """
    a = Counter(deck_a)
    b = Counter(deck_b)
    cards_in = b - a   # Counter subtraction zeros negatives
    cards_out = a - b
    return cards_in, cards_out


def load_card_names(con):
    cur = con.cursor()
    cur.execute("SELECT grpid, name FROM untapped_card_db")
    return dict(cur.fetchall())


def render_card_list(counter, name_map):
    """Render a Counter of grpids as [{name, grpid, count}] sorted by count desc."""
    rows = []
    for grpid, cnt in counter.most_common():
        rows.append({
            "grpid": grpid,
            "name": name_map.get(grpid, f"grpid:{grpid}"),
            "count": cnt,
        })
    return rows


def extract_plans(con, name_map, rebuild=False):
    cur = con.cursor()
    if rebuild:
        cur.execute("DELETE FROM untapped_sideboard_plans")
        con.commit()

    cur.execute("""
        SELECT short_id, file_path, n_games
        FROM untapped_replays
        WHERE status='ok' AND n_games > 1
    """)
    targets = cur.fetchall()
    print(f"[+] Multi-game replays to process: {len(targets)}")

    plans_added = 0
    plans_skipped_existing = 0
    for short_id, fpath, n_games in targets:
        try:
            with gzip.open(fpath, "rb") as f:
                data = json.loads(f.read())
        except Exception as e:
            print(f"  ! Failed to read {short_id}: {e}")
            continue

        decks = sorted(data.get("decks") or [], key=lambda d: d.get("game", 0))
        for i in range(len(decks) - 1):
            g_from = decks[i].get("game", i + 1)
            g_to = decks[i + 1].get("game", i + 2)
            main_a = decks[i].get("deck", {}).get("mainDeck") or []
            main_b = decks[i + 1].get("deck", {}).get("mainDeck") or []
            cards_in, cards_out = diff_decks(main_a, main_b)
            n_swapped = sum(cards_in.values())  # = sum(cards_out.values()) for valid SB

            try:
                cur.execute("""
                    INSERT INTO untapped_sideboard_plans
                        (replay_short_id, from_game, to_game,
                         cards_in_json, cards_out_json, n_cards_swapped)
                    VALUES (?,?,?,?,?,?)
                """, (
                    short_id, g_from, g_to,
                    json.dumps(render_card_list(cards_in, name_map)),
                    json.dumps(render_card_list(cards_out, name_map)),
                    n_swapped,
                ))
                plans_added += 1
            except sqlite3.IntegrityError:
                plans_skipped_existing += 1

    con.commit()
    print(f"[+] Inserted {plans_added} new plans (skipped {plans_skipped_existing} that already existed)")


def aggregate_by_archetype(con, archetype_filter=None, player_filter=None, top_n=20):
    cur = con.cursor()
    where = []
    params = []
    if archetype_filter:
        where.append("LOWER(archetype_primary) LIKE ?")
        params.append(f"%{archetype_filter.lower()}%")
    if player_filter:
        where.append("LOWER(player_name) = ?")
        params.append(player_filter.lower())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"""
        SELECT archetype_primary, player_name, deck_name,
               from_game, to_game, n_cards_swapped, cards_in_json, cards_out_json
        FROM v_untapped_sideboard_plans_with_meta
        {where_sql}
        ORDER BY archetype_primary, player_name, from_game
    """, params)
    rows = cur.fetchall()

    if not rows:
        print("\n[!] No sideboard plans match the filter.")
        return

    # Group by archetype
    by_arch = defaultdict(list)
    for r in rows:
        by_arch[r[0]].append(r)

    for arch, plans in sorted(by_arch.items(), key=lambda x: -len(x[1])):
        print()
        print("=" * 80)
        print(f"  {arch}  ({len(plans)} sideboard transitions across {len(set(p[1] for p in plans))} pilots)")
        print("=" * 80)

        # Aggregate IN/OUT
        in_counter = Counter()
        out_counter = Counter()
        for r in plans:
            for c in json.loads(r[6]):
                in_counter[c["name"]] += c["count"]
            for c in json.loads(r[7]):
                out_counter[c["name"]] += c["count"]

        print(f"\n  Most-sided-IN cards (totals across all {arch} plans):")
        for name, total in in_counter.most_common(top_n):
            print(f"    {total:3d}x  {name}")

        print(f"\n  Most-sided-OUT cards:")
        for name, total in out_counter.most_common(top_n):
            print(f"    {total:3d}x  {name}")

        # Per-plan breakdown if not too many
        if len(plans) <= 12:
            print("\n  Individual plans:")
            for r in plans:
                arch_, player, dname, fg, tg, ns, cin, cout = r
                cin_l = json.loads(cin)
                cout_l = json.loads(cout)
                print(f"\n    {player} ({dname!r}) game {fg}->{tg}, swapped {ns} cards:")
                in_txt = ", ".join(f"{c['count']}x {c['name']}" for c in cin_l)
                out_txt = ", ".join(f"{c['count']}x {c['name']}" for c in cout_l)
                print(f"      IN:  {in_txt}")
                print(f"      OUT: {out_txt}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--rebuild", action="store_true",
                    help="Drop existing plans and re-extract from all replays")
    ap.add_argument("--archetype", default=None,
                    help="Filter aggregation to archetype name substring")
    ap.add_argument("--player", default=None,
                    help="Filter aggregation to exact player name")
    ap.add_argument("--top-cards", type=int, default=20,
                    help="Show top N IN/OUT cards per archetype (default: 20)")
    ap.add_argument("--no-extract", action="store_true",
                    help="Skip extraction, only show aggregations")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()
    for ddl in SCHEMA:
        cur.execute(ddl)
    con.commit()

    # Verify card_db
    cur.execute("SELECT COUNT(*) FROM untapped_card_db")
    n_cards = cur.fetchone()[0]
    if n_cards == 0:
        print("[!] untapped_card_db is empty. Run scrapers\\untapped_card_loader.py first.")
        return 1
    print(f"[+] Card db: {n_cards} cards loaded")

    if not args.no_extract:
        name_map = load_card_names(con)
        extract_plans(con, name_map, rebuild=args.rebuild)

    cur.execute("SELECT COUNT(*) FROM untapped_sideboard_plans")
    n_plans = cur.fetchone()[0]
    print(f"[+] Plans in DB: {n_plans}")

    aggregate_by_archetype(con, args.archetype, args.player, args.top_cards)

    con.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
