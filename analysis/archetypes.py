"""
Archetype name normalization.

MTGTop8 uses inconsistent naming: "UR Prowess", "Izzet Prowess", "Jeskai Prowess",
"Blue-Red Aggro" etc. may all refer to the same deck. This module maps raw scraper
names to canonical names so analysis is consistent across events and time.

Three layers:
  1. Format pre-normalizer: fixes spacing/hyphen/case differences so
     "Mono-Green Landfall", "MonoGreen Landfall", "monogreen landfall"
     all reduce to the same string before alias lookup.
  2. Exact alias table: hard-coded known mappings (fast, deterministic).
  3. Fuzzy match fallback: uses thefuzz against the canonical name list
     (configurable threshold). Off by default for scraping; opt-in for
     analysis queries.

Card-similarity detection (find_card_based_duplicates):
  Scans the DB for archetype pairs that share both a similar name AND
  a similar mainboard (≥N of 75 cards in common). Safe to run at any time
  — it only reads, never writes. Use --card-similarity in the CLI to review
  and approve merges interactively.

Usage:
    from analysis.archetypes import normalize

    canonical = normalize("UR Prowess")         # -> "Izzet Prowess"
    canonical = normalize("Mono-Green Landfall")# -> "Mono Green Landfall"
    canonical = normalize("Unknown Deck Name")  # -> "Unknown Deck Name" (unchanged)

To add mappings, edit ALIASES below or call register_alias() at runtime.
To rebuild the canonical list from the DB, call build_canonical_list().
"""

import re

from thefuzz import process as fuzz_process


# ---------------------------------------------------------------------------
# Name format pre-normalizer
# Runs BEFORE alias lookup so spelling/punctuation variants collapse to the
# same key without requiring a separate alias entry for every permutation.
# ---------------------------------------------------------------------------

# Two-letter guild abbreviations → canonical guild name
_GUILD_MAP = {
    "uw": "Azorius",  "wu": "Azorius",
    "ub": "Dimir",    "bu": "Dimir",
    "br": "Rakdos",   "rb": "Rakdos",
    "rg": "Gruul",    "gr": "Gruul",
    "gw": "Selesnya", "wg": "Selesnya",
    "wb": "Orzhov",   "bw": "Orzhov",
    "ur": "Izzet",    "ru": "Izzet",
    "bg": "Golgari",  "gb": "Golgari",
    "rw": "Boros",    "wr": "Boros",
    "gu": "Simic",    "ug": "Simic",
}

# Three-letter shard/wedge abbreviations → canonical name
_SHARD_MAP = {
    "uwr": "Jeskai", "wur": "Jeskai", "rwu": "Jeskai",
    "brw": "Mardu",  "rwb": "Mardu",  "wbr": "Mardu",
    "bgu": "Sultai", "ugb": "Sultai", "gub": "Sultai",
    "gwu": "Bant",   "wug": "Bant",   "ugw": "Bant",
    "rgw": "Naya",   "grw": "Naya",   "wrg": "Naya",
    "ubr": "Grixis", "bru": "Grixis", "rub": "Grixis",
    "urb": "Grixis",
}


def _fix_mono_prefix(name: str) -> str:
    """'MonoRed', 'Mono-Red', 'mono red' -> 'Mono Red'"""
    return re.sub(
        r'\bmono[-\s]?([a-z])',
        lambda m: "Mono " + m.group(1).upper(),
        name,
        flags=re.IGNORECASE,
    )


def _expand_color_abbrev(name: str) -> str:
    """
    Replace leading two/three-letter color abbreviations with guild/shard names.
    e.g. 'UR Prowess' -> 'Izzet Prowess', 'UWR Control' -> 'Jeskai Control'
    Only replaces when the abbreviation appears as a standalone word token.
    """
    def _replace(m):
        token = m.group(1).lower()
        return _SHARD_MAP.get(token) or _GUILD_MAP.get(token) or m.group(1)

    # Three-letter first (more specific), then two-letter
    name = re.sub(r'\b([A-Za-z]{3})\b', _replace, name)
    name = re.sub(r'\b([A-Za-z]{2})\b', _replace, name)
    return name


