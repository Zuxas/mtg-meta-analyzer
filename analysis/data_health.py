"""
Per-format data freshness -- derived from the rows that actually exist.

`scrape_state.json` records what the LAST RUN said about itself. This module
answers the question that matters: for each format, when is the newest match
row, and is the flow still alive? Until 2026-09-20 a global `last_status: ok`
sat next to a `matches` table with no Modern rows for ten weeks.

Dates are normalized (db.helpers.SQL_NORM_DATE) before any MAX()/comparison,
because `matches.event_date` and `events.date` mix `YYYY-MM-DD` and
`dd/mm/yy` in the same column.

Usage:
    from analysis.data_health import format_freshness
    format_freshness()                 # every format present in either table
    format_freshness(["modern"])       # explicit list; absent formats -> dead
"""
from datetime import date, datetime, timedelta

from db.helpers import SQL_NORM_DATE

FRESH_MAX_DAYS = 9      # days_stale <= 9  -> "fresh"   (spec: < 10)
STALE_MAX_DAYS = 30     # 10..30           -> "stale";  > 30 -> "dead"
DEAD_WINDOW_DAYS = 60   # zero rows in the last 60 days -> "dead" regardless

STATUS_FRESH, STATUS_STALE, STATUS_DEAD = "fresh", "stale", "dead"

_MATCH_DATE = SQL_NORM_DATE.format(col="event_date")
_EVENT_DATE = SQL_NORM_DATE.format(col="date")
# A normalized value is trustworthy only if it parses as a real date; junk
# rows ('99/99/99', 'not a date') would otherwise win a MAX().
_VALID = "({d} GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]')"


def _empty() -> dict:
    return {
        "last_match_date": None, "last_event_date": None,
        "matches_30d": 0, "matches_prev_30d": 0,
        "days_stale": None, "status": STATUS_DEAD,
    }


def classify(days_stale, matches_30d: int, matches_prev_30d: int) -> str:
    if days_stale is None or days_stale > STALE_MAX_DAYS:
        return STATUS_DEAD
    if matches_30d + matches_prev_30d == 0:
        return STATUS_DEAD
    if days_stale <= FRESH_MAX_DAYS:
        return STATUS_FRESH
    return STATUS_STALE


def _known_formats(con) -> list:
    rows = con.execute(
        "SELECT DISTINCT lower(format) AS f FROM matches WHERE format IS NOT NULL "
        "UNION SELECT DISTINCT lower(format) FROM events WHERE format IS NOT NULL"
    ).fetchall()
    return sorted(r[0] for r in rows if r[0])


def format_freshness(formats=None, *, con=None, today=None) -> dict:
    """
    {format: {last_match_date, last_event_date, matches_30d, matches_prev_30d,
              days_stale, status}}   -- dates ISO, status fresh|stale|dead.

    `formats=None` means every format present in `matches` or `events`.
    `con` / `today` are injectable for tests; defaults are the live DB and
    today's date.
    """
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    d30 = (today - timedelta(days=30)).isoformat()
    d60 = (today - timedelta(days=60)).isoformat()

    own = con is None
    if own:
        from db.database import get_connection
        con = get_connection()
    try:
        fmts = [f.lower() for f in formats] if formats else _known_formats(con)
        out = {}
        for fmt in fmts:
            info = _empty()
            row = con.execute(f"""
                SELECT MAX(CASE WHEN {_VALID.format(d=_MATCH_DATE)} THEN {_MATCH_DATE} END),
                       SUM(CASE WHEN {_MATCH_DATE} >= ? THEN 1 ELSE 0 END),
                       SUM(CASE WHEN {_MATCH_DATE} >= ? AND {_MATCH_DATE} < ? THEN 1 ELSE 0 END)
                FROM matches WHERE lower(format) = ?
            """, (d30, d60, d30, fmt)).fetchone()
            info["last_match_date"] = row[0]
            info["matches_30d"] = int(row[1] or 0)
            info["matches_prev_30d"] = int(row[2] or 0)
            info["last_event_date"] = con.execute(f"""
                SELECT MAX(CASE WHEN {_VALID.format(d=_EVENT_DATE)} THEN {_EVENT_DATE} END)
                FROM events WHERE lower(format) = ?
            """, (fmt,)).fetchone()[0]
            if info["last_match_date"]:
                last = date.fromisoformat(info["last_match_date"])
                info["days_stale"] = (today - last).days
            info["status"] = classify(info["days_stale"], info["matches_30d"],
                                      info["matches_prev_30d"])
            out[fmt] = info
        return out
    finally:
        if own:
            con.close()


def describe_freshness(fmt: str, info: dict) -> str:
    """One human-readable line for tooltips / logs."""
    name = fmt.capitalize()
    if not info or not info.get("last_match_date"):
        ev = info.get("last_event_date") if info else None
        tail = f" (events to {ev}, but no match rows)" if ev else ""
        return f"{name}: NO MATCH DATA{tail}"
    n = info["days_stale"]
    return (f"{name}: {info['status']} -- last match data {info['last_match_date']} "
            f"({n} day{'s' if n != 1 else ''} ago); {info['matches_30d']:,} matches in "
            f"the last 30 days ({info['matches_prev_30d']:,} the 30 before)")
