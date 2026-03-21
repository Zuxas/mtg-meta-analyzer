# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-21 (session 2)

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
| Sideboard guide parsing + G2/G3 WR model | `analysis/sideboard_guides.py` |

---

## Phase 3: PyQt6 GUI — STABLE

### What's built (as of 2026-03-21)

```
run_gui.py                       launcher (sets matplotlib QtAgg backend first)
launch_app.bat                   double-click to launch from Explorer
create_shortcut.bat              run once to put desktop shortcut in place
gui/theme.py                     design system + TIMEFRAME_OPTIONS (9 options incl. All Time)
gui/fonts/Orbitron.ttf           bundled heading font
gui/main_window.py               8 tabs (Ask Claude shown only if API key set)
gui/setup_wizard.py              first-time setup flow
gui/worker_threads.py            all worker threads
gui/widgets/chart_canvas.py      fetch_chart_data() + draw_from_data()
gui/widgets/meta_table.py
gui/widgets/archetype_detail.py  4 tabs: Average Deck / Recent Lists / Tech Choices / Resources
gui/widgets/deck_export.py       MTGO/MTGA .txt export + decklist.org tournament sheet
gui/tabs/dashboard.py            Untapped.gg layout, trend color-coding, CSV export, dynamic titles
gui/tabs/deck_analyzer.py        Load avg deck, recommendations, Chapin tooltips, Export, Legality Checker
gui/tabs/search.py               sortable deck search, H2H with timeframe selector, My Deck vs Field
gui/tabs/charts.py               archetype autocomplete, TIMEFRAME_OPTIONS selector
gui/tabs/predictions.py
gui/tabs/knowledge_base.py       add/browse bookmarks + guides table, Sync Guides button
gui/tabs/ask_claude.py           optional streaming chat (hidden until API key set in Settings)
gui/tabs/settings.py             formats, data window, auto-update, AI Assistant key section
gui/tabs/tournament_prep.py      RCQ Optimizer (G1/G2G3 analysis, flip detection) + Breaker Math
gui/tray_icon.py                 system tray, status dots, right-click menu
gui/first_run_setup.py           one-time UAC wizard, registers all 3 tasks
analysis/tournament.py           rcq_equity() with guide-aware post-board WR
analysis/sideboard_guides.py     parse_sb_plan, get_matchup_guides, estimate_postboard_wr, flip_analysis
scrapers/guides.py               imports Skill Issue Magic Google Sheet → guides table
```

### START HERE next session

```bash
python run_gui.py
# or double-click launch_app.bat / desktop shortcut
```

---

## Session 2026-03-21 Summary — What was added

1. **Decklist Legality Checker** (Deck Analyzer tab)
   - "Check Legality" button queries `card_data.legalities` for all cards at once
   - Color-coded results table: banned=red, restricted/not_legal=orange, size issues=yellow
   - Shows ✓/✗ summary with issue count

2. **Sideboard Guide Integration in RCQ Optimizer**
   - `analysis/sideboard_guides.py` — new module
   - Parses free-text guide comments for IN/OUT sideboard plans
   - G2/G3 WR model: opponent's SB cards hurt you (-1.3%/card, cap 13%), your SB helps (+1.0%/card, cap 13%)
   - Flip detection: "FLIPPED" if G1 favored but G2/G3 not, "FLIPS IN YOUR FAVOR" if reverse
   - RCQ matchup table now shows G1 WR% and G2/G3 WR% columns
   - Clicking a matchup row shows per-matchup detail: flip verdict, WR breakdown, guide IN/OUT plans

3. **Expanded timeframe selector (all tabs)**
   - Options: 1w, 2w, 4w, 8w, 3mo, 6mo, 1yr, 2yr, All Time — centralized in `gui/theme.py`
   - All Time = `None` = no date filter on any query
   - Applied to: Dashboard, Charts, Deck Analyzer (load avg), Archetype Detail, Search H2H, RCQ Optimizer

---

## Session 2026-03-21 (session 2) Summary — What was added

1. **Bug fixes**
   - `gui/tabs/charts.py`: `QSpinBox` missing from imports — caused silent crash on launch
   - `gui/tabs/search.py`: `_DeckDetailDialog._export()` passed wrong kwargs to `show_export_menu` (used `parent=self` instead of `btn_widget`, missing `format_name`) — crashed on Export click
   - `gui/widgets/chart_canvas.py`: `_draw_heatmap()` expected old flat `{arch: {opp: winrate}}` format but `get_matchup_matrix()` returns `{"archetypes": [...], "matrix": {...}, "note": "..."}` — fixed unpacking

2. **Live Matchup Data pipeline** (new feature)
   - `scrapers/matchup_scraper.py` — scrapes MTGDecks.net `/winrates`, parses `data-winrate` attribute
   - `db/matchup_queries.py` — `matchup_matrix` table + save/get/get_last_updated
   - `gui/tabs/heatmap_tab.py` — MATCHUP DATA tab with Fetch Live / Use Cached / Paste Data
   - Registered as `self._heatmap` in `gui/main_window.py`, tab label "MATCHUP DATA"

