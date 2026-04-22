"""
matchup_hypotheses
    Personal matchup predictions — 'I think Amulet Titan vs Boros Energy
    is 55% for my side'. Later we compare this prediction against sim
    win rate, scraped real-match WR, and personal match log to see
    which of your intuitions were right.

Schema:
    id           — PK
    a_deck       — your side (normalized archetype name, free-form)
    b_deck       — opponent side
    format       — 'modern' / 'standard' / etc.
    prediction   — INT 0-100 (your predicted A-side WR)
    confidence   — 'low' / 'medium' / 'high' (freeform)
    notes        — freeform rationale
    created_at   — ISO timestamp
"""
from db.database import get_connection
from db.helpers import ensure_table as _do_ensure, utc_now as _now


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS matchup_hypotheses (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        a_deck      TEXT    NOT NULL,
        b_deck      TEXT    NOT NULL,
        format      TEXT    NOT NULL DEFAULT 'modern',
        prediction  INTEGER NOT NULL DEFAULT 50,
        confidence  TEXT    NOT NULL DEFAULT 'medium',
        notes       TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_hypotheses_format ON matchup_hypotheses(format);
    CREATE INDEX IF NOT EXISTS idx_hypotheses_a ON matchup_hypotheses(a_deck);
"""


def _ensure():
    _do_ensure(_CREATE_SQL)


def save_hypothesis(a_deck: str, b_deck: str, format_name: str,
                    prediction: int, confidence: str = "medium",
                    notes: str = "", hypothesis_id: int = None) -> int:
    _ensure()
    with get_connection() as conn:
        if hypothesis_id is not None:
            conn.execute("""
                UPDATE matchup_hypotheses SET a_deck=?, b_deck=?, format=?,
                    prediction=?, confidence=?, notes=?
                WHERE id=?
            """, (a_deck, b_deck, format_name, prediction, confidence, notes,
                  hypothesis_id))
            return hypothesis_id
        cur = conn.execute("""
            INSERT INTO matchup_hypotheses
                (a_deck, b_deck, format, prediction, confidence, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (a_deck, b_deck, format_name, prediction, confidence, notes, _now()))
        return cur.lastrowid


def delete_hypothesis(hypothesis_id: int):
    _ensure()
    with get_connection() as conn:
        conn.execute("DELETE FROM matchup_hypotheses WHERE id=?", (hypothesis_id,))


def get_hypotheses(format_name: str = None) -> list[dict]:
    """Return all hypotheses, newest first."""
    _ensure()
    q = "SELECT * FROM matchup_hypotheses"
    params = []
    if format_name:
        q += " WHERE lower(format) = lower(?)"
        params.append(format_name)
    q += " ORDER BY created_at DESC, id DESC"
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]
