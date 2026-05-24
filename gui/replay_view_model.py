# -*- coding: utf-8 -*-
"""Qt-free display logic for the full-depth replay viewer.

Pure functions that transform the M1 event stream (analysis.replay_events
build_event_stream output) into structures the QMainWindow renders:
timeline tree, event-table rows, kind filtering, navigation, jump-to
targets, and right-pane detail rows.

NO PyQt6 imports here -- this module is unit-tested headless. The Qt widgets
live in gui/widgets/replay_viewer_window.py and import from here.

Source-of-Truth Hierarchy: this is Layer-5 presentation logic. It reads the
events[] data contract and never re-parses Player.log.
"""
from __future__ import annotations

from typing import Optional

_PHASE_LABELS = {
    "Phase_Beginning": "Beginning",
    "Phase_Main1": "Precombat Main",
    "Phase_Combat": "Combat",
    "Phase_Main2": "Postcombat Main",
    "Phase_Ending": "Ending",
}
_STEP_LABELS = {
    "Step_Untap": "Untap",
    "Step_Upkeep": "Upkeep",
    "Step_Draw": "Draw",
    "Step_BeginCombat": "Begin Combat",
    "Step_DeclareAttackers": "Declare Attackers",
    "Step_DeclareBlockers": "Declare Blockers",
    "Step_FirstStrikeDamage": "First Strike Damage",
    "Step_CombatDamage": "Combat Damage",
    "Step_EndCombat": "End Combat",
    "Step_End": "End Step",
    "Step_Cleanup": "Cleanup",
}
_KIND_LABELS = {
    "phase_change": "Phase", "step_change": "Step",
    "priority_grant": "Priority", "priority_pass": "Priority Pass",
    "mulligan_decision": "Mulligan", "keep_hand": "Keep",
    "draw_card": "Draw", "play_land": "Land", "cast_spell": "Cast",
    "activate_ability": "Activate", "trigger_ability": "Trigger",
    "target_chosen": "Targets", "mana_paid": "Mana Paid",
    "mana_added": "Mana Added", "resolve": "Resolve",
    "counter_spell": "Counter", "counter_ability": "Counter Ability",
    "damage_dealt": "Damage", "life_change": "Life", "zone_change": "Zone",
    "token_created": "Token", "counter_added": "Counter+",
    "counter_removed": "Counter-", "scry": "Scry", "surveil": "Surveil",
    "shuffle": "Shuffle", "reveal": "Reveal", "cascade": "Cascade",
    "library_look": "Look", "attack_declared": "Attack",
    "block_declared": "Block", "combat_damage_assigned": "Combat Damage",
    "game_end": "Game End", "raw": "Raw",
}


def _strip_prefix(value: str) -> str:
    """'Phase_Main1' -> 'Main1', 'Step_Foo' -> 'Foo'."""
    return value.split("_", 1)[1] if "_" in value else value


def phase_label(phase: Optional[str]) -> str:
    """Return a human-readable phase name.

    Known phases map to canonical labels; unknown Phase_* enums fall back to
    stripping the prefix. None returns an em-dash placeholder.
    """
    if not phase:
        return "—"
    return _PHASE_LABELS.get(phase) or _strip_prefix(phase)


def step_label(step: Optional[str]) -> Optional[str]:
    """Return a human-readable step name, or None if step is None."""
    if not step:
        return None
    return _STEP_LABELS.get(step) or _strip_prefix(step)


def kind_label(kind: str) -> str:
    """Return a human-readable event-kind label.

    Known kinds map to short canonical labels; unknown kinds are title-cased
    slug-to-words conversions.
    """
    if kind in _KIND_LABELS:
        return _KIND_LABELS[kind]
    return kind.replace("_", " ").title()


def player_label(event: dict, my_seat: Optional[int], opp_seat: Optional[int],
                 opp_name: str = "Opp") -> str:
    """Who acted. Prefer actor_seat, fall back to active_seat."""
    seat = event.get("actor_seat")
    if seat is None:
        seat = event.get("active_seat")
    if seat is None:
        return "—"
    if seat == my_seat:
        return "You"
    if seat == opp_seat:
        return opp_name or "Opp"
    return opp_name or "Opp"