def pre_normalize(name: str) -> str:
    """
    Light formatting clean-up applied before alias lookup.
    Does NOT rename decks — only standardises spacing/case/abbreviations
    so that 'Mono-Green Landfall', 'MonoGreen landfall', 'mono green landfall'
    all produce the same string.
    """
    if not name:
        return name
    # Title-case
    result = name.strip().title()
    # Fix apostrophe casing: title() turns "Goryo's" into "Goryo'S"
    result = re.sub(r"'([A-Z])", lambda m: "'" + m.group(1).lower(), result)
    # Fix Mono prefix ("Mono-Green" -> "Mono Green", "Monogreen" -> "Mono Green")
    result = _fix_mono_prefix(result)
    # Expand color abbreviations in leading position
    result = _expand_color_abbrev(result)
    # Collapse multiple spaces
    result = re.sub(r' {2,}', ' ', result).strip()
    return result


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
    "izzet spells":            "Izzet Prowess",

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

    # --- Pioneer / Modern additions ---
    "rakdos midrange":         "Rakdos Midrange",
    "br midrange":             "Rakdos Midrange",
    "black red midrange":      "Rakdos Midrange",

    "lotus field":             "Lotus Combo",
    "lotus combo":             "Lotus Combo",

    "humans":                  "5C Humans",
    "5c humans":               "5C Humans",
    "five color humans":       "5C Humans",
    "five-color humans":       "5C Humans",

    "living end":              "Living End",
    "cascade living end":      "Living End",

    "rhinos":                  "Temur Rhinos",
    "temur rhinos":            "Temur Rhinos",
    "crashing footfalls":      "Temur Rhinos",

    # --- WUBRG color-code patterns (melee.gg) ---
    "w-u-b-g goryo's vengeance": "Goryo's Vengeance",
    "w-u-b-g goryo'S vengeance": "Goryo's Vengeance",
    "w-u-b-g overlords":       "Four-Color Overlords",
    "w-u-b-g beanstalk":       "Four-Color Beanstalk",
    "w-u-b-g":                 "Four-Color",
    "w-u-r-g domain":          "Four-Color Domain",
    "w-u-r-g aggro":           "Four-Color Aggro",
    "w-u-r-g":                 "Four-Color",
    "w-u-b-r control":         "Four-Color Control",
    "w-u-b-r":                 "Four-Color",
    "w-r-b-g":                 "Four-Color",

    # --- Five-Color standardization ---
    "five-color bring to light": "5C Bring To Light",
    "five-color landfall":     "5C Landfall",
    "five-color niv-mizzet":   "5C Niv-Mizzet",
    "five-color ramp":         "5C Ramp",
    "five-color combo":        "5C Combo",
    "five-color control":      "5C Control",

    # --- Apostrophe fixes ---
    "goryo's":                 "Goryo's Vengeance",
    "esper goryo's":           "Goryo's Vengeance",

    # --- Additional Standard aliases ---
    "4/5c control":            "Four-Color Control",
    "izzet soul cauldron":     "Izzet Cauldron",
    "ur soul cauldron":        "Izzet Cauldron",
    "izzet aggro":             "Izzet Aggro",
    "ur aggro":                "Izzet Aggro",
    "izzet control":           "Izzet Control",
    "ur control":              "Izzet Control",
    "azorius aggro":           "Azorius Aggro",
    "uw aggro":                "Azorius Aggro",

    # --- Modern: Amulet Titan (splash variants → canonical) ---
    "simic amulet titan":      "Amulet Titan",
    "selesnya amulet titan":   "Amulet Titan",
    "naya amulet titan":       "Amulet Titan",
    "izzet amulet titan":      "Amulet Titan",
    "grixis amulet titan":     "Amulet Titan",
    "jund amulet titan":       "Amulet Titan",
    "orzhov amulet titan":     "Amulet Titan",
    "golgari amulet titan":    "Amulet Titan",
    "esper amulet titan":      "Amulet Titan",
    "azorius amulet titan":    "Amulet Titan",

    # --- Modern: Eldrazi / Tron family ---
    "colorless eldrazi tron":  "Eldrazi Tron",
    "colorless eldrazi":       "Eldrazi Tron",
    "mono green tron":         "Eldrazi Tron",
    "colorless tron":          "Eldrazi Tron",
    "colorless":               "Eldrazi Tron",

    # --- Modern: Goryo's Vengeance (color labels → canonical) ---
    "esper goryo's vengeance":        "Goryo's Vengeance",
    "four-color goryo's vengeance":   "Goryo's Vengeance",
    "grixis goryo's vengeance":       "Goryo's Vengeance",
    "4c goryo's":                     "Goryo's Vengeance",
    "4cc goryo's":                    "Goryo's Vengeance",

    # --- Modern: Murktide (Dimir is canonical) ---
    "izzet murktide":          "Dimir Murktide",
    "grixis murktide":         "Dimir Murktide",

    # --- Modern: Affinity (Izzet is canonical) ---
    "affinity":                "Izzet Affinity",
    "jeskai affinity":         "Izzet Affinity",
    "azorius affinity":        "Izzet Affinity",
    "grixis affinity":         "Izzet Affinity",
    "abzan affinity":          "Izzet Affinity",
    "boros affinity":          "Izzet Affinity",
    "w-u-r-g affinity":        "Izzet Affinity",
    "temur affinity":          "Izzet Affinity",
    "mono green affinity":     "Izzet Affinity",
    "simic affinity":          "Izzet Affinity",
    "orzhov affinity":         "Izzet Affinity",
    "gruul affinity":          "Izzet Affinity",
    "wurg affinity":           "Izzet Affinity",
    "wbrg affinity":           "Izzet Affinity",
    "w-u-b-g affinity":        "Izzet Affinity",
    "bant affinity":           "Izzet Affinity",
    "mardu affinity":          "Izzet Affinity",
    "mono red affinity":       "Izzet Affinity",
    "affinity neoform":        "Izzet Affinity",

    # --- Modern: Neoform (Simic is canonical) ---
    "neoform":                 "Simic Neoform",
    "w-u-b-r-g neoform":      "Simic Neoform",
    "jeskai neoform":          "Simic Neoform",
    "bant neoform":            "Simic Neoform",
    "temur neoform":           "Simic Neoform",

    # --- Modern: Merfolk ---
    "mono blue merfolk":       "Merfolk",
    "simic merfolk":           "Merfolk",

    # --- Modern: Burn ---
    "boros burn":              "Burn",
    "mono red burn":           "Burn",

    # --- Modern: 8-Rack ---
    "10-rack":                 "8-Rack",
    "mono black 8-rack":       "8-Rack",
    "orzhov 8-rack":           "8-Rack",

    # --- Modern: Birthing Ritual (Simic is canonical) ---
    "abzan birthing ritual":   "Simic Birthing Ritual",
    "jund birthing ritual":    "Simic Birthing Ritual",

    # --- Modern: Grinding Breach variants ---
    "esper grinding breach":   "Grinding Breach",
    "grixis grinding breach":  "Grinding Breach",
    "bant grinding breach":    "Grinding Breach",

    # --- Standard consolidations ---
    "domain overlords":        "Four-Color Overlords",
    "sultai beanstalk":        "Four-Color Beanstalk",
    "azorius midrange":        "Azorius Control",

    # --- Legacy: Reanimator (Dimir is canonical) ---
    "w-u-b-g reanimator":      "Dimir Reanimator",
    "reanimator":              "Dimir Reanimator",
    "jund reanimator":         "Dimir Reanimator",
    "rakdos reanimator":       "Dimir Reanimator",
    "golgari reanimator":      "Dimir Reanimator",
    "w-u-b-r-g reanimator":    "Dimir Reanimator",
    "colorless reanimator":    "Dimir Reanimator",

    # --- Legacy: Cephalid Breakfast ---
    "w-u-b-g cephalid breakfast": "Cephalid Breakfast",
    "esper cephalid breakfast":   "Cephalid Breakfast",
    "w-u-b-g cephalid breakfast (yorion)": "Cephalid Breakfast",
    "sultai cephalid breakfast":  "Cephalid Breakfast",
    "colorless cephalid breakfast": "Cephalid Breakfast",
    "cephalid breakfast (yorion)": "Cephalid Breakfast",
    "nadu breakfast":             "Cephalid Breakfast",

    # --- Legacy: Sneak And Show ---
    "w-u-b-r-g sneak and show":  "Sneak And Show",
    "w-u-b-g sneak and show":    "Sneak And Show",
    "simic show and tell":       "Sneak And Show",
    "colorless sneak and show":  "Sneak And Show",
    "dimir show and tell":       "Sneak And Show",

    # --- Legacy: Omni-Tell ---
    "w-u-b-g omni-tell":        "Omni-Tell",
    "w-u-b-r-g omni-tell":      "Omni-Tell",

    # --- Legacy: Death And Taxes (consolidate color splashes) ---
    "orzhov death and taxes (yorion)": "Death And Taxes",
    "orzhov death and taxes":    "Death And Taxes",
    "death and taxes (yorion)":  "Death And Taxes",
    "mardu death and taxes":     "Death And Taxes",
    "colorless death and taxes (yorion)": "Death And Taxes",
    "abzan death and taxes":     "Death And Taxes",
    "abzan death and taxes (yorion)": "Death And Taxes",

    # --- Legacy: Doomsday (all variants → canonical) ---
    "sultai doomsday":           "Doomsday",
    "dimir tempo doomsday":      "Doomsday",
    "dimir doomsday":            "Doomsday",
    "esper doomsday":            "Doomsday",
    "sultai tempo doomsday":     "Doomsday",
    "nbc doomsday":              "Doomsday",
    "w-u-b-r-g doomsday":        "Doomsday",

    # --- Legacy: Storm variants ---
    "u-b-r-g the epic storm":   "The Epic Storm",
    "storm":                    "The Epic Storm",
    "u-b-r-g beseech storm":    "Beseech Storm",
    "rakdos beseech storm":     "Beseech Storm",

    # --- Legacy: Oops All Spells ---
    "u-b-r-g oops! all spells": "Oops! All Spells",

    # --- Legacy: WUBRG generic codes ---
    "w-u-b-r-g":               "5C Control",
    "u-b-r-g":                 "Four-Color",
    "w-u-r-g beanstalk":       "Four-Color Beanstalk",

    # --- Pauper: Affinity (Grixis is canonical) ---
    "esper affinity":          "Grixis Affinity",
    "dimir affinity":          "Grixis Affinity",
    "rakdos affinity":         "Grixis Affinity",
    "jund affinity":           "Grixis Affinity",
    "mono blue affinity":      "Grixis Affinity",
    "w-u-b-r affinity":       "Grixis Affinity",
    "colorless affinity":      "Grixis Affinity",

    # --- Pauper: Bogles (Selesnya is canonical) ---
    "naya bogles":             "Selesnya Bogles",
    "bant bogles":             "Selesnya Bogles",
    "w-u-r-g bogles":         "Selesnya Bogles",
    "golgari bogles":          "Selesnya Bogles",
    "abzan bogles":            "Selesnya Bogles",
    "azorius bogles":          "Selesnya Bogles",
    "mono white bogles":       "Selesnya Bogles",

    # --- Pauper: Elves (Mono Green is canonical) ---
    "golgari elves":           "Mono Green Elves",
    "temur elves":             "Mono Green Elves",
    "w-u-b-g elves":           "Mono Green Elves",
    "w-u-b-r-g elves":         "Mono Green Elves",
    "sultai elves":            "Mono Green Elves",
    "gruul elves":             "Mono Green Elves",
    "w-u-r-g elves":           "Mono Green Elves",

    # --- Pauper: Slivers → 5C Slivers ---
    "w-u-b-r-g slivers":      "5C Slivers",
    "w-u-r-g slivers":        "5C Slivers",
    "naya slivers":            "5C Slivers",
    "abzan slivers":           "5C Slivers",
    "boros slivers":           "5C Slivers",
    "grixis slivers":          "5C Slivers",
    "golgari slivers":         "5C Slivers",
    "bant slivers":            "5C Slivers",

    # --- Pauper: Dredge → Jund Dredge ---
    "w-b-r-g dredge":         "Jund Dredge",
    "u-b-r-g dredge":         "Jund Dredge",
    "golgari dredge":          "Jund Dredge",
    "mono red dredge":         "Jund Dredge",
    "grixis dredge":           "Jund Dredge",
    "abzan dredge":            "Jund Dredge",
    "rakdos dredge":           "Jund Dredge",

    # --- Pauper: WUBRG generic codes ---
    "w-u-b-r cycle storm":    "Cycle Storm",
    "u-b-r-g poison storm":   "Poison Storm",
    "u-b-r-g turbo fog":      "Turbo Fog",
    "w-u-r-g tron":           "Four-Color Tron",
    "w-u-b-r-g tron":         "5C Tron",
    "u-b-r-g tron":           "Four-Color Tron",
    "w-b-r-g synthesizer":    "Four-Color Synthesizer",
    "w-u-b-r caw-gates":      "Four-Color Caw-Gates",
    "w-u-b-r-g aggro":        "5C Aggro",
    "u-b-r-g reanimator":     "Four-Color Reanimator",

    # --- Junk entries (map to empty so they're recognized as bad) ---
    "decklist":                "",
    "all other decklists":     "",
    "rogue decklists":         "",
    "others":                  "",
    "other":                   "",
}

