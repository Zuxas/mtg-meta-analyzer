"""One-shot: enrich puzzle notes with context the scene can't currently
render (graveyard state, card abilities, mana-source breakdown). This
addresses the user feedback that puzzles felt under-specified.

Each entry below updates ONE puzzle's notes field by id. Idempotent —
re-running just rewrites the same notes.

Until the Scene dataclass gets a `graveyard` field + PuzzleSceneWidget
renders it, the notes field is the place to document "everything else
the solver needs to know."
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import get_connection
from db.helpers import utc_now


# Map puzzle question (the stable identifier we can match on) → enriched notes
_ENRICHED_NOTES = {
    "Best play this turn (T4)?": (
        "GY STATE: Both graveyards EMPTY (T4, no spells cast yet).\n\n"
        "CARDS IN HAND:\n"
        "  • Stormchaser's Talent — {U}, Enchantment Class. ETB: make a 1/1 "
        "Otter token with prowess. L2 ({3}{U}): return target instant/sorcery "
        "from GY to hand. L3 ({5}{U}): copy next instant/sorcery you cast. "
        "Since GY is EMPTY, L2 has no return target this turn.\n"
        "  • Disdainful Stroke — {1}{U}, Instant. Counter target spell with "
        "mana value 4 or greater.\n"
        "  • Eddymurk Crab — {4}{U}, Creature - Crab 4/5. NO FLASH. Sorcery "
        "speed only. Costs 5 mana — NOT CASTABLE this turn (only 4 mana "
        "available).\n"
        "  • Burst Lightning — {R}, Instant. 2 damage to any target. "
        "Kicker {4}: 4 damage instead.\n\n"
        "MANA AVAILABLE: UUUR (4 mana, 3 Islands + 1 Mountain).\n\n"
        "OPP STATE: Azorius Control, 20 life, 4 lands (3 Plains + 1 Island, "
        "one tapped — suggests they cast a 2-drop last turn but it didn't "
        "stay on board, OR they used the mana for a non-creature like Get Lost "
        "/ removal). Hand: 5 cards face-down.\n\n"
        "Stormchaser's Talent is {U} (single blue), Enchantment — Class. "
        "ETB makes a 1/1 Otter with prowess. L2 = {3}{U}, L3 = {5}{U}."
    ),
    "vs ViewtifulYosh G1 T10 — close from 3": (
        "GY STATE: Yours has ~6-8 cards by T10 (Sleight, Boomerang, Burst x2, "
        "Slickshot Show-Off [exiled], etc. — exact list not tracked). Opp GY "
        "similar volume. Talent L2 return target available (any instant/sorcery "
        "from yours).\n\n"
        "CARDS IN HAND:\n"
        "  • Burst Lightning — {R} Instant. 2 dmg to any target.\n"
        "  • Opt — {U} Instant. Scry 1, draw 1.\n"
        "  • Sleight of Hand — {U} Sorcery. Look at top 2, keep 1.\n\n"
        "MANA AVAILABLE: UUURR (5 mana, 5 lands).\n\n"
        "BOARD: Slickshot Show-Off (1/2 flying haste) + Stormchaser's Talent "
        "(1/3 Class L1, with prowess attached). Opp has Sage of the Skies "
        "(2/2 NO flying in this deck — Dimir Roomba) so Slickshot is "
        "UNBLOCKABLE here.\n\n"
        "OPP STATE: ViewtifulYosh, Dimir Roomba (Insatiable Avarice). 3 life. "
        "4 cards in hand (unknown — could be removal, could be more discard).\n\n"
        "The Slickshot Show-Off + Burst Lightning line is clean lethal."
    ),
    "vs ViewtifulYosh G1 T8 — pump and push (opp at 13)": (
        "GY STATE: Yours ~4-5 cards (Stormchaser's Talent, Boomerang, Burst). "
        "Opp GY ~2-3. L2 Talent return available (Burst Lightning would be "
        "highest-value to return).\n\n"
        "CARDS IN HAND:\n"
        "  • Impractical Joke — {1}{R}, Sorcery. Choose two: deal 1 dmg, scry 1, "
        "loot 1. Effectively a 2-mana cantrip + ping.\n"
        "  • Sleight of Hand — {U}, Sorcery. Top 2 → 1 in hand.\n"
        "  • Opt — {U}, Instant. Scry 1, draw 1.\n"
        "  • Burst Lightning — {R}, Instant. 2 dmg to any target.\n\n"
        "MANA AVAILABLE: UURR (4 mana, 4 lands). Impractical Joke + Sleight + "
        "Opt + Burst = 1R + U + U + R = 5 mana. ONE TOO MANY — must cut one. "
        "Recommend cutting Sleight (Opt gives card+scry for same cost).\n\n"
        "BOARD: Slickshot Show-Off (1/2 flying haste) + Stormchaser's Talent "
        "Otter (1/1 prowess). Opp has Sage of the Skies (no flying).\n\n"
        "Prowess pump is +2/+0 PER noncreature spell on Slickshot, +1/+1 PER "
        "noncreature on the Otter. Sequence matters: pump THEN combat damage."
    ),
    "vs Drosme G1 T6 — sequence the prowess": (
        "GY STATE: Yours has Sleight of Hand (cast T2). Opp GY has Flow State "
        "(in play, not GY). L2 Talent return = Sleight back to hand (low value).\n\n"
        "CARDS IN HAND:\n"
        "  • Burst Lightning — {R}, Instant.\n"
        "  • Opt — {U}, Instant (×2).\n\n"
        "MANA AVAILABLE: UUURR (5 mana, 5 lands per scene). Burst + 2x Opt = "
        "R + U + U = 3 mana. 2 spare.\n\n"
        "BOARD: Slickshot Show-Off just resolved this turn (1/2 flying haste). "
        "Opp has NO creatures, but DOES have Flow State (your noncreature "
        "spells make them lose 1 life each).\n\n"
        "OPP STATE: Drosme, Dimir Reanimator. 18 life. 4 cards in hand "
        "(unknown — assume reactive given the Flow State play pattern).\n\n"
        "Key insight: Slickshot has flying + haste + nothing blocks it. Attack "
        "FIRST while it's alive (2 toughness = fragile). Pump only matters "
        "for surviving blocks."
    ),
    "vs Drosme G2 T7 — bounce the Crab, swing for 5": (
        "GY STATE: Yours has 2x Stormchaser's Talent (cast T3 + T5 per the "
        "real replay — both flipped Otters generated). L2 Talent flip would "
        "return one Talent from GY (recursion loop possible).\n\n"
        "CARDS IN HAND:\n"
        "  • Burst Lightning — {R} Instant.\n"
        "  • Boomerang Basics — {U} Instant. Return target nonland permanent.\n"
        "  • Opt — {U} Instant.\n\n"
        "MANA AVAILABLE: UUURR (5 mana, 5 lands incl. 1 tapped).\n\n"
        "BOARD: Stormchaser's Talent (1/3 Class L1) + Slickshot Show-Off "
        "(1/2 flying haste). Both attacking. Two Otter tokens implied from "
        "the prior Talent flips (1/1 each with prowess).\n\n"
        "OPP STATE: Drosme, 5 life, Eddymurk Crab on board (4/5). Crab is a "
        "hard wall — can block any ground creature and survive. 2 cards in "
        "hand (likely reactive given the board state).\n\n"
        "Bounce > burn here because Crab is a 5-toughness wall. Removing it "
        "unlocks 6+ damage of creature combat."
    ),
    "vs ViewtifulYosh G3 T11 — secure the win or overkill?": (
        "GY STATE: Both GYs deep by T11 (10+ cards each side). Specific "
        "contents not load-bearing for this decision.\n\n"
        "CARDS IN HAND:\n"
        "  • Burst Lightning — {R} Instant (×2).\n"
        "  • Opt — {U} Instant.\n"
        "  • Prismari Charm — {U}{R} Instant. Choose one: bounce, scry/draw, "
        "or 4 dmg to a creature.\n\n"
        "MANA AVAILABLE: UUURRR (6 mana, 6 lands).\n\n"
        "BOARD: Eddymurk Crab (4/5) + Slickshot Show-Off (1/2 flying haste). "
        "Opp has NO creatures on board — both attackers are unblocked.\n\n"
        "OPP STATE: ViewtifulYosh, 5 life, 5 cards in hand (could be anything). "
        "If they have removal in hand: bouncing or burning the Crab loses you "
        "4 dmg of clock, but Slickshot still gets through for 1.\n\n"
        "Pro discipline: don't burn resources when combat alone is lethal. "
        "5 life - (4 + 1) = -1 = DEAD via just attacking. Card preservation "
        "doesn't matter in G3 (this is the match) but the principle "
        "generalizes."
    ),
}


def main() -> None:
    updated = 0
    with get_connection() as conn:
        for question, notes in _ENRICHED_NOTES.items():
            row = conn.execute(
                "SELECT id FROM puzzles WHERE question = ?", (question,),
            ).fetchone()
            if row is None:
                print(f"[skip] no puzzle with question: {question!r}")
                continue
            conn.execute(
                "UPDATE puzzles SET notes = ?, updated_at = ? WHERE id = ?",
                (notes, utc_now(), row["id"]),
            )
            updated += 1
            print(f"[ok] enriched id={row['id']}: {question}")
    print(f"\nDone. Enriched {updated} / {len(_ENRICHED_NOTES)} puzzles.")


if __name__ == "__main__":
    main()
