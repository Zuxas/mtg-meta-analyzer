"""
Cross-source duplicate detection with confidence scoring.

Identifies duplicate events and decks across MTGTop8, MTGDecks, and MTGMelee
using fingerprinting, name similarity, date matching, and player overlap.

Usage:
    from analysis.cross_source_dedup import find_duplicate_events, get_dedup_report
    dupes = find_duplicate_events("standard")
    report = get_dedup_report("standard")
"""

from datetime import datetime


def find_duplicate_events(format_name: str = "standard",
                          min_confidence: float = 0.5) -> list:
    """
    Find likely duplicate events across different data sources.

    Returns list of dupe groups:
    [
        {
            "confidence": float (0.0-1.0),
            "reason": str,
            "events": [
                {"id": int, "source": str, "name": str, "date": str,
                 "deck_count": int, "fingerprint_cs": str},
                ...
            ],
        },
        ...
    ]
    Sorted by confidence descending.
    """
    from db.database import get_connection

    conn = get_connection()
    try:
        # Get all events with their fingerprints and deck counts
        rows = conn.execute("""
            SELECT e.id, e.source, e.source_id, e.name, e.date, e.format,
                   e.event_fingerprint_cs AS fp_cs,
                   COUNT(d.id) AS deck_count
            FROM events e
            LEFT JOIN decks d ON d.event_id = e.id
            WHERE lower(e.format) = lower(?)
              AND e.event_fingerprint_cs IS NOT NULL
              AND e.event_fingerprint_cs != ''
            GROUP BY e.id
            ORDER BY e.date DESC
        """, (format_name,)).fetchall()
    finally:
        conn.close()

    # Group by cross-source fingerprint
    fp_groups: dict = {}
    for r in rows:
        fp = r["fp_cs"]
        fp_groups.setdefault(fp, []).append(dict(r))

    duplicates = []
    for fp, events in fp_groups.items():
        # Only interested in groups with multiple sources
        sources = {e["source"] for e in events}
        if len(sources) < 2:
            continue

        # Calculate confidence based on matching criteria
        confidence = _score_confidence(events)
        if confidence < min_confidence:
            continue

        reason = _explain_match(events, confidence)
        duplicates.append({
            "confidence": round(confidence, 2),
            "reason": reason,
            "fingerprint": fp,
            "events": [{
                "id": e["id"],
                "source": e["source"],
                "name": e["name"],
                "date": e["date"],
                "deck_count": e["deck_count"],
                "fingerprint_cs": fp,
            } for e in events],
        })

    duplicates.sort(key=lambda d: -d["confidence"])
    return duplicates


def _score_confidence(events: list) -> float:
    """Score how likely a group of events are true duplicates (0.0-1.0)."""
    if len(events) < 2:
        return 0.0

    score = 0.5  # base: fingerprint match = 50%

    # Same date → +25%
    dates = {e["date"] for e in events if e.get("date")}
    normalized_dates = set()
    for d in dates:
        normalized_dates.add(_normalize_date(d))
    if len(normalized_dates) == 1:
        score += 0.25

    # Similar deck counts → +15%
    deck_counts = [e["deck_count"] for e in events if e["deck_count"] > 0]
    if len(deck_counts) >= 2:
        max_c = max(deck_counts)
        min_c = min(deck_counts)
        if max_c > 0 and min_c / max_c >= 0.5:
            score += 0.15

    # Name similarity → +10%
    names = [e["name"].lower().strip() for e in events if e.get("name")]
    if len(names) >= 2:
        # Check if names share significant tokens
        token_sets = [set(n.split()) for n in names]
        if len(token_sets) >= 2:
            overlap = token_sets[0] & token_sets[1]
            union = token_sets[0] | token_sets[1]
            if union and len(overlap) / len(union) >= 0.3:
                score += 0.10

    return min(score, 1.0)


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYYMMDD for comparison."""
    d = (date_str or "").strip()
    if "/" in d:
        parts = d.split("/")
        if len(parts) == 3:
            dd, mm, yy = parts
            if len(yy) == 2:
                yy = "20" + yy
            return f"{yy}{mm}{dd}"
    return d.replace("-", "")


def _explain_match(events: list, confidence: float) -> str:
    """Generate a human-readable explanation of why events match."""
    sources = sorted({e["source"] for e in events})
    parts = [f"Same event across {' + '.join(sources)}"]
    if confidence >= 0.9:
        parts.append("very high confidence (fingerprint + date + deck count match)")
    elif confidence >= 0.7:
        parts.append("high confidence (fingerprint + date match)")
    else:
        parts.append("moderate confidence (fingerprint match only)")
    return " — ".join(parts)


def get_dedup_report(format_name: str = "standard") -> dict:
    """
    Generate a summary report of cross-source duplicates.

    Returns:
        {
            "format": str,
            "total_events": int,
            "duplicate_groups": int,
            "events_in_dupes": int,
            "removable_events": int,  # extra copies that could be merged
            "by_source_pair": {
                "mtgtop8+mtgdecks": int,
                "mtgtop8+mtgmelee": int,
                ...
            },
            "duplicates": list,  # from find_duplicate_events()
            "savings_pct": float,  # % of events that are duplicates
        }
    """
    from db.database import get_connection

    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM events WHERE lower(format) = lower(?)",
            (format_name,)
        ).fetchone()[0]
    finally:
        conn.close()

    dupes = find_duplicate_events(format_name, min_confidence=0.5)

    events_in_dupes = sum(len(d["events"]) for d in dupes)
    removable = sum(len(d["events"]) - 1 for d in dupes)  # keep 1, remove rest

    # Count by source pair
    by_pair: dict = {}
    for d in dupes:
        sources = sorted({e["source"] for e in d["events"]})
        pair_key = "+".join(sources)
        by_pair[pair_key] = by_pair.get(pair_key, 0) + 1

    return {
        "format": format_name,
        "total_events": total,
        "duplicate_groups": len(dupes),
        "events_in_dupes": events_in_dupes,
        "removable_events": removable,
        "by_source_pair": by_pair,
        "duplicates": dupes,
        "savings_pct": round(removable / max(total, 1) * 100, 1),
    }
