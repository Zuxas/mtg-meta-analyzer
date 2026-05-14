"""
DB helpers for personal match logging.

Schema:
    match_log
        id              — auto PK
        event_name      — e.g. "RCQ @ Card Kingdom", "FNM", "MTGO League"
        event_date      — YYYY-MM-DD
        format          — standard/modern/pioneer/legacy/pauper
        round           — round number (1, 2, 3...)
        my_deck         — your archetype (e.g. "Boros Energy")
        opp_deck        — opponent archetype
        opp_name        — opponent name (optional)
        result          — "win" / "loss" / "draw"
        play_draw       — "play" / "draw" / "" (unknown)
        g1_result       — "win" / "loss" / "" (game 1)
        g2_result       — "win" / "loss" / "" (game 2)
        g3_result       — "win" / "loss" / "" (game 3, blank if no g3)
        notes           — free text notes
        created_at      — ISO timestamp
"""
import json
from db.database import get_connection
from db.helpers import ensure_table as _do_ensure, utc_now as _now


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS match_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name  TEXT    NOT NULL DEFAULT '',
        event_date  TEXT    NOT NULL DEFAULT '',
        format      TEXT    NOT NULL DEFAULT 'standard',
        round       INTEGER NOT NULL DEFAULT 0,
        my_deck     TEXT    NOT NULL DEFAULT '',
        opp_deck    TEXT    NOT NULL DEFAULT '',
        opp_name    TEXT    NOT NULL DEFAULT '',
        result      TEXT    NOT NULL DEFAULT '',
        play_draw   TEXT    NOT NULL DEFAULT '',
        g1_result   TEXT    NOT NULL DEFAULT '',
        g2_result   TEXT    NOT NULL DEFAULT '',
        g3_result   TEXT    NOT NULL DEFAULT '',
        notes       TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_match_log_format ON match_log(format);
    CREATE INDEX IF NOT EXISTS idx_match_log_deck ON match_log(my_deck);
    CREATE INDEX IF NOT EXISTS idx_match_log_opp ON match_log(opp_deck);
    CREATE INDEX IF NOT EXISTS idx_match_log_date ON match_log(event_date);
"""


def _ensure_table():
    _do_ensure(_CREATE_SQL)
    # Additive migrations — safe to re-run; OperationalError = column exists
    import sqlite3
    with get_connection() as conn:
        for stmt in [
            "ALTER TABLE match_log ADD COLUMN swap_notes TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE match_log ADD COLUMN swap_verdict TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE match_log ADD COLUMN my_deck_id INTEGER",
            "ALTER TABLE match_log ADD COLUMN my_variant_hash TEXT",
            "ALTER TABLE match_log ADD COLUMN opp_grp_ids_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE match_log ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'",
            "ALTER TABLE match_log ADD COLUMN backfill_status TEXT NOT NULL DEFAULT 'live'",
            "CREATE INDEX IF NOT EXISTS idx_match_log_deck_id ON match_log(my_deck_id)",
            "CREATE INDEX IF NOT EXISTS idx_match_log_variant ON match_log(my_variant_hash)",
            "CREATE INDEX IF NOT EXISTS idx_match_log_backfill ON match_log(backfill_status)",
            "ALTER TABLE match_log ADD COLUMN arena_match_id TEXT",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_match_log_arena_id ON match_log(arena_match_id) WHERE arena_match_id IS NOT NULL",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
    # Delegate deck_variants CREATE
    from db.deck_variants import _ensure_table as _ensure_deck_variants
    _ensure_deck_variants()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_match(event_name: str, event_date: str, format_name: str,
               round_num: int, my_deck: str, opp_deck: str,
               opp_name: str = "", result: str = "",
               play_draw: str = "",
               g1_result: str = "", g2_result: str = "", g3_result: str = "",
               notes: str = "", swap_notes: str = "", swap_verdict: str = "",
               match_id: int = None) -> int:
    """Insert or update a match log entry. Returns the row id.

    swap_notes: free-text 'what I changed for this match' (e.g.,
        'in: 2 Dismember, out: 2 Lightning Helix')
    swap_verdict: '' (no verdict yet) / 'kept' / 'reverted' — hindsight
        flag set after the match to track whether the swap paid off.
    """
    _ensure_table()
    with get_connection() as conn:
        if match_id is not None:
            conn.execute("""
                UPDATE match_log SET event_name=?, event_date=?, format=?,
                    round=?, my_deck=?, opp_deck=?, opp_name=?, result=?,
                    play_draw=?, g1_result=?, g2_result=?, g3_result=?,
                    notes=?, swap_notes=?, swap_verdict=?
                WHERE id=?
            """, (event_name, event_date, format_name, round_num,
                  my_deck, opp_deck, opp_name, result, play_draw,
                  g1_result, g2_result, g3_result, notes,
                  swap_notes, swap_verdict, match_id))
            return match_id
        else:
            cur = conn.execute("""
                INSERT INTO match_log
                    (event_name, event_date, format, round, my_deck, opp_deck,
                     opp_name, result, play_draw, g1_result, g2_result, g3_result,
                     notes, swap_notes, swap_verdict, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_name, event_date, format_name, round_num,
                  my_deck, opp_deck, opp_name, result, play_draw,
                  g1_result, g2_result, g3_result, notes,
                  swap_notes, swap_verdict, _now()))
            return cur.lastrowid


