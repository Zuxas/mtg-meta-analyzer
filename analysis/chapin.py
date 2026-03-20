"""
Chapin Principles Evaluation module.

Evaluates a deck against Patrick Chapin's six pillars of good deck construction:
  1. Threats       — Density of win conditions
  2. Answers       — Ability to interact with opponent's threats
  3. Consistency   — Redundancy and reliability of the game plan
  4. Velocity      — Card draw, selection, and mana efficiency
  5. Mana          — Reliability and efficiency of the mana base
  6. Clock         — Speed and pressure

Each principle is scored 0-10. Overall rating is the weighted average.

Usage:
    from analysis.chapin import evaluate_deck

    result = evaluate_deck(mainboard, sideboard, format_name="standard")
    print(result.summary())

    # mainboard/sideboard = list[{name, quantity}] or {name: quantity}
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from scrapers.scryfall import get_cards_data


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PrincipleScore:
    name:        str
    score:       float       # 0–10
    rating:      str         # 'Excellent' / 'Good' / 'Fair' / 'Poor'
    explanation: str


@dataclass
class ChapinReport:
    archetype:      str
    format_name:    str
    scores:         list = field(default_factory=list)   # list[PrincipleScore]
    overall_score:  float = 0.0
    overall_rating: str   = "Unknown"
    recommendation: str   = ""

    def summary(self):
        lines = [
            f"\n=== Chapin Principles: {self.archetype} ({self.format_name.upper()}) ===\n",
            f"  Overall: {self.overall_score:.1f}/10  [{self.overall_rating}]\n",
        ]
        for ps in self.scores:
            bar_filled = int(ps.score)
            bar = ("█" * bar_filled + "░" * (10 - bar_filled))
            lines.append(f"  {ps.name:<14} {bar}  {ps.score:.1f}  [{ps.rating}]")
            lines.append(f"               {ps.explanation}")
        if self.recommendation:
            lines.append(f"\n  Recommendation: {self.recommendation}")
        lines.append("")
        return "\n".join(lines)

    def as_dict(self):
        return {
            "archetype":      self.archetype,
            "format":         self.format_name,
            "overall_score":  self.overall_score,
            "overall_rating": self.overall_rating,
            "recommendation": self.recommendation,
            "principles":     [
                {"name": ps.name, "score": ps.score,
                 "rating": ps.rating, "explanation": ps.explanation}
                for ps in self.scores
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_dict(cards):
    if isinstance(cards, dict):
        return cards
    return {c["name"]: c["quantity"] for c in cards}


def _rating(score):
    if score >= 8.0:
        return "Excellent"
    if score >= 6.0:
        return "Good"
    if score >= 4.0:
        return "Fair"
    return "Poor"


def _classify_cards(main_dict, card_data):
    """
    Returns sets of card names classified by role:
    lands, creatures, planeswalkers, spells (non-creature, non-land), interaction,
    draw_spells, ramp_spells.
    """
    lands         = set()
    creatures     = set()
    planeswalkers = set()
    interaction   = set()
    draw_spells   = set()
    ramp_spells   = set()
    other_spells  = set()

    INTERACTION_KW = [
        "destroy", "exile target", "counter target", "return target",
        "deals damage to target", "-1/-1", "-2/-2", "sacrifice a",
    ]
    DRAW_KW = [
        "draw a card", "draw two", "draw three", "draw cards",
        "look at the top", "scry", "surveil",
    ]
    RAMP_KW = [
        "search your library for a", "add {", "you may put a land",
        "land card", "basic land",
    ]

    for name, data in card_data.items():
        if name not in main_dict or not data:
            continue
        type_line  = data.get("type_line") or ""
        oracle     = (data.get("oracle_text") or "").lower()

        if "Land" in type_line:
            lands.add(name)
        elif "Creature" in type_line:
            creatures.add(name)
            # Creatures can also be interaction (ETB removal, etc.)
            if any(kw in oracle for kw in INTERACTION_KW):
                interaction.add(name)
        elif "Planeswalker" in type_line:
            planeswalkers.add(name)
        else:
            other_spells.add(name)
            if any(kw in oracle for kw in INTERACTION_KW):
                interaction.add(name)
            if any(kw in oracle for kw in DRAW_KW):
                draw_spells.add(name)
            if any(kw in oracle for kw in RAMP_KW):
                ramp_spells.add(name)

    return {
        "lands":          lands,
        "creatures":      creatures,
        "planeswalkers":  planeswalkers,
        "interaction":    interaction,
        "draw_spells":    draw_spells,
        "ramp_spells":    ramp_spells,
        "other_spells":   other_spells,
    }


def _qty(main_dict, name_set):
    """Total quantity of cards whose names are in name_set."""
    return sum(main_dict.get(n, 0) for n in name_set)


def _avg_cmc(main_dict, card_data, exclude=None):
    exclude = exclude or set()
    cmcs = []
    for name, qty in main_dict.items():
        if name in exclude:
            continue
        data = card_data.get(name)
        if data and data.get("cmc") is not None:
            cmcs.extend([float(data["cmc"])] * qty)
    return sum(cmcs) / len(cmcs) if cmcs else 0.0


# ---------------------------------------------------------------------------
# Format thresholds for scoring
# ---------------------------------------------------------------------------

_FORMAT_SPEEDS = {
    "standard": {"fast_clock": 3.5, "good_clock": 4.0},
    "pioneer":  {"fast_clock": 3.5, "good_clock": 4.0},
    "modern":   {"fast_clock": 2.5, "good_clock": 3.0},
    "legacy":   {"fast_clock": 1.5, "good_clock": 2.5},
    "vintage":  {"fast_clock": 1.5, "good_clock": 2.5},
    "pauper":   {"fast_clock": 3.0, "good_clock": 4.0},
}


# ---------------------------------------------------------------------------
# Individual principle evaluations
# ---------------------------------------------------------------------------

def _score_threats(main_dict, cats, format_name):
    """
    Principle 1 — Threat Density
    Counts creatures + planeswalkers as primary threats.
    Baseline: 10+ threat spells = excellent for most formats.
    """
    threat_names = cats["creatures"] | cats["planeswalkers"]
    threat_qty   = _qty(main_dict, threat_names)
    total_nonland = sum(main_dict.get(n, 0)
                        for n in main_dict if n not in cats["lands"])

    if total_nonland == 0:
        return PrincipleScore("Threats", 0.0, "Poor", "No non-land cards found.")

    density = threat_qty / total_nonland

    # Score: density 40%+ = 10, 25% = 7, 15% = 5, <10% = 2
    if density >= 0.40:
        score = 10.0
        note  = f"{threat_qty} threats ({density*100:.0f}% of spells) — high threat density."
    elif density >= 0.25:
        score = 7.0 + (density - 0.25) / 0.15 * 3.0
        note  = f"{threat_qty} threats ({density*100:.0f}% of spells) — solid threat density."
    elif density >= 0.15:
        score = 5.0 + (density - 0.15) / 0.10 * 2.0
        note  = f"{threat_qty} threats ({density*100:.0f}%) — moderate. Consider more win conditions."
    else:
        score = max(1.0, density / 0.15 * 5.0)
        note  = f"Only {threat_qty} threats ({density*100:.0f}%) — may struggle to close games."

    return PrincipleScore("Threats", round(score, 1), _rating(score), note)


def _score_answers(main_dict, cats, format_name):
    """
    Principle 2 — Answers / Interaction
    Counts dedicated interaction spells. Creatures with interaction ETBs count at 50%.
    """
    # Non-creature interaction (full count)
    pure_interaction = cats["interaction"] - cats["creatures"]
    creature_interaction = cats["interaction"] & cats["creatures"]

    qty = (_qty(main_dict, pure_interaction) +
           _qty(main_dict, creature_interaction) * 0.5)

    # Format context: modern/legacy need more interaction
    norms = {"standard": 6, "pioneer": 6, "modern": 8, "legacy": 10, "pauper": 6}
    target = norms.get(format_name.lower(), 6)

    ratio = qty / target
    score = min(10.0, ratio * 10.0)

    if score >= 8.0:
        note = f"{qty:.0f} interaction pieces — excellent answer density."
    elif score >= 6.0:
        note = f"{qty:.0f} interaction pieces — good, slightly below optimal."
    elif score >= 4.0:
        note = f"{qty:.0f} interaction pieces — limited. Add more removal or counters."
    else:
        note = f"Only {qty:.0f} interaction pieces — very low. Deck may fold to threats."

    return PrincipleScore("Answers", round(score, 1), _rating(score), note)


def _score_consistency(main_dict, cats):
    """
    Principle 3 — Consistency
    Measures 4-of density and mana curve smoothness.
    A consistent deck runs 4-ofs of key effects.
    """
    non_land = {n: q for n, q in main_dict.items() if n not in cats["lands"]}
    if not non_land:
        return PrincipleScore("Consistency", 0.0, "Poor", "No spells in deck.")

    unique = len(non_land)
    four_ofs = sum(1 for q in non_land.values() if q >= 4)
    three_ofs = sum(1 for q in non_land.values() if q == 3)
    singletons = sum(1 for q in non_land.values() if q == 1)

    # Score based on % of slots in 4-ofs
    total_spell_slots = sum(non_land.values())
    slots_in_4ofs = sum(q for q in non_land.values() if q >= 4)
    concentration = slots_in_4ofs / total_spell_slots if total_spell_slots else 0

    score = min(10.0, 2.0 + concentration * 10.0)

    note = (f"{four_ofs} 4-ofs, {three_ofs} 3-ofs, {singletons} singletons. "
            f"{concentration*100:.0f}% of spell slots in 4-ofs.")
    if singletons > unique * 0.4:
        note += " High singleton count reduces consistency."

    return PrincipleScore("Consistency", round(score, 1), _rating(score), note)


def _score_velocity(main_dict, cats, card_data):
    """
    Principle 4 — Velocity (card draw + selection)
    Measures access to card draw and filtering.
    """
    draw_qty = _qty(main_dict, cats["draw_spells"])
    # Cantrips on creatures count at 50%
    creature_draw = set()
    for name in cats["creatures"]:
        data = card_data.get(name)
        if data:
            oracle = (data.get("oracle_text") or "").lower()
            if "draw a card" in oracle:
                creature_draw.add(name)

    effective_draw = draw_qty + _qty(main_dict, creature_draw) * 0.5
    total_spells = sum(main_dict.get(n, 0) for n in main_dict if n not in cats["lands"])

    # Benchmark: 8+ draw spells = very high velocity
    if effective_draw >= 10:
        score = 10.0
        note  = f"{effective_draw:.0f} card draw/selection spells — exceptional velocity."
    elif effective_draw >= 6:
        score = 7.0 + (effective_draw - 6) / 4 * 3.0
        note  = f"{effective_draw:.0f} draw/filter spells — good velocity."
    elif effective_draw >= 3:
        score = 5.0 + (effective_draw - 3) / 3 * 2.0
        note  = f"{effective_draw:.0f} draw spells — moderate. More card selection would help."
    else:
        score = max(2.0, effective_draw / 3 * 5.0)
        note  = f"Only {effective_draw:.0f} draw effects — low velocity. Deck may run out of resources."

    return PrincipleScore("Velocity", round(score, 1), _rating(score), note)


def _score_mana(main_dict, cats, card_data, format_name):
    """
    Principle 5 — Mana Base
    Evaluates land count vs CMC, color fixing, and mana efficiency.
    """
    land_count = _qty(main_dict, cats["lands"])
    avg_cmc    = _avg_cmc(main_dict, card_data, exclude=cats["lands"])

    # Expected land count for the curve
    # Rule of thumb: ~17 + avg_cmc * 1.5 lands
    expected_lands = 17 + avg_cmc * 1.5
    land_ratio     = land_count / expected_lands if expected_lands else 1.0

    # Color check: more colors = more fixing needed
    color_set = set()
    for name, data in card_data.items():
        if name in cats["lands"] or not data or name not in main_dict:
            continue
        colors = data.get("colors") or []
        if isinstance(colors, str):
            try:
                colors = json.loads(colors)
            except Exception:
                colors = []
        color_set.update(colors)

    color_penalty = max(0, len(color_set) - 2) * 0.5  # penalty for 3+ colors
    score = min(10.0, land_ratio * 8.0 - color_penalty)
    score = max(0.0, score)

    note = (f"{land_count} lands, avg CMC {avg_cmc:.2f}. "
            f"{len(color_set)}-color deck.")
    if color_penalty > 0:
        note += f" Color complexity reduces mana score by {color_penalty:.1f}."

    return PrincipleScore("Mana", round(score, 1), _rating(score), note)


def _score_clock(main_dict, cats, card_data, format_name):
    """
    Principle 6 — Clock / Speed
    Estimates how quickly the deck can win. Low avg CMC of threats = faster clock.
    """
    threat_names = cats["creatures"] | cats["planeswalkers"]
    threat_cmcs  = []
    for name in threat_names:
        if name not in main_dict:
            continue
        data = card_data.get(name)
        if data and data.get("cmc") is not None:
            threat_cmcs.extend([float(data["cmc"])] * main_dict[name])

    if not threat_cmcs:
        return PrincipleScore(
            "Clock", 4.0, "Fair",
            "No creatures/planeswalkers — clock based on other win conditions."
        )

    avg_threat_cmc = sum(threat_cmcs) / len(threat_cmcs)
    speeds = _FORMAT_SPEEDS.get(format_name.lower(), _FORMAT_SPEEDS["standard"])

    if avg_threat_cmc <= speeds["fast_clock"]:
        score = 9.0 + max(0, (speeds["fast_clock"] - avg_threat_cmc) * 0.5)
        score = min(10.0, score)
        note  = f"Avg threat CMC {avg_threat_cmc:.2f} — fast clock for {format_name}."
    elif avg_threat_cmc <= speeds["good_clock"]:
        score = 6.5 + (speeds["good_clock"] - avg_threat_cmc) / \
                (speeds["good_clock"] - speeds["fast_clock"]) * 2.5
        note  = f"Avg threat CMC {avg_threat_cmc:.2f} — solid midrange clock."
    else:
        score = max(2.0, 6.5 - (avg_threat_cmc - speeds["good_clock"]) * 1.5)
        note  = f"Avg threat CMC {avg_threat_cmc:.2f} — slow clock. Needs strong late-game payoffs."

    return PrincipleScore("Clock", round(score, 1), _rating(score), note)


# ---------------------------------------------------------------------------
# Weights per principle (sum to 1.0)
# ---------------------------------------------------------------------------

_PRINCIPLE_WEIGHTS = {
    "Threats":     0.20,
    "Answers":     0.20,
    "Consistency": 0.18,
    "Velocity":    0.15,
    "Mana":        0.17,
    "Clock":       0.10,
}


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------

def evaluate_deck(mainboard, sideboard=None, format_name="standard",
                  archetype="Unknown"):
    """
    Evaluate a decklist against Chapin's six principles.

    Args:
        mainboard:   list[{name, quantity}] or {name: quantity}
        sideboard:   list[{name, quantity}] or {name: quantity} or None
        format_name: format string (default 'standard')
        archetype:   deck name for display

    Returns:
        ChapinReport
    """
    main_dict = _to_dict(mainboard)
    _to_dict(sideboard or {})  # validated but not yet used in scoring

    all_names = list(main_dict.keys())
    card_data = get_cards_data(all_names)
    cats      = _classify_cards(main_dict, card_data)

    scores = [
        _score_threats(main_dict, cats, format_name),
        _score_answers(main_dict, cats, format_name),
        _score_consistency(main_dict, cats),
        _score_velocity(main_dict, cats, card_data),
        _score_mana(main_dict, cats, card_data, format_name),
        _score_clock(main_dict, cats, card_data, format_name),
    ]

    overall = sum(
        ps.score * _PRINCIPLE_WEIGHTS.get(ps.name, 1/6)
        for ps in scores
    )

    # Generate top recommendation from weakest principle
    weakest = min(scores, key=lambda ps: ps.score)
    recommendation = f"Focus on improving {weakest.name}: {weakest.explanation}"

    overall_rating = _rating(overall)

    return ChapinReport(
        archetype=archetype,
        format_name=format_name,
        scores=scores,
        overall_score=round(overall, 2),
        overall_rating=overall_rating,
        recommendation=recommendation,
    )
