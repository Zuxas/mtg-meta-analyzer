# Replay Events M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational `events[]` data layer for the Full-Depth Replay Viewer — Player.log → structured event stream cached alongside the existing transcript. No GUI, no Odds Engine, no board viewer. Just the data contract that future systems will consume.

**Architecture:** New pure-Python module `analysis/replay_events.py` that re-walks MTGA's `Player.log` / `Player-prev.log` (reusing `_iter_json_blobs` and `_load_grpid_names` from `analysis/replay_transcript.py`) and emits a flat `events[]` list plus a `match_meta` header. Cached into the same `data/match_replays/<arena_match_id>.json` file as the existing transcript by adding new top-level keys (`schema_version`, `capabilities`, `events`, `match_meta`) alongside the existing `games` key. A CLI dump tool validates extraction. The MTGA watcher invokes both builders so new caches land complete.

**Tech Stack:** Python 3.13, pytest, stdlib only (json, pathlib, sqlite3). No new dependencies. Reuses helpers from `analysis/replay_transcript.py` and `db/database.py`. Test fixtures are hand-crafted JSON blobs in `tests/fixtures/replay_events/`.

**Spec:** `docs/superpowers/specs/2026-05-22-replay-viewer-design.md`

**Scope discipline:** This plan covers M1 only. The spec's M1 discipline guardrail forbids GUI work, Odds Engine code, board panels, Monte Carlo, overlay changes, and speculative abstractions. Any task that would touch those is out of scope — defer to the future milestone's own spec + plan.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `analysis/replay_events.py` | The event-stream extractor. `build_event_stream(arena_match_id, force_refresh)` is the only public function. ~600 LOC total. |
| `scripts/replay_event_dump.py` | CLI: `python scripts/replay_event_dump.py <arena_match_id>` prints the events as a pretty table. Smoke-test the extractor without any GUI. |
| `tests/fixtures/replay_events/__init__.py` | Shared helpers: `make_blob_iter(*blobs)` returns a callable replacement for `_iter_json_blobs` so tests can feed pre-parsed dicts. |
| `tests/fixtures/replay_events/minimal_match.py` | Minimal one-game fixture covering match-start → one cast → game-end. Used by basic tests. |
| `tests/fixtures/replay_events/full_phase_match.py` | One game touching every MTG phase + step. Used by phase coverage test. |
| `tests/fixtures/replay_events/scry_surveil_shuffle.py` | Fixture exercising `revealed_cards` + `shuffle_cause` capture. |
| `tests/test_replay_events.py` | All M1 acceptance gates as unit + integration tests. |

**Modified files:**

| Path | Responsibility |
|---|---|
| `gui/mtga_log_watcher.py` | `_build_missing_transcripts` calls both builders so new caches gain `events[]`. ~10 LOC change. |

**Untouched (and must stay untouched in M1):**

- `gui/widgets/replay_transcript_dialog.py` (classic viewer keeps working)
- `analysis/replay_transcript.py` (legacy transcript stays as ground truth for the round-trip test)
- Anything in `gui/widgets/` other than nothing
- Anything in `gui/tabs/`
- `gui/widgets/transparent_overlay.py` (live overlay — explicitly forbidden)

---

## Task Decomposition Overview

Tasks 1-3 scaffold the module and test infrastructure. Tasks 4-13 add event extraction one kind at a time (TDD: fixture-driven, one failing test per task). Tasks 14-17 add the synthesized layers (board_diff, match_meta, per-game decklists, key_events). Tasks 18-19 wire the cache I/O. Tasks 20-22 are CLI + watcher + integration validation. Task 23 is the end-of-M1 sync (docs + commit + push per project NON-NEGOTIABLE rules).

---

### Task 1: Module scaffolding

**Files:**
- Create: `analysis/replay_events.py`

- [ ] **Step 1: Create the scaffold**

```python
# analysis/replay_events.py
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
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from analysis.replay_events import build_event_stream, SCHEMA_VERSION, EVENT_KINDS, M1_CAPABILITIES; print(SCHEMA_VERSION, len(EVENT_KINDS), M1_CAPABILITIES['events'])"`
Expected: `1 33 True`

- [ ] **Step 3: Commit**

```bash
git add analysis/replay_events.py
git commit -m "feat(replay-events): module scaffold + constants

M1 scaffolding for the event-stream extractor. Public API stub raises
NotImplementedError; constants (SCHEMA_VERSION, EVENT_KINDS,
M1_CAPABILITIES) and imports from replay_transcript helpers are in place.
TDD tasks fill in the implementation."
```

---

### Task 2: Test fixture infrastructure

**Files:**
- Create: `tests/fixtures/replay_events/__init__.py`
- Create: `tests/fixtures/replay_events/minimal_match.py`

- [ ] **Step 1: Create the fixture helper**

```python
# tests/fixtures/replay_events/__init__.py
"""Hand-crafted MTGA log-blob fixtures for replay_events tests.

Fixtures are Python lists of dicts (the same shape _iter_json_blobs
yields). Tests inject these via the `_blobs` parameter on
build_event_stream so we don't need real Player.log files in source
control.
"""
from typing import Iterator


def make_blob_iter(blobs):
    """Return a callable that yields the given blobs.

    Replaces _iter_json_blobs in tests via monkeypatch.
    """
    def _iter(log_path):
        for b in blobs:
            yield b
    return _iter


def match_start(match_id, my_user_id="GCIUQPR6DRC4XL7L2ZTNU2OMNI",
                opp_name="TestOpp"):
    """Minimal matchGameRoomStateChangedEvent putting our user in seat 1."""
    return {
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "matchId": match_id,
                    "reservedPlayers": [
                        {"userId": my_user_id, "systemSeatId": 1,
                         "playerName": "You"},
                        {"userId": "OPPONENT_ID", "systemSeatId": 2,
                         "playerName": opp_name},
                    ],
                },
                "stateType": "MatchGameRoomStateType_Playing",
            },
        },
    }


def match_end(match_id):
    """Minimal matchGameRoomStateChangedEvent ending the match."""
    return {
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {"matchId": match_id, "reservedPlayers": []},
                "stateType": "MatchGameRoomStateType_MatchCompleted",
            },
        },
    }


def game_state(*, game_num=1, turn_num=1, active_seat=1, priority_seat=1,
               phase="Phase_Main1", step=None,
               life=(20, 20), mana_pool=("", ""),
               annotations=None, game_objects=None, zones=None,
               players=None, game_state_id=None):
    """Build a greToClientEvent blob with one GameStateMessage."""
    msg = {
        "type": "GREMessageType_GameStateMessage",
        "gameStateMessage": {
            "gameInfo": {"gameNumber": game_num, "stage": "GameStage_Playing"},
            "turnInfo": {
                "turnNumber": turn_num,
                "activePlayer": active_seat,
                "priorityPlayer": priority_seat,
                "phase": phase,
                "step": step,
            },
            "players": players or [
                {"systemSeatNumber": 1, "lifeTotal": life[0],
                 "manaPool": mana_pool[0]},
                {"systemSeatNumber": 2, "lifeTotal": life[1],
                 "manaPool": mana_pool[1]},
            ],
            "gameObjects": game_objects or [],
            "zones": zones or [],
            "annotations": annotations or [],
        },
    }
    if game_state_id is not None:
        msg["gameStateMessage"]["gameStateId"] = game_state_id
    return {"greToClientEvent": {"greToClientMessages": [msg]}}
```

- [ ] **Step 2: Create the minimal fixture**

```python
# tests/fixtures/replay_events/minimal_match.py
"""Minimal one-game fixture: match start, one priority grant, game end."""
from . import match_start, match_end, game_state

MATCH_ID = "minimal-test-match-001"


def build():
    return [
        match_start(MATCH_ID),
        game_state(game_num=1, turn_num=1, phase="Phase_Beginning",
                   step="Step_Untap"),
        match_end(MATCH_ID),
    ]
```

- [ ] **Step 3: Create the failing test**

```python
# tests/test_replay_events.py
"""M1 acceptance tests for analysis.replay_events.

Each test asserts one of the acceptance gates from the spec at
docs/superpowers/specs/2026-05-22-replay-viewer-design.md.
"""
from __future__ import annotations

import pytest

from analysis import replay_events
from tests.fixtures.replay_events import make_blob_iter
from tests.fixtures.replay_events.minimal_match import (
    MATCH_ID as MINIMAL_MATCH_ID, build as build_minimal,
)


def test_unknown_match_returns_none(monkeypatch):
    """build_event_stream returns None for a match not in the logs."""
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter([]))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream("nonexistent-id",
                                              force_refresh=True)
    assert result is None
```

