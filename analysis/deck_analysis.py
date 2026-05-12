"""
Deck analysis: average deck calculator and deck comparison.

Core functions (no UI coupling — safe to call from CLI, GUI, or scripts):

    get_average_deck(archetype, format_name, min_inclusion)
    compare_deck_to_average(deck, archetype, format_name, min_inclusion)
    get_deck_by_placement(event_id, placement)
    search_decks(archetype, format_name, limit)
    get_recent_event(format_name, event_type)
"""

from db.database import get_connection


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_archetype_decks(conn, archetype, format_name=None, include_archive=False):
    """
    Return all deck rows (with cards) for a given archetype.
    Matching is case-insensitive and partial (LIKE '%archetype%').
    """
    base_query = """
        SELECT d.id, d.archetype, d.player, d.placement, d.event_id,
               e.date, e.name as event_name, e.format
        FROM decks d
        JOIN events e ON e.id = d.event_id
        WHERE lower(d.archetype) LIKE lower(?)
    """
    params = [f"%{archetype}%"]

    if format_name:
        base_query += " AND lower(e.format) = lower(?)"
        params.append(format_name)

    if include_archive:
        # UNION with archive DB (must be ATTACHed)
        archive_query = base_query.replace("FROM decks", "FROM archive.decks").replace(
            "FROM events", "FROM archive.events"
        )
        full_query = base_query + " UNION ALL " + archive_query
        params = params + params
    else:
        full_query = base_query

    return conn.execute(full_query, params).fetchall()


def _fetch_deck_cards(conn, deck_ids, include_archive=False):
    """Return all deck_card rows for a list of deck IDs."""
    if not deck_ids:
        return []
    ph = ",".join("?" * len(deck_ids))
    query = f"""
        SELECT dc.deck_id, c.name, dc.quantity, dc.is_sideboard
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        WHERE dc.deck_id IN ({ph})
    """
    rows = conn.execute(query, deck_ids).fetchall()

    if include_archive:
        archive_query = query.replace("FROM deck_cards", "FROM archive.deck_cards").replace(
            "JOIN cards", "JOIN archive.cards"
        )
        rows += conn.execute(archive_query, deck_ids).fetchall()

    return rows


# ---------------------------------------------------------------------------
# Average deck
# ---------------------------------------------------------------------------

def get_average_deck(archetype, format_name=None, min_inclusion=0.25,
                     include_archive=False):
    """
    Calculate the statistical average decklist for an archetype.

    For each card, computes:
      - inclusion_rate : fraction of decks that run ≥1 copy
      - avg_qty_in     : average copies among decks that DO run it
      - avg_qty_overall: avg_qty_in × inclusion_rate (copies across all decks)
      - suggested_qty  : round(avg_qty_overall), floored at 1 when included

    Returns a dict:
    {
        "archetype": str,
        "format": str,
        "deck_count": int,
        "mainboard": [ {name, inclusion_rate, avg_qty_in, avg_qty_overall, suggested_qty}, ... ],
        "sideboard": [ ... ],
    }
    Cards below min_inclusion threshold are excluded.
    """
    from db.database import get_combined_connection
    conn = get_combined_connection(include_archive=include_archive)

    try:
        deck_rows = _fetch_archetype_decks(conn, archetype, format_name, include_archive)
        if not deck_rows:
            return None

        deck_ids = [r["id"] for r in deck_rows]
        total = len(deck_ids)
        card_rows = _fetch_deck_cards(conn, deck_ids, include_archive)
    finally:
        conn.close()

    # Aggregate per card per zone
    # Structure: {(name, is_sideboard): [qty_per_deck_that_runs_it]}
    card_appearances = {}
    # Track which decks contain each card
    card_deck_sets = {}

    for row in card_rows:
        key = (row["name"], row["is_sideboard"])
        card_appearances.setdefault(key, []).append(row["quantity"])
        card_deck_sets.setdefault(key, set()).add(row["deck_id"])

    def _build_card_list(is_sideboard):
        cards = []
        for (name, side), quantities in card_appearances.items():
            if side != is_sideboard:
                continue
            inclusion_rate = len(card_deck_sets[(name, side)]) / total
            if inclusion_rate < min_inclusion:
                continue
            avg_qty_in = sum(quantities) / len(quantities)
            avg_qty_overall = avg_qty_in * inclusion_rate
            suggested_qty = max(1, round(avg_qty_overall))
            cards.append({
                "name": name,
                "inclusion_rate": round(inclusion_rate, 3),
                "avg_qty_in": round(avg_qty_in, 2),
                "avg_qty_overall": round(avg_qty_overall, 3),
                "suggested_qty": suggested_qty,
            })
        # Sort by avg_qty_overall descending (most important cards first)
        return sorted(cards, key=lambda c: c["avg_qty_overall"], reverse=True)

    return {
        "archetype": archetype,
        "format": format_name or "all",
        "deck_count": total,
        "mainboard": _build_card_list(is_sideboard=0),
        "sideboard": _build_card_list(is_sideboard=1),
    }


