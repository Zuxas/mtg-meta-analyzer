# Sideboard Cheat-Sheet Export — Design Spec

**Date:** 2026-05-16
**Status:** Approved (pre-implementation)

---

## Problem

User has 17 saved sideboard plans for Tokyo Prowess (`saved_decks.id=17`) that live in the GUI's My Decks → Sideboard Plans sub-tab. At an RC, alt-tabbing to the laptop between rounds (or worse, during play) is suspicious and slow. Need a printable/screenshottable single-page reference so the user can print + clip to their binder or save as a phone wallpaper for at-table lookups.

## Goal

A "Export SB Cheat Sheet" button that produces a one-page image (PNG) and PDF of all SB plans for one deck. Color-coded tiles by sideboarding difficulty so the user can prioritize harder matchups at a glance.

**Non-goals:**
- Editing plans from the printout (still done in the GUI)
- Multi-deck composite sheets
- Custom per-matchup layouts (uniform grid)
- Mainboard decklist export (already exists via separate buttons)

## Architecture

One new module + a button wired into the existing Sideboard Plans sub-tab.

```
analysis/sb_cheat_sheet.py
  ├─ build_cheat_sheet_figure(deck_id) -> matplotlib.Figure
  │   Pure function. Returns a Figure with the rendered grid. Testable.
  └─ export_cheat_sheet(deck_id, out_path, fmt) -> Path
      Wraps build_cheat_sheet_figure + Figure.savefig with PNG/PDF format.

gui/widgets/saved_sb_plans.py  (existing — modify)
  └─ Add "Export SB Cheat Sheet" button + handler that:
      - Opens QFileDialog with PNG + PDF filters
      - Calls export_cheat_sheet
      - Opens the saved file via QDesktopServices
```

### Layout