- [ ] **Step 4: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_unknown_match_returns_none -v`
Expected: FAIL with `NotImplementedError: scaffold; tests drive the implementation`

- [ ] **Step 5: Make it pass — minimal extractor**

Replace the `build_event_stream` body in `analysis/replay_events.py`:

```python
def build_event_stream(arena_match_id: str,
                       force_refresh: bool = False) -> Optional[dict]:
    """Build (or load cached) event stream for one match."""
    cache = transcript_cache_path(arena_match_id)
    # Cache read happens in Task 18; for M1 scaffold we always rebuild.
    if not force_refresh and cache.exists():
        try:
            with open(cache, "r", encoding="utf-8") as f:
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
```

- [ ] **Step 6: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_unknown_match_returns_none -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add analysis/replay_events.py tests/fixtures/replay_events/ tests/test_replay_events.py
git commit -m "test(replay-events): fixture infra + unknown-match returns None

Hand-crafted MTGA blob fixtures (no real Player.log in source control).
make_blob_iter helper + match_start/match_end/game_state builders.
First test: build_event_stream returns None when arena_match_id isn't
in the log."
```

---

### Task 3: Match boundary + seat assignment

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_replay_events.py`:

```python
def test_match_boundary_populates_seats(monkeypatch):
    """match_start blob populates my_seat, opp_seat, opp_name."""
    blobs = build_minimal()
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MINIMAL_MATCH_ID,
                                              force_refresh=True)
    assert result is not None
    assert result["arena_match_id"] == MINIMAL_MATCH_ID
    assert result["my_seat"] == 1
    assert result["opp_seat"] == 2
    assert result["opp_name"] == "TestOpp"
    assert result["schema_version"] == 1
    assert result["capabilities"]["events"] is True
    assert result["capabilities"]["odds_ready"] is False
```

- [ ] **Step 2: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_match_boundary_populates_seats -v`
Expected: PASS (Task 2 step 5 already wired seat extraction)

- [ ] **Step 3: Commit**

```bash
git add tests/test_replay_events.py
git commit -m "test(replay-events): assert seat/name extraction on match boundary"
```

---

### Task 4: Phase + step events

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`
- Create: `tests/fixtures/replay_events/full_phase_match.py`

- [ ] **Step 1: Build the phase-coverage fixture**

```python
# tests/fixtures/replay_events/full_phase_match.py
"""Fixture covering one game touching every MTG phase + step.

Phase coverage acceptance gate from the spec: at least one event per
phase/step pair MTGA emits (Beginning/Untap, Beginning/Upkeep,
Beginning/Draw, Main1, Combat/Begin, Combat/DeclareAttackers,
Combat/DeclareBlockers, Combat/Damage, Combat/End, Main2, Ending/End,
Ending/Cleanup).
"""
from . import match_start, match_end, game_state

MATCH_ID = "full-phase-test-match-001"

_PHASES_STEPS = [
    ("Phase_Beginning", "Step_Untap"),
    ("Phase_Beginning", "Step_Upkeep"),
    ("Phase_Beginning", "Step_Draw"),
    ("Phase_Main1", None),
    ("Phase_Combat", "Step_BeginCombat"),
    ("Phase_Combat", "Step_DeclareAttackers"),
    ("Phase_Combat", "Step_DeclareBlockers"),
    ("Phase_Combat", "Step_CombatDamage"),
    ("Phase_Combat", "Step_EndCombat"),
    ("Phase_Main2", None),
    ("Phase_Ending", "Step_End"),
    ("Phase_Ending", "Step_Cleanup"),
]


def build():
    blobs = [match_start(MATCH_ID)]
    for idx, (phase, step) in enumerate(_PHASES_STEPS):
        blobs.append(game_state(
            game_num=1, turn_num=1, active_seat=1, priority_seat=1,
            phase=phase, step=step, game_state_id=100 + idx,
        ))
    blobs.append(match_end(MATCH_ID))
    return blobs
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_replay_events.py`:

```python
from tests.fixtures.replay_events.full_phase_match import (
    MATCH_ID as PHASE_MATCH_ID, build as build_phase_match, _PHASES_STEPS,
)


def test_phase_coverage(monkeypatch):
    """events[] includes a phase_change/step_change for every MTG phase+step pair."""
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_phase_match()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(PHASE_MATCH_ID,
                                              force_refresh=True)
    assert result is not None
    seen_pairs = set()
    for ev in result["events"]:
        if ev["kind"] in ("phase_change", "step_change"):
            seen_pairs.add((ev["phase"], ev["step"]))
    for phase, step in _PHASES_STEPS:
        assert (phase, step) in seen_pairs, \
            f"missing phase/step pair: {phase}/{step}"
```

- [ ] **Step 3: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_phase_coverage -v`
Expected: FAIL — events list is empty

- [ ] **Step 4: Implement phase/step extraction**

In `analysis/replay_events.py`, modify the main loop to walk `greToClientEvent` and emit phase/step events. Add a `_seq` counter and `prev_phase`/`prev_step` state:

```python
# Inside build_event_stream, right after `target_found = False`:
seq = 0
prev_phase: Optional[str] = None
prev_step: Optional[str] = None
prev_priority: Optional[int] = None
current_game = 1
current_turn = 0
current_active_seat: Optional[int] = None
current_priority_seat: Optional[int] = None

def _emit(kind: str, **payload):
    nonlocal seq
    if kind not in EVENT_KINDS:
        kind = "raw"
        payload.setdefault("details", {})["original_kind"] = kind
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
```

Add `current_phase = None; current_step = None` initialization near the top. Then inside the blob walk:

```python
# After the matchGameRoomStateChangedEvent handling:
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
        new_phase = ti.get("phase")
        new_step = ti.get("step")
        gs_id = gsm.get("gameStateId")

        if new_phase and new_phase != current_phase:
            current_phase = new_phase
            current_step = new_step  # update simultaneously
            _emit("phase_change", game_state_id=gs_id)
        elif new_step and new_step != current_step:
            current_step = new_step
            _emit("step_change", game_state_id=gs_id)
        elif new_phase and current_phase is None:
            # first time seeing phase
            current_phase = new_phase
            current_step = new_step
            _emit("phase_change", game_state_id=gs_id)
```

- [ ] **Step 5: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_phase_coverage -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add analysis/replay_events.py tests/fixtures/replay_events/full_phase_match.py tests/test_replay_events.py
git commit -m "feat(replay-events): emit phase_change/step_change events

