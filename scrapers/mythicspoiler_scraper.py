"""
Scraper for Mythic Spoiler (https://mythicspoiler.com)

Fetches the card list for a given set code, then enriches each card with
full metadata (mana cost, type, rules text) from the local Scryfall bulk
file.  Mythic Spoiler's individual card pages are empty templates for sets
from 2022 onward, so we only use the site for discovering which cards are
in a set — Scryfall provides the actual card data.

Usage:
    from scrapers.mythicspoiler_scraper import fetch_set_cards
    cards = fetch_set_cards("TDM")
"""

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://mythicspoiler.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

DELAY = 1.0

# ── Known set code → display name mapping ──────────────────────────────
# Used for the UI dropdown and to resolve set code → mythicspoiler URL.
# Keys are uppercase WotC set codes; values are (display_name, release_date).
KNOWN_SETS = {
    # Standard-legal (current rotation)
    "DSK": ("Duskmourn: House of Horror", "2024-09-27"),
    "FDN": ("Foundations", "2024-11-15"),
    "AET": ("Aetherdrift", "2025-02-14"),
    "TDM": ("Tarkir: Dragonstorm", "2025-04-11"),
    "EOE": ("Edge of Eternities", "2025-07-25"),
    "LWN": ("Lorwyn Eclipsed", "2025-09-26"),
    # Recent Pioneer-legal
    "OTJ": ("Outlaws of Thunder Junction", "2024-04-19"),
    "MKM": ("Murders at Karlov Manor", "2024-02-09"),
    "LCI": ("The Lost Caverns of Ixalan", "2023-11-17"),
    "WOE": ("Wilds of Eldraine", "2023-09-08"),
    "MOM": ("March of the Machine", "2023-04-21"),
    "ONE": ("Phyrexia: All Will Be One", "2023-02-10"),
    "BRO": ("The Brothers' War", "2022-11-18"),
    "DMU": ("Dominaria United", "2022-09-09"),
    "SNC": ("Streets of New Capenna", "2022-04-29"),
    "NEO": ("Kamigawa: Neon Dynasty", "2022-02-18"),
    "VOW": ("Innistrad: Crimson Vow", "2021-11-19"),
    "MID": ("Innistrad: Midnight Hunt", "2021-09-24"),
    # Modern Horizons
    "MH3": ("Modern Horizons 3", "2024-06-14"),
    "MH2": ("Modern Horizons 2", "2021-06-18"),
}


# ── Format legality table ──────────────────────────────────────────────
# Which sets are legal in which 60-card constructed formats.

# Standard: rolling window of recent sets
STANDARD_LEGAL_SETS = {
    "DSK", "FDN", "AET", "TDM",
    "EOE",  # upcoming July 2025
    "LWN",  # upcoming Sept 2025
}

# Sets that are explicitly NOT legal in any 60-card constructed format
NON_CONSTRUCTED_PREFIXES = {
    "UN",   # Un-sets (UNH, UNF, UST, etc.)
    "CM",   # Commander precons
    "C1", "C2",  # Commander sets
    "PCA",  # Planechase Anthology
    "ARC",  # Archenemy
    "BBD",  # Battlebond (legal in Legacy/Vintage only — handled by Scryfall)
}

NON_CONSTRUCTED_SETS = {
    "UST", "UNH", "UNF", "UND",  # Un-sets
    "JMP", "J22", "J25",          # Jumpstart (cards legal individually, not as a "set")
    "CLB", "CMM", "CMD",          # Commander products
}


def _is_standard_legal(set_code: str) -> bool:
    return set_code.upper() in STANDARD_LEGAL_SETS


def _is_pioneer_legal(set_code: str) -> bool:
    """Pioneer = Return to Ravnica (RTR, Oct 2012) forward."""
    if _is_standard_legal(set_code):
        return True
    # Check via Scryfall data if available; for known sets, use release date
    code = set_code.upper()
    info = KNOWN_SETS.get(code)
    if info and info[1] >= "2012-10-01":
        return True
    # Fallback: assume Pioneer-legal if not explicitly excluded
    return code not in NON_CONSTRUCTED_SETS


def _is_modern_legal(set_code: str) -> bool:
    """Modern = 8th Edition (8ED, July 2003) forward + Modern Horizons sets."""
    if _is_pioneer_legal(set_code):
        return True
    code = set_code.upper()
    if code in ("MH1", "MH2", "MH3"):
        return True
    info = KNOWN_SETS.get(code)
    if info and info[1] >= "2003-07-28":
        return True
    return False


def is_set_legal_in_format(set_code: str, fmt: str) -> tuple[bool, str]:
    """
    Check if a set is legal in the given format.
    Returns (is_legal, reason_string).
    """
    code = set_code.upper()
    fmt_lower = fmt.lower()

    # Check non-constructed
    if code in NON_CONSTRUCTED_SETS:
        return False, f"{code} is not legal in 60-card constructed formats."
    for prefix in NON_CONSTRUCTED_PREFIXES:
        if code.startswith(prefix) and len(code) <= len(prefix) + 2:
            return False, f"{code} appears to be a non-constructed product."

    if fmt_lower == "standard":
        if _is_standard_legal(code):
            return True, f"{code} is Standard-legal."
        return False, f"{code} is not currently in Standard rotation."
    elif fmt_lower == "pioneer":
        if _is_pioneer_legal(code):
            return True, f"{code} is Pioneer-legal."
        return False, f"{code} predates Pioneer (Return to Ravnica, Oct 2012)."
    elif fmt_lower == "modern":
        if _is_modern_legal(code):
            return True, f"{code} is Modern-legal."
        return False, f"{code} predates Modern (8th Edition, July 2003)."
    elif fmt_lower in ("legacy", "pauper", "vintage"):
        return True, f"All regular sets are legal in {fmt_lower.capitalize()}."
    else:
        return True, f"Unknown format '{fmt}' — assuming legal."


