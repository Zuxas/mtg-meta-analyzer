"""
Deck Scoring & Blunder Detection module.

Scores a decklist for construction errors using weighted severity tiers:
  - Minor (1pt):    Suboptimal but not wrong — marginal cards, slight curve issues
  - Moderate (4pt): Meaningful weakness — mana base problems, curve gaps
  - Major (10pt):   Critical flaw — no win conditions, no interaction, illegal cards

Each issue flagged with severity, category, description, and a suggested fix.
The deck receives a Blunder Score (lower = cleaner) and Construction Quality rating.

Usage:
    from analysis.blunders import analyze_deck

    report = analyze_deck(mainboard, sideboard, format_name="standard")
    print(report.summary())

    # mainboard/sideboard = list of {"name": str, "quantity": int}
    # or dict {name: quantity}

Feeds into the Chapin Principles Evaluation (analysis/chapin.py).
"""

from dataclasses import dataclass, field
from typing import Optional
import json

from scrapers.scryfall import get_cards_data, is_legal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BlunderIssue:
    severity:    str   # 'minor', 'moderate', 'major'
    category:    str   # e.g. 'land_count', 'cmc', 'interaction', 'win_condition'
    description: str
    suggestion:  str
    detail:      Optional[str] = None   # extra context (e.g. offending card names)

    @property
    def points(self):
        return {"minor": 1, "moderate": 4, "major": 10}.get(self.severity, 0)


@dataclass
class BlunderReport:
    archetype:            str
    format_name:          str
    mainboard_count:      int
    sideboard_count:      int
    blunder_score:        float          # 0 = perfect, 100 = disaster
    construction_quality: str           # Excellent / Good / Fair / Poor
    issues:               list = field(default_factory=list)

    def summary(self):
        lines = [
            f"\n=== Blunder Report: {self.archetype} ({self.format_name.upper()}) ===",
            f"    Mainboard: {self.mainboard_count} cards | "
            f"Sideboard: {self.sideboard_count} cards",
            f"    Blunder Score: {self.blunder_score:.0f}  |  "
            f"Construction Quality: {self.construction_quality}",
        ]
        if not self.issues:
            lines.append("    No issues detected.")
        else:
            lines.append(f"\n  Issues ({len(self.issues)}):\n")
            for issue in sorted(self.issues, key=lambda i: -i.points):
                tag = f"[{issue.severity.upper():<8}]"
                lines.append(f"  {tag} {issue.category}: {issue.description}")
                lines.append(f"            Suggestion: {issue.suggestion}")
                if issue.detail:
                    lines.append(f"            Detail: {issue.detail}")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Format-specific thresholds
# ---------------------------------------------------------------------------

_FORMAT_NORMS = {
    "standard": {
        "land_min": 20, "land_max": 26, "land_critical_min": 17,
        "cmc_warn": 3.5, "cmc_major": 5.0,
        "interaction_warn": 6, "interaction_major": 3,
        "threats_warn": 8, "threats_major": 4,
        "deck_size": 60, "sb_size": 15,
    },
    "pioneer": {
        "land_min": 20, "land_max": 26, "land_critical_min": 17,
        "cmc_warn": 3.5, "cmc_major": 5.0,
        "interaction_warn": 6, "interaction_major": 3,
        "threats_warn": 8, "threats_major": 4,
        "deck_size": 60, "sb_size": 15,
    },
    "modern": {
        "land_min": 18, "land_max": 26, "land_critical_min": 15,
        "cmc_warn": 3.0, "cmc_major": 4.5,
        "interaction_warn": 8, "interaction_major": 4,
        "threats_warn": 8, "threats_major": 4,
        "deck_size": 60, "sb_size": 15,
    },
    "legacy": {
        "land_min": 16, "land_max": 25, "land_critical_min": 13,
        "cmc_warn": 2.5, "cmc_major": 4.0,
        "interaction_warn": 10, "interaction_major": 5,
        "threats_warn": 8, "threats_major": 4,
        "deck_size": 60, "sb_size": 15,
    },
    "pauper": {
        "land_min": 18, "land_max": 26, "land_critical_min": 15,
        "cmc_warn": 3.0, "cmc_major": 5.0,
        "interaction_warn": 6, "interaction_major": 3,
        "threats_warn": 8, "threats_major": 4,
        "deck_size": 60, "sb_size": 15,
    },
}

_DEFAULT_NORMS = _FORMAT_NORMS["standard"]


def _norms(format_name):
    return _FORMAT_NORMS.get(format_name.lower(), _DEFAULT_NORMS)


# ---------------------------------------------------------------------------
# Helper: normalize input to {name: qty} dict
# ---------------------------------------------------------------------------

