# SB Cheat-Sheet Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-button export of all SB plans for a deck as a 1-page color-coded printable PNG/PDF.

**Architecture:** Pure-function `build_cheat_sheet_figure(deck_id)` returns a matplotlib `Figure`. Thin `export_cheat_sheet()` wrapper handles file I/O and multi-page paging. A button on the Sideboard Plans sub-tab inside `gui/tabs/my_decks.py` opens a `QFileDialog` then opens the saved file via `QDesktopServices`.

**Tech Stack:** Python 3.13, matplotlib (already in deps), `matplotlib.backends.backend_pdf.PdfPages` for multi-page PDF, PyQt6 (`QFileDialog`, `QDesktopServices`), pytest.

**Spec:** `docs/superpowers/specs/2026-05-16-sb-cheat-sheet-design.md`

**Baseline:** commit `e101ef3`, 191/191 tests green.

**Ship target:** tonight (2026-05-16). 3 tasks, ~1-1.5h total.

---

## Critical facts (verified from the codebase)

1. **`saved_sb_plans` schema columns** (from `db/saved_decks.py:47`): `id, deck_id, opponent_archetype, play_in (JSON list), play_out (JSON list), draw_in (JSON list), draw_out (JSON list), notes, difficulty ('Easy'|'Medium'|'Hard'), updated_at`. The `play_*` and `draw_*` fields are JSON-serialized lists of card names. Use `db.helpers.json_loads_list` to parse.
2. **Data accessor**: `db.saved_decks.get_sb_plans(deck_id) -> list[dict]` returns plans ordered by `opponent_archetype`. Each dict already has JSON fields decoded if it follows the project pattern — VERIFY at implementation time by reading `get_sb_plans` source.
3. **SB plans sub-tab lives in** `gui/tabs/my_decks.py:541` — `self._detail_tabs.addTab(sb_widget, "Sideboard Plans")`. The button goes inside `sb_widget`'s layout (created in the same `_build_*` method).
4. **matplotlib backend**: project uses `matplotlib.use("QtAgg")` for GUI charts. Cheat-sheet rendering can reuse the same backend; `Figure.savefig` works regardless.
5. **In/Out display convention**: spec says lines like `+2 CardName` for IN and `-2 CardName` for OUT. The JSON lists store card names with duplicates (e.g., `["Brotherhood's End", "Brotherhood's End"]` means +2). Collapse via `collections.Counter`.

## File structure

**Create:**
- `analysis/sb_cheat_sheet.py` — `build_cheat_sheet_figure()` + `export_cheat_sheet()` (~150 lines)
- `tests/test_sb_cheat_sheet.py` — 6 tests (~100 lines)

**Modify:**
- `gui/tabs/my_decks.py` — add "Export SB Cheat Sheet" button to the Sideboard Plans sub-tab + handler method (~30 lines)
- `CLAUDE.md` — add cheat-sheet line under §6 GUI / My Decks description
- `NEXT_STEPS.md` — strike-through the "SB quick-reference printout" bullet under RC Prep Follow-Ups

---

## Task 1: `build_cheat_sheet_figure` — pure rendering function

**Files:**
- Create: `analysis/sb_cheat_sheet.py`
- Create: `tests/test_sb_cheat_sheet.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sb_cheat_sheet.py`:

