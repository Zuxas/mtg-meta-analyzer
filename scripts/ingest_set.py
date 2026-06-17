"""
Ingest every card from a Scryfall set into the local `card_data` table.

Built for loading a freshly-spoiled set (e.g. MSH "Marvel Super Heroes")
into the local card database so the cards are available for deck-building
experiments before they ever show up in tournament data.

Data flow:
  1. Live Scryfall search  ->  q=e:<set>&unique=cards  (one object per
     oracle card, paginated, rate-limited).  This is the source of truth
     for oracle text / types / legalities / P&T.
  2. Reuse scrapers.scryfall._extract_card_data + _sqlite_upsert so the
     rows are byte-for-byte identical to what the weekly enrich pipeline
     would produce.

Optional --html <gallery.html> cross-checks coverage: it pulls the set of
card slugs from a saved Scryfall "Card Gallery" page and confirms every
slug ended up ingested (catches a card the API search might miss).

Safety:
  * Name-collision guard.  card_data is keyed by `name`; the upsert is
    last-write-wins.  Before writing we report any incoming card whose
    name already exists in card_data (reprints / basics) and skip basic
    lands by default so we never silently rewrite an existing row's
    set_code/rarity.  Use --overwrite to ingest collisions anyway.

Usage:
    python -m scripts.ingest_set --set msh
    python -m scripts.ingest_set --set msh --html "path/to/gallery.html"
    python -m scripts.ingest_set --set msh --overwrite      # ingest reprints too
    python -m scripts.ingest_set --set msh --dry-run        # report only, no write
"""

import argparse
import re
import sys
import time
import unicodedata
from urllib.parse import unquote

import requests

from db.database import get_connection, init_db
from scrapers.scryfall import _extract_card_data, _sqlite_upsert, HEADERS, API_DELAY

SEARCH_URL = "https://api.scryfall.com/cards/search"


# ---------------------------------------------------------------------------
# Scryfall fetch
# ---------------------------------------------------------------------------

def fetch_set_cards(set_code: str) -> list:
    """Return all oracle cards in a set (one object per card name)."""
    cards = []
    params = {"q": f"e:{set_code}", "unique": "cards", "order": "set"}
    url = SEARCH_URL
    page = 1
    while url:
        resp = requests.get(url, headers=HEADERS,
                            params=params if url == SEARCH_URL else None,
                            timeout=30)
        if resp.status_code == 404:
            print(f"  No cards found for set '{set_code}'.")
            return []
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("data", [])
        cards.extend(batch)
        print(f"  page {page}: +{len(batch)} cards (total {len(cards)})")
        if payload.get("has_more"):
            url = payload["next_page"]
            page += 1
            time.sleep(API_DELAY)
        else:
            url = None
    return cards


# ---------------------------------------------------------------------------
# HTML gallery coverage cross-check
# ---------------------------------------------------------------------------

def slugs_from_gallery(html_path: str, set_code: str) -> set:
    """Extract the distinct card slugs from a saved Scryfall gallery page."""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    pattern = rf'scryfall\.com/card/{re.escape(set_code)}/[0-9a-z]+/([^"?\s]+)'
    return set(re.findall(pattern, html, flags=re.IGNORECASE))


def normalize_slug(s: str) -> str:
    """
    Aggressively normalize a slug/name to a comparison key: URL-decode,
    fold accents to ASCII (Mjolnir == Mjölnir), lowercase, strip every
    non-alphanumeric char. Punctuation and encoding differences vanish,
    so coverage matching only flags genuinely absent cards.
    """
    s = unquote(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def card_slug_keys(card: dict) -> set:
    """
    All normalized slug keys a gallery URL might use for this card:
    the full oracle name plus each individual face name (modal DFC galleries
    link the back face under its own slug).
    """
    keys = {normalize_slug(card["name"])}
    for face in card.get("card_faces", []):
        if face.get("name"):
            keys.add(normalize_slug(face["name"]))
    return keys


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def existing_names(names: list) -> set:
    """Return the subset of `names` already present in card_data."""
    if not names:
        return set()
    found = set()
    with get_connection() as conn:
        for i in range(0, len(names), 400):
            chunk = names[i:i + 400]
            ph = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT name FROM card_data WHERE name IN ({ph})", chunk
            ).fetchall()
            found.update(r["name"] for r in rows)
    return found


def is_basic_land(card: dict) -> bool:
    return "Basic Land" in (card.get("type_line") or "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Ingest a Scryfall set into card_data")
    ap.add_argument("--set", required=True, help="Set code, e.g. msh")
    ap.add_argument("--html", help="Optional saved gallery HTML for coverage check")
    ap.add_argument("--overwrite", action="store_true",
                    help="Ingest cards whose name already exists in card_data")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report only; do not write to the database")
    args = ap.parse_args()

    set_code = args.set.lower()
    init_db()

    print(f"\n  Fetching set '{set_code}' from Scryfall...")
    cards = fetch_set_cards(set_code)
    if not cards:
        sys.exit(1)

    names = [c["name"] for c in cards]
    print(f"\n  Distinct card names returned: {len(set(names))}")

    # ---- collision guard --------------------------------------------------
    collisions = existing_names(names)
    basics = [c["name"] for c in cards if is_basic_land(c)]
    if collisions:
        print(f"\n  WARNING: {len(collisions)} name(s) already in card_data "
              f"(reprints/basics):")
        for n in sorted(collisions):
            tag = " [basic land]" if n in basics else ""
            print(f"    - {n}{tag}")
        if not args.overwrite:
            print("  -> Skipping these (use --overwrite to ingest anyway). "
                  "Basic lands are always skipped.")

    # ---- upsert -----------------------------------------------------------
    written = skipped = 0
    for card in cards:
        name = card["name"]
        if is_basic_land(card):
            skipped += 1
            continue
        if name in collisions and not args.overwrite:
            skipped += 1
            continue
        data = _extract_card_data(card)
        if not args.dry_run:
            _sqlite_upsert(name, data)
        written += 1

    verb = "Would write" if args.dry_run else "Wrote"
    print(f"\n  {verb}: {written}   Skipped: {skipped}")

    # ---- coverage cross-check vs gallery HTML -----------------------------
    if args.html:
        gallery = {normalize_slug(s) for s in slugs_from_gallery(args.html, set_code)}
        ingested_keys = set()
        for c in cards:
            ingested_keys |= card_slug_keys(c)
        missing = gallery - ingested_keys
        print(f"\n  Distinct gallery cards: {len(gallery)}   "
              f"Ingested slug keys: {len(ingested_keys)}")
        if missing:
            print(f"  WARNING: {len(missing)} gallery card(s) not matched to an "
                  f"ingested card:")
            for s in sorted(missing):
                print(f"    - {s}")
        else:
            print("  Coverage OK: every gallery card is represented in the ingest.")

    # ---- verification report ----------------------------------------------
    if not args.dry_run:
        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM card_data WHERE set_code = ?", (set_code,)
            ).fetchone()[0]
        print(f"\n  card_data now holds {n} rows for set '{set_code}'.")


if __name__ == "__main__":
    main()
