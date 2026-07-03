"""Import sim-mined lethal puzzle candidates into puzzle_inbox (T2 bridge).

The mtg-sim miner (`scripts/mine_lethal_puzzles.py`) is a standalone repo and
writes a JSONL of candidates; this analyzer-side script ingests them into
`puzzle_inbox` via `db.puzzles.save_inbox_candidates` (dedup-safe). The full
serialized Scene + solution line + honest caveats ride in the `evidence` JSON
so a later promote path can rebuild the puzzle without a cached replay.

Usage:
    python -m scripts.import_lethal_puzzles ../mtg-sim/data/lethal_candidates.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys

from db import puzzles as db_puzzles


def _to_inbox_row(cand: dict) -> dict:
    evidence = json.dumps({
        "source": "goldfish-miner",
        "solution_line": cand.get("solution_line", []),
        "greedy_misses": cand.get("greedy_misses", False),
        "caveats": cand.get("caveats", []),
        "scene": cand.get("scene"),
    })
    return {
        "arena_match_id": cand["arena_match_id"],
        "game_num": cand.get("game_num"),
        "turn_num": cand["turn_num"],
        "category": cand.get("category", "find_lethal"),
        "heuristic_score": float(cand.get("heuristic_score", 1.0)),
        "evidence": evidence,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import mined lethal candidates.")
    ap.add_argument("jsonl", help="path to miner JSONL output")
    ap.add_argument("--limit", type=int, default=None)
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

    inserted = db_puzzles.save_inbox_candidates(rows)
    total = len(db_puzzles.get_inbox(category="find_lethal", top_n=10000))
    print(f"Read {len(rows)} candidate(s); inserted {inserted} new "
          f"(dedup skipped {len(rows) - inserted}).")
    print(f"puzzle_inbox now holds {total} undismissed 'find_lethal' rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
