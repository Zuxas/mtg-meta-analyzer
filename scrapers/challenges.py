"""
MTGO Challenge Scraper
Targets specifically MTGO Challenge events on MTGTop8 (Challenge 32, Challenge 64).

Usage:
    python -m scrapers.challenges                        # Pioneer, last 2 pages
    python -m scrapers.challenges --format modern
    python -m scrapers.challenges --format standard --pages 3
    python -m scrapers.challenges --list-only            # show events without scraping decks
"""

import re
import argparse
from db.database import init_db, upsert_event, upsert_deck, insert_deck_cards
from scrapers.mtgtop8 import (
    scrape_format_events,
    scrape_event_decks,
    scrape_deck_cards,
    FORMATS,
)

# Keywords that identify MTGO Challenge events
CHALLENGE_KEYWORDS = ["challenge", "challenge 32", "challenge 64"]


def classify_event_type(name):
    """Return a clean event_type string based on the event name."""
    lower = name.lower()
    if "challenge 64" in lower:
        return "mtgo_challenge_64"
    if "challenge 32" in lower or "challenge" in lower:
        return "mtgo_challenge_32"
    if "league" in lower:
        return "mtgo_league"
    if "preliminary" in lower:
        return "mtgo_preliminary"
    return "paper"


def is_challenge(name):
    lower = name.lower()
    return any(kw in lower for kw in CHALLENGE_KEYWORDS)


def scrape_challenges(format_name="standard", pages=2, list_only=False):
    """
    Scrape MTGO Challenge events for a given format.
    Only stores events whose name contains 'Challenge'.
    """
    print(f"\n=== MTGO Challenge Scraper | Format: {format_name.upper()} ===\n")

    all_events = scrape_format_events(format_name, pages=pages)
    challenge_events = [ev for ev in all_events if is_challenge(ev["name"])]

    print(f"Found {len(challenge_events)} Challenge events (from {len(all_events)} total)\n")

    if list_only:
        for ev in challenge_events:
            print(f"  [{ev['date']}] {ev['name']}  (id={ev['source_id']})")
        return

    for ev in challenge_events:
        event_type = classify_event_type(ev["name"])
        event_db_id = upsert_event(
            source="mtgtop8",
            source_id=ev["source_id"],
            name=ev["name"],
            date=ev["date"],
            fmt=format_name,
            url=ev["url"],
            event_type=event_type,
        )

        print(f"[{ev['date']}] {ev['name']} (type={event_type})")
        decks = scrape_event_decks(ev["source_id"], ev["url"])
        print(f"  {len(decks)} decks")

        for dk in decks:
            deck_db_id = upsert_deck(
                event_id=event_db_id,
                source_id=dk["source_id"],
                player=dk["player"],
                archetype=dk["archetype"],
                placement=dk["placement"],
                url=dk["url"],
            )
            mainboard, sideboard = scrape_deck_cards(dk["url"])
            if mainboard:
                insert_deck_cards(deck_db_id, mainboard, sideboard)
                main_count = sum(mainboard.values())
                side_count = sum(sideboard.values())
                status = f"{main_count}main/{side_count}side"
                print(f"    [{dk['placement']:>2}] {dk['archetype'][:28]:<28} "
                      f"{dk['player']:<16} {status}")

    print("\n=== Done ===")


def get_latest_challenge(format_name="pioneer", event_type="mtgo_challenge_32"):
    """
    Query the DB for the most recent challenge of a given type and format.
    Returns the event row or None.
    """
    from db.database import get_connection
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM events
            WHERE format = ? AND event_type = ?
            ORDER BY (CASE WHEN instr(date,'/')>0
                          THEN '20'||substr(date,7,2)||substr(date,4,2)||substr(date,1,2)
                          ELSE replace(date,'-','') END) DESC
            LIMIT 1
        """, (format_name, event_type)).fetchone()
    return dict(row) if row else None


def get_challenge_decks(event_id):
    """
    Return all decks for a given event_id, sorted by placement.
    Each deck includes its full mainboard and sideboard.
    """
    from db.database import get_connection
    with get_connection() as conn:
        decks = conn.execute("""
            SELECT d.id, d.player, d.archetype, d.placement, d.url
            FROM decks d
            WHERE d.event_id = ?
            ORDER BY d.placement
        """, (event_id,)).fetchall()

        result = []
        for deck in decks:
            deck_id = deck["id"]
            cards = conn.execute("""
                SELECT c.name, dc.quantity, dc.is_sideboard
                FROM deck_cards dc
                JOIN cards c ON c.id = dc.card_id
                WHERE dc.deck_id = ?
                ORDER BY dc.is_sideboard, c.name
            """, (deck_id,)).fetchall()

            mainboard = {r["name"]: r["quantity"] for r in cards if not r["is_sideboard"]}
            sideboard = {r["name"]: r["quantity"] for r in cards if r["is_sideboard"]}

            result.append({
                "id": deck_id,
                "player": deck["player"],
                "archetype": deck["archetype"],
                "placement": deck["placement"],
                "url": deck["url"],
                "mainboard": mainboard,
                "sideboard": sideboard,
            })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MTGO Challenge scraper")
    parser.add_argument("--format", default="standard", choices=list(FORMATS.keys()))
    parser.add_argument("--pages", type=int, default=2,
                        help="Pages of event listings to check (default: 2)")
    parser.add_argument("--list-only", action="store_true",
                        help="List found Challenge events without scraping decks")
    args = parser.parse_args()

    init_db()
    scrape_challenges(
        format_name=args.format,
        pages=args.pages,
        list_only=args.list_only,
    )
