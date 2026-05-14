"""Schema + helpers for the deck_variants table.

A variant = a frozen (mainboard, sideboard) snapshot, hashed at the moment a
match is logged. This table is the durable record of what cards a deck looked
like when a match was played; saved_decks gets edited in place, so the hash
captured at insert time is the only thing that survives later deck edits.

Hash: 64-bit truncated sha256 of canonical-sorted JSON of both boards.
Collision probability negligible at one-player scale (lifetime <1000 variants).
"""
from __future__ import annotations

import hashlib
import json

from db.database import get_connection
from db.helpers import ensure_table as _do_ensure, utc_now as _now


def compute_variant_hash(mainboard: dict[str, int],
                         sideboard: dict[str, int]) -> str:
    """Return a 16-hex-char stable hash for a (mainboard, sideboard) pair.

    Input dicts may be in any order; hashing is over a canonical sort.
    Quantity changes count as variant changes."""
    canon = json.dumps({
        "mb": sorted(mainboard.items()),
        "sb": sorted(sideboard.items()),
    }, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def variant_diff(mb_prev: dict[str, int], sb_prev: dict[str, int],
                 mb_curr: dict[str, int], sb_curr: dict[str, int]) -> dict:
    """Return the (added, removed) pairs that turn prev into curr.

    Quantity changes render as paired remove (old qty) + add (new qty)
    so the UI can show 'Lightning Bolt 3 -> 4' as one row pair.
    Output lists are sorted by card name for stable rendering."""
    return {
        "mainboard": _diff_board(mb_prev, mb_curr),
        "sideboard": _diff_board(sb_prev, sb_curr),
    }


def _diff_board(prev: dict[str, int], curr: dict[str, int]) -> dict:
    added: list[tuple[str, int]] = []
    removed: list[tuple[str, int]] = []
    all_names = set(prev) | set(curr)
    for name in sorted(all_names):
        p = prev.get(name, 0)
        c = curr.get(name, 0)
        if p == c:
            continue
        if p > 0:
            removed.append((name, p))
        if c > 0:
            added.append((name, c))
    return {"added": added, "removed": removed}


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS deck_variants (
        variant_hash    TEXT PRIMARY KEY,
        deck_id         INTEGER NOT NULL REFERENCES saved_decks(id) ON DELETE CASCADE,
        mainboard_json  TEXT    NOT NULL,
        sideboard_json  TEXT    NOT NULL,
        first_seen      TEXT    NOT NULL,
        last_seen       TEXT    NOT NULL,
        match_count     INTEGER NOT NULL DEFAULT 0,
        win_count       INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_deck_variants_deck ON deck_variants(deck_id);
"""


def _ensure_table():
    _do_ensure(_CREATE_SQL)


def get_variants_for_deck(deck_id: int) -> list[dict]:
    """Return all variants for a deck, ordered by first_seen.

    Each row includes an `is_approximate` boolean: True iff every contributing
    match_log row was auto-backfilled (backfill_status='auto'). UI uses this
    to label the variant as approximate (e.g., '~v3') since the variant_hash
    was computed from the saved_decks state at backfill time, not at match time.
    """
    import sqlite3
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM deck_variants WHERE deck_id=? ORDER BY first_seen",
            (deck_id,),
        ).fetchall()
        variants = [dict(r) for r in rows]
        # Per-variant approximation flag
        for v in variants:
            counts = conn.execute(
                "SELECT backfill_status, COUNT(*) as n FROM match_log "
                "WHERE my_variant_hash=? GROUP BY backfill_status",
                (v["variant_hash"],),
            ).fetchall()
            total = sum(c["n"] for c in counts)
            auto = next((c["n"] for c in counts if c["backfill_status"] == "auto"), 0)
            v["is_approximate"] = (total > 0 and auto == total)
        return variants


def upsert_variant(deck_id: int, mainboard: dict[str, int],
                   sideboard: dict[str, int], won: bool) -> str:
    """Insert or increment a variant row. Returns the variant_hash."""
    _ensure_table()
    variant_hash = compute_variant_hash(mainboard, sideboard)
    mb_json = json.dumps(mainboard, separators=(",", ":"), ensure_ascii=False)
    sb_json = json.dumps(sideboard, separators=(",", ":"), ensure_ascii=False)
    now = _now()
    win_delta = 1 if won else 0
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO deck_variants
                (variant_hash, deck_id, mainboard_json, sideboard_json,
                 first_seen, last_seen, match_count, win_count)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(variant_hash) DO UPDATE SET
                last_seen   = excluded.last_seen,
                match_count = match_count + 1,
                win_count   = win_count + excluded.win_count
            """,
            (variant_hash, deck_id, mb_json, sb_json, now, now, win_delta),
        )
    return variant_hash
