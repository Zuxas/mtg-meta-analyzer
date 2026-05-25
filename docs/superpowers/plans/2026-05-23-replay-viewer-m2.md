# Replay Viewer M2 — Full-Depth Viewer Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `gui/widgets/replay_viewer_window.py` — a full-depth interactive `QMainWindow` that steps through any cached match at event-level granularity (timeline tree + lazy event table + right detail tabs + card preview), opened from Match History via a split "Watch (Full)" / "Watch (Classic)" button.

**Architecture:** Two new modules. `gui/replay_view_model.py` is **Qt-free** pure functions that shape the M1 `events[]` / `match_meta` dicts into display structures (timeline tree, event summaries, kind filtering, navigation, jump-to targets, detail/stack rows). It carries all the testable logic. `gui/widgets/replay_viewer_window.py` is a thin `QMainWindow` that composes a custom `QAbstractTableModel` over those helpers. The window consumes the already-shipped M1 cache via `analysis.replay_events.build_event_stream` and never re-parses logs (Source-of-Truth Hierarchy: UI → analytics → events → raw blobs, downward only).

**Tech Stack:** Python 3.13, PyQt6 (QMainWindow, QAbstractTableModel, QSortFilterProxyModel, QTreeWidget, QToolButton), pytest with `QT_QPA_PLATFORM=offscreen`. Card images via existing `gui/widgets/card_image_cache.py`. State via existing `gui/state.py::UIState`.

---

## Context the executor needs

**M1 already shipped** (`analysis/replay_events.py`). Each event in `events[]` has this real shape (verified against the live extractor — not the idealized spec):

```python
{
  "seq": 312, "game_state_id": 1234, "game_num": 1, "turn_num": 7,
  "phase": "Phase_Main1",      # raw enum; None on the very first events
  "step": None,                 # ONLY non-None for Beginning/Combat phases
  "active_seat": 1, "priority_seat": 2, "actor_seat": 2,
  "kind": "cast_spell",         # one of analysis.replay_events.EVENT_KINDS
  "card_name": "Lightning Strike", "card_grpid": 70404,
  "targets": [{"name": "Make Disappear", "grpid": 81234, "kind": "spell_or_permanent"}],
  "details": {"category": "CastSpell"},
  "life_after": {"you": 8, "opp": 14},   # can be None on early events
  "mana_pool_after": {"you": "{R}", "opp": ""},  # can be None
  "stack_after": [{"name": "Lightning Strike", "controller": "you", "targets": []}],  # can be [] 
  "board_diff": [{"instance_id": 5, "card": "...", "grpid": 1, "from": "hand", "to": "stack", "controller": "you"}],
  "log_offset": None,           # ALWAYS None in M1 — extractor never sets it. Do NOT depend on it.
  "revealed_cards": [], "shuffle_cause": None,
}
```

The full cache dict (returned by `build_event_stream`) also carries top-level `my_seat`, `opp_seat`, `opp_name`, `match_meta`, `schema_version`, `capabilities`. `match_meta` carries `key_events_by_turn` (list of `{turn, kind, actor?, seq, card?, detail?}`), `event_name`, `winner_seat`, `winner_reason`, `games[]`.

**Test harness pattern** (mirror exactly — there is NO `pytest-qt`, and `conftest.py` does NOT define an offscreen fixture, so each Qt test file declares its own):

```python
import pytest

@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

# inside each test:
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
```

**Theme constants available** (`import gui.theme as theme`): `BG`, `PANEL`, `INPUT`, `SURFACE`, `BORDER`, `BORDER_LO`, `ACCENT`, `ACCENT2`, `ACCENT_LT`, `TEXT`, `TEXT_DIM`, `TEXT_OFF`, `OK`, `WARN`, `ERR`, `SPACE_XS/SM/MD/LG/XL`, `btn_secondary()`, `btn_primary()`. Worker: `gui.worker_threads.DataLoadWorker(fn, kwargs=None)` with `.result(object)` / `.error(str)` signals.

## M2 discipline guardrail — what M2 explicitly does NOT do

Reject any change in M2 that adds:
- ❌ **No board rendering.** The center-bottom board panel is a placeholder `QLabel` ("Board view ships in M3"). The Stack list IS functional (uses `stack_after`).
- ❌ **No `gui/widgets/card_tooltip.py` generalization** (that is M3). Card preview in M2 is the *selected event's primary card only*, shown in the right pane via `card_image_cache.load_pixmap`. No hover tooltips on stack/target items.
- ❌ **No `match_log.replay_notes` schema migration** (that is M4). The Notes tab is a non-persisted placeholder `QTextEdit`.
- ❌ **No animation/playback.** Speed selector + Animate toggle are disabled placeholders.
- ❌ **No "View Raw JSON".** `log_offset` is always None in M1; the feature waits for an extractor fix.
- ❌ **No odds computation.** (Odds Engine is post-M4.)
- ❌ **No changes to `analysis/replay_events.py`.** M2 is a pure consumer.

## Deviations from the mockup (intentional, called out so they aren't "bugs")

1. The mockup's center-table **"Time"** column becomes **"Turn"**. M1 events carry no per-event wall-clock timestamp, only `turn_num`. Columns are `# / Turn / Player / Event`.
2. Board panel is a placeholder (M3).

## Mode-persistence semantics (locked — correct here before code lands if wrong)

`tabs.match_history.replay_viewer_mode` stores the user's **last-used** mode (`"full"` default, or `"classic"`). The split button's *primary click* invokes the persisted mode; the dropdown always lists **both** options; picking one from the dropdown invokes it **and** updates the persisted value so the next primary click repeats it.

## File structure

**New:**
- `gui/replay_view_model.py` — Qt-free display logic (all pure functions + constants)
- `gui/widgets/replay_viewer_window.py` — `ReplayEventTableModel` + `ReplayViewerWindow`
- `tests/test_replay_view_model.py` — pure-function tests (no Qt)
- `tests/test_replay_viewer_window.py` — offscreen-Qt smoke tests

**Modified:**
- `gui/state_keys.py` — add `MATCH_HISTORY_REPLAY_VIEWER_MODE`
- `gui/widgets/deck_match_history.py` — split the Watch button; window lifecycle; mode persistence

**Commit discipline:** one commit per task (conventional-commit messages, RTK-prefixed git per global CLAUDE.md). `git push` after commits. The CLAUDE.md/NEXT_STEPS.md/ROADMAP.md doc sync happens in the final task (Task 14) per the non-negotiable rules.

**Imports are additive.** Tasks 4/5/9/11/13 each say "Add to imports". These are **merges** — append the new names to the existing import block, never replace it. Dropping an earlier task's imports will break that task's code.

---

### Task 1: View-model label helpers

**Files:**
- Create: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_view_model.py
"""Pure-function tests for gui/replay_view_model.py (no Qt required)."""
from gui import replay_view_model as vm


def test_phase_label_known_and_fallback():
    assert vm.phase_label("Phase_Main1") == "Precombat Main"
    assert vm.phase_label("Phase_Combat") == "Combat"
    # Unknown enum strips the prefix as a best-effort label
    assert vm.phase_label("Phase_Wibble") == "Wibble"
    assert vm.phase_label(None) == "—"


def test_step_label_known_and_none():
    assert vm.step_label("Step_Upkeep") == "Upkeep"
    assert vm.step_label("Step_DeclareAttackers") == "Declare Attackers"
    assert vm.step_label("Step_Mystery") == "Mystery"
    assert vm.step_label(None) is None


def test_kind_label():
    assert vm.kind_label("cast_spell") == "Cast"
    assert vm.kind_label("priority_grant") == "Priority"
    # Unknown kind title-cases the slug
    assert vm.kind_label("some_new_kind") == "Some New Kind"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.replay_view_model'`

