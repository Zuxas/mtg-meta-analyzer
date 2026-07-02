"""
Scraper for Melee.gg (https://melee.gg) — real round-by-round match results.

Melee.gg is a .NET Razor Pages app.  The site migrated from DataTables column-filter
POSTs to a new REST-ish API in late 2024/early 2025.  Current endpoints:

  Tournament list : POST https://melee.gg/Tournament/TournamentSearch
                    Body: JSON state wrapper with filters[] array
                    Returns: {recordsTotal, data: [{id, name, formatString,
                              startDate, enrolledPlayerCount, gameDescription, ...}]}

  Round IDs       : GET https://melee.gg/Tournament/View/{tid}
                    Parse <button class="round-selector" data-id="{roundId}" ...>

  Round pairings  : POST https://melee.gg/Match/GetRoundMatches/{roundId}
                    Body: standard DataTables server-side payload with exact column names
                    Returns: {recordsTotal, data: [{Competitors:[...], ResultString, ...}]}

Usage:
    python -m scrapers.mtgmelee_scraper --format standard --pages 5
    python -m scrapers.mtgmelee_scraper --format standard --pages 5 --dry-run
    python -m scrapers.mtgmelee_scraper --test               # dump raw API responses
    python -m scrapers.mtgmelee_scraper --infer-brackets     # infer finals/SF from DB top-8
    python -m scrapers.mtgmelee_scraper --counts             # show match counts per format
"""

import re
import sys
import io
import time
import json
import logging
import argparse
from datetime import datetime

# Force UTF-8 output on Windows (tournament names can contain non-ASCII characters)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import cloudscraper
from bs4 import BeautifulSoup

from analysis.archetypes import normalize as normalize_arch

log = logging.getLogger(__name__)

from scrapers.constants import (
    URL_MELEE as _BASE,
    FORMATS_DISPLAY as _FORMAT_MAP,
    DELAY_DEFAULT as _SLEEP,
)

_SEARCH_URL      = f"{_BASE}/Tournament/TournamentSearch"
_VIEW_URL        = f"{_BASE}/Tournament/View/{{tid}}"
_ROUND_URL       = f"{_BASE}/Match/GetRoundMatches/{{rid}}"

