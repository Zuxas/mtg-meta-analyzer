"""Event-stream extractor for MTGA replays.

Walks Player.log / Player-prev.log and emits a flat list of structured
events covering every phase, step, priority pass, stack interaction, zone
change, and annotation. Cached alongside the existing transcript in
data/match_replays/<arena_match_id>.json under new top-level keys.

See docs/superpowers/specs/2026-05-22-replay-viewer-design.md for the
data contract and Source-of-Truth Hierarchy.

Public API:
    build_event_stream(arena_match_id, force_refresh=False) -> dict | None
        Returns {
            "arena_match_id": str,
            "schema_version": 1,
            "capabilities": {...},
            "match_meta": {...},
            "events": [...],
        }
        or None if the match isn't in Player.log / Player-prev.log.

This module is the ONLY place that reads Player.log for replay purposes.
The Source-of-Truth Hierarchy forbids any other module from re-parsing
logs directly.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional, Iterable, Iterator

from analysis.replay_transcript import (
    _iter_json_blobs,
    _load_grpid_names,
    CACHE_DIR,
    PLAYER_LOG,
    PLAYER_PREV_LOG,
    transcript_cache_path,
)

SCHEMA_VERSION = 1

# Closed enum of normalized event kinds. Any annotation we don't map
# explicitly falls through to kind="raw" with the full annotation dict
# in details.raw -- we never silently drop events.
EVENT_KINDS = frozenset({
    "phase_change", "step_change", "priority_grant", "priority_pass",
    "mulligan_decision", "keep_hand", "draw_card", "play_land",
    "cast_spell", "activate_ability", "trigger_ability", "target_chosen",
    "mana_paid", "mana_added", "resolve", "counter_spell",
    "counter_ability", "damage_dealt", "life_change", "zone_change",
    "token_created", "counter_added", "counter_removed", "scry",
    "surveil", "shuffle", "reveal", "cascade", "library_look",
    "attack_declared", "block_declared", "combat_damage_assigned",
    "game_end", "raw",
})

# Capabilities reported in the cache header. Update both this constant
# and the spec's capabilities block when adding a new capability.
M1_CAPABILITIES = {
    "turns": True,
    "events": True,
    "board_diff": True,
    "public_info": True,
    "per_game_decklists": True,
    "odds_ready": False,
    "stack_history": True,
    "log_offsets": True,
}


def build_event_stream(arena_match_id: str,
                       force_refresh: bool = False) -> Optional[dict]:
    """Build (or load cached) event stream for one match.

    Returns dict with shape documented at module top, or None if the
    match isn't found in Player.log / Player-prev.log.
    """
    raise NotImplementedError("scaffold; tests drive the implementation")
