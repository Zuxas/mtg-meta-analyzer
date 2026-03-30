"""
Sideboard advisor — suggests which of YOUR sideboard cards to bring
in/out for each matchup, based on:

1. Community guide data (what do other players board in vs this deck?)
2. Card role heuristics (graveyard hate vs graveyard decks, etc.)
3. Card text matching (counter vs combo, removal vs creature-heavy)

Public API:
    suggest_sb_plan(my_sideboard, opponent_archetype, format_name) → dict
    suggest_all_plans(my_sideboard, meta_standings, format_name) → list[dict]
"""

import re

# Card role heuristics: keyword in oracle text → role tag
_ROLE_PATTERNS = {
    "graveyard_hate":  r"exile.*graveyard|exile.*cards? from.*graveyard|can't.*return from.*graveyard",
    "artifact_hate":   r"destroy.*artifact|exile.*artifact|artifact.*can't",
    "enchantment_hate": r"destroy.*enchantment|exile.*enchantment",
    "lifegain":        r"you gain \d+ life|lifelink",
    "counterspell":    r"counter target spell|counter target.*ability",
    "board_wipe":      r"destroy all|deals? \d+ damage to each|exile all|-\d+/-\d+ until end",
    "discard":         r"discard|choose.*hand",
    "land_hate":       r"nonbasic.*land|blood moon|destroy target land",
    "removal":         r"destroy target creature|exile target creature|deals? \d+ damage to.*creature",
    "protection":      r"hexproof|protection from|ward|can't be countered",
}

# Archetype → which role tags are strong against it
_ARCHETYPE_WEAKNESSES = {
    # Graveyard decks
    "dimir reanimator": ["graveyard_hate", "counterspell"],
    "reanimator":       ["graveyard_hate", "counterspell"],
    "living end":       ["graveyard_hate", "counterspell"],
    "dredge":           ["graveyard_hate"],
    "goryo's vengeance": ["graveyard_hate", "counterspell"],
    # Artifact decks
    "izzet affinity":   ["artifact_hate", "board_wipe"],
    "affinity":         ["artifact_hate", "board_wipe"],
    "eldrazi tron":     ["land_hate", "artifact_hate"],
    "amulet titan":     ["land_hate", "counterspell"],
    # Combo decks
    "belcher":          ["counterspell", "discard", "land_hate"],
    "simic neoform":    ["counterspell", "graveyard_hate"],
    "grinding breach":  ["graveyard_hate", "artifact_hate", "counterspell"],
    "lotus combo":      ["counterspell", "discard"],
    "ruby storm":       ["counterspell", "discard"],
    # Aggro decks
    "burn":             ["lifegain", "protection"],
    "mono red aggro":   ["lifegain", "board_wipe", "removal"],
    "boros aggro":      ["board_wipe", "removal"],
    # Midrange/Control
    "jeskai control":   ["discard", "counterspell", "protection"],
    "azorius control":  ["discard", "counterspell"],
    "dimir midrange":   ["protection", "board_wipe"],
}


def _get_card_roles(card_name: str, format_name: str = "modern") -> set:
    """Determine the functional roles of a card from its oracle text."""
    try:
        from scrapers.scryfall import get_card_data
        data = get_card_data(card_name)
        if not data:
            return set()
        oracle = (data.get("oracle_text") or "").lower()
        roles = set()
        for role, pattern in _ROLE_PATTERNS.items():
            if re.search(pattern, oracle):
                roles.add(role)
        return roles
    except Exception:
        return set()


def _get_archetype_weaknesses(opponent: str) -> list:
    """Get the role tags that are strong against this opponent."""
    opp_lower = opponent.lower()
    # Direct match
    if opp_lower in _ARCHETYPE_WEAKNESSES:
        return _ARCHETYPE_WEAKNESSES[opp_lower]
    # Substring match
    for key, roles in _ARCHETYPE_WEAKNESSES.items():
        if key in opp_lower or opp_lower in key:
            return roles
    return []


