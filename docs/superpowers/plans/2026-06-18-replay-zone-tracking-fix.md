# Replay Zone-Tracking Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `replay_board_at` report accurate Hand / Library / Graveyard / Exile / Battlefield counts at every event by fixing how `build_event_stream` reconciles MTGA zone snapshots, then surface those counts in the replay board panel.

**Architecture:** MTGA emits mostly `GameStateType_Diff` GameStateMessages (measured 1395 Diff : 5 Full in a real log) whose `zones[]` contains ONLY the zones that changed — each with that zone's COMPLETE membership and a stable `zoneId`. The current code treats every message's `zones[]` as a full snapshot and evicts any tracked instance not re-listed, so any zone a diff omits gets wiped (~50k spurious evictions per match). Fix: extract a pure, Diff-aware `reconcile_zones()` helper that reconciles membership **per `zoneId`, only for zones present in the message**, leaving omitted zones untouched, and evicting an instance only when its recorded zone IS present but the instance is absent from all present zones (so a library→hand draw reads as a MOVE, not evict-then-readd). The `board_diff` entry shape is unchanged — only its population logic changes — so the M1 data contract is preserved. Bump `SCHEMA_VERSION` 2→3 + add a `zone_counts` capability so stale caches rebuild.

**Tech Stack:** Python 3.13, pytest. Pure logic in `analysis/replay_events.py` (Qt-free); UI in `gui/widgets/replay_board_panel.py` (PyQt6).

---

## Background / Evidence (confirmed during investigation)

- Raw log `GameStateType_Diff` : `GameStateType_Full` = **1395 : 5**.
- Diff messages include only changed zones (across 1368 diffs: Battlefield in 96, Graveyard 38, Exile 20, Hand 159, Library 79). A zone present in a diff carries its FULL membership (sample: Hand ids=7, Library ids=53 for a 60-card deck → 7 + 53 = 60).
- Zone objects carry stable identity: `zoneId` (28=shared battlefield, 31=P1 hand, 35=P2 hand, 33=P1 graveyard, 37=P2 graveyard) + `ownerSeatId`. Two copies of each owned zone (one per seat) — so reconciling by zone *name* is ambiguous; reconcile by `zoneId`.
- Clean schema-2 repro: `replay_board_at` returns all-zero zone counts at every mid-game seq (match `d2a2b506-4da6-4e01-9621-3a702204cf95`, 624 events, 2 games).
- `instance_to_zone` (name-based) is used ONLY in the reconciliation block (`analysis/replay_events.py:145,331-350`) — safe to replace with `zoneId`-based tracking.

## File Structure

- `analysis/replay_events.py` — add pure `reconcile_zones()` near the other module-level helpers; replace the inline reconciliation block (~322-362) with a call to it; drop `instance_to_zone`, add `instance_to_zoneid` + `zoneid_to_name`; bump `SCHEMA_VERSION`; add `zone_counts` capability.
- `tests/test_replay_zone_reconcile.py` — NEW. Unit tests for `reconcile_zones()` against synthetic Full/Diff GSM dicts.
- `gui/widgets/replay_board_panel.py` — show Hand/Lib/GY/Exile counts in the per-seat header (lines ~92-104).
- `tests/test_replay_board_panel.py` — assert the new header content (if the panel header is tested).
- `tests/test_replay_events.py` — verify/repair the board-diff round-trip test (eviction volume collapses ~50k→near-zero).

---

### Task 1: Pure `reconcile_zones()` helper (Diff-aware, zoneId-based)

**Files:**
- Create: `tests/test_replay_zone_reconcile.py`
- Modify: `analysis/replay_events.py` (add helper near `_ZONE_TYPE_TO_NAME`, ~line 61-70)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replay_zone_reconcile.py
"""Tests for analysis.replay_events.reconcile_zones (headless, no Qt).

Exercises the raw zone-reconciliation logic against synthetic MTGA
GameStateMessage dicts. The core bug: Diff messages list only changed zones,
so reconciliation must touch ONLY zones present in the message.
"""
from analysis.replay_events import reconcile_zones

# MTGA zoneIds (stable within a game): 28 shared battlefield, 31/35 hands,
# 33/37 graveyards, 40/41 libraries.
def _zone(ztype, zoneid, ids, owner=None):
    z = {"type": ztype, "zoneId": zoneid, "objectInstanceIds": list(ids)}
    if owner is not None:
        z["ownerSeatId"] = owner
    return z

