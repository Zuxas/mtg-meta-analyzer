"""
Scraper for Spicerack (https://spicerack.gg) - local tournament results.

Spicerack hosts RCQs, Store Championships, and large cash events.
This fills a gap in the DB: competitive paper events below the PT/RC
level that MTGTop8 doesn't cover.

Public API (no auth required):
  GET https://api.spicerack.gg/api/export-decklists/
  Params: event_format (e.g. "Modern"), num_days (default 14)

Decklists link to Moxfield. We fetch the full 75 via the Moxfield API.

Usage:
    python -m scrapers.spicerack_scraper --format modern --days 30
    python -m scrapers.spicerack_scraper --format modern --days 30 --dry-run
    python -m scrapers.spicerack_scraper --counts
    python -m scrapers.spicerack_scraper --all-formats --days 14
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, UTC

SPICERACK_API   = "https://api.spicerack.gg/api/export-decklists/"
MOXFIELD_API    = "https://api2.moxfield.com/v2/decks/all/{deck_id}"
REQUEST_DELAY   = 0.5   # seconds between Moxfield calls

HEADERS_SPICE = {"User-Agent": "mtg-meta-analyzer/1.0"}
HEADERS_MOX   = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.moxfield.com/",
}

# Spicerack format names -> DB format strings
FORMAT_MAP = {
    "modern":   "modern",
    "standard": "standard",
    "pioneer":  "pioneer",
    "legacy":   "legacy",
    "pauper":   "pauper",
    "historic": "historic",
    "explorer": "explorer",
    "timeless": "timeless",
    "vintage":  "vintage",
}

# All formats worth scraping for competitive prep
ALL_FORMATS = ["Modern", "Standard", "Pioneer", "Legacy", "Pauper"]

# Minimum players to consider an event worth importing
MIN_PLAYERS = 16


def _infer_event_type(name: str) -> str:
    """Infer event type from tournament name for event_type column."""
    name_lower = name.lower()
    if "regional championship qualifier" in name_lower or " rcq" in name_lower:
        return "rcq"
    if "store championship" in name_lower:
        return "store_championship"
    if "regional championship" in name_lower:
        return "regional_championship"
    if "pro tour" in name_lower:
        return "pro_tour"
    if "grand prix" in name_lower or " gp " in name_lower:
        return "grand_prix"
    # Large cash events (3k, 5k, $1000, $5000, etc.)
    if re.search(r'\$\d{3,}|\d+k\b', name_lower):
        return "open"
    return "paper"


def _get_json(url: str, headers: dict, timeout: int = 15) -> object:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_tournaments(event_format: str, num_days: int = 30) -> list[dict]:
    """Fetch recent tournaments from Spicerack for a given format."""
    url = f"{SPICERACK_API}?event_format={event_format}&num_days={num_days}"
    print(f"  Spicerack: {event_format} last {num_days} days -> {url}")
    try:
        data = _get_json(url, HEADERS_SPICE)
        if not isinstance(data, list):
            print(f"  [warn] unexpected response type: {type(data)}")
            return []
        filtered = [t for t in data if t.get("players", 0) >= MIN_PLAYERS]
        print(f"  Found {len(data)} events, {len(filtered)} with {MIN_PLAYERS}+ players")
        return filtered
    except Exception as e:
        print(f"  [error] Spicerack fetch failed: {e}")
        return []


def _extract_moxfield_id(url: str) -> str | None:
    """Extract deck ID from a Moxfield URL."""
    if not url or "moxfield.com" not in url:
        return None
    return url.rstrip("/").split("/")[-1] or None


def fetch_moxfield_deck(moxfield_url: str) -> tuple[dict, dict] | None:
    """
    Fetch mainboard and sideboard from Moxfield.
    Returns ({card_name: qty}, {card_name: qty}) or None on failure.
    """
    deck_id = _extract_moxfield_id(moxfield_url)
    if not deck_id:
        return None

    api_url = MOXFIELD_API.format(deck_id=deck_id)
    try:
        data = _get_json(api_url, HEADERS_MOX)
    except Exception as e:
        print(f"    [warn] Moxfield fetch failed for {deck_id}: {e}")
        return None

    mainboard = {}
    for entry in data.get("mainboard", {}).values():
        name = entry.get("card", {}).get("name")
        qty  = entry.get("quantity", 1)
        if name:
            mainboard[name] = mainboard.get(name, 0) + qty

    sideboard = {}
    for entry in data.get("sideboard", {}).values():
        name = entry.get("card", {}).get("name")
        qty  = entry.get("quantity", 1)
        if name:
            sideboard[name] = sideboard.get(name, 0) + qty

    return (mainboard, sideboard) if (mainboard or sideboard) else None


def scrape_format(event_format: str, num_days: int = 30, dry_run: bool = False,
                  top_n: int = 8) -> dict:
    """
    Scrape Spicerack for a format and store in the meta-analyzer DB.

    Args:
        event_format: Spicerack format name (e.g. "Modern")
        num_days: How far back to look
        dry_run: If True, fetch but don't write to DB
        top_n: How many top finishers per event to import (default 8 = Top 8)

    Returns:
        Stats dict: events_added, decks_added, cards_total
    """
    from db.database import upsert_event, upsert_deck, insert_deck_cards

    fmt_lower = event_format.lower()
    db_format = FORMAT_MAP.get(fmt_lower, fmt_lower)

    tournaments = fetch_tournaments(event_format, num_days)
    if not tournaments:
        return {"events_added": 0, "decks_added": 0, "cards_total": 0}

    stats = {"events_added": 0, "decks_added": 0, "cards_total": 0}

    for t in tournaments:
        tid        = str(t.get("TID", ""))
        name       = t.get("tournamentName", "Unknown")
        players    = t.get("players", 0)
        bracket_url = t.get("bracketUrl", "")
        standings  = t.get("standings", [])
        event_type = _infer_event_type(name)

        # Convert Unix timestamp to YYYY-MM-DD
        start_ts = t.get("startDate")
        if isinstance(start_ts, (int, float)):
            date_str = datetime.fromtimestamp(start_ts, tz=UTC).strftime("%Y-%m-%d")
        else:
            date_str = datetime.now(UTC).strftime("%Y-%m-%d")

        print(f"\n  [{tid}] {name} | {players}p | {event_type}")
        print(f"    date={date_str} | {len(standings)} standings")

        if dry_run:
            for rank, s in enumerate(standings[:top_n], 1):
                deck_url = s.get("decklist", "")
                print(f"    #{rank} {s.get('name','?')} -> {deck_url or '(no decklist)'}")
            stats["events_added"] += 1
            stats["decks_added"] += min(len(standings), top_n)
            continue

        # Store event
        event_id = upsert_event(
            source="spicerack",
            source_id=tid,
            name=name,
            date=date_str,
            fmt=db_format,
            url=bracket_url,
            event_type=event_type,
        )
        stats["events_added"] += 1

        # Store top-N finishers
        decks_this_event = 0
        for rank, s in enumerate(standings[:top_n], 1):
            player   = s.get("name", "Unknown")
            deck_url = s.get("decklist", "")

            if not deck_url:
                print(f"    #{rank} {player} — no decklist, skipping")
                continue

            # Fetch full decklist from Moxfield
            deck_data = fetch_moxfield_deck(deck_url)
            if deck_data is None:
                print(f"    #{rank} {player} — Moxfield fetch failed, skipping")
                continue
            mainboard, sideboard = deck_data

            deck_id = upsert_deck(
                event_id=event_id,
                source_id=f"spicerack-{tid}-{rank}",
                player=player,
                archetype=None,      # Let KNN classifier handle it
                placement=rank,
                url=deck_url,
            )
            insert_deck_cards(deck_id, mainboard, sideboard)

            total_cards = sum(mainboard.values()) + sum(sideboard.values())
            print(f"    #{rank} {player} -> {total_cards} cards stored")
            stats["decks_added"] += 1
            stats["cards_total"] += total_cards

            time.sleep(REQUEST_DELAY)

        print(f"    Stored {decks_this_event} decks for this event")

    return stats


def show_counts():
    """Show how many Spicerack events/decks are in the DB."""
    from db.database import get_connection
    with get_connection() as conn:
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE source='spicerack'"
        ).fetchone()[0]
        decks = conn.execute(
            "SELECT COUNT(*) FROM decks d JOIN events e ON e.id=d.event_id "
            "WHERE e.source='spicerack'"
        ).fetchone()[0]
        by_format = conn.execute(
            "SELECT format, COUNT(*) FROM events WHERE source='spicerack' "
            "GROUP BY format ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_type = conn.execute(
            "SELECT event_type, COUNT(*) FROM events WHERE source='spicerack' "
            "GROUP BY event_type ORDER BY COUNT(*) DESC"
        ).fetchall()
    print(f"\nSpicerack in DB: {events} events, {decks} decks")
    if by_format:
        print("By format:", ", ".join(f"{r[0]}={r[1]}" for r in by_format))
    if by_type:
        print("By type:  ", ", ".join(f"{r[0]}={r[1]}" for r in by_type))


def main():
    ap = argparse.ArgumentParser(description="Spicerack RCQ/paper event scraper")
    ap.add_argument("--format", default="Modern",
                    help="Format to scrape (default: Modern)")
    ap.add_argument("--all-formats", action="store_true",
                    help=f"Scrape all competitive formats: {ALL_FORMATS}")
    ap.add_argument("--days", type=int, default=30,
                    help="Days to look back (default: 30)")
    ap.add_argument("--top-n", type=int, default=8,
                    help="Top finishers per event to import (default: 8)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print without writing to DB")
    ap.add_argument("--counts", action="store_true",
                    help="Show current Spicerack counts in DB and exit")
    args = ap.parse_args()

    if args.counts:
        show_counts()
        return

    formats = ALL_FORMATS if args.all_formats else [args.format]

    total = {"events_added": 0, "decks_added": 0, "cards_total": 0}
    for fmt in formats:
        print(f"\n{'='*60}")
        print(f"Scraping Spicerack: {fmt}")
        print(f"{'='*60}")
        stats = scrape_format(fmt, num_days=args.days, dry_run=args.dry_run,
                              top_n=args.top_n)
        for k in total:
            total[k] += stats[k]

    print(f"\n{'='*60}")
    print(f"DONE: {total['events_added']} events, {total['decks_added']} decks, "
          f"{total['cards_total']} cards")
    if args.dry_run:
        print("(dry-run - nothing written to DB)")


if __name__ == "__main__":
    main()