def delete_match(match_id: int):
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM match_log WHERE id=?", (match_id,))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_matches(format_name: str = None, my_deck: str = None,
                since: str = None, limit: int = 200) -> list[dict]:
    """Return match log entries, newest first."""
    _ensure_table()
    q = "SELECT * FROM match_log WHERE 1=1"
    params = []
    if format_name:
        q += " AND lower(format) = lower(?)"
        params.append(format_name)
    if my_deck:
        q += " AND my_deck = ?"
        params.append(my_deck)
    if since:
        q += " AND event_date >= ?"
        params.append(since)
    q += " ORDER BY event_date DESC, round DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_matchup_stats(my_deck: str, format_name: str = None,
                      since: str = None) -> dict:
    """Aggregate personal W/L/D stats per opponent archetype.

    Returns: {opp_deck: {"wins": int, "losses": int, "draws": int,
                          "total": int, "wr": float, "play_wr": float, "draw_wr": float}}
    """
    _ensure_table()
    q = "SELECT * FROM match_log WHERE my_deck = ?"
    params = [my_deck]
    if format_name:
        q += " AND lower(format) = lower(?)"
        params.append(format_name)
    if since:
        q += " AND event_date >= ?"
        params.append(since)
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()

    stats = {}
    for r in rows:
        opp = r["opp_deck"]
        if opp not in stats:
            stats[opp] = {"wins": 0, "losses": 0, "draws": 0, "total": 0,
                          "play_w": 0, "play_l": 0, "draw_w": 0, "draw_l": 0}
        s = stats[opp]
        s["total"] += 1
        if r["result"] == "win":
            s["wins"] += 1
        elif r["result"] == "loss":
            s["losses"] += 1
        elif r["result"] == "draw":
            s["draws"] += 1
        # Play/draw splits
        if r["play_draw"] == "play":
            if r["result"] == "win":
                s["play_w"] += 1
            elif r["result"] == "loss":
                s["play_l"] += 1
        elif r["play_draw"] == "draw":
            if r["result"] == "win":
                s["draw_w"] += 1
            elif r["result"] == "loss":
                s["draw_l"] += 1

    # Compute rates
    for opp, s in stats.items():
        decisive = s["wins"] + s["losses"]
        s["wr"] = round(s["wins"] / decisive, 3) if decisive else 0.0
        play_d = s["play_w"] + s["play_l"]
        s["play_wr"] = round(s["play_w"] / play_d, 3) if play_d else None
        draw_d = s["draw_w"] + s["draw_l"]
        s["draw_wr"] = round(s["draw_w"] / draw_d, 3) if draw_d else None

    return stats


def get_overall_stats(my_deck: str = None, format_name: str = None,
                      since: str = None) -> dict:
    """Overall W/L/D summary."""
    _ensure_table()
    q = "SELECT result, COUNT(*) as n FROM match_log WHERE 1=1"
    params = []
    if my_deck:
        q += " AND my_deck = ?"
        params.append(my_deck)
    if format_name:
        q += " AND lower(format) = lower(?)"
        params.append(format_name)
    if since:
        q += " AND event_date >= ?"
        params.append(since)
    q += " GROUP BY result"
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    totals = {"wins": 0, "losses": 0, "draws": 0, "total": 0}
    for r in rows:
        if r["result"] == "win":
            totals["wins"] = r["n"]
        elif r["result"] == "loss":
            totals["losses"] = r["n"]
        elif r["result"] == "draw":
            totals["draws"] = r["n"]
    totals["total"] = totals["wins"] + totals["losses"] + totals["draws"]
    decisive = totals["wins"] + totals["losses"]
    totals["wr"] = round(totals["wins"] / decisive, 3) if decisive else 0.0
    return totals


