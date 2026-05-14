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
    grp_ids, or None if no deck scores >= 0.70.

    Compares by card NAME rather than arena_id directly so alt-art printings
    (basic lands especially have many grpids per name) all count toward the
    same card. Score = |deck_names cap observed_names| / |deck_names|.
    """
    if not observed_grp_ids:
        return None

    observed_set = set(observed_grp_ids)

    # Build grpid -> name lookup. Production schema doesn't carry arena_id
    # on card_data; the canonical mapping lives in untapped_card_db.grpid.
    # Tests can still seed card_data.arena_id directly -- we read that first
    # and fall back to untapped_card_db when the column is absent or empty.
    grpid_to_name: dict[int, str] = {}
    with get_connection() as conn:
        try:
            rows = conn.execute(
                "SELECT name, arena_id FROM card_data WHERE arena_id IS NOT NULL"
            ).fetchall()
            for r in rows:
                grpid_to_name[r["arena_id"]] = r["name"]
        except Exception:
            pass
        if not grpid_to_name:
            try:
                rows = conn.execute(
                    "SELECT name, grpid FROM untapped_card_db WHERE grpid IS NOT NULL"
                ).fetchall()
                for r in rows:
                    grpid_to_name[r["grpid"]] = r["name"]
            except Exception:
                pass
    if not grpid_to_name:
        return None

    observed_names = {grpid_to_name[g] for g in observed_set if g in grpid_to_name}
    if not observed_names:
        return None

    candidates = []
    for deck in get_decks(format_name=format_name):
        mb = deck.get("mainboard", {}) or {}
        if not mb:
            continue
        deck_names = set(mb.keys())
        overlap = len(deck_names & observed_names)
        score = overlap / len(deck_names)
        if score >= _OVERLAP_THRESHOLD:
            candidates.append((score, deck.get("created_at", ""), deck["id"]))

    if not candidates:
        return None

    # Highest score, then most recent created_at (ISO string sorts correctly)
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]
