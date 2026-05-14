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
from db.helpers import ensure_table as _do_ensure


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
