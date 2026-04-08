"""
Card adoption tracking — how card inclusion rates change over time within an archetype.

Returns week-by-week inclusion rates for all cards in a given archetype,
sorted by biggest recent change (trending cards first).

Usage:
    from analysis.card_adoption import get_card_adoption
    data = get_card_adoption("Boros Energy", "standard", weeks=8)
"""

from datetime import datetime, timedelta


def get_card_adoption(archetype: str, format_name: str = "standard",
                      weeks: int = 8, min_inclusion: float = 0.10) -> dict:
    """
    Track card inclusion rates over time for an archetype.

    Returns:
        {
            "archetype": str,
            "format": str,
            "weeks": list[str],           # bucket start dates
            "cards": [
                {
                    "name": str,
                    "current_rate": float,   # inclusion rate in most recent window
                    "trend": float,          # change vs earliest window (-1.0 to +1.0)
                    "rates": list[float],    # inclusion rate per week bucket
                    "status": str,           # "rising", "falling", "stable", "new", "dropped"
                },
                ...
            ],
        }
    """
    from db.database import get_combined_connection

    now = datetime.now()
    since = now - timedelta(weeks=weeks)

    _date_key = (
        "CASE WHEN instr(e.date,'/')>0 "
        "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
        "ELSE replace(e.date,'-','') END"
    )

    conn = get_combined_connection()
    try:
        # Get all decks for this archetype in the time window
        rows = conn.execute(f"""
            SELECT d.id AS deck_id, ({_date_key}) AS sort_date
            FROM decks d
            JOIN events e ON e.id = d.event_id
            WHERE lower(d.archetype) LIKE lower(?)
              AND lower(e.format) = lower(?)
              AND ({_date_key}) >= ?
            ORDER BY sort_date
        """, (f"%{archetype}%", format_name, since.strftime("%Y%m%d"))).fetchall()

        if not rows:
            return {"archetype": archetype, "format": format_name, "weeks": [], "cards": []}

        deck_ids = [r["deck_id"] for r in rows]
        deck_dates = {r["deck_id"]: r["sort_date"] for r in rows}

        # Get all cards for those decks
        ph = ",".join("?" * len(deck_ids))
        card_rows = conn.execute(f"""
            SELECT dc.deck_id, c.name, dc.is_sideboard
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            WHERE dc.deck_id IN ({ph}) AND dc.is_sideboard = 0
        """, deck_ids).fetchall()
    finally:
        conn.close()

    # Bucket decks into weekly windows
    bucket_size = timedelta(weeks=1)
    buckets = []
    bucket_start = since
    while bucket_start < now:
        bucket_end = bucket_start + bucket_size
        bucket_deck_ids = {
            did for did, sd in deck_dates.items()
            if bucket_start.strftime("%Y%m%d") <= sd < bucket_end.strftime("%Y%m%d")
        }
        buckets.append({
            "start": bucket_start.strftime("%Y-%m-%d"),
            "deck_ids": bucket_deck_ids,
        })
        bucket_start = bucket_end

    # Filter out empty buckets
    buckets = [b for b in buckets if b["deck_ids"]]
    if len(buckets) < 2:
        return {"archetype": archetype, "format": format_name, "weeks": [], "cards": []}

    # Map card -> set of deck_ids that include it
    card_decks: dict = {}
    for cr in card_rows:
        card_decks.setdefault(cr["name"], set()).add(cr["deck_id"])

    # Calculate per-bucket inclusion rates
    week_labels = [b["start"] for b in buckets]
    results = []
    for card_name, decks_with_card in card_decks.items():
        rates = []
        for b in buckets:
            total_in_bucket = len(b["deck_ids"])
            if total_in_bucket == 0:
                rates.append(0.0)
            else:
                count = len(decks_with_card & b["deck_ids"])
                rates.append(count / total_in_bucket)

        current_rate = rates[-1]
        earliest_rate = rates[0]
        trend = current_rate - earliest_rate

        # Skip cards below minimum inclusion in all buckets
        if max(rates) < min_inclusion:
            continue

        # Classify
        if earliest_rate < 0.05 and current_rate >= min_inclusion:
            status = "new"
        elif current_rate < 0.05 and earliest_rate >= min_inclusion:
            status = "dropped"
        elif abs(trend) < 0.05:
            status = "stable"
        elif trend > 0:
            status = "rising"
        else:
            status = "falling"

        results.append({
            "name": card_name,
            "current_rate": round(current_rate, 3),
            "trend": round(trend, 3),
            "rates": [round(r, 3) for r in rates],
            "status": status,
        })

    # Sort by absolute trend magnitude (biggest movers first)
    results.sort(key=lambda c: -abs(c["trend"]))

    return {
        "archetype": archetype,
        "format": format_name,
        "weeks": week_labels,
        "cards": results,
    }