# Pairings DataTables column definitions (must match pairings-section.min.js exactly)
_PAIRING_COLS = [
    ("TableNumber",  True,  True),
    ("PodNumber",    True,  True),
    ("Teams",        False, False),
    ("Decklists",    False, False),
    ("ResultString", False, False),
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def _pairing_dt_payload(start: int = 0, length: int = 500) -> dict:
    """Build the DataTables server-side POST payload for GetRoundMatches."""
    p = {
        "draw":             "1",
        "start":            str(start),
        "length":           str(length),
        "search[value]":    "",
        "search[regex]":    "false",
        "order[0][column]": "0",
        "order[0][dir]":    "asc",
    }
    for i, (name, searchable, orderable) in enumerate(_PAIRING_COLS):
        p[f"columns[{i}][data]"]            = name
        p[f"columns[{i}][name]"]            = name
        p[f"columns[{i}][searchable]"]      = str(searchable).lower()
        p[f"columns[{i}][orderable]"]       = str(orderable).lower()
        p[f"columns[{i}][search][value]"]   = ""
        p[f"columns[{i}][search][regex]"]   = "false"
    return p


# ---------------------------------------------------------------------------
# Tournament list
# ---------------------------------------------------------------------------

def fetch_tournament_list(format_name: str, min_players: int = 32,
                          pages: int = 5) -> list[dict]:
    """
    Return a list of completed tournament dicts:
        {id, name, format, date, player_count}

    Uses the TournamentSearch endpoint with filters[] array.
    """
    fmt_display = _FORMAT_MAP.get(format_name.lower(), format_name.title())
    session = _session()
    results = []

    def _body(start: int, length: int) -> dict:
        return {
            "ordering":           "StartDate",
            "mode":               "Table",
            "filters[]":          [fmt_display, "MagicTheGathering", "Ended"],
            "variables[draw]":    "1",
            "variables[start]":   str(start),
            "variables[length]":  str(length),
            "variables[search][value]": "",
            "variables[search][regex]": "false",
        }

    # NOTE (2026-07-02): TournamentSearch ignores the "ordering" field (both
    # "StartDate" and "-StartDate" return the same order) and always returns
    # rows ascending by id — i.e. OLDEST tournaments first.  Paging from
    # start=0 therefore never got past 2023-era events, which is why the
    # matches table went dry after 2026-03-21.  Fix: probe recordsTotal, then
    # read the LAST `pages` pages so the newest tournaments are always covered.
    try:
        resp = session.post(_SEARCH_URL, data=_body(0, 1), timeout=30)
        resp.raise_for_status()
        total = int(resp.json().get("recordsTotal") or 0)
    except Exception as exc:
        log.error("Tournament search probe failed: %s", exc)
        return results
    if total <= 0:
        log.warning("Tournament search returned recordsTotal=0 (%s)", fmt_display)
        return results
    time.sleep(_SLEEP)

    seen_ids = set()
    for page in range(pages):
        start = max(0, total - (page + 1) * 100)
        try:
            resp = session.post(_SEARCH_URL, data=_body(start, 100), timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.error("Tournament search page %d (start=%d) failed: %s",
                      page, start, exc)
            break

        rows = payload.get("data", [])
        if not rows:
            break

        for row in rows:
            t = _parse_tournament_row(row, fmt_display)
            if t and t["id"] not in seen_ids and t["player_count"] >= min_players:
                seen_ids.add(t["id"])
                results.append(t)

        log.info("Page %d (start=%d): %d cumulative qualifying tournaments (%s)",
                 page + 1, start, len(results), fmt_display)
        if start == 0:
            break   # reached the front of the result set
        time.sleep(_SLEEP)

    # API returns newest last — hand the caller newest first.
    results.sort(key=lambda t: t.get("date") or "", reverse=True)
    log.info("Total: %d %s tournaments found", len(results), format_name)
    return results


def _parse_tournament_row(row, expected_format: str) -> dict | None:
    """Parse one row dict from the TournamentSearch response."""
    try:
        if not isinstance(row, dict):
            return None

        # gameDescription filters non-MTG games (e.g. "Flesh and Blood")
        game = row.get("gameDescription", "")
        if game and "magic" not in game.lower():
            return None

        tid    = str(row.get("id", ""))
        name   = row.get("name", "")
        # formatString may be comma-separated for multi-format bundles
        fmt    = row.get("formatString", row.get("format", ""))
        date   = row.get("startDate", row.get("date", ""))
        pcount = _parse_int(row.get("enrolledPlayerCount",
                            row.get("playerCount", row.get("players", 0))))

        if not tid:
            return None

        date = _normalise_date(date)
        return {"id": tid, "name": name, "format": fmt, "date": date,
                "player_count": pcount}
    except Exception as exc:
        log.debug("Failed to parse tournament row: %s — %s", row, exc)
        return None


# ---------------------------------------------------------------------------
# Round pairings
# ---------------------------------------------------------------------------

def _get_round_ids(session, tournament_id: str) -> list[tuple[int, str]]:
    """
    GET the tournament view page and parse round selector buttons.
    Returns [(round_id, round_name), ...] ordered as they appear on the page.
    Only includes rounds where data-is-started="True".
    """
    url = _VIEW_URL.format(tid=tournament_id)
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("GET %s failed: %s", url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rounds = []
    for btn in soup.find_all("button", class_="round-selector"):
        rid  = btn.get("data-id")
        name = btn.get("data-name", "")
        # Only scrape started rounds (in-progress or finished)
        started = btn.get("data-is-started", "").lower()
        if rid and started == "true":
            rounds.append((int(rid), name))
    return rounds


def fetch_tournament_pairings(tournament_id: str) -> list[dict]:
    """
    Return all match records for a tournament:
        {round, player1, player2, player1_deck, player2_deck,
         player1_wins, player2_wins, draws, result}

    Flow:
      1. GET tournament view page to establish session cookies + parse round IDs
      2. For each round ID, POST /Match/GetRoundMatches/{roundId} with DataTables payload
    """
    session = _session()
    round_ids = _get_round_ids(session, tournament_id)
    if not round_ids:
        log.warning("No started rounds found for tournament %s", tournament_id)
        return []

    matches = []
    for rid, rname in round_ids:
        url = _ROUND_URL.format(rid=rid)
        try:
            resp = session.post(
                url,
                data=_pairing_dt_payload(),
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": _VIEW_URL.format(tid=tournament_id),
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("GetRoundMatches %s (%s) failed: %s", rid, rname, exc)
            time.sleep(_SLEEP)
            continue

        rows = payload.get("data", [])
        rnd_num = _round_number(rname)
        for row in rows:
            m = _parse_pairing_row(row, rnd_num)
            if m:
                matches.append(m)

        log.debug("Tournament %s %s (id=%s): %d pairings", tournament_id, rname, rid, len(rows))
        time.sleep(_SLEEP)

    return matches


def _round_number(round_name: str) -> int:
    """Extract integer round number from name like 'Round 3', 'Finals', 'Semifinals'."""
    m = re.search(r"\d+", round_name)
    if m:
        return int(m.group())
    name_lower = round_name.lower()
    if "final" in name_lower and "semi" not in name_lower:
        return -1   # sentinel: finals
    if "semi" in name_lower:
        return -2   # sentinel: semifinals
    if "quarter" in name_lower:
        return -3   # sentinel: quarterfinals
    return 0


def _parse_pairing_row(row: dict, round_num: int) -> dict | None:
    """
    Parse one match dict from GetRoundMatches response.

    Structure:
      row["Competitors"] = list of 1 or 2 competitor dicts
      competitor["Team"]["Players"][0]["DisplayName"] = player name
      competitor["Decklists"][0]["DecklistName"]      = registered deck name
      competitor["GameWins"]                          = game wins (int or null)
      row["GameDraws"]                                = draws
      row["ByeReason"]                                = non-null → bye
      row["HasResult"]                                = bool
    """
    try:
        comps = row.get("Competitors", [])
        # Skip byes (only 1 competitor) and unresolved matches
        if len(comps) != 2:
            return None
        if not row.get("HasResult"):
            return None
        if row.get("ByeReason") is not None:
            return None

        def _player_name(comp):
            players = comp.get("Team", {}).get("Players", [])
            return players[0].get("DisplayName", "") if players else ""

        def _deck_name(comp):
            decklists = comp.get("Decklists", [])
            return decklists[0].get("DecklistName", "") if decklists else ""

        p1, p2   = comps[0], comps[1]
        name1    = _player_name(p1)
        name2    = _player_name(p2)
        deck1    = _deck_name(p1)
        deck2    = _deck_name(p2)
        p1w      = p1.get("GameWins") or 0
        p2w      = p2.get("GameWins") or 0
        draws    = row.get("GameDraws") or 0

        if not name1 or not name2:
            return None

        if p1w > p2w:
            result = "player1"
        elif p2w > p1w:
            result = "player2"
        elif draws > 0:
            result = "draw"
        else:
            return None  # 0-0-0 — no result recorded

        return {
            "round":        round_num,
            "player1":      name1,
            "player2":      name2,
            "player1_deck": deck1,
            "player2_deck": deck2,
            "player1_wins": p1w,
            "player2_wins": p2w,
            "draws":        draws,
            "result":       result,
        }
    except Exception as exc:
        log.debug("Failed to parse pairing row: %s", exc)
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
        # Stored event_ids carry the "mtgmelee_" prefix (see match_rows below).
        # Comparing the bare tid never matched, so every run re-scraped the
        # same tournaments.  Fixed 2026-07-02.
        if f"mtgmelee_{tid}" in already_stored:
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

    # --- Tournament list ---
    print(f"\n=== Tournament list (format={fmt_display}, first 3 rows) ===")
    body = {
        "ordering":           "StartDate",
        "mode":               "Table",
        "filters[]":          [fmt_display, "MagicTheGathering", "Ended"],
        "variables[draw]":    "1",
        "variables[start]":   "0",
        "variables[length]":  "3",
        "variables[search][value]": "",
        "variables[search][regex]": "false",
    }
    try:
        resp = session.post(_SEARCH_URL, data=body, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        print(f"recordsTotal={payload.get('recordsTotal')}, rows={len(payload.get('data',[]))}")
        for t in payload.get("data", [])[:3]:
            print(json.dumps(t, indent=2, default=str))
    except Exception as exc:
        print(f"ERROR: {exc}")

    # --- Round IDs from most recent tournament ---
    tournaments = fetch_tournament_list(fmt_display, min_players=32, pages=1)
    if not tournaments:
        print("\nNo tournaments found — cannot test pairings endpoint")
        return

    t = tournaments[0]
    print(f"\n=== Round IDs for '{t['name']}' (id={t['id']}) ===")
    round_ids = _get_round_ids(session, t["id"])
    for rid, rname in round_ids:
        print(f"  {rname}: id={rid}")

    if not round_ids:
        print("  No started rounds found")
        return

    # --- First round pairings ---
    rid, rname = round_ids[0]
    print(f"\n=== Pairings for {rname} (roundId={rid}), first 3 matches ===")
    try:
        resp = session.post(
            _ROUND_URL.format(rid=rid),
            data=_pairing_dt_payload(),
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _VIEW_URL.format(tid=t["id"]),
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=30,
        )
        resp.raise_for_status()
        pdata = resp.json()
        print(f"recordsTotal={pdata.get('recordsTotal')}, rows={len(pdata.get('data',[]))}")
        non_byes = [m for m in pdata.get("data", []) if len(m.get("Competitors",[])) == 2]
        for m in non_byes[:3]:
            parsed = _parse_pairing_row(m, _round_number(rname))
            print(f"  {parsed}")
    except Exception as exc:
        print(f"ERROR: {exc}")


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
