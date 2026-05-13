"""
analysis/mulligan_study.py -- Monte Carlo mulligan simulation.

Re-uses the deterministic primer-rule evaluator from
gui.widgets.mulligan_evaluator.evaluate_hand. For each iteration:
  - Shuffle the mainboard, draw 7
  - Evaluate on the play AND on the draw (separate trials)
  - If verdict is MULL, draw 6 cards (London mull is free), re-evaluate
  - Step down through 5, then 4; below 4 we always keep

Aggregates results by matchup x play/draw into keep / mull-to-6 /
mull-to-5 / mull-to-4 rates.

CLI:
    python -m analysis.mulligan_study --deck-id 17 --hands 2000

Output is plain text so it can pipe into a printout or be embedded in
a GUI panel.
"""

from __future__ import annotations
import argparse
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Re-use the primer-rule evaluator
from gui.widgets.mulligan_evaluator import evaluate_hand


DEFAULT_MATCHUPS = [
    "",                       # Generic / no matchup adjustment
    "Selesnya Landfall",
    "Spellementals",
    "Azorius Control",
    "Golgari Midrange",
    "Izzet Prowess",          # mirror
]


def _build_deck_list(mainboard: dict) -> list:
    flat = []
    for name, count in mainboard.items():
        flat.extend([name] * count)
    return flat


def _classify_deck(mainboard: dict) -> dict:
    """Return the deck-category dict that evaluate_hand expects."""
    from analysis.chapin import _classify_cards
    from scrapers.scryfall import get_cards_data
    card_data = get_cards_data(list(mainboard.keys()))
    return _classify_cards(mainboard, card_data)


def _simulate_one(
    deck: list,
    deck_cats: dict,
    on_play: bool,
    matchup: str,
    rng: random.Random,
) -> str:
    """
    Returns "keep_7", "keep_6", "keep_5", or "keep_4" depending on which
    hand size the player kept at (with London mull they always draw 7
    cards first, then put N to the bottom).
    """
    for hand_size in (7, 6, 5):
        hand = rng.sample(deck, 7)
        verdict = evaluate_hand(hand, deck_cats, on_play, matchup)["verdict"]
        if verdict != "MULL":
            return f"keep_{hand_size}"
    return "keep_4"   # auto-keep at 4


def run_study(
    deck_id: int,
    n_hands: int = 1000,
    matchups: Optional[list] = None,
    seed: int = 42,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Simulate `n_hands` openings per (matchup, play/draw) combination and
    return aggregated keep-rate stats.
    """
    db_path = db_path or (Path(__file__).resolve().parent.parent
                          / "data" / "mtg_meta.db")
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT name, archetype, mainboard FROM saved_decks WHERE id=?",
            (deck_id,)
        ).fetchone()
    if not row:
        return {"error": f"deck_id {deck_id} not found"}
    name, archetype, mb_json = row
    mainboard = json.loads(mb_json)

    deck_flat = _build_deck_list(mainboard)
    if len(deck_flat) < 60:
        return {"error": f"mainboard is only {len(deck_flat)} cards"}

    deck_cats = _classify_deck(mainboard)
    matchups = matchups or DEFAULT_MATCHUPS
    rng = random.Random(seed)

    results = {}
    overall = Counter()
    for m in matchups:
        results[m or "(generic)"] = {}
        for on_play in (True, False):
            key = "play" if on_play else "draw"
            buckets = Counter()
            for _ in range(n_hands):
                outcome = _simulate_one(deck_flat, deck_cats,
                                         on_play, m, rng)
                buckets[outcome] += 1
                overall[outcome] += 1
            total = sum(buckets.values())
            results[m or "(generic)"][key] = {
                "n":           total,
                "keep_7":      buckets["keep_7"] / total,
                "keep_6":      buckets["keep_6"] / total,
                "keep_5":      buckets["keep_5"] / total,
                "keep_4":      buckets["keep_4"] / total,
            }

    overall_total = sum(overall.values())
    overall_pct = {k: overall[k] / overall_total for k in overall}

    return {
        "deck_name":    name,
        "deck_archetype": archetype,
        "n_per_cell":   n_hands,
        "matchups":     matchups,
        "by_matchup":   results,
        "overall":      overall_pct,
        "overall_n":    overall_total,
    }


def format_report(study: dict) -> str:
    """ASCII table report suitable for terminal output or print."""
    if "error" in study:
        return f"ERROR: {study['error']}"

    lines = []
    lines.append(f"Mulligan study: {study['deck_name']}")
    lines.append(f"  archetype: {study['deck_archetype']}")
    lines.append(f"  hands per cell: {study['n_per_cell']}  "
                 f"(total simulations: {study['overall_n']})")
    lines.append("")

    o = study["overall"]
    lines.append("--- OVERALL ---")
    lines.append(
        f"  keep 7: {o.get('keep_7', 0)*100:5.1f}%   "
        f"keep 6: {o.get('keep_6', 0)*100:5.1f}%   "
        f"keep 5: {o.get('keep_5', 0)*100:5.1f}%   "
        f"keep 4: {o.get('keep_4', 0)*100:5.1f}%"
    )
    lines.append("")
    lines.append("--- BY MATCHUP x PLAY/DRAW ---")
    lines.append(
        f"  {'matchup':<22} {'side':<5} "
        f"{'keep7':>6} {'keep6':>6} {'keep5':>6} {'keep4':>6}"
    )
    for m, sides in study["by_matchup"].items():
        for side, stats in sides.items():
            lines.append(
                f"  {m[:22]:<22} {side:<5} "
                f"{stats['keep_7']*100:5.1f}% "
                f"{stats['keep_6']*100:5.1f}% "
                f"{stats['keep_5']*100:5.1f}% "
                f"{stats['keep_4']*100:5.1f}%"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--deck-id", type=int, required=True)
    p.add_argument("--hands", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    s = run_study(args.deck_id, n_hands=args.hands, seed=args.seed)
    print(format_report(s))


if __name__ == "__main__":
    main()
