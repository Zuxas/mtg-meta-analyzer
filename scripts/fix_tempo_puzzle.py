"""One-shot fix: update tempo puzzle (id=3) in place with corrected scene
+ solution after Phase 1 first-smoke caught a mana/timing bug.

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

# Re-import the fixed scene + solution from the seeder
import scripts.seed_puzzles as seeder


def main() -> None:
    # Locate the tempo puzzle by category (only one in seed)
    existing = [
        p for p in db_puzzles.get_puzzles(category="tempo")
        if p["author"] == "seeder"
    ]
    if not existing:
        print("[skip] no seeded tempo puzzle found")
        return
    if len(existing) > 1:
        print(f"[warn] {len(existing)} seeded tempo puzzles found; "
              "updating all")

    # Pull the corrected content from the (now-updated) seeder
    new_scene = seeder._tempo_scene()
    new_spec = next(
        s for s in seeder._SEED_PUZZLES if s["category"] == "tempo"
    )

    with get_connection() as conn:
        for p in existing:
            conn.execute(
                "UPDATE puzzles SET "
                "  question = ?, solution_text = ?, notes = ?, "
                "  scene_json = ?, turn_num = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    new_spec["question"],
                    new_spec["solution_text"],
                    new_spec["notes"],
                    json.dumps(new_scene),
                    new_scene["turn_num"],
                    utc_now(),
                    p["id"],
                ),
            )
            print(f"[ok] updated puzzle id={p['id']} "
                  f"({p['category']}): {new_spec['question']}")
    print(f"\nDone. Updated {len(existing)} puzzle(s).")


if __name__ == "__main__":
    main()