3. **Skills installed** (`.claude/skills/`)
   - `triage-issue`, `improve-codebase-architecture`, `grill-me` from mattpocock/skills

---

## TOP PRIORITIES — Next Session

### 1. PyInstaller Standalone .exe Packaging

```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" \
  --add-data "gui/fonts;gui/fonts"
```

Key things to verify:
- `data/` folder stays external (DB + Scryfall bulk file too large to embed)
- `--register-tasks` arg re-uses same .exe for UAC elevation (no second binary)
- `anthropic` package bundled but optional (conditional import in ask_claude.py)
- `cloudscraper` and all scrapers bundled
- Hidden imports: `sqlite3`, `matplotlib`, `PyQt6`, `anthropic`
- Test on a clean machine or VM without Python installed
- Ship: `MTG Meta Analyzer.exe` + `fill_database.bat` + README

Likely issues to watch:
- Scryfall bulk file path (use `sys._MEIPASS` for bundled assets, `sys.executable` dir for data/)
- `analysis/charts.py` sets `matplotlib.use("Agg")` — must not be imported before `run_gui.py` sets `QtAgg`
- Task Scheduler .bat paths need to point to the .exe location, not python scripts

### 2. First-Time Setup Wizard Testing

The setup wizard (`gui/setup_wizard.py`) runs on first launch when no DB exists.
Test the full flow:
- Step 1: Scryfall bulk download (~162 MB)
- Step 2: Initial backfill (Standard events)
- Step 3: 50-event unlock gate
- Verify Task Scheduler registration dialog appears and works
- Verify wizard is never shown again after completion

Also test the format preference page (TODO — see below).

### 3. RCQ Optimizer End-to-End Test with a Real 75

Submit an actual tournament decklist through the RCQ Optimizer and verify:
- Paste 60+15 in the Deck Analyzer tab → verify legality check passes
- In Tournament Prep → RCQ Optimizer: select format, enter player count, pick archetype
- Enter the actual expected meta field (e.g., "Boros Energy x8, Mono Red x4, ...")
- Check: weighted WR, field grade, matchup breakdown
- Click each matchup row → verify G1/G2G3 split, guide IN/OUT plans render correctly
- Check flip warnings appear for appropriate matchups
- Verify sideboard recommendations are actionable

Known things to check:
- Guide data availability (requires guides table populated — run `python -m scrapers.guides` first)
- Archetype name matching (guides use free-text names — may need alias tweaks)
- Post-board WR model calibration (conservative: capped at 0.13 swing each way)

---

## Remaining Features (Lower Priority)

### A — User Preferences System (partially done)

Full spec in CLAUDE.md.

Still TODO:
1. **Format selection in setup wizard** — add page 0 before Scryfall download
   - Checkboxes: Standard (default on) / Pioneer / Modern / Legacy
   - Saves `preferences.json` immediately on Next
2. **`user_preferences` table in `db/database.py`** (or just keep using preferences.json)
3. **Wire scrapers** — `background_fill.bat` and `fill_database.py` skip unselected formats

### B — Charts Compare Mode

Overlay multiple archetype trend lines on one chart (multi-select archetype combo).

### C — Knowledge Base Improvements

- Filter guides by archetype/format/author
- Full-text search across guide comments
- Rate guides (thumbs up/down)

---

## Data status (as of 2026-03-21)

| Format | Events | Decks | Notes |
|---|---|---|---|
| Standard | 2,043+ | ~24,289+ | Nov 2024 – Mar 2026, daily 6 AM task active |
| Pioneer | 109 | 3,125 | MTGDecks 20-page scrape completed |
| Modern | scraping | TBD | Background scrape may still be running |
| Guides | 331 | — | Skill Issue Magic sheet, last synced 2026-03-21 |

---

## Known issues / notes

- **Screenshots** — always use `python -c "import pyautogui; pyautogui.screenshot().save('data/gui_screenshot.png')"`. Never save to Windows Temp folder.
- `analysis/charts.py` sets `matplotlib.use("Agg")` at import — never import it inside GUI code. Use `gui/widgets/chart_canvas.py` instead.
- `data/scryfall_oracle.json` is ~162 MB and gitignored. Regenerate: `python -m scrapers.scryfall --download`
- MTGDecks scraper uses `cloudscraper`. If 403s return: `pip install --upgrade cloudscraper`
- VS Code default terminal is **cmd** (not Git Bash). New terminals open in cmd.
- After any new backfill/scrape, enrich new cards: `python -m scrapers.scryfall`
- `exports/` folder is gitignored — created automatically on first export.
- `data/preferences.json` is gitignored — contains API key and user prefs.
- Guide archetype matching is fuzzy (substring both ways) — if guides aren't showing for a matchup, check that the archetype names in guides table roughly match the archetype names in the meta standings.
- `estimate_postboard_wr` clamps output to [0.18, 0.84] — extreme WR values (very favored/unfavored matchups) will appear slightly less extreme post-board than they really are. This is intentional conservatism.
