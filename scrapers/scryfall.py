"""
Scryfall API integration — local card database + enrichment.

Lookup hierarchy (fastest to slowest):
  1. SQLite card_data table  — cards seen in tournament data (instant)
  2. Local scryfall_oracle.json — full Scryfall oracle database (~75 MB,
     loaded into memory once per process on first miss)
  3. Live Scryfall API      — only if card is absent from local file

The local JSON is refreshed automatically every Sunday at midnight by a
Windows Task Scheduler job (registered via schedule_scryfall.bat).
It can also be refreshed manually: python -m scrapers.scryfall --download

Usage:
    python -m scrapers.scryfall                    # enrich all unenriched cards
    python -m scrapers.scryfall --force            # re-enrich all (full refresh)
    python -m scrapers.scryfall --download         # refresh bulk JSON only
    python -m scrapers.scryfall --card "Opt"       # look up and display one card
    python -m scrapers.scryfall --stats            # enrichment coverage
"""

import json
import os
import re
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
API_DELAY      = 0.12          # 120 ms between requests (Scryfall asks >=100 ms)
BULK_MAX_AGE   = timedelta(days=7)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BULK_PATH      = os.path.join(_project_root, "data", "scryfall_oracle.json")
BULK_META_PATH = os.path.join(_project_root, "data", "scryfall_meta.json")

HEADERS = {
    "User-Agent": "mtg-meta-analyzer/1.0 (personal tournament analysis tool)",
    "Accept":     "application/json",
}

# ---------------------------------------------------------------------------
# In-memory bulk cache (lazy-loaded, lives for the process lifetime)
# Structure: {name_lower: {"canonical_name": str, **card_data_fields}}
# ---------------------------------------------------------------------------

_BULK_CACHE: dict | None = None


def _get_bulk_cache() -> dict:
    """
    Return the in-memory bulk lookup, loading it from disk on first call.
    If the local file does not exist, attempts a download.
    """
    global _BULK_CACHE
    if _BULK_CACHE is not None:
        return _BULK_CACHE

    if not os.path.exists(BULK_PATH):
        print("  Local Scryfall database not found — downloading now...")
        download_bulk_data(force=False)

    _BULK_CACHE = _build_bulk_cache()
    return _BULK_CACHE


def _build_bulk_cache() -> dict:
    """Parse scryfall_oracle.json into a flat name -> data dict."""
    print(f"  Loading local Scryfall database...", end=" ", flush=True)
    with open(BULK_PATH, encoding="utf-8") as f:
        cards = json.load(f)

    cache = {}
    for card in cards:
        data = _extract_card_data(card)
        data["canonical_name"] = card["name"]

        # Index by full oracle name
        cache[card["name"].lower()] = data

        # Also index each individual face name (DFCs, split, adventure)
        for face in card.get("card_faces", []):
            face_name = face.get("name", "")
            if face_name and face_name.lower() not in cache:
                cache[face_name.lower()] = data

    print(f"{len(cache):,} name variants loaded.")
    return cache


# ---------------------------------------------------------------------------
# Bulk data download
# ---------------------------------------------------------------------------

def _bulk_is_fresh() -> bool:
    if not os.path.exists(BULK_META_PATH):
        return False
    try:
        meta = json.load(open(BULK_META_PATH))
        updated = datetime.fromisoformat(meta.get("downloaded_at", "2000-01-01"))
        return datetime.now() - updated < BULK_MAX_AGE
    except Exception:
        return False