# Reverse lookup: canonical -> canonical (so we don't change already-canonical names)
_CANONICAL_NAMES = {v for v in ALIASES.values() if v}


def register_alias(raw_name, canonical_name):
    """Add a mapping at runtime (affects this process only)."""
    ALIASES[raw_name.lower().strip()] = canonical_name
    _CANONICAL_NAMES.add(canonical_name)


def normalize(raw_name, fuzzy=False, fuzzy_threshold=85):
    """
    Return the canonical archetype name for raw_name.

    Steps:
      1. Pre-normalize formatting (spacing, hyphens, color abbreviations).
      2. If the result is already a canonical name, return as-is.
      3. Check the ALIASES table (case-insensitive exact match).
      4. If fuzzy=True, try fuzzy matching against canonical names
         (only if score >= fuzzy_threshold).
      5. Otherwise return the pre-normalized name.

    fuzzy=False by default — fuzzy matching is only for analysis queries
    where you want to resolve user input, not for the scraper (where
    false positives would silently corrupt data).
    """
    if not raw_name:
        return raw_name

    stripped = pre_normalize(raw_name.strip())

    # Already canonical
    if stripped in _CANONICAL_NAMES:
        return stripped

    # Exact alias match (case-insensitive)
    key = stripped.lower()
    if key in ALIASES:
        mapped = ALIASES[key]
        return mapped if mapped else stripped  # empty alias = keep original (junk label)

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


