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
from datetime import datetime, timezone
from db.database import get_connection


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
    with get_connection() as conn:
        conn.executescript(_CREATE_SQL)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_match(event_name: str, event_date: str, format_name: str,
               round_num: int, my_deck: str, opp_deck: str,
               opp_name: str = "", result: str = "",
               play_draw: str = "",
               g1_result: str = "", g2_result: str = "", g3_result: str = "",
               notes: str = "", match_id: int = None) -> int:
    """Insert or update a match log entry. Returns the row id."""
    _ensure_table()
    with get_connection() as conn:
        if match_id is not None:
            conn.execute("""
                UPDATE match_log SET event_name=?, event_date=?, format=?,
                    round=?, my_deck=?, opp_deck=?, opp_name=?, result=?,
                    play_draw=?, g1_result=?, g2_result=?, g3_result=?, notes=?
                WHERE id=?
            """, (event_name, event_date, format_name, round_num,
                  my_deck, opp_deck, opp_name, result, play_draw,
                  g1_result, g2_result, g3_result, notes, match_id))
            return match_id
        else:
            cur = conn.execute("""
                INSERT INTO match_log
                    (event_name, event_date, format, round, my_deck, opp_deck,
                     opp_name, result, play_draw, g1_result, g2_result, g3_result,
                     notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_name, event_date, format_name, round_num,
                  my_deck, opp_deck, opp_name, result, play_draw,
                  g1_result, g2_result, g3_result, notes, _now()))
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
