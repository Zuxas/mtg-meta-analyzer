"""CLI seeder: insert 3 hand-authored puzzles (one per category) for Phase 1
manual smoke. Re-runnable; deduplicates on (question, category).

Usage:
    python scripts/seed_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import puzzles as db_puzzles


# ── Scene builders (defined first so _SEED_PUZZLES below can call them) ──

def _stabilize_scene() -> dict:
    """Tokyo Prowess vs MGL, T7, you at 4, opp at 12, see the v5 mockup."""
    return {
        "arena_match_id": "seeded-1", "game_num": 1, "turn_num": 7,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 4,
            "hand": [
                {"name": "Burst Lightning"},
                {"name": "Slickshot Show-Off"},
                {"name": "Boomerang Basics"},
                {"name": "Slagstorm"},
                {"name": "Get Out"},
            ],
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island"},
                {"name": "Mountain"}, {"name": "Mountain"},
            ],
            "battlefield_creatures": [
                {"name": "Eddymurk Crab", "power": 4, "toughness": 5},
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "Mestre dos Magos", "archetype": "Mono Green Landfall",
            "life": 12,
            "hand": [{"name": "?", "is_face_down": True}] * 5,
            "battlefield_lands": [
                {"name": "Forest"}, {"name": "Forest"}, {"name": "Forest"},
                {"name": "Forest", "tapped": True},
                {"name": "Forest", "tapped": True},
            ],
            "battlefield_creatures": [
                {"name": "Llanowar Elves", "power": 1, "toughness": 1},
                {"name": "Llanowar Elves", "power": 1, "toughness": 1},
                {"name": "Worldwagon", "power": 4, "toughness": 4},
                {"name": "Dryadine", "power": 2, "toughness": 3},
            ],
        },
        "notes": "Opp has Worldwagon + 2 Elves; can attack for 6+ on T8.",
    }


def _find_lethal_scene() -> dict:
    return {
        "arena_match_id": "seeded-2", "game_num": 1, "turn_num": 8,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 6,
            "hand": [
                {"name": "Burst Lightning"},
                {"name": "Slickshot Show-Off"},
                {"name": "Boomerang Basics"},
            ],
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island"},
                {"name": "Mountain"}, {"name": "Mountain"},
            ],
            "battlefield_creatures": [
                {"name": "Eddymurk Crab", "power": 4, "toughness": 5},
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "Opp", "archetype": "?", "life": 8,
            "hand": [{"name": "?", "is_face_down": True}] * 4,
            "battlefield_lands": [
                {"name": "Plains"}, {"name": "Plains"}, {"name": "Island"},
            ],
            "battlefield_creatures": [
                {"name": "Floodpits Drowner", "power": 1, "toughness": 4},
            ],
        },
        "notes": "Slickshot's prowess + Crab's 4 power can close it.",
    }


def _tempo_scene() -> dict:
    return {
        "arena_match_id": "seeded-3", "game_num": 1, "turn_num": 5,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 20,
            "hand": [
                {"name": "Stormchaser's Talent"},
                {"name": "Disdainful Stroke"},
                {"name": "Eddymurk Crab"},
                {"name": "Burst Lightning"},
            ],
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island"}, {"name": "Island"},
                {"name": "Mountain"}, {"name": "Mountain"},
            ],
            "mana_available": {"U": 3, "R": 2},
        },
        "opp": {
            "name": "Opp", "archetype": "?", "life": 20,
            "hand": [{"name": "?", "is_face_down": True}] * 5,
            "battlefield_lands": [
                {"name": "Island"}, {"name": "Island", "tapped": True},
                {"name": "Plains"}, {"name": "Plains"},
            ],
        },
        "notes": "T5 on the play. You have UUURR open (5 mana). Opp has 4 lands, 2 untapped.",
    }


# ── Puzzle catalog (built AFTER scene helpers above) ────────────

_SEED_PUZZLES = [
    {
        "category": "stabilize",
        "difficulty": 3,
        "question": "Survive opp's T8",
        "solution_text": (
            "Cast Slagstorm (3 dmg to each creature) — kills both Llanowar Elves "
            "and Dryadine. Worldwagon survives at 1 toughness. Crab stays "
            "untapped to block Worldwagon next turn (Crab 4/5 vs 4/4 → Crab "
            "lives, Worldwagon dies). You take 0 in combat; stay at 4."
        ),
        "notes": "Aggressive: -2 to your own face from Slagstorm is the cost.",
        "scene": _stabilize_scene(),
    },
    {
        "category": "find_lethal",
        "difficulty": 4,
        "question": "Find lethal — opp at 8, you at 6",
        "solution_text": (
            "Cast Slickshot Show-Off for R (1 spell). Cast Boomerang Basics "
            "bouncing opp's only blocker (2 spells now, Slickshot is 3/1). "
            "Cast Burst Lightning targeting opp (3 spells, Slickshot is 4/1, "
            "2 damage from Burst). Attack with Slickshot for 4 + Crab for 4. "
            "Total: 2 + 4 + 4 = 10 → opp dead."
        ),
        "notes": "Slickshot's own cast doesn't trigger its prowess.",
        "scene": _find_lethal_scene(),
    },
    {
        "category": "tempo",
        "difficulty": 2,
        "question": "Best play this turn?",
        "solution_text": (
            "Cast Stormchaser's Talent (UR) this turn, then PASS with "
            "R + UU held up.\n\n"
            "Mana math: UUURR available (5). Talent costs U+R = 2 -> "
            "leaves UU + R. That's exactly enough to hold Burst Lightning "
            "(R) AND Disdainful Stroke (1U = 1 generic + 1 colored U, paid "
            "from the two remaining Islands).\n\n"
            "Why now: Talent is a Saga, sorcery-speed only -- can't be "
            "held for opp's end step. At 5 lands you can both deploy AND "
            "keep interaction up, so there's no reason to wait. The line "
            "that tries to hold Talent AND keep counter mana doesn't help "
            "since Talent never gets cheaper.\n\n"
            "Threat: Burst Lightning answers a small creature; Disdainful "
            "Stroke counters their next 4+ drop. Talent starts ticking "
            "toward its win con."
        ),
        "notes": "Tempo principle: deploy + leave interaction up when mana "
                 "allows BOTH. Sorcery-speed plays don't get cheaper from "
                 "waiting.",
        "scene": _tempo_scene(),
    },
]


def main() -> None:
    existing = {(p["question"], p["category"]) for p in db_puzzles.get_puzzles()}
    inserted = 0
    for spec in _SEED_PUZZLES:
        key = (spec["question"], spec["category"])
        if key in existing:
            print(f"[skip] already exists: {spec['question']}")
            continue
        pid = db_puzzles.save_puzzle(
            deck_id=None,
            arena_match_id=spec["scene"]["arena_match_id"],
            game_num=spec["scene"]["game_num"],
            turn_num=spec["scene"]["turn_num"],
            category=spec["category"],
            difficulty=spec["difficulty"],
            question=spec["question"],
            solution_text=spec["solution_text"],
            solution_keywords=[],
            grading_mode="self",
            author="seeder",
            notes=spec["notes"],
            scene=spec["scene"],
        )
        inserted += 1
        print(f"[ok] inserted puzzle id={pid} ({spec['category']}): {spec['question']}")
    print(f"\nDone. Inserted {inserted} / Skipped {len(_SEED_PUZZLES) - inserted}.")


if __name__ == "__main__":
    main()
