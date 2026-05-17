"""CLI: run the scanner over data/match_replays/*.json and save
candidates to puzzle_inbox.

Usage:
    python scripts/scan_for_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.puzzles import scanner
from db import puzzles as db_puzzles


def main() -> None:
    print("[scan] walking data/match_replays/ ...")
    candidates = scanner.scan_all()
    if not candidates:
        print("[scan] no candidates found")
        return
    by_cat: dict[str, int] = {}
    for c in candidates:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    print(f"[scan] {len(candidates)} candidates found:")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<14} {n}")

    inserted = db_puzzles.save_inbox_candidates(
        [c.to_dict() for c in candidates]
    )
    print(f"[scan] inserted {inserted} new rows into puzzle_inbox "
          f"(rest were dedup'd)")


if __name__ == "__main__":
    main()