# ---------------------------------------------------------------------------
# Deck comparison
# ---------------------------------------------------------------------------

def compare_deck_to_average(deck, archetype, format_name=None,
                             min_inclusion=0.25, include_archive=False):
    """
    Compare a specific deck against the average version of its archetype.

    deck: dict with keys "mainboard" and "sideboard", each a {card_name: qty} dict.
          (Use get_deck_by_placement() or get_deck_by_id() to fetch from DB.)

    Returns a dict:
    {
        "archetype": str,
        "deck_count": int,          # decks used to build the average
        "mainboard": {
            "added":    [{name, qty, note}],   # in this deck, not in average
            "cut":      [{name, avg_qty, note}], # in average, not in this deck
            "adjusted": [{name, this_qty, avg_qty, diff}],  # qty differs
            "matched":  [{name, qty}],           # identical to average
        },
        "sideboard": { same structure },
        "similarity_score": float,  # 0.0–1.0 (1.0 = identical to average)
    }
    """
    average = get_average_deck(archetype, format_name, min_inclusion, include_archive)
    if not average:
        return {"error": f"No data found for archetype '{archetype}'"}

    def _compare_zone(deck_zone, avg_cards):
        avg_lookup = {c["name"]: c for c in avg_cards}
        deck_names = set(deck_zone.keys())
        avg_names  = set(avg_lookup.keys())

        added    = []
        cut      = []
        adjusted = []
        matched  = []

        # Cards in this deck not in the average
        for name in sorted(deck_names - avg_names):
            added.append({
                "name": name,
                "qty": deck_zone[name],
                "note": "not in average list",
            })

        # Cards in the average not in this deck
        for name in sorted(avg_names - deck_names):
            c = avg_lookup[name]
            cut.append({
                "name": name,
                "avg_qty": c["suggested_qty"],
                "inclusion_rate": c["inclusion_rate"],
                "note": f"in {c['inclusion_rate']*100:.0f}% of avg decks",
            })

        # Cards in both — check quantity difference
        for name in sorted(deck_names & avg_names):
            this_qty = deck_zone[name]
            avg_qty  = avg_lookup[name]["suggested_qty"]
            if this_qty == avg_qty:
                matched.append({"name": name, "qty": this_qty})
            else:
                adjusted.append({
                    "name": name,
                    "this_qty": this_qty,
                    "avg_qty": avg_qty,
                    "diff": this_qty - avg_qty,
                })

        return {"added": added, "cut": cut, "adjusted": adjusted, "matched": matched}

    main_result = _compare_zone(deck.get("mainboard", {}), average["mainboard"])
    side_result = _compare_zone(deck.get("sideboard", {}), average["sideboard"])

    # Similarity score: matched cards / total unique cards across both lists
    avg_main_names = {c["name"] for c in average["mainboard"]}
    deck_main_names = set(deck.get("mainboard", {}).keys())
    all_names = avg_main_names | deck_main_names
    matched_names = {c["name"] for c in main_result["matched"]}
    similarity = len(matched_names) / len(all_names) if all_names else 1.0

    return {
        "archetype": average["archetype"],
        "deck_count": average["deck_count"],
        "mainboard": main_result,
        "sideboard": side_result,
        "similarity_score": round(similarity, 3),
    }


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------

