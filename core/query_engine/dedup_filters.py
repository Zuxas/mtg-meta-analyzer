"""
core/query_engine/dedup_filters.py

Pure Python filtering functions that prevent duplicate deck records from
inflating analysis results.

No DB calls, no side effects.  Accepts lists of sqlite3.Row or dict objects
and returns filtered lists of the same type.

Why three separate cases?
--------------------------
Cross-source duplicates (dedup_cross_source, default ON):
    The same physical deck submission scraped from both mtgtop8 AND mtgdecks
    for the same real-world event.  deck_fingerprint AND event_fingerprint
    match — these are definitively the same record and must not be double-
    counted.  Impact: ~2,600 standard decks (~7%) would otherwise be counted
    twice, inflating meta-share and top8-rate figures.

Same-player multi-event (unique_player_decks, default OFF):
    A player grinds the same 75 cards across many separate events (e.g. a
    MTGO grinder running Living End in 40 Challenges).  Each appearance is a
    genuine separate event — valid for meta-share stats but distorts
    "how popular is this build" analysis.  Off by default because for most
    questions (archetype win %, meta share over time) each tournament result
    is a separate data point.

Multi-player same build (never filtered):
    Different players independently registering the same stock list.  This is
    real signal: it means the build is popular.  Always counted separately.
"""

from collections import defaultdict


# ---------------------------------------------------------------------------
# Internal: row accessor works on both sqlite3.Row and dict
# ---------------------------------------------------------------------------

def _get(row, key, default=None):
    try:
        v = row[key]
        return v if v is not None else default
    except (IndexError, KeyError):
        return default


def _placement(row):
    """Return placement as int; treat NULL/0 as a large number (worst rank)."""
    p = _get(row, "placement")
    try:
        p = int(p)
        return p if p > 0 else 9999
    except (TypeError, ValueError):
        return 9999


# ---------------------------------------------------------------------------
# Filter 1: cross-source duplicates  (default ON)
# ---------------------------------------------------------------------------

def filter_cross_source_duplicates(rows):
    """
    Collapse rows where the same 75 cards appeared at the same real-world
    event via multiple scrapers.

    Detection: deck_fingerprint AND event_fingerprint both match.

    When collapsing a group, keep the row with the best placement (lowest
    number).  Tiebreak: prefer the row with the smallest deck_id (usually
    the earliest-scraped, typically mtgtop8 which has richer event metadata).

    Rows with a NULL deck_fingerprint or NULL event_fingerprint are passed
    through unchanged — we cannot safely identify them as duplicates.
    """
    # key -> best row so far
    keyed: dict = {}
    unkeyed: list = []

    for row in rows:
        dfp = _get(row, "deck_fingerprint")
        # Use event_fingerprint_cs (cross-source, strips trailing serials) so
        # the same real-world event matches across mtgtop8 and mtgdecks even
        # when one source appends an internal event ID (e.g. "#12835978").
        # event_fingerprint (strict) is NOT used here because it preserves
        # trailing numbers — two scrapers may produce different strict fingerprints
        # for the same real event.
        efp = _get(row, "event_fingerprint_cs")

        if not dfp or not efp:
            # Cannot determine cross-source identity without both fingerprints.
            unkeyed.append(row)
            continue

        key = (dfp, efp)
        if key not in keyed:
            keyed[key] = row
        else:
            existing = keyed[key]
            ep = _placement(existing)
            rp = _placement(row)
            if rp < ep:
                keyed[key] = row
            elif rp == ep:
                # Tiebreak: smaller deck_id wins (earlier / primary source)
                if _get(row, "deck_id", 9_999_999) < _get(existing, "deck_id", 9_999_999):
                    keyed[key] = row

    return list(keyed.values()) + unkeyed


# ---------------------------------------------------------------------------
# Filter 2: same-player multi-event  (default OFF)
# ---------------------------------------------------------------------------

def filter_unique_player_decks(rows):
    """
    Reduce a player's repeated appearances with the same 75 to a single
    record — their best result.

    Use case: a MTGO grinder running the same Living End list in 40 Challenges
    produces 40 rows.  With this filter they contribute one row (best
    placement), which gives a cleaner picture of "how many distinct players
    are running this build."

    Default: OFF.  For meta-share and trend analysis each tournament result
    is a separate data point and should be counted.  Enable only when the
    question is "how many unique players / unique builds".

    Rows with NULL player are passed through unchanged.
    """
    keyed: dict = {}
    unkeyed: list = []

    for row in rows:
        player = _get(row, "player")
        dfp    = _get(row, "deck_fingerprint")

        if not player or not dfp:
            unkeyed.append(row)
            continue

        key = (player.strip().lower(), dfp)
        if key not in keyed:
            keyed[key] = row
        else:
            existing = keyed[key]
            ep = _placement(existing)
            rp = _placement(row)
            if rp < ep:
                keyed[key] = row

    return list(keyed.values()) + unkeyed


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def apply_deck_filters(rows, dedup_cross_source=True, unique_player_decks=False):
    """
    Apply deduplication filters to a list of deck appearance rows.

    Parameters
    ----------
    rows : list
        sqlite3.Row or dict objects; must include deck_fingerprint,
        event_fingerprint, event_source, player, placement, deck_id columns
        (added to _fetch_appearances and get_meta_standings SELECTs).
    dedup_cross_source : bool, default True
        Remove cross-source duplicates (same deck + same event, different
        scraper).  Should be True for all production analysis.
    unique_player_decks : bool, default False
        Collapse a player's repeated appearances with identical 75 to their
        single best result.  Off by default; useful for "unique builds" views.

    Returns
    -------
    list
        Filtered rows in the same format as the input.
    """
    if dedup_cross_source:
        rows = filter_cross_source_duplicates(rows)
    if unique_player_decks:
        rows = filter_unique_player_decks(rows)
    return rows