# ── Mythic Spoiler scraper ─────────────────────────────────────────────

def _get(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            print(f"  [warn] attempt {attempt+1}/{retries} failed for {url}: {e}")
            time.sleep(DELAY * (attempt + 1))
    return None


def _name_from_href(href: str) -> str:
    """
    Derive a best-effort card name from a mythicspoiler card URL.
    e.g. 'cards/betorkintoall.html' → 'Betorkintoall'
    This is lossy — we rely on Scryfall fuzzy lookup to fix it.
    """
    # Strip path and extension
    name = href.rsplit("/", 1)[-1].replace(".html", "")
    # Remove trailing 1/2 for DFC
    name = re.sub(r"[12]$", "", name)
    return name


def _scrape_card_names(set_code: str) -> list[str]:
    """
    Fetch the set index page and extract raw card name slugs.
    Returns list of lowercase slug strings (no spaces, no punctuation).
    """
    url = f"{BASE_URL}/{set_code.lower()}/index.html"
    print(f"Fetching set page: {url}")
    resp = _get(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    slugs = []
    seen = set()
    for a in soup.select("a.card"):
        href = a.get("href", "")
        if not href or "cards/" not in href:
            continue
        slug = _name_from_href(href)
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    print(f"  Found {len(slugs)} card slugs from Mythic Spoiler")
    return slugs


def _lookup_scryfall(slugs: list[str], set_code: str) -> list[dict]:
    """
    Match mythicspoiler slugs against the local Scryfall bulk data.
    Returns list of card dicts with full metadata.

    Uses two indexes:
    1. Slug index (no-spaces, lowercase) built from the raw JSON
    2. The processed bulk cache as fallback for proper name lookups
    """
    import json as _json
    try:
        from scrapers.scryfall import BULK_PATH
    except ImportError:
        print("  [warn] Could not import scryfall module")
        return []

    import os
    if not os.path.exists(BULK_PATH):
        print("  [warn] No Scryfall bulk data file found")
        return []

    print("  Building slug index from Scryfall data...", end=" ", flush=True)
    with open(BULK_PATH, encoding="utf-8") as f:
        bulk = _json.load(f)

    # Build slug index: lowercase-no-punctuation → raw card dict
    # Prefer cards from this specific set
    slug_index = {}
    set_slug_index = {}
    for card in bulk:
        name = card.get("name", "")
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if not key:
            continue
        slug_index[key] = card
        # Also index front face only (for DFCs: "Name // Back" → "name")
        if " // " in name:
            front = name.split(" // ")[0]
            front_key = re.sub(r"[^a-z0-9]", "", front.lower())
            if front_key:
                slug_index[front_key] = card
        # Set-specific index
        if card.get("set", "").upper() == set_code.upper():
            set_slug_index[key] = card
            if " // " in name:
                front = name.split(" // ")[0]
                front_key = re.sub(r"[^a-z0-9]", "", front.lower())
                if front_key:
                    set_slug_index[front_key] = card

    print(f"{len(slug_index):,} entries")

    cards = []
    matched = 0
    seen_names = set()
    for slug in slugs:
        clean = re.sub(r"[^a-z0-9]", "", slug.lower())
        # Try set-specific match first, then global
        raw = set_slug_index.get(clean) or slug_index.get(clean)
        if raw:
            name = raw.get("name", slug)
            if name in seen_names:
                continue
            seen_names.add(name)
            matched += 1
            cards.append({
                "name": name,
                "mana_cost": raw.get("mana_cost", ""),
                "cmc": raw.get("cmc", 0),
                "type_line": raw.get("type_line", ""),
                "oracle_text": raw.get("oracle_text", ""),
                "colors": raw.get("colors", []),
                "rarity": raw.get("rarity", ""),
                "power": raw.get("power", ""),
                "toughness": raw.get("toughness", ""),
                "set": raw.get("set", set_code).upper(),
                "legalities": raw.get("legalities", {}),
            })

    print(f"  Matched {matched}/{len(slugs)} cards against Scryfall data")
    return cards


def fetch_set_cards(set_code: str) -> list[dict]:
    """
    Main entry point. Fetches card list from Mythic Spoiler, enriches
    from Scryfall bulk data. Returns list of card dicts.

    Each dict has: name, mana_cost, cmc, type_line, oracle_text,
    colors, rarity, power, toughness, set, legalities.
    """
    slugs = _scrape_card_names(set_code)
    if not slugs:
        print(f"  No cards found for set code '{set_code}'")
        return []

    cards = _lookup_scryfall(slugs, set_code)
    time.sleep(DELAY)
    return cards


def format_cards_for_analysis(cards: list[dict]) -> str:
    """Format card list as structured text for the Claude analysis prompt."""
    lines = []
    for c in cards:
        parts = [c["name"]]
        if c.get("mana_cost"):
            parts.append(c["mana_cost"])
        if c.get("type_line"):
            parts.append(f"— {c['type_line']}")
        if c.get("oracle_text"):
            # Compact: replace newlines with " / "
            text = c["oracle_text"].replace("\n", " / ")
            parts.append(f"[{text}]")
        if c.get("power") and c.get("toughness"):
            parts.append(f"({c['power']}/{c['toughness']})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "TDM"
    cards = fetch_set_cards(code)
    if cards:
        print(f"\n=== {len(cards)} cards from {code} ===\n")
        for c in cards[:10]:
            print(f"  {c['name']} {c['mana_cost']} — {c['type_line']}")
        if len(cards) > 10:
            print(f"  ... and {len(cards) - 10} more")
    else:
        print("No cards found.")
