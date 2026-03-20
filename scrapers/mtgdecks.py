"""
Scraper for MTGDecks.net (https://mtgdecks.net)
Second data source complementing MTGTop8.

Pulls tournament events, decklists, and card data.
Uses cloudscraper (Chrome TLS fingerprint) to bypass Cloudflare 403s.

Usage:
    python -m scrapers.mtgdecks                        # Standard, latest page
    python -m scrapers.mtgdecks --format pioneer
    python -m scrapers.mtgdecks --pages 3              # first 3 pages
    python -m scrapers.mtgdecks --min-players 32       # lower threshold (default 50)
    python -m scrapers.mtgdecks --dry-run              # list events only
"""

import re
import time
import random
import argparse
import io
import sys
from datetime import datetime, date

import cloudscraper
from bs4 import BeautifulSoup

from db.database import get_connection, upsert_event, upsert_deck, insert_deck_cards, init_db
from scrapers.challenges import classify_event_type

BASE_URL = "https://mtgdecks.net"

# Format name -> MTGDecks.net URL segment
FORMATS = {
    "standard":  "Standard",
    "pioneer":   "Pioneer",
    "modern":    "Modern",
    "legacy":    "Legacy",
    "vintage":   "Vintage",
    "pauper":    "Pauper",
}

DELAY_MIN = 2.5
DELAY_MAX = 5.0

# High-signal event keywords — always include regardless of player count
HIGH_SIGNAL_KEYWORDS = [
    "challenge", "showcase", "qualifier", "rcq", "pro tour",
    "regional championship", "magic con", "grand prix", "open",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_session = None


def _get_session():
    """Return a cloudscraper session, initialising with a homepage visit."""
    global _session
    if _session is None:
        _session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        _session.headers.update(HEADERS)
        try:
            resp = _session.get(BASE_URL + "/", timeout=20)
            resp.raise_for_status()
            print(f"  [session] ready (homepage {resp.status_code})")
        except Exception as e:
            print(f"  [warn] homepage warm-up failed: {e}")
    return _session


def _get(url, referer=None, retries=3):
    """GET with session cookies, browser headers, and random delay."""
    sess = _get_session()
    headers = {}
    if referer:
        headers["Referer"] = referer

    for attempt in range(retries):
        try:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            resp = sess.get(url, headers=headers, timeout=25)
            if resp.status_code == 403:
                print(f"  [403] attempt {attempt+1}/{retries}: {url}")
                if attempt < retries - 1:
                    time.sleep(random.uniform(5, 10))
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            print(f"  [warn] attempt {attempt+1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(random.uniform(3, 6))
    return None


def _parse_date(date_str):
    """
    Parse MTGDecks date formats: '20-Mar', '14-Mar', etc.
    Returns a datetime or None.
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    # "DD-Mon" — assume current year, roll back if in the future
    try:
        parsed = datetime.strptime(f"{date_str}-{datetime.now().year}", "%d-%b-%Y")
        if parsed.date() > date.today():
            parsed = parsed.replace(year=parsed.year - 1)
        return parsed
    except ValueError:
        pass
    # Full ISO date
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        pass
    return None


def _is_high_signal(name, player_count, min_players=50):
    """Return True if this event is worth scraping."""
    name_lower = name.lower()
    if any(kw in name_lower for kw in HIGH_SIGNAL_KEYWORDS):
        return True
    if player_count is not None and player_count >= min_players:
        return True
    return False


def _existing_source_ids():
    """Return set of source_ids from mtgdecks source already in the DB."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT source_id FROM events WHERE source='mtgdecks'"
        ).fetchall()
    return {r["source_id"] for r in rows}


# ---------------------------------------------------------------------------
# Tournament list page
# ---------------------------------------------------------------------------

def scrape_tournament_list(format_name="standard", page=1):
    """
    Fetch one page of the format-specific tournament list.
    URL pattern: https://mtgdecks.net/Standard/tournaments/page:N

    Returns list of event dicts:
    {source_id, name, date, url, platform, player_count}
    """
    fmt_slug = FORMATS.get(format_name.lower())
    if not fmt_slug:
        print(f"  Unknown format: {format_name}")
        return []

    if page == 1:
        url = f"{BASE_URL}/{fmt_slug}/tournaments"
    else:
        url = f"{BASE_URL}/{fmt_slug}/tournaments/page:{page}"

    referer = f"{BASE_URL}/{fmt_slug}/tournaments" if page > 1 else f"{BASE_URL}/"
    resp = _get(url, referer=referer)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    events = []
    seen = set()

    # Main table has class "clickable"
    tbl = soup.find("table", class_="clickable")
    if not tbl:
        print(f"  [warn] no clickable table found on page {page}")
        return []

    for row in tbl.find_all("tr"):
        # Skip header row (has <th> cells)
        if row.find("th"):
            continue

        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # --- Date (first cell, inside <strong>) ---
        date_cell = cells[0]
        strong = date_cell.find("strong")
        date_str = strong.get_text(strip=True) if strong else date_cell.get_text(strip=True).split()[0]

        # --- Event link + name (third cell, has <a>) ---
        link_cell = cells[2] if len(cells) > 2 else cells[-1]
        a_tag = link_cell.find("a")
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        name = a_tag.get_text(strip=True)

        # source_id from slug: -tournament-EVENT_ID
        m = re.search(r"-tournament-(\d+)$", href)
        if not m:
            continue
        source_id = m.group(1)
        if source_id in seen:
            continue
        seen.add(source_id)

        event_url = BASE_URL + href

        # --- Player count (fourth cell if present) ---
        player_count = None
        if len(cells) >= 4:
            pc_txt = cells[3].get_text(strip=True)
            pm = re.search(r"(\d+)", pc_txt)
            if pm:
                player_count = int(pm.group(1))

        # --- Platform from platform-icon img ---
        platform_img = link_cell.find("img", class_="platform-icon")
        platform = "paper"
        if platform_img:
            src = platform_img.get("src", "")
            if "mtgo" in src:
                platform = "mtgo"

        events.append({
            "source_id": source_id,
            "name": name,
            "date": date_str,
            "url": event_url,
            "platform": platform,
            "player_count": player_count,
        })

    return events


def _max_pages(format_name="standard"):
    """Return the number of available pages from the pagination on the first page."""
    fmt_slug = FORMATS.get(format_name.lower(), format_name)
    resp = _get(f"{BASE_URL}/{fmt_slug}/tournaments", referer=f"{BASE_URL}/")
    if not resp:
        return 1
    soup = BeautifulSoup(resp.text, "lxml")
    pag = soup.find("ul", class_="pagination")
    if not pag:
        return 1
    page_nums = []
    for a in pag.find_all("a", href=re.compile(r"/page:\d+")):
        m = re.search(r"/page:(\d+)", a["href"])
        if m:
            page_nums.append(int(m.group(1)))
    return max(page_nums) if page_nums else 1


# ---------------------------------------------------------------------------
# Event detail page — deck listing
# ---------------------------------------------------------------------------

_PLACEMENT_MAP = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
    "top4": 4, "top8": 8, "top16": 16, "top32": 32, "top64": 64,
}

