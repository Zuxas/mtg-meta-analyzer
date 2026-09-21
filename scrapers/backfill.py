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
import sys
import io
import time
import argparse
import configparser
import os
from datetime import datetime, timedelta
from scrapers.challenges import classify_event_type
from scrapers.mtgtop8 import (
    FORMATS, DELAY, BASE_URL,
    _get, _abs_url, _parse_event_id, _parse_deck_id,
    scrape_event_decks, scrape_deck_cards,
)
from db.database import get_connection, upsert_event, upsert_deck, insert_deck_cards, init_db
from db.maintenance import _parse_event_date

# FALLBACK year -> MTGTop8 `meta` filter ids, used only when the live format
# page cannot be fetched (fetch_year_metas). Captured from the live pages on
# 2026-09-21. The previous table was extrapolated from Standard (minus 1/2/3)
# and was WRONG for Pioneer/Modern/Legacy 2022-2025 -- an unknown id makes
# MTGTop8 fall back to the format's CURRENT listing, so every historical
# backfill of those years silently re-listed the current year and stored
# nothing. Pauper and Vintage were absent entirely.
YEAR_META = {
    "standard": {2026: 341, 2025: 312, 2024: 281, 2023: 250, 2022: 249},
    "pioneer":  {2026: 340, 2025: 314, 2024: 277, 2023: 247, 2022: 235},
    "modern":   {2026: 339, 2025: 315, 2024: 276, 2023: 246, 2022: 236},
    "legacy":   {2026: 338, 2025: 316, 2024: 275, 2023: 245, 2022: 237},
    "vintage":  {2026: 337, 2025: 317, 2024: 274, 2023: 244, 2022: 238},
    "pauper":   {2026: 342, 2025: 311, 2024: 282, 2023: 251, 2022: 239},
}

_YEAR_LINK = re.compile(
    r'href="\?f=(\w+)&meta=(\d+)&a="><div[^>]*>All (20\d\d) Decks</div>')


def fetch_year_metas(format_name):
    """
    {year: meta} for `format_name`, parsed from the live MTGTop8 format page
    ("All 2025 Decks" links). {} when the page cannot be fetched -- callers
    fall back to YEAR_META and say so.
    """
    code = FORMATS[format_name]
    resp = _get(f"{BASE_URL}/format?f={code}")
    if not resp:
        return {}
    return {int(year): int(meta)
            for fmt, meta, year in _YEAR_LINK.findall(resp.text) if fmt == code}


class BackfillFetchError(RuntimeError):
    """A listing page could not be fetched even after retries.

    Raised instead of pretending the year is finished: on 2026-09-21 a DNS
    blip made every remaining year and format look like it had "reached the
    cutoff" and fill_database.py printed COMPLETE with four formats at +0.
    """


class BackfillConfigError(RuntimeError):
    """The format has no YEAR_META mapping (was a print + silent return)."""


# Listing-page fetch retry: DNS blips / connection resets last seconds to
# minutes; give them a few minutes before giving up on the format.
PAGE_FETCH_ATTEMPTS = 4
PAGE_FETCH_BACKOFF = (30, 60, 120)   # seconds between attempts

# Per-event fetch failures are tolerated in isolation (a single dead page),
# but this many IN A ROW means the network / host is gone: abort the format.
MAX_CONSECUTIVE_EVENT_FAILURES = 5

# Hard ceiling on listing pages per year (a year is ~30-70 pages at MTGTop8's
# ~25 events per page); protects against a pathological pager.
MAX_PAGES_PER_YEAR = 400


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
    Returns (events_in_window, hit_cutoff, page_ids).
    events_in_window: list of event dicts within the retention window, not yet in DB.
    hit_cutoff: True if any event on this page is older than cutoff.
    page_ids: EVERY event id seen on the page, new or already stored -- the
              caller needs it to tell "a page of known events" (keep paging)
              from "an empty page" (end of year). Until 2026-09-21 those were
              indistinguishable and Modern 2026 stopped after page 2.
    """
    from bs4 import BeautifulSoup
    code = FORMATS[format_name]
    url = f"{BASE_URL}/format?f={code}&meta={meta}&cp={page}"
    resp = _get(url)
    if not resp:
        # NOT end-of-data. The caller retries with backoff and then aborts
        # the format; treating this as "hit cutoff" silently skipped years.
        raise BackfillFetchError(url)

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
    return events_in_window, hit_cutoff, seen_on_page


def _delete_event(event_db_id):
    """Remove an event and everything under it (rollback of a partial fetch)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM deck_cards WHERE deck_id IN "
                     "(SELECT id FROM decks WHERE event_id=?)", (event_db_id,))
        conn.execute("DELETE FROM decks WHERE event_id=?", (event_db_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_db_id,))


def _process_event(ev, format_name, event_type=None):
    """Store one event and ALL its decks/cards, or nothing. Returns (deck_count, ok).

    An event is kept only when fully fetched. If the event page or ANY deck
    page fails, the event is rolled back (event + decks + cards) so the next
    run re-lists and re-fetches it. Before 2026-09-21 the event row was kept
    regardless -- 17 zero-deck events and one with 14 card-less decks were
    left behind by a DNS blip, and `existing_ids` would have skipped them on
    every future run.
    """
    event_type = event_type or classify_event_type(ev["name"])
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
    if not decks:
        # fetch failure or an empty event page: either way nothing usable
        _delete_event(event_db_id)
        return 0, False
    for dk in decks:
        mainboard, sideboard = scrape_deck_cards(dk["url"])
        if not mainboard:
            _delete_event(event_db_id)
            return 0, False
        deck_db_id = upsert_deck(
            event_id=event_db_id,
            source_id=dk["source_id"],
            player=dk["player"],
            archetype=dk["archetype"],
            placement=dk["placement"],
            url=dk["url"],
        )
        insert_deck_cards(deck_db_id, mainboard, sideboard)
    return len(decks), True


