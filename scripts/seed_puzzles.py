"""CLI seeder: insert 3 hand-authored puzzles (one per category) for Phase 1
manual smoke. Re-runnable; deduplicates on (question, category).

All card names + P/T are verified against db.card_data on import — anything
that doesn't lookup raises AssertionError before the scene is built, so the
puzzles can never ship with invented or wrong card data.

Usage:
    python scripts/seed_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import puzzles as db_puzzles
from db.database import get_connection


# ── Card-data verified lookup ─────────────────────────────────────

def _card(name: str, *, tapped: bool = False) -> dict:
    """Look up a card by exact name in card_data and return a CardInZone-
    shaped dict with verified power/toughness. Raises if the card name
    isn't in the project's card_data table."""
    with get_connection() as c:
        row = c.execute(
            "SELECT name, power, toughness, type_line FROM card_data "
            "WHERE name = ?",
            (name,),
        ).fetchone()
    assert row is not None, (
        f"Card not in card_data: {name!r}. "
        "Don't hand-type card names — pull from the project's card_data table."
    )
    out: dict = {"name": row["name"]}
    if row["power"] is not None and row["power"] != "":
        try:
            out["power"] = int(row["power"])
            out["toughness"] = int(row["toughness"])
        except (TypeError, ValueError):
            pass  # variable P/T (*, X, etc.) — skip badge
    if tapped:
        out["tapped"] = True
    return out


def _basic_land(name: str, *, tapped: bool = False) -> dict:
    """Basic lands don't need card_data verification (always present)."""
    return {"name": name, **({"tapped": True} if tapped else {})}


def _face_down(count: int) -> list[dict]:
    return [{"name": "?", "is_face_down": True} for _ in range(count)]


# ── Scene builders ────────────────────────────────────────────────

def _stabilize_scene() -> dict:
    """Tokyo Prowess mirror at low life, T5 on the draw.

    Opp pressured down to 4 with Slickshot Show-Off + Otter tokens (from
    Stormchaser's Talent). Question: do you stabilize this turn or die
    on opp's T6? All cards verified in card_data.
    """
    return {
        "arena_match_id": "seeded-1", "game_num": 1, "turn_num": 5,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 4,
            "hand": [
                _card("Slagstorm"),
                _card("Boomerang Basics"),
                _card("Burst Lightning"),
                _card("Get Out"),
                _card("Opt"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Mountain"),
                _basic_land("Mountain"),
                _basic_land("Mountain"),
            ],
            "battlefield_creatures": [
                _card("Eddymurk Crab"),  # 5/5 from card_data
            ],
            "mana_available": {"U": 1, "R": 3},
        },
        "opp": {
            "name": "Opp", "archetype": "Izzet Prowess (mirror)",
            "life": 14,
            "hand": _face_down(3),
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Mountain"),
                _basic_land("Mountain"),
                _basic_land("Mountain", tapped=True),
            ],
            "battlefield_creatures": [
                _card("Slickshot Show-Off"),  # 1/2 + flying haste from card_data
            ],
        },
        "notes": (
            "Opp attacked you down to 4 with Slickshot last turn "
            "(noncreature pumps put it at 5/2). Slagstorm is in hand."
        ),
    }


def _find_lethal_scene() -> dict:
    """Late-game lethal with Crab on board, opp at 8 with one blocker.

    All cards + costs + P/T verified from card_data.
    """
    return {
        "arena_match_id": "seeded-2", "game_num": 1, "turn_num": 7,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 12,
            "hand": [
                _card("Slickshot Show-Off"),
                _card("Boomerang Basics"),
                _card("Burst Lightning"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Mountain"),
                _basic_land("Mountain"),
            ],
            "battlefield_creatures": [
                _card("Eddymurk Crab"),  # 5/5
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "Opp", "archetype": "Azorius Control", "life": 8,
            "hand": _face_down(4),
            "battlefield_lands": [
                _basic_land("Plains"),
                _basic_land("Plains"),
                _basic_land("Island"),
            ],
            "battlefield_creatures": [
                _card("Floodpits Drowner"),  # 2/1 — only blocker
            ],
        },
        "notes": "UURR available (4 mana). Crab 5/5 already on board.",
    }


def _tempo_scene() -> dict:
    """T4 on the play. Cast Talent + hold counter + hold burn.

    Stormchaser's Talent verified at {U} (not {U}{R} as previously wrong).
    """
    return {
        "arena_match_id": "seeded-3", "game_num": 1, "turn_num": 4,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Tokyo Prowess", "life": 20,
            "hand": [
                _card("Stormchaser's Talent"),
                _card("Disdainful Stroke"),
                _card("Eddymurk Crab"),
                _card("Burst Lightning"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Mountain"),
            ],
            "mana_available": {"U": 3, "R": 1},
        },
        "opp": {
            "name": "Opp", "archetype": "Azorius Control", "life": 20,
            "hand": _face_down(5),
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Plains"),
                _basic_land("Plains"),
                _basic_land("Plains", tapped=True),
            ],
        },
        "notes": "T4 on the play. UUUR open (4 mana). Opp tapped a land last turn — likely 3-drop next.",
    }


