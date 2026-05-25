# Replay Viewer M3 — Board State Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the replay viewer's bottom board-panel placeholder to life — render each player's battlefield (card thumbnails), life, mana, and hand/library/graveyard/exile counts, reconstructed from the M1 `events[]` data and synced to the event cursor.

**Architecture:** A new Layer-3 reconstructor `analysis.replay_events.replay_board_at(events, seq)` walks `board_diff` deltas to rebuild zones in memory (never stored), resetting per game. A new `gui/widgets/replay_board_panel.py::ReplayBoardPanel(QWidget)` renders that snapshot using the same `card_image_cache` + text-fallback pattern as the existing `gui/widgets/puzzle_scene.py`. The M2 `ReplayViewerWindow` swaps its placeholder `QLabel` for the panel and drives it from `_select_seq`.

**Tech Stack:** Python 3.13, PyQt6 (QWidget/QLabel/QHBoxLayout), pytest with `QT_QPA_PLATFORM=offscreen`. Card thumbnails via `gui/widgets/card_image_cache.load_pixmap`; hover-to-full-image via a generalized `gui/widgets/card_tooltip.install_card_hover`.

---

## Context the executor needs

**This builds on M2** (shipped, on `main`). The viewer (`gui/widgets/replay_viewer_window.py`) already shows a left timeline tree, a center event table, right detail tabs, and a **placeholder** board panel created at `gui/widgets/replay_viewer_window.py:253` as a `QLabel("Board view ships in M3")`, added to `outer` at ~line 260. A `_show_board_changes` `QCheckBox` exists (inert) at ~line 273. `_select_seq` (~line 344) is the single cursor seam; `_on_data_ready` (~line 304) loads the stream. Verify these line numbers by reading the file — they drift.

**The M1 event shape** (each item in `stream["events"]`), verified against `analysis/replay_events.py`:
```python
{
  "seq": int, "game_num": int, "turn_num": int, "phase": str|None, "step": str|None,
  "kind": str, "card_name": str|None, "card_grpid": int|None,
  "life_after": {"you": int, "opp": int} | None,
  "mana_pool_after": {"you": str, "opp": str} | None,   # e.g. {"you": "{R}{R}", "opp": ""}
  "board_diff": [
     {"instance_id": int, "card": str|None, "grpid": int|None,
      "from": str|None, "to": str|None, "controller": "you"|"opp"|None},
     ...
  ],
  ...
}
```
`board_diff` zone names are: `hand`, `library`, `battlefield`, `graveyard`, `exile`, `stack`, `command`, `pending`. `to=None` means the instance left all tracked zones. `controller` is `"you"`/`"opp"`/`None`.

**The top-level stream** also has `my_seat`, `opp_seat`, `opp_name`, `match_meta`, `events`.

**CRITICAL data truth — the extractor does NOT reset instance state on game change.** `analysis/replay_events.py:209-211` only updates `current_game`; `instance_to_zone`/`instance_to_grpid` persist across games. The `board_diff` stream is therefore a *continuous delta* — the game-1→game-2 boundary is just one large delta. `replay_board_at` MUST reset its reconstruction state when `game_num` increases while walking, so it reconstructs only the **current game's** board. (This is the correct semantic anyway: the board at a game-2 event should not show game-1 permanents.) A multi-game test fixture locks this.

## M3 discipline guardrail — what M3 explicitly does NOT do (and why)

