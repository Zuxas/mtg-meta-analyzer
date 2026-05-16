"""One-shot fix: rebuild ALL 3 seeded puzzles in place with corrected
scenes after first-smoke caught fabricated card data + bad mana math.

Renamed from "fix_tempo" because the same problem affected all 3 puzzles.
The seeder script (scripts/seed_puzzles.py) now does card_data verification
at scene-build time so future puzzles can't ship with invented cards.

Run once:
    python scripts/fix_tempo_puzzle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import puzzles as db_puzzles
from db.database import get_connection
from db.helpers import utc_now

import scripts.seed_puzzles as seeder


def main() -> None:
    updated = 0
    for spec in seeder._SEED_PUZZLES:
        cat = spec["category"]
        matches = [
            p for p in db_puzzles.get_puzzles(category=cat)
            if p["author"] == "seeder"
        ]
        if not matches:
            print(f"[skip] no seeded {cat} puzzle in DB")
            continue
        for p in matches:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE puzzles SET "
                    "  question = ?, solution_text = ?, notes = ?, "
                    "  scene_json = ?, turn_num = ?, difficulty = ?, "
                    "  updated_at = ? "
                    "WHERE id = ?",
                    (
                        spec["question"],
                        spec["solution_text"],
                        spec["notes"],
                        json.dumps(spec["scene"]),
                        spec["scene"]["turn_num"],
                        spec["difficulty"],
                        utc_now(),
                        p["id"],
                    ),
                )
            print(f"[ok] updated puzzle id={p['id']} ({cat}): "
                  f"{spec['question']}")
            updated += 1
    print(f"\nDone. Updated {updated} puzzle(s).")


if __name__ == "__main__":
    main()