def suggest_sb_plan(my_sideboard: dict, opponent_archetype: str,
                    format_name: str = "modern") -> dict:
    """Suggest which sideboard cards to bring in against an opponent.

    my_sideboard: {"Card Name": quantity, ...}
    opponent_archetype: e.g. "Amulet Titan"

    Returns:
        {
            "opponent": str,
            "bring_in": [{"card": str, "qty": int, "reason": str, "confidence": str}],
            "take_out_hint": str,
            "coverage": str,
        }
    """
    if not my_sideboard:
        return {"opponent": opponent_archetype, "bring_in": [],
                "take_out_hint": "", "coverage": "no sideboard"}

    # 1. Check community guides for this matchup
    guide_cards = _check_guides(opponent_archetype, format_name, set(my_sideboard.keys()))

    # 2. Check card roles vs archetype weaknesses
    weaknesses = _get_archetype_weaknesses(opponent_archetype)
    role_cards = {}
    if weaknesses:
        for card, qty in my_sideboard.items():
            roles = _get_card_roles(card, format_name)
            matching_roles = roles & set(weaknesses)
            if matching_roles:
                role_cards[card] = {
                    "qty": qty,
                    "roles": matching_roles,
                    "reason": f"{'|'.join(matching_roles)} vs {opponent_archetype}",
                }

    # 3. Merge: guides take priority, roles fill gaps
    bring_in = []
    seen = set()

    for card, info in guide_cards.items():
        if card not in seen:
            seen.add(card)
            bring_in.append({
                "card": card,
                "qty": my_sideboard.get(card, 0),
                "reason": info["reason"],
                "confidence": "high",
            })

    for card, info in role_cards.items():
        if card not in seen:
            seen.add(card)
            bring_in.append({
                "card": card,
                "qty": info["qty"],
                "reason": info["reason"],
                "confidence": "medium",
            })

    # Sort by confidence then qty
    conf_order = {"high": 0, "medium": 1, "low": 2}
    bring_in.sort(key=lambda x: (conf_order.get(x["confidence"], 9), -x["qty"]))

    total_in = sum(b["qty"] for b in bring_in)
    hint = f"Board in ~{total_in} cards → take out {total_in} of your weakest cards in this matchup"

    coverage = "guide-based" if guide_cards else ("role-based" if role_cards else "no suggestions")

    return {
        "opponent": opponent_archetype,
        "bring_in": bring_in,
        "take_out_hint": hint,
        "coverage": coverage,
    }


def _check_guides(opponent: str, format_name: str, my_sb_cards: set) -> dict:
    """Check community guides for cards that match our sideboard."""
    try:
        from analysis.sideboard_guides import get_matchup_guides
        # We don't know our archetype here, so search broadly
        from db.database import get_combined_connection
        conn = get_combined_connection()
        try:
            rows = conn.execute("""
                SELECT comment FROM guides
                WHERE lower(format) = lower(?)
                  AND (lower(archetype) LIKE ? OR lower(archetype) LIKE ?)
                LIMIT 30
            """, [format_name,
                  f"%{opponent.lower().split()[0]}%",
                  f"%{opponent.lower()}%"]).fetchall()
        finally:
            conn.close()

        if not rows:
            return {}

        # Parse IN cards from all matching guides
        from analysis.sideboard_guides import parse_sb_plan
        card_freq = {}
        for r in rows:
            plan = parse_sb_plan(r["comment"])
            for qty, name in plan.get("in", []):
                name_lower = name.lower()
                for my_card in my_sb_cards:
                    if my_card.lower() == name_lower or name_lower in my_card.lower():
                        card_freq.setdefault(my_card, 0)
                        card_freq[my_card] += 1

        result = {}
        for card, freq in card_freq.items():
            result[card] = {
                "reason": f"found in {freq} guide(s) vs {opponent}",
            }
        return result

    except Exception:
        return {}


def suggest_all_plans(my_sideboard: dict, meta_archetypes: list,
                      format_name: str = "modern") -> list:
    """Generate SB suggestions for all meta matchups.

    meta_archetypes: list of archetype name strings
    Returns list of suggest_sb_plan results, sorted by most cards to board in.
    """
    results = []
    for opp in meta_archetypes:
        plan = suggest_sb_plan(my_sideboard, opp, format_name)
        if plan["bring_in"]:
            results.append(plan)
    results.sort(key=lambda p: -sum(b["qty"] for b in p["bring_in"]))
    return results