- [ ] **Step 3: Write minimal implementation**

```python
# gui/replay_view_model.py
"""Qt-free display logic for the full-depth replay viewer.

Pure functions that transform the M1 event stream (analysis.replay_events
build_event_stream output) into structures the QMainWindow renders:
timeline tree, event-table rows, kind filtering, navigation, jump-to
targets, and right-pane detail rows.

NO PyQt6 imports here — this module is unit-tested headless. The Qt widgets
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
    if not phase:
        return "—"
    return _PHASE_LABELS.get(phase) or _strip_prefix(phase)


def step_label(step: Optional[str]) -> Optional[str]:
    if not step:
        return None
    return _STEP_LABELS.get(step) or _strip_prefix(step)


def kind_label(kind: str) -> str:
    if kind in _KIND_LABELS:
        return _KIND_LABELS[kind]
    return kind.replace("_", " ").title()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): M2 view-model label helpers"
```

---

### Task 2: Event summary + player label

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

- [ ] **Step 1: Write the failing test**

```python
def _ev(**kw):
    base = {
        "seq": 0, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
        "step": None, "active_seat": 1, "priority_seat": 1, "actor_seat": 1,
        "kind": "cast_spell", "card_name": None, "card_grpid": None,
        "targets": [], "details": {}, "life_after": None,
        "mana_pool_after": None, "stack_after": [], "board_diff": [],
        "log_offset": None, "revealed_cards": [], "shuffle_cause": None,
    }
    base.update(kw)
    return base


def test_player_label_maps_seat():
    assert vm.player_label(_ev(actor_seat=1), my_seat=1, opp_seat=2, opp_name="Bob") == "You"
    assert vm.player_label(_ev(actor_seat=2), my_seat=1, opp_seat=2, opp_name="Bob") == "Bob"
    # No actor -> fall back to active_seat
    assert vm.player_label(_ev(actor_seat=None, active_seat=2), my_seat=1, opp_seat=2, opp_name="Bob") == "Bob"
    # Unknown -> em dash
    assert vm.player_label(_ev(actor_seat=None, active_seat=None), my_seat=1, opp_seat=2, opp_name="Bob") == "—"


def test_event_summary_cast_with_targets():
    e = _ev(kind="cast_spell", card_name="Lightning Strike",
            targets=[{"name": "Make Disappear", "grpid": 1, "kind": "spell"}])
    s = vm.event_summary(e, opp_name="Bob")
    assert "Lightning Strike" in s
    assert "Make Disappear" in s


def test_event_summary_life_change():
    e = _ev(kind="life_change", details={"seat": 1, "delta": -3, "from": 11, "to": 8})
    s = vm.event_summary(e, opp_name="Bob")
    assert "8" in s and ("-3" in s or "−3" in s or "3" in s)


def test_event_summary_phase_change():
    e = _ev(kind="phase_change", phase="Phase_Combat", step="Step_DeclareAttackers")
    s = vm.event_summary(e, opp_name="Bob")
    assert "Combat" in s and "Declare Attackers" in s


def test_event_summary_falls_back_to_kind_label():
    assert vm.event_summary(_ev(kind="shuffle", shuffle_cause="fetch"), opp_name="Bob")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: FAIL — `AttributeError: module 'gui.replay_view_model' has no attribute 'player_label'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): event_summary + player_label"
```

---

### Task 3: format_event_row

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

- [ ] **Step 1: Write the failing test**

```python
def test_format_event_row_shape():
    e = _ev(seq=42, turn_num=7, kind="cast_spell", card_name="Lightning Strike",
            actor_seat=1)
    row = vm.format_event_row(e, my_seat=1, opp_seat=2, opp_name="Bob")
    assert row["seq"] == 42
    assert row["turn"] == 7
    assert row["player"] == "You"
    assert "Lightning Strike" in row["summary"]
    assert row["kind"] == "cast_spell"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py::test_format_event_row_shape -q`
Expected: FAIL — `AttributeError: ... 'format_event_row'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py::test_format_event_row_shape -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): format_event_row"
```

---

### Task 4: ReplayEventTableModel (lazy QAbstractTableModel)

**Files:**
- Create: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

This is the first Qt task. The model is lazy: it holds `events` + a `visible_seqs` list (the rows actually shown). `set_visible_seqs` resets the model. Columns are `# / Turn / Player / Event`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_viewer_window.py
"""Offscreen-Qt smoke tests for gui/widgets/replay_viewer_window.py."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Stub the Scryfall image fetch so window tests never hit the network
    # (load_pixmap otherwise blocks up to 8s on a cache miss). The viewer
    # falls back to rendering the card name as text when this returns None.
    monkeypatch.setattr(
        "gui.widgets.card_image_cache.load_pixmap",
        lambda **kwargs: None,
    )


def _sample_stream():
    """Minimal but realistic build_event_stream() output: 1 game, 2 turns,
    a phase with a step and a phase without, a cast + counter + life + end."""
    def ev(seq, **kw):
        base = {
            "seq": seq, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
            "step": None, "active_seat": 1, "priority_seat": 1, "actor_seat": 1,
            "kind": "cast_spell", "card_name": None, "card_grpid": None,
            "targets": [], "details": {}, "life_after": {"you": 20, "opp": 20},
            "mana_pool_after": {"you": "", "opp": ""}, "stack_after": [],
            "board_diff": [], "log_offset": None, "revealed_cards": [],
            "shuffle_cause": None,
        }
        base.update(kw)
        return base
    events = [
        ev(0, kind="phase_change", phase="Phase_Beginning", step="Step_Upkeep"),
        ev(1, kind="draw_card", phase="Phase_Beginning", step="Step_Draw",
           card_name="Island"),
        ev(2, kind="phase_change", phase="Phase_Main1", step=None),
        ev(3, kind="cast_spell", phase="Phase_Main1", card_name="Lightning Strike",
           card_grpid=70404,
           targets=[{"name": "Make Disappear", "grpid": 81234, "kind": "spell"}],
           stack_after=[{"name": "Lightning Strike", "controller": "you", "targets": []}]),
        ev(4, kind="counter_spell", phase="Phase_Main1", actor_seat=2,
           card_name="Make Disappear"),
        ev(5, kind="life_change", turn_num=2, phase="Phase_Combat",
           step="Step_CombatDamage", details={"seat": 2, "delta": -3, "from": 20, "to": 17},
           life_after={"you": 20, "opp": 17}),
        ev(6, kind="game_end", turn_num=2, details={"reason": "Concede", "winning_seat": 1}),
    ]
    return {
        "arena_match_id": "test-match", "schema_version": 1,
        "capabilities": {"events": True}, "my_seat": 1, "opp_seat": 2,
        "opp_name": "Bob",
        "match_meta": {
            "event_name": "Constructed_BestOf3_Ranked", "winner_seat": 1,
            "winner_reason": "Concede",
            "key_events_by_turn": [
                {"turn": 1, "kind": "first_spell", "actor": "you", "seq": 3,
                 "card": "Lightning Strike"},
                {"turn": 2, "kind": "concede", "actor": "opp", "seq": 6},
            ],
            "games": [],
        },
        "events": events,
    }


def test_table_model_rows_and_cells():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [e["seq"] for e in s["events"]],
                                  my_seat=1, opp_seat=2, opp_name="Bob")
    assert model.rowCount() == 7
    assert model.columnCount() == 4
    # Row 3 = the cast
    idx = model.index(3, 3)  # Event column
    assert "Lightning Strike" in model.data(idx, Qt.ItemDataRole.DisplayRole)
    # seq <-> row mapping
    assert model.seq_for_row(3) == 3
    assert model.row_for_seq(3) == 3


def test_table_model_visible_subset():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [3, 4], my_seat=1, opp_seat=2,
                                  opp_name="Bob")
    assert model.rowCount() == 2
    assert model.seq_for_row(0) == 3
    assert model.row_for_seq(4) == 1
    assert model.row_for_seq(0) is None  # seq 0 not visible
    # Reset to a different subset
    model.set_visible_seqs([0, 1, 2, 3, 4, 5, 6])
    assert model.rowCount() == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.widgets.replay_viewer_window'`

- [ ] **Step 3: Write minimal implementation**

```python
# gui/widgets/replay_viewer_window.py
"""Full-depth replay viewer (M2).

