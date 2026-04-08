"""
Slot analysis — explain why a card is in a deck and what alternatives exist.

For any card in an archetype, provides:
  - Role classification (Threat/Removal/etc)
  - Inclusion rate and trend
  - Functional substitutes from Card2Vec
  - Cards competing for the same role slot

Usage:
    from analysis.slot_analysis import analyze_slot
    info = analyze_slot("Lightning Bolt", "Izzet Prowess", "standard")
"""


def analyze_slot(card_name: str, archetype: str,
                 format_name: str = "standard") -> dict:
    """
    Explain a card's role in a deck: why it's here, what else could go in its slot.

    Returns:
        {
            "card": str,
            "archetype": str,
            "format": str,
            "role": str,                     # Threat/Removal/Card Advantage/etc
            "inclusion_rate": float,         # 0.0-1.0 in this archetype
            "avg_copies": float,             # average copies when included
            "is_core": bool,                 # >80% inclusion = core card
            "is_flex": bool,                 # 15-80% inclusion = flex slot
            "trend": str,                    # "rising", "falling", "stable", "new"
            "trend_delta": float,            # inclusion change over recent weeks
            "substitutes": list[dict],       # [{name, similarity}, ...] from Card2Vec
            "competitors": list[dict],       # same-role flex slots competing for this slot
            "explanation": str,              # human-readable summary
        }
    """
    from analysis.deck_analysis import get_average_deck

    avg = get_average_deck(archetype, format_name, min_inclusion=0.05)
    if not avg:
        return _empty(card_name, archetype, format_name, "Archetype not found")

    # Find the card in mainboard or sideboard
    all_cards = avg.get("mainboard", []) + avg.get("sideboard", [])
    card_info = None
    for c in all_cards:
        if c["name"].lower() == card_name.lower():
            card_info = c
            break

    if not card_info:
        return _empty(card_name, archetype, format_name, "Card not found in this archetype")

    inc = card_info["inclusion_rate"]
    avg_qty = card_info.get("avg_qty_in", card_info.get("avg_qty", 0))
    is_core = inc >= 0.80
    is_flex = 0.15 <= inc < 0.80

    # Get role
    role = _get_role(card_name)

    # Get trend
    trend, trend_delta = _get_trend(card_name, archetype, format_name)

    # Get substitutes from Card2Vec
    substitutes = _get_substitutes(card_name, format_name)

    # Find same-role competitors (other flex slots with the same role)
    competitors = []
    if is_flex:
        all_names = [c["name"] for c in avg.get("mainboard", [])
                     if 0.15 <= c["inclusion_rate"] < 0.80]
        roles = _get_roles_batch(all_names)
        for c in avg.get("mainboard", []):
            if (c["name"] != card_name
                    and 0.15 <= c["inclusion_rate"] < 0.80
                    and roles.get(c["name"]) == role):
                competitors.append({
                    "name": c["name"],
                    "inclusion_rate": round(c["inclusion_rate"], 3),
                    "avg_copies": round(c.get("avg_qty_in", c.get("avg_qty", 0)), 1),
                })
        competitors.sort(key=lambda x: -x["inclusion_rate"])

    # Build explanation
    explanation = _build_explanation(
        card_name, role, inc, avg_qty, is_core, is_flex,
        trend, trend_delta, len(substitutes), len(competitors),
    )

    return {
        "card": card_name,
        "archetype": archetype,
        "format": format_name,
        "role": role,
        "inclusion_rate": round(inc, 3),
        "avg_copies": round(avg_qty, 2),
        "is_core": is_core,
        "is_flex": is_flex,
        "trend": trend,
        "trend_delta": round(trend_delta, 3),
        "substitutes": substitutes[:8],
        "competitors": competitors[:6],
        "explanation": explanation,
    }


def _empty(card, arch, fmt, reason):
    return {
        "card": card, "archetype": arch, "format": fmt,
        "role": "Unknown", "inclusion_rate": 0, "avg_copies": 0,
        "is_core": False, "is_flex": False,
        "trend": "unknown", "trend_delta": 0,
        "substitutes": [], "competitors": [],
        "explanation": reason,
    }


def _get_role(card_name: str) -> str:
    try:
        from db.database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT type_line, oracle_text FROM card_data WHERE name = ?",
                (card_name,)
            ).fetchone()
        finally:
            conn.close()
        if row:
            from gui.widgets.archetype_detail import _classify_card_role
            return _classify_card_role(row["type_line"], row["oracle_text"])
    except Exception:
        pass
    return "Unknown"


def _get_roles_batch(card_names: list) -> dict:
    try:
        from gui.widgets.archetype_detail import _get_card_roles
        return _get_card_roles(card_names)
    except Exception:
        return {}


def _get_trend(card_name: str, archetype: str, format_name: str):
    try:
        from analysis.card_adoption import get_card_adoption
        data = get_card_adoption(archetype, format_name, weeks=6)
        for c in data.get("cards", []):
            if c["name"].lower() == card_name.lower():
                return c["status"], c["trend"]
    except Exception:
        pass
    return "unknown", 0.0


def _get_substitutes(card_name: str, format_name: str) -> list:
    try:
        from analysis.cooccurrence_embeddings import find_functional_substitutes
        return find_functional_substitutes(card_name, format_name, top_n=8)
    except Exception:
        return []


def _build_explanation(card, role, inc, avg_qty, is_core, is_flex,
                       trend, trend_delta, sub_count, comp_count) -> str:
    parts = []

    # Core vs flex
    if is_core:
        parts.append(f"{card} is a core card ({inc*100:.0f}% inclusion, ~{avg_qty:.1f} copies).")
    elif is_flex:
        parts.append(f"{card} is a flex slot ({inc*100:.0f}% inclusion, ~{avg_qty:.1f} copies).")
    else:
        parts.append(f"{card} appears in {inc*100:.0f}% of lists (~{avg_qty:.1f} copies).")

    # Role
    parts.append(f"Role: {role}.")

    # Trend
    if trend == "rising":
        parts.append(f"Trending up (+{trend_delta*100:.0f}% over recent weeks).")
    elif trend == "falling":
        parts.append(f"Trending down ({trend_delta*100:.0f}% over recent weeks).")
    elif trend == "new":
        parts.append("Recently adopted — new addition to the archetype.")

    # Competition
    if comp_count > 0:
        parts.append(f"{comp_count} other {role.lower()} card{'s' if comp_count != 1 else ''} compete for this slot.")

    # Substitutes
    if sub_count > 0:
        parts.append(f"{sub_count} functional substitutes identified.")

    return " ".join(parts)
