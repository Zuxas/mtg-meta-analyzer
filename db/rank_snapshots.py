"""MTGA rank progression tracking.

Stores point-in-time snapshots of the user's constructed (and limited)
rank from MTGA Player.log. One row per capture. Over time, building a
time series; deltas computed via consecutive rows.

Tables:
    rank_snapshots
        id              auto PK
        captured_at_utc ISO timestamp
        format          'constructed' or 'limited'
        season_ordinal  int (89 for current season)
        class           'Bronze' / 'Silver' / 'Gold' / 'Platinum' /
                        'Diamond' / 'Mythic'
        level           int 1-4 (within tier)
        wins            lifetime W in this season
        losses          lifetime L in this season
        notes           optional ('background_fill', 'manual', etc.)

Public API:
    save_snapshot(format_name, season, class_name, level, wins, losses,
                  notes='') -> int
    get_latest(format_name='constructed') -> dict | None
    get_recent(format_name='constructed', limit=30) -> list[dict]
    delta_today(format_name='constructed') -> dict | None
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, date, timezone
from typing import Optional

from db.database import get_connection


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS rank_snapshots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at_utc TEXT NOT NULL,
        format          TEXT NOT NULL,
        season_ordinal  INTEGER NOT NULL,
        class           TEXT NOT NULL,
        level           INTEGER NOT NULL,
        wins            INTEGER NOT NULL DEFAULT 0,
        losses          INTEGER NOT NULL DEFAULT 0,
        notes           TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_rank_snapshots_format_at
        ON rank_snapshots(format, captured_at_utc);
"""

# Rank "score" for delta computation: lower = lower rank.
# Each tier has 4 levels (1 = entry, 4 = top of tier).
_CLASS_ORDER = {
    "Bronze": 0,
    "Silver": 1,
    "Gold": 2,
    "Platinum": 3,
    "Diamond": 4,
    "Mythic": 5,
}


def _ensure_table(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        conn.executescript(_CREATE_SQL)
        conn.commit()
    finally:
        if own:
            conn.close()


def rank_score(class_name: str, level: int) -> int:
    """Return a comparable integer where higher = higher rank.

    Score = tier * 100 + level (so Diamond 4 = 404, Platinum 3 = 303, etc.).
    Mythic is special -- level can go above 4 for Mythic% rank, but we
    just use the level here. Mythic 1 = 501.
    """
    tier = _CLASS_ORDER.get(class_name, 0)
    return tier * 100 + (level or 0)


def save_snapshot(format_name: str, season_ordinal: int, class_name: str,
                  level: int, wins: int, losses: int,
                  notes: str = "",
                  captured_at_utc: Optional[str] = None) -> int:
    if captured_at_utc is None:
        captured_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT INTO rank_snapshots "
            "(captured_at_utc, format, season_ordinal, class, level, "
            " wins, losses, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (captured_at_utc, format_name, season_ordinal, class_name,
             level, wins, losses, notes),
        )
        conn.commit()
        return cur.lastrowid


def get_latest(format_name: str = "constructed") -> Optional[dict]:
    """Return the most-recent snapshot for the given format."""
    with get_connection() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT * FROM rank_snapshots WHERE format = ? "
            "ORDER BY captured_at_utc DESC LIMIT 1",
            (format_name,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_recent(format_name: str = "constructed",
               limit: int = 30) -> list[dict]:
    """Return recent snapshots, newest first."""
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM rank_snapshots WHERE format = ? "
            "ORDER BY captured_at_utc DESC LIMIT ?",
            (format_name, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delta_today(format_name: str = "constructed") -> Optional[dict]:
    """Compute rank delta from the FIRST snapshot today to the LATEST.

    Returns {
        'start_class', 'start_level', 'end_class', 'end_level',
        'rank_delta',  # in score units (positive = climb)
        'wins_today', 'losses_today',
        'n_snapshots_today',
    } or None if no snapshots today.
    """
    today_iso = date.today().isoformat()
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM rank_snapshots WHERE format = ? "
            "AND captured_at_utc >= ? ORDER BY captured_at_utc ASC",
            (format_name, today_iso),
        ).fetchall()
    if not rows:
        return None
    first = dict(rows[0])
    last = dict(rows[-1])
    return {
        "start_class": first["class"],
        "start_level": first["level"],
        "end_class": last["class"],
        "end_level": last["level"],
        "rank_delta": (rank_score(last["class"], last["level"]) -
                       rank_score(first["class"], first["level"])),
        "wins_today": last["wins"] - first["wins"],
        "losses_today": last["losses"] - first["losses"],
        "n_snapshots_today": len(rows),
    }