A QMainWindow that steps through one cached match at event granularity:
left timeline tree, center lazy event table, right detail tabs + card
preview. Consumes analysis.replay_events.build_event_stream output via a
background worker; never re-parses Player.log itself.

See docs/superpowers/specs/2026-05-22-replay-viewer-design.md (M2).
Display logic lives in gui/replay_view_model.py (Qt-free, unit-tested).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex

from gui import replay_view_model as vm


class ReplayEventTableModel(QAbstractTableModel):
    """Lazy table over events[], showing only visible_seqs rows.

    Columns: # / Turn / Player / Event. Lazy in the sense that data() formats
    one row on demand; a 2000-event match builds no per-row widgets.
    """

    COLUMNS = ["#", "Turn", "Player", "Event"]

    def __init__(self, events: list[dict], visible_seqs: list[int],
                 my_seat: Optional[int], opp_seat: Optional[int],
                 opp_name: str = "Opp", parent=None):
        super().__init__(parent)
        self._events = events
        self._by_seq = {e.get("seq"): e for e in events}
        self._visible = list(visible_seqs)
        self._my_seat = my_seat
        self._opp_seat = opp_seat
        self._opp_name = opp_name or "Opp"

    # ── lazy reset on filter change ───────────────────────────────
    def set_visible_seqs(self, seqs: list[int]) -> None:
        self.beginResetModel()
        self._visible = list(seqs)
        self.endResetModel()

    # ── seq <-> row mapping (for selection sync) ──────────────────
    def seq_for_row(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def row_for_seq(self, seq: int) -> Optional[int]:
        try:
            return self._visible.index(seq)
        except ValueError:
            return None

    def event_for_row(self, row: int) -> Optional[dict]:
        seq = self.seq_for_row(row)
        return self._by_seq.get(seq) if seq is not None else None

    # ── QAbstractTableModel API ───────────────────────────────────
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        ev = self.event_for_row(index.row())
        if ev is None:
            return None
        row = vm.format_event_row(ev, self._my_seat, self._opp_seat, self._opp_name)
        col = index.column()
        if col == 0:
            return str(row["seq"])
        if col == 1:
            return str(row["turn"]) if row["turn"] is not None else ""
        if col == 2:
            return row["player"]
        if col == 3:
            return row["summary"]
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): lazy ReplayEventTableModel"
```

---

### Task 5: ReplayViewerWindow skeleton + clickable event table

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

**Milestone: after this task the viewer opens and shows a scrollable, clickable event table.** Tree/filters/detail come later. Construction takes a `defer_load` flag so tests populate synchronously via `_on_data_ready` instead of racing the worker thread.

- [ ] **Step 1: Write the failing test**

```python
def test_window_constructs_and_populates():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", opp_name="Bob",
                           defer_load=True)
    # No data yet -> table model empty / None
    w._on_data_ready(_sample_stream())
    assert w._model is not None
    assert w._model.rowCount() == 7
    # Current selection defaults to first event
    assert w._current_seq == 0
    # Title carries the match id
    assert "test-match" in w.windowTitle()


def test_window_select_seq_updates_current():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    assert w._current_seq == 3


def test_window_handles_none_stream():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="missing", defer_load=True)
    w._on_data_ready(None)  # match not in log
    assert w._model is None or w._model.rowCount() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: FAIL — `ImportError: cannot import name 'ReplayViewerWindow'`

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `gui/widgets/replay_viewer_window.py`:

```python
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QSplitter, QHeaderView, QSizePolicy, QAbstractItemView,
)
import gui.theme as theme
```

Then append the window class:

```python
class ReplayViewerWindow(QMainWindow):
    """Top-level, non-modal full-depth replay viewer."""

    def __init__(self, arena_match_id: str, opp_name: str = "",
                 my_deck_label: str = "", parent=None, *, defer_load: bool = False):
        super().__init__(parent)
        self._arena_match_id = arena_match_id
        self._opp_name = opp_name or "Opp"
        self._my_deck_label = my_deck_label
        self._stream: Optional[dict] = None
        self._model: Optional[ReplayEventTableModel] = None
        self._current_seq: Optional[int] = None
        self._my_seat: Optional[int] = None
        self._opp_seat: Optional[int] = None
        self._worker = None

        self.setWindowTitle(f"Replay Viewer — {arena_match_id}")
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        # Non-modal window: free its memory when the user closes it.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._build_ui()
        if not defer_load:
            self._start_load(force=False)

    # ── UI skeleton ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                 theme.SPACE_MD, theme.SPACE_SM)
        outer.setSpacing(theme.SPACE_SM)

        # Top bar: match meta + nav (nav buttons wired in Task 9)
        self._topbar = QHBoxLayout()
        self._meta_lbl = QLabel("Loading…")
        self._meta_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._topbar.addWidget(self._meta_lbl, 1)
        self._counter_lbl = QLabel("")
        self._counter_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._topbar.addWidget(self._counter_lbl)
        outer.addLayout(self._topbar)

        # Center: event table (tree + detail added in later tasks)
        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            f"QTableView {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            f"gridline-color: {theme.BORDER_LO}; alternate-background-color: {theme.INPUT}; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; padding: 4px; }}"
        )
        outer.addWidget(self._table, 1)

    # ── data load ─────────────────────────────────────────────────
    def _start_load(self, force: bool) -> None:
        from gui.worker_threads import DataLoadWorker
        self._meta_lbl.setText("Loading replay…")

        def _do():
            from analysis.replay_events import build_event_stream
            return build_event_stream(self._arena_match_id, force_refresh=force)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_data_ready)
        w.error.connect(lambda msg: self._meta_lbl.setText(f"Load failed: {msg}"))
        w.finished.connect(w.deleteLater)
        w.start()
        self._worker = w

    def _on_data_ready(self, stream: Optional[dict]) -> None:
        if stream is None:
            self._meta_lbl.setText(
                "Match not found in Player.log / Player-prev.log "
                "(log may have rotated)."
            )
            return
        self._stream = stream
        self._my_seat = stream.get("my_seat")
        self._opp_seat = stream.get("opp_seat")
        self._opp_name = stream.get("opp_name") or self._opp_name
        events = stream.get("events") or []

        self._model = ReplayEventTableModel(
            events, [e.get("seq") for e in events],
            self._my_seat, self._opp_seat, self._opp_name,
        )
        self._table.setModel(self._model)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.selectionModel().selectionChanged.connect(
            self._on_table_selection
        )

        meta = stream.get("match_meta") or {}
        self._meta_lbl.setText(
            f"{meta.get('event_name') or 'Match'}  ·  vs {self._opp_name}  ·  "
            f"{len(events)} events"
        )
        if events:
            self._select_seq(events[0].get("seq"))

    # ── selection ─────────────────────────────────────────────────
    def _select_seq(self, seq: Optional[int]) -> None:
        """The one place that moves the cursor. Later tasks extend this to
        also sync the tree, detail tabs, and card preview."""
        if seq is None or self._model is None:
            return
        self._current_seq = seq
        row = self._model.row_for_seq(seq)
        if row is not None:
            self._table.selectRow(row)
        total = self._model.rowCount()
        cur = (self._model.row_for_seq(seq) or 0) + 1
        self._counter_lbl.setText(f"Event {cur}/{total}")

    def _on_table_selection(self, *args) -> None:
        idxs = self._table.selectionModel().selectedRows()
        if not idxs or self._model is None:
            return
        seq = self._model.seq_for_row(idxs[0].row())
        if seq is not None and seq != self._current_seq:
            self._select_seq(seq)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): window skeleton with clickable event table"
```

