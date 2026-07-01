"""
Scraper for MTGTop8 (https://www.mtgtop8.com)
Pulls recent tournament events, decklists, and card data.
"""

import re
import time
import requests
from bs4 import BeautifulSoup

from scrapers.constants import (
    URL_MTGTOP8 as BASE_URL,
    FORMATS_MTGTOP8 as FORMATS,
    DELAY_DEFAULT as DELAY,
)
from scrapers import polite_client


def _get(url, retries=3):
    """Fetch via the shared polite client (honest UA + per-host rate limit +
    circuit breaker + robots). Preserves the legacy contract: returns a
    response-like object on success, or None on any failure. The `retries`
    arg is kept for call-site compatibility; backoff is owned by polite_client.
    """
    try:
        # PoliteResponse exposes .text/.ok/.status_code like requests.Response.
        return polite_client.get(url)
    except (polite_client.PoliteClientError, requests.RequestException) as e:
        # PoliteClientError is the base of RobotsDisallowed/HostCircuitOpen.
        print(f"  [warn] fetch failed for {url}: {e}")
        return None


def _parse_event_id(url):
    m = re.search(r'[?&]e=(\d+)', url)
    return m.group(1) if m else None


def _parse_deck_id(url):
    m = re.search(r'[?&]d=(\d+)', url)
    return m.group(1) if m else None


def _abs_url(href):
    """Convert a relative MTGTop8 href to an absolute URL."""
    href = href.lstrip("/")
    if href.startswith("?"):
        return f"{BASE_URL}/event{href}"
    if href.startswith("event"):
        return f"{BASE_URL}/{href}"
    return f"{BASE_URL}/{href}"


def _normalize_date(date_str):
    """Convert DD/MM/YY or DD/MM/YYYY to YYYY-MM-DD. Pass through anything else."""
    if not date_str or '/' not in date_str:
        return date_str
    parts = date_str.strip().split('/')
    if len(parts) != 3:
        return date_str
    day, month, year = parts
    if len(year) == 2:
        year = '20' + year
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def scrape_format_events(format_name, pages=1):
    """
    Fetch recent event listings for a format.
    Returns list of dicts: {source_id, name, date, url}
    """
    code = FORMATS.get(format_name.lower())
    if not code:
        raise ValueError(f"Unknown format '{format_name}'. Choose from: {list(FORMATS)}")

    events = []
    seen = set()

    for page in range(1, pages + 1):
        url = f"{BASE_URL}/format?f={code}&meta=58&cp={page}"
        print(f"Fetching event list: {url}")
        resp = _get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Events are in tr.hover_tr rows; the event link is in td.S14
        for row in soup.select("tr.hover_tr"):
            link = row.select_one("td.S14 a[href*='event?e=']")
            if not link:
                continue
            event_url = _abs_url(link["href"])
            source_id = _parse_event_id(event_url)
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)

            name = link.get_text(strip=True)
            # Date is the last cell of the row
            cells = row.find_all("td")
            date = cells[-1].get_text(strip=True) if cells else ""

            events.append({
                "source_id": source_id,
                "name": name,
                "date": _normalize_date(date),
                "url": event_url,
            })

        time.sleep(DELAY)

    print(f"Found {len(events)} events for {format_name}")
    return events


