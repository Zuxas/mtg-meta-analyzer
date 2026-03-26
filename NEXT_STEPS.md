# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-25

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

## Session 2026-03-21 (session 5) Summary — What was added

1. **Real match W/L pipeline** (MTGMelee scraper + matches DB + win_rates additions)
   - `scrapers/mtgmelee_scraper.py` — DataTables POST scraper for MTGMelee round pairings
     `--test` flag dumps raw API response for endpoint verification
     `--infer-brackets` derives finals + SF matches from existing top-8 placement data
     `--counts` shows stored match counts per format
     `--dry-run` parses without saving
   - `db/matches_queries.py` — `matches` table: save_matches / get_matches / get_stored_event_ids / get_match_counts
   - `analysis/win_rates.py` — `get_real_matchup_winrates()` + `get_real_archetype_winrates()`
     both require `min_matches=20` threshold; return empty dict silently if table empty
   - Dashboard WIN RATE panel: real W/L shown as "54.3%★" with tooltip "Match W/L (n=142)"
     estimated values show as "54.3%" (slightly dimmed) with tooltip explaining source
   - **FIRST RUN**: `python -m scrapers.mtgmelee_scraper --test` to verify API endpoint shapes
     Then: `python -m scrapers.mtgmelee_scraper --infer-brackets` (free data from existing DB)
     Then: `python -m scrapers.mtgmelee_scraper --format standard --pages 5`

2. **Matchup Data tab fixes** (`gui/tabs/heatmap_tab.py`)
   - Fixed "Use Cached" crash: `theme.ERROR` → `theme.ERR` in `_PasteDialog`
   - Null-check: empty cache now shows friendly "No cached data yet — click Fetch Live Data first"
     instead of crashing; tracks `_load_source` to give context-specific message
   - `_filter_to_meta()`: cross-references `get_meta_standings()` top-30 and filters the
     256-archetype raw matrix down to only relevant meta decks, sorted by meta share descending
   - Info label shows "showing top N by meta share (filtered from 256)" when filtering is active
   - Auto-save on fetch was already in place (`_FetchWorker` calls `save_matchup_data`)

2. **Meta tier list badges** (Dashboard win rate panel)
   - New "Tier" column in the WIN RATE panel (4th column)
   - `_tier_badge(winrate, meta_share, is_declining)` static method on DashboardTab
   - S (gold) = win rate >55% AND meta share >8%
   - A (green) = win rate >52% OR meta share >5%
   - B (cyan) = everything else in top N
   - C (red) = declining trend (share dropped >0.5% vs prior period)
   - No new files — only `gui/tabs/dashboard.py` modified

---

## Session 2026-03-21 (session 3) Summary — What was added

1. **Archetype normalization — three-layer upgrade** (`analysis/archetypes.py`)
   - `pre_normalize()`: fixes spacing/hyphens/color abbreviations automatically
     ("Mono-Green Landfall" / "MonoGreen Landfall" / "monogreen landfall" → "Mono Green Landfall";
     "UR Prowess" → "Izzet Prowess"; "UWR Control" → "Jeskai Control")
   - `find_card_based_duplicates()`: finds pairs with similar names AND ≥67% card overlap
     (10% inclusion threshold); finds 125 pairs in Standard
   - `merge_archetypes(keep, remove)`: renames DB records for a confirmed merge
   - CLI: `--card-similarity --apply` for interactive review, `--pre-normalize` for preview

2. **Easy wins** (see below for what was completed this session)

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

## TOP PRIORITIES — Mar 25 (Session 3)

### Session 2026-03-25 (Session 3) Summary — What was completed

1. **Pioneer/Modern MTGMelee support verified** — `_FORMAT_MAP` already had correct format strings; both confirmed working: Pioneer (225 tournaments), Modern (778 tournaments)
2. **`background_fill.bat` updated** — added `[5/7] MTGMelee` section after MTGDecks; all 3 formats (standard/pioneer/modern) with `--pages 3`; step count updated from 6 to 7
3. **Heatmap "Use Cached" crash fixed** (`gui/tabs/heatmap_tab.py`) — added `_cancel_worker()` helper with RuntimeError guard; both `_fetch_live` and `_load_cached` now set `self._worker = None` on finish via `finished.connect(lambda: ...)`
4. **Predictions "how this works" info box** (`gui/tabs/predictions.py`) — static QFrame explaining top_meta/trending_up/trending_down prediction types and Validate flow
5. **Dashboard tier badge legend** (`gui/tabs/dashboard.py`) — tooltip on "Tier" column header explaining S/A/B/C colors and ★ real-data suffix
6. **Tray balloon first-time only** (`gui/main_window.py`) — close-to-tray balloon now shows once; `balloon_shown: true` saved to `scrape_state.json` after first display

### Session 2026-03-25 (Session 2) Summary — What was completed

1. **Dashboard Meta Impact bar** — shows dedup filter effect (rows removed, most affected archetypes)
2. **Dashboard worker lifecycle fix** — Refresh crash resolved (RuntimeError guard + `_panel_worker = None` on finish)
3. **Trend denominator fix** (`analysis/win_rates.py`) — `get_archetype_trend()` denominator now uses dedup-aware `COUNT(DISTINCT ...)` when `dedup_cross_source=True`
4. **MTGMelee scraper — full rewrite** (`scrapers/mtgmelee_scraper.py`)
   - melee.gg migrated to new API — both old endpoints dead
   - Tournament list: `POST /Tournament/TournamentSearch` with `filters[]` array
   - Pairings: GET view page → parse round `data-id` → POST `/Match/GetRoundMatches/{roundId}` with exact DataTables column payload
   - Dry-run verified: 21 tournaments, ~10k+ matches, exit code 0