def _parse_placement(rank_text):
    """Convert '1st', 'Top4', '2nd' etc. to an integer placement."""
    key = rank_text.strip().lower().split("\n")[0].split("(")[0].strip()
    if key in _PLACEMENT_MAP:
        return _PLACEMENT_MAP[key]
    m = re.match(r"(\d+)", key)
    return int(m.group(1)) if m else None


def scrape_event_decks(source_id, event_url):
    """
    Fetch the event detail page and return a list of deck dicts:
    {source_id, player, archetype, placement, url}

    MTGDecks event page row structure:
      <td><strong>1st<br/>(10-0)<br/>100%</strong></td>   -- rank cell
      <td><a href="/Standard/archetype-by-player-DECKID">Archetype</a>
          <span class="text-capitalize">by playername</span></td>   -- deck cell
    """
    resp = _get(event_url, referer=f"{BASE_URL}/Standard/tournaments")
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    decks = []
    seen_deck_ids = set()

    tbl = soup.find("table", class_="clickable")
    if not tbl:
        return []

    for row in tbl.find_all("tr"):
        if row.find("th"):
            continue

        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # Rank cell (first td): "1st", "2nd", "Top4" etc.
        rank_text = cells[0].get_text(separator="\n", strip=True)
        placement = _parse_placement(rank_text) or (len(decks) + 1)

        # Deck cell (second td): link + player span
        deck_cell = cells[1]
        a_tag = deck_cell.find("a", href=re.compile(r"-\d+$"))
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        m = re.search(r"-(\d+)$", href)
        if not m:
            continue
        deck_id = m.group(1)
        if deck_id in seen_deck_ids:
            continue
        seen_deck_ids.add(deck_id)

        archetype = a_tag.get_text(strip=True)
        deck_url = BASE_URL + href if href.startswith("/") else href

        # Player from "by playername" span
        player_span = deck_cell.find("span", class_="text-capitalize")
        player = ""
        if player_span:
            player = player_span.get_text(strip=True).removeprefix("by ").strip()

        decks.append({
            "source_id": deck_id,
            "player": player,
            "archetype": archetype,
            "placement": placement,
            "url": deck_url,
        })

    return decks


# ---------------------------------------------------------------------------
# Individual deck page — card list
# ---------------------------------------------------------------------------

