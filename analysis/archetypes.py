"""
Archetype name normalization.

MTGTop8 uses inconsistent naming: "UR Prowess", "Izzet Prowess", "Jeskai Prowess",
"Blue-Red Aggro" etc. may all refer to the same deck. This module maps raw scraper
names to canonical names so analysis is consistent across events and time.

Two layers:
  1. Exact alias table: hard-coded known mappings (fast, deterministic).
  2. Fuzzy match fallback: uses thefuzz against the canonical name list (configurable
     threshold). Off by default for scraping; opt-in for analysis queries.

Usage:
    from analysis.archetypes import normalize

    canonical = normalize("UR Prowess")         # -> "Izzet Prowess"
    canonical = normalize("Unknown Deck Name")  # -> "Unknown Deck Name" (unchanged)

To add mappings, edit ALIASES below or call register_alias() at runtime.
To rebuild the canonical list from the DB, call build_canonical_list().
"""

from thefuzz import process as fuzz_process


# ---------------------------------------------------------------------------
# Alias table
# Format:  "raw name (lowercase)": "Canonical Name"
# Keep entries lowercase on the left side so matching is case-insensitive.
# ---------------------------------------------------------------------------

ALIASES = {
    # --- Izzet / UR Prowess ---
    "ur prowess":              "Izzet Prowess",
    "blue red prowess":        "Izzet Prowess",
    "blue-red prowess":        "Izzet Prowess",
    "izzet aggro":             "Izzet Prowess",
    "izzet spells":            "Izzet Prowess",
    "ur aggro":                "Izzet Prowess",

    # --- Mono Red Aggro ---
    "red deck wins":           "Mono Red Aggro",
    "rdw":                     "Mono Red Aggro",
    "mono-red aggro":          "Mono Red Aggro",
    "mono red":                "Mono Red Aggro",

    # --- Azorius Control ---
    "uw control":              "Azorius Control",
    "white blue control":      "Azorius Control",
    "white-blue control":      "Azorius Control",
    "azorius tempo":           "Azorius Control",

    # --- Dimir Midrange ---
    "ub midrange":             "Dimir Midrange",
    "blue black midrange":     "Dimir Midrange",
    "blue-black midrange":     "Dimir Midrange",
    "dimir control":           "Dimir Midrange",

    # --- Domain Ramp ---
    "5c ramp":                 "Domain Ramp",
    "five color ramp":         "Domain Ramp",
    "5 color ramp":            "Domain Ramp",
    "domain":                  "Domain Ramp",
    "naya domain":             "Domain Ramp",

    # --- Mono Green Aggro / Stompy ---
    "green stompy":            "Mono Green Aggro",
    "mono-green aggro":        "Mono Green Aggro",
    "mono green stompy":       "Mono Green Aggro",
    "green aggro":             "Mono Green Aggro",

    # --- Jeskai Control ---
    "uwr control":             "Jeskai Control",
    "jeskai tempo":            "Jeskai Control",

    # --- Boros Aggro ---
    "rw aggro":                "Boros Aggro",
    "red white aggro":         "Boros Aggro",
    "red-white aggro":         "Boros Aggro",

    # --- Gruul Aggro ---
    "rg aggro":                "Gruul Aggro",
    "red green aggro":         "Gruul Aggro",
    "gruul monsters":          "Gruul Aggro",

    # --- Pioneer / Modern additions can go here ---
    "rakdos midrange":         "Rakdos Midrange",
    "br midrange":             "Rakdos Midrange",
    "black red midrange":      "Rakdos Midrange",

    "lotus field":             "Lotus Combo",
    "lotus combo":             "Lotus Combo",

    "humans":                  "5C Humans",
    "5c humans":               "5C Humans",
    "five color humans":       "5C Humans",

    "living end":              "Living End",
    "cascade living end":      "Living End",

    "rhinos":                  "Temur Rhinos",
    "temur rhinos":            "Temur Rhinos",
    "crashing footfalls":      "Temur Rhinos",
}

# Reverse lookup: canonical -> canonical (so we don't change already-canonical names)
_CANONICAL_NAMES = set(ALIASES.values())


def register_alias(raw_name, canonical_name):
    """Add a mapping at runtime (affects this process only)."""
    ALIASES[raw_name.lower().strip()] = canonical_name
    _CANONICAL_NAMES.add(canonical_name)


def normalize(raw_name, fuzzy=False, fuzzy_threshold=85):
    """
    Return the canonical archetype name for raw_name.

    Steps:
      1. If raw_name is already a canonical name, return as-is.
      2. Check the ALIASES table (case-insensitive exact match).
      3. If fuzzy=True, try fuzzy matching against canonical names
         (only if score >= fuzzy_threshold).
      4. Otherwise return raw_name unchanged.

    fuzzy=False by default — fuzzy matching is only for analysis queries
    where you want to resolve user input, not for the scraper (where
    false positives would silently corrupt data).
    """
    if not raw_name:
        return raw_name

    stripped = raw_name.strip()

    # Already canonical
    if stripped in _CANONICAL_NAMES:
        return stripped

    # Exact alias match (case-insensitive)
    key = stripped.lower()
    if key in ALIASES:
        return ALIASES[key]

    # Fuzzy match (opt-in)
    if fuzzy and _CANONICAL_NAMES:
        result = fuzz_process.extractOne(
            stripped,
            list(_CANONICAL_NAMES),
            score_cutoff=fuzzy_threshold
        )
        if result:
            return result[0]

    return stripped


def normalize_batch(names, fuzzy=False, fuzzy_threshold=85):
    """Normalize a list of names. Returns {raw: canonical}."""
    return {n: normalize(n, fuzzy=fuzzy, fuzzy_threshold=fuzzy_threshold) for n in names}


def build_canonical_list():
    """
    Return a sorted list of all archetype names currently in the active DB.
    Useful for seeding the fuzzy matcher with real data.
    """
    from db.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT archetype FROM decks WHERE archetype != '' ORDER BY archetype"
        ).fetchall()
    return [r["archetype"] for r in rows]


def suggest_aliases(threshold=80):
    """
    Scan the DB for archetype names that are likely duplicates.
    Groups names by fuzzy similarity and returns suggestions.
    Returns list of (canonical_candidate, [similar_names], max_score).
    Useful for discovering new aliases to add to the table.
    """
    names = build_canonical_list()
    if len(names) < 2:
        return []

    visited  = set()
    groups   = []

    for name in names:
        if name in visited:
            continue
        matches = fuzz_process.extract(name, names, limit=10)
        similar = [
            m[0] for m in matches
            if m[1] >= threshold and m[0] != name and m[0] not in visited
        ]
        if similar:
            all_in_group = [name] + similar
            visited.update(all_in_group)
            groups.append((name, similar, max(m[1] for m in matches if m[0] in similar)))

    return sorted(groups, key=lambda g: -g[2])
