"""Import sim-mined lethal puzzle candidates into puzzle_inbox (T2 bridge).

Takes both miners' JSONL: the goldfish miner (`mine_lethal_puzzles.py`, open
board) and the gauntlet miner (`mine_gauntlet_puzzles.py`, real opponent board
+ revealed hand; carries `source: gauntlet-miner`).

The mtg-sim miner (`scripts/mine_lethal_puzzles.py`) is a standalone repo and
writes a JSONL of candidates; this analyzer-side script ingests them into
`puzzle_inbox` via `db.puzzles.save_inbox_candidates` (dedup-safe). The full
serialized Scene + solution line + honest caveats ride in the `evidence` JSON
so a later promote path can rebuild the puzzle without a cached replay.

Usage (dry run by default; --commit writes):
    python -m scripts.import_lethal_puzzles ../mtg-sim/data/lethal_candidates.jsonl --commit
    python -m scripts.import_lethal_puzzles ../mtg-sim/data/gauntlet_candidates.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys

from db import puzzles as db_puzzles


def _to_inbox_row(cand: dict) -> dict:
    evidence = {
        "source": cand.get("source", "goldfish-miner"),
        "solution_line": cand.get("solution_line", []),
        "greedy_misses": cand.get("greedy_misses", False),
        "caveats": cand.get("caveats", []),
        "scene": cand.get("scene"),
    }
    # gauntlet-miner extras (real opponent board)
    for key in ("our_deck", "opp_deck", "apl_found", "live_blockers", "opp_permanents",
                "robust_vs_best_blocks", "hand_threats", "clean"):
        if key in cand:
            evidence[key] = cand[key]
    evidence = json.dumps(evidence)
    return {
        "arena_match_id": cand["arena_match_id"],
        "game_num": cand.get("game_num"),
        "turn_num": cand["turn_num"],
        "category": cand.get("category", "find_lethal"),
        "heuristic_score": float(cand.get("heuristic_score", 1.0)),
        "evidence": evidence,
    }


def _already_in_inbox(row: dict) -> bool:
    """Same dedup key as save_inbox_candidates, read-only."""
    import sqlite3
    from db.database import get_connection
    with get_connection() as conn:
        try:
            return conn.execute(
                "SELECT 1 FROM puzzle_inbox WHERE arena_match_id = ? AND "
                "game_num IS ? AND turn_num = ? AND category = ?",
                (row["arena_match_id"], row.get("game_num"), row["turn_num"],
                 row["category"]),
            ).fetchone() is not None
        except sqlite3.OperationalError:  # no puzzle tables yet
            return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import mined lethal candidates.")
    ap.add_argument("jsonl", help="path to miner JSONL output")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--commit", action="store_true",
                    help="write to puzzle_inbox (default: dry run, no writes)")
    args = ap.parse_args(argv)

    rows = []
    with open(args.jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(_to_inbox_row(json.loads(line)))
            if args.limit and len(rows) >= args.limit:
                break

    if not args.commit:
        new_rows = [r for r in rows if not _already_in_inbox(r)]
        print(f"DRY RUN: read {len(rows)} candidate(s); {len(new_rows)} would be "
              f"new, {len(rows) - len(new_rows)} already in puzzle_inbox. "
              f"Re-run with --commit to write.")
        return 0

    inserted = db_puzzles.save_inbox_candidates(rows)
    total = len(db_puzzles.get_inbox(category="find_lethal", top_n=10000))
    print(f"Read {len(rows)} candidate(s); inserted {inserted} new "
          f"(dedup skipped {len(rows) - inserted}).")
    print(f"puzzle_inbox now holds {total} undismissed 'find_lethal' rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
