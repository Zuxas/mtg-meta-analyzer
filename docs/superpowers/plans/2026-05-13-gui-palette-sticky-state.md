# GUI Quick Wins — Palette + Sticky State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a global Ctrl+K command palette and persisted UI state (format / timeframe / per-tab selections) for the mtg-meta-analyzer GUI, eliminating the action-cost and context-cost friction identified in the brainstorm.

**Architecture:** Two new modules: `gui/state.py` (pure-Python `UIState` singleton wrapping `data/preferences.json` with dotted-path get/set and debounced disk save) and `gui/widgets/palette_registry.py` + `gui/widgets/command_palette.py` (registry data layer is pure Python; QDialog is the thin Qt layer on top). Wired into `gui/main_window.py` via `QShortcut(Ctrl+K)` and a single `UIState` instance threaded into each tab.

**Tech Stack:** Python 3.13, PyQt6, `thefuzz` (already in requirements.txt), pytest (bootstrap fresh — no current test infra).

**Spec:** `docs/superpowers/specs/2026-05-13-gui-palette-sticky-state-design.md` (commit `8fb07bd`).

---

## File Structure

**Files created (this plan):**

| Path | Purpose |
|---|---|
| `gui/state.py` | `UIState` singleton; reads/writes `data/preferences.json`; dotted-path API; debounced disk save |
| `gui/widgets/palette_registry.py` | `PaletteEntry` dataclass + `PaletteRegistry` class; prefix parsing; fuzzy search; stale-recent pruning. Pure Python — no Qt |
| `gui/widgets/command_palette.py` | `CommandPalette` QDialog; input + result list; key navigation; calls registry |
| `gui/widgets/_palette_actions.py` | Registers built-in `ACT:*` actions; reads context from MainWindow |
| `tests/__init__.py` | Empty; marks tests/ as package |
| `tests/conftest.py` | Sets `sys.path` to project root so `from gui.state import UIState` works |
| `tests/test_ui_state.py` | Unit tests for `UIState` (load / get / set / reset / corrupt-JSON recovery) |
| `tests/test_palette_registry.py` | Unit tests for `PaletteRegistry` (register / search / prefix parsing / context predicate / prune_recents) |

**Files modified:**

| Path | Change |
|---|---|
| `gui/main_window.py` | Import `UIState`, construct singleton, wire `Ctrl+K` shortcut, populate `PaletteRegistry` with real tabs/archetypes/decks/cards/actions on startup, persist `global.last_active_tab_path` on tab change |
| `gui/tabs/dashboard.py` | Hydrate `selected_archetype` + `chart_archetypes` in `showEvent`; persist on widget change |
| `gui/tabs/my_decks.py` | Hydrate `selected_deck_id` in `showEvent`; persist on selection change |
| `gui/tabs/charts.py` | Hydrate `archetypes` + `chart_type` in `showEvent`; persist on change |
| `gui/tabs/heatmap_tab.py` | Hydrate `top_n` + `source_filter` in `showEvent`; persist on change |
| `gui/tabs/scout.py` | Hydrate `days` + `target_archetypes` in `showEvent`; persist on change |
| `gui/tabs/settings.py` | Add "Reset UI state" button |

---

## Task 1: Bootstrap pytest + UIState skeleton (failing tests)

**Files:**
- Modify: `requirements.txt` (add `pytest>=8.0`)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_ui_state.py`

The codebase has no test infrastructure yet. This task adds the smallest viable pytest setup AND writes failing tests for `UIState` before any implementation.

- [ ] **Step 1.0: Add pytest to requirements.txt**

Append at the end of `requirements.txt`:

```
# Test infrastructure (added 2026-05-13)
pytest>=8.0
```

Then install:

```bash
pip install pytest>=8.0
```

Verify:

```bash
python -m pytest --version
```

Expected: `pytest 8.x.x` (or newer).

- [ ] **Step 1.1: Create empty `tests/__init__.py`**

```bash
touch tests/__init__.py
```

- [ ] **Step 1.2: Create `tests/conftest.py`**

```python
"""Pytest configuration. Adds project root to sys.path so tests can
import `gui.state`, `gui.widgets.palette_registry`, etc.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

- [ ] **Step 1.3: Write `tests/test_ui_state.py` (failing tests for UIState API)**

```python
"""Tests for gui.state.UIState.

UIState is a pure-Python singleton wrapping data/preferences.json.
It supports dotted-path get/set, debounced disk save, and corrupt-JSON
recovery. These tests never touch Qt — UIState must work standalone.
"""
import json
from pathlib import Path

import pytest

from gui.state import UIState


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect UIState to a per-test preferences.json under tmp_path."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    # Reset singleton between tests
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


def test_get_returns_default_when_key_missing(tmp_prefs):
    state = UIState.instance()
    assert state.get("tabs.dashboard.selected_archetype", default="Foo") == "Foo"


def test_set_then_get_round_trip(tmp_prefs):
    state = UIState.instance()
    state.set("tabs.dashboard.selected_archetype", "Izzet Prowess")
    assert state.get("tabs.dashboard.selected_archetype") == "Izzet Prowess"


def test_set_creates_intermediate_dicts(tmp_prefs):
    state = UIState.instance()
    state.set("tabs.scout.days", 14)
    state.set("tabs.scout.target_archetypes", ["Izzet Prowess"])
    assert state.get("tabs.scout.days") == 14
    assert state.get("tabs.scout.target_archetypes") == ["Izzet Prowess"]


def test_save_writes_to_disk(tmp_prefs):
    state = UIState.instance()
    state.set("global.format", "Standard")
    state.flush()  # synchronous save for tests
    data = json.loads(tmp_prefs.read_text())
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_load_preserves_unrelated_prefs(tmp_prefs):
    # Existing preferences (formats, api_key) must not be clobbered
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "anthropic_api_key": "sk-test",
    }))
    state = UIState.instance()
    state.set("global.format", "Standard")
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data["anthropic_api_key"] == "sk-test"
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_corrupt_json_falls_back_to_empty_state(tmp_prefs):
    tmp_prefs.write_text("{not valid json}")
    state = UIState.instance()
    # Load failure is silent; get returns defaults
    assert state.get("anything", default="fallback") == "fallback"


def test_corrupt_ui_state_key_does_not_kill_other_prefs(tmp_prefs):
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "ui_state": "not-a-dict",  # corrupt
    }))
    state = UIState.instance()
    # ui_state slot recovers, formats unaffected on save
    state.set("global.format", "Standard")
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_reset_clears_ui_state_only(tmp_prefs):
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "ui_state": {"global": {"format": "Standard"}},
    }))
    state = UIState.instance()
    state.reset()
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data.get("ui_state", {}) == {}
```

- [ ] **Step 1.4: Run tests — they MUST fail (no `gui/state.py` yet)**

```bash
python -m pytest tests/test_ui_state.py -v
```

Expected output: `ModuleNotFoundError: No module named 'gui.state'` (or similar import error). 8 tests collected → all fail/error at collection.

- [ ] **Step 1.5: Commit failing tests**

```bash
git add tests/__init__.py tests/conftest.py tests/test_ui_state.py
git commit -m "test(state): scaffold pytest + failing UIState tests (TDD red)"
```

---

## Task 2: Implement UIState to make tests pass

**Files:**
- Create: `gui/state.py`

- [ ] **Step 2.1: Write `gui/state.py`**

```python
"""UIState — persisted GUI state singleton.

