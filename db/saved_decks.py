"""
DB helpers for user-saved decks and per-matchup sideboard plans.

Schema:

    saved_decks
        id          — auto PK
        name        — user-given deck name (e.g. "My RCQ Pile")
        format      — lowercase format string (e.g. "standard")
        archetype   — normalised archetype name (e.g. "Izzet Prowess")
        mainboard   — JSON object: {"Card Name": quantity, ...}
        sideboard   — JSON object: {"Card Name": quantity, ...}
        notes       — free-text notes
        created_at  — ISO-8601 timestamp

    saved_sb_plans
        id                  — auto PK
        deck_id             — FK → saved_decks.id (CASCADE DELETE)
        opponent_archetype  — normalised opponent archetype
        play_in             — JSON list of card names to bring in on the play
        play_out            — JSON list of card names to take out on the play
        draw_in             — JSON list of card names to bring in on the draw
        draw_out            — JSON list of card names to take out on the draw
        notes               — free-text notes for this matchup
        difficulty          — "Easy" | "Medium" | "Hard" (sideboarding difficulty)
        updated_at          — ISO-8601 timestamp
"""

import json
from datetime import datetime, timezone

from db.database import get_connection


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS saved_decks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        format      TEXT    NOT NULL DEFAULT '',
        archetype   TEXT    NOT NULL DEFAULT '',
        mainboard   TEXT    NOT NULL DEFAULT '{}',
        sideboard   TEXT    NOT NULL DEFAULT '{}',
        notes       TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS saved_sb_plans (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        deck_id             INTEGER NOT NULL REFERENCES saved_decks(id) ON DELETE CASCADE,
        opponent_archetype  TEXT    NOT NULL DEFAULT '',
        play_in             TEXT    NOT NULL DEFAULT '[]',
        play_out            TEXT    NOT NULL DEFAULT '[]',
        draw_in             TEXT    NOT NULL DEFAULT '[]',
        draw_out            TEXT    NOT NULL DEFAULT '[]',
        notes               TEXT    NOT NULL DEFAULT '',
        difficulty          TEXT    NOT NULL DEFAULT 'Medium',
        updated_at          TEXT    NOT NULL,
        UNIQUE(deck_id, opponent_archetype)
    );

    CREATE INDEX IF NOT EXISTS idx_saved_decks_format
        ON saved_decks(format);
    CREATE INDEX IF NOT EXISTS idx_sb_plans_deck
        ON saved_sb_plans(deck_id);
"""


def _ensure_tables():
    with get_connection() as conn:
        conn.executescript(_CREATE_SQL)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Saved decks — write
# ---------------------------------------------------------------------------

def save_deck(name: str, format_name: str, archetype: str,
              mainboard: dict, sideboard: dict,
              notes: str = "", deck_id: int = None) -> int:
    """
    Insert a new saved deck or update an existing one.

    Pass deck_id to update an existing row; omit (or pass None) to insert new.
    Returns the row id.

    mainboard / sideboard: {"Card Name": quantity, ...}
    """
    _ensure_tables()
    mb = json.dumps(mainboard or {})
    sb = json.dumps(sideboard or {})
    fmt = (format_name or "").lower()

    with get_connection() as conn:
        if deck_id is not None:
            conn.execute(
                """
                UPDATE saved_decks
                SET name=?, format=?, archetype=?, mainboard=?, sideboard=?, notes=?
                WHERE id=?
                """,
                (name, fmt, archetype, mb, sb, notes, deck_id),
            )
            return deck_id
        else:
            cur = conn.execute(
                """
                INSERT INTO saved_decks (name, format, archetype, mainboard, sideboard, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, fmt, archetype, mb, sb, notes, _now()),
            )
            return cur.lastrowid


def delete_deck(deck_id: int) -> None:
    """Delete a saved deck and all its SB plans (CASCADE)."""
    _ensure_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM saved_decks WHERE id=?", (deck_id,))