def _gsm(*zones):
    return {"zones": list(zones)}

def _fresh_state():
    # (instance_to_zoneid, zoneid_to_name) accumulate across messages.
    return {}, {}

# Common enrichment maps; owners make controller resolve to you/opp.
GRPIDS = {}            # iid -> grpid (unknown for face-down lib cards)
OWNERS = {}            # iid -> seat
NAMES = {}             # grpid -> name
MY, OPP = 1, 2

def _reconcile(gsm, i2z, z2n):
    return reconcile_zones(
        gsm, instance_to_zoneid=i2z, zoneid_to_name=z2n,
        instance_to_grpid=GRPIDS, instance_to_owner=OWNERS,
        grpid_names=NAMES, my_seat=MY, opp_seat=OPP,
    )

def test_full_message_establishes_membership():
    i2z, z2n = _fresh_state()
    full = _gsm(
        _zone("ZoneType_Hand", 31, [1, 2, 3, 4, 5, 6, 7], owner=1),
        _zone("ZoneType_Library", 40, list(range(100, 153)), owner=1),  # 53 ids
    )
    diffs = _reconcile(full, i2z, z2n)
    # 7 hand + 53 library = 60 enters; all from None
    assert sum(1 for d in diffs if d["to"] == "hand") == 7
    assert sum(1 for d in diffs if d["to"] == "library") == 53
    assert all(d["from"] is None for d in diffs)

def test_diff_omitting_a_zone_does_not_evict_it():
    # Bug repro: after a Full establishes hand+library, a battlefield-only Diff
    # must NOT evict the hand/library instances.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 2, 3], owner=1),
        _zone("ZoneType_Library", 40, [100, 101, 102], owner=1),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(
        _zone("ZoneType_Battlefield", 28, [99]),
    ), i2z, z2n)
    # only the battlefield enter; NO evictions of hand/library
    assert [d for d in diffs if d["to"] is None] == []
    assert any(d["to"] == "battlefield" and d["instance_id"] == 99 for d in diffs)
    # hand/library instances still tracked
    assert i2z[1] == 31 and i2z[100] == 40

def test_draw_reads_as_move_not_evict_then_readd():
    # Card 100 moves library(40) -> hand(31). Both zones present in the diff.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1], owner=1),
        _zone("ZoneType_Library", 40, [100, 101], owner=1),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 100], owner=1),
        _zone("ZoneType_Library", 40, [101], owner=1),
    ), i2z, z2n)
    moves = [d for d in diffs if d["instance_id"] == 100]
    assert len(moves) == 1
    assert moves[0]["from"] == "library" and moves[0]["to"] == "hand"
    assert [d for d in diffs if d["to"] is None] == []  # no spurious eviction
    assert i2z[100] == 31

def test_eviction_when_present_zone_loses_instance_to_unlisted_zone():
    # Card leaves hand(31) and its destination zone is NOT in the message.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1, 2], owner=1)), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1], owner=1)), i2z, z2n)
    ev = [d for d in diffs if d["to"] is None]
    assert len(ev) == 1 and ev[0]["instance_id"] == 2 and ev[0]["from"] == "hand"
    assert 2 not in i2z

def test_two_seats_same_zone_name_are_independent():
    # P1 hand (31) and P2 hand (35) share the name "hand" but distinct zoneIds.
    # A diff updating only P1's hand must not evict P2's hand.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(
        _zone("ZoneType_Hand", 31, [1, 2], owner=1),
        _zone("ZoneType_Hand", 35, [8, 9], owner=2),
    ), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1], owner=1)), i2z, z2n)
    ev = [d["instance_id"] for d in diffs if d["to"] is None]
    assert ev == [2]            # only P1's discard
    assert i2z[8] == 35 and i2z[9] == 35  # P2 hand untouched

def test_game2_full_resyncs_membership():
    # A later Full (game 2) re-lists the same zoneIds; stale game-1 instances in
    # those present zones get evicted, new ones enter.
    i2z, z2n = _fresh_state()
    _reconcile(_gsm(_zone("ZoneType_Hand", 31, [1, 2, 3], owner=1)), i2z, z2n)
    diffs = _reconcile(_gsm(_zone("ZoneType_Hand", 31, [50, 51], owner=1)), i2z, z2n)
    evicted = sorted(d["instance_id"] for d in diffs if d["to"] is None)
    entered = sorted(d["instance_id"] for d in diffs if d["to"] == "hand")
    assert evicted == [1, 2, 3]
    assert entered == [50, 51]

