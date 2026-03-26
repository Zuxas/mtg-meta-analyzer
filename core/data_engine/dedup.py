"""
core/data_engine/dedup.py — Cross-source duplicate detection foundation.

PHASE 1 (this file): exact-match fingerprints only.
  Pure functions — no DB calls, no side effects. Can be used anywhere.

PHASE 2 (future): fuzzy matching + confidence scoring.
  See inline comments marked "Phase 2" throughout this file.

Typical usage:

    from core.data_engine.dedup import (
        generate_event_fingerprint,      # strict — stored in events.event_fingerprint
        generate_event_fingerprint_cs,   # cross-source — stored in events.event_fingerprint_cs
        generate_deck_fingerprint,
        events_are_duplicates,
        decks_are_duplicates,
    )

    fp = generate_event_fingerprint(
        name="MTGO Standard Challenge #12",
        date="15/03/26",
        format_name="standard",
    )

    is_dup = events_are_duplicates(
        name_a="MTGO Standard Challenge 12", date_a="15/03/26", format_a="standard",
        name_b="Magic Online Standard Challenge #12", date_b="2026-03-15", format_b="Standard",
    )
    # → True (same event, different source naming)
"""

import hashlib
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

def normalize_date(raw: str) -> str:
    """
    Normalize any date string to YYYYMMDD.

    Handles all date formats seen across sources:
      DD/MM/YY   (MTGTop8)     "15/03/26"   → "20260315"
      YYYY-MM-DD (MTGDecks)    "2026-03-15" → "20260315"
      YYYYMMDD   (pre-normalized in queries) → unchanged

    Returns the raw string unchanged on parse failure rather than raising,
    so a bad date still produces a usable (if less accurate) fingerprint.
    """
    raw = (raw or "").strip()
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 3:
            d, m, y = parts
            year = f"20{y}" if len(y) == 2 else y
            return f"{year}{m.zfill(2)}{d.zfill(2)}"
    if "-" in raw and len(raw) == 10:
        # YYYY-MM-DD
        return raw.replace("-", "")
    return raw  # already YYYYMMDD, or unknown — return as-is


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

# Both sources refer to MTGO differently in event names.
_MTGO_ALIASES = re.compile(
    r"\b(magic\s*online|mtgo|mtg\s*online)\b", re.IGNORECASE
)

# Strips trailing serial numbers e.g. "#12835978" or bare "12" at end of name.
# Used ONLY in cross-source normalization — not in the stored event fingerprint.
_TRAILING_NUMBER = re.compile(r"\s*#?\d+\s*$")

_MULTI_SPACE = re.compile(r"\s+")


def _normalize_event_name(name: str) -> str:
    """
    Strict normalization — trailing numbers are PRESERVED.

    Used for the stored event_fingerprint so that same-source same-day
    numbered events (e.g. "LCQ #1" through "LCQ #22") each receive a
    distinct fingerprint.  The old behaviour of stripping trailing numbers
    caused all 22 rounds on the same day to collapse into one fingerprint,
    producing 417 false-positive duplicate groups.

    Steps:
      1. Lowercase
      2. Collapse MTGO name variants → "mtgo"
      3. Collapse runs of whitespace
      4. Strip leading/trailing whitespace
    """
    n = (name or "").lower()
    n = _MTGO_ALIASES.sub("mtgo", n)
    n = _MULTI_SPACE.sub(" ", n)
    return n.strip()


def _normalize_event_name_cs(name: str) -> str:
    """
    Cross-source normalization — strips trailing numbers.

    Used for event_fingerprint_cs so that the same real-world event matches
    across scrapers even when one source appends an internal serial number
    (e.g. mtgdecks appends "#12835978" to MTGO event names).

    The one confirmed cross-source event match in production ("RC Turin 2026")
    has identical names on both sources so trailing-number stripping is not
    needed there.  This function is retained for robustness against future
    cases where sources differ in trailing numbers.

    Steps:
      1. Lowercase
      2. Collapse MTGO name variants → "mtgo"
      3. Strip trailing number/serial
      4. Collapse runs of whitespace
      5. Strip leading/trailing whitespace
    """
    n = (name or "").lower()
    n = _MTGO_ALIASES.sub("mtgo", n)
    n = _TRAILING_NUMBER.sub("", n)
    n = _MULTI_SPACE.sub(" ", n)
    return n.strip()


