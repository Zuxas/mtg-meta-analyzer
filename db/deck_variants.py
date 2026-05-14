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