These are **deferred**, each for a concrete reason — reject any PR that adds them to M3:
- ❌ **Tap state / 90° rotation** — `board_diff` carries zone membership, not tapped state. M1 emits no tap event. (Also: `puzzle_scene.py:169` documents that Qt `QLabel` stylesheets can't `rotate()`; real rotation needs `QTransform` on the pixmap.) Needs an M1 extractor extension + pixmap rotation.
- ❌ **+1/+1 counters** — M1 never emits `counter_added`/`counter_removed` (the extractor's annotation loop handles only ZoneTransfer/Targets/Damage/Scry/Surveil/Shuffle). No per-permanent counter data exists. Needs an extractor extension.
- ❌ **Attached auras** — `board_diff` shows an aura on the battlefield but not what it's attached to. Needs an extractor extension.
- ❌ **Combat (attacker red-border / block arrows)** — `attack_declared`/`block_declared` are **your-side only** (parsed from your client's submit messages); opponent combat is absent from `events[]`. A one-sided highlight would be misleading. Defer until board-diff + `damage_dealt` can derive opp attackers too (M4+).
- ❌ **Lands/creatures split on the battlefield** — requires per-card type classification (`db.card_data` coupling + column verification). M3 renders the battlefield as one ordered strip; the split is M4 polish.
- ❌ **Rendering your hand contents** — the panel shows hand *count* (hand is hidden info in a board view; your hand cards are already visible in the event detail pane). Hand thumbnails deferred.
- ❌ **No new `events[]`/`board_diff` schema fields, no extractor changes, no cache rebuild.** M3 is a pure consumer of the existing M1 contract.

If a need for one of the above arises mid-implementation, the correct action is: document it as a future "M3.5 extractor extension" and ship M3 without it. The board reconstruction is a strict prefix of any fuller version, so nothing here is wasted.

## File structure

**New:**
- `analysis/replay_events.py` — ADD `replay_board_at(events, seq)` (Layer-3 reconstructor; pure, Qt-free, lives beside `build_event_stream`).
- `gui/widgets/replay_board_panel.py` — `ReplayBoardPanel(QWidget)`.
- `tests/test_replay_board.py` — reconstructor tests (headless).

**Modified:**
- `gui/widgets/card_tooltip.py` — ADD generalized `install_card_hover(widget, card_name)` (the existing `install_card_tooltip` is `QTableWidget`-coupled; this works on any widget).
- `gui/widgets/replay_viewer_window.py` — replace the placeholder, drive the panel from `_select_seq`, wire `_show_board_changes`.
- `tests/test_replay_viewer_window.py` — replace the obsolete `test_window_board_panel_is_placeholder`; add a board-render test.

**Commit discipline:** one commit per task (conventional-commit, RTK-prefixed git per global CLAUDE.md). Do not push per-task — the controller handles branch finishing. The CLAUDE.md/NEXT_STEPS.md/ROADMAP.md doc sync happens in the final task.

## `replay_board_at` return contract (locked — the future Odds Engine consumes this)

```python
{
  "seq": int,                       # echoes the requested seq (callers verify)
  "you": {
    "battlefield": [{"instance_id": int, "grpid": int|None, "name": str|None}, ...],
    "graveyard":  [ ...same shape... ],
    "exile":      [ ...same shape... ],
    "hand":       [ ...known cards only (grpid set)... ],
    "hand_count": int,              # all hand instances (known + unknown)
    "library_count": int,
    "graveyard_count": int,         # == len(graveyard)
    "exile_count": int,             # == len(exile)
  },
  "opp": { ...same keys; opp "hand" is [] (hidden), but hand_count is the N... },
}
```
Instance-level (not just counts) so the Odds Engine can track per-permanent. `controller=None` instances are **excluded** from both buckets (asserted by a test). Battlefield/graveyard/exile lists are sorted by `instance_id` for deterministic rendering.

---

### Task 1: `replay_board_at` reconstructor

**Files:**
- Modify: `analysis/replay_events.py` (add the function; place it after `build_event_stream`)
- Test: `tests/test_replay_board.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_board.py
"""Tests for analysis.replay_events.replay_board_at (headless, no Qt)."""
from analysis.replay_events import replay_board_at


def _ev(seq, game_num, diffs):
    return {"seq": seq, "game_num": game_num, "turn_num": 1, "phase": None,
            "step": None, "kind": "zone_change", "card_name": None,
            "card_grpid": None, "board_diff": diffs}


def _d(iid, grpid, name, frm, to, controller):
    return {"instance_id": iid, "grpid": grpid, "card": name,
            "from": frm, "to": to, "controller": controller}


def test_reconstructs_battlefield_and_zones():
    events = [
        _ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")]),
        _ev(1, 1, [_d(2, 200, "Goblin", "hand", "battlefield", "you")]),
        _ev(2, 1, [_d(3, 300, "Bear", None, "battlefield", "opp")]),
        _ev(3, 1, [_d(2, 200, "Goblin", "battlefield", "graveyard", "you")]),
    ]
    b0 = replay_board_at(events, 0)
    assert b0["seq"] == 0
    assert [c["name"] for c in b0["you"]["battlefield"]] == ["Mountain"]

    b1 = replay_board_at(events, 1)
    assert sorted(c["name"] for c in b1["you"]["battlefield"]) == ["Goblin", "Mountain"]

    b3 = replay_board_at(events, 3)
    assert [c["name"] for c in b3["you"]["battlefield"]] == ["Mountain"]
    assert [c["name"] for c in b3["you"]["graveyard"]] == ["Goblin"]
    assert b3["you"]["graveyard_count"] == 1
    assert [c["name"] for c in b3["opp"]["battlefield"]] == ["Bear"]


def test_to_none_removes_instance_and_token_enters():
    # A token enters from nowhere (from=None) then leaves (to=None).
    events = [
        _ev(0, 1, [_d(9, 900, "Goblin Token", None, "battlefield", "you")]),
        _ev(1, 1, [_d(9, 900, "Goblin Token", "battlefield", None, "you")]),
    ]
    assert [c["name"] for c in replay_board_at(events, 0)["you"]["battlefield"]] == ["Goblin Token"]
    assert replay_board_at(events, 1)["you"]["battlefield"] == []


def test_hand_and_library_counts():
    events = [
        _ev(0, 1, [_d(1, 100, "Island", None, "hand", "you")]),
        _ev(0, 1, [_d(2, None, None, None, "hand", "opp")]),   # opp hand: grpid unknown
        _ev(1, 1, [_d(5, None, None, None, "library", "you")]),
    ]
    b = replay_board_at(events, 1)
    assert b["you"]["hand_count"] == 1
    assert [c["name"] for c in b["you"]["hand"]] == ["Island"]  # known
    assert b["opp"]["hand_count"] == 1
    assert b["opp"]["hand"] == []                                # opp hand hidden
    assert b["you"]["library_count"] == 1


def test_controller_none_excluded():
    events = [_ev(0, 1, [_d(1, 100, "Mystery", None, "battlefield", None)])]
    b = replay_board_at(events, 0)
    assert b["you"]["battlefield"] == []
    assert b["opp"]["battlefield"] == []


def test_resets_on_game_change():
    # Game 1 leaves a permanent on the battlefield; game 2 must NOT show it.
    events = [
        _ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")]),
        {"seq": 1, "game_num": 1, "turn_num": 9, "phase": None, "step": None,
         "kind": "game_end", "card_name": None, "card_grpid": None, "board_diff": []},
        _ev(2, 2, [_d(7, 700, "Forest", None, "battlefield", "you")]),
    ]
    b = replay_board_at(events, 2)
    names = [c["name"] for c in b["you"]["battlefield"]]
    assert names == ["Forest"]          # game-1 Mountain is gone
    assert "Mountain" not in names


def test_seq_beyond_end_is_clamped_safely():
    events = [_ev(0, 1, [_d(1, 100, "Mountain", None, "battlefield", "you")])]
    b = replay_board_at(events, 999)
    assert [c["name"] for c in b["you"]["battlefield"]] == ["Mountain"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_board.py -q`
Expected: FAIL — `ImportError: cannot import name 'replay_board_at' from 'analysis.replay_events'`

- [ ] **Step 3: Write minimal implementation**

Add to `analysis/replay_events.py` (after `build_event_stream`):

```python
def replay_board_at(events: list, seq: int) -> dict:
    """Reconstruct the board state as of (and including) the event at `seq`.

    Layer-3 reconstruction (Source-of-Truth Hierarchy): derived on demand by
    applying each event's board_diff in order; never stored. Resets per game
    because the M1 extractor does NOT reset instance tracking on game change,
    so the board_diff stream is a continuous cross-game delta — we scope to
    the current game by clearing state whenever game_num increases.

    Returns the dict documented in docs/superpowers/plans/2026-05-24-replay-viewer-m3.md.
    Instances with controller=None are excluded from both seat buckets.
    """
    instances: dict[int, dict] = {}
    cur_game = None
    for ev in events:
        if ev.get("seq", 0) > seq:
            break
        g = ev.get("game_num")
        if cur_game is None:
            cur_game = g
        elif g is not None and g != cur_game:
            instances = {}          # new game -> fresh board
            cur_game = g
        for d in ev.get("board_diff") or []:
            iid = d.get("instance_id")
            if iid is None:
                continue
            to = d.get("to")
            if to is None:
                instances.pop(iid, None)
            else:
                instances[iid] = {
                    "instance_id": iid,
                    "grpid": d.get("grpid"),
                    "name": d.get("card"),
                    "controller": d.get("controller"),
                    "zone": to,
                }

    def _empty() -> dict:
        return {"battlefield": [], "graveyard": [], "exile": [], "hand": [],
                "hand_count": 0, "library_count": 0,
                "graveyard_count": 0, "exile_count": 0}

    you, opp = _empty(), _empty()
    for inst in sorted(instances.values(), key=lambda i: i["instance_id"]):
        ctrl = inst["controller"]
        if ctrl == "you":
            bucket = you
        elif ctrl == "opp":
            bucket = opp
        else:
            continue  # controller unknown -> excluded
        card = {"instance_id": inst["instance_id"], "grpid": inst["grpid"],
                "name": inst["name"]}
        z = inst["zone"]
        if z == "battlefield":
            bucket["battlefield"].append(card)
        elif z == "graveyard":
            bucket["graveyard"].append(card)
        elif z == "exile":
            bucket["exile"].append(card)
        elif z == "hand":
            bucket["hand_count"] += 1
            if inst["grpid"]:           # known card (yours); opp hand grpid is None
                bucket["hand"].append(card)
        elif z == "library":
            bucket["library_count"] += 1
    for b in (you, opp):
        b["graveyard_count"] = len(b["graveyard"])
        b["exile_count"] = len(b["exile"])
    return {"seq": seq, "you": you, "opp": opp}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_board.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add analysis/replay_events.py tests/test_replay_board.py
rtk git commit -m "feat(replay-viewer): M3 replay_board_at zone reconstructor"
```

---

### Task 2: Generalize `install_card_hover` for any widget

**Files:**
- Modify: `gui/widgets/card_tooltip.py`
- Test: `tests/test_card_tooltip_hover.py`

The existing `install_card_tooltip` is hard-wired to `QTableWidget` (uses `cellEntered`, `item(row,col)`). The board panel's card thumbnails are plain `QLabel`s, so we add a widget-agnostic `install_card_hover(widget, card_name)` using a shared `QObject` event filter (the robust cross-widget way — instance-level `enterEvent` override is unreliable for arbitrary widgets). It reuses the existing shared `CardTooltip` (`_get_tooltip()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_card_tooltip_hover.py
"""Smoke test for the generalized install_card_hover."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


def test_install_card_hover_tags_widget():
    from PyQt6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    from gui.widgets.card_tooltip import install_card_hover
    lbl = QLabel("Lightning Strike")
    install_card_hover(lbl, "Lightning Strike")
    assert lbl._hover_card_name == "Lightning Strike"
    # Re-installing updates the name without error
    install_card_hover(lbl, "Make Disappear")
    assert lbl._hover_card_name == "Make Disappear"


def test_install_card_hover_enter_event_does_not_crash():
    from PyQt6.QtWidgets import QApplication, QLabel
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtCore import QPointF
    app = QApplication.instance() or QApplication([])
    from gui.widgets.card_tooltip import install_card_hover
    lbl = QLabel("Island")
    install_card_hover(lbl, "Island")
    # Posting an Enter event through the filter must not raise.
    ev = QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0))
    app.sendEvent(lbl, ev)
    leave = QEvent(QEvent.Type.Leave)
    app.sendEvent(lbl, leave)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_card_tooltip_hover.py -q`
Expected: FAIL — `ImportError: cannot import name 'install_card_hover'`

- [ ] **Step 3: Write minimal implementation**

Add to `gui/widgets/card_tooltip.py` (after `install_card_tooltip`). First extend the imports at the top of the file:

```python
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QTimer, QObject, QEvent
```
(merge `QObject, QEvent` into the existing `PyQt6.QtCore` import line.)

Then append:

```python
class _CardHoverFilter(QObject):
    """Shared event filter: shows the floating CardTooltip when the mouse
    enters any widget carrying a `_hover_card_name` attribute. Works on
    arbitrary widgets (unlike install_card_tooltip, which needs a table)."""

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.Type.Enter:
            name = getattr(obj, "_hover_card_name", "")
            if name:
                _get_tooltip().show_for_card(name, QCursor.pos())
        elif etype == QEvent.Type.Leave:
            _get_tooltip().schedule_hide()
        return False  # never consume the event


_hover_filter: "_CardHoverFilter | None" = None


def _get_hover_filter() -> "_CardHoverFilter":
    global _hover_filter
    if _hover_filter is None:
        _hover_filter = _CardHoverFilter()
    return _hover_filter


def install_card_hover(widget, card_name: str) -> None:
    """Show the Scryfall card image when the mouse hovers over `widget`.

    Re-callable: updates the card name in place. The widget must outlive the
    hover (the shared filter reads `widget._hover_card_name` at enter time)."""
    widget._hover_card_name = card_name or ""
    widget.installEventFilter(_get_hover_filter())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_card_tooltip_hover.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/card_tooltip.py tests/test_card_tooltip_hover.py
rtk git commit -m "feat(replay-viewer): generalize card tooltip to install_card_hover for any widget"
```

---

### Task 3: `ReplayBoardPanel` widget

**Files:**
- Create: `gui/widgets/replay_board_panel.py`
- Test: `tests/test_replay_board_panel.py`

A two-row board (opp top, you bottom). Each row = a header (life + mana + Hand/Lib/GY/Exile count chips) + a battlefield strip of card thumbnails (reusing the `puzzle_scene.py` `load_pixmap`-with-text-fallback pattern + a `_clear_layout` re-render helper). `render(board, event, *, show_changes=False)` is the entry point. A thumbnail gets an accent highlight border when its `grpid` matches the current event's `card_grpid`; when `show_changes` is on, thumbnails whose `instance_id` is in the **current event's** `board_diff` get a change-highlight border.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_board_panel.py
"""Offscreen-Qt tests for ReplayBoardPanel."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Avoid Scryfall network on cache miss; panel falls back to text labels.
    monkeypatch.setattr("gui.widgets.card_image_cache.load_pixmap",
                        lambda **kwargs: None)


def _board():
    return {
        "seq": 5,
        "you": {"battlefield": [{"instance_id": 1, "grpid": 100, "name": "Mountain"},
                                {"instance_id": 2, "grpid": 200, "name": "Goblin"}],
                "graveyard": [], "exile": [], "hand": [],
                "hand_count": 3, "library_count": 30,
                "graveyard_count": 0, "exile_count": 0},
        "opp": {"battlefield": [{"instance_id": 9, "grpid": 900, "name": "Bear"}],
                "graveyard": [], "exile": [], "hand": [],
                "hand_count": 5, "library_count": 28,
                "graveyard_count": 1, "exile_count": 0},
    }


def _event(**kw):
    base = {"seq": 5, "card_grpid": 200, "board_diff": [],
            "life_after": {"you": 12, "opp": 7},
            "mana_pool_after": {"you": "{R}", "opp": ""}}
    base.update(kw)
    return base


def test_panel_renders_battlefield_and_counts():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), _event())
    assert sorted(p._battlefield_names("you")) == ["Goblin", "Mountain"]
    assert p._battlefield_names("opp") == ["Bear"]
    # Headers reflect the event's life + the board counts
    assert "12" in p._header_text("you")
    assert "7" in p._header_text("opp")
    assert "3" in p._header_text("you")   # hand count


def test_panel_highlights_current_card():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), _event(card_grpid=200))   # Goblin is the current card
    assert 2 in p._highlighted_instances()       # Goblin's instance_id