---

### Task 6: Match History split button + window lifecycle + mode persistence

**Files:**
- Modify: `gui/state_keys.py`
- Modify: `gui/widgets/deck_match_history.py:180-189` (button creation), `:642-656` (`_on_watch_replay`)
- Test: `tests/test_replay_viewer_window.py`

**Milestone: after this task the viewer is reachable from the running app.** The single "▶ Watch replay" `QPushButton` becomes a `QToolButton` split button. Primary click uses the persisted mode; the dropdown lists both and updates the persisted mode.

- [ ] **Step 1: Add the state key (no test — constant only)**

In `gui/state_keys.py`, after the Scout block, add:

```python
# Match History replay viewer
MATCH_HISTORY_REPLAY_VIEWER_MODE = "tabs.match_history.replay_viewer_mode"  # "full" | "classic"
```

- [ ] **Step 2: Write the failing test**

```python
def test_open_full_viewer_helper_returns_window():
    """deck_match_history.open_full_replay_viewer builds a ReplayViewerWindow."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.deck_match_history import open_full_replay_viewer
    w = open_full_replay_viewer(
        arena_match_id="test-match", opp_name="Bob", my_deck_label="Izzet",
        parent=None, defer_load=True,
    )
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    assert isinstance(w, ReplayViewerWindow)
    assert w._arena_match_id == "test-match"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py::test_open_full_viewer_helper_returns_window -q`
Expected: FAIL — `ImportError: cannot import name 'open_full_replay_viewer'`

- [ ] **Step 4: Implement the helper + split button**

In `gui/widgets/deck_match_history.py`, add a module-level helper near the imports (so it is unit-testable without the widget):

```python
def open_full_replay_viewer(arena_match_id: str, opp_name: str = "",
                            my_deck_label: str = "", parent=None,
                            *, defer_load: bool = False):
    """Construct (don't show) a ReplayViewerWindow. Returned so callers can
    keep a reference and so tests can assert without an event loop."""
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    return ReplayViewerWindow(
        arena_match_id=arena_match_id, opp_name=opp_name,
        my_deck_label=my_deck_label, parent=parent, defer_load=defer_load,
    )
```

Replace the button creation at `gui/widgets/deck_match_history.py:180-189`:

```python
        from PyQt6.QtWidgets import QToolButton, QMenu
        from PyQt6.QtGui import QAction
        from gui.state import UIState
        from gui import state_keys

        self._replay_window = None  # live ReplayViewerWindow (reopen guard)
        self._replay_dialog = None  # live classic dialog

        self._replay_btn = QToolButton()
        self._replay_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self._replay_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._replay_btn.setStyleSheet(theme.btn_secondary())
        self._replay_btn.setEnabled(False)

        self._act_full = QAction("▶ Watch (Full)", self)
        self._act_full.triggered.connect(lambda: self._watch_replay("full"))
        self._act_classic = QAction("Watch (Classic)", self)
        self._act_classic.triggered.connect(lambda: self._watch_replay("classic"))

        menu = QMenu(self._replay_btn)
        menu.addAction(self._act_full)
        menu.addAction(self._act_classic)
        self._replay_btn.setMenu(menu)

        # Primary click reflects the last-used mode (default "full").
        mode = UIState.instance().get(
            state_keys.MATCH_HISTORY_REPLAY_VIEWER_MODE, "full"
        )
        self._replay_btn.setDefaultAction(
            self._act_classic if mode == "classic" else self._act_full
        )
        sb_head_row.addWidget(self._replay_btn)
```

Replace `_on_watch_replay` at `gui/widgets/deck_match_history.py:642-656` with the mode-aware version:

```python
    def _watch_replay(self, mode: str) -> None:
        from gui.state import UIState
        from gui import state_keys
        from PyQt6.QtGui import QAction  # noqa: F401 (type hint clarity)

        match_row = getattr(self, "_selected_match_row", None)
        if not match_row:
            return
        arena_id = match_row.get("arena_match_id")
        if not arena_id:
            return

        # Persist last-used mode + make it the new default click.
        UIState.instance().set(
            state_keys.MATCH_HISTORY_REPLAY_VIEWER_MODE, mode
        )
        self._replay_btn.setDefaultAction(
            self._act_classic if mode == "classic" else self._act_full
        )

        if mode == "classic":
            from gui.widgets.replay_transcript_dialog import ReplayTranscriptDialog
            dlg = ReplayTranscriptDialog(
                arena_match_id=arena_id,
                opp_name=match_row.get("opp_name") or "",
                my_deck_label=match_row.get("my_deck") or "",
                parent=self,
            )
            dlg.exec()
            return

        # Full viewer: reopen guard — raise the existing window if alive.
        if self._replay_window is not None:
            try:
                if self._replay_window.isVisible():
                    self._replay_window.raise_()
                    self._replay_window.activateWindow()
                    return
            except RuntimeError:
                self._replay_window = None  # C++ object already deleted

        w = open_full_replay_viewer(
            arena_match_id=arena_id,
            opp_name=match_row.get("opp_name") or "",
            my_deck_label=match_row.get("my_deck") or "",
            parent=self,
        )
        self._replay_window = w
        # WA_DeleteOnClose frees the C++ object; clear our Python ref too.
        w.destroyed.connect(lambda *_: setattr(self, "_replay_window", None))
        w.show()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py::test_open_full_viewer_helper_returns_window -q`
Expected: PASS

- [ ] **Step 6: Verify the enable/disable sites still work**

`grep -n "_replay_btn" gui/widgets/deck_match_history.py` — confirm every reference is either the new creation block or a `setEnabled` call (the three `setEnabled(False)` lines ~507/512/516 and the `setEnabled(bool(... arena_match_id))` line ~524). **Critically, confirm no surviving `self._replay_btn.clicked.connect(...)` line** references the deleted `_on_watch_replay` method — the old `QPushButton.clicked.connect(self._on_watch_replay)` at ~188 must be gone (replaced by the QAction wiring). `QToolButton` has `setEnabled`, so the enable/disable sites keep working unchanged. Read the lines to confirm.

- [ ] **Step 7: Run full suite + commit**

Run: `python -m pytest tests/test_replay_viewer_window.py tests/test_replay_view_model.py -q`
Expected: PASS

```bash
rtk git add gui/state_keys.py gui/widgets/deck_match_history.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): Match History split button + window lifecycle"
```

---

### Task 7: Kind-filter groups + filter_events

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

- [ ] **Step 1: Write the failing test**

