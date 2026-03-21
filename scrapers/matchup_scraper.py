"""
Scraper for MTGDecks.net win-rate tables.

URL pattern: https://mtgdecks.net/{Format}/winrates

Returns a dict: {archetype_a: {archetype_b: {"winrate": float, "matches": int}}}

Usage:
    python -m scrapers.matchup_scraper --format standard
    python -m scrapers.matchup_scraper --format pioneer --save
"""

import re
import argparse

import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://mtgdecks.net"

FORMATS = {
    "standard": "Standard",
    "pioneer":  "Pioneer",
    "modern":   "Modern",
    "legacy":   "Legacy",
}

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
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_winrates(format_name: str = "standard") -> dict:
    """
    Scrape the MTGDecks win-rate table for a format.
    Returns {archetype_a: {archetype_b: {"winrate": float, "matches": int}}}
    Raises requests.HTTPError on non-200 response.
    """
    fmt_segment = FORMATS.get(format_name.lower())
    if not fmt_segment:
        raise ValueError(f"Unsupported format: {format_name!r}. Choose from: {list(FORMATS)}")

    url = f"{BASE_URL}/{fmt_segment}/winrates"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return _parse_winrate_table(response.text)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_matches(text: str) -> int:
    m = re.search(r"([\d,]+)\s+match", text.replace("\xa0", " "))
    return int(m.group(1).replace(",", "")) if m else 0


def _parse_winrate_table(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return {}

    rows = table.find_all("tr")
    if len(rows) < 2:
        return {}

    # Row 0: headers — col 0 = blank, col 1 = "Overall", col 2+ = opponent names
    header_cells = rows[0].find_all(["th", "td"])
    opponents = [c.get_text(strip=True) for c in header_cells[2:]]

    result = {}
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        row_arch = cells[0].get_text(strip=True)
        if not row_arch:
            continue

        result[row_arch] = {}

        # cells[1] = "Overall" column — skip; cells[2:] = per-opponent
        for i, cell in enumerate(cells[2:]):
            if i >= len(opponents):
                break
            opp = opponents[i]
            if not opp:
                continue

            # Prefer data-winrate attribute (integer, e.g. "51")
            wr_attr = cell.get("data-winrate")
            if wr_attr is not None:
                try:
                    winrate = int(wr_attr) / 100.0
                except (ValueError, TypeError):
                    continue
            else:
                bold = cell.find("b")
                if not bold:
                    continue
                try:
                    winrate = int(bold.get_text(strip=True)) / 100.0
                except (ValueError, TypeError):
                    continue

            matches_div = cell.find(class_="matches-number")
            matches = _parse_matches(matches_div.get_text() if matches_div else "")

            result[row_arch][opp] = {"winrate": winrate, "matches": matches}

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape MTGDecks win-rate tables")
    parser.add_argument("--format", default="standard",
                        choices=list(FORMATS), metavar="FORMAT")
    parser.add_argument("--save", action="store_true",
                        help="Save results to the local DB after scraping")
    args = parser.parse_args()

    print(f"Scraping {args.format} winrates from MTGDecks…")
    data = scrape_winrates(args.format)
    total_cells = sum(len(v) for v in data.values())
    print(f"Found {len(data)} archetypes, {total_cells} matchup cells")

    if args.save:
        from db.matchup_queries import save_matchup_data
        save_matchup_data(args.format, data)
        print("Saved to DB.")
    else:
        for arch, opponents in list(data.items())[:3]:
            print(f"  {arch}: {list(opponents.items())[:3]}")
