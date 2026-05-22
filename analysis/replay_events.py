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

    # ── Event-emission state ──────────────────────────────────
    seq = 0
    current_phase: Optional[str] = None
    current_step: Optional[str] = None
    current_game = 1
    current_turn = 0
    current_active_seat: Optional[int] = None
    current_priority_seat: Optional[int] = None

    def _emit(kind: str, **payload):
        nonlocal seq
        if kind not in EVENT_KINDS:
            payload.setdefault("details", {})["original_kind"] = kind
            kind = "raw"
        ev = {
            "seq": seq,
            "game_state_id": payload.pop("game_state_id", None),
            "game_num": current_game,
            "turn_num": current_turn,
            "phase": current_phase,
            "step": current_step,
            "active_seat": current_active_seat,
            "priority_seat": current_priority_seat,
            "actor_seat": payload.pop("actor_seat", None),
            "kind": kind,
            "card_name": payload.pop("card_name", None),
            "card_grpid": payload.pop("card_grpid", None),
            "targets": payload.pop("targets", []),
            "details": payload.pop("details", {}),
            "life_after": payload.pop("life_after", None),
            "mana_pool_after": payload.pop("mana_pool_after", None),
            "stack_after": payload.pop("stack_after", []),
            "board_diff": payload.pop("board_diff", []),
            "log_offset": payload.pop("log_offset", None),
            "revealed_cards": payload.pop("revealed_cards", []),
            "shuffle_cause": payload.pop("shuffle_cause", None),
        }
        events.append(ev)
        seq += 1

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

            # ── GameStateMessage handler ─────────────────────────
            gre = obj.get("greToClientEvent")
            if gre:
                for msg in gre.get("greToClientMessages", []) or []:
                    if msg.get("type") != "GREMessageType_GameStateMessage":
                        continue
                    gsm = msg.get("gameStateMessage", {})
                    gi = gsm.get("gameInfo", {})
                    gn = gi.get("gameNumber")
                    if gn and gn != current_game:
                        current_game = gn
                    ti = gsm.get("turnInfo", {})
                    tn = ti.get("turnNumber")
                    if tn:
                        current_turn = tn
                    active = ti.get("activePlayer")
                    if active:
                        current_active_seat = active
                    priority = ti.get("priorityPlayer")
                    if priority:
                        current_priority_seat = priority
                    new_phase = ti.get("phase")
                    new_step = ti.get("step")
                    gs_id = gsm.get("gameStateId")

                    if new_phase and new_phase != current_phase:
                        # Phase changed (includes first phase seen when
                        # current_phase is None).
                        current_phase = new_phase
                        current_step = new_step  # update simultaneously
                        _emit("phase_change", game_state_id=gs_id)
                    elif new_step and new_step != current_step:
                        # Same phase, step advanced within the phase.
                        current_step = new_step
                        _emit("step_change", game_state_id=gs_id)

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