```python
def test_kind_groups_cover_all_event_kinds():
    from analysis.replay_events import EVENT_KINDS
    covered = set()
    for kinds in vm.KIND_GROUPS.values():
        covered |= kinds
    assert covered == set(EVENT_KINDS), covered.symmetric_difference(set(EVENT_KINDS))


def test_kinds_for_groups_union():
    kinds = vm.kinds_for_groups({"Casts", "Combat"})
    assert "cast_spell" in kinds
    assert "attack_declared" in kinds
    assert "scry" not in kinds


def test_filter_events_returns_visible_seqs():
    events = [_ev(seq=0, kind="cast_spell"), _ev(seq=1, kind="priority_grant"),
              _ev(seq=2, kind="life_change")]
    seqs = vm.filter_events(events, {"cast_spell", "life_change"})
    assert seqs == [0, 2]
    # None => all
    assert vm.filter_events(events, None) == [0, 1, 2]


def test_default_off_groups():
    assert "Priority" in vm.DEFAULT_OFF_GROUPS
    assert "Raw" in vm.DEFAULT_OFF_GROUPS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py -q -k "group or filter"`
Expected: FAIL — `AttributeError: ... 'KIND_GROUPS'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
# Kind chips are grouped — 33 individual chips would be unusable. Groups in
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
    out: set = set()
    for g in active_groups:
        out |= KIND_GROUPS.get(g, set())
    return out


def filter_events(events: list, allowed_kinds) -> list:
    """Return the seq of every event whose kind is allowed. allowed_kinds
    None => all events visible."""
    if allowed_kinds is None:
        return [e.get("seq") for e in events]
    return [e.get("seq") for e in events if e.get("kind") in allowed_kinds]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): kind-filter groups + filter_events"
```

---

### Task 8: nav_target navigation

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

- [ ] **Step 1: Write the failing test**

```python
def test_nav_target_directions():
    visible = [0, 3, 5, 9]
    assert vm.nav_target(visible, None, "first") == 0
    assert vm.nav_target(visible, None, "last") == 9
    assert vm.nav_target(visible, 3, "next") == 5
    assert vm.nav_target(visible, 3, "prev") == 0
    # clamp at ends
    assert vm.nav_target(visible, 9, "next") == 9
    assert vm.nav_target(visible, 0, "prev") == 0
    # current not in visible: next => first greater, prev => last lesser
    assert vm.nav_target(visible, 4, "next") == 5
    assert vm.nav_target(visible, 4, "prev") == 3
    # empty
    assert vm.nav_target([], 0, "next") is None
    # current None on next => first
    assert vm.nav_target(visible, None, "next") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py::test_nav_target_directions -q`
Expected: FAIL — `AttributeError: ... 'nav_target'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py::test_nav_target_directions -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): nav_target navigation helper"
```

---

### Task 9: Window nav buttons + kind-filter chips + search proxy

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

Wire the top-bar nav buttons (◀◀ ◀ ▶ ▶▶), a row of checkable kind-group chips, and a search box. **Search vs filter split (locked):** kind chips rebuild the model's `visible_seqs` via `filter_events`; the search box is a `QSortFilterProxyModel` that substring-matches the Event column **on top of** the already-filtered model. Do not fold kind filtering into the proxy.

- [ ] **Step 1: Write the failing test**

```python
def test_window_kind_filter_rebuilds_visible():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # Turn OFF everything except "Casts" -> only cast_spell (seq 3) + play_land remain.
    w._active_groups = {"Casts"}
    w._apply_kind_filter()
    visible = [w._model.seq_for_row(r) for r in range(w._model.rowCount())]
    assert 3 in visible          # the cast
    assert 5 not in visible      # life_change filtered out


def test_window_nav_buttons_move_cursor():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(0)
    w._on_nav("next")
    assert w._current_seq == 1
    w._on_nav("last")
    assert w._current_seq == 6
    w._on_nav("first")
    assert w._current_seq == 0


def test_window_search_filters_proxy():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._on_search_changed("Lightning")
    # Proxy now shows only rows whose Event text contains "Lightning"
    assert w._proxy.rowCount() == 1
    w._on_search_changed("")
    assert w._proxy.rowCount() == w._model.rowCount()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "filter or nav or search"`
Expected: FAIL — `AttributeError: 'ReplayViewerWindow' object has no attribute '_apply_kind_filter'`

- [ ] **Step 3: Write minimal implementation**

Add to the imports in `gui/widgets/replay_viewer_window.py`:

```python
from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtWidgets import QToolButton, QLineEdit, QButtonGroup, QCheckBox
```

In `_build_ui`, after the top-bar `meta_lbl`/`counter_lbl` and before the table, insert nav buttons into `self._topbar` and add a filter row:

```python
        # Nav buttons (added to the existing topbar, left of the counter)
        self._nav_btns = {}
        for key, glyph, tip in (("first", "◀◀", "First event"),
                                ("prev", "◀", "Previous"),
                                ("next", "▶", "Next"),
                                ("last", "▶▶", "Last event")):
            b = QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.setStyleSheet(theme.btn_secondary())
            b.clicked.connect(lambda _=False, k=key: self._on_nav(k))
            self._topbar.insertWidget(self._topbar.count() - 1, b)
            self._nav_btns[key] = b

        # Filter row: kind-group chips + search box
        filt = QHBoxLayout()
        filt.setSpacing(theme.SPACE_XS)
        self._chip_boxes = {}
        for group in vm.KIND_GROUPS:
            cb = QCheckBox(group)
            cb.setChecked(group not in vm.DEFAULT_OFF_GROUPS)
            cb.setStyleSheet(f"color: {theme.TEXT_DIM};")
            cb.stateChanged.connect(self._on_chip_changed)
            filt.addWidget(cb)
            self._chip_boxes[group] = cb
        filt.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search events…")
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 3px 8px; }}"
        )
        self._search.textChanged.connect(self._on_search_changed)
        filt.addWidget(self._search)
        outer.addLayout(filt)

        self._active_groups = {
            g for g in vm.KIND_GROUPS if g not in vm.DEFAULT_OFF_GROUPS
        }
        self._proxy = None
```

In `_on_data_ready`, after building `self._model` and before `setModel`, wrap it in the proxy and apply the initial kind filter. Replace the `self._table.setModel(self._model)` line with:

```python
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterKeyColumn(3)  # Event column
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._table.setModel(self._proxy)
        self._apply_kind_filter()
```

Because the view now sits on the proxy, selection sync must map through it. Update `_select_seq` and `_on_table_selection` to translate source↔proxy rows:

```python
    def _select_seq(self, seq: Optional[int]) -> None:
        if seq is None or self._model is None:
            return
        src_row = self._model.row_for_seq(seq)
        if src_row is None:
            return  # seq filtered out of the visible set; leave the cursor put
        self._current_seq = seq
        if self._proxy is not None:
            proxy_idx = self._proxy.mapFromSource(self._model.index(src_row, 0))
            if proxy_idx.isValid():
                self._table.selectRow(proxy_idx.row())
        total = self._model.rowCount()
        self._counter_lbl.setText(f"Event {src_row + 1}/{total}")

    def _on_table_selection(self, *args) -> None:
        idxs = self._table.selectionModel().selectedRows()
        if not idxs or self._model is None or self._proxy is None:
            return
        src_idx = self._proxy.mapToSource(idxs[0])
        seq = self._model.seq_for_row(src_idx.row())
        if seq is not None and seq != self._current_seq:
            self._select_seq(seq)
```

Add the new handlers:

```python
    def _on_nav(self, direction: str) -> None:
        if self._model is None:
            return
        visible = [self._model.seq_for_row(r) for r in range(self._model.rowCount())]
        target = vm.nav_target(visible, self._current_seq, direction)
        if target is not None:
            self._select_seq(target)

    def _on_chip_changed(self, *args) -> None:
        self._active_groups = {
            g for g, cb in self._chip_boxes.items() if cb.isChecked()
        }
        self._apply_kind_filter()

    def _apply_kind_filter(self) -> None:
        if self._model is None or self._stream is None:
            return
        events = self._stream.get("events") or []
        allowed = vm.kinds_for_groups(self._active_groups)
        self._model.set_visible_seqs(vm.filter_events(events, allowed))
        # Keep cursor valid after the row set changes.
        if self._model.row_for_seq(self._current_seq) is None:
            visible = [self._model.seq_for_row(r) for r in range(self._model.rowCount())]
            self._select_seq(vm.nav_target(visible, self._current_seq, "next"))

    def _on_search_changed(self, text: str) -> None:
        if self._proxy is not None:
            self._proxy.setFilterFixedString(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): nav buttons + kind chips + search proxy"
```

