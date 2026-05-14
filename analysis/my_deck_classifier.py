"""Classify which saved_deck the user piloted in a given match.

Mirrors the overlap-score logic in scrapers/mtga_log_parser.classify_opponent_deck
but flipped onto the user's saved_decks table. Used by Untapped sync to attach
my_deck_id to each match_log row.

Score = |grp_ids_observed ∩ saved_deck.mainboard_card_ids| / |saved_deck.mainboard_card_ids|

If the top score is < 0.70, return None (orphan; Resolve... UI will catch it).
Ties broken by most-recent created_at.
"""
from __future__ import annotations

from typing import Optional

from db.database import get_connection
from db.saved_decks import get_decks

_OVERLAP_THRESHOLD = 0.70


def classify_my_deck(observed_grp_ids: list[int],
                     format_name: str) -> Optional[int]:
    """Return the saved_decks.id whose mainboard best explains the observed
    grp_ids, or None if no deck scores >= 0.70."""
    if not observed_grp_ids:
        return None

    observed_set = set(observed_grp_ids)

    # Build name -> arena_id lookup from card_data so we can compare
    # mainboard (keyed by card name) against grp_ids (= arena_id).
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name, arena_id FROM card_data WHERE arena_id IS NOT NULL"
        ).fetchall()
    name_to_arena = {r["name"]: r["arena_id"] for r in rows}

    candidates = []
    for deck in get_decks(format_name=format_name):
        mb = deck.get("mainboard", {}) or {}
        if not mb:
            continue
        deck_arena_ids = {name_to_arena[n] for n in mb if n in name_to_arena}
        if not deck_arena_ids:
            continue
        overlap = len(deck_arena_ids & observed_set)
        score = overlap / len(deck_arena_ids)
        if score >= _OVERLAP_THRESHOLD:
            candidates.append((score, deck.get("created_at", ""), deck["id"]))

    if not candidates:
        return None

    # Highest score, then most recent created_at (ISO string sorts correctly)
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]