def apply_normalization(dry_run=False, fuzzy=False, fuzzy_threshold=85):
    """
    Retroactive migration: update decks.archetype for all known aliases.

    For each distinct archetype name in the DB, if normalize() returns a different
    canonical name, UPDATE all matching rows.

    Args:
        dry_run:         Print changes without modifying the DB.
        fuzzy:           Also apply fuzzy matching (higher false-positive risk).
        fuzzy_threshold: Minimum fuzzy score to apply (default 85).

    Returns:
        dict with 'mapped', 'skipped', 'total', 'changes' keys.
    """
    from db.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT archetype, COUNT(*) as cnt FROM decks "
            "WHERE archetype IS NOT NULL AND archetype != '' "
            "GROUP BY archetype ORDER BY cnt DESC"
        ).fetchall()

    changes = []
    skipped = 0
    for row in rows:
        raw = row["archetype"]
        canonical = normalize(raw, fuzzy=fuzzy, fuzzy_threshold=fuzzy_threshold)
        if canonical != raw:
            changes.append((raw, canonical, row["cnt"]))
        else:
            skipped += 1

    if not changes:
        print("  No archetype mappings to apply.")
        return {"mapped": 0, "skipped": skipped, "total": len(rows), "changes": []}

    print(f"\n  {'DRY RUN — ' if dry_run else ''}Archetype normalization: "
          f"{len(changes)} mappings, {skipped} already canonical\n")

    for raw, canonical, cnt in changes:
        print(f"  {raw!r:<40} -> {canonical!r}  ({cnt} decks)")

    if not dry_run:
        print()
        with get_connection() as conn:
            for raw, canonical, _ in changes:
                conn.execute(
                    "UPDATE decks SET archetype=? WHERE archetype=?",
                    (canonical, raw)
                )
        print(f"  Applied {len(changes)} mappings to active DB.")
    else:
        print(f"\n  (Dry run — no changes made. Run with --apply to commit.)")

    return {
        "mapped": len(changes),
        "skipped": skipped,
        "total": len(rows),
        "changes": changes,
    }


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