---

### Task 10: build_timeline_tree (variable depth)

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

**Tree-depth rule (locked):** within one (game, turn, phase), if **any** event has a non-None `step`, group that phase's events under step nodes (preserving first-seen step order); events with None step in that phase attach directly under the phase node. If **no** event in the phase has a step, events attach directly under the phase. Turn node label uses `active_seat` → "You"/opp_name.

- [ ] **Step 1: Write the failing test**

```python
def test_build_timeline_tree_variable_depth():
    events = [
        _ev(seq=0, game_num=1, turn_num=1, phase="Phase_Beginning",
            step="Step_Upkeep", kind="phase_change", active_seat=1),
        _ev(seq=1, game_num=1, turn_num=1, phase="Phase_Beginning",
            step="Step_Draw", kind="draw_card", active_seat=1),
        _ev(seq=2, game_num=1, turn_num=1, phase="Phase_Main1", step=None,
            kind="cast_spell", active_seat=1),
        _ev(seq=3, game_num=1, turn_num=2, phase="Phase_Main1", step=None,
            kind="cast_spell", active_seat=2),
    ]
    tree = vm.build_timeline_tree(events, my_seat=1, opp_seat=2, opp_name="Bob")
    # One game
    assert len(tree) == 1
    game = tree[0]
    assert game["type"] == "game" and game["game_num"] == 1
    # Two turns
    assert len(game["children"]) == 2
    t1 = game["children"][0]
    assert t1["type"] == "turn" and t1["turn_num"] == 1
    assert "You" in t1["label"]
    # Turn 1 has two phases
    phases = t1["children"]
    assert [p["phase"] for p in phases] == ["Phase_Beginning", "Phase_Main1"]
    # Beginning has step children (Upkeep, Draw)
    beg = phases[0]
    assert all(c["type"] == "step" for c in beg["children"])
    assert [c["step"] for c in beg["children"]] == ["Step_Upkeep", "Step_Draw"]
    # Each step holds its event(s)
    assert beg["children"][0]["children"][0]["type"] == "event"
    # Main1 (no steps) has event children directly
    main1 = phases[1]
    assert all(c["type"] == "event" for c in main1["children"])
    assert main1["children"][0]["seq"] == 2
    # Turn 2 label shows opp
    t2 = game["children"][1]
    assert "Bob" in t2["label"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py::test_build_timeline_tree_variable_depth -q`
Expected: FAIL — `AttributeError: ... 'build_timeline_tree'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
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
    """Nested Game → Turn → Phase → [Step] → Event structure for the
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py::test_build_timeline_tree_variable_depth -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): build_timeline_tree with variable depth"
```

---

### Task 11: Window timeline tree + bidirectional selection sync

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

Add the left `QTreeWidget` inside a `QSplitter` to the left of the table. Clicking an event leaf calls `_select_seq`; selecting a table row scrolls/highlights the matching tree leaf. Store `seq` on each event leaf via `Qt.ItemDataRole.UserRole`.

- [ ] **Step 1: Write the failing test**

```python
def test_window_tree_populates_and_selects():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # Tree has at least one game root
    assert w._tree.topLevelItemCount() >= 1
    # Find an event leaf carrying seq 3 and activate it
    leaf = w._find_tree_leaf(3)
    assert leaf is not None
    w._on_tree_item_clicked(leaf, 0)
    assert w._current_seq == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py::test_window_tree_populates_and_selects -q`
Expected: FAIL — `AttributeError: 'ReplayViewerWindow' object has no attribute '_tree'`

- [ ] **Step 3: Write minimal implementation**

Add to imports:

```python
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
```

In `_build_ui`, replace `outer.addWidget(self._table, 1)` with a horizontal splitter holding the tree and the table:

```python
        body = QSplitter(Qt.Orientation.Horizontal)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; }}"
        )
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        body.addWidget(self._tree)
        body.addWidget(self._table)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 3)
        outer.addWidget(body, 1)
```

In `_on_data_ready`, insert `self._populate_tree()` **immediately before** the `self._apply_kind_filter()` line added in Task 9. Order matters: `_apply_kind_filter` can call `_select_seq` (when the first event is filtered out), and `_select_seq`'s tree-highlight branch needs `_leaf_by_seq` already built. So the sequence becomes: build model+proxy → `setModel` → `_populate_tree()` → `_apply_kind_filter()` → (Task 13 adds `_build_jump_menu()` here) → final `_select_seq(events[0])`.

```python
        self._populate_tree()
        self._apply_kind_filter()   # already present from Task 9; tree now precedes it
```

Add the tree methods:

```python
    def _populate_tree(self) -> None:
        if self._stream is None:
            return
        from gui import replay_view_model as _vm
        self._tree.clear()
        self._leaf_by_seq = {}
        tree = _vm.build_timeline_tree(
            self._stream.get("events") or [], self._my_seat, self._opp_seat,
            self._opp_name,
        )

        def _add(parent_item, node):
            item = QTreeWidgetItem([node.get("label", "")])
            if node.get("type") == "event":
                item.setData(0, Qt.ItemDataRole.UserRole, node.get("seq"))
                self._leaf_by_seq[node.get("seq")] = item
            if parent_item is None:
                self._tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for child in node.get("children", []):
                _add(item, child)
            return item

        for game_node in tree:
            top = _add(None, game_node)
            top.setExpanded(True)

    def _find_tree_leaf(self, seq):
        return getattr(self, "_leaf_by_seq", {}).get(seq)

    def _on_tree_item_clicked(self, item, _col) -> None:
        seq = item.data(0, Qt.ItemDataRole.UserRole)
        if seq is not None:
            self._select_seq(seq)
```

Extend `_select_seq` so it also highlights the matching tree leaf. Add at the end of `_select_seq` (after the counter label update):

```python
        leaf = getattr(self, "_leaf_by_seq", {}).get(seq)
        if leaf is not None:
            self._tree.setCurrentItem(leaf)
            self._tree.scrollToItem(leaf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): timeline tree + selection sync"
```

---

### Task 12: Detail rows, stack rows, jump-to targets, always-visible value

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_view_model.py`

Four small pure helpers feeding the right pane and the Jump-To menu. Each defaults gracefully when `life_after` / `mana_pool_after` / `stack_after` are None/empty (M1 emits these as None on early events — risk #7 in the spec).

- [ ] **Step 1: Write the failing test**

```python
def test_event_details_rows_skips_none():
    e = _ev(seq=3, turn_num=7, phase="Phase_Main1", kind="cast_spell",
            card_name="Lightning Strike", actor_seat=1,
            life_after={"you": 8, "opp": 14}, mana_pool_after=None,
            targets=[{"name": "Make Disappear", "grpid": 1, "kind": "spell"}])
    rows = vm.event_details_rows(e, my_seat=1, opp_seat=2, opp_name="Bob")
    keys = {k for k, _v in rows}
    assert "Seq" in keys and "Kind" in keys and "Card" in keys
    assert "Targets" in keys
    assert "Life" in keys
    # mana_pool_after is None -> no Mana row
    assert "Mana" not in keys