def test_unmapped_zones_ignored():
    # Limbo/Stack/etc. are not battlefield/hand/library/graveyard/exile.
    i2z, z2n = _fresh_state()
    diffs = _reconcile(_gsm(_zone("ZoneType_Limbo", 99, [1, 2])), i2z, z2n)
    assert diffs == []
    assert i2z == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_replay_zone_reconcile.py -q`
Expected: FAIL — `ImportError: cannot import name 'reconcile_zones'`.

- [ ] **Step 3: Implement `reconcile_zones()`**

Add to `analysis/replay_events.py` just below `_ZONE_TYPE_TO_NAME` (~line 70):

```python
def reconcile_zones(gsm: dict, *,
                    instance_to_zoneid: dict[int, int],
                    zoneid_to_name: dict[int, str],
                    instance_to_grpid: dict[int, int],
                    instance_to_owner: dict[int, int],
                    grpid_names: dict[int, str],
                    my_seat, opp_seat) -> list[dict]:
    """Compute board_diff entries for one GameStateMessage.

    MTGA sends mostly GameStateType_Diff messages whose ``zones[]`` lists only
    the zones that changed -- each with that zone's COMPLETE membership and a
    stable ``zoneId``. So we reconcile per zoneId: zones present in this message
    are recomputed; zones absent are left untouched. An instance is evicted
    (``to`` = None) only when the zone it was recorded in IS present in this
    message yet the instance is absent from ALL present zones (it left to an
    un-listed zone). Membership across all present zones is computed first, so a
    library->hand draw reads as a MOVE, not evict-then-readd.

    Mutates ``instance_to_zoneid`` and ``zoneid_to_name`` in place. Returns diff
    dicts with the existing board_diff shape:
    {instance_id, card, grpid, from, to, controller}.
    """
    # 1. Membership across all mapped zones present in THIS message.
    present_zoneids: dict[int, str] = {}
    current_membership: dict[int, int] = {}   # iid -> zoneId
    for zone in gsm.get("zones", []) or []:
        name = _ZONE_TYPE_TO_NAME.get(zone.get("type"))
        if not name:
            continue
        zid = zone.get("zoneId")
        if zid is None:
            continue
        present_zoneids[zid] = name
        zoneid_to_name[zid] = name
        for iid in zone.get("objectInstanceIds", []) or []:
            current_membership[iid] = zid

    def _mk(iid, from_zid, to_zid):
        grp = instance_to_grpid.get(iid)
        owner = instance_to_owner.get(iid)
        return {
            "instance_id": iid,
            "card": grpid_names.get(grp) if grp else None,
            "grpid": grp,
            "from": zoneid_to_name.get(from_zid) if from_zid is not None else None,
            "to": present_zoneids.get(to_zid) if to_zid is not None else None,
            "controller": ("you" if owner == my_seat
                           else "opp" if owner == opp_seat else None),
        }

    diffs: list[dict] = []
    # 2. Enters / moves: instance's current zoneId differs from recorded.
    for iid, zid in current_membership.items():
        old_zid = instance_to_zoneid.get(iid)
        if old_zid != zid:
            diffs.append(_mk(iid, old_zid, zid))
            instance_to_zoneid[iid] = zid
    # 3. Evictions: recorded in a PRESENT zone but absent from all present zones.
    for iid, old_zid in list(instance_to_zoneid.items()):
        if old_zid in present_zoneids and iid not in current_membership:
            diffs.append(_mk(iid, old_zid, None))
            del instance_to_zoneid[iid]
    return diffs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_replay_zone_reconcile.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_replay_zone_reconcile.py analysis/replay_events.py
git commit -m "feat(replay): add Diff-aware per-zoneId reconcile_zones helper"
```

---

### Task 2: Wire `reconcile_zones()` into `build_event_stream` + bump schema

**Files:**
- Modify: `analysis/replay_events.py` (decl ~145; reconciliation block ~322-362; `SCHEMA_VERSION` line 44; `M1_CAPABILITIES` 74-83; `required` tuple 100-102)

- [ ] **Step 1: Swap the tracking state declaration**

In `build_event_stream` replace line ~145:

```python
    instance_to_zone: dict[int, str] = {}