def _targets_str(event: dict) -> str:
    names = [t.get("name") for t in (event.get("targets") or []) if t.get("name")]
    return ", ".join(names)


def event_summary(event: dict, *, opp_name: str = "Opp") -> str:
    """One human-readable line describing the event for the table / tree."""
    kind = event.get("kind", "raw")
    card = event.get("card_name")
    tgts = _targets_str(event)
    details = event.get("details") or {}

    if kind in ("cast_spell", "play_land", "activate_ability",
                "trigger_ability", "resolve", "counter_spell",
                "counter_ability", "draw_card", "zone_change",
                "token_created"):
        label = kind_label(kind)
        text = f"{label}: {card}" if card else label
        if tgts:
            text += f" → {tgts}"
        return text
    if kind == "target_chosen":
        return f"Targets → {tgts}" if tgts else "Targets chosen"
    if kind == "life_change":
        delta = details.get("delta")
        to = details.get("to")
        sign = f"{delta:+d}" if isinstance(delta, int) else "?"
        return f"Life {sign} → {to}"
    if kind == "damage_dealt":
        return f"Damage: {details.get('damage', '?')}"
    if kind in ("phase_change", "step_change"):
        ph = phase_label(event.get("phase"))
        st = step_label(event.get("step"))
        return f"{ph} — {st}" if st else ph
    if kind in ("scry", "surveil"):
        n = len(event.get("revealed_cards") or [])
        return f"{kind_label(kind)} ({n} seen)"
    if kind == "shuffle":
        return f"Shuffle ({event.get('shuffle_cause') or 'unknown'})"
    if kind in ("mulligan_decision", "keep_hand"):
        return kind_label(kind)
    if kind in ("attack_declared", "block_declared"):
        items = details.get("attackers") or details.get("blocks") or []
        names = [i.get("name") or i.get("blocker") for i in items]
        names = [n for n in names if n]
        return f"{kind_label(kind)}: {', '.join(names)}" if names else kind_label(kind)
    if kind == "game_end":
        return f"Game end ({details.get('reason') or '?'})"
    if kind in ("priority_grant", "priority_pass"):
        return kind_label(kind)
    # raw + anything unmapped
    return kind_label(kind)


def format_event_row(event: dict, my_seat: Optional[int], opp_seat: Optional[int],
                     opp_name: str = "Opp") -> dict:
    """The 4 display cells for one table row: # / Turn / Player / Event."""
    return {
        "seq": event.get("seq"),
        "turn": event.get("turn_num"),
        "player": player_label(event, my_seat, opp_seat, opp_name),
        "summary": event_summary(event, opp_name=opp_name),
        "kind": event.get("kind", "raw"),
    }


# Kind chips are grouped -- 34 individual chips would be unusable. Groups in
# DEFAULT_OFF_GROUPS start unchecked (priority passes + raw fallthrough are
# noise for most review). Every kind in analysis.replay_events.EVENT_KINDS
# must appear in exactly one group (asserted by a test).
KIND_GROUPS: dict[str, set] = {
    "Casts": {"cast_spell", "play_land", "activate_ability", "trigger_ability"},
    "Combat": {"attack_declared", "block_declared", "combat_damage_assigned",
               "damage_dealt"},
    "Stack": {"counter_spell", "counter_ability", "resolve", "target_chosen"},
    "Priority": {"priority_grant", "priority_pass"},
    "Reveals": {"scry", "surveil", "reveal", "cascade", "library_look", "shuffle"},
    "Zone/Life": {"zone_change", "draw_card", "life_change", "token_created",
                  "counter_added", "counter_removed", "mana_paid", "mana_added"},
    "Flow": {"phase_change", "step_change", "mulligan_decision", "keep_hand",
             "game_end"},
    "Raw": {"raw"},
}
DEFAULT_OFF_GROUPS = {"Priority", "Raw"}