Reads and writes `data/preferences.json`. Adds a top-level `ui_state` key
without disturbing existing keys (`formats`, `anthropic_api_key`, etc.).

API:
    UIState.instance() -> singleton
    state.get(path, default=None)  # dotted-path access
    state.set(path, value)         # debounced disk save (250ms)
    state.reset()                  # clear ui_state key only
    state.flush()                  # synchronous save (used by tests + on exit)

Pure Python — no Qt dependency. Debounce via threading.Timer so unit tests
can run without QApplication.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PREFERENCES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "preferences.json"
)
DEBOUNCE_SECONDS = 0.25


class UIState:
    _instance: "UIState | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._prefs: dict[str, Any] = {}
        self._data: dict[str, Any] = {}
        self._timer: threading.Timer | None = None
        self._save_lock = threading.Lock()
        self.load()

    @classmethod
    def instance(cls) -> "UIState":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def load(self) -> None:
        """Read preferences.json. Tolerant of missing file / corrupt JSON."""
        try:
            if PREFERENCES_PATH.exists():
                with PREFERENCES_PATH.open("r", encoding="utf-8") as f:
                    self._prefs = json.load(f)
            else:
                self._prefs = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("preferences.json unreadable (%s); using empty state", e)
            self._prefs = {}
        ui_state = self._prefs.get("ui_state")
        if isinstance(ui_state, dict):
            self._data = ui_state
        else:
            if ui_state is not None:
                logger.warning("ui_state key was not a dict; resetting to empty")
            self._data = {}

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, path: str, value: Any) -> None:
        keys = path.split(".")
        node = self._data
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value
        self._schedule_save()

    def reset(self) -> None:
        self._data = {}
        self._schedule_save()

    def flush(self) -> None:
        """Cancel pending debounce and save synchronously."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._save_now()

    def _schedule_save(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(DEBOUNCE_SECONDS, self._save_now)
        self._timer.daemon = True
        self._timer.start()

    def _save_now(self) -> None:
        with self._save_lock:
            self._prefs["ui_state"] = self._data
            try:
                PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = PREFERENCES_PATH.with_suffix(".json.tmp")
                with tmp_path.open("w", encoding="utf-8") as f:
                    json.dump(self._prefs, f, indent=2)
                tmp_path.replace(PREFERENCES_PATH)
            except OSError as e:
                logger.error("Failed to save preferences.json: %s", e)
```

- [ ] **Step 2.2: Run tests — they MUST pass**

```bash
python -m pytest tests/test_ui_state.py -v
```

Expected output: 8 passed.

- [ ] **Step 2.3: Commit implementation**

```bash
git add gui/state.py
git commit -m "feat(state): UIState singleton with debounced JSON persistence"
```

---

## Task 3: PaletteRegistry data layer (failing tests)

**Files:**
- Create: `tests/test_palette_registry.py`

- [ ] **Step 3.1: Write failing tests for `PaletteRegistry`**

```python
"""Tests for gui.widgets.palette_registry.

The registry is pure Python — no Qt. It owns: entry storage, prefix parsing,
fuzzy search, context predicates, and stale-recent pruning.
"""
import pytest

from gui.widgets.palette_registry import (
    PaletteEntry,
    PaletteRegistry,
    parse_prefix,
)


def _entry(id_, category, name, secondary="", context_predicate=None):
    return PaletteEntry(
        id=id_, category=category, name=name,
        secondary=secondary, handler=lambda: None,
        context_predicate=context_predicate,
    )


def test_parse_prefix_no_prefix():
    assert parse_prefix("izzet") == (None, "izzet")


def test_parse_prefix_actions():
    assert parse_prefix(">refresh") == ("ACT", "refresh")


def test_parse_prefix_tabs():
    assert parse_prefix("#dashboard") == ("TAB", "dashboard")


def test_parse_prefix_archetypes():
    assert parse_prefix("@izzet") == ("ARCH", "izzet")


def test_parse_prefix_decks():
    assert parse_prefix(":tokyo") == ("DECK", "tokyo")


def test_parse_prefix_cards():
    assert parse_prefix("c:sheoldred") == ("CARD", "sheoldred")


def test_register_and_get():
    reg = PaletteRegistry()
    e = _entry("tab:dashboard", "TAB", "Dashboard")
    reg.register(e)
    assert reg.get("tab:dashboard") is e


def test_register_replaces_existing_id():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard", "old"))
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard", "new"))
    assert reg.get("tab:dashboard").secondary == "new"
    assert len(reg.search("dashboard")) == 1  # not duplicated


def test_unregister_removes_entry():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.unregister("tab:dashboard")
    assert reg.get("tab:dashboard") is None
    assert reg.search("dashboard") == []


def test_search_fuzzy_match():
    reg = PaletteRegistry()
    reg.register(_entry("arch:izzet-prowess", "ARCH", "Izzet Prowess"))
    reg.register(_entry("arch:mono-green", "ARCH", "Mono-Green Landfall"))
    results = reg.search("izet")  # typo
    assert results[0].id == "arch:izzet-prowess"


def test_search_prefix_filters_category():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("arch:dashboard-archetype", "ARCH", "Dashboard Archetype"))
    results = reg.search("#dashboard")
    assert all(r.category == "TAB" for r in results)
    assert results[0].id == "tab:dashboard"


def test_search_cards_gated_behind_prefix_for_short_queries():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("card:sheoldred", "CARD", "Sheoldred, the Apocalypse"))
    # Without prefix, query "s" should NOT surface the card
    results = reg.search("s")
    assert not any(r.category == "CARD" for r in results)
    # With c: prefix, card surfaces
    results = reg.search("c:sheo")
    assert results[0].category == "CARD"


def test_search_context_predicate_filters_entry():
    reg = PaletteRegistry()
    available = {"value": False}
    reg.register(_entry(
        "act:print-sb", "ACT", "Print SB Guide",
        context_predicate=lambda: available["value"],
    ))
    assert reg.search("print") == []
    available["value"] = True
    assert len(reg.search("print")) == 1


def test_prune_recents_drops_unknown_ids():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    pruned = reg.prune_recents([
        "tab:dashboard",
        "arch:deleted-archetype",
        "tab:nonexistent",
    ])
    assert pruned == ["tab:dashboard"]
```

- [ ] **Step 3.2: Run tests — MUST fail (no `palette_registry.py` yet)**

```bash
python -m pytest tests/test_palette_registry.py -v
```

Expected: `ModuleNotFoundError: No module named 'gui.widgets.palette_registry'`.

- [ ] **Step 3.3: Commit failing tests**

```bash
git add tests/test_palette_registry.py
git commit -m "test(palette): scaffold failing PaletteRegistry tests (TDD red)"
```

---

## Task 4: Implement PaletteRegistry to make tests pass

**Files:**
- Create: `gui/widgets/palette_registry.py`

- [ ] **Step 4.1: Write `gui/widgets/palette_registry.py`**

```python
"""PaletteRegistry — searchable command catalog for the command palette.