# ---------------------------------------------------------------------------
# Saved decks — read
# ---------------------------------------------------------------------------

def get_decks(format_name: str = None) -> list[dict]:
    """
    Return all saved decks, optionally filtered by format.
    mainboard and sideboard are returned as dicts (deserialized from JSON).
    """
    _ensure_tables()
    q = "SELECT * FROM saved_decks"
    params = []
    if format_name:
        q += " WHERE lower(format) = lower(?)"
        params.append(format_name)
    q += " ORDER BY created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_deserialize_deck(dict(r)) for r in rows]


def get_deck(deck_id: int) -> dict | None:
    """Return a single saved deck by id, or None if not found."""
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM saved_decks WHERE id=?", (deck_id,)
        ).fetchone()
    return _deserialize_deck(dict(row)) if row else None


def _deserialize_deck(row: dict) -> dict:
    """Parse JSON fields back to dicts."""
    try:
        row["mainboard"] = json.loads(row.get("mainboard") or "{}")
    except (json.JSONDecodeError, TypeError):
        row["mainboard"] = {}
    try:
        row["sideboard"] = json.loads(row.get("sideboard") or "{}")
    except (json.JSONDecodeError, TypeError):
        row["sideboard"] = {}
    return row


# ---------------------------------------------------------------------------
# Sideboard plans — write
# ---------------------------------------------------------------------------

def save_sb_plan(deck_id: int, opponent_archetype: str,
                 play_in: list = None, play_out: list = None,
                 draw_in: list = None, draw_out: list = None,
                 notes: str = "", difficulty: str = "Medium") -> int:
    """
    Upsert a sideboard plan for a (deck, opponent) pair.
    play_in/out and draw_in/out are lists of card name strings.
    Returns the row id.
    """
    _ensure_tables()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_sb_plans
                (deck_id, opponent_archetype, play_in, play_out,
                 draw_in, draw_out, notes, difficulty, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(deck_id, opponent_archetype) DO UPDATE SET
                play_in    = excluded.play_in,
                play_out   = excluded.play_out,
                draw_in    = excluded.draw_in,
                draw_out   = excluded.draw_out,
                notes      = excluded.notes,
                difficulty = excluded.difficulty,
                updated_at = excluded.updated_at
            """,
            (
                deck_id,
                opponent_archetype,
                json.dumps(play_in  or []),
                json.dumps(play_out or []),
                json.dumps(draw_in  or []),
                json.dumps(draw_out or []),
                notes,
                difficulty,
                _now(),
            ),
        )
        return cur.lastrowid


def delete_sb_plan(deck_id: int, opponent_archetype: str) -> None:
    """Remove a single SB plan for a (deck, opponent) pair."""
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM saved_sb_plans WHERE deck_id=? AND opponent_archetype=?",
            (deck_id, opponent_archetype),
        )


# ---------------------------------------------------------------------------
# Sideboard plans — read
# ---------------------------------------------------------------------------

def get_sb_plans(deck_id: int) -> list[dict]:
    """
    Return all SB plans for a saved deck.
    play_in/out and draw_in/out are returned as lists.
    """
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_sb_plans WHERE deck_id=? ORDER BY opponent_archetype",
            (deck_id,),
        ).fetchall()
    return [_deserialize_plan(dict(r)) for r in rows]


def get_sb_plan(deck_id: int, opponent_archetype: str) -> dict | None:
    """Return a single SB plan for a (deck, opponent) pair, or None."""
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM saved_sb_plans WHERE deck_id=? AND opponent_archetype=?",
            (deck_id, opponent_archetype),
        ).fetchone()
    return _deserialize_plan(dict(row)) if row else None


def _deserialize_plan(row: dict) -> dict:
    """Parse JSON list fields back to Python lists."""
    for field in ("play_in", "play_out", "draw_in", "draw_out"):
        try:
            row[field] = json.loads(row.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            row[field] = []
    return row