def resolve_and_save(event_name: str, event_date: str, format_name: str,
                     round_num: int, my_deck_id: int | None, opp_deck: str,
                     result: str, source: str,
                     play_draw: str = "", opp_name: str = "",
                     g1_result: str = "", g2_result: str = "",
                     g3_result: str = "", notes: str = "",
                     opp_grp_ids: list[int] | None = None,
                     arena_match_id: str | None = None) -> int:
    """Insert a match_log row with full variant linkage.

    If my_deck_id is provided, resolves the current saved_decks snapshot and
    upserts a deck_variants row; the match_log row gets my_variant_hash set
    and backfill_status='live'.

    If my_deck_id is None, the row is inserted with backfill_status='orphan'
    so the Resolve... UI can pick it up later.

    Returns the new match_log.id."""
    _ensure_table()
    from db.deck_variants import upsert_variant
    from db.saved_decks import get_decks

    variant_hash: str | None = None
    backfill_status = "live"
    if my_deck_id is None:
        backfill_status = "orphan"
    else:
        decks = [d for d in get_decks() if d["id"] == my_deck_id]
        if not decks:
            backfill_status = "orphan"
            my_deck_id = None
        else:
            deck = decks[0]
            variant_hash = upsert_variant(
                deck_id=my_deck_id,
                mainboard=deck.get("mainboard", {}) or {},
                sideboard=deck.get("sideboard", {}) or {},
                won=(result == "win"),
            )

    my_deck_string = ""
    if my_deck_id is not None:
        d = next((x for x in get_decks() if x["id"] == my_deck_id), None)
        if d:
            my_deck_string = d.get("archetype", "") or d.get("name", "")

    opp_grp_json = json.dumps(opp_grp_ids or [], separators=(",", ":"))

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO match_log
                (event_name, event_date, format, round, my_deck, opp_deck,
                 opp_name, result, play_draw, g1_result, g2_result, g3_result,
                 notes, swap_notes, swap_verdict, created_at,
                 my_deck_id, my_variant_hash, opp_grp_ids_json, source,
                 backfill_status, arena_match_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?)
            """,
            (event_name, event_date, format_name, round_num, my_deck_string,
             opp_deck, opp_name, result, play_draw, g1_result, g2_result,
             g3_result, notes, "", "", _now(),
             my_deck_id, variant_hash, opp_grp_json, source,
             backfill_status, arena_match_id),
        )
        return cur.lastrowid


def get_trend_data(my_deck: str = None, format_name: str = None) -> list[dict]:
    """Win rate trend grouped by event date.

    Returns list of {"date": str, "wins": int, "losses": int, "draws": int,
                      "total": int, "wr": float, "cumulative_wr": float}
    sorted by date ascending.
    """
    _ensure_table()
    q = """
        SELECT event_date, result, COUNT(*) AS n
        FROM match_log WHERE event_date IS NOT NULL AND event_date != ''
    """
    params = []
    if my_deck:
        q += " AND my_deck = ?"
        params.append(my_deck)
    if format_name:
        q += " AND lower(format) = lower(?)"
        params.append(format_name)
    q += " GROUP BY event_date, result ORDER BY event_date ASC"

    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()

    # Group by date
    from collections import OrderedDict
    dates: OrderedDict = OrderedDict()
    for r in rows:
        d = r["event_date"][:10]
        if d not in dates:
            dates[d] = {"date": d, "wins": 0, "losses": 0, "draws": 0}
        if r["result"] == "win":
            dates[d]["wins"] = r["n"]
        elif r["result"] == "loss":
            dates[d]["losses"] = r["n"]
        elif r["result"] == "draw":
            dates[d]["draws"] = r["n"]

    result = []
    cum_w, cum_l = 0, 0
    for d in dates.values():
        d["total"] = d["wins"] + d["losses"] + d["draws"]
        decisive = d["wins"] + d["losses"]
        d["wr"] = round(d["wins"] / decisive, 3) if decisive else 0.0
        cum_w += d["wins"]
        cum_l += d["losses"]
        cum_decisive = cum_w + cum_l
        d["cumulative_wr"] = round(cum_w / cum_decisive, 3) if cum_decisive else 0.0
        result.append(d)

    return result