def scrape_deck_cards(deck_url):
    """
    Fetch a deck page and return (mainboard, sideboard).
    Each is a list of {name, quantity}.

    Primary: parse <textarea id="arena_deck"> — clean Arena export format:
        Deck
        4 Slickshot Show-Off
        ...
        Sideboard
        4 SomeCard

    Fallback: parse <tr class="cardItem" data-card-id="NAME" data-required="QTY">
    with sideboard marked by <th class="type Sideboard">.
    """
    resp = _get(deck_url, referer=deck_url.rsplit("/", 1)[0] + "/")
    if not resp:
        return [], []

    soup = BeautifulSoup(resp.text, "lxml")
    mainboard = []
    sideboard = []

    # --- Primary: Arena textarea ---
    textarea = soup.find("textarea", id="arena_deck")
    if textarea:
        current = mainboard
        for line in textarea.get_text().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower() == "deck":
                current = mainboard
                continue
            if line.lower() == "sideboard":
                current = sideboard
                continue
            m = re.match(r"^(\d+)\s+(.+)$", line)
            if m:
                qty = int(m.group(1))
                name = m.group(2).strip()
                if 1 <= qty <= 20 and name:
                    current.append({"name": name, "quantity": qty})
        if mainboard:
            return mainboard, sideboard

    # --- Fallback: data-card-id rows ---
    in_sideboard = False
    for el in soup.find_all(["th", "tr"]):
        if el.name == "th":
            classes = el.get("class", [])
            if "Sideboard" in classes:
                in_sideboard = True
            elif "type" in classes:
                in_sideboard = False
            continue
        # <tr class="cardItem" data-card-id="NAME" data-required="QTY">
        if "cardItem" in (el.get("class") or []):
            name = el.get("data-card-id", "").strip()
            qty_str = el.get("data-required", "").strip()
            if name and qty_str.isdigit():
                entry = {"name": name, "quantity": int(qty_str)}
                if in_sideboard:
                    sideboard.append(entry)
                else:
                    mainboard.append(entry)

    return mainboard, sideboard


# ---------------------------------------------------------------------------
# Store one event + its decks
# ---------------------------------------------------------------------------

def _process_event(ev, format_name):
    """Upsert event + all decks + cards. Returns (deck_count, stored_with_cards)."""
    parsed_date = _parse_date(ev["date"])
    date_iso = parsed_date.strftime("%Y-%m-%d") if parsed_date else ev["date"]

    event_type = classify_event_type(ev["name"])

    event_db_id = upsert_event(
        source="mtgdecks",
        source_id=ev["source_id"],
        name=ev["name"],
        date=date_iso,
        fmt=format_name,
        url=ev["url"],
        event_type=event_type,
    )

    decks = scrape_event_decks(ev["source_id"], ev["url"])
    stored = 0
    for dk in decks:
        deck_db_id = upsert_deck(
            event_id=event_db_id,
            source_id=dk["source_id"],
            player=dk["player"],
            archetype=dk["archetype"],
            placement=dk["placement"],
            url=dk["url"],
        )
        main_list, side_list = scrape_deck_cards(dk["url"])
        # insert_deck_cards expects {name: qty} dicts
        main_dict = {c["name"]: c["quantity"] for c in main_list}
        side_dict = {c["name"]: c["quantity"] for c in side_list}
        if main_dict:
            insert_deck_cards(deck_db_id, main_dict, side_dict)
            stored += 1

    return len(decks), stored


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_scraper(format_name="standard", pages=1, min_players=50, dry_run=False):
    """
    Scrape the latest N pages of tournaments for a format.
    Skips events already in the DB and events below the signal threshold.
    """
    existing_ids = _existing_source_ids()

    print(f"\n{'='*60}")
    print(f"  MTGDecks.net | {format_name.upper()} | pages={pages} | min_players={min_players}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    total_events = 0
    total_decks = 0

    for page in range(1, pages + 1):
        print(f"-- Page {page} -------------------------------------------")
        events = scrape_tournament_list(format_name, page)
        if not events:
            print("  No events found. Stopping.")
            break

        filtered = [e for e in events if _is_high_signal(e["name"], e["player_count"], min_players)]
        new_events = [e for e in filtered if e["source_id"] not in existing_ids]
        skipped = len(events) - len(filtered)
        print(f"  {len(events)} events | {len(filtered)} high-signal | {len(new_events)} new | {skipped} skipped (low signal)\n")

        for ev in new_events:
            parsed = _parse_date(ev["date"])
            date_str = parsed.strftime("%Y-%m-%d") if parsed else ev["date"]
            pc = f"{ev['player_count']}p" if ev["player_count"] else "?p"
            print(f"  [{date_str}] ({pc}) {ev['name'][:50]}", end="")

            if dry_run:
                print("  [DRY RUN]")
                continue

            deck_count, stored = _process_event(ev, format_name)
            existing_ids.add(ev["source_id"])
            total_events += 1
            total_decks += deck_count
            print(f"  — {deck_count} decks ({stored} with cards)")

    print(f"\n{'-'*60}")
    print(f"  DONE: {total_events} events, {total_decks} decks stored")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MTGDecks.net scraper")
    parser.add_argument("--format", default="standard", choices=list(FORMATS.keys()))
    parser.add_argument("--pages", type=int, default=1,
                        help="Number of tournament list pages to scrape (default 1)")
    parser.add_argument("--min-players", type=int, default=50,
                        help="Min player count to scrape (default 50; MTGO Challenges always included)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List events only, don't store anything")
    args = parser.parse_args()

    init_db()
    run_scraper(format_name=args.format, pages=args.pages,
                min_players=args.min_players, dry_run=args.dry_run)
