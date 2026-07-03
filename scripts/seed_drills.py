"""Seed outs-math drills into the puzzles table (puzzle-trainer v0, T1).

Generates hypergeometric "outs" drills grounded in REAL decklists sampled
from mtg_meta.db (house rule 8: never fabricate — every drill stores its
source-decklist attribution in `notes`). Idempotent per run only in the
sense that it always appends; pass --replace to clear existing drill_outs
rows first.

Usage:
    python -m scripts.seed_drills --count 30
    python -m scripts.seed_drills --count 40 --replace --seed 7
"""
from __future__ import annotations

import argparse
import sys

from analysis.puzzles.drill_generator import CATEGORY, generate_drills
from db import puzzles as db_puzzles
from db.database import get_connection


def _clear_existing() -> int:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM puzzles WHERE category = ?", (CATEGORY,))
        return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed outs-math drills.")
    ap.add_argument("--count", type=int, default=30, help="drills to insert")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed")
    ap.add_argument("--replace", action="store_true",
                    help="delete existing drill_outs puzzles first")
    args = ap.parse_args(argv)

    if args.replace:
        removed = _clear_existing()
        print(f"Cleared {removed} existing '{CATEGORY}' puzzles.")

    with get_connection() as conn:
        drills = generate_drills(conn, n=args.count, seed=args.seed)

    inserted = 0
    tiers: dict[int, int] = {}
    for d in drills:
        db_puzzles.save_puzzle(
            deck_id=None,            # attribution lives in notes; decks.id != saved_decks.id
            arena_match_id=None,
            game_num=None,
            turn_num=d.turn_num,
            category=d.category,
            difficulty=d.difficulty,
            question=d.question,
            solution_text=d.solution_text,
            solution_keywords=d.solution_keywords,
            grading_mode=d.grading_mode,
            author="drill_generator",
            notes=d.notes,
            scene=d.scene,
        )
        inserted += 1
        tiers[d.difficulty] = tiers.get(d.difficulty, 0) + 1

    print(f"Inserted {inserted} '{CATEGORY}' drills.")
    print("Difficulty spread: " + ", ".join(
        f"{k}-star x{tiers[k]}" for k in sorted(tiers)))
    total = len(db_puzzles.get_puzzles(category=CATEGORY))
    print(f"Total '{CATEGORY}' puzzles now in DB: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