def test_stack_rows_from_stack_after():
    e = _ev(stack_after=[
        {"name": "Lightning Strike", "controller": "you", "targets": ["Make Disappear"]},
        {"name": "Make Disappear", "controller": "opp", "targets": []},
    ])
    rows = vm.stack_rows(e)
    assert len(rows) == 2
    assert rows[0]["name"] == "Lightning Strike"
    assert rows[0]["controller"] == "you"
    # empty / None stack
    assert vm.stack_rows(_ev(stack_after=[])) == []
    assert vm.stack_rows(_ev(stack_after=None)) == []


def test_jump_to_targets_from_match_meta():
    meta = {"key_events_by_turn": [
        {"turn": 1, "kind": "mulligan_to_6", "actor": "you", "seq": 7},
        {"turn": 3, "kind": "first_spell", "actor": "you", "seq": 42, "card": "Stormchaser's Talent"},
        {"turn": 10, "kind": "concede", "actor": "opp", "seq": 1476},
    ]}
    targets = vm.jump_to_targets(meta)
    assert targets[0]["seq"] == 7
    assert "Mulligan" in targets[0]["label"]
    assert "Stormchaser's Talent" in targets[1]["label"]
    assert "Concede" in targets[2]["label"]
    # missing key gracefully -> empty
    assert vm.jump_to_targets({}) == []


def test_always_visible_value_defaults():
    e = _ev(life_after={"you": 8, "opp": 14}, mana_pool_after={"you": "{R}", "opp": ""},
            phase="Phase_Main1", stack_after=[{"name": "X", "controller": "you", "targets": []}])
    assert "8" in vm.always_visible_value(e, "life")
    assert "14" in vm.always_visible_value(e, "life")
    assert "{R}" in vm.always_visible_value(e, "mana")
    assert "Precombat Main" in vm.always_visible_value(e, "phase")
    assert "1" in vm.always_visible_value(e, "stack_count")
    # None life -> safe placeholder, no crash
    assert vm.always_visible_value(_ev(life_after=None), "life")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_view_model.py -q -k "details or stack or jump or always"`
Expected: FAIL — `AttributeError: ... 'event_details_rows'`

- [ ] **Step 3: Write minimal implementation**

Append to `gui/replay_view_model.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_view_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_view_model.py
rtk git commit -m "feat(replay-viewer): detail/stack rows + jump-to + always-visible"
```

---

### Task 13: Right detail pane + card preview + bottom controls + Jump-To menu

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

Add the right `QTabWidget` (Event Details / Stack / Notes), a card-preview `QLabel` below it, a Jump-To `QToolButton` menu in the top bar, the placeholder board panel + bottom controls (speed/Animate disabled; Show Board Changes + Always Visible functional bindings). `_select_seq` drives all of them.

- [ ] **Step 1: Write the failing test**

```python
def test_window_detail_pane_updates_on_select():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)  # the Lightning Strike cast
    # Event Details table shows >=1 row mentioning the card somewhere
    txt = w._detail_text()
    assert "Lightning Strike" in txt
    # Stack tab reflects stack_after of seq 3
    assert w._stack_list.count() == 1
    # Always-visible label populated
    assert w._always_lbl.text()


def test_window_jump_menu_built():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # Jump-To menu has one action per key event (2 in the fixture)
    assert len(w._jump_btn.menu().actions()) == 2


def test_window_board_panel_is_placeholder():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    assert "M3" in w._board_panel.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "detail_pane or jump_menu or board_panel"`
Expected: FAIL — `AttributeError: 'ReplayViewerWindow' object has no attribute '_detail_text'`

- [ ] **Step 3: Write minimal implementation**

Add to imports:

```python
from PyQt6.QtWidgets import (
    QTabWidget, QTableWidget, QTableWidgetItem, QListWidget, QTextEdit,
    QComboBox, QMenu,
)
from PyQt6.QtGui import QAction, QPixmap
```

In `_build_ui`, add the right pane to the `body` splitter (after `body.addWidget(self._table)`), then the board placeholder + bottom controls. Insert before `body.setStretchFactor(...)`:

```python
        # Right pane: detail tabs + card preview
        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._detail_tbl = QTableWidget(0, 2)
        self._detail_tbl.setHorizontalHeaderLabels(["Field", "Value"])
        self._detail_tbl.horizontalHeader().setStretchLastSection(True)
        self._detail_tbl.verticalHeader().setVisible(False)
        self._tabs.addTab(self._detail_tbl, "Event Details")
        self._stack_list = QListWidget()
        self._tabs.addTab(self._stack_list, "Stack")
        self._notes = QTextEdit()
        # Read-only in M2: placeholder text vanishes once the user types, so
        # an editable box would silently lose input on close. Persistence is M4.
        self._notes.setReadOnly(True)
        self._notes.setPlainText("Per-replay notes ship in M4 (not saved in M2).")
        self._tabs.addTab(self._notes, "Notes")
        right_v.addWidget(self._tabs, 1)
        self._preview = QLabel()
        self._preview.setMinimumHeight(180)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
        )
        right_v.addWidget(self._preview)
        body.addWidget(right)
```

Update the stretch factors to account for three panes:

```python
        body.setStretchFactor(0, 1)  # tree
        body.setStretchFactor(1, 3)  # table
        body.setStretchFactor(2, 2)  # right pane
```

After the `body` splitter, add the board placeholder + bottom controls:

```python
        self._board_panel = QLabel("Board view ships in M3")
        self._board_panel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._board_panel.setMinimumHeight(90)
        self._board_panel.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT_DIM}; "
            f"border: 1px dashed {theme.BORDER};"
        )
        outer.addWidget(self._board_panel)

        controls = QHBoxLayout()
        controls.setSpacing(theme.SPACE_SM)
        speed = QComboBox()
        speed.addItems(["0.5x", "1x", "2x", "4x"])
        speed.setCurrentText("1x")
        speed.setEnabled(False)  # playback is M5
        controls.addWidget(QLabel("Speed:"))
        controls.addWidget(speed)
        animate = QCheckBox("Animate")
        animate.setEnabled(False)
        controls.addWidget(animate)
        self._show_board_changes = QCheckBox("Show Board Changes")
        controls.addWidget(self._show_board_changes)
        controls.addStretch()
        controls.addWidget(QLabel("Always Visible:"))
        self._always_combo = QComboBox()
        self._always_combo.addItems(["life", "mana", "phase", "stack_count"])
        self._always_combo.currentTextChanged.connect(
            lambda *_: self._refresh_always_visible()
        )
        controls.addWidget(self._always_combo)
        self._always_lbl = QLabel("")
        self._always_lbl.setStyleSheet(f"color: {theme.ACCENT};")
        controls.addWidget(self._always_lbl)
        outer.addLayout(controls)
```

In the top bar, add a Jump-To button. In `_build_ui`, after the nav buttons loop, insert:

```python
        self._jump_btn = QToolButton()
        self._jump_btn.setText("Jump To ▾")
        self._jump_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._jump_btn.setStyleSheet(theme.btn_secondary())
        self._jump_btn.setMenu(QMenu(self._jump_btn))
        self._topbar.insertWidget(self._topbar.count() - 1, self._jump_btn)
```

In `_on_data_ready`, after `self._populate_tree()`, build the jump menu:

```python
        self._build_jump_menu()
```

Extend `_select_seq` to refresh the detail pane, stack, preview, and always-visible label. Add at the end of `_select_seq`:

```python
        ev = self._model.event_for_row(self._model.row_for_seq(seq)) if self._model else None
        if ev is not None:
            self._update_detail(ev)
            self._update_preview(ev)
            self._refresh_always_visible()
