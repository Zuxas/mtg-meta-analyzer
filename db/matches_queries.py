"""
DB helpers for the real match results table.

Schema (created on first use in active DB):
    matches (id, event_id, round, player1, player2,
             player1_arch, player2_arch, winner_arch,
             result, format, event_date, source)

result values: 'player1' | 'player2' | 'draw'
source values: 'mtgmelee' | 'bracket_finals' | 'bracket_sf' | 'bracket_qf'
"""

from db.database import get_connection
from db.helpers import ensure_table as _do_ensure


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS matches (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id      TEXT    NOT NULL,
        round         INTEGER,
        player1       TEXT,
        player2       TEXT,
        player1_arch  TEXT    NOT NULL,
        player2_arch  TEXT    NOT NULL,
        winner_arch   TEXT,
        result        TEXT,
        format        TEXT    NOT NULL,
        event_date    TEXT,
        source        TEXT    NOT NULL DEFAULT 'mtgmelee',
        UNIQUE(event_id, round, player1, player2)
    );
    CREATE INDEX IF NOT EXISTS idx_matches_format
        ON matches(format);
    CREATE INDEX IF NOT EXISTS idx_matches_event
        ON matches(event_id);
    CREATE INDEX IF NOT EXISTS idx_matches_archs
        ON matches(player1_arch, player2_arch);
"""


def _ensure_table():
    _do_ensure(_CREATE_SQL)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_matches(match_rows: list[dict]) -> int:
    """
    Upsert a list of match dicts.  Each dict must have:
        event_id, round, player1, player2,
        player1_arch, player2_arch, winner_arch,
        result, format, event_date, source
    Returns the number of rows inserted/replaced.
    """
    if not match_rows:
        return 0
    _ensure_table()
    rows = [
        (
            m["event_id"],
            m.get("round"),
            m.get("player1", ""),
            m.get("player2", ""),
            m["player1_arch"],
            m["player2_arch"],
            m.get("winner_arch"),
            m.get("result"),
            m["format"].lower(),
            m.get("event_date"),
            m.get("source", "mtgmelee"),
        )
        for m in match_rows
    ]
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO matches
                (event_id, round, player1, player2,
                 player1_arch, player2_arch, winner_arch,
                 result, format, event_date, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_matches(format_name: str, since=None, source: str = None) -> list[dict]:
    """Return all stored matches for a format, optionally filtered by date/source."""
    _ensure_table()
    q = "SELECT * FROM matches WHERE lower(format) = lower(?)"
    params = [format_name]
    if since:
        q += " AND event_date >= ?"
        params.append(since.strftime("%Y-%m-%d") if hasattr(since, "strftime") else str(since))
    if source:
        q += " AND source = ?"
        params.append(source)
    q += " ORDER BY event_date DESC, id DESC"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_stored_event_ids(format_name: str, source: str = "mtgmelee") -> set:
    """Return the set of event_ids already stored for a format+source (for dedup)."""
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT event_id FROM matches WHERE lower(format)=lower(?) AND source=?",
            (format_name, source),
        ).fetchall()
    return {r["event_id"] for r in rows}


def get_match_counts(format_name: str) -> dict:
    """Return {source: count} for a format."""
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) as n FROM matches WHERE lower(format)=lower(?) GROUP BY source",
            (format_name,),
        ).fetchall()
    return {r["source"]: r["n"] for r in rows}
