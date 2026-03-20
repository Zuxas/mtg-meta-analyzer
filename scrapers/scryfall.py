"""
Scryfall API integration — card data enrichment.

Strategy:
  1. Download Scryfall "oracle_cards" bulk JSON (~75 MB) once per week.
     This covers every uniquely-named card with current oracle data.
  2. Match every card name in our DB against the bulk lookup (exact + face names).
  3. For any cards not found in bulk, fall back to /cards/named?fuzzy= API calls.
  4. Store enrichment in the card_data table (keyed by card name, not card_id,
     so the same data works across both the active and archive DBs).

Usage:
    python -m scrapers.scryfall                    # enrich all unenriched cards
    python -m scrapers.scryfall --force            # re-enrich all (refresh)
    python -m scrapers.scryfall --download         # just refresh bulk file
    python -m scrapers.scryfall --card "Lightning Bolt"
"""

import json
import os
import time
import argparse
import requests
from datetime import datetime, timedelta
from db.database import get_connection, init_db


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
NAMED_URL      = "https://api.scryfall.com/cards/named"
API_DELAY      = 0.12          # 120 ms between API calls (Scryfall asks >=100 ms)
BULK_MAX_AGE   = timedelta(days=7)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BULK_PATH      = os.path.join(_project_root, "data", "scryfall_oracle.json")
BULK_META_PATH = os.path.join(_project_root, "data", "scryfall_meta.json")

HEADERS = {
    "User-Agent": "mtg-meta-analyzer/1.0 (personal tournament analysis tool)",
    "Accept":     "application/json",
}


# ---------------------------------------------------------------------------
# Bulk data download
# ---------------------------------------------------------------------------

def _bulk_is_fresh():
    """Return True if the local bulk file exists and is less than BULK_MAX_AGE old."""
    if not os.path.exists(BULK_META_PATH):
        return False
    try:
        meta = json.load(open(BULK_META_PATH))
        updated = datetime.fromisoformat(meta.get("downloaded_at", "2000-01-01"))
        return datetime.now() - updated < BULK_MAX_AGE
    except Exception:
        return False


