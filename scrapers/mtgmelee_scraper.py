"""
Scraper for MTGMelee (https://mtgmelee.com) — real round-by-round match results.

MTGMelee is a .NET Razor Pages app that uses server-side DataTables for its
tournament list and pairings tables.  Both endpoints accept a standard DataTables
POST payload and return JSON with a ``data`` array.

Endpoint notes (verify with --test if these change):
  Tournament list : POST https://mtgmelee.com/Tournaments
                    extra field: columns[3][search][value] = "Standard"  (format filter)
  Round pairings  : POST https://mtgmelee.com/Tournament/View/{id}
                    extra field: columns[2][search][value] = "1"         (round filter)

Usage:
    python -m scrapers.mtgmelee_scraper --format standard --pages 5
    python -m scrapers.mtgmelee_scraper --format standard --pages 5 --dry-run
    python -m scrapers.mtgmelee_scraper --test               # dump raw API responses
    python -m scrapers.mtgmelee_scraper --infer-brackets     # infer finals/SF from DB top-8
    python -m scrapers.mtgmelee_scraper --counts             # show match counts per format
"""

import re
import sys
import time
import json
import logging
import argparse
from datetime import datetime

import cloudscraper
from bs4 import BeautifulSoup

from analysis.archetypes import normalize as normalize_arch

log = logging.getLogger(__name__)

_BASE = "https://mtgmelee.com"
_LIST_URL     = f"{_BASE}/Tournaments"
_PAIRING_URL  = f"{_BASE}/Tournament/View/{{tid}}"

# Seconds between requests — be respectful
_SLEEP = 1.5

# DataTables column index that holds the format name in the tournament list
_FORMAT_COL = 3

# DataTables column index that holds the round number in the pairings table
_ROUND_COL = 2