5. **Swagger API explored** — all 21 REST endpoints at `/swagger/ui/index` require staff authentication; public DataTables approach is correct
6. **`db/saved_decks.py` created** — tables: `saved_decks` + `saved_sb_plans` (CASCADE delete); functions: save_deck, get_deck(s), delete_deck, save_sb_plan, get_sb_plan(s), delete_sb_plan; all tests pass
7. **Full MTGMelee scrape complete** — 221,163 real match records across all formats:
   - Standard: 108,648 matches (250 tournaments)
   - Pioneer:   20,095 matches  (58 tournaments — all available)
   - Modern:    92,420 matches (347 tournaments — all available)

---

### 1. Memory leak audit (CRITICAL — app crashed overnight)
- Audit all long-running threads, worker objects, and signal connections for leaks
- Check QuickScrapeWorker, FigureCanvasQTAgg, and DB connections for improper teardown
- Add resource tracking / explicit cleanup on close

### 2. My Decks GUI tab
- `db/saved_decks.py` **now exists** (created 2026-03-25)
- `gui/tabs/my_decks.py` — list saved decks, import from DB, add manually, edit/delete
- Click deck → shows 75 + all saved SB plans
- "Open in RCQ Optimizer" passes deck to tournament_prep.py

### 3. Fix remaining smoke test bugs
- ~~"Use Cached" crash in Matchup Data tab~~ — **FIXED** (2026-03-25 session 3): `_cancel_worker()` + `self._worker = None` on finish
- Auto-legality check triggers on Analyze (should only run on explicit button click)
- ~~Predictions tab "how this works" info box~~ — **DONE** (2026-03-25 session 3)

### 4. Legend/key for dashboard colors and star badges
- ~~Add tier badge legend~~ — **DONE** (2026-03-25 session 3): tooltip on "Tier" column header
- ~~Tray balloon first-time only~~ — **DONE** (2026-03-25 session 3): `balloon_shown` flag in scrape_state.json

---

## PREVIOUS TOP PRIORITIES (Mar 25 Session 1)

### My Decks GUI tab + RCQ Optimizer upgrade
- `db/saved_decks.py` exists (created 2026-03-25) — go straight to GUI
- `gui/tabs/my_decks.py` — list saved decks, import from DB, add manually, edit/delete
- Click deck → shows 75 + all saved SB plans
- "Open in RCQ Optimizer" passes deck to tournament_prep.py
- RCQ Optimizer: add saved deck selector dropdown at top
- Each matchup row: show saved SB plan if exists, fall back to guides table
- "Edit Plan" button per row → inline play/draw IN/OUT editor with difficulty badge
- Plans auto-save to saved_sb_plans table

### 2. Printable tournament guide export (Mar 25 Session 2)
- "Export Guide" on any saved deck → clean .txt or HTML
- Full 75 + each matchup as a section with ON PLAY / ON DRAW IN/OUT + notes
- Save to exports/ and auto-open; clean enough to print and fold for a tournament

## MEDIUM PRIORITY — Easy wins still TODO (do in order, commit after each)

### 3. Charts Compare Mode (~30 min)
- Change archetype field in Charts tab to multi-select QListWidget or editable combo
- Overlay multiple archetypes as lines on one trend chart
- No new files — only `gui/tabs/charts.py` + `gui/widgets/chart_canvas.py`

### 4. DB layer for My Decks — DONE (2026-03-25)
- `db/saved_decks.py` created and tested
- Tables: `saved_decks`, `saved_sb_plans` (CASCADE delete on deck removal)
- Functions: save_deck / get_decks / get_deck / delete_deck / save_sb_plan / get_sb_plan / get_sb_plans / delete_sb_plan
- Next: GUI tab (`gui/tabs/my_decks.py`)

### 5. Play/draw split in sideboard guides (~20 min)
- Upgrade `analysis/sideboard_guides.py`
- Add in_cards_play / out_cards_play / in_cards_draw / out_cards_draw fields
- Add difficulty field (Easy/Medium/Hard based on variance between lines)
- No new files — only `analysis/sideboard_guides.py`

### Remaining lower-priority features
- **User Preferences System** — format selection in setup wizard (page 0), wire scrapers to skip unselected formats
- **Knowledge Base improvements** — filter by archetype/format, full-text search, guide rating

## LOW PRIORITY / FUTURE

### PyInstaller Standalone .exe Packaging ← NOT YET (app still evolving)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" \
  --add-data "gui/fonts;gui/fonts"
```
Key things to verify when ready:
- `data/` folder stays external (DB + Scryfall bulk too large to embed)
- `--register-tasks` re-uses same .exe for UAC elevation
- `anthropic` optional (conditional import in ask_claude.py)
- `analysis/charts.py` sets `matplotlib.use("Agg")` — must not import before `run_gui.py` sets `QtAgg`
- Test on clean machine without Python

### Apr+ roadmap
- Cowork audit (card images, KB improvements)
- Card image hover preview in deck analyzer / search tabs
- Game simulation engine integration

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