# ---------------------------------------------------------------------------
# Card-similarity duplicate detection
# ---------------------------------------------------------------------------

def _get_core_cards(conn, archetype: str, format_name: str,
                    min_inclusion: float = 0.10) -> set:
    """
    Return the set of mainboard card names that appear in at least
    min_inclusion fraction of this archetype's decks in the given format.
    """
    total_row = conn.execute("""
        SELECT COUNT(DISTINCT d.id) AS cnt
        FROM decks d
        JOIN events e ON e.id = d.event_id
        WHERE lower(d.archetype) = lower(?) AND lower(e.format) = lower(?)
    """, (archetype, format_name)).fetchone()
    total = total_row["cnt"] if total_row else 0
    if total == 0:
        return set()

    card_rows = conn.execute("""
        SELECT c.name, COUNT(DISTINCT d.id) AS appearances
        FROM decks d
        JOIN events e ON e.id = d.event_id
        JOIN deck_cards dc ON dc.deck_id = d.id
        JOIN cards c ON c.id = dc.card_id
        WHERE lower(d.archetype) = lower(?)
          AND lower(e.format) = lower(?)
          AND dc.is_sideboard = 0
        GROUP BY c.name
        HAVING CAST(appearances AS REAL) / ? >= ?
    """, (archetype, format_name, total, min_inclusion)).fetchall()

    return {r["name"] for r in card_rows}