def test_panel_show_changes_highlights_diff_instances():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    ev = _event(card_grpid=None,
                board_diff=[{"instance_id": 1, "grpid": 100, "card": "Mountain",
                             "from": "hand", "to": "battlefield", "controller": "you"}])
    p.render(_board(), ev, show_changes=True)
    assert 1 in p._highlighted_instances()       # Mountain just changed
    # With show_changes off, the same diff does not highlight
    p.render(_board(), ev, show_changes=False)
    assert 1 not in p._highlighted_instances()


def test_panel_handles_none_event_fields():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    p = ReplayBoardPanel()
    p.render(_board(), {"seq": 5, "card_grpid": None, "board_diff": [],
                        "life_after": None, "mana_pool_after": None})
    # No crash; headers still render with placeholders
    assert p._header_text("you")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_board_panel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.widgets.replay_board_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# gui/widgets/replay_board_panel.py
"""Board-state panel for the full-depth replay viewer (M3).

Renders a two-row board (opp on top, you on the bottom) from the snapshot
produced by analysis.replay_events.replay_board_at(). Card thumbnails use
gui/widgets/card_image_cache (disk cache) with a text fallback, mirroring
gui/widgets/puzzle_scene.py. Hover shows the full Scryfall image via
gui/widgets/card_tooltip.install_card_hover.

Deferred to later milestones (data not in the M1 contract): tap rotation,
+1/+1 counters, attached auras, combat highlighting, lands/creatures split,
hand thumbnails. See docs/superpowers/plans/2026-05-24-replay-viewer-m3.md.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from gui.widgets.card_image_cache import load_pixmap
from gui.widgets.card_tooltip import install_card_hover
import gui.theme as theme

_CARD_W, _CARD_H = 56, 78


class ReplayBoardPanel(QWidget):
    """Two-row board rendered from a replay_board_at() snapshot + the event."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.PANEL};")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(6, 4, 6, 4)
        self._outer.setSpacing(4)
        # Per-seat render bookkeeping (also used by tests)
        self._bf_names: dict[str, list[str]] = {"you": [], "opp": []}
        self._header_txt: dict[str, str] = {"you": "", "opp": ""}
        self._highlighted: set[int] = set()
        self._build_skeleton()

    # ── skeleton: two rows, each header + battlefield strip ────────
    def _build_skeleton(self) -> None:
        self._rows: dict[str, dict] = {}
        for seat in ("opp", "you"):
            row = QVBoxLayout()
            row.setSpacing(2)
            header = QLabel("")
            header.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            bf = QHBoxLayout()
            bf.setSpacing(3)
            bf_holder = QWidget()
            bf_holder.setLayout(bf)
            row.addWidget(header)
            row.addWidget(bf_holder)
            self._outer.addLayout(row)
            if seat == "opp":
                self._outer.addWidget(self._divider())
            self._rows[seat] = {"header": header, "bf": bf}

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {theme.BORDER};")
        return f

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    # ── render entry point ─────────────────────────────────────────
    def render(self, board: dict, event: dict, *, show_changes: bool = False) -> None:
        life = event.get("life_after") or {}
        mana = event.get("mana_pool_after") or {}
        cur_grpid = event.get("card_grpid")
        changed_iids = set()
        if show_changes:
            changed_iids = {d.get("instance_id")
                            for d in (event.get("board_diff") or [])
                            if d.get("instance_id") is not None}
        self._highlighted = set()

        for seat in ("opp", "you"):
            seat_board = board.get(seat) or {}
            life_v = life.get(seat)
            mana_v = mana.get(seat)
            header = (
                f"{'You' if seat == 'you' else 'Opp'}  "
                f"Life {life_v if life_v is not None else '?'}  "
                f"Mana {mana_v or '-'}  "
                f"Hand {seat_board.get('hand_count', 0)}  "
                f"Lib {seat_board.get('library_count', 0)}  "
                f"GY {seat_board.get('graveyard_count', 0)}  "
                f"Exile {seat_board.get('exile_count', 0)}"
            )
            self._header_txt[seat] = header
            self._rows[seat]["header"].setText(header)

            bf_layout = self._rows[seat]["bf"]
            self._clear_layout(bf_layout)
            names: list[str] = []
            cards = seat_board.get("battlefield") or []
            for card in cards:
                names.append(card.get("name") or "?")
                iid = card.get("instance_id")
                grp = card.get("grpid")
                highlight = None
                if cur_grpid is not None and grp == cur_grpid:
                    highlight = theme.ACCENT          # current event's card
                elif iid in changed_iids:
                    highlight = theme.WARN            # changed this event
                if highlight is not None and iid is not None:
                    self._highlighted.add(iid)
                bf_layout.addWidget(self._make_card(card, highlight))
            bf_layout.addStretch(1)
            self._bf_names[seat] = names

    def _make_card(self, card: dict, highlight: Optional[str]) -> QWidget:
        name = card.get("name")
        grpid = card.get("grpid")
        border = highlight or theme.BORDER
        px = load_pixmap(card_name=name, grpid=grpid) if name else None
        lbl = QLabel()
        lbl.setFixedSize(_CARD_W, _CARD_H)
        if px is not None:
            lbl.setPixmap(px.scaled(_CARD_W, _CARD_H,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            lbl.setStyleSheet(f"border: 2px solid {border};")
        else:
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setText(name or "?")
            lbl.setStyleSheet(
                f"border: 2px solid {border}; background: {theme.INPUT}; "
                f"color: {theme.TEXT}; font-size: 8px;"
            )
        if name:
            lbl.setToolTip(name)
            install_card_hover(lbl, name)
        return lbl

    # ── test / accessibility accessors ─────────────────────────────
    def _battlefield_names(self, seat: str) -> list:
        return list(self._bf_names.get(seat, []))

    def _header_text(self, seat: str) -> str:
        return self._header_txt.get(seat, "")

    def _highlighted_instances(self) -> set:
        return set(self._highlighted)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_board_panel.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_board_panel.py tests/test_replay_board_panel.py
rtk git commit -m "feat(replay-viewer): ReplayBoardPanel two-row board renderer"
```

---

### Task 4: Wire the board panel into the viewer window

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

Replace the placeholder `QLabel` with a `ReplayBoardPanel`, render it from `_select_seq` (after the detail/preview block) with a same-seq memo, and make the `_show_board_changes` checkbox re-render. The existing M2 `test_window_board_panel_is_placeholder` becomes obsolete and is replaced.

- [ ] **Step 1: Write the failing test** — replace `test_window_board_panel_is_placeholder` in `tests/test_replay_viewer_window.py` with:

```python
def test_window_board_panel_renders_on_select():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # The placeholder is gone; the board panel is the real widget now.
    assert isinstance(w._board_panel, ReplayBoardPanel)
    w._select_seq(3)   # the Lightning Strike cast (on the stack, not battlefield)
    # Headers populate from the event's life totals (you 20 / opp 20 in the sample)
    assert "20" in w._board_panel._header_text("you")


def test_window_show_board_changes_toggle_rerenders():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    # Toggling the checkbox must not raise and must re-render for the current seq.
    w._show_board_changes.setChecked(True)
    assert w._show_board_changes.isChecked()
```

(Delete the old `test_window_board_panel_is_placeholder` — its `"M3" in ... .text()` assertion no longer holds.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "board_panel_renders or board_changes_toggle"`
Expected: FAIL — `AttributeError`/assertion (the panel is still a `QLabel`).

- [ ] **Step 3: Write minimal implementation**

(a) MERGE the import at the top of `gui/widgets/replay_viewer_window.py`:

```python
from gui.widgets.replay_board_panel import ReplayBoardPanel
```

(b) In `_build_ui`, REPLACE the placeholder block (the `self._board_panel = QLabel("Board view ships in M3")` ... `outer.addWidget(self._board_panel)` lines) with:

```python
        self._board_panel = ReplayBoardPanel()
        self._board_panel.setMinimumHeight(180)
        outer.addWidget(self._board_panel)
        self._last_board_seq = None  # memo so re-signals don't rebuild needlessly
```

(c) Wire the existing `_show_board_changes` checkbox to re-render. Find where it is created (`self._show_board_changes = QCheckBox("Show Board Changes")`) and add right after it:

```python
        self._show_board_changes.stateChanged.connect(
            lambda *_: self._render_board(force=True)
        )
```

(d) At the END of `_select_seq` (after the detail/preview/always-visible block added in M2 Task 13), add:

```python
        self._render_board()
```

(e) Add the `_render_board` method:

```python
    def _render_board(self, *, force: bool = False) -> None:
        if self._model is None or self._current_seq is None:
            return
        if not force and self._current_seq == self._last_board_seq:
            return
        self._last_board_seq = self._current_seq
        ev = self._model.event_for_row(self._model.row_for_seq(self._current_seq))
        if ev is None:
            return
        from analysis.replay_events import replay_board_at
        events = (self._stream or {}).get("events") or []
        board = replay_board_at(events, self._current_seq)
        self._board_panel.render(
            board, ev, show_changes=self._show_board_changes.isChecked()
        )
```

Note: `_render_board` is called at the end of `_select_seq`, which already early-returns for filtered-out seqs (`src_row is None`) — so the board only updates for visible events, consistent with the rest of the panes. The `force=True` path (checkbox toggle) bypasses the same-seq memo so toggling re-renders the current event.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (the board tests pass; all prior window tests still green).

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): wire board panel into viewer, driven by _select_seq"
```

---

### Task 5: Full-suite verification, manual smoke, docs sync

**Files:**
- Modify: `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md`
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest -q`
Expected: PASS. Baseline after M2 was 271. M3 adds ~16 (≈6 reconstructor + ≈2 tooltip + ≈4 panel + ≈2 window, minus 1 deleted placeholder test). Target ~287, 0 failures. If any pre-existing test newly fails, STOP and investigate (superpowers:verification-before-completion — no papering over regressions).

- [ ] **Step 2: Manual GUI smoke** (offscreen tests can't confirm visuals)

Run: `python run_gui.py`

Confirm, recording each result:
1. My Decks → Tokyo Prowess (id 17) → Match History → a match with an `arena_match_id` → Watch (Full).
2. The board panel renders below the event table: two rows (opp top, you bottom) with life / mana / Hand / Lib / GY / Exile, and battlefield thumbnails.
3. Click through events / use nav buttons → the battlefield updates; permanents appear as they're played and move to GY when they die; life/mana track the cursor.
4. The current event's card (when it's a battlefield permanent) shows an accent highlight ring; hovering a thumbnail pops the full Scryfall image.
5. Toggle **Show Board Changes** → the card(s) that changed on the current event get a highlight.
6. Scrub to a **game 2** event in a Bo3 → the board shows only game-2 permanents (no game-1 carryover).

- [ ] **Step 3: Update docs**

- `ROADMAP.md`: check off "Replay-viewer M3: board state panel". Note the deferred items (tap/counters/auras/combat/lands-split) carried to M4 or a future extractor extension.
- `NEXT_STEPS.md`: move M3 to shipped; set M4 (polish: event search refinements, jump-to items, per-replay notes + `match_log.replay_notes` migration, markdown export, remove classic dialog) as the next pickup. Note the deferred-board items as candidate M4/M3.5 work.
- `CLAUDE.md`: update the Match History / replay viewer bullet to mention the board panel (`gui/widgets/replay_board_panel.py` + `analysis.replay_events.replay_board_at`), and that tap/counters/auras/combat are deferred (not in the M1 data contract). Bump the "Last updated" line. Repo-relative paths only (pre-push hook rejects `E:/...`).

- [ ] **Step 4: Commit**

```bash
rtk git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
rtk git commit -m "docs: ship replay-viewer M3 (board state panel)"
```

(Branch finishing — merge to main + push — is handled by the controller via superpowers:finishing-a-development-branch after this task.)

---

## Self-Review

**Spec coverage (M3 section, design doc lines 367-384):**
- Two-row layout (opp top, you bottom) → Task 3. ✅
- Per row: life + hand/library/GY/exile counts + mana → Task 3 header. ✅
- Battlefield card thumbnails via `card_image_cache` → Task 3. ✅
- Hover → full Scryfall image via generalized `install_card_tooltip` → Task 2 (`install_card_hover`) + Task 3 wiring. ✅
- Highlight ring on the current event's card (`card_grpid`/targets) → Task 3 (`card_grpid` match). ⚠️ Partial: highlights by `card_grpid`; `targets[]`-based highlight deferred (the current card is the common case). Documented.
- Reconstructor `analysis.replay_events.replay_board_at(events, seq)` → Task 1. ✅
- Tap / counters / auras → **deferred** (no M1 data); documented in the guardrail. ⚠️ Intentional.
- `_select_seq` drives the panel; `Show Board Changes` functional → Task 4. ✅

**Placeholder scan:** No "TBD"/"implement later". Every code step is complete. Deferred items (tap/counters/auras/combat/lands-split/hand-thumbnails) are *documented intentional* scope cuts with reasons, not plan placeholders.

**Type consistency:** `replay_board_at(events, seq)` return keys (`seq`/`you`/`opp`/`battlefield`/`graveyard`/`exile`/`hand`/`hand_count`/`library_count`/`graveyard_count`/`exile_count`) are consistent between Task 1's definition, Task 3's renderer, and the test fixtures. `ReplayBoardPanel.render(board, event, *, show_changes=False)` and the accessors `_battlefield_names`/`_header_text`/`_highlighted_instances` match between Task 3 and Task 4's tests. `install_card_hover(widget, card_name)` matches between Task 2 and Task 3. `_render_board`/`_last_board_seq`/`_board_panel`/`_show_board_changes` consistent between Task 4's steps and tests.

**Known data caveats carried in the plan:** extractor non-reset on game change → `replay_board_at` resets per game (Task 1, tested); opp combat absent → combat deferred; `counter_added` not emitted → counters deferred; library/hand counts for game 2+ rely on the boundary delta being complete (battlefield reconstructs cleanly because it starts empty each game).
