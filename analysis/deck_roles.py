"""
Deck role classification — tag archetypes as Aggro, Midrange, Control, Combo, or Tempo.

Uses the average decklist composition (creature count, removal density, mana curve,
combo piece indicators) to classify each archetype's strategic role.

Usage:
    from analysis.deck_roles import classify_role, classify_roles_batch
    role = classify_role("Boros Energy", "standard")
    roles = classify_roles_batch(["Boros Energy", "Dimir Control"], "standard")
"""

from functools import lru_cache


# ── Card classification helpers ───────────────────────────────────────────

def _is_creature(type_line: str) -> bool:
    return "creature" in (type_line or "").lower()


def _is_land(type_line: str) -> bool:
    return "land" in (type_line or "").lower()


def _is_planeswalker(type_line: str) -> bool:
    return "planeswalker" in (type_line or "").lower()


def _is_removal(oracle: str) -> bool:
    keywords = [
        "destroy target", "exile target", "deals damage to",
        "counter target", "-x/-x", "gets -", "destroy all", "exile all",
    ]
    return any(kw in (oracle or "").lower() for kw in keywords)


def _is_draw(oracle: str) -> bool:
    keywords = ["draw a card", "draw two", "draw cards", "scry", "surveil"]
    return any(kw in (oracle or "").lower() for kw in keywords)


def _is_combo_indicator(oracle: str) -> bool:
    """Detect cards that enable infinite/deterministic combos."""
    keywords = [
        "you win the game", "infinite", "untap all",
        "take an extra turn", "copy target spell",
        "sacrifice a creature: add", "each opponent loses",
        "return all", "cast without paying",
    ]
    return any(kw in (oracle or "").lower() for kw in keywords)


def _is_cheap(cmc: float) -> bool:
    """CMC <= 2 is 'cheap' for aggro/tempo purposes."""
    return (cmc or 0) <= 2.0


# ── Role classification ──────────────────────────────────────────────────

_ROLE_CACHE: dict = {}


def classify_role(archetype: str, format_name: str = "standard",
                  min_inclusion: float = 0.25) -> str:
    """
    Classify an archetype into a strategic role based on its average decklist.

    Returns one of: "Aggro", "Midrange", "Control", "Combo", "Tempo"

    Classification logic:
        1. Count creatures, removal, draw, combo indicators, and average CMC
        2. Apply weighted heuristics:
           - High creature count + low curve → Aggro
           - High removal + high draw + high curve → Control
           - Combo indicators present → Combo
           - Moderate creatures + moderate removal + low curve → Tempo
           - Everything else → Midrange
    """
    cache_key = (archetype.lower(), format_name.lower())
    if cache_key in _ROLE_CACHE:
        return _ROLE_CACHE[cache_key]

    role = _classify_role_impl(archetype, format_name, min_inclusion)
    _ROLE_CACHE[cache_key] = role
    return role


def _classify_role_impl(archetype: str, format_name: str,
                        min_inclusion: float) -> str:
    try:
        from analysis.deck_analysis import get_average_deck
        avg = get_average_deck(archetype, format_name, min_inclusion=min_inclusion)
        if not avg or not avg.get("mainboard"):
            # Try with looser matching
            avg = get_average_deck(archetype, format_name, min_inclusion=0.10)
            if not avg or not avg.get("mainboard"):
                return "Unknown"
    except Exception:
        return "Unknown"

    # Get card data for all mainboard cards
    card_names = [c["name"] for c in avg["mainboard"]]
    card_data = _get_card_data_batch(card_names)

    # Analyze composition
    total_cards = 0
    creature_count = 0
    removal_count = 0
    draw_count = 0
    combo_count = 0
    cheap_creature_count = 0
    total_cmc = 0.0
    nonland_count = 0

    for c in avg["mainboard"]:
        name = c["name"]
        qty = c.get("suggested_qty", round(c.get("avg_qty", 1)))
        cd = card_data.get(name, {})
        tl = cd.get("type_line", "")
        ot = cd.get("oracle_text", "")
        cmc = cd.get("cmc", 0) or 0

        total_cards += qty

        if _is_land(tl):
            continue

        nonland_count += qty
        total_cmc += cmc * qty

        if _is_creature(tl) or _is_planeswalker(tl):
            creature_count += qty
            if _is_cheap(cmc):
                cheap_creature_count += qty
        if _is_removal(ot):
            removal_count += qty
        if _is_draw(ot):
            draw_count += qty
        if _is_combo_indicator(ot):
            combo_count += qty

    if nonland_count == 0:
        return "Unknown"

    avg_cmc = total_cmc / nonland_count
    creature_pct = creature_count / nonland_count
    removal_pct = removal_count / nonland_count
    draw_pct = draw_count / nonland_count
    cheap_creature_pct = cheap_creature_count / nonland_count

    # Classification rules (order matters)
    # Combo: significant combo indicators (need a critical mass, not just a few triggers)
    if combo_count >= 8:
        return "Combo"

    # Aggro: lots of cheap creatures, low curve
    if creature_pct >= 0.55 and avg_cmc <= 2.3 and cheap_creature_pct >= 0.35:
        return "Aggro"

    # Control: few creatures, lots of removal + draw, high curve
    if creature_pct <= 0.25 and (removal_pct + draw_pct) >= 0.35:
        return "Control"

    # Tempo: moderate creatures, some removal, low curve
    if creature_pct >= 0.30 and removal_pct >= 0.10 and avg_cmc <= 2.5:
        return "Tempo"

    # Midrange: everything else
    return "Midrange"


def classify_roles_batch(archetypes: list, format_name: str = "standard") -> dict:
    """Classify multiple archetypes. Returns {archetype: role}."""
    return {arch: classify_role(arch, format_name) for arch in archetypes}


def _get_card_data_batch(card_names: list) -> dict:
    """Look up type_line, oracle_text, cmc for a list of card names."""
    if not card_names:
        return {}
    try:
        from db.database import get_connection
        conn = get_connection()
        try:
            ph = ",".join("?" * len(card_names))
            rows = conn.execute(f"""
                SELECT name, type_line, oracle_text, cmc
                FROM card_data WHERE name IN ({ph})
            """, card_names).fetchall()
        finally:
            conn.close()
        return {r["name"]: dict(r) for r in rows}
    except Exception:
        return {}