- **Page size:** US Letter portrait (8.5" × 11") at 300 DPI = 2550 × 3300 px (PNG); same logical size for PDF (vector).
- **Header (top ~1.2"):** deck name (bold, large), format, total plan count, generation timestamp.
- **Grid:** 3 columns × N rows. Each tile is ~2.5" wide × ~1.5" tall.
  - Up to 18 plans fit on page 1.
  - If more plans exist, additional pages auto-generated (matplotlib `PdfPages` for PDF; per-page PNG files for PNG with `_p2.png` suffix).
- **Tile contents:**
  - Opponent archetype name (header, bold)
  - Difficulty badge (small, colored chip top-right)
  - `IN:` list — `+N CardName` per line, max 7 lines
  - `OUT:` list — `-N CardName` per line, max 7 lines
  - If more than 7 IN/OUT lines, last line shows `+N more...`

### Color coding (by `saved_sb_plans.difficulty`)

| Difficulty | Tile background | Border |
|---|---|---|
| Easy | `#1a3320` (dark green) | `#80c890` (mint accent) |
| Medium | `#1a1f33` (dark navy) | `#6080c8` (slate accent) |
| Hard | `#33201a` (dark red) | `#d88060` (warm accent) |
| (missing / null) | `#1a1a1a` (neutral) | `#666` (grey) |

Color values match the existing `gui/theme.py` palette family for visual consistency with the rest of the app.

## Component contract

```python
def build_cheat_sheet_figure(
    deck_id: int,
    *,
    per_page_cols: int = 3,
    per_page_rows: int = 6,
    page_num: int = 1,
) -> matplotlib.figure.Figure:
    """Build the cheat-sheet figure for one page of plans.

    Returns the matplotlib Figure (caller owns lifecycle / must close).
    Raises ValueError if deck_id doesn't exist or has no SB plans."""


def export_cheat_sheet(
    deck_id: int,
    out_path: Path,
    *,
    fmt: Literal["png", "pdf"] = "png",
) -> Path:
    """Export ALL plans for deck_id. Returns the absolute path of the
    written file.

    PNG mode: single page only (truncates to first 18 plans if more
    exist; user warned via stderr). Multi-page PNG output is two files:
    out.png and out_p2.png, etc.

    PDF mode: multi-page native via PdfPages — all plans fit, paginated."""
```

## Data flow

```
User clicks "Export SB Cheat Sheet" in Sideboard Plans sub-tab
  │
  ├─ QFileDialog opens (PNG / PDF filter)
  ├─ User picks path + format
  │
  ├─ export_cheat_sheet(deck_id=current, out_path=picked, fmt=picked)
  │     │
  │     ├─ Query: SELECT * FROM saved_sb_plans WHERE deck_id=? ORDER BY opp_archetype
  │     ├─ For each page (18 plans/page):
  │     │     ├─ build_cheat_sheet_figure(deck_id, page_num=N)
  │     │     │     └─ matplotlib: create Figure(8.5, 11)
  │     │     │     └─ For each plan: add subplot with tile bg color + IN/OUT text
  │     │     └─ Figure.savefig(out_path, dpi=300, format=fmt)
  │     │
  │     └─ Return path of written file
  │
  └─ QDesktopServices.openUrl(file://...) opens the saved file
```

## Error handling

| Scenario | Handling |
|---|---|
| Deck has 0 SB plans | Raise `ValueError("Deck has no sideboard plans")` — GUI catches, shows QMessageBox |
| Deck has > 18 plans + format=PNG | Generate first 18 on page 1 + write additional PNG files with `_p2.png` suffix. Stderr warning. |
| Out path unwritable | Standard OSError propagates — GUI catches, shows error dialog |
| Card name has no Scryfall image (any) | Doesn't matter — we don't render images, just text |
| `saved_sb_plans.in_cards_json` malformed | Skip that plan, log warning to stderr |

## Testing

`tests/test_sb_cheat_sheet.py`:

```python
def test_build_figure_returns_matplotlib_figure(tmp_db):
    """Smoke: build_cheat_sheet_figure returns a Figure for a deck
    with at least one SB plan."""

def test_build_figure_raises_for_deck_with_no_plans(tmp_db):
    """Empty SB plans → ValueError."""

def test_export_png_writes_nonempty_file(tmp_db, tmp_path):
    """export_cheat_sheet(fmt='png') writes a > 0 byte file."""

def test_export_pdf_writes_nonempty_file(tmp_db, tmp_path):
    """export_cheat_sheet(fmt='pdf') writes a > 0 byte file."""

def test_export_pdf_includes_all_pages(tmp_db, tmp_path):
    """Deck with 20+ plans → PDF should contain multiple pages.
    Verify via PyPDF2 page count or simply file size > single-page baseline."""

def test_difficulty_colors_applied(tmp_db):
    """Build figure, walk subplot facecolors, assert at least one
    matches the difficulty palette."""
```

Fixture: `tmp_db` clones an in-memory DB with one deck + ~3 plans across all difficulty levels.

### Manual smoke

1. Open GUI → My Decks → Tokyo Prowess → Sideboard Plans sub-tab
2. Click "Export SB Cheat Sheet" → file dialog opens
3. Save as PNG → file opens in default image viewer
4. Verify: all 17 plans visible, color-coded by difficulty, IN/OUT cards readable
5. Repeat with PDF format
6. Print the PDF on actual paper — verify it's legible at standard print quality

## File structure

**Create:**
- `analysis/sb_cheat_sheet.py` — `build_cheat_sheet_figure` + `export_cheat_sheet`
- `tests/test_sb_cheat_sheet.py` — 6 tests

**Modify:**
- `gui/widgets/saved_sb_plans.py` (or wherever the Sideboard Plans sub-tab lives — verify exact location) — add "Export SB Cheat Sheet" button + handler

## Trade-offs accepted

1. **Static grid layout (3×6)** — could be smarter (vary tile size by IN/OUT count) but adds complexity for marginal value. Fixed grid is predictable to print.
2. **PNG multi-page = multiple files** — alternative would be auto-stitch into one tall image, but that defeats "1-page printable." PDF handles paging natively, recommend it for >18 plans.
3. **No mainboard summary on every page** — only on page 1 header. Saves space; mainboard rarely changes mid-tournament.
4. **No matchup WR%** — was offered as an option; user chose color-coding instead. WR can be a future enhancement.

## Out of scope

- Live editing from the cheat sheet (still done in GUI)
- Custom themes / printer-friendly grayscale mode (dark palette assumes color print or screen)
- Multi-deck composite sheets

---

**End of spec.**