def download_bulk_data(force=False):
    """
    Download the Scryfall oracle_cards bulk file to BULK_PATH.
    Skips if the local file is fresh and force=False.
    Returns the path to the bulk file.
    """
    if not force and _bulk_is_fresh():
        print(f"  Bulk data is fresh (< {BULK_MAX_AGE.days} days old). Use --force to re-download.")
        return BULK_PATH

    os.makedirs(os.path.dirname(BULK_PATH), exist_ok=True)
    print("  Fetching bulk data index from Scryfall...")

    resp = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    entries = resp.json().get("data", [])

    oracle_entry = next((e for e in entries if e["type"] == "oracle_cards"), None)
    if not oracle_entry:
        raise RuntimeError("Could not find oracle_cards entry in Scryfall bulk data index.")

    download_url = oracle_entry["download_uri"]
    size_mb = oracle_entry.get("size", 0) / 1024 / 1024
    print(f"  Downloading oracle cards ({size_mb:.0f} MB)...")

    with requests.get(download_url, headers=HEADERS, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(BULK_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r    {pct:5.1f}%  ({downloaded//1024//1024} MB)", end="", flush=True)
    print()

    json.dump(
        {"downloaded_at": datetime.now().isoformat(), "source_url": download_url},
        open(BULK_META_PATH, "w")
    )
    print(f"  Saved to {BULK_PATH}")
    return BULK_PATH


# ---------------------------------------------------------------------------
# Bulk data parsing
# ---------------------------------------------------------------------------

def _extract_card_data(card):
    """
    Extract enrichment fields from a Scryfall card object.
    For double-faced cards, front-face data is used for mana cost / oracle text.
    Returns a flat dict matching the card_data table columns.
    """
    face = card.get("card_faces", [{}])[0] if "card_faces" in card else card

    return {
        "scryfall_id":    card.get("id"),
        "mana_cost":      face.get("mana_cost") or card.get("mana_cost") or "",
        "cmc":            float(card.get("cmc", 0.0)),
        "colors":         json.dumps(card.get("colors") or face.get("colors") or []),
        "color_identity": json.dumps(card.get("color_identity", [])),
        "type_line":      card.get("type_line") or face.get("type_line", ""),
        "oracle_text":    face.get("oracle_text") or card.get("oracle_text") or "",
        "power":          face.get("power") or card.get("power"),
        "toughness":      face.get("toughness") or card.get("toughness"),
        "rarity":         card.get("rarity", ""),
        "set_code":       card.get("set", ""),
        "legalities":     json.dumps(card.get("legalities", {})),
        "enriched_at":    datetime.now().isoformat(),
    }


def load_bulk_lookup(bulk_path=None):
    """
    Load the bulk JSON and build a name -> enrichment dict.

    Keys added for each card:
      - Exact oracle name (e.g. "Delver of Secrets // Insectile Aberration")
      - Front face name alone (e.g. "Delver of Secrets")
      - Each individual face name for split / adventure cards
    """
    path = bulk_path or BULK_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Bulk data not found at {path}. Run with --download first.")

    print(f"  Loading bulk data from {path}...")
    with open(path, encoding="utf-8") as f:
        cards = json.load(f)
    print(f"  Loaded {len(cards):,} oracle cards.")

    lookup = {}
    for card in cards:
        data = _extract_card_data(card)
        full_name = card["name"]
        lookup[full_name.lower()] = (full_name, data)

        # Also index each face name individually
        for face in card.get("card_faces", []):
            face_name = face.get("name", "")
            if face_name and face_name.lower() not in lookup:
                lookup[face_name.lower()] = (full_name, data)

    print(f"  Built lookup with {len(lookup):,} name variants.")
    return lookup


# ---------------------------------------------------------------------------
# Per-card API fallback
# ---------------------------------------------------------------------------

def _fetch_single_card(name):
    """
    Look up one card by name using the Scryfall /cards/named?fuzzy= endpoint.
    Returns enrichment dict or None if not found.
    """
    time.sleep(API_DELAY)
    try:
        resp = requests.get(NAMED_URL, headers=HEADERS,
                            params={"fuzzy": name}, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _extract_card_data(resp.json())
    except Exception as e:
        print(f"    Warning: API error for '{name}': {e}")
        return None


# ---------------------------------------------------------------------------
# DB enrichment
# ---------------------------------------------------------------------------

def _upsert_card_data(conn, name, data):
    conn.execute("""
        INSERT INTO card_data
            (name, scryfall_id, mana_cost, cmc, colors, color_identity,
             type_line, oracle_text, power, toughness, rarity, set_code,
             legalities, enriched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
            scryfall_id=excluded.scryfall_id,
            mana_cost=excluded.mana_cost, cmc=excluded.cmc,
            colors=excluded.colors, color_identity=excluded.color_identity,
            type_line=excluded.type_line, oracle_text=excluded.oracle_text,
            power=excluded.power, toughness=excluded.toughness,
            rarity=excluded.rarity, set_code=excluded.set_code,
            legalities=excluded.legalities, enriched_at=excluded.enriched_at
    """, (
        name,
        data["scryfall_id"], data["mana_cost"], data["cmc"],
        data["colors"], data["color_identity"], data["type_line"],
        data["oracle_text"], data["power"], data["toughness"],
        data["rarity"], data["set_code"], data["legalities"], data["enriched_at"],
    ))


def enrich_cards(force=False, bulk_path=None, batch_size=200):
    """
    Enrich all card names in the DB with Scryfall data.

    force=False: skip cards that already have an enriched_at timestamp.
    Returns (enriched_count, skipped_count, not_found_count).
    """
    # 1. Ensure bulk data is available
    if not os.path.exists(bulk_path or BULK_PATH) or not _bulk_is_fresh():
        download_bulk_data(force=False)

    lookup = load_bulk_lookup(bulk_path)

    # 2. Get card names to enrich
    with get_connection() as conn:
        if force:
            rows = conn.execute("SELECT name FROM cards ORDER BY name").fetchall()
        else:
            rows = conn.execute("""
                SELECT c.name FROM cards c
                LEFT JOIN card_data cd ON cd.name = c.name
                WHERE cd.name IS NULL
                ORDER BY c.name
            """).fetchall()

    names = [r["name"] for r in rows]
    total = len(names)
    print(f"\n  Cards to enrich: {total}")

    if total == 0:
        print("  All cards already enriched. Use --force to refresh.")
        return 0, 0, 0

    enriched = skipped = not_found = 0
    batch = {}

    def _flush(batch):
        with get_connection() as conn:
            for n, d in batch.items():
                _upsert_card_data(conn, n, d)

    for i, name in enumerate(names, 1):
        # Try bulk lookup first (case-insensitive)
        key = name.lower()
        if key in lookup:
            _, data = lookup[key]
            batch[name] = data
            enriched += 1
        else:
            # Try stripping Alchemy prefix
            stripped = name.lstrip("A-") if name.startswith("A-") else None
            if stripped and stripped.lower() in lookup:
                _, data = lookup[stripped.lower()]
                batch[name] = data
                enriched += 1
            else:
                # Fall back to API
                data = _fetch_single_card(name)
                if data:
                    batch[name] = data
                    enriched += 1
                else:
                    not_found += 1

        if i % batch_size == 0 or i == total:
            _flush(batch)
            batch = {}
            print(f"  [{i:>6}/{total}]  enriched={enriched}  not_found={not_found}")

    print(f"\n  Done. Enriched: {enriched} | Already done: {skipped} | Not found: {not_found}")
    return enriched, skipped, not_found


# ---------------------------------------------------------------------------
# Query helpers (used by analysis modules)
# ---------------------------------------------------------------------------

def get_card_data(name):
    """
    Fetch enrichment data for one card by name.
    Returns a dict with all card_data fields, or None if not enriched.
    Colors, color_identity, and legalities are deserialized from JSON.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM card_data WHERE name = ?", (name,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("colors", "color_identity", "legalities"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def get_cards_data(names):
    """
    Fetch enrichment data for a list of card names.
    Returns {name: data_dict} — missing cards are absent from the result.
    """
    if not names:
        return {}
    ph = ",".join("?" * len(names))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM card_data WHERE name IN ({ph})", list(names)
        ).fetchall()
    result = {}
    for row in rows:
        d = dict(row)
        for key in ("colors", "color_identity", "legalities"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        result[d["name"]] = d
    return result


def is_legal(card_name, format_name):
    """
    Return True if card_name is legal in format_name according to Scryfall data.
    Returns None if enrichment data is unavailable.
    """
    data = get_card_data(card_name)
    if not data or not data.get("legalities"):
        return None
    legalities = data["legalities"]
    if isinstance(legalities, str):
        try:
            legalities = json.loads(legalities)
        except Exception:
            return None
    return legalities.get(format_name.lower()) == "legal"


def enrich_stats():
    """Return a summary of enrichment coverage."""
    with get_connection() as conn:
        total_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        enriched    = conn.execute("SELECT COUNT(*) FROM card_data").fetchone()[0]
        unenriched  = conn.execute("""
            SELECT COUNT(*) FROM cards c
            LEFT JOIN card_data cd ON cd.name = c.name
            WHERE cd.name IS NULL
        """).fetchone()[0]
    return {
        "total_cards": total_cards,
        "enriched":    enriched,
        "unenriched":  unenriched,
        "pct":         round(enriched / total_cards * 100, 1) if total_cards else 0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_card(name):
    data = get_card_data(name)
    if not data:
        # Try to fetch live and store
        print(f"  Not in DB — fetching from Scryfall API...")
        raw = _fetch_single_card(name)
        if not raw:
            print(f"  Card '{name}' not found on Scryfall.")
            return
        with get_connection() as conn:
            _upsert_card_data(conn, name, raw)
        data = get_card_data(name)

    print(f"\n  {name}")
    print(f"  Mana cost  : {data.get('mana_cost', '?')}  (CMC {data.get('cmc', '?')})")
    print(f"  Type       : {data.get('type_line', '?')}")
    colors = data.get("colors", [])
    ci     = data.get("color_identity", [])
    print(f"  Colors     : {', '.join(colors) if colors else 'Colorless'}  "
          f"(identity: {', '.join(ci) if ci else 'C'})")
    print(f"  Rarity     : {data.get('rarity', '?')}  ({data.get('set_code', '?').upper()})")
    oracle = data.get("oracle_text", "")
    if oracle:
        for line in oracle.splitlines():
            print(f"    {line}")
    legalities = data.get("legalities", {})
    if legalities:
        legal_fmts = [f for f, v in legalities.items() if v == "legal"]
        print(f"  Legal in   : {', '.join(sorted(legal_fmts))}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MTG Meta Analyzer -- Scryfall card enrichment")
    parser.add_argument("--download",  action="store_true", help="Download/refresh bulk data file")
    parser.add_argument("--force",     action="store_true", help="Re-enrich all cards (ignore existing)")
    parser.add_argument("--card",      metavar="NAME",       help="Look up and display one card")
    parser.add_argument("--stats",     action="store_true", help="Show enrichment coverage stats")
    args = parser.parse_args()

    init_db()

    if args.stats:
        s = enrich_stats()
        print(f"\n  Cards in DB : {s['total_cards']:,}")
        print(f"  Enriched    : {s['enriched']:,}  ({s['pct']}%)")
        print(f"  Unenriched  : {s['unenriched']:,}\n")

    elif args.card:
        _print_card(args.card)

    elif args.download:
        download_bulk_data(force=True)

    else:
        enrich_cards(force=args.force)