# ── Puzzle catalog (built AFTER scene helpers above) ────────────

_SEED_PUZZLES = [
    {
        "category": "stabilize",
        "difficulty": 3,
        "question": "Survive at 4 vs Tokyo mirror",
        "solution_text": (
            "Cast Slagstorm targeting 'each creature' mode for {1}{R}{R} "
            "(3 mana). Kills opp's Slickshot Show-Off (toughness 2 → -1) "
            "and any Otter tokens from Stormchaser's Talent (1/1 → 0). "
            "Your Crab takes 3 dmg too (5/5 → 5/2) but survives.\n\n"
            "Mana math: URRR available (4). Slagstorm spends 1+R+R = 3, "
            "leaves UR open for Boomerang or Burst on opp's turn if a "
            "fresh threat lands.\n\n"
            "Crab now sits as a 5/2 blocker. Opp top-decks a single "
            "creature → Crab eats it. You stay at 4, then untap and "
            "either deploy your own Slickshot or counter on T6.\n\n"
            "Why not 'each player' Slagstorm? You're at 4 life. 3 dmg "
            "to you kills you instantly."
        ),
        "notes": (
            "Slagstorm is modal — picking the wrong mode kills you here. "
            "Crab survives a 'each creature' choice because 5 > 3."
        ),
        "scene": _stabilize_scene(),
    },
    {
        "category": "find_lethal",
        "difficulty": 4,
        "question": "Find lethal — opp at 8",
        "solution_text": (
            "1. Cast Slickshot Show-Off for {1}{R} (2 mana). Comes in "
            "1/2 with flying + haste. No prowess trigger from its own "
            "cast (Slickshot only triggers on noncreature spells).\n"
            "2. Cast Boomerang Basics for {U} bouncing Floodpits Drowner "
            "(noncreature spell → Slickshot +2/+0 → 3/2).\n"
            "3. Cast Burst Lightning for {R} targeting opp face for 2 "
            "damage (noncreature spell → Slickshot +2/+0 → 5/2). "
            "Opp at 8 → 6.\n"
            "4. Attack with Crab (5) + Slickshot (5, flying so unblockable "
            "by Drowner anyway, but the bounce removed it). "
            "10 combat damage → opp 6 → -4 = DEAD.\n\n"
            "Mana spent: 2 + 1 + 1 = 4 = UURR exactly."
        ),
        "notes": (
            "Slickshot's pump is +2/+0 PER noncreature spell — not the "
            "+1/+1 prowess on older cards. Stacks twice this turn."
        ),
        "scene": _find_lethal_scene(),
    },
    {
        "category": "tempo",
        "difficulty": 2,
        "question": "Best play this turn (T4)?",
        "solution_text": (
            "Cast Stormchaser's Talent for {U} (1 mana). It enters and "
            "creates a 1/1 blue-red Otter creature token with prowess.\n\n"
            "Mana math: UUUR available (4). Talent costs 1 → leaves UUR.\n"
            "  - Hold Burst Lightning (R) = 1 R held.\n"
            "  - Hold Disdainful Stroke (1U = 1 generic + 1 colored U) = "
            "1 colored U + 1 generic (from the extra Island).\n"
            "After holding both: 0 mana spent on opp's turn, full "
            "interaction up.\n\n"
            "Why not Crab? Crab is {5}{U}{U} — 7 mana, can't cast at 4.\n"
            "Why not pass with everything up? Talent is {U} only — losing "
            "1 turn of the Otter token + L2/L3 progress for no upside.\n"
            "Why deploy Talent NOT hold it? Talent is sorcery-speed only. "
            "Waiting doesn't help; it just delays the Otter and the "
            "graveyard-return engine at L2."
        ),
        "notes": (
            "Stormchaser's Talent is {U} (single blue), Enchantment — "
            "Class. ETB makes a 1/1 Otter with prowess. L2 = {3}{U}, "
            "L3 = {5}{U}."
        ),
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