def find_similar_scraped_decks(card_list: dict, format_name: str,
                               top_n: int = 5) -> list:
    """Return top-N scraped decks most similar to the input decklist.

    Uses Jaccard similarity on mainboard card names (ignores copy counts;
    two decks running 2 vs 4 Lightning Bolt still both count as 'plays
    Lightning Bolt'). Pre-filters candidates to decks that share at
    least one card with the input, then ranks top 30 candidates by
    Jaccard and returns the best top_n.

    Each result has: deck_id, player, archetype, placement, event_name,
    date, similarity (0-1), shared_count, pilot_total_cards.
    """
    from db.database import get_combined_connection

    user_names = list((card_list or {}).keys())
    if not user_names:
        return []
    user_set = set(user_names)
    a_size = len(user_set)

    conn = get_combined_connection()
    try:
        placeholders = ",".join("?" * len(user_names))
        # Rank candidate decks by number of shared mainboard cards
        cand_rows = conn.execute(
            f"""
            SELECT d.id AS deck_id,
                   COUNT(DISTINCT c.name) AS shared
            FROM decks d
            JOIN events e ON e.id = d.event_id
            JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
            JOIN cards c ON c.id = dc.card_id
            WHERE e.format = ? AND c.name IN ({placeholders})
            GROUP BY d.id
            ORDER BY shared DESC
            LIMIT 30
            """,
            [format_name, *user_names],
        ).fetchall()

        if not cand_rows:
            return []

        cand_ids = [r["deck_id"] for r in cand_rows]
        id_placeholders = ",".join("?" * len(cand_ids))
        detail_rows = conn.execute(
            f"""
            SELECT d.id AS deck_id, d.player, d.archetype, d.placement,
                   e.name AS event_name, e.date,
                   c.name AS card_name
            FROM decks d
            JOIN events e ON e.id = d.event_id
            JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
            JOIN cards c ON c.id = dc.card_id
            WHERE d.id IN ({id_placeholders})
            """,
            cand_ids,
        ).fetchall()
    finally:
        conn.close()

    # Group card names per deck; capture metadata from first row per deck
    decks_by_id = {}
    for r in detail_rows:
        did = r["deck_id"]
        entry = decks_by_id.setdefault(did, {
            "deck_id": did,
            "player": r["player"],
            "archetype": r["archetype"],
            "placement": r["placement"],
            "event_name": r["event_name"],
            "date": r["date"],
            "cards": set(),
        })
        entry["cards"].add(r["card_name"])

    results = []
    for entry in decks_by_id.values():
        b_set = entry["cards"]
        shared = len(user_set & b_set)
        union = a_size + len(b_set) - shared
        if union == 0:
            continue
        jaccard = shared / union
        results.append({
            "deck_id": entry["deck_id"],
            "player": entry["player"] or "unknown",
            "archetype": entry["archetype"] or "?",
            "placement": entry["placement"],
            "event_name": entry["event_name"] or "",
            "date": (entry["date"] or "")[:10],
            "similarity": round(jaccard, 4),
            "shared_count": shared,
            "pilot_total_cards": len(b_set),
        })
    results.sort(key=lambda d: -d["similarity"])
    return results[:top_n]


def get_deck_by_id(deck_id, include_archive=False):
    """Fetch a single deck's mainboard and sideboard from the DB by ID."""
    from db.database import get_combined_connection
    conn = get_combined_connection(include_archive=include_archive)
    try:
        deck_row = conn.execute(
            "SELECT d.*, e.name as event_name, e.date, e.format FROM decks d "
            "JOIN events e ON e.id = d.event_id WHERE d.id = ?", (deck_id,)
        ).fetchone()
        if not deck_row:
            return None

        cards = conn.execute("""
            SELECT c.name, dc.quantity, dc.is_sideboard
            FROM deck_cards dc JOIN cards c ON c.id = dc.card_id
            WHERE dc.deck_id = ?
        """, (deck_id,)).fetchall()
    finally:
        conn.close()

    return {
        "id": deck_id,
        "player": deck_row["player"],
        "archetype": deck_row["archetype"],
        "placement": deck_row["placement"],
        "event_name": deck_row["event_name"],
        "date": deck_row["date"],
        "format": deck_row["format"],
        "mainboard": {r["name"]: r["quantity"] for r in cards if not r["is_sideboard"]},
        "sideboard": {r["name"]: r["quantity"] for r in cards if r["is_sideboard"]},
    }


def get_deck_by_placement(event_id, placement=1):
    """Fetch the deck at a given placement in an event (default: 1st place)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM decks WHERE event_id=? AND placement=?",
            (event_id, placement)
        ).fetchone()
    if not row:
        return None
    return get_deck_by_id(row["id"])


def get_recent_event(format_name="standard", event_type=None):
    """Return the most recent event of a given format (and optionally type)."""
    with get_connection() as conn:
        q = "SELECT * FROM events WHERE format=?"
        params = [format_name]
        if event_type:
            q += " AND event_type=?"
            params.append(event_type)
        q += (" ORDER BY (CASE WHEN instr(date,'/')>0 "
              "THEN '20'||substr(date,7,2)||substr(date,4,2)||substr(date,1,2) "
              "ELSE replace(date,'-','') END) DESC LIMIT 1")
        row = conn.execute(q, params).fetchone()
    return dict(row) if row else None


def search_decks(archetype=None, format_name=None, limit=20):
    """List decks matching an archetype/format, most recent first."""
    with get_connection() as conn:
        q = """
            SELECT d.id, d.archetype, d.player, d.placement,
                   e.name as event_name, e.date, e.format, e.event_type
            FROM decks d JOIN events e ON e.id = d.event_id
            WHERE 1=1
        """
        params = []
        if archetype:
            q += " AND lower(d.archetype) LIKE lower(?)"
            params.append(f"%{archetype}%")
        if format_name:
            q += " AND lower(e.format) = lower(?)"
            params.append(format_name)
        q += (" ORDER BY (CASE WHEN instr(e.date,'/')>0 "
              "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
              "ELSE replace(e.date,'-','') END) DESC, d.placement ASC LIMIT ?")
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]