```
with:
```python
    instance_to_zoneid: dict[int, int] = {}
    zoneid_to_name: dict[int, str] = {}
```

- [ ] **Step 2: Replace the inline reconciliation block**

Replace the whole block from `# Build current zone snapshot from zones[]` through `pending_zone_diffs = zone_diffs` (~lines 322-362) with:

```python
                    # Diff-aware zone reconciliation (per zoneId). MTGA sends
                    # mostly partial GameStateType_Diff messages; only zones
                    # present here are recomputed -- see reconcile_zones.
                    pending_zone_diffs = reconcile_zones(
                        gsm,
                        instance_to_zoneid=instance_to_zoneid,
                        zoneid_to_name=zoneid_to_name,
                        instance_to_grpid=instance_to_grpid,
                        instance_to_owner=instance_to_owner,
                        grpid_names=grpid_names,
                        my_seat=my_seat, opp_seat=opp_seat,
                    )
```

- [ ] **Step 3: Bump schema + add capability**

Line 44:
```python
SCHEMA_VERSION = 3  # 3: Diff-aware per-zoneId zone reconciliation (accurate zone counts)
```
In `M1_CAPABILITIES` (after `"log_offsets": True,`):
```python
    "zone_counts": True,
```
In the `required` tuple in the cache-load guard (~lines 100-102), add `"zone_counts"`:
```python
            required = ("events", "board_diff", "public_info",
                        "per_game_decklists", "stack_history",
                        "log_offsets", "zone_counts")
```

- [ ] **Step 4: Run the full replay test suite**

Run: `python -m pytest tests/ -q -k replay`
Expected: PASS. If `tests/test_replay_events.py` has a board-diff round-trip / eviction assertion that now changes (eviction volume collapses ~50k→near-zero), update it to assert the corrected behavior (no mass `to: None` on partial messages). Show the change in the commit.

- [ ] **Step 5: Real-data verification (manual checkpoint — not a committed test)**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from analysis.replay_events import build_event_stream, replay_board_at
d = build_event_stream('d2a2b506-4da6-4e01-9621-3a702204cf95', force_refresh=True)
evs = d['events']; maxseq = max(e.get('seq',0) for e in evs)
for frac in (0.3,0.5,0.7,0.9):
    s=int(maxseq*frac); b=replay_board_at(evs,s); y,o=b['you'],b['opp']
    print(f'seq~{s}: YOU bf={len(y[\"battlefield\"])} hand={y[\"hand_count\"]} lib={y[\"library_count\"]} gy={y[\"graveyard_count\"]} | OPP bf={len(o[\"battlefield\"])} hand={o[\"hand_count\"]} lib={o[\"library_count\"]}')
b0 = replay_board_at(evs, 0)
print('OPENING you hand/lib =', b0['you']['hand_count'], b0['you']['library_count'])
"
```
Expected: nonzero, sane counts (hand ~5-7, library decreasing from ~53, battlefield grows). Opening hand+library should sum to ~60 for the owner. NOTE: this rebuilds the cache at schema 3 (the stale schema-2 cache is overwritten — confirms cache invalidation works).

- [ ] **Step 6: Run the WHOLE suite**

Run: `python -m pytest -q`
Expected: all green (was 355).

- [ ] **Step 7: Commit**

```bash
git add analysis/replay_events.py tests/test_replay_events.py
git commit -m "fix(replay): Diff-aware zone reconciliation; bump SCHEMA_VERSION 3 + zone_counts cap"
```

---

### Task 3: Surface zone counts in the board panel

**Files:**
- Modify: `gui/widgets/replay_board_panel.py` (header block ~92-104)
- Modify: `tests/test_replay_board_panel.py` (if it asserts header text)

- [ ] **Step 1: Check whether the panel header is tested**

Run: `python -m pytest tests/test_replay_board_panel.py -q`
Read the test to see if it asserts the header string. If it does, update the expectation in Step 3's test edit; if not, skip the test edit.

- [ ] **Step 2: Update the header to include zone counts**

Replace lines ~92-104 (the comment + `header = (...)` block) with:

```python
            # Zone counts now reliable (schema 3 Diff-aware reconciliation).
            bf_n = len(seat_board.get("battlefield") or [])
            hand_n = seat_board.get("hand_count", 0)
            lib_n = seat_board.get("library_count", 0)
            gy_n = seat_board.get("graveyard_count", 0)
            ex_n = seat_board.get("exile_count", 0)
            header = (
                f"{'You' if seat == 'you' else 'Opp'}  "
                f"Life {life_v if life_v is not None else '?'}  "
                f"Mana {mana_v or '-'}  "
                f"Hand {hand_n}  Lib {lib_n}  "
                f"GY {gy_n}  Exile {ex_n}  Battlefield {bf_n}"
            )