Pure Python. No Qt. The QDialog layer (command_palette.py) consumes this.

Entries have stable IDs (`tab:dashboard`, `arch:izzet-prowess`, etc.) so
recents stored in UIState survive renames and tab reorganization.

Card category is gated behind the `c:` prefix (or appears only when the
query is ≥2 chars and matches nothing in other categories) so the 32k-card
namespace doesn't drown short queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from thefuzz import fuzz, process

CATEGORIES = ("TAB", "ARCH", "DECK", "CARD", "ACT")

_CATEGORY_PRIORITY = {"TAB": 0, "ACT": 1, "ARCH": 2, "DECK": 3, "CARD": 4}

_MIN_FUZZ_SCORE = 50  # WRatio cutoff; below this, treat as "no match"


@dataclass
class PaletteEntry:
    id: str                   # stable; e.g. "tab:my-decks"
    category: str             # one of CATEGORIES
    name: str                 # display name (the searchable text)
    secondary: str = ""       # context line shown below name
    handler: Callable[[], None] = field(default=lambda: None)
    context_predicate: Optional[Callable[[], bool]] = None


def parse_prefix(query: str) -> tuple[Optional[str], str]:
    """Return (category_filter_or_None, remaining_query)."""
    if query.startswith("c:"):
        return ("CARD", query[2:].strip())
    if query and query[0] in ">#@:":
        prefix_map = {">": "ACT", "#": "TAB", "@": "ARCH", ":": "DECK"}
        return (prefix_map[query[0]], query[1:].strip())
    return (None, query.strip())


class PaletteRegistry:
    def __init__(self) -> None:
        self._entries: list[PaletteEntry] = []
        self._by_id: dict[str, PaletteEntry] = {}

    def register(self, entry: PaletteEntry) -> None:
        if entry.id in self._by_id:
            self._entries.remove(self._by_id[entry.id])
        self._entries.append(entry)
        self._by_id[entry.id] = entry

    def unregister(self, entry_id: str) -> None:
        e = self._by_id.pop(entry_id, None)
        if e is not None:
            self._entries.remove(e)

    def get(self, entry_id: str) -> Optional[PaletteEntry]:
        return self._by_id.get(entry_id)

    def has(self, entry_id: str) -> bool:
        return entry_id in self._by_id

    def search(self, query: str, limit: int = 8) -> list[PaletteEntry]:
        category, q = parse_prefix(query)
        candidates = [
            e for e in self._entries
            if (category is None or e.category == category)
            and (e.context_predicate is None or e.context_predicate())
        ]

        # No prefix: hide CARD entries unless query is long enough AND
        # at least one card outscores the highest non-card. To keep this
        # tractable we simply hide cards when no prefix is given.
        if category is None:
            candidates = [e for e in candidates if e.category != "CARD"]

        if not q:
            candidates.sort(key=lambda e: (_CATEGORY_PRIORITY.get(e.category, 9), e.name))
            return candidates[:limit]

        choices = {e.id: e.name for e in candidates}
        matches = process.extract(q, choices, scorer=fuzz.WRatio, limit=limit)
        # matches: list of (name, score, id)
        return [self._by_id[m[2]] for m in matches if m[1] >= _MIN_FUZZ_SCORE]

    def prune_recents(self, recents: list[str]) -> list[str]:
        return [r for r in recents if r in self._by_id]
```

- [ ] **Step 4.2: Run tests — MUST pass**

```bash
python -m pytest tests/test_palette_registry.py -v
```

Expected: 14 passed.

- [ ] **Step 4.3: Commit**

```bash
git add gui/widgets/palette_registry.py
git commit -m "feat(palette): registry data layer with fuzzy search + prefix parsing"
```

---

## Task 5: Command palette QDialog widget

**Files:**
- Create: `gui/widgets/command_palette.py`

No automated Qt tests in v1 — manual smoke after Task 8 covers this. The widget is small enough that careful TDD on the registry covers the brain of it.

- [ ] **Step 5.1: Write `gui/widgets/command_palette.py`**

```python
"""CommandPalette — modal QDialog presenting PaletteRegistry results.

Triggered by Ctrl+K from MainWindow. Self-closes on Esc, Enter, or focus loss.
Reuses the dark theme from gui.theme — no separate stylesheet.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QLabel,
    QFrame, QHBoxLayout, QWidget,
)

import gui.theme as theme
from gui.widgets.palette_registry import PaletteEntry, PaletteRegistry


# Verified token names from gui/theme.py: PANEL, SURFACE, INPUT, BORDER,
# ACCENT, ACCENT_LT, ACCENT_DK, ACCENT2, TEXT, TEXT_DIM, TEXT_OFF, WARN, OK, ERR.
# There is NO theme.HOVER, NO theme.MUTED, NO theme.WARNING — use rgba()
# literals for hover (matching existing stylesheet patterns) and TEXT_DIM /
# WARN respectively.
CATEGORY_COLORS = {
    "TAB":  theme.ACCENT,
    "ACT":  theme.WARN,
    "ARCH": theme.ACCENT_LT,
    "DECK": theme.OK,
    "CARD": theme.ACCENT2,
}


class _ResultRow(QFrame):
    """Single result row: [TAG] name / secondary."""

    def __init__(self, entry: PaletteEntry):
        super().__init__()
        self.entry = entry
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        tag = QLabel(entry.category)
        tag.setFixedWidth(48)
        tag.setStyleSheet(
            f"color: {CATEGORY_COLORS.get(entry.category, theme.TEXT_DIM)};"
            f" font-size: 10px; font-weight: 600;"
        )
        text = QWidget()
        text_lay = QVBoxLayout(text)
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(0)
        name_lbl = QLabel(entry.name)
        name_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        text_lay.addWidget(name_lbl)
        if entry.secondary:
            sec_lbl = QLabel(entry.secondary)
            sec_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            text_lay.addWidget(sec_lbl)
        layout.addWidget(tag)
        layout.addWidget(text, 1)


class CommandPalette(QDialog):
    def __init__(
        self,
        registry: PaletteRegistry,
        recents_provider: Callable[[], list[str]],
        recents_writer: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self._registry = registry
        self._recents_provider = recents_provider
        self._recents_writer = recents_writer
        self._setup_ui()
        self._refresh_results("")

    def _setup_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setModal(True)
        self.setFixedSize(600, 400)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type to search — prefixes: > actions  # tabs  @ archetypes  : decks  c: cards")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {theme.TEXT};"
            f" border: none; border-bottom: 1px solid {theme.BORDER};"
            f" padding: 12px; font-size: 14px; }}"
        )
        self.input.textChanged.connect(self._refresh_results)
        layout.addWidget(self.input)

        self.list_widget = QListWidget()
        # Selected-item style matches the existing stylesheet pattern (see
        # gui/theme.py: QTableWidget::item:selected uses
        # `rgba(94, 181, 207, 0.15)` with color ACCENT_LT).
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; }}"
            f" QListWidget::item:selected {{"
            f"   background: rgba(94, 181, 207, 0.15);"
            f"   color: {theme.ACCENT_LT};"
            f" }}"
        )
        self.list_widget.itemActivated.connect(self._on_activate)
        layout.addWidget(self.list_widget)

    def _refresh_results(self, query: str) -> None:
        self.list_widget.clear()
        if not query:
            recents = self._registry.prune_recents(self._recents_provider())
            entries = [self._registry.get(rid) for rid in recents[:5]]
            entries = [e for e in entries if e is not None]
            if not entries:
                entries = self._registry.search("", limit=8)
        else:
            entries = self._registry.search(query, limit=8)

        for e in entries:
            row = _ResultRow(e)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, e.id)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.list_widget.currentItem()
            if current is not None:
                self._on_activate(current)
            return
        if key == Qt.Key.Key_Down:
            row = min(self.list_widget.currentRow() + 1, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(row)
            return
        if key == Qt.Key.Key_Up:
            row = max(self.list_widget.currentRow() - 1, 0)
            self.list_widget.setCurrentRow(row)
            return
        super().keyPressEvent(event)

    def _on_activate(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        entry = self._registry.get(entry_id)
        if entry is None:
            self.accept()
            return
        self._recents_writer(entry_id)
        self.accept()
        # Defer handler call until after the dialog has actually closed,
        # so handlers that open another modal don't fight the palette's focus.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, entry.handler)
```

- [ ] **Step 5.2: Verify it imports cleanly**

```bash
python -c "from gui.widgets.command_palette import CommandPalette; print('ok')"
```

Expected: `ok`. If `theme.HOVER` or `theme.MUTED` don't exist, fall back to `theme.BG` and a hardcoded `#888` respectively — verify by grep'ing `gui/theme.py` and adjusting the stylesheet strings.

- [ ] **Step 5.3: Commit**

```bash
git add gui/widgets/command_palette.py
git commit -m "feat(palette): CommandPalette QDialog widget"
```

---

## Task 6: Main window integration — Ctrl+K + UIState + populate registry

**Files:**
- Modify: `gui/main_window.py`
- Create: `gui/widgets/_palette_actions.py`

- [ ] **Step 6.1: Write `gui/widgets/_palette_actions.py`**

This module owns registration of `ACT:*` (action) entries that depend on MainWindow context. Keeping it separate from `command_palette.py` keeps the widget logic-free.

```python
"""Action registration for the command palette.