def kinds_for_groups(active_groups) -> set:
    """Return the union of all individual kinds for the given group names."""
    out: set = set()
    for g in active_groups:
        out |= KIND_GROUPS.get(g, set())
    return out


def filter_events(events: list, allowed_kinds) -> list:
    """Return the seq of every event whose kind is allowed.

    allowed_kinds None => all events visible.
    """
    if allowed_kinds is None:
        return [e.get("seq") for e in events]
    return [e.get("seq") for e in events if e.get("kind") in allowed_kinds]


def nav_target(visible_seqs: list, current_seq, direction: str):
    """Next/prev/first/last seq within the currently-visible rows.

    visible_seqs is the model's row order (monotonic seq). Clamps at both
    ends. If current_seq isn't visible, next picks the first greater seq and
    prev the last lesser seq."""
    if not visible_seqs:
        return None
    ordered = sorted(visible_seqs)
    if direction == "first":
        return ordered[0]
    if direction == "last":
        return ordered[-1]
    if current_seq is None:
        return ordered[0] if direction == "next" else ordered[-1]
    if direction == "next":
        for s in ordered:
            if s > current_seq:
                return s
        return ordered[-1]
    if direction == "prev":
        for s in reversed(ordered):
            if s < current_seq:
                return s
        return ordered[0]
    return current_seq


def _turn_label(turn_num, active_seat, my_seat, opp_seat, opp_name) -> str:
    if active_seat == my_seat:
        who = "You"
    elif active_seat == opp_seat:
        who = opp_name or "Opp"
    else:
        who = "?"
    return f"Turn {turn_num} — {who}"


def _event_node(event: dict, opp_name: str) -> dict:
    return {
        "type": "event",
        "seq": event.get("seq"),
        "kind": event.get("kind"),
        "label": event_summary(event, opp_name=opp_name),
    }


def build_timeline_tree(events: list, my_seat, opp_seat, opp_name: str = "Opp") -> list:
    """Nested Game -> Turn -> Phase -> [Step] -> Event structure for the
    QTreeWidget. Step layer only appears when the phase has stepped events.
    Preserves first-seen order at every level."""
    games: list = []
    game_idx: dict = {}

    def _get_child(parent_children, key, factory):
        """Find-or-create a child node by an identity key, preserving order."""
        for node in parent_children:
            if node.get("_key") == key:
                return node
        node = factory()
        node["_key"] = key
        parent_children.append(node)
        return node

    for ev in events:
        gnum = ev.get("game_num")
        g = _get_child(games, ("g", gnum), lambda: {
            "type": "game", "game_num": gnum,
            "label": f"Game {gnum}", "children": []})
        tnum = ev.get("turn_num")
        t = _get_child(g["children"], ("t", tnum), lambda: {
            "type": "turn", "turn_num": tnum,
            "label": _turn_label(tnum, ev.get("active_seat"), my_seat,
                                 opp_seat, opp_name),
            "children": []})
        ph = ev.get("phase")
        p = _get_child(t["children"], ("p", ph), lambda: {
            "type": "phase", "phase": ph,
            "label": phase_label(ph), "children": [],
            "_events": []})
        p["_events"].append(ev)

    # Second pass: now that every phase knows its events, decide step grouping.
    for g in games:
        for t in g["children"]:
            for p in t["children"]:
                evs = p.pop("_events")
                has_step = any(e.get("step") for e in evs)
                if not has_step:
                    p["children"] = [_event_node(e, opp_name) for e in evs]
                    continue
                children: list = []
                step_idx: dict = {}
                for e in evs:
                    st = e.get("step")
                    if st is None:
                        children.append(_event_node(e, opp_name))
                        continue
                    if st not in step_idx:
                        node = {"type": "step", "step": st,
                                "label": step_label(st), "children": []}
                        step_idx[st] = node
                        children.append(node)
                    step_idx[st]["children"].append(_event_node(e, opp_name))
                p["children"] = children

    # Strip the internal _key bookkeeping before returning.
    def _clean(node):
        node.pop("_key", None)
        for c in node.get("children", []):
            _clean(c)
    for g in games:
        _clean(g)
    return games