```

Add the new methods:

```python
    def _update_detail(self, event: dict) -> None:
        rows = vm.event_details_rows(event, self._my_seat, self._opp_seat,
                                     self._opp_name)
        self._detail_tbl.setRowCount(len(rows))
        for r, (label, value) in enumerate(rows):
            self._detail_tbl.setItem(r, 0, QTableWidgetItem(label))
            self._detail_tbl.setItem(r, 1, QTableWidgetItem(value))
        self._stack_list.clear()
        for sr in vm.stack_rows(event):
            tgt = f" → {sr['targets']}" if sr["targets"] else ""
            self._stack_list.addItem(
                f"{sr['pos']}. {sr['name']} ({sr['controller']}){tgt}"
            )

    def _detail_text(self) -> str:
        """Concatenated detail-table text (used by tests + accessibility)."""
        out = []
        for r in range(self._detail_tbl.rowCount()):
            for c in range(2):
                it = self._detail_tbl.item(r, c)
                if it:
                    out.append(it.text())
        return " ".join(out)

    def _update_preview(self, event: dict) -> None:
        name = event.get("card_name")
        grpid = event.get("card_grpid")
        if not name:
            self._preview.clear()
            self._preview.setText("(no card)")
            return
        from gui.widgets.card_image_cache import load_pixmap
        px = load_pixmap(card_name=name, grpid=grpid)
        if px is not None:
            self._preview.setPixmap(
                px.scaledToHeight(176, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._preview.setText(name)

    def _refresh_always_visible(self) -> None:
        if self._current_seq is None or self._model is None:
            return
        ev = self._model.event_for_row(self._model.row_for_seq(self._current_seq))
        if ev is not None:
            self._always_lbl.setText(
                vm.always_visible_value(ev, self._always_combo.currentText())
            )

    def _build_jump_menu(self) -> None:
        menu = self._jump_btn.menu()
        menu.clear()
        meta = (self._stream or {}).get("match_meta") or {}
        for tgt in vm.jump_to_targets(meta):
            act = QAction(tgt["label"], self)
            act.triggered.connect(lambda _=False, s=tgt["seq"]: self._select_seq(s))
            menu.addAction(act)
```

Note: `_update_preview` calls `load_pixmap`, which hits the network on a cache miss. In offscreen tests the cards in the fixture (Lightning Strike) may already be cached or return None — both are handled (falls back to text). Tests assert on detail/stack/always, not on the pixmap.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (network-independent — preview falls back to text)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): right detail pane + preview + jump-to + bottom controls"
```

---

### Task 14: Full-suite verification, manual smoke, docs sync

**Files:**
- Modify: `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md`
- Test: full suite

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -q`
Expected: PASS — baseline was 235 green; this plan adds ~30 (≈12 view-model + ≈10 window). Target ~265 green, 0 failures. If any pre-existing test newly fails, STOP and investigate (per superpowers:verification-before-completion — do not paper over a regression).

- [ ] **Step 2: Manual GUI smoke (offscreen is not enough for visual confirmation)**

Run: `python run_gui.py`

Then confirm, recording the result of each:
1. Decks → My Decks → select Tokyo Prowess (id 17) → Match History sub-tab.
2. Select a recent match that has an `arena_match_id` (the ▶ button enables).
3. Click the main button → **Full** viewer opens; tree expands to Phase/Step/Event; table scrolls; clicking a row updates the right Event Details + Stack + card preview; nav buttons (◀◀ ◀ ▶ ▶▶) move the cursor; kind chips hide/show rows; search box narrows; Jump-To lists key events.
4. Use the dropdown → **Watch (Classic)** → old dialog still opens. Reopen the split button — its primary action now defaults to Classic (mode persisted). Switch back to Full via dropdown.
5. Close the Full window, reopen — no crash, no duplicate window; opening twice without closing raises the existing window.
6. Pick a match with **no** `arena_match_id` cached / rotated out → Full viewer shows the "Match not found…" message gracefully.

- [ ] **Step 3: Update docs**

- `ROADMAP.md`: check off "Replay Viewer M2 — full-depth viewer window".
- `NEXT_STEPS.md`: move M2 from "next" to "shipped"; add M3 (board state panel) as the next pickup with the spec section reference.
- `CLAUDE.md`: update the Match History bullet to document the split "Watch (Full)" / "Watch (Classic)" button and the new `gui/widgets/replay_viewer_window.py` + `gui/replay_view_model.py` modules; bump the "Last updated" line. Do **not** embed absolute local paths (pre-push hook rejects `E:/...`); use repo-relative paths only.

- [ ] **Step 4: Commit + push**

```bash
rtk git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
rtk git commit -m "docs: ship replay-viewer M2 (full-depth viewer window)"
rtk git push
```

---

## Self-Review

**Spec coverage (M2 section, spec lines 340-365):**
- Left pane QTreeWidget Game→Turn→Phase→Step→Event → Task 10 (tree builder) + Task 11 (widget). ✅
- Key Events flat clickable items → Jump-To menu, Task 12 + 13. ✅ (Mockup also shows a "Key Events" list section in the tree; the Jump-To menu satisfies the same navigation need. If the executor wants the in-tree list too, it's a trivial add in Task 11 — noted, not required for acceptance.)
- Search-events bar (QSortFilterProxyModel) → Task 9. ✅
- Center table custom QAbstractTableModel, lazy, columns #/Time/Player/Event → Task 4 (model) + Task 5 (view). "Time"→"Turn" deviation documented. ✅
- Filters bar kind chips → Task 7 (logic) + Task 9 (UI). ✅
- Center bottom board placeholder + functional Stack → Task 13 (board placeholder + Stack tab). ✅
- Right pane QTabWidget Event Details / Stack / Notes + card preview → Task 13. ✅
- Top bar match ID + nav (◀◀ ◀ N/M ▶ ▶▶) + Jump-To + Filters → Tasks 5/9/13. ✅ (|▶ jump-to-end is covered by ▶▶ = last; the spec lists both — "last" suffices, an explicit jump-to-end is redundant.)
- Bottom controls speed/Animate placeholders + Show Board Changes + Always Visible → Task 13. ✅ (Show Board Changes has no board to toggle in M2 — it's present but inert until M3; documented.)
- Split button Watch (Full)/Watch (Classic), shared lifecycle ref, persist `tabs.match_history.replay_viewer_mode` → Task 6. ✅
- Risk #7 (graceful missing keys) → null-default tests in Tasks 5, 12. ✅

**Placeholder scan:** No "TBD"/"implement later". Every code step shows complete code. Board panel / speed / Animate / Notes are *intentional, documented* placeholders per the M2 spec, not plan placeholders.

**Type consistency:** `_select_seq(seq)`, `seq_for_row`/`row_for_seq`/`event_for_row`, `set_visible_seqs`, `_active_groups`, `_apply_kind_filter`, `_on_nav`, `_on_search_changed`, `_leaf_by_seq`, `_build_jump_menu`, `_refresh_always_visible` are named identically across the tasks that define and call them. View-model functions (`phase_label`, `step_label`, `kind_label`, `player_label`, `event_summary`, `format_event_row`, `filter_events`, `kinds_for_groups`, `nav_target`, `build_timeline_tree`, `event_details_rows`, `stack_rows`, `jump_to_targets`, `always_visible_value`) match between definition and call sites. `KIND_GROUPS` / `DEFAULT_OFF_GROUPS` consistent. The split button keeps the attribute name `self._replay_btn` so the existing `setEnabled` sites (Task 6 Step 6) keep working.

**Known M1 data caveat carried into the plan:** `log_offset` is always None (extractor never writes it) — no M2 task depends on it; "View Raw JSON" is explicitly out of scope.