Called once from MainWindow.__init__ after tabs are built. Each function
adds a set of entries to the registry, with handlers that close over the
MainWindow instance.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from gui.widgets.palette_registry import PaletteEntry, PaletteRegistry

if TYPE_CHECKING:
    from gui.main_window import MainWindow


def register_tab_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Walk the QTabWidget tree and register every leaf tab as TAB:..."""
    root = window._tabs  # verified: top-level QTabWidget in MainWindow (main_window.py:129)

    def _walk(tabs, path_prefix: str) -> None:
        for i in range(tabs.count()):
            child = tabs.widget(i)
            label = tabs.tabText(i)
            path = f"{path_prefix}/{label}" if path_prefix else label
            from PyQt6.QtWidgets import QTabWidget
            if isinstance(child, QTabWidget):
                _walk(child, path)
            else:
                slug = path.lower().replace(" ", "-").replace("/", "-")
                entry_id = f"tab:{slug}"
                def make_handler(p=path, t=tabs, idx=i):
                    return lambda: window.activate_tab_by_path(p)
                reg.register(PaletteEntry(
                    id=entry_id, category="TAB",
                    name=f"Jump to {path}", secondary="",
                    handler=make_handler(),
                ))

    _walk(root, "")


def register_action_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Register built-in ACT:* entries."""
    reg.register(PaletteEntry(
        id="act:refresh-current-tab", category="ACT",
        name="Refresh current tab", secondary="Same as F5",
        handler=window._refresh_current_tab,
    ))
    reg.register(PaletteEntry(
        id="act:open-settings", category="ACT",
        name="Open Settings", secondary="",
        handler=lambda: window.activate_tab_by_path("Settings"),
    ))
    reg.register(PaletteEntry(
        id="act:reset-ui-state", category="ACT",
        name="Reset UI state", secondary="Clears persisted selections/filters",
        handler=window.reset_ui_state,
    ))
    for fmt in ("standard", "modern", "pioneer", "legacy", "pauper"):
        reg.register(PaletteEntry(
            id=f"act:format-{fmt}", category="ACT",
            name=f"Set format → {fmt.title()}", secondary="",
            handler=lambda f=fmt: window.set_format(f),
        ))


def register_archetype_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Enumerate distinct archetypes from the decks table and register ARCH:*.

    `analysis/archetypes.py` does NOT expose a public "list all archetypes"
    function (only `merge_archetypes()`, `pre_normalize()`, `ALIASES`).
    Source-of-truth archetype names come from the decks table directly.
    The window argument is currently unused here — kept for symmetry with
    other registrars in case the handler later needs window context.
    """
    try:
        from db.database import get_combined_connection
        conn = get_combined_connection()
        cur = conn.execute(
            "SELECT DISTINCT archetype FROM decks "
            "WHERE archetype IS NOT NULL AND archetype != '' "
            "ORDER BY archetype"
        )
        names = [row[0] for row in cur]
    except Exception:
        return
    for name in names:
        slug = name.lower().replace(" ", "-")
        reg.register(PaletteEntry(
            id=f"arch:{slug}", category="ARCH",
            name=name, secondary="",
            handler=lambda n=name: window.open_archetype_detail(n),
        ))


def register_deck_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Enumerate saved_decks rows and register DECK:* entries.

    Verified signature: `db.saved_decks.get_decks(format_name: str = None)
    -> list[dict]`. Each dict has keys 'id', 'name', 'format', 'archetype',
    'mainboard', 'sideboard', 'notes', 'created_at' (see save_deck schema
    in db/saved_decks.py).
    """
    try:
        from db.saved_decks import get_decks
        rows = get_decks()
    except Exception:
        return
    for row in rows:
        deck_id = row["id"]
        name = row["name"]
        reg.register(PaletteEntry(
            id=f"deck:{deck_id}", category="DECK",
            name=name, secondary=f"id={deck_id}",
            handler=lambda d=deck_id: window.open_saved_deck(d),
        ))