def event_details_rows(event: dict, my_seat, opp_seat, opp_name: str = "Opp") -> list:
    """Ordered (label, value) pairs for the Event Details tab. Omits rows
    whose value is None/empty so the pane stays compact."""
    rows: list = []

    def add(label, value):
        if value is None or value == "" or value == []:
            return
        rows.append((label, str(value)))

    add("Seq", event.get("seq"))
    add("Turn", event.get("turn_num"))
    ph = phase_label(event.get("phase"))
    st = step_label(event.get("step"))
    add("Phase", f"{ph} — {st}" if st else (ph if ph != "—" else None))
    add("Player", player_label(event, my_seat, opp_seat, opp_name))
    add("Kind", kind_label(event.get("kind", "raw")))
    add("Card", event.get("card_name"))
    tgts = _targets_str(event)
    add("Targets", tgts)
    la = event.get("life_after")
    if la:
        add("Life", f"You {la.get('you')} / {opp_name} {la.get('opp')}")
    mp = event.get("mana_pool_after")
    if mp and (mp.get("you") or mp.get("opp")):
        add("Mana", f"You {mp.get('you') or '—'} / {opp_name} {mp.get('opp') or '—'}")
    details = event.get("details") or {}
    if "damage" in details:
        add("Damage", details.get("damage"))
    if event.get("shuffle_cause"):
        add("Shuffle cause", event.get("shuffle_cause"))
    rc = event.get("revealed_cards") or []
    if rc:
        add("Revealed", ", ".join(r.get("name", "?") for r in rc))
    return rows


def stack_rows(event: dict) -> list:
    """Rows for the Stack tab, from stack_after (top of list = as logged)."""
    stack = event.get("stack_after") or []
    out = []
    for i, item in enumerate(stack):
        out.append({
            "pos": i + 1,
            "name": item.get("name", "?"),
            "controller": item.get("controller", "?"),
            "targets": ", ".join(item.get("targets") or []),
        })
    return out


_JUMP_LABELS = {
    "first_spell": "First spell", "first_combat": "First combat",
    "low_life_threshold": "Low life", "lethal_attack": "Lethal attack",
    "concede": "Concede",
}


def jump_to_targets(match_meta: dict) -> list:
    """Flatten match_meta.key_events_by_turn into [{label, seq}] for the
    Jump-To menu."""
    out = []
    for ke in (match_meta or {}).get("key_events_by_turn") or []:
        kind = ke.get("kind", "")
        if kind.startswith("mulligan_to_"):
            base = f"Mulligan to {kind.rsplit('_', 1)[-1]}"
        else:
            base = _JUMP_LABELS.get(kind, kind.replace("_", " ").title())
        turn = ke.get("turn")
        label = f"T{turn} {base}" if turn is not None else base
        if ke.get("card"):
            label += f": {ke['card']}"
        elif ke.get("detail"):
            label += f" ({ke['detail']})"
        elif ke.get("actor"):
            label += f" ({ke['actor']})"
        out.append({"label": label, "seq": ke.get("seq")})
    return out


def always_visible_value(event: dict, field: str) -> str:
    """Render the field the user pinned in the 'Always Visible' dropdown."""
    if field == "life":
        la = event.get("life_after") or {}
        return f"Life — You {la.get('you', '?')} / Opp {la.get('opp', '?')}"
    if field == "mana":
        mp = event.get("mana_pool_after") or {}
        return f"Mana — You {mp.get('you') or '—'} / Opp {mp.get('opp') or '—'}"
    if field == "phase":
        ph = phase_label(event.get("phase"))
        st = step_label(event.get("step"))
        return f"{ph} — {st}" if st else ph
    if field == "stack_count":
        return f"{len(event.get('stack_after') or [])} on stack"
    return ""