def scrape_event_decks(event_source_id, event_url):
    """
    Fetch all decks listed on a single event page.
    Returns list of dicts: {source_id, player, archetype, placement, url}
    """
    print(f"  Fetching event {event_source_id}: {event_url}")
    resp = _get(event_url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    decks = []
    seen = set()

    # Each deck entry: a plain div (no class) containing div.S14 > a[href*=d=]
    # The plain div's text is "Archetype|Player"
    for s14 in soup.select("div.S14"):
        link = s14.find("a", href=re.compile(r'd=\d+'))
        if not link:
            continue
        deck_url = _abs_url(link["href"])
        deck_id = _parse_deck_id(deck_url)
        if not deck_id or deck_id in seen:
            continue
        seen.add(deck_id)

        archetype = link.get_text(strip=True)

        # Player name is in the parent div, outside the S14
        parent = s14.find_parent("div")
        if parent:
            parts = [t.strip() for t in parent.get_text(separator="|").split("|") if t.strip()]
            # parts[0] = archetype, parts[1] = player (if present)
            player = parts[1] if len(parts) > 1 else ""
            # Ignore navigation text that slipped in
            if len(player) > 40 or "Switch" in player:
                player = ""
        else:
            player = ""

        decks.append({
            "source_id": deck_id,
            "player": player,
            "archetype": archetype,
            "placement": len(decks) + 1,
            "url": deck_url,
        })

    time.sleep(DELAY)
    return decks


def scrape_deck_cards(deck_url):
    """
    Fetch mainboard and sideboard from a deck page.
    Returns (mainboard, sideboard) as {card_name: quantity}.
    """
    resp = _get(deck_url)
    if not resp:
        return {}, {}

    soup = BeautifulSoup(resp.text, "lxml")
    mainboard = {}
    sideboard = {}

    # Cards are in div.deck_line elements.
    # Section headers are div.O14 — "SIDEBOARD" marks the switch to side cards.
    in_sideboard = False
    for div in soup.find_all("div"):
        cls = div.get("class") or []

        if "O14" in cls:
            if "SIDEBOARD" in div.get_text(strip=True).upper():
                in_sideboard = True
            continue

        if "deck_line" in cls:
            text = div.get_text(strip=True)
            # Format: "4Monastery Swiftspear" or "15Mountain"
            m = re.match(r'^(\d+)(.+)$', text)
            if m:
                qty = int(m.group(1))
                name = m.group(2).strip()
                if name:
                    if in_sideboard:
                        sideboard[name] = sideboard.get(name, 0) + qty
                    else:
                        mainboard[name] = mainboard.get(name, 0) + qty

    time.sleep(DELAY)
    return mainboard, sideboard


def run(format_name="standard", pages=1, max_events=10):
    """
    Full pipeline: scrape events -> decks -> cards -> store in DB.
    """
    from datetime import datetime
    from db.database import upsert_event, upsert_deck, insert_deck_cards

    print(f"\n=== Scraping MTGTop8 | Format: {format_name.upper()} | Pages: {pages} ===")
    print(f"    Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    events = scrape_format_events(format_name, pages=pages)
    events = events[:max_events]

    for ev in events:
        event_db_id = upsert_event(
            source="mtgtop8",
            source_id=ev["source_id"],
            name=ev["name"],
            date=ev["date"],
            fmt=format_name,
            url=ev["url"],
        )

        decks = scrape_event_decks(ev["source_id"], ev["url"])
        print(f"    {len(decks)} decks found")

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
                # Card-based reclassification: ONLY for junk/empty names
                _JUNK = {"", "Decklist", "All Other Decklists", "Rogue Decklists",
                          "Others", "Other", "Unclassified"}
                if dk["archetype"] in _JUNK:
                    try:
                        from analysis.archetype_classifier import classify_by_cards
                        classified = classify_by_cards(mainboard, format_name)
                        if classified:
                            from db.database import get_connection
                            with get_connection() as conn:
                                conn.execute("UPDATE decks SET archetype=? WHERE id=?",
                                             (classified, deck_db_id))
                            dk["archetype"] = classified
                    except Exception:
                        pass

                    # Layer 4: KNN embedding fallback (if card-based classifier failed)
                    if dk["archetype"] in _JUNK:
                        try:
                            from analysis.knn_classifier import classify_deck
                            knn_result = classify_deck(mainboard, format_name)
                            if knn_result:
                                predicted, confidence = knn_result
                                if confidence >= 0.6:
                                    from db.database import get_connection
                                    with get_connection() as conn:
                                        conn.execute("UPDATE decks SET archetype=? WHERE id=?",
                                                     (predicted, deck_db_id))
                                    dk["archetype"] = predicted
                        except Exception:
                            pass
                insert_deck_cards(deck_db_id, mainboard, sideboard)
                print(f"      [{dk['placement']}] {dk['archetype'][:30]:<30} "
                      f"{dk['player']:<15} "
                      f"— {sum(mainboard.values())}main/{sum(sideboard.values())}side")

    print("\n=== Done ===")