def register_card_entries(reg: PaletteRegistry) -> None:
    """Enumerate card_data names (large) and register CARD:* entries.

    Card category is gated behind c: prefix in the registry; registering
    all ~32k is fine because thefuzz only scores when a query is present.
    """
    try:
        import sqlite3
        from db.database import get_combined_connection
        conn = get_combined_connection()
        cur = conn.execute("SELECT name FROM card_data")
        for (name,) in cur:
            slug = name.lower().replace(" ", "-").replace(",", "")[:60]
            reg.register(PaletteEntry(
                id=f"card:{slug}", category="CARD",
                name=name, secondary="",
                handler=lambda n=name: None,  # TODO wire to card browser
            ))
    except Exception:
        return


def register_all(reg: PaletteRegistry, window: "MainWindow") -> None:
    register_tab_entries(reg, window)
    register_action_entries(reg, window)
    register_archetype_entries(reg, window)
    register_deck_entries(reg, window)
    register_card_entries(reg)
```

**Note on `register_archetype_entries` and `register_deck_entries`:** these import from `analysis.archetypes` and `db.saved_decks`. Before this step, grep to confirm function names — if `all_archetype_names()` doesn't exist, use the actual archetype enumeration call (likely `get_archetypes(format=...)` from `db/database.py` or similar). Same for `list_saved_decks`. Fall back to `try/except: return` if the lookup is unclear — registering archetypes/decks is non-critical for the palette to ship.

- [ ] **Step 6.2: Modify `gui/main_window.py` — add UIState, palette wiring, and helper methods**

Insert imports near the top of the file (after the existing `from gui.worker_threads ...` line):

```python
from gui.state import UIState
from gui.widgets.palette_registry import PaletteRegistry
from gui.widgets.command_palette import CommandPalette
from gui.widgets._palette_actions import register_all as _palette_register_all
```

Inside `MainWindow.__init__`, after `theme.apply_theme(...)`:

```python
        # Persisted UI state singleton — used by tabs for filter persistence
        self.ui_state = UIState.instance()

        # Command palette — populated after _build_ui()
        self._palette_registry = PaletteRegistry()
```

After `self._build_ui()` and before `QTimer.singleShot(...)`:

```python
        # Populate palette registry (tabs must exist by now)
        _palette_register_all(self._palette_registry, self)

        # Ctrl+K opens palette
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_palette)

        # Restore last active tab path, if any
        last_path = self.ui_state.get("global.last_active_tab_path")
        if last_path:
            self.activate_tab_by_path(last_path)
