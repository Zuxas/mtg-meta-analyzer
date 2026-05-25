# Replay Viewer M4 — Notes, Mark-Important & Markdown Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the replay viewer into a review tool — let the pilot write per-replay notes that persist, mark important events, and export a Markdown review summary.

**Architecture:** Per-replay annotations (`{text, marks}`) are stored as a JSON blob in a new `match_log.replay_notes` column, keyed by `arena_match_id` (unique). A Qt-free `gui/replay_view_model.replay_markdown(stream, marked_seqs, notes_text)` renders the review. The M2/M3 `ReplayViewerWindow` gets an editable Notes tab (load/save), a ★ Mark toggle (marks feed the Jump-To menu + export), and an Export button.

**Tech Stack:** Python 3.13, SQLite (via `db/match_log.py`), PyQt6, pytest with `QT_QPA_PLATFORM=offscreen` + a tmp-DB fixture.

---

## Context the executor needs

This builds on M1+M2+M3 (all shipped to `main`). The viewer is `gui/widgets/replay_viewer_window.py::ReplayViewerWindow`. Verified anchors (line numbers drift — locate by content):
- `__init__`: `self._arena_match_id = arena_match_id` (~line 111).
- `_build_ui`: the Jump-To button block (~164-169); the right-pane tabs incl. the **Notes** tab — currently `self._notes = QTextEdit()` set **read-only** with placeholder text "Per-replay notes ship in M4…" (~233-238); the bottom `controls` QHBoxLayout (~259-286).
- `_on_data_ready` (~304-335): sets `self._stream`, `self._my_seat`, `self._opp_seat`, `self._opp_name`, builds the model/proxy, calls `self._populate_tree()`, `self._apply_kind_filter()`, `self._build_jump_menu()`.
- `_select_seq` (the cursor seam — already updates table/counter/tree/detail/preview/board; early-returns when the seq isn't visible, i.e. `src_row is None`).
- `_build_jump_menu` (~528-536): clears `self._jump_btn.menu()` and adds one action per `vm.jump_to_targets(meta)` entry.
- The viewer is a non-modal `QMainWindow` with `WA_DeleteOnClose` set; there is **no** `closeEvent` override yet.

`vm` is `from gui import replay_view_model as vm`. The view-model already has `phase_label`, `step_label`, `event_summary`, `player_label`. Tests use the `_sample_stream()` helper + the autouse `_offscreen_qt` fixture in `tests/test_replay_viewer_window.py`.

**`match_log` schema lives in `db/match_log.py`** (NOT `db/database.py`). Its `_ensure_table()` (lines 52-74) runs the `CREATE TABLE IF NOT EXISTS` then a list of try/except-wrapped `ALTER TABLE match_log ADD COLUMN …` migrations (this is where `arena_match_id` was added, with a `UNIQUE INDEX … WHERE arena_match_id IS NOT NULL`). `created_at TEXT NOT NULL` is the **only** column without a default; every other column has a `DEFAULT` or is nullable. `get_connection()` yields `sqlite3.Row` rows (dict-style access works).

## M4 scope (locked with the pilot) + deferrals

**In scope:** (1) persisted per-replay notes, (2) mark-important events, (3) Markdown export.

**Explicitly NOT in M4 (reject if added):**
- ❌ **Removing the "Watch (Classic)" dialog** — the spec gates this on Full being default ~1 week; Full shipped 2026-05-24. Premature. Revisit ~2026-06.
- ❌ **The M1 data-quality fix** (game_num oscillation / sparse zone tracking) — separate data-layer track, filed in NEXT_STEPS. M4 is viewer-only.
- ❌ Full-text event search, kind-filter chips, Jump-To-key-events menu — **already shipped in M2.** Do not rebuild.
- ❌ Restoring the board's Hand/Lib/GY/Exile counts — blocked on the M1 fix.

## Save-failure contract (deviation from spec, decided here)

The spec says "save to `match_log.replay_notes`". A replay can be opened for a match that has **no `match_log` row** (a cached replay never imported from Player.log). Rather than silently dropping notes, `save_replay_notes` **creates a minimal stub `match_log` row** keyed by `arena_match_id` (`source='replay_notes_stub'`, all other columns default; `created_at` set) when none exists. Notes always persist; the Player.log importer can enrich the stub later. The stub keys on the existing unique `arena_match_id` index, so no invariant breaks.

## File structure

**Modified:**
- `db/match_log.py` — add the `replay_notes` migration + `get_replay_notes` / `save_replay_notes`.
- `gui/replay_view_model.py` — add `replay_markdown(stream, marked_seqs, notes_text)`.
- `gui/widgets/replay_viewer_window.py` — editable Notes tab + load/save + closeEvent; ★ Mark toggle; Export button.
- `tests/test_replay_viewer_window.py` — window tests for notes/mark/export.

**New test files:**
- `tests/test_replay_notes_db.py` — DB accessor tests.
- `tests/test_replay_markdown.py` — markdown render tests.

**Commit discipline:** one commit per task (conventional-commit, RTK-prefixed git). Do not push per-task — the controller finishes the branch. Docs sync (CLAUDE.md/NEXT_STEPS.md/ROADMAP.md) is the final task. **Do not stage `gui/tabs/my_decks.py`** (unrelated uncommitted work). **Imports are additive — merge, don't replace.**

---

### Task 1: `match_log.replay_notes` migration + accessors

**Files:**
- Modify: `db/match_log.py`
- Test: `tests/test_replay_notes_db.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_replay_notes_db.py`:

```python
# tests/test_replay_notes_db.py
"""Tests for per-replay notes/marks persistence in db/match_log.py."""
import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    yield


def test_get_defaults_when_absent(tmp_db):
    from db.match_log import get_replay_notes
    data = get_replay_notes("no-such-match")
    assert data == {"text": "", "marks": []}


def test_save_creates_stub_then_get_roundtrips(tmp_db):
    from db.match_log import save_replay_notes, get_replay_notes
    # No match_log row exists for this arena_match_id -> stub created.
    assert save_replay_notes("arena-1", "passed priority T7", [3, 1, 3]) is True
    data = get_replay_notes("arena-1")
    assert data["text"] == "passed priority T7"
    assert data["marks"] == [1, 3]            # deduped + sorted


def test_save_updates_existing_row(tmp_db):
    from db.match_log import save_match, save_replay_notes, get_replay_notes
    mid = save_match("FNM", "2026-05-25", "standard", 1, "Izzet Prowess",
                     "Golgari", match_id=None)
    # Attach an arena_match_id to that row so save_replay_notes UPDATEs it.
    from db.database import get_connection
    with get_connection() as c:
        c.execute("UPDATE match_log SET arena_match_id=? WHERE id=?",
                  ("arena-2", mid))
    assert save_replay_notes("arena-2", "note", [5]) is True
    # Did NOT create a second row.
    with get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM match_log WHERE arena_match_id=?",
                      ("arena-2",)).fetchone()[0]
    assert n == 1
    assert get_replay_notes("arena-2") == {"text": "note", "marks": [5]}


def test_empty_arena_id_is_noop(tmp_db):
    from db.match_log import save_replay_notes, get_replay_notes
    assert save_replay_notes("", "x", [1]) is False
    assert get_replay_notes("") == {"text": "", "marks": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_notes_db.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_replay_notes'`

- [ ] **Step 3: Write minimal implementation**

(a) In `db/match_log.py`, extend the import line:
```python
from db.helpers import ensure_table as _do_ensure, utc_now as _now, json_loads_dict
```

(b) In `_ensure_table`, add to the migration list (after the `arena_match_id` lines):
```python
            "ALTER TABLE match_log ADD COLUMN replay_notes TEXT NOT NULL DEFAULT ''",
```

(c) Append these functions to `db/match_log.py`:
```python
def get_replay_notes(arena_match_id: str) -> dict:
    """Per-replay annotations for a match: {"text": str, "marks": [int, ...]}.
    Defaults to empty when the row/column is missing or unparseable."""
    _ensure_table()
    if not arena_match_id:
        return {"text": "", "marks": []}
    with get_connection() as conn:
        row = conn.execute(
            "SELECT replay_notes FROM match_log WHERE arena_match_id=?",
            (arena_match_id,),
        ).fetchone()
    raw = row["replay_notes"] if row and row["replay_notes"] else ""
    data = json_loads_dict(raw)
    text = data.get("text", "") if isinstance(data, dict) else ""
    raw_marks = data.get("marks", []) if isinstance(data, dict) else []
    marks = sorted({int(m) for m in raw_marks if isinstance(m, (int, float))})
    return {"text": str(text or ""), "marks": marks}


def save_replay_notes(arena_match_id: str, text: str = "", marks=None) -> bool:
    """Persist per-replay notes + marked event seqs as a JSON blob in
    match_log.replay_notes. If no match_log row exists for this arena_match_id
    (a cached replay never imported from Player.log), create a minimal stub row
    so notes never silently drop — the importer can enrich the stub later.
    Returns False only when arena_match_id is empty."""
    if not arena_match_id:
        return False
    _ensure_table()
    marks_clean = sorted({int(m) for m in (marks or [])})
    payload = json.dumps({"text": text or "", "marks": marks_clean})
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE match_log SET replay_notes=? WHERE arena_match_id=?",
            (payload, arena_match_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO match_log (arena_match_id, created_at, source, "
                "replay_notes) VALUES (?, ?, 'replay_notes_stub', ?)",
                (arena_match_id, _now(), payload),
            )
    return True
```
(`json` is already imported at the top of `db/match_log.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_notes_db.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add db/match_log.py tests/test_replay_notes_db.py
rtk git commit -m "feat(replay-viewer): M4 match_log.replay_notes column + get/save accessors"
```

---

### Task 2: `replay_markdown` review renderer (pure)

**Files:**
- Modify: `gui/replay_view_model.py`
- Test: `tests/test_replay_markdown.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_replay_markdown.py`:

```python
# tests/test_replay_markdown.py
"""Tests for gui.replay_view_model.replay_markdown (headless, no Qt)."""
from gui import replay_view_model as vm


def _stream():
    def ev(seq, **kw):
        base = {"seq": seq, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
                "step": None, "actor_seat": 1, "active_seat": 1, "kind": "cast_spell",
                "card_name": None, "targets": [], "details": {}}
        base.update(kw)
        return base
    return {
        "my_seat": 1, "opp_seat": 2, "opp_name": "Bob",
        "match_meta": {"event_name": "RC Cincinnati", "winner_seat": 1,
                       "winner_reason": "Concede"},
        "events": [
            ev(3, turn_num=7, kind="cast_spell", card_name="Lightning Strike"),
            ev(5, turn_num=9, kind="life_change",
               details={"delta": -3, "to": 2}),
        ],
    }


def test_markdown_header_notes_and_marks():
    md = vm.replay_markdown(_stream(), [3], "Should have held up the burn.")
    assert "# Replay review" in md
    assert "RC Cincinnati" in md and "Bob" in md
    assert "**Won**" in md and "Concede" in md
    assert "Should have held up the burn." in md
    assert "## Marked events" in md
    assert "Lightning Strike" in md          # the marked event
    assert "T7" in md


def test_markdown_no_marks_and_no_notes():
    md = vm.replay_markdown(_stream(), [], "")
    assert "_(no notes)_" in md
    assert "_(none marked)_" in md


def test_markdown_unknown_result_and_filters_bad_marks():
    s = _stream()
    s["match_meta"]["winner_seat"] = None
    md = vm.replay_markdown(s, [3, 999], "")   # 999 isn't a real seq -> dropped
    assert "unknown" in md.lower()
    assert "Lightning Strike" in md
    assert "999" not in md


def test_markdown_loss_when_opp_wins():
    s = _stream()
    s["match_meta"]["winner_seat"] = 2
    assert "**Lost**" in vm.replay_markdown(s, [], "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_markdown.py -q`
Expected: FAIL — `AttributeError: module 'gui.replay_view_model' has no attribute 'replay_markdown'`

- [ ] **Step 3: Write minimal implementation** — append to `gui/replay_view_model.py`:

```python
def replay_markdown(stream: dict, marked_seqs, notes_text: str = "") -> str:
    """Render a Markdown replay-review summary: header (event / opponent /
    result), the pilot's free-text notes, and a list of marked events.
    Consumes the build_event_stream() dict (the locked M1 contract)."""
    stream = stream or {}
    meta = stream.get("match_meta") or {}
    events = stream.get("events") or []
    my_seat = stream.get("my_seat")
    opp_seat = stream.get("opp_seat")
    opp_name = stream.get("opp_name") or "Opp"
    by_seq = {e.get("seq"): e for e in events}

    event_name = meta.get("event_name") or "Match"
    winner = meta.get("winner_seat")
    if winner is None:
        result = "Result: unknown"
    elif winner == my_seat:
        result = "Result: **Won**"
    else:
        result = "Result: **Lost**"
    reason = meta.get("winner_reason")
    if reason:
        result += f" ({reason})"

    lines = [f"# Replay review — {event_name} vs {opp_name}", "", result, "",
             "## Notes", (notes_text or "").strip() or "_(no notes)_", "",
             "## Marked events"]

    marks = sorted({int(s) for s in (marked_seqs or []) if s in by_seq})
    if not marks:
        lines.append("_(none marked)_")
    else:
        for s in marks:
            ev = by_seq[s]
            ph = phase_label(ev.get("phase"))
            st = step_label(ev.get("step"))
            phase_str = f"{ph} — {st}" if st else ph
            who = player_label(ev, my_seat, opp_seat, opp_name)
            summary = event_summary(ev, opp_name=opp_name)
            lines.append(
                f"- **G{ev.get('game_num')} T{ev.get('turn_num')} · {phase_str}** "
                f"({who}): {summary}"
            )
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_markdown.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
rtk git add gui/replay_view_model.py tests/test_replay_markdown.py
rtk git commit -m "feat(replay-viewer): replay_markdown review renderer"
```

---

### Task 3: Editable Notes tab + load/save + closeEvent

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_replay_viewer_window.py`:

```python
def test_window_notes_load_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-note", defer_load=True)
    w._on_data_ready(_sample_stream())
    assert not w._notes.isReadOnly()                 # editable now
    w._notes.setPlainText("held up burn on T7")
    w._persist_replay_notes(flash=True)
    assert get_replay_notes("arena-note")["text"] == "held up burn on T7"
    # A fresh window for the same match loads the saved notes.
    w2 = ReplayViewerWindow(arena_match_id="arena-note", defer_load=True)
    w2._on_data_ready(_sample_stream())
    assert w2._notes.toPlainText() == "held up burn on T7"


def test_window_closeevent_persists_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QCloseEvent
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-close", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._notes.setPlainText("typed then closed")
    w.closeEvent(QCloseEvent())                      # read text -> DB -> base
    assert get_replay_notes("arena-close")["text"] == "typed then closed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "notes_load or closeevent_persists"`
Expected: FAIL — `_notes.isReadOnly()` is True / `_persist_replay_notes` missing.

- [ ] **Step 3: Write minimal implementation**

(a) In `__init__`, after `self._arena_match_id = arena_match_id`, add:
```python
        self._marked_seqs: set[int] = set()
```

(b) In `_build_ui`, REPLACE the Notes-tab block (the `self._notes = QTextEdit()` … `self._tabs.addTab(self._notes, "Notes")` lines, currently read-only) with an editable composite:
```python
        notes_tab = QWidget()
        notes_v = QVBoxLayout(notes_tab)
        notes_v.setContentsMargins(0, 0, 0, 0)
        self._notes = QTextEdit()
        self._notes.setPlaceholderText(
            "Notes for this replay (saved to your match log)…"
        )
        notes_v.addWidget(self._notes, 1)
        notes_btn_row = QHBoxLayout()
        self._notes_save_btn = QPushButton("Save notes")
        self._notes_save_btn.setStyleSheet(theme.btn_secondary())
        self._notes_save_btn.clicked.connect(
            lambda: self._persist_replay_notes(flash=True)
        )
        notes_btn_row.addWidget(self._notes_save_btn)
        self._notes_status = QLabel("")
        self._notes_status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px;"
        )
        notes_btn_row.addWidget(self._notes_status)
        notes_btn_row.addStretch()
        notes_v.addLayout(notes_btn_row)
        self._tabs.addTab(notes_tab, "Notes")
```
(`QWidget`, `QVBoxLayout`, `QHBoxLayout`, `QLabel`, `QPushButton`, `QTextEdit` are all already imported from M2/M3.)

(c) In `_on_data_ready`, immediately after `self._stream = stream` (and before the model is built), add:
```python
        self._load_replay_notes()
```

(d) Add these methods to the class:
```python
    def _load_replay_notes(self) -> None:
        from db.match_log import get_replay_notes
        data = get_replay_notes(self._arena_match_id)
        self._notes.setPlainText(data.get("text", ""))
        self._marked_seqs = set(data.get("marks", []))

    def _persist_replay_notes(self, *, flash: bool = False) -> None:
        from db.match_log import save_replay_notes
        ok = save_replay_notes(
            self._arena_match_id, self._notes.toPlainText(),
            sorted(self._marked_seqs),
        )
        if flash:
            self._notes_status.setText("Saved" if ok else "Not saved")

    def closeEvent(self, event) -> None:
        # Persist BEFORE WA_DeleteOnClose tears the widget down: read the text,
        # write the DB, THEN defer to the base class. Do not touch the widget
        # after super().closeEvent().
        try:
            self._persist_replay_notes()
        except Exception:
            pass
        super().closeEvent(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (the 2 new tests pass; all prior window tests still green).

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): editable Notes tab with load/save + close persistence"
```

---

### Task 4: ★ Mark-important toggle

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

Adds a top-bar "☆ Mark / ★ Marked" toggle that adds/removes the current visible event's seq from `_marked_seqs`, persists immediately, and surfaces marked events in the Jump-To menu. The button is disabled when the current event isn't visible (filtered out).

- [ ] **Step 1: Write the failing test** — append to `tests/test_replay_viewer_window.py`:

```python
def test_window_mark_toggle_persists_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-mark", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    w._toggle_mark()
    assert 3 in w._marked_seqs
    assert "Marked" in w._mark_btn.text()                 # ★ Marked
    assert get_replay_notes("arena-mark")["marks"] == [3] # persisted
    # Jump-To menu now includes a marked entry (key events + >=1 mark).
    assert len(w._jump_btn.menu().actions()) >= 1
    # Toggling again removes it.
    w._toggle_mark()
    assert 3 not in w._marked_seqs
    assert get_replay_notes("arena-mark")["marks"] == []


def test_window_mark_button_disabled_when_no_visible_event(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-mark2", defer_load=True)
    # Before any data/selection, the mark button is disabled.
    assert not w._mark_btn.isEnabled()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "mark_toggle or mark_button_disabled"`
Expected: FAIL — `_mark_btn` / `_toggle_mark` missing.

- [ ] **Step 3: Write minimal implementation**

(a) In `_build_ui`, immediately after the Jump-To button block (after `self._topbar.insertWidget(self._topbar.count() - 1, self._jump_btn)`), add the Mark button:
```python
        self._mark_btn = QToolButton()
        self._mark_btn.setText("☆ Mark")
        self._mark_btn.setStyleSheet(theme.btn_secondary())
        self._mark_btn.setToolTip("Mark this event as important (saved with the replay)")
        self._mark_btn.setEnabled(False)
        self._mark_btn.clicked.connect(self._toggle_mark)
        self._topbar.insertWidget(self._topbar.count() - 1, self._mark_btn)
```

(b) Add these methods:
```python
    def _toggle_mark(self) -> None:
        seq = self._current_seq
        if (seq is None or self._model is None
                or self._model.row_for_seq(seq) is None):
            return  # only mark a currently-visible event
        if seq in self._marked_seqs:
            self._marked_seqs.discard(seq)
        else:
            self._marked_seqs.add(seq)
        self._persist_replay_notes()   # marks persist immediately
        self._refresh_mark_button()
        self._build_jump_menu()        # marked events appear in Jump-To

    def _refresh_mark_button(self) -> None:
        seq = self._current_seq
        visible = (seq is not None and self._model is not None
                   and self._model.row_for_seq(seq) is not None)
        self._mark_btn.setEnabled(visible)
        marked = bool(visible and seq in self._marked_seqs)
        self._mark_btn.setText("★ Marked" if marked else "☆ Mark")
        self._mark_btn.setToolTip(
            f"Mark this event as important · {len(self._marked_seqs)} marked"
        )
```

(c) At the END of `_select_seq`, add:
```python
        self._refresh_mark_button()
```

(d) REPLACE `_build_jump_menu` with the version that also lists marked events:
```python
    def _build_jump_menu(self) -> None:
        menu = self._jump_btn.menu()
        menu.clear()
        meta = (self._stream or {}).get("match_meta") or {}
        for tgt in vm.jump_to_targets(meta):
            act = QAction(tgt["label"], self)
            act.triggered.connect(lambda _=False, s=tgt["seq"]: self._select_seq(s))
            menu.addAction(act)
        if self._marked_seqs and self._model is not None:
            menu.addSeparator()
            for s in sorted(self._marked_seqs):
                row = self._model.row_for_seq(s)
                ev = self._model.event_for_row(row) if row is not None else None
                label = (f"★ T{ev.get('turn_num')}: "
                         f"{vm.event_summary(ev, opp_name=self._opp_name)}"
                         if ev else f"★ seq {s}")
                act = QAction(label, self)
                act.triggered.connect(lambda _=False, ss=s: self._select_seq(ss))
                menu.addAction(act)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS (the 2 new tests pass; all prior window tests still green).

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): mark-important event toggle + Jump-To marked section"
```

---

### Task 5: Export review (Markdown) button

**Files:**
- Modify: `gui/widgets/replay_viewer_window.py`
- Test: `tests/test_replay_viewer_window.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_replay_viewer_window.py`:

```python
def test_window_build_review_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-export", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._notes.setPlainText("kept the counter up")
    w._select_seq(3)
    w._toggle_mark()                       # mark the cast
    md = w._build_review_markdown()
    assert "# Replay review" in md
    assert "kept the counter up" in md
    assert "## Marked events" in md
    assert "Lightning Strike" in md        # the marked event from _sample_stream
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_viewer_window.py -q -k "build_review_markdown"`
Expected: FAIL — `_build_review_markdown` missing.

- [ ] **Step 3: Write minimal implementation**

(a) In `_build_ui`, after the Mark button block, add the Export button:
```python
        self._export_btn = QToolButton()
        self._export_btn.setText("Export review")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setToolTip("Export a Markdown review (notes + marked events)")
        self._export_btn.clicked.connect(self._on_export_review)
        self._topbar.insertWidget(self._topbar.count() - 1, self._export_btn)
```

(b) Add these methods:
```python
    def _build_review_markdown(self) -> str:
        return vm.replay_markdown(
            self._stream or {}, sorted(self._marked_seqs),
            self._notes.toPlainText(),
        )

    def _on_export_review(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        md = self._build_review_markdown()
        default = f"replay_review_{self._arena_match_id}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export replay review", default, "Markdown (*.md)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            self._meta_lbl.setText(f"Exported review → {path}")
        except OSError as e:
            self._meta_lbl.setText(f"Export failed: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_viewer_window.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add gui/widgets/replay_viewer_window.py tests/test_replay_viewer_window.py
rtk git commit -m "feat(replay-viewer): export Markdown replay review"
```

---

### Task 6: Full-suite verification, manual smoke, docs sync

**Files:**
- Modify: `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md`
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run (this Windows env mangles piped pytest progress — use PowerShell and read the exit code + summary): `python -m pytest -q`
Expected: PASS. Baseline after M3 was 285. M4 adds ~14 (4 DB + 4 markdown + 2 notes + 2 mark + 1 export, ± a couple). Target ~298, 0 failures. If any pre-existing test newly fails, STOP and investigate (superpowers:verification-before-completion).

- [ ] **Step 2: Manual GUI smoke**

Run: `python run_gui.py` → My Decks → Tokyo Prowess (id 17) → Match History → a match with an `arena_match_id` → Watch (Full). Confirm:
1. Notes tab is editable; type a note, click **Save notes** → status shows "Saved".
2. Navigate to an event, click **☆ Mark** → it becomes **★ Marked**; the Jump-To menu gains a "★ …" entry that navigates to it. Toggle off → reverts.
3. The Mark button disables when no event is selected / when the current event is filtered out by a kind chip.
4. Click **Export review** → choose a path → a `.md` file is written with the header, your notes, and the marked events.
5. Close the window, reopen the same match → your notes + marks are still there.

- [ ] **Step 3: Update docs**

- `ROADMAP.md`: check off the M4 notes/mark/export items; note classic-dialog removal is still deferred (Full not yet default ~1 week) and the M1 data fix remains the gating follow-up.
- `NEXT_STEPS.md`: move M4 (notes/mark/export) to shipped; set the next pickup as either the **M1 data-quality fix** (unblocks board counts + tap/counters) or **classic-dialog retirement** (after ~1 week of Full as default). Keep the manual-smoke note.
- `CLAUDE.md`: update the replay-viewer bullet to mention editable notes (`match_log.replay_notes`), mark-important, and Markdown export; bump the "Last updated" line. Repo-relative paths only.

- [ ] **Step 4: Commit**

```bash
rtk git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
rtk git commit -m "docs: ship replay-viewer M4 (notes, mark-important, markdown export)"
```

(Branch finishing — merge to main + push — handled by the controller via superpowers:finishing-a-development-branch after this task.)

---

## Self-Review

**Spec coverage (M4 section, design doc lines 456-468):**
- Full event-text search → **already in M2** (not re-done). ✅ (documented)
- Kind filter chips → **already in M2**. ✅ (documented)
- Jump-To dropdown items → **already in M2**; M4 extends it with a marked-events section (Task 4). ✅
- Mark-important-event + per-replay notes saved to `match_log.replay_notes` → Task 1 (DB) + Task 3 (notes) + Task 4 (mark). ✅ (column lives in `db/match_log.py`, not `db/database.py` — corrected.)
- Export Markdown summary → Task 2 (renderer) + Task 5 (button). ✅
- Remove "Watch (Classic)" → **deferred** (premature; documented). ⚠️ intentional.

**Placeholder scan:** No "TBD"/"implement later". Every code step is complete. The classic-removal + M1-fix deferrals are documented intentional scope cuts, not plan gaps.

**Type consistency:** `get_replay_notes(arena_match_id) -> {"text", "marks"}` and `save_replay_notes(arena_match_id, text, marks)` match between Task 1's definition and Tasks 3/4's calls. `replay_markdown(stream, marked_seqs, notes_text)` matches between Task 2 and Task 5's `_build_review_markdown`. Window attrs/methods — `_marked_seqs`, `_notes`, `_notes_save_btn`, `_notes_status`, `_load_replay_notes`, `_persist_replay_notes`, `_mark_btn`, `_toggle_mark`, `_refresh_mark_button`, `_build_jump_menu`, `_export_btn`, `_build_review_markdown`, `_on_export_review` — are defined before/where they're called and named consistently across Tasks 3-5. `closeEvent` ordering (read text → write DB → `super().closeEvent`) is explicit per the advisor.

**Save-failure contract:** decided (Option B stub-row creation) and tested (`test_save_creates_stub_then_get_roundtrips`). Mark-button visibility gate explicit (Task 4 `_toggle_mark` + `_refresh_mark_button`). Markdown helper takes `stream` (the locked contract), not unpacked pieces.