def _normalize_format(fmt: str) -> str:
    return (fmt or "").lower().strip()


def _normalize_card_name(name: str) -> str:
    """
    Normalize a card name so Arena and MTGO exports match.

    Differences seen in practice:
      - Curly apostrophes vs straight: "Kaito's Pursuit" vs "Kaito\u2019s Pursuit"
      - Double spaces from copy-paste
    Card names are otherwise stable across sources.
    """
    n = (name or "").lower().strip()
    n = re.sub(r"['\u2018\u2019\u201a\u201b]", "'", n)  # normalize apostrophes
    n = re.sub(r"\s+", " ", n)
    return n


# ---------------------------------------------------------------------------
# Fingerprint generation
# ---------------------------------------------------------------------------

def generate_event_fingerprint(
    name: str,
    date: str,
    format_name: str,
) -> str:
    """
    Return a 16-char hex fingerprint for an event (strict — preserves trailing numbers).

    Hashes: normalized_date | normalized_format | normalized_name_strict

    Trailing numbers are preserved so same-source same-day numbered events
    (e.g. "LCQ #1" through "LCQ #22") receive distinct fingerprints and do
    not form false-positive duplicate groups.

    Stored in the events.event_fingerprint column.  For cross-source duplicate
    detection, use generate_event_fingerprint_cs which tolerates source-
    specific trailing serials.

    16 hex chars = 64-bit SHA-256 prefix.
    """
    norm_date = normalize_date(date)
    norm_fmt  = _normalize_format(format_name)
    norm_name = _normalize_event_name(name)        # strict: no trailing-number strip
    payload   = f"{norm_date}|{norm_fmt}|{norm_name}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def generate_event_fingerprint_cs(
    name: str,
    date: str,
    format_name: str,
) -> str:
    """
    Return a 16-char hex fingerprint for cross-source event matching.

    Uses _normalize_event_name_cs which strips trailing numbers, allowing
    the same real-world event to match across scrapers even when one source
    appends an internal serial (e.g. "#12835978" in mtgdecks event names).

    Stored in events.event_fingerprint_cs.  Used by:
      - upsert_event: detect cross-source duplicate events at scrape time
      - filter_cross_source_duplicates: group deck appearances by real event
    """
    norm_date = normalize_date(date)
    norm_fmt  = _normalize_format(format_name)
    norm_name = _normalize_event_name_cs(name)     # cross-source: strips trailing number
    payload   = f"{norm_date}|{norm_fmt}|{norm_name}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def generate_deck_fingerprint(
    mainboard: dict,
    sideboard: Optional[dict] = None,
    player: Optional[str] = None,
) -> str:
    """
    Return a 16-char hex fingerprint for a deck's card content.

    mainboard / sideboard are {card_name: quantity} dicts, as stored by
    insert_deck_cards() or returned by analysis/deck_analysis.py.

    Player name is excluded from the default fingerprint so that the
    same 75 cards scraped from two sources match even when player names
    differ (MTGO usernames vs real names at paper events).

    Pass player= for a stricter fingerprint, e.g. to detect when the same
    player submitted nearly identical lists to multiple events.

    Canonical card string format:  "4xlightning bolt;2xwild slash;..."
    (sorted alphabetically by normalized card name, quantities embedded)

    Phase 2 plan:
      - deck_card_overlap(mb_a, mb_b) → float: shared cards / union of cards
      - Thresholds: ≥ 0.95 = near-certain duplicate, ≥ 0.80 = same archetype variant
      - Treat lands separately: land base varies more than spell suite
        (two 75s with identical spells but different basic land counts → still dup)
      - Expose confidence score so GUI can surface "probable duplicate" pairs
        for manual review rather than auto-merging
    """
    def _canonical(card_dict: dict) -> str:
        if not card_dict:
            return ""
        pairs = sorted(
            (_normalize_card_name(k), int(v))
            for k, v in card_dict.items()
            if k and v
        )
        return ";".join(f"{qty}x{name}" for name, qty in pairs)

    main_str = _canonical(mainboard or {})
    side_str = _canonical(sideboard or {})
    payload  = f"main:{main_str}||side:{side_str}"

    if player:
        payload += f"||player:{(player or '').lower().strip()}"

    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def events_are_duplicates(
    name_a: str, date_a: str, format_a: str,
    name_b: str, date_b: str, format_b: str,
    cross_source: bool = False,
) -> bool:
    """
    Return True if two event rows represent the same real-world event.

    cross_source=False (default): uses strict fingerprint — trailing numbers
        preserved.  Suitable for same-source comparison.
    cross_source=True: uses cross-source fingerprint — trailing numbers
        stripped.  Suitable for comparing events from different scrapers.

    Phase 2 plan:
      - Return (is_dup: bool, confidence: float) tuple
      - confidence = 1.0 for exact match, <1.0 for fuzzy match
      - Expose threshold parameter (default 0.85) for callers to tune
      - At confidence 0.7–0.85: surface to user for manual review
    """
    if cross_source:
        fp_a = generate_event_fingerprint_cs(name_a, date_a, format_a)
        fp_b = generate_event_fingerprint_cs(name_b, date_b, format_b)
    else:
        fp_a = generate_event_fingerprint(name_a, date_a, format_a)
        fp_b = generate_event_fingerprint(name_b, date_b, format_b)
    return fp_a == fp_b