```

Add these methods to `MainWindow` (anywhere after `__init__`):

```python
    # --- Palette helpers ---

    def _open_palette(self) -> None:
        dlg = CommandPalette(
            self._palette_registry,
            recents_provider=lambda: self.ui_state.get("palette_recents", []) or [],
            recents_writer=self._record_palette_recent,
            parent=self,
        )
        dlg.exec()

    def _record_palette_recent(self, entry_id: str) -> None:
        recents = self.ui_state.get("palette_recents", []) or []
        recents = [r for r in recents if r != entry_id]
        recents.insert(0, entry_id)
        self.ui_state.set("palette_recents", recents[:20])

    # --- Tab navigation helpers (used by palette handlers) ---

    def activate_tab_by_path(self, path: str) -> None:
        """e.g. 'Decks/My Decks' → switch top-level Decks then sub-tab My Decks."""
        parts = path.split("/")
        from PyQt6.QtWidgets import QTabWidget
        node = self._tabs
        for part in parts:
            for i in range(node.count()):
                if node.tabText(i) == part:
                    node.setCurrentIndex(i)
                    if isinstance(node.widget(i), QTabWidget):
                        node = node.widget(i)
                    break
        self.ui_state.set("global.last_active_tab_path", path)

    def set_format(self, fmt: str) -> None:
        self.ui_state.set("global.format", fmt)
        # Tabs hydrate from this on their next showEvent. Trigger a refresh
        # so the currently visible tab reflects the change immediately.
        self._refresh_current_tab()

    def open_archetype_detail(self, archetype_name: str) -> None:
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        dlg = ArchetypeDetailDialog(archetype_name, parent=self)
        dlg.exec()

    def open_saved_deck(self, deck_id: int) -> None:
        self.activate_tab_by_path("Decks/My Decks")
        my_decks = self._find_tab("My Decks")
        if my_decks is not None and hasattr(my_decks, "select_deck_by_id"):
            my_decks.select_deck_by_id(deck_id)

    def _find_tab(self, name: str):
        """Walk QTabWidget tree, return first widget whose tabText matches name."""
        from PyQt6.QtWidgets import QTabWidget
        def _walk(tabs):
            for i in range(tabs.count()):
                if tabs.tabText(i) == name:
                    return tabs.widget(i)
                child = tabs.widget(i)
                if isinstance(child, QTabWidget):
                    found = _walk(child)
                    if found is not None:
                        return found
            return None
        return _walk(self._tabs)

    def reset_ui_state(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Reset UI state",
            "Clear all persisted selections, filters, palette recents?\n"
            "(Format / API key / scrape preferences are NOT affected.)"
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.ui_state.reset()
            self.ui_state.flush()
```

**On exit** (find the existing `closeEvent` method or add one if missing):

```python
    def closeEvent(self, event):
        try:
            self.ui_state.flush()
        except Exception:
            pass
        super().closeEvent(event)
```

**Verified 2026-05-13:** The top-level `QTabWidget` in `MainWindow._build_ui()` is named `self._tabs` (line 129 of `gui/main_window.py`). The nested tab containers are `self._meta_tab`, `self._decks_tab`, `self._tournament_tab`, `self._resources_tab`. The `_refresh_current_tab` method already exists and walks the tree — your `act:refresh-current-tab` handler can call it directly.

- [ ] **Step 6.3: Manual smoke test — palette opens**

```bash
python run_gui.py
```

Open the GUI. Press **Ctrl+K**. Palette appears centered. Type "dash" — "Jump to Dashboard" highlighted. Press Enter — palette closes, Dashboard tab activates. Press Ctrl+K again — palette appears; if Recents is empty it shows top tabs sorted by category priority.

- [ ] **Step 6.4: Commit**

```bash
git add gui/main_window.py gui/widgets/_palette_actions.py
git commit -m "feat(gui): wire Ctrl+K palette + UIState into MainWindow"
```

---

## Task 7: Per-tab sticky state — Dashboard + My Decks

These two are the highest-value persistence slices (Tokyo Prowess deck pre-select on launch is the headline win).

**Files:**
- Modify: `gui/tabs/dashboard.py`
- Modify: `gui/tabs/my_decks.py`

**Important context (verified 2026-05-13):** Format and timeframe selectors are **per-tab**, not global. The dashboard's timeframe widget is `self._tf` (a `QComboBox` populated from `theme.TIMEFRAME_OPTIONS`; default text `theme.TIMEFRAME_DEFAULT = "2 weeks"`; `currentIndexChanged` signal wired to `self._schedule_refresh()`). See `gui/tabs/dashboard.py` line ~272. Persistence respects that reality: each tab persists its own slice. No cross-tab broadcast.

The archetype selector widget on Dashboard is not visible by name from a top-level grep. Step 7.1 below shows the persistence pattern; **the executor must grep `gui/tabs/dashboard.py` for `QComboBox` and the existing archetype-population code (look near `_load_dashboard`, `_populate_popularity`) to find the actual attribute name**. If the dashboard archetype widget does not exist as a single combo (e.g. selection happens via clicking a row in a `QTableWidget` instead), drop the `selected_archetype` persistence for v1 and replace with whatever single-value selection the user actually controls.

- [ ] **Step 7.1: Dashboard hydration — timeframe (verified) + archetype (grep-confirm)**

Add a `showEvent` override to `DashboardTab` (top of class, after `__init__`):

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        self._hydrate_from_state()
        self._hydrated_state = True

    def _hydrate_from_state(self) -> None:
        from gui.state import UIState
        state = UIState.instance()
        # Timeframe — verified: self._tf is a QComboBox storing text values
        # like "2 weeks" / "4 weeks" / "All Time"
        tf = state.get("tabs.dashboard.timeframe")
        if tf and hasattr(self, "_tf"):
            self._tf.blockSignals(True)
            idx = self._tf.findText(tf)
            if idx >= 0:
                self._tf.setCurrentIndex(idx)
            self._tf.blockSignals(False)
        # Archetype — GREP-CONFIRM: open dashboard.py, search for "QComboBox"
        # populated with archetype names. If named `self._arch_combo` (or
        # similar), uncomment and rename below:
        # arch = state.get("tabs.dashboard.selected_archetype")
        # if arch and hasattr(self, "_arch_combo"):
        #     self._arch_combo.blockSignals(True)
        #     idx = self._arch_combo.findText(arch)
        #     if idx >= 0:
        #         self._arch_combo.setCurrentIndex(idx)
        #     self._arch_combo.blockSignals(False)
        # If dashboard archetype is selected via QTableWidget row instead,
        # skip persistence for v1 and document in spec follow-ups.
```

Wire persistence — at the bottom of `_build_ui` (or wherever `self._tf` is created — line ~272), add:

```python
        from gui.state import UIState
        self._tf.currentTextChanged.connect(
            lambda txt: UIState.instance().set("tabs.dashboard.timeframe", txt)
        )
        # For the archetype combo (after grep-confirming attribute name):
        # self._arch_combo.currentTextChanged.connect(
        #     lambda txt: UIState.instance().set("tabs.dashboard.selected_archetype", txt)
        # )
```

- [ ] **Step 7.2: My Decks hydration**

In `gui/tabs/my_decks.py`, find the deck list widget. `MyDecksTab` is a god node (37 edges per graph report); grep for `QListWidget` and `setData(Qt.ItemDataRole.UserRole`. The standard pattern is `item.setData(Qt.ItemDataRole.UserRole, deck["id"])` somewhere in the deck-population code.

Add `select_deck_by_id` (called by `MainWindow.open_saved_deck`), `showEvent` hydration, and selection persistence:

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated", False):
            return
        from gui.state import UIState
        deck_id = UIState.instance().get("tabs.my_decks.selected_deck_id")
        if deck_id is not None:
            self.select_deck_by_id(deck_id)
        self._hydrated = True

    def select_deck_by_id(self, deck_id: int) -> bool:
        """Select the deck row matching deck_id. Returns True if found."""
        # Find the QListWidget item whose stored ID == deck_id, set as current.
        # Implementation depends on existing list-population code — typical
        # pattern is item.setData(Qt.ItemDataRole.UserRole, deck_id).
        if not hasattr(self, "_deck_list"):
            return False
        for i in range(self._deck_list.count()):
            item = self._deck_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == deck_id:
                self._deck_list.setCurrentRow(i)
                return True
        return False
```

Connect the list's `currentItemChanged` to persist:

```python
        self._deck_list.currentItemChanged.connect(self._persist_selected_deck)

    def _persist_selected_deck(self, current, _previous):
        from gui.state import UIState
        if current is None:
            return
        deck_id = current.data(Qt.ItemDataRole.UserRole)
        if deck_id is not None:
            UIState.instance().set("tabs.my_decks.selected_deck_id", deck_id)
```

- [ ] **Step 7.3: Manual smoke**

Launch GUI. On Dashboard, pick "Izzet Prowess" from archetype dropdown. Switch to another tab. Switch back to Dashboard — selection persists. Close app, relaunch — selection still persists.

On My Decks, click Tokyo Prowess (id=17). Switch tabs. Switch back — deck still selected. Close app, relaunch — same.

- [ ] **Step 7.4: Commit**

```bash
git add gui/tabs/dashboard.py gui/tabs/my_decks.py
git commit -m "feat(gui): sticky state for Dashboard archetype + My Decks selection"
```

---

## Task 8: Per-tab sticky state — Charts, Heatmap, Scout

Three tabs, same pattern. Each step shows the full code (no "same as above") because the widget names differ per tab and the executor may work them out of order.

**Files:**
- Modify: `gui/tabs/charts.py`
- Modify: `gui/tabs/heatmap_tab.py`
- Modify: `gui/tabs/scout.py`

**Pattern recap:**
1. Override `showEvent`. Guard with `_hydrated_state` flag so we only hydrate once per session.
2. Read each persisted field via `UIState.instance().get("tabs.<tab>.<field>", default)`.
3. Apply to widget with `blockSignals(True)` / `False` wrapping.
4. Connect the widget's change signal to a one-line lambda that calls `UIState.instance().set(...)`.

For Tasks 8.1-8.3, **first** grep the target file for `QComboBox`, `QListWidget`, `QSpinBox` and confirm the actual attribute names. The names below are this plan's best-guess; rename inline if they differ.

- [ ] **Step 8.1: Charts (`gui/tabs/charts.py`)**

Expected widgets: `self._tf` (timeframe combo, same pattern as Dashboard), `self._chart_type_combo` (chart type), `self._arch_list` (archetype multi-select; likely `QListWidget` with checkable items).

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        from gui.state import UIState
        state = UIState.instance()

        # Timeframe
        tf = state.get("tabs.charts.timeframe")
        if tf and hasattr(self, "_tf"):
            self._tf.blockSignals(True)
            idx = self._tf.findText(tf)
            if idx >= 0:
                self._tf.setCurrentIndex(idx)
            self._tf.blockSignals(False)

        # Chart type
        chart_type = state.get("tabs.charts.chart_type")
        if chart_type and hasattr(self, "_chart_type_combo"):
            self._chart_type_combo.blockSignals(True)
            idx = self._chart_type_combo.findText(chart_type)
            if idx >= 0:
                self._chart_type_combo.setCurrentIndex(idx)
            self._chart_type_combo.blockSignals(False)

        # Archetypes (multi-select via QListWidget checkable items)
        archs = state.get("tabs.charts.archetypes", [])
        if archs and hasattr(self, "_arch_list"):
            self._arch_list.blockSignals(True)
            from PyQt6.QtCore import Qt
            for i in range(self._arch_list.count()):
                item = self._arch_list.item(i)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        Qt.CheckState.Checked if item.text() in archs
                        else Qt.CheckState.Unchecked
                    )
            self._arch_list.blockSignals(False)

        self._hydrated_state = True
```

Wire persistence — after each widget is created in `_build_ui`:

```python
        from gui.state import UIState
        self._tf.currentTextChanged.connect(
            lambda txt: UIState.instance().set("tabs.charts.timeframe", txt)
        )
        self._chart_type_combo.currentTextChanged.connect(
            lambda txt: UIState.instance().set("tabs.charts.chart_type", txt)
        )
        self._arch_list.itemChanged.connect(self._persist_charts_archetypes)

    def _persist_charts_archetypes(self, _item):
        from PyQt6.QtCore import Qt
        from gui.state import UIState
        checked = [
            self._arch_list.item(i).text()
            for i in range(self._arch_list.count())
            if self._arch_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        UIState.instance().set("tabs.charts.archetypes", checked)
```

- [ ] **Step 8.2: Heatmap (`gui/tabs/heatmap_tab.py`)**

Expected widgets: `self._top_n_spin` (QSpinBox for top-N), `self._source_combo` (QComboBox for data-source filter — "all" / "real" / "scraped" / "untapped").

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        from gui.state import UIState
        state = UIState.instance()

        top_n = state.get("tabs.matchup_data.top_n")
        if top_n is not None and hasattr(self, "_top_n_spin"):
            self._top_n_spin.blockSignals(True)
            self._top_n_spin.setValue(int(top_n))
            self._top_n_spin.blockSignals(False)

        src = state.get("tabs.matchup_data.source_filter")
        if src and hasattr(self, "_source_combo"):
            self._source_combo.blockSignals(True)
            idx = self._source_combo.findText(src)
            if idx >= 0:
                self._source_combo.setCurrentIndex(idx)
            self._source_combo.blockSignals(False)

        self._hydrated_state = True
```

Persistence:

```python
        from gui.state import UIState
        self._top_n_spin.valueChanged.connect(
            lambda v: UIState.instance().set("tabs.matchup_data.top_n", int(v))
        )
        self._source_combo.currentTextChanged.connect(
            lambda txt: UIState.instance().set("tabs.matchup_data.source_filter", txt)
        )
```

- [ ] **Step 8.3: Scout (`gui/tabs/scout.py`)**

Expected widgets: `self._days_spin` (QSpinBox for days-window), `self._target_list` (QListWidget for target archetypes).

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        from gui.state import UIState
        state = UIState.instance()

        days = state.get("tabs.scout.days")
        if days is not None and hasattr(self, "_days_spin"):
            self._days_spin.blockSignals(True)
            self._days_spin.setValue(int(days))
            self._days_spin.blockSignals(False)

        targets = state.get("tabs.scout.target_archetypes", [])
        if targets and hasattr(self, "_target_list"):
            self._target_list.blockSignals(True)
            from PyQt6.QtCore import Qt
            for i in range(self._target_list.count()):
                item = self._target_list.item(i)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        Qt.CheckState.Checked if item.text() in targets
                        else Qt.CheckState.Unchecked
                    )
            self._target_list.blockSignals(False)

        self._hydrated_state = True
```

Persistence:

```python
        from gui.state import UIState
        self._days_spin.valueChanged.connect(
            lambda v: UIState.instance().set("tabs.scout.days", int(v))
        )
        self._target_list.itemChanged.connect(self._persist_scout_targets)

    def _persist_scout_targets(self, _item):
        from PyQt6.QtCore import Qt
        from gui.state import UIState
        checked = [
            self._target_list.item(i).text()
            for i in range(self._target_list.count())
            if self._target_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        UIState.instance().set("tabs.scout.target_archetypes", checked)
```

- [ ] **Step 8.4: Manual smoke**

For each of the three tabs: set a non-default value (Charts: pick a chart-type + check 2-3 archetypes; Heatmap: change top-N to 20 and source to "real"; Scout: change days to 30). Switch away and back → preserved. Close app and relaunch → still preserved.

If any widget name doesn't match (e.g. `_arch_list` is actually `_archetype_list`), update the attribute reference and re-run the smoke for that tab.

- [ ] **Step 8.5: Commit**

```bash
git add gui/tabs/charts.py gui/tabs/heatmap_tab.py gui/tabs/scout.py
git commit -m "feat(gui): sticky state for Charts, Heatmap, Scout selectors"
```

---

## Task 9: Reset path — Settings button + final docs

**Files:**
- Modify: `gui/tabs/settings.py`
- Modify: `CLAUDE.md` (add section about UIState / palette)
- Modify: `NEXT_STEPS.md` (mark item complete; add follow-ups)

- [ ] **Step 9.1: Settings tab "Reset UI state" button**

In `gui/tabs/settings.py`, add a button near other reset/refresh controls:

```python
from PyQt6.QtWidgets import QPushButton

# Inside _build_ui or equivalent:
        reset_state_btn = QPushButton("Reset UI state")
        reset_state_btn.setToolTip(
            "Clear persisted selections, filters, palette recents.\n"
            "Does not affect format / API key / scrape preferences."
        )
        reset_state_btn.clicked.connect(self._on_reset_ui_state)
        # Append to the same layout as the other action buttons

    def _on_reset_ui_state(self):
        from gui.state import UIState
        from PyQt6.QtWidgets import QMessageBox
        ok = QMessageBox.question(
            self, "Reset UI state",
            "Clear persisted selections, filters, and palette recents?"
        )
        if ok == QMessageBox.StandardButton.Yes:
            UIState.instance().reset()
            UIState.instance().flush()
            QMessageBox.information(self, "Reset", "UI state cleared.")
```

- [ ] **Step 9.2: Update `CLAUDE.md` — add a "Persisted UI state" subsection under Section 6 (GUI)**

Append this paragraph after the "Timeframe System" subsection:

```markdown
### Persisted UI state
`gui/state.py::UIState` is a singleton wrapping `data/preferences.json` under a `ui_state` key. Tabs hydrate from it in `showEvent` (with `blockSignals(True)` to avoid loops) and persist on widget change. Slices today: `global.last_active_tab_path`, plus **per-tab** selections — Dashboard timeframe + archetype, My Decks selected deck, Charts timeframe + archetypes + chart-type, Heatmap top-N + source filter, Scout days + target archetypes. Format/timeframe are per-tab (not global broadcast) because the current GUI architecture has per-tab selectors. Schema-tolerant (`get(path, default)` always returns the default). Reset via palette `> Reset UI state` or Settings button.

### Command palette
**Ctrl+K** opens `gui/widgets/command_palette.py::CommandPalette`. Fuzzy-searches `gui/widgets/palette_registry.py::PaletteRegistry`, populated at startup by `gui/widgets/_palette_actions.py::register_all`. Categories: TAB / ARCH / DECK / CARD / ACT. Prefixes: `>` actions, `#` tabs, `@` archetypes, `:` decks, `c:` cards. Recents persisted in `ui_state.palette_recents` (top 20, stale entries pruned by `PaletteRegistry.prune_recents`).
```

- [ ] **Step 9.3: Update `NEXT_STEPS.md`**

Move the "GUI ergonomics — Direction A" line from `### UI/UX` open-priorities to a new `## RECENTLY COMPLETED (2026-05-13)` subsection. Add a follow-up line:

```markdown
- [ ] Direction C arc — design language pass + tab reorganization.
      Drive priorities from one week of palette recents data + sticky-state
      slices that prove demand. Spec to be written after 2026-05-20.
```

- [ ] **Step 9.4: Full manual smoke checklist**

Run through this list. Any failure → fix before committing.

1. Launch app. Press Ctrl+K. Palette opens centered.
2. Type "izzet prowess" — `arch:izzet-prowess` appears, press Enter — Archetype Detail dialog opens.
3. Close dialog. Ctrl+K. Type "@izzet" — only ARCH entries match. Type "#dash" — only TAB entries. Type ">refresh" — only ACT entries. Type ":tokyo" — only DECK entries. Type "c:sheoldred" — Sheoldred card appears.
4. Type "x" with no prefix — empty or low-relevance non-card results only; no cards drown the list.
5. Ctrl+K with empty input — Recents (or default sorted tabs) show.
6. From Dashboard, pick "Izzet Prowess" in archetype dropdown. Switch to Charts tab and back to Dashboard — selection persists.
7. From My Decks, click Tokyo Prowess (id=17). Switch tabs and back — selection persists.
8. Close app entirely. Relaunch. The last active tab is restored. Dashboard archetype + My Decks selection still pinned.
9. From palette, run `> Reset UI state`. Confirm. Close app. Relaunch. Defaults are back.
10. Manually corrupt `data/preferences.json` by adding garbage text. Launch app — it should launch without crashing; default state applies. Restore the file from git.

- [ ] **Step 9.5: Commit + push**

```bash
git add gui/tabs/settings.py CLAUDE.md NEXT_STEPS.md
git commit -m "$(cat <<'EOF'
feat(gui): GUI quick-wins ship complete (palette + sticky state)

Direction A of the GUI ergonomics arc. Ctrl+K palette over tabs /
archetypes / saved decks / cards / actions with fuzzy match + prefixes.
Persisted UI state (format / timeframe / per-tab selections) across
switches and restarts. Reset path via palette action + Settings button.

Spec: docs/superpowers/specs/2026-05-13-gui-palette-sticky-state-design.md
Plan: docs/superpowers/plans/2026-05-13-gui-palette-sticky-state.md

Direction C (design system pass + tab reorganization) queued; will be
informed by one week of palette-recents usage data.
EOF
)"
git push
```

---

## Self-review

**Spec coverage check:**
- Spec §1 (Goal): Tasks 1-9 cover. ✓
- Spec §2 (Scope: in) — palette: Tasks 3-6. UIState: Tasks 1-2. Hooks into main_window: Task 6. Per-tab state: Tasks 7-8. Reset path: Task 9. ✓
- Spec §3 (Architecture diagram): Wiring in Task 6. ✓
- Spec §4 (Section 1 — Palette): behavior (Task 5), registry (Tasks 3-4), action registry (Task 6), fuzzy matching (Task 4), prefixes (Task 4), context-awareness (Task 4 via `context_predicate`), tab-reorg stability (Task 6 dynamic walk + stable IDs). ✓
- Spec §5 (Section 2 — Sticky state): storage (Task 2), API (Task 2), hydration (Tasks 7-8), persistence (Tasks 7-8), persisted slices (Tasks 7-8), edge cases (Tasks 1-2 + 7-8). ✓
- Spec §6 (Testing approach): unit for UIState (Task 1-2) + registry (Tasks 3-4). Manual smoke for Qt (Tasks 6, 7, 8, 9). ✓
- Spec §7 (Imperfections): static action registry — Task 6 handles dynamic tab walking; manual registry is acknowledged. Other imperfections persist as future work, no task needed.

**Placeholder scan:** One TODO comment in Task 6's card handler (`lambda n=name: None,  # TODO wire to card browser`) — this is deliberate scope deferral (Card Browser wire-up is a v2 polish; v1 cards in palette are searchable but selecting one is a no-op). Acceptable per the spec's "out of scope: no Scryfall live fallback" framing. No other TBDs / TODOs / "..." placeholders are load-bearing.

**Type consistency:** `UIState.get/set/reset/flush` consistent across Tasks 1, 2, 6, 7, 8, 9. `PaletteEntry` fields stable across Tasks 3-6. `PaletteRegistry.register/unregister/get/has/search/prune_recents` consistent across Tasks 3-6.

**Verified in main_window.py:** top-level QTabWidget is `self._tabs`; sub-tabs are `self._meta_tab`, `self._decks_tab`, `self._tournament_tab`, `self._resources_tab`. Refresh method is `_refresh_current_tab`. `db.saved_decks.get_decks()` returns `list[dict]` with `id`/`name`/`format`/`archetype` keys. Dashboard timeframe widget is `self._tf` (QComboBox, `theme.TIMEFRAME_OPTIONS`, default `"2 weeks"`).

**v2 revisions applied 2026-05-13 from advisor pass:**
- Dropped `global.format` / `global.timeframe` from persistence — format/timeframe are per-tab in the current GUI (each tab owns its own combo). Persistence respects that.
- Card-prefix gating simplified: cards always behind `c:` only; no ≥2-char fallback. Empty-state placeholder text hints at the prefix.
- Theme tokens corrected — `theme.HOVER` / `theme.MUTED` / `theme.WARNING` don't exist; use `theme.SURFACE`/`theme.TEXT_DIM`/`theme.WARN` plus the existing `rgba(94, 181, 207, 0.15)` hover pattern.
- `self.tabs` → `self._tabs` everywhere.
- `analysis.archetypes.all_archetype_names()` was fictional; replaced with `SELECT DISTINCT archetype FROM decks` via `get_combined_connection()`.
- `db.saved_decks.list_saved_decks()` → `db.saved_decks.get_decks()` (verified signature).
- `pytest` added to requirements.txt at Step 1.0 (was missing).
- Per-tab task code is now repeated explicitly per tab in Task 8, not "same pattern as above".

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-13-gui-palette-sticky-state.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task (9 tasks), review between tasks, fast iteration. Best for plans where tasks have crisp boundaries and the engineer benefits from a clean context per task.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Faster total wall time but my context fills up over the session.

Which approach?
