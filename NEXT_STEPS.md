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

## Phase 3: PyQt6 GUI — STABLE ✅

### What's built (as of 2026-03-20)

```
run_gui.py                       ✅ launcher (sets matplotlib QtAgg backend first)
launch_app.bat                   ✅ double-click to launch from Explorer (no terminal needed)
create_shortcut.bat              ✅ run once to put desktop shortcut in place
gui/theme.py                     ✅ personal website design system (#3b3c4d / #65bcd5 / Orbitron)
gui/fonts/Orbitron.ttf           ✅ bundled heading font
gui/main_window.py               ✅ theme applied, 6 tabs, 1200x700 default size
gui/setup_wizard.py              ✅ website theme colors, first-time setup flow
gui/worker_threads.py            ✅ all worker threads
gui/widgets/chart_canvas.py      ✅ fetch_chart_data() + draw_from_data() for dashboard
gui/widgets/meta_table.py        ✅
gui/widgets/archetype_detail.py  ✅ click-to-open deck detail dialog (avg deck, recent lists, tech)
gui/tabs/dashboard.py            ✅ Untapped.gg-inspired layout, single-click opens detail
gui/tabs/deck_analyzer.py        ✅ theme buttons, inline styles removed
gui/tabs/search.py               ✅ theme.btn_primary() for all search buttons
gui/tabs/charts.py               ✅ theme buttons, CHART_BG for PNG export
gui/tabs/predictions.py          ✅ theme.btn_primary/secondary/success()
gui/tabs/settings.py             ✅ format checkboxes, data window, auto-update, storage info
gui/tray_icon.py                 ✅ system tray, status dots, right-click menu
gui/first_run_setup.py           ✅ one-time UAC wizard, registers all 3 tasks
```

### START HERE next session

```bash
python run_gui.py
# or double-click launch_app.bat / desktop shortcut
```

Expected on returning run: dashboard auto-loads within 1 second, Recent Top Finishes shows
current week's events, single-click any archetype row → deck detail dialog.

### Bugs fixed (2026-03-20 session)

- **Date filter fix** — MTGTop8 stores `DD/MM/YY`, MTGDecks stores `YYYY-MM-DD`. Filtering
  was comparing incompatible string formats (e.g. `'14/03/26' >= '20260306'` = False in ASCII),
  silently excluding all MTGTop8 events. Fixed with `_DATE_KEY` CASE expression (normalizes both
  to `YYYYMMDD`) + `_dt_to_db_str` returning `%Y%m%d`. Applied in `win_rates.py`,
  `dashboard.py`, `archetype_detail.py`.
- **`get_meta_standings` day-of-month bug** — A prior edit used `replace_all=True` but missed
  the function due to different indentation. The filter was doing `e.date >= '20260306'` string
  compare against `DD/MM/YY` dates — only events on days 20-31 passed. Fixed manually.
- **Izzet Prowess missing from Win Rate/Popular panels** — `get_meta_standings(top=12)` sorted by
  `(avg_points, top8_rate)`, excluding Izzet Prowess (#1 by appearances, 601 events) as it ranked
  outside top 12 on performance. Fixed: `refresh()` now fetches `top=50`; populate functions slice
  to user's selected top N after sorting independently.
- **Mana color pips showing as squares** — `QLabel` backgrounds don't clip to `border-radius` in
  Qt. Fixed: `theme.make_pip_widget()` now uses `QFrame` + `WA_StyledBackground` attribute which
  forces Qt to clip the background, producing actual circles.
- **Dynamic panel titles** — "WIN RATE THIS WEEK" is now "WIN RATE — 2 WEEKS" (or whatever
  timeframe is selected). Titles update on every refresh via `_winrate_hdr` and `_pop_hdr` refs.
- **Player column added** — Recent Top Finishes now shows 6 columns: Place / Colors / Archetype /
  Player / Event / Date.
- **"No decklists found" for clicked archetypes** — Recent Top Finishes stored `"UR  Izzet Prowess"`
  (color identity prefix) in the archetype cell. Fixed: raw name stored in `UserRole` data,
  click handler reads `UserRole` instead of `text()`.
- **`%-d` format code** — Linux-only; replaced with `dt.day` in `archetype_detail.py`.
- **Scraper run-date print** — Both `scrapers/mtgtop8.py` and `scrapers/mtgdecks.py` now
  print `Run date: YYYY-MM-DD HH:MM` at the start of every scrape run.

### Performance fix applied (2026-03-20)
`get_meta_standings` in `analysis/win_rates.py` — single bulk query, ~0.07s (was 9.36s).

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
| Standard | 2,043 | ~24,289 | Nov 2024 – Mar 2026 |
| Pioneer | 10 | ~147 | Recent MTGO only (MTGTop8 has little Pioneer data) |
| Modern | 0 | 0 | MTGTop8 has no Modern data; use MTGDecks scraper |

- Pioneer/Modern depth: run `python -m scrapers.mtgdecks --format pioneer --pages 20`
- Standard backfill in progress — daily 6 AM task will maintain going forward
- Card data: 99.98% coverage (24,284/24,289 decks have full card lists)

---

## Known issues / notes

- **Pip circles** — `QFrame` + `WA_StyledBackground` approach is implemented and committed
  but not yet visually confirmed. Restart GUI to verify circles render correctly.
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