def find_card_based_duplicates(
    format_name: str = "standard",
    name_threshold: int = 60,
    card_overlap: float = 0.67,
    min_decks: int = 3,
) -> list:
    """
    Find archetype pairs that are likely the same deck under different names.

    An archetype pair is flagged when BOTH conditions are true:
      1. Their names have a fuzzy similarity score >= name_threshold
      2. shared_cards / max(|core_a|, |core_b|) >= card_overlap

    The default card_overlap of 0.67 approximates "50 of 75 cards in common".
    Core sets are computed at 10% inclusion (cards in >=10% of that archetype's
    decklists), matching the same threshold used in archetype detail views.

    Args:
        format_name:     Format to search in.
        name_threshold:  Minimum thefuzz name similarity score (0-100).
        card_overlap:    Minimum ratio of shared cards (0.0-1.0, default 0.67).
        min_decks:       Ignore archetypes with fewer than this many decks.

    Returns:
        List of dicts, sorted by card overlap descending:
        {
            "arch_a":        str,
            "arch_b":        str,
            "name_score":    int,
            "shared_cards":  int,
            "cards_a":       int,   # size of arch_a's core set
            "cards_b":       int,   # size of arch_b's core set
            "shared_names":  set,   # the actual overlapping card names
            "suggestion":    str,   # recommended canonical name
        }
    """
    from db.database import get_connection

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT d.archetype, COUNT(DISTINCT d.id) AS cnt
            FROM decks d
            JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?)
              AND d.archetype IS NOT NULL AND d.archetype != ''
            GROUP BY d.archetype
            HAVING cnt >= ?
            ORDER BY cnt DESC
        """, (format_name, min_decks)).fetchall()

    archetypes = [r["archetype"] for r in rows]
    if len(archetypes) < 2:
        return []

    # Step 1: find name-similar pairs (fast, no DB needed)
    candidate_pairs = []
    checked = set()
    for i, arch_a in enumerate(archetypes):
        for arch_b in archetypes[i + 1:]:
            key = (min(arch_a, arch_b), max(arch_a, arch_b))
            if key in checked:
                continue
            checked.add(key)
            from thefuzz import fuzz
            score = fuzz.token_sort_ratio(arch_a.lower(), arch_b.lower())
            if score >= name_threshold:
                candidate_pairs.append((arch_a, arch_b, score))

    if not candidate_pairs:
        return []

    # Step 2: load card sets only for candidate archetypes
    needed = {arch for pair in candidate_pairs for arch in pair[:2]}
    with get_connection() as conn:
        core_cache = {
            arch: _get_core_cards(conn, arch, format_name)
            for arch in needed
        }

    # Step 3: compute card overlap for each candidate pair
    results = []
    for arch_a, arch_b, name_score in candidate_pairs:
        core_a = core_cache.get(arch_a, set())
        core_b = core_cache.get(arch_b, set())
        if not core_a or not core_b:
            continue
        shared = core_a & core_b
        ratio = len(shared) / max(len(core_a), len(core_b)) if (core_a and core_b) else 0
        if ratio >= card_overlap:
            # Pick the canonical suggestion: prefer the name that is longer /
            # more descriptive, or whichever already exists in the alias table.
            norm_a = normalize(arch_a)
            norm_b = normalize(arch_b)
            if norm_a != arch_a:
                suggestion = norm_a
            elif norm_b != arch_b:
                suggestion = norm_b
            else:
                # Pick the more common one (first in list = higher deck count)
                suggestion = arch_a
            results.append({
                "arch_a":        arch_a,
                "arch_b":        arch_b,
                "name_score":    name_score,
                "shared_cards":  len(shared),
                "overlap_ratio": round(ratio, 2),
                "cards_a":       len(core_a),
                "cards_b":       len(core_b),
                "shared_names":  shared,
                "suggestion":    suggestion,
            })

    return sorted(results, key=lambda r: -r["shared_cards"])


def merge_archetypes(keep: str, remove: str) -> int:
    """
    Rename all decks with archetype `remove` to `keep` in the active DB.
    Returns the number of rows updated.
    """
    from db.database import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE decks SET archetype = ? WHERE archetype = ?",
            (keep, remove)
        )
        updated = conn.execute(
            "SELECT changes() AS n"
        ).fetchone()["n"]
    return updated


if __name__ == "__main__":
    import argparse
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Apply archetype alias normalization to existing DB records"
    )
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes to the DB (default is dry run)")
    parser.add_argument("--fuzzy", action="store_true",
                        help="Also apply fuzzy matching (higher false-positive risk)")
    parser.add_argument("--fuzzy-threshold", type=int, default=85,
                        help="Fuzzy score cutoff 0-100 (default 85)")
    parser.add_argument("--card-similarity", action="store_true",
                        help="Find duplicates by name similarity + card overlap and "
                             "prompt to merge interactively")
    parser.add_argument("--format", default="standard",
                        help="Format for --card-similarity (default: standard)")
    parser.add_argument("--name-threshold", type=int, default=60,
                        help="Min name fuzzy score for --card-similarity (default 60)")
    parser.add_argument("--card-overlap", type=float, default=0.67,
                        help="Min card overlap ratio 0-1 for --card-similarity (default 0.67 ≈ 50/75)")
    parser.add_argument("--pre-normalize", action="store_true",
                        help="Show how pre_normalize() would reformat all DB archetype names")
    args = parser.parse_args()

    if args.pre_normalize:
        names = build_canonical_list()
        changes = [(n, pre_normalize(n)) for n in names if pre_normalize(n) != n]
        if not changes:
            print("No formatting changes needed.")
        else:
            print(f"{len(changes)} names would be reformatted:\n")
            for raw, fixed in changes:
                print(f"  {raw!r:<45} -> {fixed!r}")
        sys.exit(0)

    if args.card_similarity:
        print(f"Scanning {args.format} for card-based duplicates "
              f"(name>={args.name_threshold}, overlap>={args.card_overlap})…\n")
        dupes = find_card_based_duplicates(
            format_name=args.format,
            name_threshold=args.name_threshold,
            card_overlap=args.card_overlap,
        )
        if not dupes:
            print("No duplicate pairs found with those thresholds.")
            sys.exit(0)

        print(f"Found {len(dupes)} potential duplicate pair(s):\n")
        merged = 0
        for i, d in enumerate(dupes, 1):
            print(f"  [{i}/{len(dupes)}]")
            print(f"    A: {d['arch_a']!r}  ({d['cards_a']} core cards)")
            print(f"    B: {d['arch_b']!r}  ({d['cards_b']} core cards)")
            print(f"    Name similarity : {d['name_score']}/100")
            print(f"    Card overlap    : {d['shared_cards']} cards  ({d['overlap_ratio']*100:.0f}%)")
            sample = sorted(d['shared_names'])[:8]
            print(f"    Sample overlap  : {', '.join(sample)}"
                  + (" …" if len(d['shared_names']) > 8 else ""))
            print(f"    Suggested name  : {d['suggestion']!r}")
            if args.apply:
                ans = input("    Merge? [y/N/custom name]: ").strip()
                if ans.lower() == "y":
                    keep = d["suggestion"]
                    remove = d["arch_b"] if keep == d["arch_a"] else d["arch_a"]
                    n = merge_archetypes(keep, remove)
                    print(f"    -> Merged {n} decks from {remove!r} into {keep!r}")
                    merged += 1
                elif ans and ans.lower() != "n":
                    # User typed a custom canonical name
                    keep = ans.strip()
                    for remove in (d["arch_a"], d["arch_b"]):
                        if remove != keep:
                            n = merge_archetypes(keep, remove)
                            print(f"    -> Renamed {n} decks: {remove!r} -> {keep!r}")
                    merged += 1
                else:
                    print("    Skipped.")
            print()
        if args.apply:
            print(f"Done. {merged}/{len(dupes)} pairs merged.")
        else:
            print("Dry run — pass --apply to merge interactively.")
        sys.exit(0)

    apply_normalization(
        dry_run=not args.apply,
        fuzzy=args.fuzzy,
        fuzzy_threshold=args.fuzzy_threshold,
    )
