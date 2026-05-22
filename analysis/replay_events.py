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
from collections import Counter
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

_ZONE_TYPE_TO_NAME = {
    "ZoneType_Hand": "hand",
    "ZoneType_Library": "library",
    "ZoneType_Battlefield": "battlefield",
    "ZoneType_Graveyard": "graveyard",
    "ZoneType_Exile": "exile",
    "ZoneType_Stack": "stack",
    "ZoneType_Command": "command",
    "ZoneType_Pending": "pending",
}

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
    instance_to_grpid: dict[int, int] = {}
    instance_to_owner: dict[int, int] = {}
    instance_to_zone: dict[int, str] = {}
    pending_zone_diffs: list[dict] = []
    current_stack: list[dict] = []
    seen_annotations: set[int] = set()
    game_over_emitted: set[int] = set()
    prev_life: dict[int, int] = {}
    prev_mana: dict[int, str] = {}
    current_life_after: Optional[dict] = None
    current_mana_pool_after: Optional[dict] = None

    def _emit(kind: str, **payload):
        nonlocal seq, pending_zone_diffs
        if kind not in EVENT_KINDS:
            payload.setdefault("details", {})["original_kind"] = kind
            kind = "raw"
        diffs_for_this_event = payload.pop("board_diff", None)
        if diffs_for_this_event is None:
            diffs_for_this_event = pending_zone_diffs
            pending_zone_diffs = []
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
            "life_after": payload.pop("life_after", dict(current_life_after) if current_life_after else None),
            "mana_pool_after": payload.pop("mana_pool_after", dict(current_mana_pool_after) if current_mana_pool_after else None),
            "stack_after": payload.pop("stack_after", list(current_stack)),
            "board_diff": diffs_for_this_event,
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
                    if cfg.get("eventId") and not match_meta["event_name"]:
                        match_meta["event_name"] = cfg["eventId"]
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
                    stage = gi.get("stage")
                    if stage == "GameStage_GameOver" and current_game not in game_over_emitted:
                        game_over_emitted.add(current_game)
                        results = gi.get("results") or []
                        if results:
                            winning_team = results[0].get("winningTeamId")
                            reason = results[0].get("reason", "")
                            reason_clean = reason.replace("ResultReason_", "") if reason else None
                            if match_meta["winner_seat"] is None:
                                match_meta["winner_seat"] = winning_team
                                match_meta["winner_reason"] = reason_clean
                        _emit("game_end", game_state_id=gsm.get("gameStateId"),
                              details={"winning_seat": match_meta["winner_seat"],
                                       "reason": match_meta["winner_reason"]})
                    ti = gsm.get("turnInfo", {})
                    tn = ti.get("turnNumber")
                    if tn:
                        current_turn = tn
                    active = ti.get("activePlayer")
                    if active:
                        current_active_seat = active
                    priority = ti.get("priorityPlayer")
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

                    # Track instance->grpid + instance->owner from gameObjects
                    for go in gsm.get("gameObjects", []) or []:
                        inst = go.get("instanceId")
                        grp = go.get("grpId")
                        owner = go.get("ownerSeatId") or go.get("controllerSeatId")
                        if isinstance(inst, int) and isinstance(grp, int) and grp > 0:
                            instance_to_grpid[inst] = grp
                        if isinstance(inst, int) and isinstance(owner, int):
                            instance_to_owner[inst] = owner

                    # Update stack snapshot from zones[]
                    for zone in gsm.get("zones", []) or []:
                        if zone.get("type") == "ZoneType_Stack":
                            new_stack = []
                            for iid in zone.get("objectInstanceIds", []) or []:
                                grp = instance_to_grpid.get(iid)
                                owner = instance_to_owner.get(iid)
                                new_stack.append({
                                    "name": grpid_names.get(grp, f"grpId:{grp}") if grp else f"instance#{iid}",
                                    "controller": ("you" if owner == my_seat else "opp"),
                                    "targets": [],  # populated by later target_chosen events
                                })
                            current_stack = new_stack

                    # Track life + mana from players[]; emit life_change on delta.
                    for p in gsm.get("players", []) or []:
                        seat = p.get("systemSeatNumber")
                        lt = p.get("lifeTotal")
                        mp = p.get("manaPool", "") or ""
                        if seat is None:
                            continue
                        if lt is not None:
                            last = prev_life.get(seat)
                            prev_life[seat] = lt  # update FIRST
                            current_life_after = {
                                "you": prev_life.get(my_seat),
                                "opp": prev_life.get(opp_seat),
                            }
                            if last is not None and lt != last:
                                _emit("life_change", game_state_id=gs_id,
                                      details={"seat": seat, "delta": lt - last,
                                               "from": last, "to": lt})
                        if mp != prev_mana.get(seat, ""):
                            prev_mana[seat] = mp
                            current_mana_pool_after = {
                                "you": prev_mana.get(my_seat, ""),
                                "opp": prev_mana.get(opp_seat, ""),
                            }

                    # Build current zone snapshot from zones[]
                    current_zones: dict[int, str] = {}
                    for zone in gsm.get("zones", []) or []:
                        zname = _ZONE_TYPE_TO_NAME.get(zone.get("type"))
                        if not zname:
                            continue
                        for iid in zone.get("objectInstanceIds", []) or []:
                            current_zones[iid] = zname

                    # Compute diffs against the running instance_to_zone map
                    zone_diffs: list[dict] = []
                    for iid, new_zone in current_zones.items():
                        old_zone = instance_to_zone.get(iid)
                        if old_zone != new_zone:
                            grp = instance_to_grpid.get(iid)
                            owner = instance_to_owner.get(iid)
                            zone_diffs.append({
                                "instance_id": iid,
                                "card": grpid_names.get(grp) if grp else None,
                                "grpid": grp,
                                "from": old_zone,
                                "to": new_zone,
                                "controller": "you" if owner == my_seat else "opp" if owner == opp_seat else None,
                            })
                            instance_to_zone[iid] = new_zone
                    # Detect instances that disappeared (no longer in any zone)
                    for iid in list(instance_to_zone.keys()):
                        if iid not in current_zones:
                            old_zone = instance_to_zone.pop(iid)
                            grp = instance_to_grpid.get(iid)
                            owner = instance_to_owner.get(iid)
                            zone_diffs.append({
                                "instance_id": iid,
                                "card": grpid_names.get(grp) if grp else None,
                                "grpid": grp,
                                "from": old_zone,
                                "to": None,
                                "controller": "you" if owner == my_seat else "opp" if owner == opp_seat else None,
                            })

                    pending_zone_diffs = zone_diffs

                    for ann in gsm.get("annotations", []) or []:
                        ann_id = ann.get("id")
                        if ann_id is None or ann_id in seen_annotations:
                            continue
                        seen_annotations.add(ann_id)
                        types = ann.get("type") or []
                        if not types:
                            continue
                        t = types[0]
                        affected = ann.get("affectedIds") or []
                        details_list = ann.get("details") or []
                        details_map = {d["key"]: d for d in details_list}

                        def _ds(key):
                            d = details_map.get(key)
                            if not d:
                                return None
                            v = d.get("valueString")
                            if v:
                                return v[0] if isinstance(v, list) else v
                            v = d.get("valueInt32")
                            if v:
                                return v[0] if isinstance(v, list) else v
                            return None

                        if t == "AnnotationType_ZoneTransfer":
                            cat = _ds("category") or ""
                            for iid in affected:
                                grp = instance_to_grpid.get(iid)
                                nm = grpid_names.get(grp) if grp else None
                                owner = instance_to_owner.get(iid)
                                kind_map = {
                                    "CastSpell": "cast_spell",
                                    "Resolve": "resolve",
                                    "Countered": "counter_spell",
                                    "PlayLand": "play_land",
                                    "Draw": "draw_card",
                                    "Discard": "zone_change",
                                    "Destroy": "zone_change",
                                    "Mill": "zone_change",
                                    "Exile": "zone_change",
                                    "Sacrifice": "zone_change",
                                    "Return": "zone_change",
                                    "Put": "zone_change",
                                }
                                kind = kind_map.get(cat)
                                if kind:
                                    _emit(kind, game_state_id=gs_id,
                                          actor_seat=owner,
                                          card_name=nm, card_grpid=grp,
                                          details={"category": cat})
                        elif t == "AnnotationType_PlayerSubmittedTargets":
                            target_objs = []
                            for tiid in affected:
                                grp = instance_to_grpid.get(tiid)
                                target_objs.append({
                                    "name": grpid_names.get(grp, f"instance#{tiid}") if grp else f"instance#{tiid}",
                                    "grpid": grp,
                                    "kind": "spell_or_permanent",
                                })
                            _emit("target_chosen", game_state_id=gs_id, targets=target_objs)
                        elif t == "AnnotationType_DamageDealt":
                            amount = _ds("damage")
                            _emit("damage_dealt", game_state_id=gs_id,
                                  details={"damage": amount, "affected_ids": list(affected)})
                        elif t == "AnnotationType_Scry":
                            top_d = details_map.get("topIds", {})
                            bot_d = details_map.get("bottomIds", {})
                            top_iids = top_d.get("valueInt32") or [] if top_d else []
                            bot_iids = bot_d.get("valueInt32") or [] if bot_d else []
                            revealed = []
                            for iid in top_iids:
                                grp = instance_to_grpid.get(iid)
                                revealed.append({
                                    "grpid": grp,
                                    "name": grpid_names.get(grp, f"instance#{iid}") if grp else f"instance#{iid}",
                                    "source": "scry_top",
                                    "seat": my_seat,
                                    "library_position": "top",
                                })
                            for iid in bot_iids:
                                grp = instance_to_grpid.get(iid)
                                revealed.append({
                                    "grpid": grp,
                                    "name": grpid_names.get(grp, f"instance#{iid}") if grp else f"instance#{iid}",
                                    "source": "scry_top",  # source is still scry; position differs
                                    "seat": my_seat,
                                    "library_position": "bottom",
                                })
                            _emit("scry", game_state_id=gs_id, revealed_cards=revealed,
                                  details={"top_count": len(top_iids), "bottom_count": len(bot_iids)})
                        elif t == "AnnotationType_Surveil":
                            top_d = details_map.get("topIds", {})
                            top_iids = (top_d.get("valueInt32") or []) if top_d else []
                            top_set = set(top_iids)
                            revealed = []
                            for iid in affected:
                                grp = instance_to_grpid.get(iid)
                                kept_on_top = iid in top_set
                                revealed.append({
                                    "grpid": grp,
                                    "name": grpid_names.get(grp, f"instance#{iid}") if grp else f"instance#{iid}",
                                    "source": "surveil_top" if kept_on_top else "surveil_gy",
                                    "seat": my_seat,
                                    "library_position": "top" if kept_on_top else None,
                                })
                            _emit("surveil", game_state_id=gs_id, revealed_cards=revealed)
                        elif t == "AnnotationType_Shuffle":
                            cause = _ds("cause") or "unknown"
                            _emit("shuffle", game_state_id=gs_id, shuffle_cause=cause)

                    # If zone diffs weren't consumed by an annotation-driven
                    # event, emit a synthetic zone_change event holding them.
                    if pending_zone_diffs:
                        _emit("zone_change", game_state_id=gs_id)

                    if priority is not None and priority != current_priority_seat:
                        current_priority_seat = priority
                        _emit("priority_grant", game_state_id=gs_id)

            # ── Client-to-server messages (mulligan, attackers, blockers) ─
            cmsm = obj.get("clientToMatchServiceMessageType")
            if cmsm == "ClientToMatchServiceMessageType_ClientToGREMessage":
                payload = obj.get("payload", {}) or {}
                ptype = payload.get("type", "")
                if ptype == "ClientMessageType_MulliganResp":
                    decision = (payload.get("mulliganResp", {}) or {}).get("decision", "")
                    if decision == "MulliganOption_Mulligan":
                        _emit("mulligan_decision",
                              details={"decision": "mulligan", "actor": "you"})
                    elif decision == "MulliganOption_AcceptHand":
                        _emit("keep_hand", details={"actor": "you"})
                elif ptype == "ClientMessageType_SubmitAttackersReq":
                    atks = (payload.get("submitAttackersReq", {}) or {}).get(
                        "attackers", []) or []
                    attackers = []
                    for a in atks:
                        iid = a.get("attackerId")
                        grp = instance_to_grpid.get(iid)
                        attackers.append({
                            "instance_id": iid,
                            "grpid": grp,
                            "name": grpid_names.get(grp, f"instance#{iid}") if grp else f"instance#{iid}",
                        })
                    if attackers:
                        _emit("attack_declared",
                              details={"attackers": attackers, "actor": "you"},
                              actor_seat=my_seat)
                elif ptype == "ClientMessageType_SubmitBlockersReq":
                    bmap = (payload.get("submitBlockersReq", {}) or {}).get(
                        "blockerToAttackerMap", []) or []
                    blocks = []
                    for b in bmap:
                        biid = b.get("blockerId")
                        aiid = b.get("attackerId")
                        bg = instance_to_grpid.get(biid)
                        ag = instance_to_grpid.get(aiid)
                        blocks.append({
                            "blocker_id": biid, "blocker": grpid_names.get(bg, "?"),
                            "attacker_id": aiid, "attacker": grpid_names.get(ag, "?"),
                        })
                    if blocks:
                        _emit("block_declared",
                              details={"blocks": blocks, "actor": "you"},
                              actor_seat=my_seat)
                elif ptype == "ClientMessageType_SubmitDeckResp":
                    deck = (payload.get("submitDeckResp", {}) or {}).get("deck", {}) or {}
                    cards = deck.get("deckCards", []) or []
                    # First SubmitDeckResp is G1; subsequent ones are G2/G3
                    gnum = len(match_meta["games"]) + 1
                    prev_cards = match_meta["games"][-1]["decklist_my_grpids"] if match_meta["games"] else []
                    # Compute multiset diff vs previous game
                    prev_count = Counter(prev_cards)
                    cur_count = Counter(cards)
                    sb_in = []
                    sb_out = []
                    for grp, n_cur in cur_count.items():
                        n_prev = prev_count.get(grp, 0)
                        if n_cur > n_prev:
                            sb_in.extend([grp] * (n_cur - n_prev))
                    for grp, n_prev in prev_count.items():
                        n_cur = cur_count.get(grp, 0)
                        if n_prev > n_cur:
                            sb_out.extend([grp] * (n_prev - n_cur))
                    match_meta["games"].append({
                        "game_num": gnum,
                        "decklist_my_grpids": list(cards),
                        "sideboard_in": sb_in,
                        "sideboard_out": sb_out,
                    })
                    if gnum == 1:
                        match_meta["decklist_my_grpids"] = list(cards)

    if not target_found:
        return None

    # Post-pass: extract key events
    def _extract_key_events(events_list: list[dict]) -> list[dict]:
        keys = []
        mull_count = 0
        first_spell_seen = False
        first_combat_seen = False
        low_life_marked = False
        for ev in events_list:
            if ev["kind"] == "mulligan_decision":
                mull_count += 1
            elif ev["kind"] == "keep_hand":
                if mull_count > 0:
                    keys.append({
                        "turn": ev["turn_num"],
                        "kind": f"mulligan_to_{7 - mull_count}",
                        "actor": "you",
                        "seq": ev["seq"],
                    })
            elif ev["kind"] == "cast_spell" and not first_spell_seen:
                first_spell_seen = True
                keys.append({
                    "turn": ev["turn_num"],
                    "kind": "first_spell",
                    "actor": "you" if ev.get("actor_seat") == my_seat else "opp",
                    "seq": ev["seq"],
                    "card": ev.get("card_name"),
                })
            elif ev["kind"] == "attack_declared" and not first_combat_seen:
                first_combat_seen = True
                keys.append({
                    "turn": ev["turn_num"],
                    "kind": "first_combat",
                    "seq": ev["seq"],
                })
            elif ev["kind"] == "life_change":
                life_after = ev.get("life_after") or {}
                my_life = life_after.get("you")
                if my_life is not None and my_life <= 5 and not low_life_marked:
                    low_life_marked = True
                    keys.append({
                        "turn": ev["turn_num"],
                        "kind": "low_life_threshold",
                        "actor": "you",
                        "seq": ev["seq"],
                        "detail": f"{my_life} life",
                    })
            elif ev["kind"] == "game_end":
                reason = (ev.get("details") or {}).get("reason", "") or ""
                if reason == "Concede":
                    winning = (ev.get("details") or {}).get("winning_seat")
                    actor = "you" if winning != my_seat else "opp"
                    keys.append({
                        "turn": ev["turn_num"],
                        "kind": "concede",
                        "actor": actor,
                        "seq": ev["seq"],
                    })
                elif reason == "DamageDealt":
                    keys.append({
                        "turn": ev["turn_num"],
                        "kind": "lethal_attack",
                        "seq": ev["seq"],
                    })
        return keys

    match_meta["key_events_by_turn"] = _extract_key_events(events)

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
