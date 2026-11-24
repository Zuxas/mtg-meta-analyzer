"""
Scraper for Melee.gg (https://melee.gg) — real round-by-round match results.

Melee.gg is a .NET Razor Pages app.  The site migrated from DataTables column-filter
POSTs to a new REST-ish API in late 2024/early 2025.  Current endpoints:

  Tournament list : POST https://melee.gg/Tournament/TournamentSearch
                    Body: JSON state wrapper with filters[] array
                    Returns: {recordsTotal, data: [{id, name, formatString,
                              startDate, enrolledPlayerCount, gameDescription, ...}]}

  Round IDs       : GET https://melee.gg/Tournament/View/{tid}
                    Parse <button class="round-selector" data-id="{roundId}"
                    data-is-started="True"> inside #pairings-round-selector-container
                    (the standings container repeats the rounds with data-is-completed only)

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
from db.helpers import force_utf8_stdio
force_utf8_stdio()

import cloudscraper
from bs4 import BeautifulSoup

from analysis.archetypes import ALIASES, pre_normalize, normalize as normalize_arch

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


class DiscoveryFailed(Exception):
    """TournamentSearch discovery did not return a usable result -- the probe or
    a page request failed, or recordsTotal was 0. This is an OUTAGE (Cloudflare
    block / API change), NOT a genuine 'no new events', so the run must exit
    nonzero instead of recording `ok` with no data (#18)."""


class IncompleteTournament(Exception):
    """A round failed to fetch, so the event's pairings are incomplete. Callers
    store nothing for it, leaving it retryable on the next run."""

    def __init__(self, tid, failed_rounds):
        self.tid = tid
        self.failed_rounds = list(failed_rounds)
        super().__init__(
            f"tournament {tid}: {len(self.failed_rounds)} round(s) failed: "
            + ", ".join(self.failed_rounds)
        )


def fetch_round_rows(session, tid, rid) -> list:
    """Every GetRoundMatches DataTables row for one round, paged until
    `recordsTotal` is reached (RC/MagicCon rounds exceed the 500-row page).
    Raises on any HTTP/JSON failure so the caller decides whether to skip or
    record the round. Shared by fetch_tournament_pairings and
    scripts/relabel_melee_history.py."""
    start, rows = 0, []
    while True:
        resp = session.post(
            _ROUND_URL.format(rid=rid),
            data=_pairing_dt_payload(start, 500),
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _VIEW_URL.format(tid=tid),
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        page = payload.get("data", [])
        rows += page
        total = payload.get("recordsTotal", len(rows))
        time.sleep(_SLEEP)
        if not page or len(rows) >= total:
            break
        start += len(page)
    return rows


# ---------------------------------------------------------------------------
# Tournament list
# ---------------------------------------------------------------------------

_SEARCH_PAGE = 100       # rows per TournamentSearch request (the server caps length at 500)


def fetch_tournament_list(format_name: str, min_players: int = 32,
                          pages: int = 5) -> list[dict]:
    """
    Return a list of completed tournament dicts, newest first:
        {id, name, format, date, player_count}

    Uses the TournamentSearch endpoint with filters[] array.  At most
    `pages` + 2 requests (a recordsTotal probe, `pages` pages, one re-check).
    """
    fmt_display = _FORMAT_MAP.get(format_name.lower(), format_name.title())
    session = _session()

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

    def _total() -> int:
        resp = session.post(_SEARCH_URL, data=_body(0, 1), timeout=30)
        resp.raise_for_status()
        return int(resp.json().get("recordsTotal") or 0)

    # NOTE (2026-07-02): TournamentSearch ignores the "ordering" field and
    # always returns rows ascending by id -- OLDEST first -- so the newest
    # tournaments are on the LAST pages.
    # NOTE (2026-10-01): the server also SNAPS the offset to a multiple of the
    # page length: it serves rows (start // length) * length onwards.  The old
    # code asked for start = total - 100*(page+1) (e.g. 1051 of 1,151), was
    # served rows 1000-1099, and never saw the newest `total % 100` rows -- every
    # Modern event after 2026-09-13 (and the China RC, the Dallas RCQ flights).
    # Paging itself is deterministic (verified by repeated identical requests).
    # Fix: request page-ALIGNED offsets, walking back from the last page.
    try:
        total = _total()
    except Exception as exc:
        # An outage looks exactly like 'no new events' to the caller; make it
        # loud so the pipeline records an error instead of a silent ok (#18).
        raise DiscoveryFailed(f"TournamentSearch probe failed ({fmt_display}): {exc}") from exc
    if total <= 0:
        raise DiscoveryFailed(
            f"TournamentSearch returned recordsTotal=0 ({fmt_display}) -- a supported "
            "format should never be empty; likely a blocked scraper or a bad format map")
    time.sleep(_SLEEP)

    found: dict[str, dict] = {}            # id -> tournament (pages may overlap / repeat rows)
    filtered = {"n": 0}                    # events seen but below min_players

    def _read_page(page_no: int) -> int:
        start = page_no * _SEARCH_PAGE
        resp = session.post(_SEARCH_URL, data=_body(start, _SEARCH_PAGE), timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("data", []) or []
        for row in rows:
            t = _parse_tournament_row(row, fmt_display)
            if not t:
                continue
            if t["player_count"] >= min_players:
                found.setdefault(t["id"], t)
            else:
                filtered["n"] += 1
        log.info("Page start=%d: %d rows, %d cumulative qualifying tournaments (%s)",
                 start, len(rows), len(found), fmt_display)
        return len(rows)

    last_page = (total - 1) // _SEARCH_PAGE
    for i in range(max(0, pages)):
        page_no = last_page - i
        if page_no < 0:
            break                          # reached the front of the result set
        try:
            n = _read_page(page_no)
        except Exception as exc:
            raise DiscoveryFailed(
                f"TournamentSearch page start={page_no * _SEARCH_PAGE} failed "
                f"({fmt_display}): {exc}") from exc
        if n == 0 and i > 0:
            break
        time.sleep(_SLEEP)

    # A tournament that ended during the walk shifts every row by one; re-read
    # the newest page once if the total moved, so the newest rows are not lost.
    try:
        new_total = _total()
        if new_total != total and new_total > 0:
            _read_page((new_total - 1) // _SEARCH_PAGE)
    except Exception as exc:
        log.warning("Tournament search re-check failed: %s", exc)

    # Newest first (date, then id -- ids grow with creation time).
    results = sorted(found.values(),
                     key=lambda t: (t.get("date") or "", _parse_int(t["id"])), reverse=True)
    log.info("Total: %d %s tournaments found (%d below min_players=%d, filtered)",
             len(results), format_name, filtered["n"], min_players)
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

def _parse_round_ids(html: str) -> tuple[list[tuple[int, str]], str]:
    """
    Parse a Tournament/View page into ([(round_id, round_name), ...], reason).

    Rounds are the <button class="round-selector" data-id=... data-is-started="True">
    buttons of the PAIRINGS selector (#pairings-round-selector-container); the
    standings selector repeats every round with data-is-completed only.  Pages
    without that container (older markup) fall back to every round-selector
    button.  Unstarted rounds (data-is-started="False") are never admitted.

    reason: "ok" | "no-started-rounds" | "no-round-selectors" |
            "no-pairings-section" -- the public page shows no pairings at all
            (seen 2026-10-01 on SCG's "$1K Modern RCQ - SCG CON Dallas" (442749),
            a registration shell whose play happened in separate
            "FLIGHT A/B" tournaments that discovery finds on their own).
    """
    soup = BeautifulSoup(html, "html.parser")
    scope = soup.find(id="pairings-round-selector-container") or soup
    buttons = scope.find_all("button", class_="round-selector")
    if not buttons:
        has_section = soup.find(id="pairings") is not None
        return [], ("no-round-selectors" if has_section else "no-pairings-section")
    rounds, seen = [], set()
    for btn in buttons:
        rid = btn.get("data-id")
        started = (btn.get("data-is-started") or "").strip().lower()
        if not rid or started != "true" or not rid.isdigit() or int(rid) in seen:
            continue
        seen.add(int(rid))
        rounds.append((int(rid), btn.get("data-name", "")))
    return rounds, ("ok" if rounds else "no-started-rounds")


def _get_round_ids(session, tournament_id: str) -> list[tuple[int, str]]:
    """
    GET the tournament view page and parse its started pairing rounds.
    Returns [(round_id, round_name), ...] ordered as they appear on the page.
    """
    url = _VIEW_URL.format(tid=tournament_id)
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("GET %s failed: %s", url, exc)
        return []

    rounds, reason = _parse_round_ids(resp.text)
    if reason == "no-pairings-section":
        log.warning("Tournament %s: the public page has no pairings section (pairings hidden, "
                    "or the event was split into separate flight tournaments)", tournament_id)
    elif reason != "ok":
        log.warning("Tournament %s: %s", tournament_id, reason)
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
    failed = []
    for rid, rname in round_ids:
        try:
            rows = fetch_round_rows(session, tournament_id, rid)
        except Exception as exc:
            log.warning("GetRoundMatches %s (%s) failed: %s", rid, rname, exc)
            failed.append(rname)
            time.sleep(_SLEEP)
            continue

        rnd_num = _round_number(rname)
        for row in rows:
            m = _parse_pairing_row(row, rnd_num)
            if m:
                matches.append(m)

        log.debug("Tournament %s %s (id=%s): %d pairings", tournament_id, rname, rid, len(rows))

    if failed:
        # Partial data skews conversion/WR/Glicko on the biggest events; store
        # nothing so the event is re-fetched next run.
        raise IncompleteTournament(tournament_id, failed)
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


# Melee tags each MATCH with its own Format; a multi-format event (Pro Tour,
# trios) mixes Draft/Limited and several constructed formats in one tournament.
# Mirror quarantine_matches.py's predicate so the live scraper and the one-off
# cleanup script agree on what counts as Limited.
LIMITED_FORMATS = ("draft", "sealed")


def _is_limited(fmt: str | None) -> bool:
    return bool(fmt) and any(w in fmt.lower() for w in LIMITED_FORMATS)


def _match_format(row: dict, comps: list) -> str | None:
    """The format of THIS match, not the event's combined formatString. Prefer
    the row-level Format (a single value); fall back to a competitor's decklist
    Format. A comma-joined value is the event bundle (e.g. "Modern, Standard"),
    not a per-match signal, so it is ignored."""
    mf = row.get("Format") or row.get("FormatDescription")
    if mf and "," not in mf:
        return mf.strip()
    for comp in comps:
        for d in comp.get("Decklists") or []:
            dmf = d.get("Format")
            if dmf and "," not in dmf:
                return dmf.strip()
    return None


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
            "match_format": _match_format(row, comps),
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
    Map a registered deck name to a normalised archetype name: exact canonical
    name or alias (analysis.archetypes.normalize, fuzzy OFF), otherwise the
    published name, pre-normalised.  Never invents a label:
      * blank names, and names the alias table flags as junk ('' alias, e.g.
        "Decklist"), are unlabelled ("") -- the caller skips those matches;
      * no fuzzy matching.  Until 2026-10-01 this called normalize(deck_name, fmt),
        so the format string landed in normalize's positional `fuzzy` parameter
        and labels were fuzzy-guessed -- wrongly and unstably ('Mono-Green
        Broodscale' -> 'Mono Red Aggro'; 'Mono-Red Ruby Storm' -> 'Cycle Storm'
        or 'Poison Storm').  Rows stored before that date may carry such labels.
    """
    if not deck_name or not deck_name.strip():
        return ""
    if ALIASES.get(pre_normalize(deck_name.strip()).lower()) == "":
        return ""                                       # explicitly junk, not an archetype
    try:
        result = normalize_arch(deck_name)               # exact canonical / alias only
        return result or deck_name
    except Exception:
        return deck_name


# ---------------------------------------------------------------------------
# Main scrape-and-store pipeline
# ---------------------------------------------------------------------------

def _match_rows(t: dict, pairings: list[dict], format_name: str) -> list[dict]:
    """Storable match rows of one tournament: decided matches whose BOTH deck
    names map to an archetype (unlabelled decks are skipped, never guessed).

    Each match carries its OWN format (#14): in a multi-format event only the
    matches actually played in ``format_name`` are kept -- Limited (Draft/Sealed)
    rows are dropped, and matches in a different constructed format are left for
    that format's own scrape -- so a Pro Tour's Draft rounds never land in Modern
    or Standard win rates. A match with no per-match Format (ordinary
    single-format event) is kept as before."""
    rows = []
    want = format_name.strip().lower()
    dropped_limited = dropped_other = 0
    for p in pairings:
        if not p["result"]:
            continue  # skip byes / incomplete
        mf = p.get("match_format")
        if mf:
            if _is_limited(mf):
                dropped_limited += 1
                continue
            if mf.lower() != want:
                dropped_other += 1
                continue
        arch1 = _map_archetype(p["player1_deck"], format_name)
        arch2 = _map_archetype(p["player2_deck"], format_name)
        if not arch1 or not arch2:
            continue  # skip if we can't determine archetypes

        winner = (arch1 if p["result"] == "player1" else
                  arch2 if p["result"] == "player2" else None)
        rows.append({
            "event_id":    f"mtgmelee_{t['id']}",
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
    if dropped_limited or dropped_other:
        log.info("mtgmelee_%s: kept %d, dropped %d Limited + %d other-format row(s) "
                 "(multi-format event; requested %s)",
                 t["id"], len(rows), dropped_limited, dropped_other, format_name)
    return rows


# Tournament ids skipped on the last scrape because a round failed to fetch
# (incomplete -> stored nothing -> retryable next run). main() exits nonzero
# when non-empty so the pipeline records an error outcome.
LAST_INCOMPLETE: list[str] = []


def scrape_tournaments(tournament_ids: list[str], format_name: str, pages: int = 5,
                       dry_run: bool = False) -> dict:
    """
    Targeted, idempotent (re)scrape of specific tournaments -- the backfill path.

    Metadata (date, name) comes from TournamentSearch (never guessed); an id the
    search does not list is reported, not scraped.  Rows go through the same
    `save_matches` (INSERT OR IGNORE on UNIQUE(event_id, round, player1, player2)),
    so re-running inserts nothing new.  Returns {tid: stats}; `inserted` is the
    exact change in stored rows for that event.
    """
    from db.matches_queries import save_matches, count_event_matches

    LAST_INCOMPLETE.clear()
    listed = {t["id"]: t for t in fetch_tournament_list(format_name, 0, pages)}
    out = {}
    for tid in [str(x) for x in tournament_ids]:
        t = listed.get(tid)
        if t is None:
            log.error("Tournament %s is not in the %s TournamentSearch window (pages=%d)",
                      tid, format_name, pages)
            out[tid] = {"error": "not-listed"}
            continue
        try:
            pairings = fetch_tournament_pairings(tid)
        except IncompleteTournament as exc:
            log.error("Tournament %s stored nothing — %s (retry next run)", tid, exc)
            out[tid] = {"error": "incomplete-rounds", "failed_rounds": exc.failed_rounds}
            LAST_INCOMPLETE.append(tid)
            continue
        rows = _match_rows(t, pairings, format_name)
        stats = {"name": t["name"], "date": t["date"], "players": t["player_count"],
                 "pairings": len(pairings), "decided": sum(1 for p in pairings if p["result"]),
                 "storable": len(rows)}
        if not dry_run and rows:
            before = count_event_matches(f"mtgmelee_{tid}")
            save_matches(rows)
            stats["inserted"] = count_event_matches(f"mtgmelee_{tid}") - before
            from db.matches_queries import LAST_SAVE_SKIPPED
            stats["excluded_skipped"] = len(LAST_SAVE_SKIPPED)
        out[tid] = stats
        print(f"  {tid} {t['name']} ({t['date']}): {stats}")
    return out


def scrape_and_store(format_name: str, pages: int = 5,
                     min_players: int = 32, dry_run: bool = False) -> int:
    """
    Scrape MTGMelee tournaments and store round pairings in the matches table.
    Returns total matches saved.
    """
    from db.matches_queries import save_matches, get_stored_event_ids

    already_stored = get_stored_event_ids(format_name, source="mtgmelee")
    tournaments    = fetch_tournament_list(format_name, min_players, pages)

    LAST_INCOMPLETE.clear()
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
        try:
            pairings = fetch_tournament_pairings(tid)
        except IncompleteTournament as exc:
            log.error("  %s stored nothing — %s (retry next run)", t["name"], exc)
            LAST_INCOMPLETE.append(tid)
            continue

        if not pairings:
            log.warning("  No pairings found for tournament %s", tid)
            continue

        match_rows = _match_rows(t, pairings, format_name)

        if dry_run:
            print(f"  {t['name']}: {len(match_rows)} matches (dry run — not saved)")
            continue

        saved = save_matches(match_rows)
        total_saved += saved
        from db.matches_queries import LAST_SAVE_SKIPPED
        log.info("  Saved %d matches from %s%s", saved, t["name"],
                 f" ({len(LAST_SAVE_SKIPPED)} refused: excluded event/round)" if LAST_SAVE_SKIPPED else "")

    if LAST_INCOMPLETE:
        log.error("%d tournament(s) had failed rounds and were skipped (retryable): %s",
                  len(LAST_INCOMPLETE), ", ".join(LAST_INCOMPLETE))
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

    Semifinals/quarterfinals are NOT inferred: a 1st-vs-3rd / 2nd-vs-4th guess
    was wrong whenever seeding differed, and those `bracket_sf` rows counted as
    real matches in every `FROM matches` query with no way to tell them apart
    from observed pairings (#19). Only the certain final is recorded.

    Only events with a real single-elim top 8 are inferred: League/Preliminary
    are skipped (Swiss-only, no cut) and any event whose deepest placement is
    below 8 (a 5-0 list, not a bracket). Cross-source duplicates are collapsed
    by event_fingerprint_cs so a tournament scraped from two sites yields one
    final, and an event that already has real pairing rows is left alone.
    NOTE: a Melee-scraped tournament and its mtgtop8/mtgdecks placement copy
    live under different event_id namespaces with no shared key, so that
    cross-source overlap is not dedup'd here (no reliable join exists).
    """
    from db.database import get_combined_connection
    from db.matches_queries import save_matches, get_stored_event_ids
    from scrapers.challenges import classify_event_type

    already = get_stored_event_ids(format_name, source="bracket_finals")

    conn = get_combined_connection()
    try:
        # max_place is MAX over ALL decks (no placement/archetype filter) so a
        # League 5-0 dump reads its true depth; the CASE arms still pull the top 4.
        rows = conn.execute("""
            SELECT
                e.id                  AS event_id,
                e.name                AS name,
                e.event_type          AS event_type,
                e.event_fingerprint_cs AS fp_cs,
                e.date,
                MAX(d.placement)                                            AS max_place,
                MAX(CASE WHEN d.placement=1 AND d.archetype!='' THEN d.archetype END) AS arch_1,
                MAX(CASE WHEN d.placement=2 AND d.archetype!='' THEN d.archetype END) AS arch_2
            FROM events e
            JOIN decks d ON d.event_id = e.id
            WHERE lower(e.format) = lower(?)
            GROUP BY e.id
            HAVING arch_1 IS NOT NULL AND arch_2 IS NOT NULL
            ORDER BY e.id
        """, (format_name,)).fetchall()

        # Events that already carry real (non-inferred) pairing rows: never
        # layer an inferred finals on top of a scraped one for the same event.
        real_event_ids = {
            row["event_id"] for row in conn.execute(
                "SELECT DISTINCT event_id FROM matches "
                "WHERE lower(format)=lower(?) AND source NOT LIKE 'bracket%'",
                (format_name,),
            ).fetchall()
        }
    finally:
        conn.close()

    # League / Preliminary are Swiss-only (no single-elim cut); mtgtop8 stores
    # them with event_type NULL, so fall back to the name. max_place < 8 means
    # the "bracket" is really a 5-0 list or a small pod -- not a top 8.
    NO_BRACKET_TYPES = {"mtgo_league", "mtgo_preliminary"}

    match_rows = []
    seen_fp = set()
    for r in rows:
        eid = str(r["event_id"])
        etype = r["event_type"] or classify_event_type(r["name"] or "")
        if etype in NO_BRACKET_TYPES:
            continue
        if (r["max_place"] or 0) < 8:
            continue
        if eid in real_event_ids:
            continue
        # Collapse cross-source duplicates (same tournament scraped from
        # mtgtop8 AND mtgdecks share event_fingerprint_cs) to one final.
        fp = r["fp_cs"]
        if fp:
            if fp in seen_fp:
                continue
            seen_fp.add(fp)
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

    if dry_run:
        print(f"Bracket inference ({format_name}): {len(match_rows)} matches "
              f"from {len(rows)} events (dry run — not saved)")
        return len(match_rows)

    saved = save_matches(match_rows)
    print(f"Bracket inference ({format_name}): saved {saved} matches "
          f"from {len(rows)} events")
    return saved


def date_health(format_name: str | None = None) -> dict:
    """Read-only one-off check (#19): count matches rows whose stored
    `event_date` is NOT already ISO `YYYY-MM-DD`, and count inferred
    `bracket_*` rows (bracket_finals kept, bracket_sf no longer produced).
    Returns {non_iso, bracket_finals, bracket_sf}."""
    from db.database import get_connection
    where = "WHERE lower(format)=lower(?)" if format_name else ""
    args = (format_name,) if format_name else ()
    with get_connection() as conn:
        non_iso = conn.execute(
            f"SELECT COUNT(*) AS n FROM matches {where}"
            f"{' AND' if where else 'WHERE'} event_date IS NOT NULL "
            "AND event_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'",
            args,
        ).fetchone()["n"]
        by_src = dict(conn.execute(
            f"SELECT source, COUNT(*) AS n FROM matches {where}"
            f"{' AND' if where else 'WHERE'} source LIKE 'bracket%' GROUP BY source",
            args,
        ).fetchall())
    out = {"non_iso": non_iso,
           "bracket_finals": by_src.get("bracket_finals", 0),
           "bracket_sf": by_src.get("bracket_sf", 0)}
    print(f"date_health({format_name or 'all'}): {out}")
    return out


def cleanup_league_bracket_rows(dry_run: bool = True) -> int:
    """One-off: delete inferred `bracket_*` rows that an earlier run fabricated
    for League / Preliminary events (which have no single-elim cut). Dry-run by
    default -- reports the count; pass dry_run=False to delete. Live-DB write."""
    from db.database import get_combined_connection, get_connection
    from scrapers.challenges import classify_event_type

    conn = get_combined_connection()
    try:
        ev_rows = conn.execute(
            "SELECT id, name, event_type FROM events"
        ).fetchall()
    finally:
        conn.close()

    no_cut = {
        str(r["id"]) for r in ev_rows
        if (r["event_type"] or classify_event_type(r["name"] or "")) in ("mtgo_league", "mtgo_preliminary")
    }
    if not no_cut:
        print("cleanup_league_bracket_rows: no League/Preliminary events found")
        return 0

    with get_connection() as conn:
        placeholders = ",".join("?" for _ in no_cut)
        doomed = conn.execute(
            f"SELECT COUNT(*) AS n FROM matches "
            f"WHERE source LIKE 'bracket%' AND event_id IN ({placeholders})",
            tuple(no_cut),
        ).fetchone()["n"]
        if dry_run:
            print(f"cleanup_league_bracket_rows: would delete {doomed} bracket row(s) "
                  f"from {len(no_cut)} League/Preliminary event(s) (dry run)")
            return doomed
        conn.execute(
            f"DELETE FROM matches "
            f"WHERE source LIKE 'bracket%' AND event_id IN ({placeholders})",
            tuple(no_cut),
        )
        conn.commit()
    print(f"cleanup_league_bracket_rows: deleted {doomed} bracket row(s) "
          f"from {len(no_cut)} League/Preliminary event(s)")
    return doomed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_int(val) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(val)))
    except (ValueError, TypeError):
        return 0


def _normalise_date(raw: str) -> str:
    """Normalise a date string to ISO YYYY-MM-DD; returns the raw string on
    failure. Delegates to db.helpers.normalize_event_date, which reads
    DD/MM/YY and DD/MM/YYYY correctly -- the old copy tried %m/%d first and had
    no two-digit-year pattern, so MTGTop8 `events.date` values fed to
    infer_bracket_matches were mis-dated (#19)."""
    from db.helpers import normalize_event_date
    return normalize_event_date(raw) or (raw or "").strip()


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
    try:
        tournaments = fetch_tournament_list(fmt_display, min_players=32, pages=1)
    except DiscoveryFailed as exc:
        print(f"\nDISCOVERY FAILED: {exc}")
        return
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
    parser.add_argument("--cleanup-league-brackets", action="store_true",
                        help="Delete inferred bracket rows wrongly recorded for League/"
                             "Preliminary events (dry run unless --commit-cleanup)")
    parser.add_argument("--commit-cleanup", action="store_true",
                        help="Actually delete with --cleanup-league-brackets (default is dry run)")
    parser.add_argument("--date-health", action="store_true",
                        help="Count non-ISO matches.event_date rows + bracket_* rows (read-only)")
    parser.add_argument("--counts",  action="store_true",
                        help="Show stored match counts per format and exit")
    parser.add_argument("--tournament-id", action="append", default=[],
                        help="Scrape only this tournament id (repeatable; targeted backfill, "
                             "idempotent); must appear in the --pages search window")
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

    if args.date_health:
        date_health(args.format)
        return

    if args.cleanup_league_brackets:
        cleanup_league_bracket_rows(dry_run=not args.commit_cleanup)
        return

    if args.infer_brackets:
        infer_bracket_matches(args.format, dry_run=args.dry_run)
        return

    # A discovery outage (probe/page failure, recordsTotal=0) exits nonzero so
    # the #16 pipeline records an error instead of a silent 'ok, no data' (#18).
    try:
        if args.tournament_id:
            scrape_tournaments(args.tournament_id, args.format, pages=args.pages, dry_run=args.dry_run)
            if LAST_INCOMPLETE:
                sys.exit(2)
            return

        scrape_and_store(
            format_name=args.format,
            pages=args.pages,
            min_players=args.min_players,
            dry_run=args.dry_run,
        )
    except DiscoveryFailed as exc:
        log.error("*** MELEE DISCOVERY FAILED *** %s", exc)
        sys.exit(2)

    if LAST_INCOMPLETE:
        # Pipeline (#16) treats a nonzero rc as an error outcome for this source.
        sys.exit(2)


if __name__ == "__main__":
    main()