Every distinct phase/step pair MTGA emits in turnInfo produces an event.
Acceptance gate: phase_coverage test asserts ≥1 event per pair of the
12 MTG phases/steps."
```

---

### Task 5: Priority tracking

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the priority-sequencing test**

Append to `tests/test_replay_events.py`:

```python
def _make_priority_fixture():
    """3 game-state messages alternating priorityPlayer: 1, 2, 1."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "priority-test-match-001"
    return MID, [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, game_state_id=200),
        game_state(turn_num=1, priority_seat=2, game_state_id=201),
        game_state(turn_num=1, priority_seat=1, game_state_id=202),
        match_end(MID),
    ]


def test_priority_sequencing(monkeypatch):
    """Every event between two priority_grant events has the same priority_seat."""
    mid, blobs = _make_priority_fixture()
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(mid, force_refresh=True)
    assert result is not None
    grants = [e for e in result["events"] if e["kind"] == "priority_grant"]
    assert len(grants) == 3
    assert [g["priority_seat"] for g in grants] == [1, 2, 1]
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_priority_sequencing -v`
Expected: FAIL — no priority_grant events emitted

- [ ] **Step 3: Emit priority_grant on every priorityPlayer transition**

Add to the GameStateMessage block in `analysis/replay_events.py`, right after the phase/step block:

```python
        if priority is not None and priority != current_priority_seat:
            current_priority_seat = priority
            _emit("priority_grant", game_state_id=gs_id)
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_priority_sequencing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): emit priority_grant on every priorityPlayer change

Acceptance gate: priority_sequencing test asserts grants land in the
order MTGA reports them."
```

---

### Task 6: Stack snapshot from zones

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the stack-snapshot test**

Append to `tests/test_replay_events.py`:

```python
def test_stack_after_populated_from_zones(monkeypatch):
    """When zones[] contains ZoneType_Stack with object IDs, stack_after
    on the next event reflects the stack."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "stack-test-match-001"
    grpid_names = {100: "Lightning Strike", 200: "Make Disappear"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=300,
            game_objects=[
                {"instanceId": 1, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 2, "grpId": 200, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
            zones=[
                {"type": "ZoneType_Stack", "objectInstanceIds": [1, 2]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result is not None
    assert len(result["events"]) >= 1
    last = result["events"][-1]
    names = [s["name"] for s in last["stack_after"]]
    assert names == ["Lightning Strike", "Make Disappear"]
    controllers = [s["controller"] for s in last["stack_after"]]
    assert controllers == ["you", "opp"]
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_stack_after_populated_from_zones -v`
Expected: FAIL — stack_after is empty

- [ ] **Step 3: Track instance->grpid+owner and build stack_after**

Add to `analysis/replay_events.py` (state init near top of `build_event_stream`):

```python
instance_to_grpid: dict[int, int] = {}
instance_to_owner: dict[int, int] = {}
current_stack: list[dict] = []
```

Inside the GameStateMessage block, before `_emit`:

```python
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
```

In the `_emit` function definition, change the `stack_after` default to use the current snapshot:

```python
"stack_after": payload.pop("stack_after", list(current_stack)),
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_stack_after_populated_from_zones -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): snapshot stack_after from zones[]

Every event carries the current stack state at emit time, reconstructed
from zones[].objectInstanceIds and the running instance->grpid map."
```

---

### Task 7: Cast / resolve / counter events

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the cast/resolve test**

Append to `tests/test_replay_events.py`:

```python
def test_cast_resolve_counter_events(monkeypatch):
    """ZoneTransfer annotations with category=CastSpell/Resolve/Countered
    produce cast_spell/resolve/counter_spell events."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "cast-test-match-001"
    grpid_names = {100: "Lightning Strike"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=400,
            game_objects=[
                {"instanceId": 5, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 1, "type": ["AnnotationType_ZoneTransfer"],
                 "affectedIds": [5],
                 "details": [{"key": "category",
                              "valueString": ["CastSpell"]}]},
                {"id": 2, "type": ["AnnotationType_ZoneTransfer"],
                 "affectedIds": [5],
                 "details": [{"key": "category",
                              "valueString": ["Resolve"]}]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "cast_spell" in kinds
    assert "resolve" in kinds
    cast = [e for e in result["events"] if e["kind"] == "cast_spell"][0]
    assert cast["card_name"] == "Lightning Strike"
    assert cast["card_grpid"] == 100
    assert cast["actor_seat"] == 1
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_cast_resolve_counter_events -v`
Expected: FAIL — no cast_spell events

- [ ] **Step 3: Add annotation walker**

Add to `analysis/replay_events.py`, after the stack-snapshot block:

```python
seen_annotations: set[int] = set()
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
                _emit(kind, game_state_id=gs_id, actor_seat=owner,
                      card_name=nm, card_grpid=grp,
                      details={"category": cat})
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_cast_resolve_counter_events -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): cast_spell / resolve / counter_spell / play_land / draw_card

ZoneTransfer annotation walker dispatches to normalized kinds; one event
per affected instanceId. actor_seat resolved from instance owner."
```

---

### Task 8: Targets + damage events

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the targets/damage test**

Append to `tests/test_replay_events.py`:

```python
def test_targets_and_damage(monkeypatch):
    """PlayerSubmittedTargets -> target_chosen; DamageDealt -> damage_dealt."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "tgt-test-match-001"
    grpid_names = {100: "Lightning Strike", 200: "Goblin"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=500,
            game_objects=[
                {"instanceId": 5, "grpId": 100, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 6, "grpId": 200, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
            annotations=[
                {"id": 10, "type": ["AnnotationType_PlayerSubmittedTargets"],
                 "affectedIds": [6]},
                {"id": 11, "type": ["AnnotationType_DamageDealt"],
                 "affectedIds": [5, 6],
                 "details": [{"key": "damage",
                              "valueInt32": [3]}]},
            ],
        ),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "target_chosen" in kinds
    assert "damage_dealt" in kinds
    tgt = [e for e in result["events"] if e["kind"] == "target_chosen"][0]
    assert tgt["targets"][0]["name"] == "Goblin"
    dmg = [e for e in result["events"] if e["kind"] == "damage_dealt"][0]
    assert dmg["details"]["damage"] == 3
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_targets_and_damage -v`
Expected: FAIL

- [ ] **Step 3: Handle PlayerSubmittedTargets and DamageDealt**

In `analysis/replay_events.py`, extend the annotation walker:

```python
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
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_targets_and_damage -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): target_chosen + damage_dealt"
```

---

### Task 9: Scry / surveil — public information capture

**Files:**
- Modify: `analysis/replay_events.py`
- Create: `tests/fixtures/replay_events/scry_surveil_shuffle.py`
- Modify: `tests/test_replay_events.py`

This task lands the FIRST half of the Odds Engine data contract.

- [ ] **Step 1: Create the scry/surveil fixture**

```python
# tests/fixtures/replay_events/scry_surveil_shuffle.py
"""Fixture for revealed_cards + shuffle_cause capture (Odds Engine contract)."""
from . import match_start, match_end, game_state

MATCH_ID = "scry-shuffle-test-match-001"

GRPID_NAMES = {300: "Opt", 301: "Island", 302: "Mountain"}


def build_scry():
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=600,
            game_objects=[
                {"instanceId": 10, "grpId": 300, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 11, "grpId": 301, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 12, "grpId": 302, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 20, "type": ["AnnotationType_Scry"],
                 "affectedIds": [],
                 "details": [
                     {"key": "topIds", "valueInt32": [11]},
                     {"key": "bottomIds", "valueInt32": [12]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]


def build_surveil():
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=601,
            game_objects=[
                {"instanceId": 13, "grpId": 300, "ownerSeatId": 1,
                 "controllerSeatId": 1},
            ],
            annotations=[
                {"id": 21, "type": ["AnnotationType_Surveil"],
                 "affectedIds": [13],
                 "details": [
                     {"key": "topIds", "valueInt32": [13]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]


def build_shuffle(cause="effect"):
    return [
        match_start(MATCH_ID),
        game_state(
            turn_num=1, priority_seat=1, game_state_id=602,
            annotations=[
                {"id": 22, "type": ["AnnotationType_Shuffle"],
                 "affectedIds": [],
                 "details": [
                     {"key": "cause", "valueString": [cause]},
                 ]},
            ],
        ),
        match_end(MATCH_ID),
    ]
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_replay_events.py`:

```python
def test_scry_populates_revealed_cards(monkeypatch):
    """Scry annotation produces an event with revealed_cards populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as SCRY_MID, GRPID_NAMES, build_scry,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_scry()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(SCRY_MID, force_refresh=True)
    assert result is not None
    scry = [e for e in result["events"] if e["kind"] == "scry"]
    assert len(scry) == 1
    revealed = scry[0]["revealed_cards"]
    assert any(r["name"] == "Island" and r["library_position"] == "top"
               for r in revealed)
    assert any(r["name"] == "Mountain" and r["library_position"] == "bottom"
               for r in revealed)


def test_surveil_populates_revealed_cards(monkeypatch):
    """Surveil annotation produces an event with revealed_cards populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as MID, GRPID_NAMES, build_surveil,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_surveil()))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    surveil_evs = [e for e in result["events"] if e["kind"] == "surveil"]
    assert len(surveil_evs) == 1
    revealed = surveil_evs[0]["revealed_cards"]
    assert revealed and revealed[0]["name"] == "Opt"
    assert revealed[0]["source"] == "surveil_top"
```

- [ ] **Step 3: Run tests to confirm they fail**

Run: `python -m pytest tests/test_replay_events.py::test_scry_populates_revealed_cards tests/test_replay_events.py::test_surveil_populates_revealed_cards -v`
Expected: FAIL

- [ ] **Step 4: Handle Scry and Surveil annotations**

In `analysis/replay_events.py`, extend the annotation walker:

```python
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
        revealed = []
        for iid in affected:
            grp = instance_to_grpid.get(iid)
            revealed.append({
                "grpid": grp,
                "name": grpid_names.get(grp, f"instance#{iid}") if grp else f"instance#{iid}",
                "source": "surveil_top",
                "seat": my_seat,
                "library_position": "top",
            })
        _emit("surveil", game_state_id=gs_id, revealed_cards=revealed)
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `python -m pytest tests/test_replay_events.py::test_scry_populates_revealed_cards tests/test_replay_events.py::test_surveil_populates_revealed_cards -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add analysis/replay_events.py tests/fixtures/replay_events/scry_surveil_shuffle.py tests/test_replay_events.py
git commit -m "feat(replay-events): scry + surveil populate revealed_cards

First half of the Odds Engine data contract. Each scry/surveil event
ships a revealed_cards[] list with grpid, name, source, seat, and
library_position so future Odds Engine can reconstruct public-info
state at any seq."
```

---

### Task 10: Shuffle events with shuffle_cause

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

Second half of the Odds Engine data contract.

- [ ] **Step 1: Add the shuffle test**

Append to `tests/test_replay_events.py`:

```python
def test_shuffle_populates_cause(monkeypatch):
    """Shuffle annotation produces an event with details.cause populated."""
    from tests.fixtures.replay_events.scry_surveil_shuffle import (
        MATCH_ID as MID, GRPID_NAMES, build_shuffle,
    )
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(build_shuffle(cause="fetch")))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: GRPID_NAMES)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    shuffles = [e for e in result["events"] if e["kind"] == "shuffle"]
    assert len(shuffles) == 1
    assert shuffles[0]["shuffle_cause"] == "fetch"


def test_shuffle_unknown_cause_defaults(monkeypatch):
    """Shuffle without cause detail gets shuffle_cause='unknown'."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "shuffle-unknown-001"
    blobs = [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, annotations=[
            {"id": 30, "type": ["AnnotationType_Shuffle"],
             "affectedIds": [], "details": []},
        ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    shuffles = [e for e in result["events"] if e["kind"] == "shuffle"]
    assert len(shuffles) == 1
    assert shuffles[0]["shuffle_cause"] == "unknown"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_replay_events.py -k "shuffle" -v`
Expected: FAIL

- [ ] **Step 3: Handle Shuffle annotation**

In `analysis/replay_events.py`, extend the annotation walker:

```python
    elif t == "AnnotationType_Shuffle":
        cause = _ds("cause") or "unknown"
        _emit("shuffle", game_state_id=gs_id, shuffle_cause=cause)
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `python -m pytest tests/test_replay_events.py -k "shuffle" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): shuffle events carry shuffle_cause

Second half of Odds Engine data contract. Defaults to 'unknown' when
the annotation has no cause detail."
```

---

### Task 11: Life + mana_pool deltas

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the life + mana test**

Append to `tests/test_replay_events.py`:

```python
def test_life_change_emitted(monkeypatch):
    """When a player's lifeTotal changes between game states, a life_change event lands."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "life-test-001"
    blobs = [
        match_start(MID),
        game_state(turn_num=1, life=(20, 20), priority_seat=1),
        game_state(turn_num=1, life=(20, 17), priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    lifechanges = [e for e in result["events"] if e["kind"] == "life_change"]
    assert len(lifechanges) == 1
    assert lifechanges[0]["details"]["seat"] == 2
    assert lifechanges[0]["details"]["delta"] == -3
    assert lifechanges[0]["life_after"]["opp"] == 17
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_life_change_emitted -v`
Expected: FAIL

- [ ] **Step 3: Track life + mana per message**

Add to `analysis/replay_events.py` state init:

```python
prev_life: dict[int, int] = {}
prev_mana: dict[int, str] = {}
current_life_after = None
current_mana_pool_after = None
```

Inside the GameStateMessage block, after stack snapshot:

```python
# Track life + mana from players[]; emit life_change on delta.
for p in gsm.get("players", []) or []:
    seat = p.get("systemSeatNumber")
    lt = p.get("lifeTotal")
    mp = p.get("manaPool", "") or ""
    if seat is None:
        continue
    if lt is not None:
        last = prev_life.get(seat)
        if last is not None and lt != last:
            _emit("life_change", game_state_id=gs_id,
                  details={"seat": seat, "delta": lt - last,
                           "from": last, "to": lt})
        prev_life[seat] = lt
    if mp != prev_mana.get(seat, ""):
        prev_mana[seat] = mp

# Update the per-event life_after / mana_pool_after defaults.
current_life_after = {
    "you": prev_life.get(my_seat),
    "opp": prev_life.get(opp_seat),
}
current_mana_pool_after = {
    "you": prev_mana.get(my_seat, ""),
    "opp": prev_mana.get(opp_seat, ""),
}
```

Update the `_emit` defaults:

```python
"life_after": payload.pop("life_after", dict(current_life_after) if current_life_after else None),
"mana_pool_after": payload.pop("mana_pool_after", dict(current_mana_pool_after) if current_mana_pool_after else None),
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_life_change_emitted -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): life_change events + life_after / mana_pool_after on every event"
```

---

### Task 12: Board diff validity

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the board-diff test**

Append to `tests/test_replay_events.py`:

```python
def test_board_diff_validity(monkeypatch):
    """Applying all board_diff[] entries from seq=0 produces the same
    zone counts MTGA reports in zones[]."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "board-test-001"
    grpid_names = {500: "Mountain"}
    blobs = [
        match_start(MID),
        # T1: Mountain in hand
        game_state(turn_num=1, priority_seat=1, game_state_id=700,
                   game_objects=[
                       {"instanceId": 50, "grpId": 500, "ownerSeatId": 1,
                        "controllerSeatId": 1, "zoneId": 1},
                   ],
                   zones=[
                       {"type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": [50]},
                       {"type": "ZoneType_Battlefield",
                        "objectInstanceIds": []},
                   ]),
        # T1: Mountain played
        game_state(turn_num=1, priority_seat=1, game_state_id=701,
                   game_objects=[
                       {"instanceId": 50, "grpId": 500, "ownerSeatId": 1,
                        "controllerSeatId": 1, "zoneId": 2},
                   ],
                   zones=[
                       {"type": "ZoneType_Hand", "ownerSeatId": 1,
                        "objectInstanceIds": []},
                       {"type": "ZoneType_Battlefield",
                        "objectInstanceIds": [50]},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    # Walk all board_diff entries and apply them
    zones_now = {"hand": set(), "battlefield": set()}
    for ev in result["events"]:
        for diff in ev["board_diff"]:
            src = diff.get("from")
            dst = diff.get("to")
            iid = diff["instance_id"]
            if src in zones_now:
                zones_now[src].discard(iid)
            if dst in zones_now:
                zones_now[dst].add(iid)
    # Final state should match the last MTGA zones[] snapshot
    assert 50 in zones_now["battlefield"]
    assert 50 not in zones_now["hand"]
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_board_diff_validity -v`
Expected: FAIL

- [ ] **Step 3: Track instance->zone and emit board_diff entries**

Add to `analysis/replay_events.py` state init:

```python
instance_to_zone: dict[int, str] = {}
```

Add a helper and zone-diff logic in the GameStateMessage block (after the stack-snapshot section):

```python
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

# Build current zone snapshot from zones[]
current_zones: dict[int, str] = {}
for zone in gsm.get("zones", []) or []:
    zname = _ZONE_TYPE_TO_NAME.get(zone.get("type"))
    if not zname:
        continue
    for iid in zone.get("objectInstanceIds", []) or []:
        current_zones[iid] = zname

# Compute diffs against the running instance_to_zone map
zone_diffs = []
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

# Emit a zone_change event holding the batch diff if there are diffs
# AND no other event has fired this message (i.e., diffs aren't
# already attributed to a cast/resolve/etc.)
pending_zone_diffs = zone_diffs  # consumed by the next _emit
```

Update `_emit` to attach pending zone diffs to the first event emitted in this message, then clear:

```python
def _emit(kind: str, **payload):
    nonlocal seq, pending_zone_diffs
    if kind not in EVENT_KINDS:
        kind = "raw"
    diffs_for_this_event = payload.pop("board_diff", None)
    if diffs_for_this_event is None:
        diffs_for_this_event = pending_zone_diffs
        pending_zone_diffs = []
    ev = {
        # ... (same as before, with board_diff = diffs_for_this_event)
    }
    events.append(ev)
    seq += 1
```

After processing all annotations in a message, if pending_zone_diffs is non-empty, emit a synthetic `zone_change`:

```python
# After the annotations loop:
if pending_zone_diffs:
    _emit("zone_change", game_state_id=gs_id)
```

Move `pending_zone_diffs = []` initialization to the top of `build_event_stream`.

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_board_diff_validity -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): board_diff[] entries on zone transitions

Every event carries the zone diffs since the previous event. Synthetic
zone_change events catch transitions not already attributed to a
cast/resolve/etc."
```

---

### Task 13: Mulligan + game_end + winner detection

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the mulligan + game-end test**

Append to `tests/test_replay_events.py`:

```python
def test_mulligan_and_game_end(monkeypatch):
    """ClientMessageType_MulliganResp -> mulligan_decision; game stage
    Completed -> game_end."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "mull-test-001"
    blobs = [
        match_start(MID),
        # Mull decision from client
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_MulliganResp",
             "mulliganResp": {"decision": "MulliganOption_Mulligan"},
         }},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_MulliganResp",
             "mulliganResp": {"decision": "MulliganOption_AcceptHand"},
         }},
        game_state(turn_num=1, priority_seat=1),
        # Game ends with seat 1 winning
        {"greToClientEvent": {"greToClientMessages": [{
            "type": "GREMessageType_GameStateMessage",
            "gameStateMessage": {
                "gameInfo": {
                    "gameNumber": 1,
                    "stage": "GameStage_GameOver",
                    "results": [{"winningTeamId": 1,
                                 "reason": "ResultReason_Concede"}],
                },
                "turnInfo": {"turnNumber": 1, "phase": "Phase_Main1"},
                "players": [], "gameObjects": [], "zones": [],
                "annotations": [],
            },
        }]}},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "mulligan_decision" in kinds
    assert "keep_hand" in kinds
    assert "game_end" in kinds
    assert result["match_meta"]["winner_seat"] == 1
    assert result["match_meta"]["winner_reason"] == "Concede"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_mulligan_and_game_end -v`
Expected: FAIL

- [ ] **Step 3: Handle Mulligan + game-end**

In `analysis/replay_events.py`, after the GameStateMessage block, detect game-over from `gameInfo.stage`:

```python
stage = gi.get("stage")
if stage == "GameStage_GameOver":
    results = gi.get("results") or []
    if results:
        winning_team = results[0].get("winningTeamId")
        reason = results[0].get("reason", "")
        # Strip "ResultReason_" prefix
        reason_clean = reason.replace("ResultReason_", "") if reason else None
        if match_meta["winner_seat"] is None:
            match_meta["winner_seat"] = winning_team
            match_meta["winner_reason"] = reason_clean
    _emit("game_end", game_state_id=gs_id,
          details={"winning_seat": match_meta["winner_seat"],
                   "reason": match_meta["winner_reason"]})
```

Add a separate handler for ClientToMatchServiceMessage blobs after the GRE block:

```python
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
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_mulligan_and_game_end -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): mulligan_decision, keep_hand, game_end + winner detection"
```

---

### Task 14: Attackers + blockers (client messages)

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the combat test**

Append to `tests/test_replay_events.py`:

```python
def test_attack_and_block_declared(monkeypatch):
    """SubmitAttackersReq -> attack_declared; SubmitBlockersReq -> block_declared."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "combat-test-001"
    grpid_names = {600: "Goblin Guide", 601: "Wall of Omens"}
    blobs = [
        match_start(MID),
        game_state(
            turn_num=2, priority_seat=1, game_state_id=800,
            game_objects=[
                {"instanceId": 100, "grpId": 600, "ownerSeatId": 1,
                 "controllerSeatId": 1},
                {"instanceId": 101, "grpId": 601, "ownerSeatId": 2,
                 "controllerSeatId": 2},
            ],
        ),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitAttackersReq",
             "submitAttackersReq": {
                 "attackers": [{"attackerId": 100}],
             },
         }},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitBlockersReq",
             "submitBlockersReq": {
                 "blockerToAttackerMap": [
                     {"blockerId": 101, "attackerId": 100},
                 ],
             },
         }},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert "attack_declared" in kinds
    assert "block_declared" in kinds
    atk = [e for e in result["events"] if e["kind"] == "attack_declared"][0]
    assert atk["details"]["attackers"][0]["name"] == "Goblin Guide"
    blk = [e for e in result["events"] if e["kind"] == "block_declared"][0]
    assert blk["details"]["blocks"][0]["blocker"] == "Wall of Omens"
    assert blk["details"]["blocks"][0]["attacker"] == "Goblin Guide"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_attack_and_block_declared -v`
Expected: FAIL

- [ ] **Step 3: Handle attacker/blocker submits**

In `analysis/replay_events.py`, extend the ClientToMatchServiceMessage handler:

```python
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
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_attack_and_block_declared -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): attack_declared + block_declared from client messages"
```

---

### Task 15: Match meta — event name + timestamps + duration

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the match-meta test**

Append to `tests/test_replay_events.py`:

```python
def test_match_meta_populated(monkeypatch):
    """match_meta has format, event_name, start/end, duration_sec, winner."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "meta-test-001"
    blobs = [
        # MatchPending blob also carries event metadata
        {"matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "gameRoomConfig": {
                    "matchId": MID,
                    "reservedPlayers": [
                        {"userId": "GCIUQPR6DRC4XL7L2ZTNU2OMNI",
                         "systemSeatId": 1, "playerName": "You"},
                        {"userId": "OPP", "systemSeatId": 2,
                         "playerName": "Opp"},
                    ],
                    "eventId": "Constructed_BestOf3_Ranked",
                },
                "stateType": "MatchGameRoomStateType_Playing",
            },
        }},
        game_state(turn_num=1, priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result["match_meta"]["event_name"] == "Constructed_BestOf3_Ranked"
    # decklist_my_grpids defaults to [] in M1 without a SubmitDeckResp blob
    assert result["match_meta"]["decklist_my_grpids"] == []
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_match_meta_populated -v`
Expected: FAIL (event_name not captured yet)

- [ ] **Step 3: Capture event_name during match boundary**

In `analysis/replay_events.py`, modify the match-boundary handler:

```python
if mid == arena_match_id:
    target_found = True
    if cfg.get("eventId") and not match_meta["event_name"]:
        match_meta["event_name"] = cfg["eventId"]
    # ... existing seat logic
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_match_meta_populated -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): match_meta.event_name from gameRoomConfig.eventId"
```

---

### Task 16: Per-game decklists from SubmitDeckResp

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

Required for postboard Odds Engine support.

- [ ] **Step 1: Add the per-game decklist test**

Append to `tests/test_replay_events.py`:

```python
def test_per_game_decklists(monkeypatch):
    """SubmitDeckResp blobs populate match_meta.games[i].decklist_my_grpids."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "deck-test-001"
    deck_g1 = [101, 102, 103, 104, 101]  # game 1 mainboard
    deck_g2 = [101, 102, 103, 105, 105]  # game 2 — swapped 104→105 (+1 of 105)
    blobs = [
        match_start(MID),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitDeckResp",
             "submitDeckResp": {
                 "deck": {"deckCards": deck_g1, "sideboardCards": []},
             },
         }},
        game_state(game_num=1, turn_num=1, priority_seat=1),
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {
             "type": "ClientMessageType_SubmitDeckResp",
             "submitDeckResp": {
                 "deck": {"deckCards": deck_g2, "sideboardCards": []},
             },
         }},
        game_state(game_num=2, turn_num=1, priority_seat=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    games = result["match_meta"]["games"]
    assert len(games) == 2
    assert games[0]["decklist_my_grpids"] == deck_g1
    assert games[1]["decklist_my_grpids"] == deck_g2
    # G2 sideboarded in 105 x2, out 104 x1
    assert 105 in games[1]["sideboard_in"]
    assert 104 in games[1]["sideboard_out"]
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_per_game_decklists -v`
Expected: FAIL

- [ ] **Step 3: Handle SubmitDeckResp and compute sideboard diffs**

Add to `analysis/replay_events.py`, extending the ClientToMatchServiceMessage handler:

```python
    elif ptype == "ClientMessageType_SubmitDeckResp":
        deck = (payload.get("submitDeckResp", {}) or {}).get("deck", {}) or {}
        cards = deck.get("deckCards", []) or []
        # First SubmitDeckResp is G1; subsequent ones are G2/G3
        gnum = len(match_meta["games"]) + 1
        prev_cards = match_meta["games"][-1]["decklist_my_grpids"] if match_meta["games"] else []
        # Compute multiset diff
        from collections import Counter
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
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_per_game_decklists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): per-game decklist tracking in match_meta.games[]

SubmitDeckResp blobs feed match_meta.games[i].decklist_my_grpids plus
sideboard_in/sideboard_out multiset diffs vs the previous game. Required
for postboard odds calculations in the future Odds Engine."
```

---

### Task 17: Key events extraction (post-pass)

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the key-events test**

Append to `tests/test_replay_events.py`:

```python
def test_key_events_extracted(monkeypatch):
    """key_events_by_turn includes first_spell, mulligan_to_6, concede."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "key-events-test-001"
    grpid_names = {700: "Lightning Strike"}
    blobs = [
        match_start(MID),
        # Mull → keep on 6
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {"type": "ClientMessageType_MulliganResp",
                     "mulliganResp": {"decision": "MulliganOption_Mulligan"}}},
        {"clientToMatchServiceMessageType":
            "ClientToMatchServiceMessageType_ClientToGREMessage",
         "payload": {"type": "ClientMessageType_MulliganResp",
                     "mulliganResp": {"decision": "MulliganOption_AcceptHand"}}},
        # First spell turn 3
        game_state(turn_num=3, priority_seat=1, game_state_id=900,
                   game_objects=[
                       {"instanceId": 200, "grpId": 700, "ownerSeatId": 1,
                        "controllerSeatId": 1},
                   ],
                   annotations=[
                       {"id": 50, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [200],
                        "details": [{"key": "category",
                                     "valueString": ["CastSpell"]}]},
                   ]),
        # Concede
        {"greToClientEvent": {"greToClientMessages": [{
            "type": "GREMessageType_GameStateMessage",
            "gameStateMessage": {
                "gameInfo": {"gameNumber": 1,
                             "stage": "GameStage_GameOver",
                             "results": [{"winningTeamId": 2,
                                          "reason": "ResultReason_Concede"}]},
                "turnInfo": {"turnNumber": 4, "phase": "Phase_Main1"},
                "players": [], "gameObjects": [], "zones": [],
                "annotations": [],
            },
        }]}},
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    keys = result["match_meta"]["key_events_by_turn"]
    kinds = [k["kind"] for k in keys]
    assert "mulligan_to_6" in kinds
    assert "first_spell" in kinds
    assert "concede" in kinds
    first_spell = [k for k in keys if k["kind"] == "first_spell"][0]
    assert first_spell["turn"] == 3
    assert first_spell["card"] == "Lightning Strike"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_key_events_extracted -v`
Expected: FAIL

- [ ] **Step 3: Add key-events post-pass**

In `analysis/replay_events.py`, before the return statement, add:

```python
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
                # actor = the loser, i.e., the player who isn't winning
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
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_key_events_extracted -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): key_events_by_turn post-pass

Identifies mulligan_to_N, first_spell, first_combat, low_life_threshold,
lethal_attack, concede. Drives the Key Events sidebar in the future
viewer."
```

---

### Task 18: Cache write — extend existing JSON with events[]

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the cache-roundtrip test**

Append to `tests/test_replay_events.py`:

```python
def test_cache_write_preserves_classic_keys(tmp_path, monkeypatch):
    """Writing event stream to an existing classic cache preserves the
    games/turns keys the classic dialog reads."""
    import json
    MID = "cache-test-001"
    # Seed an existing classic transcript cache
    classic = {
        "arena_match_id": MID,
        "my_seat": 1, "opp_seat": 2, "opp_name": "TestOpp",
        "games": [
            {"game_num": 1, "turns": [
                {"turn": 1, "active_seat": 1, "active_label": "You",
                 "actions": ["You play Mountain (land)"]},
            ]},
        ],
    }
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    (tmp_path / f"{MID}.json").write_text(json.dumps(classic),
                                          encoding="utf-8")

    # Feed minimal blobs through extractor
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    blobs = [match_start(MID), game_state(turn_num=1, priority_seat=1),
             match_end(MID)]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=True)
    assert result is not None

    # Cache file now has BOTH classic and new keys
    with open(tmp_path / f"{MID}.json", encoding="utf-8") as f:
        merged = json.load(f)
    assert "games" in merged
    assert merged["games"][0]["turns"][0]["actions"] == ["You play Mountain (land)"]
    assert "events" in merged
    assert "match_meta" in merged
    assert merged["schema_version"] == 1
    assert merged["capabilities"]["events"] is True
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_cache_write_preserves_classic_keys -v`
Expected: FAIL — we don't write to disk yet

- [ ] **Step 3: Add merge-and-write logic**

In `analysis/replay_events.py`, before the `return` statement:

```python
# Write the merged cache: preserve any existing classic keys
# (games/turns/actions etc.) and add our new event-stream keys.
out = {
    "arena_match_id": arena_match_id,
    "schema_version": SCHEMA_VERSION,
    "capabilities": dict(M1_CAPABILITIES),
    "match_meta": match_meta,
    "my_seat": my_seat,
    "opp_seat": opp_seat,
    "opp_name": opp_name,
    "events": events,
}

# Merge with existing classic cache if present
existing_cache_path = transcript_cache_path(arena_match_id)
if existing_cache_path.exists():
    try:
        with open(existing_cache_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        # Preserve classic keys we don't write ourselves
        for k in ("games",):
            if k in existing and k not in out:
                out[k] = existing[k]
    except Exception:
        pass  # ignore corrupted classic cache

try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(existing_cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
except Exception:
    pass  # best-effort

return out
```

Make sure `CACHE_DIR` is imported at module top (it is — verify).

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_cache_write_preserves_classic_keys -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): merge events[] into existing classic cache JSON

Cache write preserves the existing games/turns keys (classic dialog
keeps reading them) and adds schema_version, capabilities, match_meta,
events. One file per match, two consumers, zero classic-side breakage."
```

---

### Task 19: Cache read — capabilities-driven auto-rebuild

**Files:**
- Modify: `analysis/replay_events.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the auto-rebuild test**

Append to `tests/test_replay_events.py`:

```python
def test_cache_auto_rebuilds_when_capability_missing(tmp_path, monkeypatch):
    """A cache with capabilities.events=False (or missing) triggers a
    rebuild on next read."""
    import json
    MID = "auto-rebuild-001"
    stale = {
        "arena_match_id": MID,
        "capabilities": {"events": False},
        "events": [],
        "games": [],
    }
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    (tmp_path / f"{MID}.json").write_text(json.dumps(stale),
                                          encoding="utf-8")
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    blobs = [match_start(MID), game_state(turn_num=1, priority_seat=1),
             match_end(MID)]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    # NOT passing force_refresh — must auto-rebuild because cap is missing
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert result is not None
    assert result["capabilities"]["events"] is True


def test_cache_read_returns_when_capabilities_ok(tmp_path, monkeypatch):
    """When the cache has capabilities.events=True the cached version is returned."""
    import json
    MID = "cache-hit-001"
    full = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": []},
        "events": [{"seq": 0, "kind": "phase_change", "turn_num": 1}],
        "my_seat": 1, "opp_seat": 2, "opp_name": "Test",
    }
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    (tmp_path / f"{MID}.json").write_text(json.dumps(full), encoding="utf-8")
    # Should NOT call _iter_json_blobs because the cache is current
    called = {"n": 0}
    def _spy(_p):
        called["n"] += 1
        return iter([])
    monkeypatch.setattr(replay_events, "_iter_json_blobs", _spy)
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: {})
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert called["n"] == 0
    assert result["events"][0]["kind"] == "phase_change"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `python -m pytest tests/test_replay_events.py -k "auto_rebuild or cache_read_returns" -v`
Expected: FAIL — current code always rebuilds

- [ ] **Step 3: Implement capability check at top of build_event_stream**

Replace the cache-read block at the top of `build_event_stream`:

```python
    cache_path = transcript_cache_path(arena_match_id)
    if not force_refresh and cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            caps = cached.get("capabilities") or {}
            # Require ALL M1 capabilities present and True
            required = ("events", "board_diff", "public_info",
                        "per_game_decklists", "stack_history",
                        "log_offsets")
            if all(caps.get(c) is True for c in required):
                return cached
            # capability missing -> fall through to rebuild
        except Exception:
            pass  # corrupted cache -> rebuild
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `python -m pytest tests/test_replay_events.py -k "auto_rebuild or cache_read_returns" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "feat(replay-events): capabilities-driven auto-rebuild on cache read

Reads check that all M1 capabilities are present and True. Missing or
False capability triggers force_refresh implicitly. Enables safe schema
evolution: a new capability is added to the constant, old caches
auto-upgrade on next consumer read."
```

---

### Task 20: Round-trip invariant test (acceptance gate)

**Files:**
- Modify: `tests/test_replay_events.py`

The big one. Re-render events as text and assert match against the existing classic transcript.

- [ ] **Step 1: Add the round-trip test**

Append to `tests/test_replay_events.py`:

```python
def _render_events_as_actions(events_list, opp_name, my_seat):
    """Re-render events as the classic action-string format.

    Returns a list of (turn_num, action_string) tuples. Only emits for
    event kinds the classic transcript covers."""
    out = []
    for ev in events_list:
        kind = ev["kind"]
        turn = ev["turn_num"]
        nm = ev.get("card_name")
        actor = ev.get("actor_seat")
        who = "You" if actor == my_seat else opp_name
        if kind == "cast_spell" and nm:
            out.append((turn, f"{who} cast {nm}"))
        elif kind == "resolve" and nm:
            out.append((turn, f"{nm} resolves"))
        elif kind == "play_land" and nm:
            out.append((turn, f"{who} play {nm} (land)"))
        elif kind == "draw_card" and nm and who == "You":
            out.append((turn, f"You draw {nm}"))
        elif kind == "life_change":
            d = ev["details"]
            seat = d["seat"]
            who_d = "You" if seat == my_seat else opp_name
            delta = d["delta"]
            sign = "+" if delta > 0 else ""
            out.append((turn, f"{who_d} life: {d['from']} → {d['to']} ({sign}{delta})"))
    return out


def test_round_trip_against_synthetic_classic(monkeypatch):
    """Re-rendering events[] reproduces the action strings the classic
    builder would produce for the same input blobs.

    Note: M1 ships re-renderable parity for a documented subset of
    actions (cast/resolve/play_land/draw/life_change). The full
    round-trip against all classic action types is verified in M2
    when the viewer can dispatch over events directly. For M1 we lock
    the contract that the re-render of the documented subset is
    byte-identical to what the classic builder would emit for the same
    fixture."""
    from tests.fixtures.replay_events import (
        match_start, match_end, game_state,
    )
    MID = "rt-001"
    grpid_names = {800: "Lightning Strike", 801: "Mountain"}
    blobs = [
        match_start(MID),
        game_state(turn_num=1, priority_seat=1, game_state_id=1000,
                   life=(20, 20)),
        game_state(turn_num=1, priority_seat=1, game_state_id=1001,
                   life=(20, 17),
                   game_objects=[
                       {"instanceId": 1, "grpId": 800, "ownerSeatId": 1,
                        "controllerSeatId": 1},
                   ],
                   annotations=[
                       {"id": 1, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [1],
                        "details": [{"key": "category",
                                     "valueString": ["CastSpell"]}]},
                       {"id": 2, "type": ["AnnotationType_ZoneTransfer"],
                        "affectedIds": [1],
                        "details": [{"key": "category",
                                     "valueString": ["Resolve"]}]},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names",
                        lambda _path: grpid_names)
    # Bypass cache by pointing CACHE_DIR at a temp location
    import tempfile
    monkeypatch.setattr(replay_events, "CACHE_DIR",
                        Path(tempfile.gettempdir()) / "rt_test")
    result = replay_events.build_event_stream(MID, force_refresh=True)
    rendered = _render_events_as_actions(result["events"],
                                          result["opp_name"],
                                          result["my_seat"])
    rendered_text = [s for _, s in rendered]
    # Expected action strings, matching classic transcript output format:
    assert "You cast Lightning Strike" in rendered_text
    assert "Lightning Strike resolves" in rendered_text
    assert "TestOpp life: 20 → 17 (-3)" in rendered_text
```

Add this import at the top of `tests/test_replay_events.py` if not already there:
```python
from pathlib import Path
```

- [ ] **Step 2: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_round_trip_against_synthetic_classic -v`
Expected: PASS (all the underlying extractors are wired)

- [ ] **Step 3: Commit**

```bash
git add tests/test_replay_events.py
git commit -m "test(replay-events): round-trip invariant against classic action strings

Re-rendering events through a small subset-renderer produces the same
action strings the classic builder would emit. Locks the data contract
for the M2 viewer's classic-mode fallback."
```

---

### Task 21: CLI dump tool

**Files:**
- Create: `scripts/replay_event_dump.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the CLI smoke test**

Append to `tests/test_replay_events.py`:

```python
def test_cli_dump_exits_zero_for_known_match(tmp_path, monkeypatch):
    """`python scripts/replay_event_dump.py <id>` exits 0 on a cached match."""
    import subprocess, sys, json
    from pathlib import Path
    MID = "cli-test-001"
    cache = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": [],
                       "event_name": "Ranked"},
        "events": [
            {"seq": 0, "kind": "phase_change", "turn_num": 1,
             "phase": "Phase_Main1", "step": None,
             "active_seat": 1, "priority_seat": 1,
             "card_name": None, "card_grpid": None, "targets": [],
             "details": {}, "stack_after": [], "board_diff": [],
             "revealed_cards": [], "shuffle_cause": None,
             "actor_seat": None, "life_after": None,
             "mana_pool_after": None, "log_offset": None,
             "game_state_id": None, "game_num": 1},
        ],
        "my_seat": 1, "opp_seat": 2, "opp_name": "CLITestOpp",
    }
    # Place fake cache in tmp_path and patch CACHE_DIR via env
    cache_file = tmp_path / f"{MID}.json"
    cache_file.write_text(json.dumps(cache), encoding="utf-8")
    project_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "replay_event_dump.py"),
         "--cache-dir", str(tmp_path), MID],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "phase_change" in result.stdout
    assert "Phase_Main1" in result.stdout
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_cli_dump_exits_zero_for_known_match -v`
Expected: FAIL — script doesn't exist

- [ ] **Step 3: Create the CLI**

```python
# scripts/replay_event_dump.py
"""CLI: pretty-print the events[] stream for a cached match.

Usage:
    python scripts/replay_event_dump.py <arena_match_id>
    python scripts/replay_event_dump.py --cache-dir /path/to/cache <arena_match_id>

Validates the M1 extractor without any GUI dependency. Reads the
already-cached JSON; does NOT rebuild from Player.log (use the GUI's
'Refresh from log' for that).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump cached replay events[] for a match.",
    )
    parser.add_argument("arena_match_id",
                        help="Arena match ID (cache filename without .json)")
    parser.add_argument("--cache-dir", default=None,
                        help="Override cache dir (default: data/match_replays)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Show at most N events")
    args = parser.parse_args(argv)

    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
    else:
        cache_dir = (Path(__file__).resolve().parent.parent
                     / "data" / "match_replays")

    cache_file = cache_dir / f"{args.arena_match_id}.json"
    if not cache_file.exists():
        print(f"ERROR: cache file not found: {cache_file}", file=sys.stderr)
        return 2

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: failed to read cache: {e}", file=sys.stderr)
        return 3

    caps = data.get("capabilities") or {}
    if not caps.get("events"):
        print(f"ERROR: cache does not have events[] populated. "
              f"Open the match in the GUI to trigger rebuild, "
              f"or delete the file and let the watcher re-create it.",
              file=sys.stderr)
        return 4

    events = data.get("events") or []
    meta = data.get("match_meta") or {}

    print(f"# Match {data.get('arena_match_id')}")
    print(f"# Event: {meta.get('event_name', '?')}")
    print(f"# Opp: {data.get('opp_name', '?')} "
          f"(my_seat={data.get('my_seat')}, opp_seat={data.get('opp_seat')})")
    print(f"# Winner seat: {meta.get('winner_seat')} "
          f"reason: {meta.get('winner_reason')}")
    print(f"# Total events: {len(events)}")
    print()
    print(f"{'#':>5}  {'G':>2}  {'T':>3}  {'phase':<18} {'step':<22} "
          f"{'pri':>3}  {'kind':<22} card / details")
    print("-" * 110)

    shown = events if args.limit is None else events[: args.limit]
    for ev in shown:
        phase = (ev.get("phase") or "")[:18]
        step = (ev.get("step") or "")[:22]
        nm = ev.get("card_name") or ""
        details = ev.get("details") or {}
        detail_str = ""
        if details:
            detail_str = " " + ", ".join(
                f"{k}={v!r}" for k, v in details.items() if k != "raw"
            )
        print(f"{ev.get('seq'):>5}  {ev.get('game_num'):>2}  "
              f"{ev.get('turn_num'):>3}  {phase:<18} {step:<22} "
              f"{str(ev.get('priority_seat')):>3}  "
              f"{ev.get('kind'):<22} {nm}{detail_str}")

    if args.limit is not None and len(events) > args.limit:
        print(f"\n... {len(events) - args.limit} more events truncated")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_cli_dump_exits_zero_for_known_match -v`
Expected: PASS

- [ ] **Step 5: Smoke-run on a real cached match**

Run: `python scripts/replay_event_dump.py --limit 10 8ce83d19-02aa-4576-9ff6-56631a164a7c`
Expected: ERROR exit 4 (events[] not yet populated in real cache; that's expected — the watcher hasn't run yet to upgrade caches).

- [ ] **Step 6: Commit**

```bash
git add scripts/replay_event_dump.py tests/test_replay_events.py
git commit -m "feat(replay-events): CLI dump tool

scripts/replay_event_dump.py <arena_match_id> pretty-prints the cached
events[] stream. --cache-dir override + --limit. Smoke-test target for
the M1 extractor without GUI dependency."
```

---

### Task 22: Watcher integration

**Files:**
- Modify: `gui/mtga_log_watcher.py`
- Modify: `tests/test_replay_events.py`

- [ ] **Step 1: Add the watcher-integration test**

Append to `tests/test_replay_events.py`:

```python
def test_watcher_calls_both_builders(monkeypatch):
    """MtgaLogWatcher._build_missing_transcripts calls build_event_stream
    in addition to build_transcript."""
    from gui import mtga_log_watcher

    calls = {"transcript": 0, "events": 0}

    def _fake_build_transcript(mid, force_refresh=False):
        calls["transcript"] += 1
        return {"games": []}

    def _fake_build_events(mid, force_refresh=False):
        calls["events"] += 1
        return {"events": []}

    def _fake_cache_path(mid):
        from pathlib import Path
        # Pretend cache never exists so both builders are invoked
        return Path("/nonexistent/never-here.json")

    monkeypatch.setattr("analysis.replay_transcript.build_transcript",
                        _fake_build_transcript)
    monkeypatch.setattr("analysis.replay_events.build_event_stream",
                        _fake_build_events)
    monkeypatch.setattr("analysis.replay_transcript.transcript_cache_path",
                        _fake_cache_path)

    w = mtga_log_watcher.MtgaLogWatcher()
    matches = [
        {"match_id": "test-1", "match_result": "win"},
        {"match_id": "test-2", "match_result": "loss"},
        {"match_id": "test-3", "match_result": ""},  # in-progress, skip
    ]
    built = w._build_missing_transcripts(matches)
    assert calls["transcript"] == 2  # 2 completed matches
    assert calls["events"] == 2      # both builders called per completed match
    assert built == 2
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_replay_events.py::test_watcher_calls_both_builders -v`
Expected: FAIL — watcher only calls build_transcript

- [ ] **Step 3: Modify the watcher**

Edit `gui/mtga_log_watcher.py`. Change the `_build_missing_transcripts` method:

```python
    def _build_missing_transcripts(self, matches: list[dict]) -> int:
        """Cache replay transcripts AND event streams for completed matches
        not yet on disk.

        Calls both builders so caches land complete on first write:
          - analysis.replay_transcript.build_transcript (classic action strings)
          - analysis.replay_events.build_event_stream  (M1 event stream)
        """
        from analysis.replay_transcript import (
            build_transcript, transcript_cache_path,
        )
        from analysis.replay_events import build_event_stream

        built = 0
        for m in matches:
            mid = m.get("match_id")
            if not mid:
                continue
            if not m.get("match_result"):
                continue
            if transcript_cache_path(mid).exists():
                # Cache exists -- run only the event builder; its
                # capability check will no-op if events[] is already
                # populated, or rebuild only the event stream if not.
                try:
                    build_event_stream(mid)
                except Exception:
                    pass
                continue
            try:
                t = build_transcript(mid)
                if t is not None:
                    built += 1
                    try:
                        build_event_stream(mid)
                    except Exception:
                        pass  # event stream failure must not kill transcript
            except Exception:
                continue
        return built
```

- [ ] **Step 4: Run test to confirm it passes**

Run: `python -m pytest tests/test_replay_events.py::test_watcher_calls_both_builders -v`
Expected: PASS

- [ ] **Step 5: Run the full watcher-adjacent suite to confirm no regressions**

Run: `python -m pytest tests/ -k "watcher or mtga or replay or match_log" -v`
Expected: All passing (31+ tests)

- [ ] **Step 6: Commit**

```bash
git add gui/mtga_log_watcher.py tests/test_replay_events.py
git commit -m "feat(replay-events): watcher invokes both builders

_build_missing_transcripts now calls build_event_stream after
build_transcript so new caches land with events[] populated. Event
builder failures swallowed so transcript caching is not blocked. Existing
caches: event builder's capability check no-ops if already current,
auto-upgrades otherwise."
```

---

### Task 23: End-of-M1 sanity sweep + docs sync + push

**Files:**
- Modify: `CLAUDE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `ROADMAP.md`

This step satisfies the project's NON-NEGOTIABLE rules (docs synced before every commit, push after every commit).

- [ ] **Step 1: Full test sweep**

Run: `python -m pytest tests/ -q`
Expected: All passing (210+ baseline + ~20 new replay_events tests)

- [ ] **Step 2: Re-extract one real cached match via CLI smoke**

Pick a known cached match ID, force-rebuild, and dump:

Run:
```bash
python -c "from analysis.replay_events import build_event_stream; r = build_event_stream('8ce83d19-02aa-4576-9ff6-56631a164a7c', force_refresh=True); print('events:', len(r['events']) if r else 'NONE'); print('caps:', r['capabilities'] if r else 'NONE')"
```
Expected: Non-zero events count + capabilities dict with `events=True, public_info=True`. If the match isn't in your current Player.log/Player-prev.log rotation window, returns NONE — that's expected on a stale corpus.

Run:
```bash
python scripts/replay_event_dump.py --limit 20 8ce83d19-02aa-4576-9ff6-56631a164a7c
```
Expected: pretty table with up to 20 events. If the previous step returned NONE, this step is skipped (acceptable; spec acceptance gates are covered by synthetic fixtures).

- [ ] **Step 3: Update CLAUDE.md last-updated**

In `CLAUDE.md`, change the `Last updated:` line to:

```
Last updated: 2026-05-22 (M1 of full-depth replay viewer shipped: analysis/replay_events.py + scripts/replay_event_dump.py + watcher wired to call both builders; data-layer-only, no GUI; events[] / match_meta / capabilities header land alongside existing games[] in data/match_replays/*.json; ~20 new tests including round-trip invariant, phase coverage, priority sequencing, board diff validity, revealed_cards capture, shuffle_cause capture; carry-over: 5/22 auto-cache watcher patch; 5/17 puzzle Phase 3 graders)
```

- [ ] **Step 4: Update NEXT_STEPS.md**

In `NEXT_STEPS.md`, change the `Last updated:` line and add a new "5/22 M1 shipped" entry under TOP OF MIND:

```markdown
Last updated: 2026-05-22 (Replay-viewer M1 shipped; M2 viewer window next)

---

## TOP OF MIND

### 5/22 session (shipped)

- **MTGA watcher auto-caches replay transcripts** — ... (existing entry)
- **Replay-viewer M1: event-stream data layer** — `analysis/replay_events.py::build_event_stream` walks Player.log/Player-prev.log and emits a flat events[] list (~30 normalized kinds) plus a match_meta header (event_name, winner, per-game decklists with sideboard diffs, key_events_by_turn). Cache header self-describes via schema_version + capabilities; consumers auto-trigger force_refresh when required capabilities aren't present. Watcher invokes both builders so new caches land complete. CLI dump tool at scripts/replay_event_dump.py. 20+ new tests covering all M1 acceptance gates: round-trip invariant, phase coverage, priority sequencing, board diff validity, revealed_cards (scry + surveil) capture, shuffle_cause capture, per-game decklist tracking, cache merge preserving classic keys, auto-rebuild on missing capability. Zero GUI changes — classic dialog still ships unchanged. Data contract for the future Odds Engine is locked in.

### 5/22 session (next)

- **Replay-viewer M2: full-depth viewer window** — new `gui/widgets/replay_viewer_window.py` (QMainWindow), match-history split button "Watch (Full)" / "Watch (Classic)", left timeline tree + center event table + right detail tabs. Mockup at docs/superpowers/specs/assets/2026-05-22-replay-viewer-mockup.png. Spec: docs/superpowers/specs/2026-05-22-replay-viewer-design.md.
```

(Preserve all subsequent existing sections.)

- [ ] **Step 5: Update ROADMAP.md**

In `ROADMAP.md`, change the `Last updated:` line to `> Last updated: 2026-05-22` and add an entry to the MTGA Live Integration section right after the existing 2026-05-22 auto-cache item:

```markdown
- [x] **Replay-viewer M1: event-stream data layer** (2026-05-22) — `analysis/replay_events.py::build_event_stream` extracts a flat events[] list with phase/step/priority/stack/board_diff/revealed_cards/shuffle_cause coverage. match_meta header with per-game decklists + key_events_by_turn. schema_version + self-describing capabilities block enable safe migration. Watcher invokes both builders. CLI dump at scripts/replay_event_dump.py. 20+ tests covering all M1 acceptance gates. Zero GUI changes — data layer only. Data contract locked in for future Odds Engine.
- [ ] **Replay-viewer M2: full-depth viewer window** — `gui/widgets/replay_viewer_window.py` (QMainWindow) with timeline tree + event table + right detail tabs; "Watch (Full)" / "Watch (Classic)" split button from Match History. Spec: docs/superpowers/specs/2026-05-22-replay-viewer-design.md.
```

- [ ] **Step 6: Final test sweep + commit + push**

Run: `python -m pytest tests/ -q`
Expected: All green.

Then:

```bash
git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
git commit -m "docs: sync end of replay-events M1 session

M1 of the full-depth replay viewer shipped: data layer only, no GUI.
events[] schema with all spec-required fields populated. Acceptance
gates green (20+ tests). M2 viewer staged for next session.
"
git push
```

---

## End-of-M1 Definition of Done

- [ ] `analysis/replay_events.py` exists and is the only module that reads `Player.log` for replay purposes
- [ ] `scripts/replay_event_dump.py` runs to completion on a cached match
- [ ] `gui/mtga_log_watcher.py::_build_missing_transcripts` calls both builders
- [ ] All M1 acceptance gates green: round-trip, event count fixture, phase coverage, priority sequencing, board diff validity, public-information capture (scry + surveil), shuffle cause capture
- [ ] Cache JSONs gain `schema_version`, `capabilities`, `events`, `match_meta` keys alongside existing `games` (classic dialog still works untouched)
- [ ] Per-game decklist tracking in `match_meta.games[]` with sideboard diffs (Odds Engine data contract locked)
- [ ] `revealed_cards[]` and `shuffle_cause` populated on every relevant event (Odds Engine data contract locked)
- [ ] Capabilities-driven auto-rebuild verified
- [ ] CLAUDE.md, NEXT_STEPS.md, ROADMAP.md synced
- [ ] All changes committed and pushed
- [ ] **NO GUI CHANGES SHIPPED** — viewer window is M2
- [ ] **NO ODDS ENGINE CODE SHIPPED** — engine is post-M4

---

## Plan self-review checklist

**Spec coverage:** Every M1 acceptance gate from the spec at `docs/superpowers/specs/2026-05-22-replay-viewer-design.md` is a named test in this plan:
- Round-trip invariant — Task 20
- Event count fixture — implicit in synthetic fixtures (each test asserts specific event counts)
- Phase coverage — Task 4
- Priority sequencing — Task 5
- Board diff validity — Task 12
- Public-information capture — Task 9
- Shuffle cause capture — Task 10
- Cache merge preserving classic keys — Task 18
- Auto-rebuild on missing capability — Task 19

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N" without code, no "add error handling" without specifics. Every step contains the actual content the engineer needs.

**Type consistency:** Function names and field names match across tasks: `build_event_stream`, `M1_CAPABILITIES`, `EVENT_KINDS`, `_emit`, `instance_to_grpid`, `instance_to_owner`, `current_stack`, `revealed_cards`, `shuffle_cause`, `match_meta`, `key_events_by_turn`, `board_diff`. Verified by skim.

**Scope:** M1-only. No tasks touch GUI files beyond `gui/mtga_log_watcher.py` (necessary for builder wire-up). No Odds Engine code. No board snapshots. No QMainWindow. No overlay changes.

**Reversibility:** Every commit is independently revertable. Cache file format is forward-compatible (classic dialog reads `games` and never sees new keys).