def _to_dict(cards):
    """Accept list[{name, quantity}] or dict{name: qty}. Returns dict."""
    if isinstance(cards, dict):
        return cards
    return {c["name"]: c["quantity"] for c in cards}


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def _check_deck_size(main_dict, side_dict, norms, issues):
    total = sum(main_dict.values())
    expected = norms["deck_size"]
    if total < expected:
        issues.append(BlunderIssue(
            severity="major" if total < expected - 4 else "moderate",
            category="deck_size",
            description=f"Mainboard has {total} cards (minimum {expected}).",
            suggestion=f"Add {expected - total} more cards to reach the minimum.",
        ))
    elif total > expected + 5:
        issues.append(BlunderIssue(
            severity="minor",
            category="deck_size",
            description=f"Mainboard has {total} cards (typically {expected}).",
            suggestion="Trimming to 60 improves consistency.",
        ))

    sb_total = sum(side_dict.values())
    if sb_total > norms["sb_size"]:
        issues.append(BlunderIssue(
            severity="minor",
            category="sideboard_size",
            description=f"Sideboard has {sb_total} cards (max {norms['sb_size']}).",
            suggestion=f"Cut {sb_total - norms['sb_size']} sideboard cards.",
        ))


def _check_land_count(main_dict, card_data, norms, issues):
    lands = [name for name, data in card_data.items()
             if data and "Land" in (data.get("type_line") or "")
             and name in main_dict]
    land_count = sum(main_dict.get(name, 0) for name in lands)

    if land_count < norms["land_critical_min"]:
        issues.append(BlunderIssue(
            severity="major",
            category="land_count",
            description=f"Only {land_count} lands in the mainboard.",
            suggestion=f"Add lands up to at least {norms['land_min']} for consistent mana.",
            detail=f"Minimum recommended: {norms['land_min']}, critical threshold: {norms['land_critical_min']}",
        ))
    elif land_count < norms["land_min"]:
        issues.append(BlunderIssue(
            severity="moderate",
            category="land_count",
            description=f"Low land count: {land_count} (recommended {norms['land_min']}-{norms['land_max']}).",
            suggestion="Consider adding 1-2 more lands unless this is an aggressive combo deck.",
        ))
    elif land_count > norms["land_max"]:
        issues.append(BlunderIssue(
            severity="minor",
            category="land_count",
            description=f"High land count: {land_count} (typical max {norms['land_max']}).",
            suggestion="Trim a land or two if the curve is low, unless you need ramp.",
        ))

    return land_count, lands


def _check_mana_curve(main_dict, card_data, land_names, norms, issues):
    non_land_cmcs = []
    for name, qty in main_dict.items():
        if name in land_names:
            continue
        data = card_data.get(name)
        if data and data.get("cmc") is not None:
            non_land_cmcs.extend([float(data["cmc"])] * qty)

    if not non_land_cmcs:
        return None

    avg_cmc = sum(non_land_cmcs) / len(non_land_cmcs)

    if avg_cmc >= norms["cmc_major"]:
        issues.append(BlunderIssue(
            severity="major",
            category="mana_curve",
            description=f"Very high average CMC: {avg_cmc:.2f}. Deck will be very slow.",
            suggestion="Lower the curve by replacing expensive spells with cheaper options.",
        ))
    elif avg_cmc >= norms["cmc_warn"]:
        issues.append(BlunderIssue(
            severity="moderate",
            category="mana_curve",
            description=f"High average CMC: {avg_cmc:.2f}. May struggle in the early game.",
            suggestion="Consider cheaper interaction or cantrips to smooth out the early turns.",
        ))

    return avg_cmc


def _check_color_consistency(main_dict, card_data, land_names, issues):
    """Warn if the deck plays many colors without enough fixing."""
    color_set = set()
    for name, data in card_data.items():
        if name in land_names or not data:
            continue
        colors = data.get("colors")
        if isinstance(colors, str):
            try:
                colors = json.loads(colors)
            except Exception:
                colors = []
        if colors:
            color_set.update(colors)

    land_count = sum(main_dict.get(n, 0) for n in land_names)
    num_colors = len(color_set)

    if num_colors >= 4 and land_count < 22:
        issues.append(BlunderIssue(
            severity="moderate",
            category="color_consistency",
            description=f"{num_colors}-color deck with only {land_count} lands.",
            suggestion="Add more dual lands or fixing to support this many colors reliably.",
        ))
    elif num_colors >= 3 and land_count < 20:
        issues.append(BlunderIssue(
            severity="minor",
            category="color_consistency",
            description=f"{num_colors}-color deck with {land_count} lands — mana may be inconsistent.",
            suggestion="Consider adding mana fixing or trimming to fewer colors.",
        ))


def _check_interaction(main_dict, card_data, land_names, norms, issues):
    """Count interactive spells (removal, counters, bounce)."""
    interaction_keywords = [
        "destroy", "exile target", "counter target", "return target",
        "deals damage to target", "-1/-1", "-2/-2", "-3/-3",
        "sacrifice a", "each opponent loses",
    ]
    interaction_names = []
    for name, data in card_data.items():
        if name in land_names or not data:
            continue
        oracle = (data.get("oracle_text") or "").lower()
        if any(kw in oracle for kw in interaction_keywords):
            interaction_names.append(name)

    interaction_count = sum(main_dict.get(n, 0) for n in interaction_names
                            if n in main_dict)

    if interaction_count < norms["interaction_major"]:
        issues.append(BlunderIssue(
            severity="major",
            category="interaction",
            description=f"Very low interaction: only {interaction_count} interactive spells.",
            suggestion=f"Add at least {norms['interaction_warn']} removal/counter spells.",
            detail="Decks need to answer opponent threats to win consistently.",
        ))
    elif interaction_count < norms["interaction_warn"]:
        issues.append(BlunderIssue(
            severity="moderate",
            category="interaction",
            description=f"Low interaction: {interaction_count} interactive spells.",
            suggestion=f"Consider adding more removal to reach {norms['interaction_warn']}+.",
        ))

    return interaction_count, interaction_names