def run_backfill(format_name="standard", since=None, dry_run=False):
    """
    Full backfill: iterate year-by-year, page-by-page, newest to oldest.
    Stops at the retention cutoff or when source data runs out.
    """
    cutoff = since if since else _load_cutoff(format_name)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    existing_ids = _get_existing_source_ids()

    table = YEAR_META.get(format_name, {})
    year_metas = fetch_year_metas(format_name)
    if year_metas:
        stale = {y: (table.get(y), m) for y, m in year_metas.items()
                 if y in table and table[y] != m}
        if stale:
            print(f"  [warn] YEAR_META fallback table is stale for {format_name} "
                  f"(year: (table, live)) {stale} -- using live ids; update backfill.py")
    else:
        year_metas = table
        if year_metas:
            print(f"  [warn] could not fetch the MTGTop8 format page; using the YEAR_META "
                  f"fallback table for {format_name}")
    if not year_metas:
        raise BackfillConfigError(
            f"No year-meta mapping for format '{format_name}' (live page unreachable and "
            f"no YEAR_META fallback). Add it to YEAR_META in backfill.py.")

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
    transient_failures = 0
    event_failures = 0
    consecutive_failures = 0
    total_decks = 0

    for year in years_to_cover:
        meta = year_metas[year]
        print(f"-- {year} (meta={meta}) -----------------------------------")
        page = 1
        year_events = 0
        year_decks = 0
        prev_page_ids = None

        while True:
            print(f"  Page {page}...", end=" ", flush=True)
            for attempt in range(1, PAGE_FETCH_ATTEMPTS + 1):
                try:
                    events, hit_cutoff, page_ids = _scrape_year_page(
                        format_name, meta, page, cutoff, existing_ids
                    )
                    break
                except BackfillFetchError as e:
                    if attempt == PAGE_FETCH_ATTEMPTS:
                        print(f"\n  [abort] listing page failed {attempt}x: {e}")
                        raise
                    wait = PAGE_FETCH_BACKOFF[min(attempt, len(PAGE_FETCH_BACKOFF)) - 1]
                    transient_failures += 1
                    print(f"\n  [retry {attempt}/{PAGE_FETCH_ATTEMPTS - 1}] fetch failed, "
                          f"waiting {wait}s: {e}")
                    time.sleep(wait)

            skipped = f"  [no new events on page; {len(page_ids)} known]" if not events else ""
            print(f"{len(events)} new events{skipped}")

            for ev in events:
                parsed = _parse_event_date(ev['date'])
                date_display = parsed.strftime('%Y-%m-%d') if parsed else ev['date']
                print(f"    [{date_display}] {ev['name'][:45]}", end="")

                if dry_run:
                    print("  [DRY RUN — skipped]")
                else:
                    deck_count, ok = _process_event(ev, format_name)
                    if ok:
                        year_events += 1
                        year_decks += deck_count
                        existing_ids.add(ev['source_id'])
                        consecutive_failures = 0
                        print(f"  — {deck_count} decks stored")
                    else:
                        event_failures += 1
                        consecutive_failures += 1
                        print("  — FETCH FAILED, rolled back (will retry next run)")
                        if consecutive_failures >= MAX_CONSECUTIVE_EVENT_FAILURES:
                            raise BackfillFetchError(
                                f"{consecutive_failures} consecutive event fetch failures "
                                f"in {format_name} {year} -- host/network down, aborting format")

            if hit_cutoff:
                print(f"  Reached cutoff ({cutoff_str}) — stopping year {year}.")
                break

            # End of year = an EMPTY page, or the site repeating the last page
            # past the end. A page of already-known events is neither: keep
            # paging (older events on later pages may still be missing).
            if not page_ids:
                print(f"  No more pages for {year}.")
                break
            if page_ids == prev_page_ids:
                print(f"  Page {page} repeats page {page - 1} — end of {year}.")
                break
            if page >= MAX_PAGES_PER_YEAR:
                print(f"  [warn] hit MAX_PAGES_PER_YEAR={MAX_PAGES_PER_YEAR} for {year}; stopping.")
                break
            prev_page_ids = page_ids
            page += 1

        total_events += year_events
        total_decks += year_decks
        print(f"  {year} done: {year_events} events, {year_decks} decks stored.\n")

    print(f"{'-'*60}")
    print(f"  BACKFILL COMPLETE")
    print(f"  Total: {total_events} events, {total_decks} decks stored"
          + (f"  ({transient_failures} transient fetch failures recovered)" if transient_failures else ""))
    print(f"{'='*60}\n")
    return {"format": format_name, "events": total_events, "decks": total_decks,
            "years": years_to_cover, "transient_failures": transient_failures,
            "event_failures": event_failures}


if __name__ == "__main__":
    # Force UTF-8 output so event names with special characters don't crash on Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MTG Meta Analyzer -- historical backfill")
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