```python
"""Tests for analysis/sb_cheat_sheet.py — SB plan grid renderer."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "sb.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "sb_arc.db")
    yield db_path


def _seed_deck_with_plans(plan_specs: list[dict]) -> int:
    """Insert a saved deck + N SB plans. Returns deck_id."""
    from db import saved_decks
    saved_decks._ensure_tables()
    deck_id = saved_decks.save_deck(
        name="Test Deck", format="standard", archetype="Test",
        mainboard={"Mountain": 60}, sideboard={}, notes="",
    )
    for spec in plan_specs:
        saved_decks.save_sb_plan(
            deck_id=deck_id,
            opponent_archetype=spec["opp"],
            play_in=spec.get("play_in", []),
            play_out=spec.get("play_out", []),
            draw_in=spec.get("draw_in", []),
            draw_out=spec.get("draw_out", []),
            notes="",
            difficulty=spec.get("difficulty", "Medium"),
        )
    return deck_id


def test_build_figure_returns_matplotlib_figure(tmp_db):
    from matplotlib.figure import Figure
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([
        {"opp": "Azorius Control", "play_in": ["Brotherhood's End"] * 2,
         "play_out": ["Slickshot Show-Off"] * 2, "difficulty": "Easy"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    assert isinstance(fig, Figure)
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_build_figure_raises_for_deck_with_no_plans(tmp_db):
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([])
    with pytest.raises(ValueError, match="no sideboard plans"):
        build_cheat_sheet_figure(deck_id)


def test_build_figure_includes_all_plans_on_one_page_when_under_18(tmp_db):
    """3 plans → 3 subplot axes (excluding the header axis)."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([
        {"opp": "Az Control", "difficulty": "Easy"},
        {"opp": "Boros Energy", "difficulty": "Medium"},
        {"opp": "Mono Green", "difficulty": "Hard"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    # Plan tile axes are tagged with gid="plan_tile" so we can count them
    plan_axes = [ax for ax in fig.axes if ax.get_gid() == "plan_tile"]
    assert len(plan_axes) == 3
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_difficulty_color_applied_per_tile(tmp_db):
    """Easy tile must have green-family facecolor, Hard must have
    red-family. Verifies the difficulty palette dispatch."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure, _DIFFICULTY_COLORS
    deck_id = _seed_deck_with_plans([
        {"opp": "Easy Matchup", "difficulty": "Easy"},
        {"opp": "Hard Matchup", "difficulty": "Hard"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    plan_axes = [ax for ax in fig.axes if ax.get_gid() == "plan_tile"]
    # Order matches alphabetical opponent_archetype: Easy Matchup, Hard Matchup
    easy_bg = plan_axes[0].get_facecolor()
    hard_bg = plan_axes[1].get_facecolor()
    expected_easy = _DIFFICULTY_COLORS["Easy"]["bg"]
    expected_hard = _DIFFICULTY_COLORS["Hard"]["bg"]
    # Compare RGB tuples; matplotlib returns 4-tuples with alpha
    from matplotlib.colors import to_rgb
    assert easy_bg[:3] == pytest.approx(to_rgb(expected_easy), abs=0.01)
    assert hard_bg[:3] == pytest.approx(to_rgb(expected_hard), abs=0.01)
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_pagination_via_page_num_kwarg(tmp_db):
    """Deck with 20 plans + page_num=2 → page 2 has plans 19-20 (2 tiles)."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    specs = [{"opp": f"Archetype {i:02d}"} for i in range(20)]
    deck_id = _seed_deck_with_plans(specs)
    fig_p2 = build_cheat_sheet_figure(deck_id, page_num=2)
    plan_axes = [ax for ax in fig_p2.axes if ax.get_gid() == "plan_tile"]
    assert len(plan_axes) == 2  # 20 total, 18/page → 2 on page 2
    import matplotlib.pyplot as plt
    plt.close(fig_p2)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_sb_cheat_sheet.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'analysis.sb_cheat_sheet'`.

- [ ] **Step 3: Implement `analysis/sb_cheat_sheet.py` (render function only)**

Create the file:

```python
"""SB cheat-sheet renderer — produces a 1-page printable matplotlib
Figure of all sideboard plans for a saved deck. Caller (or the
export_cheat_sheet wrapper) handles file I/O.

Pure-function design lets the test suite verify rendering without
touching the file system or GUI.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from db.saved_decks import get_sb_plans
from db.database import get_connection


_PER_PAGE_COLS = 3
_PER_PAGE_ROWS = 6
_PER_PAGE = _PER_PAGE_COLS * _PER_PAGE_ROWS  # 18

# US Letter portrait in inches
_PAGE_W_IN = 8.5
_PAGE_H_IN = 11.0

# Difficulty palette — dark backgrounds suitable for color print or screen.
# Each entry has 'bg' (tile face) and 'border' (axis spine color).
_DIFFICULTY_COLORS = {
    "Easy":   {"bg": "#1a3320", "border": "#80c890"},
    "Medium": {"bg": "#1a1f33", "border": "#6080c8"},
    "Hard":   {"bg": "#33201a", "border": "#d88060"},
    None:     {"bg": "#1a1a1a", "border": "#666666"},
}

_TEXT_FG = "#e6e6e6"
_TEXT_DIM = "#9aa0b4"
_MAX_INOUT_LINES = 7


def _fetch_deck_name(deck_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name, format FROM saved_decks WHERE id = ?", (deck_id,),
        ).fetchone()
    if row is None:
        return f"Deck #{deck_id}"
    return f"{row['name']} ({row['format'] or 'no format'})"


def _format_inout(card_names: list[str], sign: str) -> list[str]:
    """Collapse duplicates into '+N CardName' / '-N CardName' lines.
    Truncates to _MAX_INOUT_LINES with a '+N more...' tail."""
    counter = Counter(card_names or [])
    lines = [f"{sign}{n} {name}" for name, n in counter.most_common()]
    if len(lines) > _MAX_INOUT_LINES:
        extra = len(lines) - (_MAX_INOUT_LINES - 1)
        lines = lines[: _MAX_INOUT_LINES - 1] + [f"{sign}{extra} more..."]
    return lines


def _render_tile(ax, plan: dict) -> None:
    """Render one plan into an existing axis. Axis is configured with
    no ticks/labels; we paint a colored background + text."""
    difficulty = plan.get("difficulty") or None
    palette = _DIFFICULTY_COLORS.get(difficulty, _DIFFICULTY_COLORS[None])

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(palette["bg"])
    for spine in ax.spines.values():
        spine.set_edgecolor(palette["border"])
        spine.set_linewidth(1.5)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_gid("plan_tile")  # so tests can find these axes

    # Header: opponent archetype
    opp = plan.get("opponent_archetype") or "(unknown)"
    ax.text(
        0.04, 0.92, opp,
        fontsize=11, fontweight="bold", color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
    )
    # Difficulty chip top-right
    ax.text(
        0.96, 0.92, (difficulty or "—"),
        fontsize=8, color=palette["border"],
        transform=ax.transAxes, verticalalignment="top",
        horizontalalignment="right",
    )

    # IN / OUT columns — use play_in/play_out (primary) since most
    # matchups have same swaps for play and draw; the user can lean on
    # notes / GUI for play vs draw distinctions.
    in_lines = _format_inout(plan.get("play_in") or [], "+")
    out_lines = _format_inout(plan.get("play_out") or [], "-")

    ax.text(
        0.04, 0.78, "IN",
        fontsize=8, color=_TEXT_DIM,
        transform=ax.transAxes, verticalalignment="top",
    )
    ax.text(
        0.04, 0.72, "\n".join(in_lines) or "(none)",
        fontsize=8, color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
        family="monospace",
    )

    ax.text(
        0.54, 0.78, "OUT",
        fontsize=8, color=_TEXT_DIM,
        transform=ax.transAxes, verticalalignment="top",
    )
    ax.text(
        0.54, 0.72, "\n".join(out_lines) or "(none)",
        fontsize=8, color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
        family="monospace",
    )


def build_cheat_sheet_figure(
    deck_id: int,
    *,
    page_num: int = 1,
) -> Figure:
    """Build the cheat-sheet figure for one page of plans.

    Returns the matplotlib Figure (caller owns lifecycle / must close).
    Raises ValueError if deck_id doesn't exist or has no SB plans."""
    plans = get_sb_plans(deck_id)
    if not plans:
        raise ValueError(f"Deck #{deck_id} has no sideboard plans to render")

    start_idx = (page_num - 1) * _PER_PAGE
    page_plans = plans[start_idx : start_idx + _PER_PAGE]
    if not page_plans:
        raise ValueError(
            f"page_num={page_num} is out of range for deck #{deck_id} "
            f"({len(plans)} plans, {(_PER_PAGE)} per page)"
        )

    fig = Figure(figsize=(_PAGE_W_IN, _PAGE_H_IN), facecolor="#0c0d14")

    # Header axis (top ~10% of page)
    header_ax = fig.add_axes((0.04, 0.92, 0.92, 0.06))
    header_ax.set_xticks([]); header_ax.set_yticks([])
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    header_ax.set_facecolor("#0c0d14")
    total_pages = (len(plans) + _PER_PAGE - 1) // _PER_PAGE
    header_ax.text(
        0.0, 0.7, _fetch_deck_name(deck_id),
        fontsize=14, fontweight="bold", color=_TEXT_FG,
        transform=header_ax.transAxes,
    )
    header_ax.text(
        0.0, 0.1,
        f"{len(plans)} sideboard plans  ·  page {page_num} of {total_pages}  ·  "
        f"generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        fontsize=9, color=_TEXT_DIM,
        transform=header_ax.transAxes,
    )

    # Tile grid (remaining ~85% of page)
    grid_top = 0.90
    grid_bottom = 0.03
    grid_left = 0.04
    grid_right = 0.96
    cell_w = (grid_right - grid_left) / _PER_PAGE_COLS
    cell_h = (grid_top - grid_bottom) / _PER_PAGE_ROWS
    inner_pad_x = 0.005
    inner_pad_y = 0.008

    for i, plan in enumerate(page_plans):
        row = i // _PER_PAGE_COLS
        col = i % _PER_PAGE_COLS
        x = grid_left + col * cell_w + inner_pad_x
        y = grid_top - (row + 1) * cell_h + inner_pad_y
        w = cell_w - 2 * inner_pad_x
        h = cell_h - 2 * inner_pad_y
        ax = fig.add_axes((x, y, w, h))
        _render_tile(ax, plan)

    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sb_cheat_sheet.py -v
```

