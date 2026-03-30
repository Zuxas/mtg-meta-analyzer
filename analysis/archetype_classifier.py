"""
Card-based archetype classifier.

Reads YAML-like config files from config/archetypes/ that define each
archetype by its signature cards (minCopies / exactCopies constraints).

Public API:
    classify_by_cards(card_list, format_name) → str or None
    load_archetype_configs(format_name) → list[dict]

Card list format: {"Card Name": quantity, ...}
"""
import os
import re
from functools import lru_cache

_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "archetypes",
)


def _parse_config(text: str) -> list[dict]:
    """Parse the YAML-like archetype config format into structured dicts.

    Returns: [{"name": str, "strictMode": bool,
               "cards": [{"name": str, "minCopies": int, "exactCopies": int|None}]}]
    """
    archetypes = []
    current = None
    in_cards = False  # inside signatureCards block

    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue

        # Measure indent to distinguish archetype-level vs card-level
        indent = len(line) - len(line.lstrip())

        # Top-level archetype (indent 2, "  - name: ...")
        m = re.match(r'^  - name:\s*(.+)', line)
        if m and indent <= 4:
            if current:
                archetypes.append(current)
            current = {"name": m.group(1).strip().strip('"'), "strictMode": False, "cards": []}
            in_cards = False
            continue

        if current is None:
            continue

        stripped = line.strip()

        # strictMode
        if stripped.startswith("strictMode:"):
            current["strictMode"] = "true" in stripped.lower()
            continue

        # signatureCards: marker
        if stripped == "signatureCards:":
            in_cards = True
            continue

        if in_cards:
            # Card name (deeply indented "      - name: ...")
            m = re.match(r'^\s+- name:\s*(.+)', line)
            if m and indent >= 6:
                current["cards"].append({
                    "name": m.group(1).strip().strip('"'),
                    "minCopies": None,
                    "exactCopies": None,
                })
                continue

            # minCopies / exactCopies (even deeper)
            m = re.match(r'minCopies:\s*(\d+)', stripped)
            if m and current["cards"]:
                current["cards"][-1]["minCopies"] = int(m.group(1))
                continue
            m = re.match(r'exactCopies:\s*(\d+)', stripped)
            if m and current["cards"]:
                current["cards"][-1]["exactCopies"] = int(m.group(1))
                continue

    if current:
        archetypes.append(current)

    return archetypes


@lru_cache(maxsize=10)
def load_archetype_configs(format_name: str) -> list[dict]:
    """Load and parse the archetype config for a format.

    Returns list of archetype defs with name + card constraints.
    """
    path = os.path.join(_CONFIG_DIR, f"{format_name.lower()}.txt")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return _parse_config(f.read())


def classify_by_cards(card_list: dict, format_name: str) -> str | None:
    """Classify a decklist by matching against signature card definitions.

    card_list: {"Card Name": quantity, ...} (mainboard only is fine)
    format_name: "standard", "modern", etc.

    Returns the archetype name of the best match, or None if no match.
    Checks all archetypes and returns the one with the most matching
    signature cards (weighted by constraint specificity).
    """
    configs = load_archetype_configs(format_name)
    if not configs:
        return None

    # Normalize card list keys to lowercase for matching
    cards_lower = {k.lower(): v for k, v in card_list.items()}

    best_name = None
    best_score = 0

    for arch in configs:
        constraints = arch["cards"]
        if not constraints:
            continue

        positive_matched = 0
        positive_total = 0
        failed = False

        for c in constraints:
            card_lower = c["name"].lower()
            qty = cards_lower.get(card_lower, 0)

            if c["exactCopies"] is not None:
                # Pass/fail gate only — does NOT count toward score
                if qty != c["exactCopies"]:
                    failed = True
                    break
            elif c["minCopies"] is not None:
                positive_total += 1
                if qty >= c["minCopies"]:
                    positive_matched += 1
                elif arch.get("strictMode"):
                    failed = True
                    break

        if failed:
            continue

        # Score: fraction of POSITIVE constraints matched (negatives are gates only)
        score = positive_matched / positive_total if positive_total else 0

        if score > best_score:
            best_score = score
            best_name = arch["name"]

    # Require at least 60% of positive signature cards to match
    if best_score >= 0.6:
        return best_name
    return None
