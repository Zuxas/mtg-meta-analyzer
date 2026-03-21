# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-20

---

## Phase 2: Core Analysis — COMPLETE

All backend modules done. Do not rebuild any of these.

| Module | Command |
|---|---|
| Archetype normalization (migration applied) | `python -m analysis.archetypes --apply` |
| MTGDecks.net scraper (cloudscraper) | `python -m scrapers.mtgdecks --pages 3` |
| Trend charts (meta share, trend, heatmap) | `python -m analysis.query chart meta` |
| Prediction logging + validation | `python -m analysis.query predict` |
| Blunder Detection (Major/Moderate/Minor) | `python -m analysis.query blunder "Deck"` |
| Chapin Principles (6 scored principles) | `python -m analysis.query chapin "Deck"` |

---

## Phase 3: PyQt6 GUI — COMPLETE (theme wired, ready to test)

### What's built (as of 2026-03-20)

```
run_gui.py                  ✅ launcher (sets matplotlib QtAgg backend first)
gui/theme.py                ✅ personal website design system (#3b3c4d / #65bcd5 / Orbitron)
gui/fonts/Orbitron.ttf      ✅ bundled heading font
gui/main_window.py          ✅ theme applied, 5 tabs, cmd terminal default
gui/setup_wizard.py         ✅ website theme colors, first-time setup flow
gui/worker_threads.py       ✅ all worker threads
gui/widgets/chart_canvas.py ✅ CHART_PALETTE/BG/PANEL/GRID from theme module
gui/widgets/meta_table.py   ✅
gui/tabs/dashboard.py       ✅ theme.btn_primary() for Refresh button
gui/tabs/deck_analyzer.py   ✅ theme buttons, inline styles removed
gui/tabs/search.py          ✅ theme.btn_primary() for all search buttons
gui/tabs/charts.py          ✅ theme buttons, CHART_BG for PNG export
gui/tabs/predictions.py     ✅ theme.btn_primary/secondary/success()
```

### START HERE next session

```bash
python run_gui.py
```

Expected on first run: setup wizard (if DB < 50 events).
Expected on returning run: dashboard loads, background scrape starts.

### Known things to test / likely issues

1. **Orbitron font** — `gui/fonts/Orbitron.ttf` is a variable-weight font registered
   via `QFontDatabase.addApplicationFont()`. If tab labels don't look right, check
   that `HEADING_FONT` is set correctly in `theme.py` after `apply_theme()` runs.

2. **Chart canvas sizing** — heatmap figure size recalculates dynamically but may
   need `self._canvas.updateGeometry()` or a `draw_idle()` call after resize.

3. **Deck Analyzer legality check** — `analyze_deck()` calls `get_cards_data()`
   which uses the Scryfall local cache. If `data/scryfall_oracle.json` is missing,
   legality check raises. Run `python -m scrapers.scryfall --download` first.

4. **search_local() return format** — `card.get("legalities")` may be a JSON string
   (stored as TEXT in SQLite). The search tab already has a `json.loads` fallback.

5. **predictions `accuracy_report()`** — returns `{}` or `None` if no predictions
   exist yet. The tab handles this gracefully but verify on fresh DB.

---

## Database build scripts — COMPLETE

| Script | Purpose |
|---|---|
| `fill_database.bat` | Double-click first-time full build (3-year backfill, all sources) |
| `fill_database.py` | Python script called by fill_database.bat |
| `background_fill.bat` | Daily incremental scrape (Standard + Pioneer + Modern) |
| `schedule_background_fill.bat` | One-time setup: register 6 AM Task Scheduler task |

### Register 6 AM task (if not done yet)
Right-click `schedule_background_fill.bat` → **Run as Administrator** (once).
This adds a silent daily 6 AM scrape alongside the existing 5 PM task.

---

## Next features after basic run is stable

### A — First-run data quality
- After setup wizard completes, auto-run `python -m analysis.archetypes --apply`
  to normalize newly scraped archetype names
- Add a "Normalize Archetypes" button to main window menu bar

### B — Dashboard improvements
- Add "Last N weeks" summary chip below chart (e.g. "+2.3% meta share")
- Color-code table rows: green = rising, red = falling vs prior 2 weeks
- Export table as CSV button

### C — Charts tab polish
- Auto-populate archetype autocomplete from DB (`get_meta_standings` result)
- "Compare archetypes" mode: overlay multiple trend lines on one chart

### D — Deck Analyzer improvements
- "Load Average Deck" button: populate the text box with the average deck for
  a selected archetype (calls `get_average_deck()`)
- Show Chapin explanation text per principle (already in `PrincipleScore.explanation`)

### E — Packaging (after GUI is stable)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer"
```
- `data/` stays external (DB + Scryfall bulk file too large to embed)
- Include `README_INSTALL.txt` explaining where to place data files
- Test on a clean machine without Python installed

---

## Data status (as of 2026-03-20)

| Format | Events | Decks | Date range |
|---|---|---|---|
| Standard | 1,816 | ~20,010 | Jan 2025 – Mar 2026 |
| Pioneer | 10 | 147 | Recent only |
| Modern | 0 | 0 | background_fill.bat will populate going forward |

- No 2023/2024 data — MTGTop8 pagination depth limit reached Jan 2025
- To get deeper history: run `python -m scrapers.backfill --format standard` manually
  (may take several hours; will push back further if MTGTop8 has older pages)

---

## Known issues / notes

- `analysis/charts.py` sets `matplotlib.use("Agg")` at import — never import it
  inside GUI code. Use `gui/widgets/chart_canvas.py` instead.
- `data/scryfall_oracle.json` is ~162 MB and gitignored. Regenerate:
  `python -m scrapers.scryfall --download`
- MTGDecks scraper uses `cloudscraper`. If 403s return:
  `pip install --upgrade cloudscraper`
- Blunder/Chapin on average decks may show <60 cards (inclusion threshold) — expected.
- VS Code default terminal is now **cmd** (not Git Bash). New terminals open in cmd.
- After any new backfill/scrape, enrich new cards:
  `python -m scrapers.scryfall`
