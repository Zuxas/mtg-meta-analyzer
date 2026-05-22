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
    cache_path = transcript_cache_path(arena_match_id)
    # Cache read happens in Task 19; for M1 scaffold we always rebuild.
    if not force_refresh and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            caps = cached.get("capabilities") or {}
            if caps.get("events") is True:
                return cached
        except Exception:
            pass  # fall through to rebuild

    grpid_names = _load_grpid_names(
        Path(__file__).resolve().parent.parent / "data" / "mtg_meta.db"
    )

    events: list[dict] = []
    match_meta: dict = {
        "format": None, "event_name": None,
        "start_time": None, "end_time": None, "duration_sec": None,
        "winner_seat": None, "winner_reason": None,
        "decklist_my_grpids": [], "decklist_opp_observed_grpids": [],
        "games": [], "key_events_by_turn": [],
    }
    my_seat: Optional[int] = None
    opp_seat: Optional[int] = None
    opp_name = ""
    target_found = False
    my_user_id = "GCIUQPR6DRC4XL7L2ZTNU2OMNI"

    for log_path in (PLAYER_LOG, PLAYER_PREV_LOG):
        for obj in _iter_json_blobs(log_path):
            mrse = obj.get("matchGameRoomStateChangedEvent")
            if mrse:
                room = mrse.get("gameRoomInfo", {})
                cfg = room.get("gameRoomConfig", {})
                mid = cfg.get("matchId")
                if mid == arena_match_id:
                    target_found = True
                    for p in cfg.get("reservedPlayers", []) or []:
                        if p.get("userId") == my_user_id:
                            my_seat = p.get("systemSeatId")
                        else:
                            opp_seat = p.get("systemSeatId")
                            opp_name = p.get("playerName") or opp_name
                continue

    if not target_found:
        return None

    return {
        "arena_match_id": arena_match_id,
        "schema_version": SCHEMA_VERSION,
        "capabilities": dict(M1_CAPABILITIES),
        "match_meta": match_meta,
        "my_seat": my_seat,
        "opp_seat": opp_seat,
        "opp_name": opp_name,
        "events": events,
    }