```

- [ ] **Step 3: Add/adjust a header assertion test**

If `tests/test_replay_board_panel.py` builds the panel, add (or update) a test asserting the header contains the new fields. Example (adapt to the file's existing fixture style):

```python
def test_header_shows_zone_counts(qtbot):
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    panel = ReplayBoardPanel(); qtbot.addWidget(panel)
    board = {"you": {"battlefield": [{"name": "x", "instance_id": 1, "grpid": 1}],
                     "hand_count": 5, "library_count": 48,
                     "graveyard_count": 2, "exile_count": 0},
             "opp": {"battlefield": [], "hand_count": 6, "library_count": 50,
                     "graveyard_count": 1, "exile_count": 0}}
    panel.update_board({"board_diff": []}, board, {"you": 20, "opp": 18}, {"you": "", "opp": ""}, False)
    assert "Hand 5" in panel._header_txt["you"]
    assert "Lib 48" in panel._header_txt["you"]
    assert "GY 2" in panel._header_txt["you"]
```

(Confirm the exact `update_board`/render method name + signature from the file before writing — adjust accordingly.)

- [ ] **Step 4: Run the panel tests + whole suite**

Run: `python -m pytest tests/test_replay_board_panel.py -q && python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add gui/widgets/replay_board_panel.py tests/test_replay_board_panel.py
git commit -m "feat(replay): show Hand/Lib/GY/Exile counts in board panel header"
```

---

### Task 4: Docs + push

**Files:**
- Modify: `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md`

- [ ] **Step 1: Update CLAUDE.md** — add a dated note: zone-tracking fixed via Diff-aware per-zoneId reconciliation in `reconcile_zones`; `SCHEMA_VERSION` 3 + `zone_counts` capability auto-rebuilds caches; board panel now shows all zone counts. Mention the remaining deferred items (tap/counters/auras still not in the data contract).

- [ ] **Step 2: Update NEXT_STEPS.md** — mark the "sparse hand/lib/GY/exile zone tracking" item RESOLVED (was the last open half of the M1 data-quality fix). Note the manual GUI smoke now also covers visible zone counts.

- [ ] **Step 3: Update ROADMAP.md** — check off the zone-count fix under the replay-viewer / data-quality section.

- [ ] **Step 4: Commit + push (scrub local paths / the user's first name per the pre-push hook)**

```bash
git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
git commit -m "docs: replay zone-tracking fix (Diff-aware reconciliation, schema 3)"
git push
```

- [ ] **Step 5: Confirm CI green** — `gh run list --limit 2` → both workflows success on the new HEAD.

---

## Self-Review Notes

- **Spec coverage:** root cause (Diff-as-Full) → Task 1+2; schema/cache invalidation → Task 2 Step 3+5; fix reaches UI → Task 3; exact-count oracle → Task 1 `test_full_message_establishes_membership` (7/53) + Task 2 Step 5; durable fixture (no live log dependency) → Task 1 synthetic GSMs; game-2 coverage → Task 1 `test_game2_full_resyncs_membership` + Task 2 Step 5 (the repro match has 2 games); membership-then-evict invariant → `reconcile_zones` step order + `test_draw_reads_as_move_not_evict_then_readd`.
- **Deferred (NOT in this plan):** tap-state, +1/+1 counters, attached auras, combat highlighting — still absent from the `events[]`/`board_diff` data contract; a separate extractor extension.
- **Risk:** if `tests/test_replay_events.py` asserts exact eviction/diff counts on a real cached fixture, those numbers change — update to assert corrected behavior (Task 2 Step 4).