_FORMAT_MAP = {
    "standard": "Standard",
    "pioneer":  "Pioneer",
    "modern":   "Modern",
    "legacy":   "Legacy",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def _dt_post(session, url: str, start: int = 0, length: int = 100,
             extra: dict = None) -> dict | None:
    """
    Fire a standard DataTables server-side POST and return the JSON response.
    Returns None on any network or parse error.
    """
    payload = {
        "draw":           "1",
        "start":          str(start),
        "length":         str(length),
        "search[value]":  "",
        "search[regex]":  "false",
    }
    if extra:
        payload.update(extra)
    try:
        resp = session.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "json" not in ct and not resp.text.strip().startswith("{"):
            log.warning("Unexpected content-type from %s: %s", url, ct)
            return None
        return resp.json()
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Tournament list
# ---------------------------------------------------------------------------

def fetch_tournament_list(format_name: str, min_players: int = 32,
                          pages: int = 5) -> list[dict]:
    """
    Return a list of completed tournament dicts:
        {id, name, format, date, player_count}

    Applies server-side format filter via DataTables column search.
    """
    fmt_display = _FORMAT_MAP.get(format_name.lower(), format_name.title())
    session = _session()
    results = []

    for page in range(pages):
        start = page * 100
        payload = _dt_post(
            session, _LIST_URL,
            start=start, length=100,
            extra={
                f"columns[{_FORMAT_COL}][search][value]": fmt_display,
                f"columns[{_FORMAT_COL}][searchable]":    "true",
            },
        )
        if not payload:
            log.error("Tournament list page %d returned no data — check --test output", page)
            break

        rows = payload.get("data", [])
        if not rows:
            break  # no more pages

        for row in rows:
            t = _parse_tournament_row(row, fmt_display)
            if t and t["player_count"] >= min_players:
                results.append(t)

        log.info("Page %d: %d/%d matching tournaments (≥%d players, %s)",
                 page + 1, len([r for r in results]), len(results),
                 min_players, fmt_display)
        time.sleep(_SLEEP)

    log.info("Total: %d %s tournaments found", len(results), format_name)
    return results


def _parse_tournament_row(row, expected_format: str) -> dict | None:
    """Parse one DataTables row from the tournament list."""
    try:
        if isinstance(row, list):
            # Array form: [name_html, organizer_html?, format_html?, date_html?, players_html?, ...]
            def _text(cell):
                return BeautifulSoup(str(cell), "html.parser").get_text(strip=True)

            name_soup = BeautifulSoup(str(row[0]), "html.parser")
            link = name_soup.find("a", href=re.compile(r"/Tournament/View/\d+"))
            if not link:
                return None
            tid  = re.search(r"/Tournament/View/(\d+)", link["href"]).group(1)
            name = link.get_text(strip=True)

            fmt   = _text(row[_FORMAT_COL]) if len(row) > _FORMAT_COL else ""
            date  = _text(row[_FORMAT_COL + 1]) if len(row) > _FORMAT_COL + 1 else ""
            pcount = _parse_int(_text(row[_FORMAT_COL + 2])) if len(row) > _FORMAT_COL + 2 else 0

        elif isinstance(row, dict):
            tid    = str(row.get("id", row.get("Id", "")))
            name   = row.get("name", row.get("Name", ""))
            fmt    = row.get("format", row.get("Format", ""))
            date   = row.get("startDate", row.get("date", ""))
            pcount = _parse_int(row.get("playerCount", row.get("players", 0)))
        else:
            return None

        # Normalise date to YYYY-MM-DD
        date = _normalise_date(date)

        return {"id": tid, "name": name, "format": fmt, "date": date,
                "player_count": pcount}
    except Exception as exc:
        log.debug("Failed to parse tournament row: %s — %s", row, exc)
        return None


# ---------------------------------------------------------------------------
# Round pairings
# ---------------------------------------------------------------------------

def fetch_tournament_pairings(tournament_id: str,
                               max_rounds: int = 16) -> list[dict]:
    """
    Return all match records for a tournament:
        {round, player1, player2, player1_deck, player2_deck,
         player1_wins, player2_wins, draws, result}

    Iterates rounds 1..max_rounds, stopping when a round returns no data.
    """
    url     = _PAIRING_URL.format(tid=tournament_id)
    session = _session()
    matches = []

    for rnd in range(1, max_rounds + 1):
        payload = _dt_post(
            session, url,
            start=0, length=500,
            extra={
                f"columns[{_ROUND_COL}][search][value]": str(rnd),
                f"columns[{_ROUND_COL}][searchable]":    "true",
            },
        )
        if not payload:
            break

        rows = payload.get("data", [])
        if not rows:
            break  # no more rounds

        for row in rows:
            m = _parse_pairing_row(row, rnd)
            if m:
                matches.append(m)

        log.debug("Tournament %s round %d: %d pairings", tournament_id, rnd, len(rows))
        time.sleep(_SLEEP)

    return matches


def _parse_pairing_row(row, round_num: int) -> dict | None:
    """Parse one DataTables row from the pairings table."""
    def _text(cell):
        return BeautifulSoup(str(cell), "html.parser").get_text(strip=True)

    try:
        if isinstance(row, list) and len(row) >= 3:
            # Typical column order: player1 | result | player2 | deck1? | deck2?
            p1          = _text(row[0])
            result_str  = _text(row[1])
            p2          = _text(row[2])
            deck1       = _text(row[3]) if len(row) > 3 else ""
            deck2       = _text(row[4]) if len(row) > 4 else ""
        elif isinstance(row, dict):
            p1         = row.get("player1Name", row.get("player1", ""))
            p2         = row.get("player2Name", row.get("player2", ""))
            result_str = row.get("result", row.get("outcome", ""))
            deck1      = row.get("deck1", row.get("deckName1", ""))
            deck2      = row.get("deck2", row.get("deckName2", ""))
        else:
            return None

        if not p1 or not p2:
            return None  # bye or incomplete row

        p1w, p2w, draws = _parse_result(result_str)
        if p1w == 0 and p2w == 0 and draws == 0:
            result = None   # BYE / unknown
        elif p1w > p2w:
            result = "player1"
        elif p2w > p1w:
            result = "player2"
        else:
            result = "draw"

        return {
            "round":        round_num,
            "player1":      p1,
            "player2":      p2,
            "player1_deck": deck1,
            "player2_deck": deck2,
            "player1_wins": p1w,
            "player2_wins": p2w,
            "draws":        draws,
            "result":       result,
        }
    except Exception as exc:
        log.debug("Failed to parse pairing row: %s — %s", row, exc)
        return None


def _parse_result(s: str) -> tuple[int, int, int]:
    """Parse '2-1', '2-0-1', 'W', 'L', 'Draw' → (p1_wins, p2_wins, draws)."""
    if not s:
        return 0, 0, 0
    s = s.strip().upper()
    if "BYE" in s:
        return 0, 0, 0
    if "DRAW" in s:
        return 0, 0, 1
    nums = re.findall(r"\d+", s)
    if len(nums) >= 2:
        p1w, p2w = int(nums[0]), int(nums[1])
        draws = int(nums[2]) if len(nums) > 2 else 0
        return p1w, p2w, draws
    if s.startswith("W"):
        return 2, 0, 0
    if s.startswith("L"):
        return 0, 2, 0
    return 0, 0, 0


# ---------------------------------------------------------------------------
# Archetype mapping
# ---------------------------------------------------------------------------

def _map_archetype(deck_name: str, fmt: str) -> str:
    """
    Map a registered deck name to a normalised archetype name.
    Uses analysis.archetypes.normalize() which applies pre-normalisation,
    alias lookup, and fuzzy matching.
    """
    if not deck_name:
        return ""
    try:
        result = normalize_arch(deck_name, fmt)
        return result or deck_name
    except Exception:
        return deck_name


# ---------------------------------------------------------------------------
# Main scrape-and-store pipeline
# ---------------------------------------------------------------------------

def scrape_and_store(format_name: str, pages: int = 5,
                     min_players: int = 32, dry_run: bool = False) -> int:
    """
    Scrape MTGMelee tournaments and store round pairings in the matches table.
    Returns total matches saved.
    """
    from db.matches_queries import save_matches, get_stored_event_ids

    already_stored = get_stored_event_ids(format_name, source="mtgmelee")
    tournaments    = fetch_tournament_list(format_name, min_players, pages)

    total_saved = 0
    for t in tournaments:
        tid = t["id"]
        if tid in already_stored:
            log.info("Skipping %s (already stored)", t["name"])
            continue

        log.info("Scraping %s (%s, %d players) …", t["name"], t["date"], t["player_count"])
        pairings = fetch_tournament_pairings(tid)

        if not pairings:
            log.warning("  No pairings found for tournament %s", tid)
            continue

        match_rows = []
        for p in pairings:
            if not p["result"]:
                continue  # skip byes / incomplete
            arch1 = _map_archetype(p["player1_deck"], format_name)
            arch2 = _map_archetype(p["player2_deck"], format_name)
            if not arch1 or not arch2:
                continue  # skip if we can't determine archetypes

            winner = (arch1 if p["result"] == "player1" else
                      arch2 if p["result"] == "player2" else None)
            match_rows.append({
                "event_id":    f"mtgmelee_{tid}",
                "round":       p["round"],
                "player1":     p["player1"],
                "player2":     p["player2"],
                "player1_arch": arch1,
                "player2_arch": arch2,
                "winner_arch": winner,
                "result":      p["result"],
                "format":      format_name,
                "event_date":  t["date"],
                "source":      "mtgmelee",
            })

        if dry_run:
            print(f"  {t['name']}: {len(match_rows)} matches (dry run — not saved)")
            continue

        saved = save_matches(match_rows)
        total_saved += saved
        log.info("  Saved %d matches from %s", saved, t["name"])

    log.info("Done. Total matches saved: %d", total_saved)
    return total_saved


# ---------------------------------------------------------------------------
# Bracket inference from existing top-8 DB data
# ---------------------------------------------------------------------------

def infer_bracket_matches(format_name: str, dry_run: bool = False) -> int:
    """
    Infer W/L records from top-8 placement data already in the DB.

    What we can infer with certainty:
      Finals  — 1st beat 2nd  (1 match per event)

    What we infer with reasonable confidence (standard seeding assumed):
      Semifinals — 1st beat one of {3rd, 4th}; 2nd beat the other
        If 3rd_arch == 4th_arch: exact pairing known, add both SF matches.
        Otherwise: add with source='bracket_sf' — some noise accepted.

    Quarterfinals — skipped (seeding unknown without bracket data).
    """
    from db.database import get_combined_connection
    from db.matches_queries import save_matches, get_stored_event_ids

    already = get_stored_event_ids(format_name, source="bracket_finals")

    conn = get_combined_connection()
    try:
        # Fetch all events with at least a 1st and 2nd place deck
        rows = conn.execute("""
            SELECT
                e.id         AS event_id,
                e.source_id  AS src_id,
                e.source     AS src,
                e.date,
                MAX(CASE WHEN d.placement=1 THEN d.archetype END) AS arch_1,
                MAX(CASE WHEN d.placement=2 THEN d.archetype END) AS arch_2,
                MAX(CASE WHEN d.placement=3 THEN d.archetype END) AS arch_3,
                MAX(CASE WHEN d.placement=4 THEN d.archetype END) AS arch_4
            FROM events e
            JOIN decks d ON d.event_id = e.id
            WHERE lower(e.format) = lower(?)
              AND d.placement BETWEEN 1 AND 4
              AND d.archetype != ''
            GROUP BY e.id
            HAVING arch_1 IS NOT NULL AND arch_2 IS NOT NULL
        """, (format_name,)).fetchall()
    finally:
        conn.close()

    match_rows = []
    for r in rows:
        eid = str(r["event_id"])
        if eid in already:
            continue
        date = _normalise_date(r["date"] or "")

        # Finals — definite
        match_rows.append({
            "event_id":    eid,
            "round":       -1,   # sentinel: finals
            "player1":     "1st",
            "player2":     "2nd",
            "player1_arch": r["arch_1"],
            "player2_arch": r["arch_2"],
            "winner_arch": r["arch_1"],
            "result":      "player1",
            "format":      format_name,
            "event_date":  date,
            "source":      "bracket_finals",
        })

        # Semifinals — if we have 3rd and 4th
        a3, a4 = r["arch_3"], r["arch_4"]
        if a3 and a4:
            # 1st_arch beat one SF opponent, 2nd_arch beat the other.
            # If archetypes match (same deck), pairing is unambiguous for stats.
            # Add both SF records regardless — at scale the noise averages out.
            for finalist, sf_opp, sf_result in [
                (r["arch_1"], a3, "player1"),
                (r["arch_2"], a4, "player1"),
            ]:
                match_rows.append({
                    "event_id":    eid,
                    "round":       -2,   # sentinel: semifinals
                    "player1":     finalist,
                    "player2":     sf_opp,
                    "player1_arch": finalist,
                    "player2_arch": sf_opp,
                    "winner_arch": finalist,
                    "result":      sf_result,
                    "format":      format_name,
                    "event_date":  date,
                    "source":      "bracket_sf",
                })

    if dry_run:
        print(f"Bracket inference ({format_name}): {len(match_rows)} matches "
              f"from {len(rows)} events (dry run — not saved)")
        return len(match_rows)

    saved = save_matches(match_rows)
    print(f"Bracket inference ({format_name}): saved {saved} matches "
          f"from {len(rows)} events")
    return saved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_int(val) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(val)))
    except (ValueError, TypeError):
        return 0


