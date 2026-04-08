"""
DB helpers for the scraped matchup matrix table.

Schema (added to the active DB on first use):
    matchup_matrix (format, archetype_a, archetype_b, winrate, matches, fetched_at)

All functions follow the same connection pattern as database.py.
"""

from datetime import datetime

from db.database import get_connection


_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS matchup_matrix (
        format      TEXT    NOT NULL,
        archetype_a TEXT    NOT NULL,
        archetype_b TEXT    NOT NULL,
        winrate     REAL    NOT NULL,
        matches     INTEGER NOT NULL DEFAULT 0,
        fetched_at  TEXT    NOT NULL,
        PRIMARY KEY (format, archetype_a, archetype_b)
    );
"""


def _ensure_table():
    with get_connection() as conn:
        conn.execute(_CREATE_TABLE)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_matchup_data(format_name: str, matrix: dict):
    """
    Upsert all rows from a scraped matrix dict.
    matrix: {archetype_a: {archetype_b: {"winrate": float, "matches": int}}}
    """
    _ensure_table()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    rows = []
    for arch_a, opponents in matrix.items():
        for arch_b, stats in opponents.items():
            rows.append((
                format_name.lower(),
                arch_a, arch_b,
                stats["winrate"],
                stats.get("matches", 0),
                now,
            ))

    with get_connection() as conn:
        conn.executemany("""
            INSERT INTO matchup_matrix
                (format, archetype_a, archetype_b, winrate, matches, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(format, archetype_a, archetype_b) DO UPDATE SET
                winrate    = excluded.winrate,
                matches    = excluded.matches,
                fetched_at = excluded.fetched_at
        """, rows)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_matchup_matrix(format_name: str) -> dict:
    """
    Return {archetype_a: {archetype_b: {"winrate": float, "matches": int}}}
    for all cached matchups in the given format, or {} if none stored yet.
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT archetype_a, archetype_b, winrate, matches
            FROM matchup_matrix
            WHERE lower(format) = lower(?)
            ORDER BY archetype_a, archetype_b
        """, (format_name,)).fetchall()

    result = {}
    for r in rows:
        result.setdefault(r["archetype_a"], {})[r["archetype_b"]] = {
            "winrate": r["winrate"],
            "matches": r["matches"],
        }
    return result


# ---------------------------------------------------------------------------
# Matchup notes (team annotations per cell)
# ---------------------------------------------------------------------------

_CREATE_NOTES_TABLE = """
    CREATE TABLE IF NOT EXISTS matchup_notes (
        format      TEXT NOT NULL,
        archetype_a TEXT NOT NULL,
        archetype_b TEXT NOT NULL,
        note        TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL,
        PRIMARY KEY (format, archetype_a, archetype_b)
    );
"""


def _ensure_notes_table():
    with get_connection() as conn:
        conn.execute(_CREATE_NOTES_TABLE)


def save_matchup_note(format_name: str, arch_a: str, arch_b: str, note: str):
    """Upsert a team note for a specific matchup cell."""
    _ensure_notes_table()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection() as conn:
        if note.strip():
            conn.execute("""
                INSERT INTO matchup_notes (format, archetype_a, archetype_b, note, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(format, archetype_a, archetype_b) DO UPDATE SET
                    note = excluded.note, updated_at = excluded.updated_at
            """, (format_name.lower(), arch_a, arch_b, note.strip(), now))
        else:
            conn.execute("""
                DELETE FROM matchup_notes
                WHERE format = ? AND archetype_a = ? AND archetype_b = ?
            """, (format_name.lower(), arch_a, arch_b))


def get_matchup_notes(format_name: str) -> dict:
    """Return {(arch_a, arch_b): note_text} for all notes in a format."""
    _ensure_notes_table()
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT archetype_a, archetype_b, note
            FROM matchup_notes
            WHERE format = ? AND note != ''
        """, (format_name.lower(),)).fetchall()
    return {(r["archetype_a"], r["archetype_b"]): r["note"] for r in rows}


def get_last_updated(format_name: str) -> str | None:
    """
    Return the most recent fetched_at timestamp string for a format, or None
    if no data has been fetched yet.
    """
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute("""
            SELECT MAX(fetched_at) AS ts
            FROM matchup_matrix
            WHERE lower(format) = lower(?)
        """, (format_name,)).fetchone()
    return row["ts"] if row and row["ts"] else None