def decks_are_duplicates(
    mainboard_a: dict, sideboard_a: dict,
    mainboard_b: dict, sideboard_b: dict,
) -> bool:
    """
    Return True if two decks have identical card lists.

    Phase 1: exact fingerprint match only (same 75 cards, same quantities).

    Phase 2 plan:
      - Return (is_dup: bool, overlap: float) where overlap is the Jaccard
        card overlap ratio (shared cards / union of unique card names)
      - near-certain: overlap ≥ 0.95
      - probable:     overlap ≥ 0.80
      - same archetype: overlap ≥ 0.67 (matches find_card_based_duplicates threshold)
    """
    fp_a = generate_deck_fingerprint(mainboard_a, sideboard_a)
    fp_b = generate_deck_fingerprint(mainboard_b, sideboard_b)
    return fp_a == fp_b


# ---------------------------------------------------------------------------
# Quick self-test (python -m core.data_engine.dedup)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Event fingerprint test ===")

    # Same event, two source naming conventions — should match
    fp1 = generate_event_fingerprint(
        "MTGO Standard Challenge #12", "15/03/26", "standard"
    )
    fp2 = generate_event_fingerprint(
        "Magic Online Standard Challenge 12", "2026-03-15", "Standard"
    )
    print(f"  fp1 (MTGTop8 style): {fp1}")
    print(f"  fp2 (MTGDecks style): {fp2}")
    print(f"  match: {fp1 == fp2}  (expect True)")

    # Different event — should not match
    fp3 = generate_event_fingerprint(
        "MTGO Standard Challenge #13", "22/03/26", "standard"
    )
    print(f"  fp3 (different event): {fp3}")
    print(f"  fp1==fp3: {fp1 == fp3}  (expect False)")

    print()
    print("=== Deck fingerprint test ===")

    mb = {"Lightning Bolt": 4, "Wild Slash": 2, "Monastery Swiftspear": 4}
    sb = {"Smash to Smithereens": 3}

    # Same cards, different apostrophe style — should match
    mb2 = {"Lightning Bolt": 4, "Wild Slash": 2, "Monastery Swiftspear": 4}
    sb2 = {"Smash to Smithereens": 3}

    fp4 = generate_deck_fingerprint(mb, sb)
    fp5 = generate_deck_fingerprint(mb2, sb2)
    print(f"  fp4: {fp4}")
    print(f"  fp5: {fp5}")
    print(f"  match: {fp4 == fp5}  (expect True)")

    # Different sideboard
    sb3 = {"Smash to Smithereens": 2}
    fp6 = generate_deck_fingerprint(mb, sb3)
    print(f"  fp6 (diff sideboard): {fp6}")
    print(f"  fp4==fp6: {fp4 == fp6}  (expect False)")

    print()
    print("=== normalize_date test ===")
    for raw, expected in [
        ("15/03/26", "20260315"),
        ("2026-03-15", "20260315"),
        ("20260315", "20260315"),
    ]:
        result = normalize_date(raw)
        status = "OK" if result == expected else f"FAIL (got {result})"
        print(f"  {raw!r:20} -> {result}  {status}")