def _check_win_conditions(main_dict, card_data, land_names, norms, issues):
    """Count threats / win conditions."""
    threat_types = {"Creature", "Planeswalker"}
    threat_names = []
    for name, data in card_data.items():
        if name in land_names or not data:
            continue
        type_line = data.get("type_line") or ""
        if any(t in type_line for t in threat_types):
            threat_names.append(name)

    threat_count = sum(main_dict.get(n, 0) for n in threat_names if n in main_dict)

    if threat_count < norms["threats_major"]:
        issues.append(BlunderIssue(
            severity="major",
            category="win_condition",
            description=f"Only {threat_count} threat cards (creatures + planeswalkers).",
            suggestion="Add more win conditions — the deck needs ways to close out the game.",
        ))
    elif threat_count < norms["threats_warn"]:
        issues.append(BlunderIssue(
            severity="moderate",
            category="win_condition",
            description=f"Low threat density: {threat_count} threats.",
            suggestion="Consider adding more creatures or planeswalkers as win conditions.",
        ))

    return threat_count


def _check_format_legality(main_dict, side_dict, format_name, issues):
    """Flag any cards that are not legal in the specified format."""
    all_cards = set(main_dict) | set(side_dict)
    illegal = []
    for name in all_cards:
        if not is_legal(name, format_name):
            zone = "mainboard" if name in main_dict else "sideboard"
            illegal.append(f"{name} ({zone})")

    if illegal:
        issues.append(BlunderIssue(
            severity="major",
            category="legality",
            description=f"{len(illegal)} card(s) not legal in {format_name.upper()}.",
            suggestion="Replace illegal cards before registering the deck.",
            detail=", ".join(illegal[:10]) + ("..." if len(illegal) > 10 else ""),
        ))


def _check_four_of_consistency(main_dict, issues):
    """Flag decks with low 4-of density for non-land cards (inconsistency signal)."""
    non_land_cards = {n: q for n, q in main_dict.items()}
    if not non_land_cards:
        return
    unique = len(non_land_cards)
    four_ofs = sum(1 for q in non_land_cards.values() if q >= 4)
    ratio = four_ofs / unique if unique else 0

    # Only flag if unique count is large enough to matter
    if unique >= 15 and ratio < 0.15:
        issues.append(BlunderIssue(
            severity="minor",
            category="consistency",
            description=f"Only {four_ofs}/{unique} card types are 4-ofs ({ratio*100:.0f}%).",
            suggestion="Running more 4-of sets improves consistency. Trim singletons.",
        ))


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def analyze_deck(mainboard, sideboard=None, format_name="standard",
                 archetype="Unknown", check_legality=True):
    """
    Analyze a decklist for construction issues.

    Args:
        mainboard:       list[{name, quantity}] or {name: quantity}
        sideboard:       list[{name, quantity}] or {name: quantity} or None
        format_name:     format string (default 'standard')
        archetype:       deck name for display
        check_legality:  whether to call Scryfall legality check (requires enriched data)

    Returns:
        BlunderReport
    """
    main_dict = _to_dict(mainboard)
    side_dict = _to_dict(sideboard or {})
    norms     = _norms(format_name)

    # Fetch Scryfall data for all cards at once (3-tier lookup)
    all_names = list(set(main_dict) | set(side_dict))
    card_data = get_cards_data(all_names)

    issues = []

    # Run all checks
    _check_deck_size(main_dict, side_dict, norms, issues)
    land_count, land_names = _check_land_count(main_dict, card_data, norms, issues)
    land_name_set = set(land_names)
    _check_mana_curve(main_dict, card_data, land_name_set, norms, issues)
    _check_color_consistency(main_dict, card_data, land_name_set, issues)
    _check_interaction(main_dict, card_data, land_name_set, norms, issues)
    _check_win_conditions(main_dict, card_data, land_name_set, norms, issues)
    _check_four_of_consistency(main_dict, issues)
    if check_legality:
        _check_format_legality(main_dict, side_dict, format_name, issues)

    # Score
    raw_score = sum(i.points for i in issues)
    blunder_score = min(raw_score, 100)

    if blunder_score <= 5:
        quality = "Excellent"
    elif blunder_score <= 15:
        quality = "Good"
    elif blunder_score <= 35:
        quality = "Fair"
    else:
        quality = "Poor"

    return BlunderReport(
        archetype=archetype,
        format_name=format_name,
        mainboard_count=sum(main_dict.values()),
        sideboard_count=sum(side_dict.values()),
        blunder_score=blunder_score,
        construction_quality=quality,
        issues=issues,
    )
