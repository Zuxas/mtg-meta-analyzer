"""
Sideboard advisor — suggests which of YOUR sideboard cards to bring
in/out for each matchup, based on:

1. Community guide data (what do other players board in vs this deck?)
2. Card role heuristics (graveyard hate vs graveyard decks, etc.)
3. Card text matching (counter vs combo, removal vs creature-heavy)

Public API:
    suggest_sb_plan(my_sideboard, opponent_archetype, format_name, mainboard) → dict
    suggest_all_plans(my_sideboard, meta_standings, format_name, mainboard) → list[dict]
"""

import re

# Card roles that are WEAK against certain archetype types
# "removal" is bad vs creatureless combo, "counterspell" is bad vs low-curve aggro, etc.
_ARCHETYPE_DEAD_ROLES = {
    # Combo (few/no creatures to kill)
    "belcher":          ["removal", "board_wipe"],
    "living end":       ["removal"],
    "lotus combo":      ["removal", "board_wipe"],
    "ruby storm":       ["removal", "board_wipe"],
    "simic neoform":    ["removal", "board_wipe"],
    "grinding breach":  ["removal"],
    # Big mana (removal doesn't matter, they go over you)
    "amulet titan":     ["removal"],
    "eldrazi tron":     [],
    # Aggro (counterspells too slow)
    "burn":             ["counterspell"],
    "mono red aggro":   ["counterspell"],
    "boros aggro":      ["counterspell"],
    # Control (aggressive 1-drops bad)
    "jeskai control":   [],
    "azorius control":  [],
}

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
    "removal":         r"destroy target creature|destroy target permanent|exile target creature|exile target permanent|deals? \d+ damage to any target|deals? \d+ damage to target|deals? \d+ damage to.*creature|damage to that (?:creature|permanent|player)",
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


def _get_dead_roles(opponent: str) -> list:
    """Get card roles that are WEAK/dead against this opponent."""
    opp_lower = opponent.lower()
    for key, roles in _ARCHETYPE_DEAD_ROLES.items():
        if key in opp_lower or opp_lower in key:
            return roles
    return []


def _suggest_outs(mainboard: dict, opponent: str, num_outs: int,
                  format_name: str = "modern") -> list:
    """Suggest mainboard cards to take OUT against an opponent.

    Returns: [{"card": str, "qty": int, "reason": str}]
    """
    if not mainboard or num_outs <= 0:
        return []

    dead_roles = _get_dead_roles(opponent)

    # Check community guides for OUT cards
    guide_outs = _check_guide_outs(opponent, format_name, set(mainboard.keys()))

    # Score each mainboard card: higher = worse in this matchup = board out first
    scored = []
    for card, qty in mainboard.items():
        score = 0
        reason = ""

        # Check guides first
        if card in guide_outs:
            score += 50
            reason = guide_outs[card]

        # Check card roles vs dead roles
        if dead_roles:
            roles = _get_card_roles(card, format_name)
            dead_matches = roles & set(dead_roles)
            if dead_matches:
                score += 30
                reason = reason or f"{'|'.join(dead_matches)} weak vs {opponent}"

        if score > 0:
            scored.append({"card": card, "qty": qty, "score": score, "reason": reason})

    # Sort by score descending, take enough to match num_outs
    scored.sort(key=lambda x: -x["score"])

    outs = []
    remaining = num_outs
    for s in scored:
        if remaining <= 0:
            break
        take = min(s["qty"], remaining)
        outs.append({"card": s["card"], "qty": take, "reason": s["reason"]})
        remaining -= take

    return outs


def _check_guide_outs(opponent: str, format_name: str, my_main_cards: set) -> dict:
    """Check community guides for OUT cards that match our mainboard."""
    try:
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

        from analysis.sideboard_guides import parse_sb_plan
        card_freq = {}
        for r in rows:
            plan = parse_sb_plan(r["comment"])
            for qty, name in plan.get("out", []):
                name_lower = name.lower()
                for my_card in my_main_cards:
                    if my_card.lower() == name_lower or name_lower in my_card.lower():
                        card_freq.setdefault(my_card, 0)
                        card_freq[my_card] += 1

        return {card: f"out in {freq} guide(s) vs {opponent}" for card, freq in card_freq.items()}
    except Exception:
        return {}


def suggest_sb_plan(my_sideboard: dict, opponent_archetype: str,
                    format_name: str = "modern",
                    mainboard: dict = None) -> dict:
    """Suggest which sideboard cards to bring in AND mainboard cards to take out.

    my_sideboard: {"Card Name": quantity, ...}
    mainboard: {"Card Name": quantity, ...} (optional, enables OUT suggestions)
    opponent_archetype: e.g. "Amulet Titan"

    Returns:
        {
            "opponent": str,
            "bring_in": [{"card": str, "qty": int, "reason": str, "confidence": str}],
            "take_out": [{"card": str, "qty": int, "reason": str}],
            "coverage": str,
        }
    """
    if not my_sideboard:
        return {"opponent": opponent_archetype, "bring_in": [], "take_out": [],
                "coverage": "no sideboard"}

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

    # Sort by confidence then qty
    total_in = sum(b["qty"] for b in bring_in)

    # Suggest OUT cards from mainboard (match total IN count)
    take_out = []
    if mainboard and total_in > 0:
        take_out = _suggest_outs(mainboard, opponent_archetype, total_in, format_name)

    coverage = "guide-based" if guide_cards else ("role-based" if role_cards else "no suggestions")

    return {
        "opponent": opponent_archetype,
        "bring_in": bring_in,
        "take_out": take_out,
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
                      format_name: str = "modern",
                      mainboard: dict = None) -> list:
    """Generate SB suggestions for all meta matchups.

    meta_archetypes: list of archetype name strings
    mainboard: {"Card Name": qty} for OUT suggestions
    Returns list of suggest_sb_plan results, sorted by most cards to board in.
    """
    results = []
    for opp in meta_archetypes:
        plan = suggest_sb_plan(my_sideboard, opp, format_name, mainboard=mainboard)
        if plan["bring_in"]:
            results.append(plan)
    results.sort(key=lambda p: -sum(b["qty"] for b in p["bring_in"]))
    return results