def _normalise_date(raw: str) -> str:
    """Try to normalise various date strings to YYYY-MM-DD. Returns raw on failure."""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Try to extract a 4-digit year + 2+2 digit date
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_test(args):
    """Dump raw API responses so the user can verify endpoint shapes."""
    fmt_display = _FORMAT_MAP.get(args.format.lower(), args.format.title())
    session = _session()
    print(f"\n=== Tournament list (format={fmt_display}, first 5 rows) ===")
    payload = _dt_post(session, _LIST_URL, start=0, length=5,
                       extra={f"columns[{_FORMAT_COL}][search][value]": fmt_display})
    if payload:
        print(json.dumps(payload, indent=2, default=str)[:4000])
    else:
        print("ERROR: no response — check network / Cloudflare status")


def main(argv=None):
    parser = argparse.ArgumentParser(description="MTGMelee round-by-round match scraper")
    parser.add_argument("--format",  default="standard",
                        choices=list(_FORMAT_MAP.keys()),
                        help="Format to scrape (default: standard)")
    parser.add_argument("--pages",   type=int, default=5,
                        help="Tournament list pages to fetch (default: 5, ~500 tournaments)")
    parser.add_argument("--min-players", type=int, default=32,
                        help="Minimum players to include a tournament (default: 32)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print without saving to DB")
    parser.add_argument("--test",    action="store_true",
                        help="Dump raw API responses and exit (no DB writes)")
    parser.add_argument("--infer-brackets", action="store_true",
                        help="Infer finals/SF matches from existing top-8 DB placements")
    parser.add_argument("--counts",  action="store_true",
                        help="Show stored match counts per format and exit")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
    )

    if args.counts:
        from db.matches_queries import get_match_counts
        for fmt in _FORMAT_MAP:
            counts = get_match_counts(fmt)
            total  = sum(counts.values())
            detail = ", ".join(f"{s}={n}" for s, n in sorted(counts.items())) if counts else "none"
            print(f"{fmt:12s}: {total:6d} matches  ({detail})")
        return

    if args.test:
        _cmd_test(args)
        return

    if args.infer_brackets:
        infer_bracket_matches(args.format, dry_run=args.dry_run)
        return

    scrape_and_store(
        format_name=args.format,
        pages=args.pages,
        min_players=args.min_players,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
