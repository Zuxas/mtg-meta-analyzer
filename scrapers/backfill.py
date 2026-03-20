"""
Historical backfill scraper.

Pages backwards through MTGTop8 year-by-year, from today back to the
configured retention cutoff. Skips events already in the database.
Stops automatically when it reaches data older than the cutoff.

Usage:
    python -m scrapers.backfill                      # Standard, back to retention cutoff
    python -m scrapers.backfill --format pioneer
    python -m scrapers.backfill --format standard --since 2024-01-01
    python -m scrapers.backfill --dry-run            # list events only, no scraping
"""

import re
import time
import argparse
import configparser
import os
from datetime import datetime, timedelta
from scrapers.challenges import classify_event_type
from scrapers.mtgtop8 import (
    FORMATS, HEADERS, DELAY, BASE_URL,
    _get, _abs_url, _parse_event_id, _parse_deck_id,
    scrape_event_decks, scrape_deck_cards,
)
from db.database import get_connection, upsert_event, upsert_deck, insert_deck_cards, init_db
from db.maintenance import _parse_event_date

# Meta values per format per year on MTGTop8.
# Add new years here annually, or new formats as needed.
YEAR_META = {
    "standard": {
        2026: 341,
        2025: 312,
        2024: 281,
        2023: 250,
        2022: 249,
    },
    "pioneer": {
        2026: 340,
        2025: 311,
        2024: 280,
        2023: 248,
        2022: 247,
    },
    "modern": {
        2026: 339,
        2025: 310,
        2024: 279,
        2023: 246,
        2022: 245,
    },
    "legacy": {
        2026: 338,
        2025: 309,
        2024: 278,
        2023: 244,
        2022: 243,
    },
}


def _load_cutoff(format_name):
    """Read retention days from config and return the cutoff datetime."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(project_root, 'config.ini'))
    days = cfg.getint('retention', format_name, fallback=1095)
    return datetime.now() - timedelta(days=days)


def _get_existing_source_ids():
    """Return set of source_ids already in the active DB."""
    with get_connection() as conn:
        rows = conn.execute("SELECT source_id FROM events").fetchall()
    return {r['source_id'] for r in rows}


def _scrape_year_page(format_name, meta, page, cutoff, existing_ids):
    """
    Fetch one page of events for a given year meta filter.
    Returns (events_in_window, hit_cutoff).
    events_in_window: list of event dicts within the retention window, not yet in DB.
    hit_cutoff: True if any event on this page is older than cutoff.
    """
    from bs4 import BeautifulSoup
    code = FORMATS[format_name]
    url = f"{BASE_URL}/format?f={code}&meta={meta}&cp={page}"
    resp = _get(url)
    if not resp:
        return [], True  # treat fetch failure as end of data

    soup = BeautifulSoup(resp.text, "lxml")
    events_in_window = []
    hit_cutoff = False
    seen_on_page = set()

    for row in soup.select("tr.hover_tr"):
        link = row.select_one("td.S14 a[href*='event?e=']")
        if not link:
            continue
        event_url = _abs_url(link["href"])
        source_id = _parse_event_id(event_url)
        if not source_id or source_id in seen_on_page:
            continue
        seen_on_page.add(source_id)

        cells = row.find_all("td")
        date_str = cells[-1].get_text(strip=True) if cells else ""
        parsed_date = _parse_event_date(date_str)

        if parsed_date and parsed_date < cutoff:
            hit_cutoff = True
            continue  # don't include but keep checking the page

        name = link.get_text(strip=True)

        if source_id in existing_ids:
            continue  # already stored or seen this run — skip

        # Mark as seen immediately so it won't appear on subsequent pages
        existing_ids.add(source_id)

        events_in_window.append({
            "source_id": source_id,
            "name": name,
            "date": date_str,
            "url": event_url,
        })

    time.sleep(DELAY)
    return events_in_window, hit_cutoff


def _process_event(ev, format_name, event_type=None):
    event_type = event_type or classify_event_type(ev["name"])
    """Store one event and all its decks/cards. Returns deck count."""
    event_db_id = upsert_event(
        source="mtgtop8",
        source_id=ev["source_id"],
        name=ev["name"],
        date=ev["date"],
        fmt=format_name,
        url=ev["url"],
        event_type=event_type,
    )
    decks = scrape_event_decks(ev["source_id"], ev["url"])
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
    return len(decks)


def run_backfill(format_name="standard", since=None, dry_run=False):
    """
    Full backfill: iterate year-by-year, page-by-page, newest to oldest.
    Stops at the retention cutoff or when source data runs out.
    """
    cutoff = since if since else _load_cutoff(format_name)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    existing_ids = _get_existing_source_ids()

    year_metas = YEAR_META.get(format_name, {})
    if not year_metas:
        print(f"No year-meta mapping for format '{format_name}'. Add it to YEAR_META in backfill.py.")
        return

    # Cover years from current year down to the cutoff year
    current_year = datetime.now().year
    cutoff_year = cutoff.year
    years_to_cover = sorted(
        [y for y in year_metas if cutoff_year <= y <= current_year],
        reverse=True  # newest first
    )

    print(f"\n{'='*60}")
    print(f"  BACKFILL: {format_name.upper()} | Cutoff: {cutoff_str}")
    print(f"  Years: {years_to_cover} | Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    total_events = 0
    total_decks = 0

    for year in years_to_cover:
        meta = year_metas[year]
        print(f"-- {year} (meta={meta}) -----------------------------------")
        page = 1
        year_events = 0
        year_decks = 0

        while True:
            print(f"  Page {page}...", end=" ", flush=True)
            events, hit_cutoff = _scrape_year_page(
                format_name, meta, page, cutoff, existing_ids
            )

            skipped = "  [no new events on page]" if not events else ""
            print(f"{len(events)} new events{skipped}")

            for ev in events:
                parsed = _parse_event_date(ev['date'])
                date_display = parsed.strftime('%Y-%m-%d') if parsed else ev['date']
                print(f"    [{date_display}] {ev['name'][:45]}", end="")

                if dry_run:
                    print("  [DRY RUN — skipped]")
                else:
                    deck_count = _process_event(ev, format_name)
                    year_events += 1
                    year_decks += deck_count
                    existing_ids.add(ev['source_id'])
                    print(f"  — {deck_count} decks stored")

            if hit_cutoff:
                print(f"  Reached cutoff ({cutoff_str}) — stopping year {year}.")
                break

            if not events and page > 1:
                print(f"  No more pages for {year}.")
                break

            page += 1

        total_events += year_events
        total_decks += year_decks
        print(f"  {year} done: {year_events} events, {year_decks} decks stored.\n")

    print(f"{'-'*60}")
    print(f"  BACKFILL COMPLETE")
    print(f"  Total: {total_events} events, {total_decks} decks stored")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MTG Meta Analyzer — historical backfill")
    parser.add_argument("--format", default="standard", choices=list(FORMATS.keys()))
    parser.add_argument(
        "--since",
        help="Override cutoff date (YYYY-MM-DD). Default: config retention window.",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=None,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="List events that would be scraped without storing anything")
    args = parser.parse_args()

    init_db()
    run_backfill(format_name=args.format, since=args.since, dry_run=args.dry_run)
