"""Auto-create a saved_decks entry when an MTGA match shows a deck we
haven't seen before.

Workflow:
  1. mtga_log_parser observes grpIds the user played.
  2. analysis.my_deck_classifier compares against existing saved_decks;
     if overlap >= 0.70, it returns the saved_decks.id and we're done.
  3. If no match, this module:
     - Skips Limited events (Sealed / Draft / Cube) -- those are one-off
       pools, not worth saving.
     - Skips matches with too few observed cards (default <20) to avoid
       creating decks from concede-on-turn-1 garbage.
     - Resolves grpIds to card names, classifies against meta archetypes
       (paper-event data via classify_opponent_deck).
     - Checks if a saved deck already exists for that (archetype, format).
       If yes, returns its id (existing match will link there).
     - If no, creates `<archetype> (auto-imported YYYY-MM-DD)` with
       observed cards as the mainboard, empty sideboard. Returns new id.

Design notes:
  - Observed grpIds aren't a complete 75 -- only cards the user drew
    over the game. So the auto-created mainboard is approximate. Subsequent
    matches with the same archetype will hit the existing deck via name
    lookup, not by re-creating.
  - Sideboard isn't observed from the user's seat -- left empty so the
    Match Log "Resolve..." dialog (or the user manually) can fill it.
  - Re-running the parser does NOT re-create or stomp existing decks.
    Idempotent on (archetype, format).
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Optional

from db.database import get_connection
from db.saved_decks import get_decks, save_deck

_MIN_OBSERVED_CARDS = 20  # below this, treat as garbage; concede-on-T1 etc.


# Event-name classification -- duplicated from
# gui.widgets.deck_match_history because that module imports Qt and we
# need this callable from headless CLI scrapers too.
_RANKED_BO3_EVENTS = {"Traditional_Ladder", "Constructed_BestOf3_Ranked"}
_RANKED_BO1_EVENTS = {"Ladder", "Constructed_BestOf1_Ranked"}
_UNRANKED_PREFIXES = ("Constructed_BestOf3", "Constructed_BestOf1", "DirectGame")
_LIMITED_KEYWORDS = ("Sealed", "Draft", "Cube")


def classify_event(event_name: str) -> str:
    """Return one of: 'ranked-bo3', 'ranked-bo1', 'unranked', 'limited', 'other'."""
    if not event_name:
        return "other"
    name = event_name.strip()
    if name in _RANKED_BO3_EVENTS:
        return "ranked-bo3"
    if name in _RANKED_BO1_EVENTS:
        return "ranked-bo1"
    for kw in _LIMITED_KEYWORDS:
        if kw in name:
            return "limited"
    for pfx in _UNRANKED_PREFIXES:
        if name.startswith(pfx) and "Ranked" not in name:
            return "unranked"
    return "other"


def _resolve_grpids_to_name_counts(observed_grp_ids: list[int]) -> dict[str, int]:
    """grpId list -> {card_name: qty} via untapped_card_db.

    Quantities are summed across duplicate grpIds and across alt-arts
    (multiple grpIds mapping to the same card name).
    """
    if not observed_grp_ids:
        return {}
    with get_connection() as conn:
        placeholders = ",".join("?" * len(set(observed_grp_ids)))
        unique_ids = list(set(observed_grp_ids))
        try:
            rows = conn.execute(
                f"SELECT grpid, name FROM untapped_card_db "
                f"WHERE grpid IN ({placeholders}) AND name IS NOT NULL",
                unique_ids,
            ).fetchall()
        except Exception:
            return {}
    grpid_to_name = {r[0] if isinstance(r, tuple) else r["grpid"]:
                     r[1] if isinstance(r, tuple) else r["name"]
                     for r in rows}
    counts: Counter = Counter()
    for grp in observed_grp_ids:
        name = grpid_to_name.get(grp)
        if name:
            counts[name] += 1
    # Observed grpIds are unique per match (parser dedups). So counts mostly
    # cap at 1 per card. That's fine -- we use the deck as a recognition
    # fingerprint, not a stat-precise 4-of count.
    return dict(counts)


def _classify_archetype(observed_grp_ids: list[int],
                        format_name: str) -> str:
    """Reuse the opponent classifier on the user's own grpIds -- the
    overlap-score logic is the same in both directions."""
    try:
        from scrapers.mtga_log_parser import classify_opponent_deck
        result = classify_opponent_deck(observed_grp_ids, format_name)
        if result and result not in ("Unknown", "Deck"):
            return result
    except Exception:
        pass
    return "Unknown Archetype"


def find_or_create_deck(observed_grp_ids: list[int],
                       format_name: str,
                       event_category: str = "",
                       sideboard_grp_ids: list[int] | None = None) -> Optional[int]:
    """Find or create a saved_decks row that fits these observed grpIds.

    event_category: one of {'ranked-bo3', 'ranked-bo1', 'unranked',
                            'limited', 'other'}.  Limited events are
                    skipped (returns None).
    sideboard_grp_ids: the user's sideboard from
                      connectResp.deckMessage.sideboardCards if available.
                      Used only when creating a new deck OR when filling
                      in an empty SB on an existing auto-imported deck.

    Returns saved_decks.id, or None if we declined to create / link.
    """
    if event_category == "limited":
        return None
    if not observed_grp_ids:
        return None
    if len(set(observed_grp_ids)) < _MIN_OBSERVED_CARDS:
        return None

    archetype = _classify_archetype(observed_grp_ids, format_name)
    if archetype == "Unknown Archetype":
        # Don't pollute saved_decks with unclassifiable rows.
        return None

    sideboard_grp_ids = sideboard_grp_ids or []
    sideboard = _resolve_grpids_to_name_counts(sideboard_grp_ids)

    # Look for an existing saved deck with this archetype + format
    for d in get_decks(format_name=format_name):
        if d.get("archetype", "").strip().lower() == archetype.lower():
            # If the existing deck has an empty sideboard (typical for
            # an auto-imported deck from before SB capture was wired in)
            # AND we now have SB grpIds, fill it in opportunistically.
            existing_sb = d.get("sideboard") or {}
            if sideboard and not existing_sb:
                save_deck(
                    name=d["name"],
                    format_name=d.get("format", format_name),
                    archetype=d.get("archetype", archetype),
                    mainboard=d.get("mainboard") or {},
                    sideboard=sideboard,
                    notes=d.get("notes", ""),
                    deck_id=d["id"],
                )
            return d["id"]

    # No existing -- create a new one with the observed cards
    mainboard = _resolve_grpids_to_name_counts(observed_grp_ids)
    if not mainboard:
        return None

    today_str = date.today().isoformat()
    name = f"{archetype} (auto-imported {today_str})"
    new_id = save_deck(
        name=name,
        format_name=format_name,
        archetype=archetype,
        mainboard=mainboard,
        sideboard=sideboard,
        notes=(
            f"Auto-imported from MTGA Player.log on {today_str}. "
            f"Mainboard + sideboard derived from observed grpIds across "
            f"game(s); edit My Decks to refine."
        ),
    )
    return new_id
