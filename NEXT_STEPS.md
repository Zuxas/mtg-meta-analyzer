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
gui/main_window.py          ✅ theme applied, 6 tabs, 1200x700 default size
gui/setup_wizard.py         ✅ website theme colors, first-time setup flow
gui/worker_threads.py       ✅ all worker threads
gui/widgets/chart_canvas.py ✅ CHART_PALETTE/BG/PANEL/GRID from theme module
gui/widgets/meta_table.py   ✅
gui/tabs/dashboard.py       ✅ auto-loads on startup, weeks filter applies to table+chart
gui/tabs/deck_analyzer.py   ✅ theme buttons, inline styles removed
gui/tabs/search.py          ✅ theme.btn_primary() for all search buttons
gui/tabs/charts.py          ✅ theme buttons, CHART_BG for PNG export
gui/tabs/predictions.py     ✅ theme.btn_primary/secondary/success()
gui/tabs/settings.py        ✅ format checkboxes, data window, auto-update, storage info
gui/tray_icon.py            ✅ system tray, status dots, right-click menu
gui/first_run_setup.py      ✅ one-time UAC wizard, registers all 3 tasks
```

### Performance fix applied (2026-03-20)
`get_meta_standings` in `analysis/win_rates.py` was making one SQL query per archetype
(~918 queries, 9+ seconds). Fixed to use a single bulk query — now 0.07s.
The dashboard `refresh()` also passes a `since` date from the Weeks control so only
the relevant time window is loaded.

### START HERE next session

```bash
python run_gui.py
```

Expected on first run: setup wizard (if DB < 50 events).
Expected on returning run: dashboard auto-loads data within 1 second, background scrape starts.

### Known things to test / likely issues

1. **Est Win% / Avg Pts columns show "—"** for archetypes with only 2-3 appearances —
   this is correct behavior (not enough data for reliable estimates).

2. **Deck Analyzer legality check** — `analyze_deck()` calls `get_cards_data()`
   which uses the Scryfall local cache. If `data/scryfall_oracle.json` is missing,
   legality check raises. Run `python -m scrapers.scryfall --download` first.

3. **search_local() return format** — `card.get("legalities")` may be a JSON string
   (stored as TEXT in SQLite). The search tab already has a `json.loads` fallback.

4. **predictions `accuracy_report()`** — returns `{}` or `None` if no predictions
   exist yet. The tab handles this gracefully but verify on fresh DB.

---

## Tray icon + UAC first-run wizard — COMPLETE

| File | Status |
|---|---|
| `gui/tray_icon.py` | ✅ programmatic icon, green/orange/red dot, right-click menu, 60s refresh timer |
| `gui/first_run_setup.py` | ✅ one-time UAC dialog, registers all 3 tasks, never shown again |
| `register_tasks.py` | ✅ elevated task registration, writes config.ini flag on success |
| `run_gui.py` | ✅ wires tray + first-run wizard, `setQuitOnLastWindowClosed(False)` |
| `gui/main_window.py` | ✅ `set_tray()`, `closeEvent` hide-to-tray, scrape writes tray status |
| `update_claude_code.bat` | ✅ self-elevating npm update helper |

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

## User Preferences System — PARTIALLY IMPLEMENTED

Full spec documented in CLAUDE.md under "User Preferences System".

### Done:
- `gui/tabs/settings.py` — Settings tab with format checkboxes, data window, auto-update, storage info
- `load_preferences()` / `save_preferences()` helpers in settings.py read/write `data/preferences.json`

### Still TODO:
1. **Format selection in setup wizard** — add page 0 before Scryfall download
   - Checkboxes: Standard (default on) / Pioneer / Modern / Legacy
   - Saves `preferences.json` immediately on Next
2. **`db/database.py`** — add `user_preferences` table to schema
3. **Wire scrapers** — `background_fill.bat` and `fill_database.py` skip unselected formats

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
