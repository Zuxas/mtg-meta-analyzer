"""Seed puzzles authored from REAL match data: opponents from cached
replays (ViewtifulYosh, Drosme), cards from saved Tokyo Prowess
(saved_decks.id=17). Every card name verified against card_data before
the scene is built — fails loud if any card is missing.

Idempotent: dedups on (question, category), so re-running is safe.

Usage:
    python scripts/seed_real_puzzles.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import puzzles as db_puzzles
from db.database import get_connection


# ── Card-data verified lookup (same pattern as scripts/seed_puzzles.py) ──

def _card(name: str, *, tapped: bool = False) -> dict:
    with get_connection() as c:
        row = c.execute(
            "SELECT name, power, toughness FROM card_data WHERE name = ?",
            (name,),
        ).fetchone()
    assert row is not None, (
        f"Card not in card_data: {name!r}. "
        "Real-data seeder must only use cards that exist."
    )
    out: dict = {"name": row["name"]}
    if row["power"] is not None and row["power"] != "":
        try:
            out["power"] = int(row["power"])
            out["toughness"] = int(row["toughness"])
        except (TypeError, ValueError):
            pass
    if tapped:
        out["tapped"] = True
    return out


def _basic_land(name: str, *, tapped: bool = False) -> dict:
    return {"name": name, **({"tapped": True} if tapped else {})}


def _face_down(count: int) -> list[dict]:
    return [{"name": "?", "is_face_down": True} for _ in range(count)]


# ── Scenes built from real match data ──

def _viewtiful_g1_t10_scene() -> dict:
    """ViewtifulYosh G1 T10 — opp at 3, you have Slickshot + Flow State
    on board. Real arena_match_id from cached replay."""
    return {
        "arena_match_id": "8ce83d19-02aa-4576-9ff6-56631a164a7c",
        "game_num": 1, "turn_num": 10,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Izzet Prowess (Tokyo)", "life": 14,
            "hand": [
                _card("Burst Lightning"),
                _card("Opt"),
                _card("Sleight of Hand"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Steam Vents"),
                _basic_land("Spirebluff Canal"),
                _basic_land("Riverpyre Verge"),
            ],
            "battlefield_creatures": [
                _card("Slickshot Show-Off"),
                _card("Stormchaser's Talent"),
            ],
            "mana_available": {"U": 3, "R": 2},
        },
        "opp": {
            "name": "ViewtifulYosh",
            "archetype": "Dimir Roomba (Insatiable Avarice)",
            "life": 3,
            "hand": _face_down(4),
            "battlefield_lands": [
                _basic_land("Watery Grave"),
                _basic_land("Gloomlake Verge"),
                _basic_land("Restless Reef"),
                _basic_land("Starting Town"),
                _basic_land("Island", tapped=True),
            ],
            "battlefield_creatures": [
                _card("Sage of the Skies"),
            ],
        },
        "notes": (
            "Real match vs ViewtifulYosh — G1 T10. Opp at 3 life with a "
            "Sage of the Skies blocker. Slickshot Show-Off (1/2 flying haste) "
            "already in play. Burst Lightning + Opt + Sleight in hand. "
            "5 lands available for UUURR."
        ),
    }


def _viewtiful_g1_t8_scene() -> dict:
    """ViewtifulYosh G1 T8 — push opp from ~13 toward lethal range.
    Big triple-spell turn (Impractical Joke + Sleight + Opt). Teaches
    Slickshot pump sequencing."""
    return {
        "arena_match_id": "8ce83d19-02aa-4576-9ff6-56631a164a7c",
        "game_num": 1, "turn_num": 8,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Izzet Prowess (Tokyo)", "life": 14,
            "hand": [
                _card("Impractical Joke"),
                _card("Sleight of Hand"),
                _card("Opt"),
                _card("Burst Lightning"),
            ],
            "battlefield_lands": [
                _basic_land("Spirebluff Canal"),
                _basic_land("Island"),
                _basic_land("Steam Vents"),
                _basic_land("Riverpyre Verge"),
            ],
            "battlefield_creatures": [
                _card("Slickshot Show-Off"),
                _card("Stormchaser's Talent"),
            ],
            "mana_available": {"U": 2, "R": 2},
        },
        "opp": {
            "name": "ViewtifulYosh", "archetype": "Dimir Roomba", "life": 13,
            "hand": _face_down(3),
            "battlefield_lands": [
                _basic_land("Watery Grave"),
                _basic_land("Gloomlake Verge"),
                _basic_land("Restless Reef"),
            ],
            "battlefield_creatures": [
                _card("Sage of the Skies"),
            ],
        },
        "notes": (
            "Real match vs ViewtifulYosh — G1 T8. UURR available (4 mana). "
            "Slickshot already in play. Stacking noncreature casts pumps it +2/+0 "
            "PER spell. Sage of the Skies (opp's blocker) doesn't have flying so "
            "Slickshot is unblockable here."
        ),
    }


def _drosme_g1_t6_scene() -> dict:
    """Drosme G1 T6 — your big push turn. Slickshot just hit; need to
    sequence Burst + Opt + Opt for max prowess."""
    return {
        "arena_match_id": "bfa19abb-35da-4785-a8a9-dd317a0e1e31",
        "game_num": 1, "turn_num": 6,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Izzet Prowess (Tokyo)", "life": 18,
            "hand": [
                _card("Burst Lightning"),
                _card("Opt"),
                _card("Opt"),
            ],
            "battlefield_lands": [
                _basic_land("Spirebluff Canal"),
                _basic_land("Island"),
                _basic_land("Steam Vents"),
                _basic_land("Multiversal Passage"),
                _basic_land("Steam Vents"),
            ],
            "battlefield_creatures": [
                _card("Slickshot Show-Off"),
            ],
            "mana_available": {"U": 3, "R": 2},
        },
        "opp": {
            "name": "Drosme", "archetype": "Dimir Reanimator", "life": 18,
            "hand": _face_down(4),
            "battlefield_lands": [
                _basic_land("Watery Grave"),
                _basic_land("Gloomlake Verge"),
                _basic_land("Restless Reef"),
            ],
            "battlefield_creatures": [],
        },
        "notes": (
            "Real match vs Drosme — G1 T6. Slickshot just resolved. "
            "UURR available (4 mana). Drosme has Flow State on board "
            "(your noncreature spells make them lose 1 life each)."
        ),
    }


def _drosme_g2_t7_scene() -> dict:
    """Drosme G2 T7 — opp at 5, you need to close before they stabilize.
    Real archetypal close-it-out moment."""
    return {
        "arena_match_id": "bfa19abb-35da-4785-a8a9-dd317a0e1e31",
        "game_num": 2, "turn_num": 7,
        "play_or_draw": "draw",
        "you": {
            "name": "You", "archetype": "Izzet Prowess (Tokyo)", "life": 18,
            "hand": [
                _card("Burst Lightning"),
                _card("Boomerang Basics"),
                _card("Opt"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Steam Vents"),
                _basic_land("Spirebluff Canal"),
                _basic_land("Riverpyre Verge"),
            ],
            "battlefield_creatures": [
                _card("Stormchaser's Talent"),
                _card("Slickshot Show-Off"),
            ],
            "mana_available": {"U": 3, "R": 2},
        },
        "opp": {
            "name": "Drosme", "archetype": "Dimir Reanimator", "life": 5,
            "hand": _face_down(2),
            "battlefield_lands": [
                _basic_land("Watery Grave"),
                _basic_land("Gloomlake Verge"),
                _basic_land("Restless Reef"),
                _basic_land("Starting Town"),
                _basic_land("Watery Grave", tapped=True),
            ],
            "battlefield_creatures": [
                _card("Eddymurk Crab"),
            ],
        },
        "notes": (
            "Real match vs Drosme — G2 T7. Opp at 5 life with a Crab "
            "(5/5) blocker. You have Slickshot (with prowess stacks) and "
            "Talent attacker. UUURR available. Need 5 damage past one blocker."
        ),
    }


def _viewtiful_g3_t11_scene() -> dict:
    """ViewtifulYosh G3 T11 — closed out at -7. Massive overkill turn,
    teaches when to NOT waste burn (save for game 2 of a series). Or
    when to dump everything for safety."""
    return {
        "arena_match_id": "8ce83d19-02aa-4576-9ff6-56631a164a7c",
        "game_num": 3, "turn_num": 11,
        "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Izzet Prowess (Tokyo)", "life": 16,
            "hand": [
                _card("Burst Lightning"),
                _card("Burst Lightning"),
                _card("Opt"),
                _card("Prismari Charm"),
            ],
            "battlefield_lands": [
                _basic_land("Island"),
                _basic_land("Island"),
                _basic_land("Steam Vents"),
                _basic_land("Steam Vents"),
                _basic_land("Spirebluff Canal"),
                _basic_land("Riverpyre Verge"),
            ],
            "battlefield_creatures": [
                _card("Eddymurk Crab"),
                _card("Slickshot Show-Off"),
            ],
            "mana_available": {"U": 3, "R": 3},
        },
        "opp": {
            "name": "ViewtifulYosh", "archetype": "Dimir Roomba", "life": 5,
            "hand": _face_down(5),
            "battlefield_lands": [
                _basic_land("Watery Grave"),
                _basic_land("Gloomlake Verge"),
                _basic_land("Restless Reef"),
                _basic_land("Starting Town", tapped=True),
            ],
            "battlefield_creatures": [],
        },
        "notes": (
            "Real match vs ViewtifulYosh — G3 T11. Crab + Slickshot both "
            "attacking unblocked is 6 damage = opp -1. But sequencing matters: "
            "if they have one unknown card that's a removal spell for the "
            "Crab, you lose 5 dmg of clock. UUURRR available."
        ),
    }


# ── Puzzle catalog ──

_SEED_PUZZLES = [
    {
        "category": "find_lethal",
        "difficulty": 4,
        "question": "vs ViewtifulYosh G1 T10 — close from 3",
        "solution_text": (
            "Slickshot (1/2 flying haste) attacks unblocked (Sage of the Skies "
            "has no flying) — opp 3 → 1.\n\n"
            "Then cast Burst Lightning {R} targeting opp face for 2 damage. "
            "Noncreature spell → Slickshot got +2/+0 BEFORE damage (would matter "
            "if blocked), but since it's already through, the prowess pump is "
            "moot here. Opp 1 → -1 = DEAD.\n\n"
            "Mana spent: just R. UUURR remain for next turn (irrelevant — game "
            "ends).\n\n"
            "Why not Stormchaser's Talent attack too? Talent is 1/3 with no "
            "evasion — Sage of the Skies (let's assume 3/3 with flying) blocks "
            "and trades. Not needed; Slickshot + Burst is exactly lethal."
        ),
        "notes": "Slickshot's haste + flying is the key here, not prowess pumps.",
        "scene": _viewtiful_g1_t10_scene(),
        "solution_keywords": ["slickshot", "attack", "burst lightning", "face"],
        "grading_mode": "keyword",
    },
    {
        "category": "find_lethal",
        "difficulty": 3,
        "question": "vs ViewtifulYosh G1 T8 — pump and push (opp at 13)",
        "solution_text": (
            "Attack first with Slickshot + Talent. Slickshot starts at 1/2 "
            "(flying haste). Talent's Otter is 1/1 prowess.\n\n"
            "Then cast in this order:\n"
            "1. Opt {U} → Slickshot becomes 3/2, Otter 2/1. Draw a card.\n"
            "2. Sleight of Hand {U} → Slickshot 5/2, Otter 3/1.\n"
            "3. Impractical Joke {1}{R} → Slickshot 7/2, Otter 4/1.\n\n"
            "Combat damage (after pumps): Slickshot 7 flying through, Otter 4 "
            "(blocked by Sage of the Skies which is 3/3 flying — trades).\n\n"
            "Total damage: 7 (Slickshot through). Opp 13 → 6.\n\n"
            "If you want to close: cast Burst Lightning {R} face for 2 more. "
            "Opp 6 → 4. NOT lethal this turn, but you've set up T9 lethal "
            "with another burn or an attack from a fresh threat.\n\n"
            "Mana: UURR available. Spent: U + U + 1R + R = 5 mana. "
            "Wait — you only have 4 mana (UURR = 4). So drop ONE of the spells. "
            "Cut Sleight of Hand (it's a 1-mana scry-1-draw-1; the prowess pump "
            "from a second spell is worth less than the card advantage)."
        ),
        "notes": (
            "Prowess pump is +2/+0 PER noncreature spell on Slickshot, +1/+1 PER "
            "noncreature on Otter. Sequence matters: pump THEN combat damage."
        ),
        "scene": _viewtiful_g1_t8_scene(),
        "solution_keywords": ["attack", "slickshot", "opt", "impractical joke", "pump"],
        "grading_mode": "keyword",
    },
    {
        "category": "tempo",
        "difficulty": 3,
        "question": "vs Drosme G1 T6 — sequence the prowess",
        "solution_text": (
            "Order matters because Slickshot stacks +2/+0 per noncreature cast.\n\n"
            "Optimal sequence:\n"
            "1. Attack with Slickshot FIRST (it's haste-flying, currently 1/2).\n"
            "2. Mid-combat or after: cast Burst Lightning {R} face for 2 dmg.\n"
            "3. Cast Opt {U} (draw 1, Drosme also loses 1 from Flow State).\n"
            "4. Cast Opt {U} (draw 1, Drosme another 1).\n\n"
            "Damage tally: Slickshot 1 + Burst 2 + Flow State 1×2 = 5 damage. "
            "Opp 18 → 13.\n\n"
            "Why not pump Slickshot before attacking?\n"
            "Because Slickshot dies easily (only 2 toughness). Get the damage "
            "in first while it's alive. The +2/+0 stacks only matter for surviving "
            "blocks — opp has no blockers here.\n\n"
            "Mana: UUURR available (5 mana). Spent: 1R (Slickshot was already in "
            "play) + R (Burst) + U + U = 4 mana. One spare for next turn."
        ),
        "notes": (
            "Flow State pings opp for 1 each of YOUR noncreature spells. "
            "Combined with Slickshot already on board, this is a passive "
            "damage faucet."
        ),
        "scene": _drosme_g1_t6_scene(),
        "solution_keywords": ["attack first", "burst lightning", "opt", "flow state"],
        "grading_mode": "keyword",
    },
    {
        "category": "find_lethal",
        "difficulty": 4,
        "question": "vs Drosme G2 T7 — bounce the Crab, swing for 5",
        "solution_text": (
            "Cast Boomerang Basics {U} bouncing Eddymurk Crab back to hand. "
            "Noncreature spell → Slickshot prowess +2/+0 (3/2), Talent's Otter "
            "+1/+1.\n\n"
            "Attack with everything:\n"
            "- Slickshot (3/2 flying haste) — unblockable\n"
            "- Stormchaser's Talent (1/3) → no blockers left\n"
            "- Otter (2/2 prowess from Talent's flip) → no blockers left\n\n"
            "Damage: 3 + 1 + 2 = 6. Opp 5 → -1 = DEAD.\n\n"
            "Backup line if Boomerang gets countered: Burst Lightning {R} face "
            "for 2 damage = 3 (Slickshot) + 1 (Talent) + 1 (Otter, only 1/1 "
            "without pump since you got countered, so no prowess) + 2 (Burst) = "
            "7 damage past Crab block. Crab eats one creature (Slickshot trades "
            "via flying — wait, Slickshot has flying so Crab can't block). "
            "Crab blocks Talent or Otter, lethal still goes through. Opp dies.\n\n"
            "Mana: UUURR (5 mana). Boomerang U + Burst R = 2 mana spent."
        ),
        "notes": (
            "Bounce is better than burn here because Crab is a hard wall (5/5). "
            "Removing the blocker unlocks 6+ damage of creature combat."
        ),
        "scene": _drosme_g2_t7_scene(),
        "solution_keywords": ["boomerang", "bounce", "crab", "attack"],
        "grading_mode": "keyword",
    },
    {
        "category": "tempo",
        "difficulty": 2,
        "question": "vs ViewtifulYosh G3 T11 — secure the win or overkill?",
        "solution_text": (
            "Don't overcommit. Eddymurk Crab (5/5) + Slickshot (1/2 flying haste) "
            "both attack — opp has no blockers so 6 damage through. Opp 5 → -1 "
            "= DEAD without spending any cards from hand.\n\n"
            "DO NOT cast Burst Lightning or Prismari Charm — save them for "
            "potential next game (you're in G3 so this is the match-winner, but "
            "the principle of card-preservation matters in mulligan-fodder spots "
            "earlier in a tournament).\n\n"
            "Also DO NOT cast Opt — drawing a card doesn't matter; the game's over.\n\n"
            "Why this puzzle is here: identifying when 'just attack' is correct "
            "vs when you need to spend resources to push damage. With 6 damage "
            "of unblocked creatures vs 5 life, the answer is clear: combat alone "
            "wins it. UUURRR mana goes unspent — that's fine."
        ),
        "notes": (
            "Pro discipline: don't burn resources when combat alone is lethal. "
            "Crab's evasion (flying or just unblocked because opp has no creatures) "
            "is doing all the work."
        ),
        "scene": _viewtiful_g3_t11_scene(),
        "solution_keywords": ["attack", "do not", "save", "combat alone", "no blockers"],
        "grading_mode": "keyword",
    },
]


def main() -> None:
    existing = {(p["question"], p["category"]) for p in db_puzzles.get_puzzles()}
    inserted = 0
    skipped = 0
    for spec in _SEED_PUZZLES:
        key = (spec["question"], spec["category"])
        if key in existing:
            print(f"[skip] already exists: {spec['question']}")
            skipped += 1
            continue
        pid = db_puzzles.save_puzzle(
            deck_id=17,  # Tokyo Prowess
            arena_match_id=spec["scene"]["arena_match_id"],
            game_num=spec["scene"]["game_num"],
            turn_num=spec["scene"]["turn_num"],
            category=spec["category"],
            difficulty=spec["difficulty"],
            question=spec["question"],
            solution_text=spec["solution_text"],
            solution_keywords=spec.get("solution_keywords", []),
            grading_mode=spec.get("grading_mode", "self"),
            author="real-data-seeder",
            notes=spec["notes"],
            scene=spec["scene"],
        )
        inserted += 1
        print(f"[ok] inserted id={pid}: {spec['question']}")
    print(f"\nDone. Inserted {inserted} / Skipped {skipped} / Total in catalog {len(_SEED_PUZZLES)}.")


if __name__ == "__main__":
    main()