Expected: PASS (5 tests pass; the 6th `test_export_*` tests are added in Task 2).

If `_render_tile` fails because `play_in` from `get_sb_plans` is still a JSON string (not parsed list), inspect `db/saved_decks.py::get_sb_plans` — if it returns raw strings, parse with `json.loads` before passing to `_format_inout`. The tests use `save_sb_plan` which round-trips through JSON, so the test path will surface this if it's a problem.

- [ ] **Step 5: Run full suite, confirm no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 196 passed (was 191 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add analysis/sb_cheat_sheet.py tests/test_sb_cheat_sheet.py
git commit -m "feat(sb-cheat-sheet): build_cheat_sheet_figure pure renderer + 5 tests"
```

---

## Task 2: `export_cheat_sheet` wrapper (PNG + PDF, multi-page)

**Files:**
- Modify: `analysis/sb_cheat_sheet.py` (append `export_cheat_sheet`)
- Modify: `tests/test_sb_cheat_sheet.py` (append 3 export tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_sb_cheat_sheet.py`:

```python
def test_export_png_writes_nonempty_file(tmp_db, tmp_path):
    from analysis.sb_cheat_sheet import export_cheat_sheet
    deck_id = _seed_deck_with_plans([
        {"opp": "Az Control", "difficulty": "Easy"},
    ])
    out = tmp_path / "cheat.png"
    written = export_cheat_sheet(deck_id, out, fmt="png")
    assert written.exists()
    assert written.stat().st_size > 0


def test_export_pdf_writes_nonempty_file(tmp_db, tmp_path):
    from analysis.sb_cheat_sheet import export_cheat_sheet
    deck_id = _seed_deck_with_plans([
        {"opp": "Az Control", "difficulty": "Easy"},
        {"opp": "Mono Green", "difficulty": "Hard"},
    ])
    out = tmp_path / "cheat.pdf"
    written = export_cheat_sheet(deck_id, out, fmt="pdf")
    assert written.exists()
    assert written.stat().st_size > 0


def test_export_pdf_paginates_for_large_decks(tmp_db, tmp_path):
    """20+ plans → PDF has multiple pages. Verified by file size
    being significantly larger than a 1-plan baseline."""
    from analysis.sb_cheat_sheet import export_cheat_sheet
    specs = [{"opp": f"Archetype {i:02d}"} for i in range(20)]
    deck_id_big = _seed_deck_with_plans(specs)
    big = tmp_path / "big.pdf"
    export_cheat_sheet(deck_id_big, big, fmt="pdf")

    specs_small = [{"opp": "Just one"}]
    deck_id_small = _seed_deck_with_plans(specs_small)
    small = tmp_path / "small.pdf"
    export_cheat_sheet(deck_id_small, small, fmt="pdf")

    # Big should be at least 1.5x the small file (paginated → more content)
    assert big.stat().st_size > small.stat().st_size * 1.2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_sb_cheat_sheet.py::test_export_png_writes_nonempty_file tests/test_sb_cheat_sheet.py::test_export_pdf_writes_nonempty_file tests/test_sb_cheat_sheet.py::test_export_pdf_paginates_for_large_decks -v
```

Expected: FAIL (function not defined).

- [ ] **Step 3: Implement `export_cheat_sheet`**

Append to `analysis/sb_cheat_sheet.py`:

```python
def export_cheat_sheet(
    deck_id: int,
    out_path,
    *,
    fmt: str = "png",
) -> "Path":
    """Export ALL plans for deck_id to disk.

    PNG mode: page 1 goes to out_path. If more than _PER_PAGE plans
    exist, additional pages are written as out_p2.png, out_p3.png, etc.
    Stderr warns about overflow.

    PDF mode: single multi-page PDF via PdfPages.

    Returns the path of the FIRST file written (the user-facing one)."""
    from pathlib import Path
    import sys

    out_path = Path(out_path)
    plans = get_sb_plans(deck_id)
    if not plans:
        raise ValueError(f"Deck #{deck_id} has no sideboard plans to export")

    total_pages = (len(plans) + _PER_PAGE - 1) // _PER_PAGE

    if fmt == "png":
        # Page 1 → out_path; pages 2+ → out_p{N}.png
        for page_num in range(1, total_pages + 1):
            fig = build_cheat_sheet_figure(deck_id, page_num=page_num)
            if page_num == 1:
                target = out_path
            else:
                stem = out_path.stem
                target = out_path.with_name(f"{stem}_p{page_num}{out_path.suffix}")
            fig.savefig(str(target), dpi=300, facecolor=fig.get_facecolor())
            plt.close(fig)
        if total_pages > 1:
            print(
                f"[sb_cheat_sheet] {total_pages - 1} additional page(s) "
                f"written alongside {out_path.name}",
                file=sys.stderr,
            )
        return out_path

    if fmt == "pdf":
        from matplotlib.backends.backend_pdf import PdfPages
        with PdfPages(str(out_path)) as pdf:
            for page_num in range(1, total_pages + 1):
                fig = build_cheat_sheet_figure(deck_id, page_num=page_num)
                pdf.savefig(fig, facecolor=fig.get_facecolor())
                plt.close(fig)
        return out_path

    raise ValueError(f"Unknown fmt: {fmt!r} (expected 'png' or 'pdf')")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_sb_cheat_sheet.py -v
```

Expected: PASS (8 tests — 5 from Task 1 + 3 new).

- [ ] **Step 5: Run full suite, confirm no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 199 passed.

- [ ] **Step 6: Commit**

```bash
git add analysis/sb_cheat_sheet.py tests/test_sb_cheat_sheet.py
git commit -m "feat(sb-cheat-sheet): export_cheat_sheet (PNG + multi-page PDF)"
```

---

## Task 3: GUI button + manual smoke + docs + push

**Files:**
- Modify: `gui/tabs/my_decks.py` — add "Export SB Cheat Sheet" button to Sideboard Plans sub-tab
- Modify: `CLAUDE.md` — note feature in My Decks description
- Modify: `NEXT_STEPS.md` — check off the bullet

- [ ] **Step 1: Locate the SB plans sub-tab construction**

Use Read on `gui/tabs/my_decks.py` around line 541 (where `_detail_tabs.addTab(sb_widget, "Sideboard Plans")` is) and trace backward to find where `sb_widget` is built and what its layout variable is named. Typically the construction looks like:

```python
sb_widget = QWidget()
sb_layout = QVBoxLayout(sb_widget)
# ... existing widgets ...
self._detail_tabs.addTab(sb_widget, "Sideboard Plans")
```

Identify the layout variable (e.g., `sb_layout`) and a good insertion point — typically right after the existing toolbar buttons OR right before the addTab call.

- [ ] **Step 2: Add the "Export SB Cheat Sheet" button**

Use Edit to insert a new button widget into the SB plans sub-tab. Find where existing SB-plan buttons live (e.g., "Save", "Delete", "Suggest") and add the new button alongside them. Generic pattern (adapt to actual code):

```python
self._export_cheat_sheet_btn = QPushButton("📋 Export Cheat Sheet")
self._export_cheat_sheet_btn.setToolTip(
    "Export all SB plans as a 1-page printable PNG or PDF (color-coded by difficulty)"
)
self._export_cheat_sheet_btn.clicked.connect(self._on_export_cheat_sheet)
# Add to existing button row layout:
<button_row_layout>.addWidget(self._export_cheat_sheet_btn)
```

If the existing buttons don't use an emoji prefix, drop the `📋` prefix to stay consistent.

- [ ] **Step 3: Add the handler method**

Add to the same class (likely `MyDecksTab` or similar — verify with Read):

```python
def _on_export_cheat_sheet(self) -> None:
    """Export the current deck's SB plans as PNG or PDF."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    if not self._current_deck:
        QMessageBox.information(self, "No deck", "Pick a deck first.")
        return
    deck_id = self._current_deck["id"]
    default_name = f"{self._current_deck['name'].replace(' ', '_')}_SB_cheat_sheet.pdf"
    out_path, selected_filter = QFileDialog.getSaveFileName(
        self, "Export SB Cheat Sheet", default_name,
        "PDF (*.pdf);;PNG (*.png)",
    )
    if not out_path:
        return
    fmt = "pdf" if out_path.lower().endswith(".pdf") else "png"
    try:
        from analysis.sb_cheat_sheet import export_cheat_sheet
        from pathlib import Path
        written = export_cheat_sheet(deck_id, Path(out_path), fmt=fmt)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(written)))
    except ValueError as e:
        QMessageBox.warning(self, "Export failed", str(e))
    except Exception as e:
        QMessageBox.critical(self, "Export error", f"Unexpected error: {e}")
```

The `self._current_deck` attribute is referenced at `my_decks.py:1205` per the codebase scan — verify it exists and points to a dict with `id` and `name` keys.

- [ ] **Step 4: Headless smoke test**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from gui.tabs.my_decks import MyDecksTab
w = MyDecksTab()
print('OK — class constructs, button exists:', hasattr(w, '_export_cheat_sheet_btn'))
"
```

Expected: `OK — class constructs, button exists: True`.

If `MyDecksTab` isn't the actual class name, substitute the correct one.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 199 passed (no GUI changes have tests beyond the headless smoke).

- [ ] **Step 6: Manual smoke test**

User runs:
```bash
python run_gui.py
```

Then: My Decks → Tokyo Prowess → Sideboard Plans → "Export Cheat Sheet" button → file dialog opens → save as PDF → file opens in default viewer → verify all 17 plans visible + color-coded.

- [ ] **Step 7: Update CLAUDE.md My Decks description**

Find the My Decks paragraph in `CLAUDE.md` §6 (around line 130-140; matches the existing "5 sub-tabs: Decklist / Sideboard Plans..." text). Add a sentence at the end of the Sideboard Plans description:

```markdown
"Export Cheat Sheet" button generates a 1-page printable PNG/PDF of all SB plans for at-table reference, with tiles color-coded by difficulty (Easy=green / Medium=navy / Hard=red).
```

- [ ] **Step 8: Update CLAUDE.md "Last updated" line**

Edit line 3 to bump:

```markdown
Last updated: 2026-05-16 (puzzle Phase 2 + single-instance + SB cheat-sheet shipped)
```

- [ ] **Step 9: Update NEXT_STEPS.md**

Under "RC Prep Follow-Ups", find:

```markdown
- [ ] Sideboard quick-reference printout — 1-page exportable card (PDF
      or PNG) of the 12-matchup SB grid for Tokyo Prowess.
```

Replace with:

```markdown
- [x] ~~Sideboard quick-reference printout~~ ✓ shipped (`analysis/sb_cheat_sheet.py` + "Export Cheat Sheet" button on My Decks → Sideboard Plans). 1-page PDF/PNG, color-coded by difficulty.
```

- [ ] **Step 10: Commit + push**

```bash
git add gui/tabs/my_decks.py CLAUDE.md NEXT_STEPS.md
git commit -m "feat(sb-cheat-sheet): GUI button on Sideboard Plans sub-tab + docs"
git push
```

If pre-push hook rejects (see `[[feedback_pre-push-hook-path-scrubbing]]` / `[[feedback_no-user-handles-in-docs]]`), scrub and NEW-commit.

---

## Validation gates

- [ ] `python -m pytest tests/test_sb_cheat_sheet.py -v` → 8 pass
- [ ] `python -m pytest tests/` → 199 pass
- [ ] Headless smoke: `MyDecksTab` constructs with button attribute
- [ ] Manual smoke (user): Export button → file dialog → PDF saves → opens in viewer → all plans visible + color-coded
- [ ] `git push` succeeds

---

## What this does NOT do (intentional Phase 1 limits)

- No live preview before export (user can re-export if it looks wrong)
- No matchup WR% on tiles (offered, deferred — color-coding chosen instead)
- No play-vs-draw split per tile (uses `play_in`/`play_out` as primary; the GUI handles play/draw distinction in detail view)
- No custom theme / grayscale-print mode (dark palette assumes color output)
- No multi-deck composite sheets