def download_bulk_data(force=False) -> str:
    """
    Download the Scryfall oracle_cards bulk file to BULK_PATH.
    Skips if file is fresh and force=False.
    Invalidates the in-memory cache so next access reloads from disk.
    Returns path to the bulk file.
    """
    global _BULK_CACHE

    if not force and _bulk_is_fresh() and os.path.exists(BULK_PATH):
        age_hours = (datetime.now() - datetime.fromisoformat(
            json.load(open(BULK_META_PATH)).get("downloaded_at", "2000-01-01")
        )).total_seconds() / 3600
        print(f"  Local database is fresh ({age_hours:.0f}h old). Use --force to re-download.")
        return BULK_PATH

    os.makedirs(os.path.dirname(BULK_PATH), exist_ok=True)
    print("  Fetching bulk data index from Scryfall...")

    resp = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    entries = resp.json().get("data", [])
    oracle_entry = next((e for e in entries if e["type"] == "oracle_cards"), None)
    if not oracle_entry:
        raise RuntimeError("oracle_cards entry not found in Scryfall bulk index.")

    download_url = oracle_entry["download_uri"]
    size_mb = oracle_entry.get("size", 0) / 1024 / 1024
    print(f"  Downloading oracle cards ({size_mb:.0f} MB)...")

    with requests.get(download_url, headers=HEADERS, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(BULK_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    print(f"\r    {downloaded/total*100:5.1f}%  "
                          f"({downloaded//1024//1024} / {total//1024//1024} MB)",
                          end="", flush=True)
    print()

    json.dump(
        {"downloaded_at": datetime.now().isoformat(), "source_url": download_url},
        open(BULK_META_PATH, "w")
    )
    print(f"  Saved: {BULK_PATH}")

    # Invalidate in-memory cache so next access reloads fresh data
    _BULK_CACHE = None
    return BULK_PATH


# ---------------------------------------------------------------------------
# Card data extraction
# ---------------------------------------------------------------------------

def _extract_card_data(card: dict) -> dict:
    """
    Extract enrichment fields from a Scryfall card object.
    For DFCs/split/adventure cards, front-face data is used for
    mana cost, oracle text, and power/toughness.
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


def _deserialize(row: dict) -> dict:
    """Decode JSON string fields in a card_data row."""
    d = dict(row)
    for key in ("colors", "color_identity", "legalities"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _sqlite_lookup(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM card_data WHERE name = ?", (name,)
        ).fetchone()
    return _deserialize(dict(row)) if row else None


def _sqlite_upsert(name: str, data: dict):
    with get_connection() as conn:
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
            data.get("scryfall_id"), data.get("mana_cost"), data.get("cmc"),
            data.get("colors") if isinstance(data.get("colors"), str)
                else json.dumps(data.get("colors", [])),
            data.get("color_identity") if isinstance(data.get("color_identity"), str)
                else json.dumps(data.get("color_identity", [])),
            data.get("type_line"), data.get("oracle_text"),
            data.get("power"), data.get("toughness"),
            data.get("rarity"), data.get("set_code"),
            data.get("legalities") if isinstance(data.get("legalities"), str)
                else json.dumps(data.get("legalities", {})),
            data.get("enriched_at", datetime.now().isoformat()),
        ))


# ---------------------------------------------------------------------------
# Live API fallback
# ---------------------------------------------------------------------------

def _api_lookup(name: str) -> dict | None:
    """Look up one card via the live Scryfall API. Rate-limited."""
    time.sleep(API_DELAY)
    try:
        resp = requests.get(NAMED_URL, headers=HEADERS,
                            params={"fuzzy": name}, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _extract_card_data(resp.json())
    except Exception as e:
        print(f"  Warning: Scryfall API error for '{name}': {e}")
        return None


# ---------------------------------------------------------------------------
# Public query interface
# ---------------------------------------------------------------------------

def get_card_data(name: str) -> dict | None:
    """
    Return full card data for a card name.

    Lookup order:
      1. SQLite card_data table (instant — covers all tournament cards)
      2. Local scryfall_oracle.json (loaded into memory once per process)
      3. Live Scryfall API (only if genuinely absent from local database)

    Results from layers 2 and 3 are written back to SQLite so future
    calls for the same card always hit layer 1.
    """
    # 1. SQLite
    row = _sqlite_lookup(name)
    if row:
        return row

    # 2. Local bulk cache
    cache = _get_bulk_cache()
    key = name.lower()
    if key in cache:
        data = cache[key]
        _sqlite_upsert(name, data)
        return _deserialize(data)

    # 3. Live API (last resort)
    data = _api_lookup(name)
    if data:
        _sqlite_upsert(name, data)
        return _deserialize(data)

    return None


def get_cards_data(names: list) -> dict:
    """
    Fetch enrichment data for multiple card names efficiently.
    Returns {name: data_dict} — missing cards are absent.
    """
    if not names:
        return {}

    # Batch SQLite lookup
    ph = ",".join("?" * len(names))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM card_data WHERE name IN ({ph})", list(names)
        ).fetchall()
    result = {dict(r)["name"]: _deserialize(dict(r)) for r in rows}

    # For any misses, use bulk cache then API
    missing = [n for n in names if n not in result]
    for name in missing:
        data = get_card_data(name)
        if data:
            result[name] = data

    return result


def is_legal(card_name: str, format_name: str) -> bool | None:
    """
    Return True if card_name is legal in format_name.
    Returns None if no enrichment data is available.
    """
    data = get_card_data(card_name)
    if not data:
        return None
    legalities = data.get("legalities", {})
    if not isinstance(legalities, dict):
        return None
    return legalities.get(format_name.lower()) == "legal"


def search_local(query: str, limit: int = 8) -> list:
    """
    Fuzzy search the local bulk database by card name.
    Returns list of card data dicts, best matches first.
    Does NOT call the Scryfall API.

    Useful for natural-language queries like "what does sheoldred do"
    where the exact name isn't known.

    Scoring uses token_set_ratio (handles subset matches well) plus a
    bonus for names that START with the query terms, so "sheoldred"
    correctly ranks "Sheoldred, the Apocalypse" above "Reaper of Sheoldred".
    """
    from thefuzz import fuzz

    # Strip common natural-language prefixes/suffixes
    cleaned = re.sub(
        r'^(what does|what is|show me|tell me about|look up|find|search for|'
        r'how does|what\'s|whats|can you show me)\s+',
        '', query.strip(), flags=re.IGNORECASE
    )
    cleaned = re.sub(r'\s+(do|does|work|mean)\s*\??$', '', cleaned,
                     flags=re.IGNORECASE).strip().strip('"\'')

    cache = _get_bulk_cache()
    unique_names = list(dict.fromkeys(
        v["canonical_name"] for v in cache.values() if "canonical_name" in v
    ))

    q_lower = cleaned.lower()
    scored = []
    for name in unique_names:
        base  = fuzz.token_set_ratio(q_lower, name.lower())
        direct = fuzz.ratio(q_lower, name.lower())   # whole-string similarity tiebreaker

        # Primary name = text before first comma or "//"
        primary = name.split(",")[0].split("//")[0].strip().lower()
        primary_exact = primary == q_lower           # "sheoldred" → "Sheoldred, the Apocalypse"
        starts_with   = (not primary_exact) and name.lower().startswith(q_lower)

        # Penalize DFC names ("Name // Other") when query doesn't contain "//"
        dfc_penalty = ("//" in name and "//" not in cleaned)

        scored.append((name, base, primary_exact, starts_with, direct, dfc_penalty))

    # Sort: base desc → primary_exact desc → dfc_penalty asc → starts_with desc → direct desc → shorter name first
    scored.sort(key=lambda x: (-x[1], -x[2], x[5], -x[3], -x[4], len(x[0])))

    results = []
    for name, base, *_rest in scored[:limit]:
        if base < 45:
            continue
        data = get_card_data(name)
        if data:
            results.append({"match_score": base, **data, "name": name})
    return results


def get_deck_usage(card_name: str, format_name: str = "standard") -> dict:
    """
    Return tournament usage stats for a card from our local DB.
    """
    with get_connection() as conn:
        total_decks = conn.execute("""
            SELECT COUNT(DISTINCT d.id) FROM decks d
            JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?)
        """, (format_name,)).fetchone()[0]

        row = conn.execute("""
            SELECT
                COUNT(DISTINCT dc.deck_id) AS deck_count,
                SUM(dc.quantity)            AS total_copies,
                AVG(CAST(dc.quantity AS REAL)) AS avg_copies,
                SUM(CASE WHEN dc.is_sideboard = 0 THEN 1 ELSE 0 END) AS main_count,
                SUM(CASE WHEN dc.is_sideboard = 1 THEN 1 ELSE 0 END) AS side_count
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            JOIN decks d ON d.id = dc.deck_id
            JOIN events e ON e.id = d.event_id
            WHERE c.name = ? AND lower(e.format) = lower(?)
        """, (card_name, format_name)).fetchone()

    deck_count = row["deck_count"] if row else 0
    return {
        "format":        format_name,
        "total_decks":   total_decks,
        "decks_with_card": deck_count,
        "inclusion_pct": round(deck_count / total_decks * 100, 1) if total_decks else 0,
        "avg_copies":    round(row["avg_copies"] or 0, 2) if row else 0,
        "main_count":    row["main_count"] if row else 0,
        "side_count":    row["side_count"] if row else 0,
    }


def enrich_stats() -> dict:
    """Return a summary of enrichment coverage."""
    with get_connection() as conn:
        total_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        enriched    = conn.execute("SELECT COUNT(*) FROM card_data").fetchone()[0]
        unenriched  = conn.execute("""
            SELECT COUNT(*) FROM cards c
            LEFT JOIN card_data cd ON cd.name = c.name
            WHERE cd.name IS NULL
        """).fetchone()[0]
    bulk_age = None
    if os.path.exists(BULK_META_PATH):
        try:
            meta = json.load(open(BULK_META_PATH))
            dt   = datetime.fromisoformat(meta.get("downloaded_at", ""))
            bulk_age = (datetime.now() - dt).days
        except Exception:
            pass
    return {
        "total_cards": total_cards,
        "enriched":    enriched,
        "unenriched":  unenriched,
        "pct":         round(enriched / total_cards * 100, 1) if total_cards else 0,
        "bulk_age_days": bulk_age,
        "bulk_path":   BULK_PATH,
        "bulk_exists": os.path.exists(BULK_PATH),
    }


# ---------------------------------------------------------------------------
# Batch enrichment (run once after backfill, then weekly)
# ---------------------------------------------------------------------------

def enrich_cards(force: bool = False, batch_size: int = 200):
    """
    Enrich all card names in the tournament DB with Scryfall data.
    Uses the local bulk file; only calls the API for genuine misses.
    Returns (enriched, skipped, not_found).
    """
    # Ensure local bulk file is available
    if not os.path.exists(BULK_PATH) or not _bulk_is_fresh():
        download_bulk_data(force=False)

    cache = _get_bulk_cache()

    with get_connection() as conn:
        if force:
            rows = conn.execute("SELECT name FROM cards ORDER BY name").fetchall()
        else:
            rows = conn.execute("""
                SELECT c.name FROM cards c
                LEFT JOIN card_data cd ON cd.name = c.name
                WHERE cd.name IS NULL ORDER BY c.name
            """).fetchall()

    names = [r["name"] for r in rows]
    total = len(names)
    print(f"\n  Cards to enrich: {total}")
    if total == 0:
        print("  All cards already enriched. Use --force to refresh.")
        return 0, 0, 0

    enriched = not_found = 0
    batch = {}

    def _flush(b):
        for n, d in b.items():
            _sqlite_upsert(n, d)

    for i, name in enumerate(names, 1):
        key = name.lower()
        if key in cache:
            batch[name] = cache[key]
            enriched += 1
        elif name.startswith("A-") and name[2:].lower() in cache:
            # Alchemy card: try without prefix
            batch[name] = cache[name[2:].lower()]
            enriched += 1
        else:
            data = _api_lookup(name)
            if data:
                batch[name] = data
                enriched += 1
            else:
                not_found += 1

        if i % batch_size == 0 or i == total:
            _flush(batch)
            batch = {}
            print(f"  [{i:>6}/{total}]  enriched={enriched}  not_found={not_found}")

    print(f"\n  Done. Enriched: {enriched} | Not found: {not_found}")
    return enriched, 0, not_found


# ---------------------------------------------------------------------------
# CLI display helper
# ---------------------------------------------------------------------------

def print_card(name: str, format_name: str = None, show_usage: bool = True):
    data = get_card_data(name)

    if not data:
        # Try fuzzy search in local bulk
        results = search_local(name, limit=3)
        if results:
            best = results[0]
            print(f"\n  '{name}' not found exactly.")
            print(f"  Best match: '{best['name']}' (score {best['match_score']})\n")
            data = best
            name = best["name"]
        else:
            print(f"\n  Card '{name}' not found in local database.\n")
            return

    colors  = data.get("colors", [])
    ci      = data.get("color_identity", [])
    pt_str  = ""
    if data.get("power") is not None:
        pt_str = f"  ({data['power']}/{data['toughness']})"

    print(f"\n  {data.get('name', name)}")
    print(f"  {'-' * 55}")
    print(f"  Mana cost   : {data.get('mana_cost') or '{0}'}  "
          f"(CMC {data.get('cmc', 0):.0f}){pt_str}")
    print(f"  Type        : {data.get('type_line', '?')}")
    print(f"  Colors      : {', '.join(colors) if colors else 'Colorless'}  "
          f"| Identity: {', '.join(ci) if ci else 'C'}")
    print(f"  Rarity      : {data.get('rarity', '?').title()}  "
          f"({data.get('set_code', '?').upper()})")

    oracle = data.get("oracle_text", "")
    if oracle:
        print(f"  {'-' * 55}")
        for line in oracle.splitlines():
            print(f"  {line}")

    legalities = data.get("legalities", {})
    if legalities and isinstance(legalities, dict):
        legal_fmts  = [f for f, v in legalities.items() if v == "legal"]
        banned_fmts = [f for f, v in legalities.items() if v == "banned"]
        if format_name:
            status = legalities.get(format_name.lower(), "unknown")
            print(f"  {'-' * 55}")
            tag = "LEGAL" if status == "legal" else status.upper()
            print(f"  {format_name.title()} legal : {tag}")
        else:
            print(f"  {'-' * 55}")
            print(f"  Legal in    : {', '.join(sorted(legal_fmts)) or 'none'}")
            if banned_fmts:
                print(f"  Banned in   : {', '.join(sorted(banned_fmts))}")

    if show_usage:
        fmt = format_name or "standard"
        usage = get_deck_usage(name, fmt)
        if usage["total_decks"] > 0:
            print(f"  {'-' * 55}")
            if usage["decks_with_card"] > 0:
                print(f"  {fmt.title()} usage : {usage['decks_with_card']} decks "
                      f"({usage['inclusion_pct']}% of {usage['total_decks']} total)  "
                      f"avg {usage['avg_copies']:.1f} copies")
                if usage["main_count"] and usage["side_count"]:
                    print(f"                  main: {usage['main_count']}  "
                          f"side: {usage['side_count']}")
            else:
                print(f"  {fmt.title()} usage : not seen in {usage['total_decks']} "
                      f"tournament decks")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MTG Meta Analyzer -- Scryfall local card database"
    )
    parser.add_argument("--download",  action="store_true",
                        help="Download/refresh local bulk database")
    parser.add_argument("--force",     action="store_true",
                        help="Re-enrich all cards (ignore existing data)")
    parser.add_argument("--card",      metavar="NAME",
                        help="Look up and display one card")
    parser.add_argument("--format",    default=None,
                        help="Format for legality check (used with --card)")
    parser.add_argument("--stats",     action="store_true",
                        help="Show enrichment coverage and database status")
    args = parser.parse_args()

    init_db()

    if args.stats:
        s = enrich_stats()
        print(f"\n  Local database  : {s['bulk_path']}")
        print(f"  DB exists       : {'Yes' if s['bulk_exists'] else 'No -- run --download'}")
        if s["bulk_age_days"] is not None:
            print(f"  DB age          : {s['bulk_age_days']} days old")
        print(f"  Cards in DB     : {s['total_cards']:,}")
        print(f"  Enriched        : {s['enriched']:,}  ({s['pct']}%)")
        print(f"  Unenriched      : {s['unenriched']:,}")
        if s["unenriched"] > 0:
            print(f"\n  Run 'python -m scrapers.scryfall' to enrich remaining cards.")
        print()

    elif args.card:
        print_card(args.card, format_name=args.format)

    elif args.download:
        download_bulk_data(force=True)

    else:
        enrich_cards(force=args.force)
