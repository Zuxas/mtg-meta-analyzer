# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-04-06

---

## TOP PRIORITIES — Active Sprint: Advanced Analytics Integration

### Phase 1. Prep Priority + Trap Detection (DONE)
- [x] `analysis/meta_scoring.py` — prep_priority() score 0-100, classify_status() labels
- [x] Statuses: Pillar (green), Trap (red), Underplayed (gold), Fringe (grey)
- [x] Dashboard Win Rate panel: Prep column (0-100, color-coded) + Status column
- [x] Scoring blends meta share (60%) + win rate (40%)

### Phase 2. Glicko-2 Power Ratings (DONE)
- [x] `analysis/ratings.py` — pure Python Glicko-2 implementation (no external deps)
- [x] Processes 262k+ real matches grouped into weekly rating periods
- [x] RatingResult: rating (µ), deviation (φ), volatility (σ), confidence interval
- [x] Dashboard Win Rate panel: Rating column with tooltip (CI, match count)
- [x] Color-coded: green ≥1600, orange ≥1500, red below avg; dimmed if high uncertainty
- [x] 120s TTL cache for performance

### Phase 3. Nash Equilibrium + RPS Cycles (DONE)
- [x] `analysis/equilibrium.py` — replicator dynamics, Nash LP solver, RPS cycle detection
- [x] Monte Carlo tournament simulation (simulate_tournament)
- [x] Heatmap tab: "Equilibrium" button → dialog with Optimal vs Actual + RPS cycles
- [x] Installed scipy 1.17.1

### Phase 4. Card Text Embeddings (DONE)
- [x] `analysis/card_embeddings.py` — 768-dim ModernBERT embeddings (32k cards)
- [x] `scripts/download_embeddings.py` — HuggingFace parquet download (90 MB)
- [x] Card Browser: "Similar Cards" section in card detail panel
- [x] Deck Analyzer: "Deck Similarity" section (vs meta archetypes)
- [x] Installed pyarrow 23.0.1

### Phase 5. Co-occurrence Embeddings / Card2Vec (DONE)
- [x] `analysis/cooccurrence_embeddings.py` — Word2Vec trained on 33k+ decklists
- [x] Card Browser: "Functional Substitutes" section in card detail panel
- [x] Models trained: Standard (33k decks), Modern (9k decks)
- [x] Installed gensim 4.4.0

### Phase 6. KNN Archetype Classifier (DONE)
- [x] `analysis/knn_classifier.py` — KNN on deck embeddings, hybrid_classify()
- [x] Deck Analyzer: auto-detect archetype (fills label in cyan italic)
- [x] Models trained: Standard (116 archetypes), Modern (115 archetypes)
- [x] Installed scikit-learn 1.8.0

---

### Dashboard Improvements (DONE — this session)
- [x] Popular panel: "Change" column replacing sparklines (% change vs prior period)
- [x] Win Rate panel: "Change" column (WR% delta vs prior period)
- [x] "NEW" entries get tooltip with apps count + meta share
- [x] Removed dead `_make_sparkline()` function

### Heatmap Improvements (DONE — this session)
- [x] Timeframe selector on Matchup Data tab (filters real match data by date)
- [x] Default 8 weeks — prevents stale pre-ban/rotation data

### Lower Priority
- ~~Consolidate .bat scripts into single launcher~~ DONE — `mtg.bat`
- ~~Match Logging Enhancements~~ DONE — personal WR vs meta (was already there), trend chart added
- ~~Settings buttons for "Download Embeddings" / "Train Card2Vec"~~ DONE
- ~~Monte Carlo simulation in Equilibrium dialog~~ DONE (was already wired)
- ~~Batch reclassify unknown archetypes~~ DONE — Standard 2, Pioneer 22, Legacy 24 reclassified
- ~~Team Collaboration: gauntlet export~~ DONE — Export button on Heatmap tab, import via Paste Data
- Team notes field on matchup heatmap cells
- PyInstaller .exe packaging

---

## Session 2026-04-06 — Advanced Analytics Integration (all 6 phases)

### New files created
1. `analysis/meta_scoring.py` — prep priority (0-100) + trap detection (Pillar/Trap/Underplayed/Fringe)
2. `analysis/ratings.py` — pure Python Glicko-2 implementation, weekly rating periods, 262k+ matches
3. `analysis/equilibrium.py` — Nash equilibrium (LP), replicator dynamics, RPS cycle detection, Monte Carlo sim
4. `analysis/card_embeddings.py` — 768-dim ModernBERT embeddings, similarity search, deck vectors
5. `analysis/cooccurrence_embeddings.py` — Card2Vec Word2Vec trained on local decklists
6. `analysis/knn_classifier.py` — KNN archetype classifier with hybrid_classify() fallback
7. `scripts/download_embeddings.py` — HuggingFace parquet downloader (90 MB)
8. `docs/AI_DEVELOPMENT_PROCESS.md` — process log for sharing with other devs

### Dashboard changes
- Win Rate panel: 8 columns (Pips/Archetype/Win%/Change/Rating/Prep/Status/Tier)
- Popular panel: Change column replacing sparklines
- Removed dead _make_sparkline() code

### Matchup Data changes
- Equilibrium button → Nash optimal vs actual shares, RPS cycles dialog
- Timeframe selector (1w to All Time, default 8w)

### Card Browser changes
- "Similar Cards" section (text-based embeddings)
- "Functional Substitutes" section (Card2Vec co-occurrence)

### Deck Analyzer changes
- "Deck Similarity" section (vs meta archetypes)
- Auto-detect archetype via KNN (cyan italic label)

### New dependencies
- scipy 1.17.1, pyarrow 23.0.1, gensim 4.4.0, scikit-learn 1.8.0

### Models trained
- Card2Vec: Standard (33k decks), Modern (9k decks)
- KNN: Standard (116 archetypes), Modern (115 archetypes)
- Embeddings: 32k cards downloaded from HuggingFace

---

## Session 2026-03-29/30 — Major feature batch + classifier fix

### Features built
1. **Match Log tab** — personal tournament match tracker with event/round/opponent/result/play-draw/game-by-game logging, matchup stats with play/draw WR splits, auto-incrementing rounds
2. **Generate Prep Package** — Event Optimizer button creates printable HTML with 75 + field matchups + personal records + SB plan status + gap warnings
3. **Meta Shift dialog** — Dashboard button comparing current vs prior period: rising/falling/new/gone archetypes sorted by biggest change
4. **60-second query cache** — 33x speedup on dashboard loads (1.3s → 39ms on cache hit)

### Bug fixes
- Dashboard auto-refresh on format/timeframe change (was requiring manual Refresh click)
- Charts tab worker crash (CompareLoader deleted) — safe deleteLater pattern
- Heatmap empty archetypes filtered from Charts tab heatmap
- Predictions NoneType crash when top8_rate is None from matches fallback
- Moxfield URL import 403 — switched to cloudscraper + v2 API
- MTGTop8 URL import — proper HTML parsing of deck_line divs
- SB plan opponent dropdown now uses deck's format, excludes existing plans
- Print SB Guide button on Sideboard Plans tab (compact 2-column layout)
- All Time chart capped to 52 weeks for performance
- Heatmap auto-reload on format change
- Tooltip "Matches logged" wording
- Knowledge Base last synced label
- Breaker Math top cut selector (8/16/32/64)
- Event Optimizer meta distribution timeframe tooltip

### Normalization
- Remaining archetype counts: Modern 705, Standard 1,113, Pioneer 293
- Long tail is genuine niche decks — min_arch_appearances=10 filter handles them

---

## Session 2026-03-27 — User Preferences System wired end-to-end

### What was built

1. **`gui/setup_wizard.py` — Format selection page 0**
   - New `_build_format_page()` method: checkboxes for Standard/Pioneer/Modern/Legacy
   - Standard pre-checked; others unchecked by default
   - `_save_format_prefs(formats)` saves immediately to `data/preferences.json` before Scryfall download
   - Standard forced into selection even if unchecked (required for core app)
   - `_next()` updated: page 0→1 saves formats, page 1→2 starts Scryfall, page 2→3 starts backfill
   - `_on_scryfall_done` fixed to advance to page index 3 (was 2, now offset by format page)
   - `_start_backfill()` uses selected formats from checkboxes (primary format for initial scrape)

2. **`fill_database.py` — Reads preferences at runtime**
   - Added `import json` to imports
   - New `_load_formats()` function reads `data/preferences.json`, returns `["standard"]` on any failure
   - `step_mtgtop8_backfill()` calls `_load_formats()` at start — no more module-level `BACKFILL_FORMATS`
   - `step_mtgdecks()` calls `_load_formats()` at start — no more module-level `MTGDECKS_FORMATS`
   - Safe to re-run: if preferences.json doesn't exist yet, defaults to Standard only

3. **`scripts/run_fill_from_prefs.py` — New script**
   - Reads `data/preferences.json` at runtime for format list
   - Runs MTGTop8, MTGDecks, MTGMelee, Scryfall enrichment, normalization, archive maintenance
   - MTGMelee always runs Legacy + Pauper in addition to selected formats (real match data is broadly useful)
   - Subprocess approach — each scraper runs as a child process with UTF-8 encoding set

4. **`background_fill.bat` — Simplified**
   - Was: 7 hardcoded sections with format-specific commands for Standard/Pioneer/Modern
   - Now: single call to `scripts\run_fill_from_prefs.py`
   - Format list is now owned entirely by preferences.json — change Settings → next scrape picks it up

### What this means for Claude Code sessions
- `fill_database.py` and `background_fill.bat` no longer need editing when adding/changing formats
- Format selection lives in `data/preferences.json` (gitignored) and `gui/tabs/settings.py`
- The setup wizard now correctly captures user intent before doing any network work
- `scripts/run_fill_from_prefs.py` is the canonical place to add new scraper steps

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
gui/tabs/tournament_prep.py      Event Optimizer (G1/G2G3 analysis, flip detection) + Breaker Math
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

2. **Sideboard Guide Integration in Event Optimizer**
   - `analysis/sideboard_guides.py` — new module
   - Parses free-text guide comments for IN/OUT sideboard plans
   - G2/G3 WR model: opponent's SB cards hurt you (-1.3%/card, cap 13%), your SB helps (+1.0%/card, cap 13%)
   - Flip detection: "FLIPPED" if G1 favored but G2/G3 not, "FLIPS IN YOUR FAVOR" if reverse
   - RCQ matchup table now shows G1 WR% and G2/G3 WR% columns
   - Clicking a matchup row shows per-matchup detail: flip verdict, WR breakdown, guide IN/OUT plans

3. **Expanded timeframe selector (all tabs)**
   - Options: 1w, 2w, 4w, 8w, 3mo, 6mo, 1yr, 2yr, All Time — centralized in `gui/theme.py`
   - All Time = `None` = no date filter on any query
   - Applied to: Dashboard, Charts, Deck Analyzer (load avg), Archetype Detail, Search H2H, Event Optimizer

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

### Session 2026-03-26 (Session 27) — 7-item feature batch

1. **Normalization audit** (Standard + Pioneer): 34 aliases, Standard 1,113 / Pioneer 293 archetypes
2. **URL Import**: Deck Analyzer "Import from URL" — Moxfield, Archidekt, MTGGoldfish, MTGTop8
3. **Knowledge Base**: Format + Archetype filter dropdowns, search includes comment/source text
4. **Card images**: Average Deck tab shows card image tooltips on hover, background prefetch from Scryfall (capped 30 cards, 100ms rate limit)
5. **Heatmap sticky headers**: replaced QScrollArea with direct QTableWidget (has built-in frozen headers)
6. **Layout consistency**: search tab margins fixed 12→8 to match all other tabs
7. **Sparklines**: Popular panel "Trend" column with 4-week mini line chart (QPainter, green/red/grey)
8. **Win Rate threshold**: raised to 15 appearances minimum
9. **Boros Energy**: Modern-only merge (21,417 matches)

---

### Session 2026-03-26 (Session 26) — Boros Energy merge, URL import, Popular panel

1. **Boros Energy Modern merge**: format-specific SQL update (not in aliases) — Boros Aggro→Boros Energy for Modern only. Now 21,417 total Modern matches.
2. **URL Import in Deck Analyzer**: "Import from URL" button + `_fetch_decklist_from_url()` supporting Moxfield (v3 API), MTGGoldfish (download endpoint), Archidekt (small API), MTGTop8 (HTML parse). Background worker with error handling.
3. **Popular panel**: sorting already worked correctly (sortByColumn + _SortItem with numeric sort role) — verified no change needed.

---

### Session 2026-03-26 (Session 25) — Standard + Pioneer normalization audit

1. **Standard**: Esper Pixie (6 variants → 6,122 matches), Izzet Cauldron (9 variants → 6,487), Four-Color Overlords (6 small variants consolidated), Izzet Spellementals (plural/Dimir → 1,888), Simic Rhythm (Nature's Rhythm + Five-Color → canonical), Convoke small variants, Azorious typo fix
2. **Pioneer**: Abzan Greasefang (Esper/Orzhov → 808), Jund Sacrifice (Rakdos/Golgari → 1,968), Izzet Creativity (4 small variants consolidated)
3. **Backfill**: 34 renames applied. Standard 1,113 (was 1,139), Pioneer 293 (was 301), Modern 706 (was 708)

---

### Session 2026-03-26 (Session 24) — Affinity + Neoform consolidation

1. **Izzet Affinity**: 18 variants (plain Affinity, Jeskai, Azorius, Grixis, etc.) consolidated → now 7,326 total matches (was 2,631)
2. **Simic Neoform**: 5 variants consolidated → now 517 total matches
3. **Backfill**: 23 renames applied, Modern 708 unique archetypes (was 731)

---

### Session 2026-03-26 (Session 23) — Trend data fallback to matches table

1. **`_archetype_trend_from_matches()`**: new function builds weekly/daily trend data from the matches table when the decks table has no recent data for an archetype
2. **`_parse_match_date()`**: handles both YYYY-MM-DD and DD/MM/YY date formats in the matches table (bracket-inferred matches use DD/MM/YY)
3. **Two fallback triggers in `get_archetype_trend()`**: (a) when `_fetch_appearances` returns empty (archetype not in decks table at all), (b) when decks-based trend has 0 total appearances across all buckets (stale data)
4. **Verified**: Izzet Prowess 795 apps/7w (from decks), Izzet Cauldron 0 apps/8w but 85 apps/52w (from matches — correctly shows deck fell out of meta recently), all archetypes produce valid trend data

---

### Session 2026-03-26 (Session 22) — Fix scraper Unicode crash, encoding for all entry points

1. **Root cause fixed**: `main.py` crashed with `UnicodeEncodeError: 'charmap' codec can't encode '\u0144'` when printing Polish player names. The `print()` call encoded to cp1252 (Windows default) which can't handle Unicode. This crash has been silently killing the daily scraper for months.
2. **Fix applied to all entry points**: `sys.stdout/stderr = TextIOWrapper(..., encoding='utf-8', errors='replace')` added to `main.py`, `scrapers/mtgdecks.py` (stderr was missing)
3. **Bat files**: `SET PYTHONIOENCODING=utf-8` added to `background_fill.bat` and `run_daily.bat` as defense-in-depth
4. **Verified**: `python main.py --format standard --pages 3` now processes events with Unicode player names without crashing

---

### Session 2026-03-26 (Session 21) — Meta standings fallback to matches table

1. **Root cause found**: decks table (MTGTop8/MTGDecks) is stale — last real data is Oct 2025. Daily scrapers run (Last Result: 0) but crash silently with UnicodeEncodeError on non-ASCII player names. Only ~50 obscure entries exist in recent weeks.
2. **Fallback built**: `get_meta_standings()` now checks if top archetype has <20 appearances or total <100. If so, falls back to `_meta_standings_from_matches()` which builds standings from the 262k real match records. Results tagged with `_source="matches"`.
3. **Dashboard warning**: when fallback is active, status bar shows orange "using match data — deck scraper needs refresh"
4. **Result**: Standard meta now shows Izzet Prowess (23,662 matches, 52.1%), Dimir Midrange (15,481, 50.0%), Mono Red Aggro (14,791, 50.7%) etc. — real data instead of "Momo-White" at 3 appearances.
5. **Scraper issue**: MTGTop8 `main.py` crashes with `UnicodeEncodeError: 'charmap' codec can't encode character '\u0144'` — needs encoding fix in stdout wrapper (separate task)

---

### Session 2026-03-26 (Session 20) — Fix default top 8, WR debug, event labels

1. **Top 8 by appearances**: `_rebuild_checkboxes()` now computes total appearances from `sample_data` and checks the 8 archetypes with the most data — no more Momo-White/Vivi appearing by default
2. **WR debug logging**: win_pct chart prints `[CHART WR] archetype: N/M weeks pass filter, smoothed range X-Y%` for each plotted archetype — helps verify the smoothing and minimum threshold
3. **Event marker labels**: fontsize 6→8, added `fontweight="bold"` for visibility
4. **Initial chart draw**: `_on_chart_data` now passes the top-8 visible set to `draw_from_data` on first load (was drawing all before checkboxes took effect)

---

### Session 2026-03-26 (Session 19) — Chart polish: event labels, WR smoothing, default top 8

1. **Event marker labels**: replaced `ax.text` with `ax.annotate(xycoords=("data","axes fraction"))` + `clip_on=False` so labels render above the chart area
2. **Win rate smoothing**: win_pct mode now suppresses weeks with <3 appearances, applies 3-point rolling average before plotting — eliminates 0-100% noise spikes
3. **Default top 8**: archetype checkboxes default to only top 8 checked (by meta share), rest unchecked — makes chart readable; user can check more via sidebar

---

### Session 2026-03-26 (Session 18) — Format event markers on timeline charts

1. **data/format_events.json**: manually maintained file with set releases, B&R announcements, and rotation dates for all 5 formats (28 events total covering last 18 months)
2. **chart_canvas.py**: `_draw_event_markers()` overlays vertical dashed lines at event dates — blue for set releases, orange for rotations, red for B&R. Short label rotated 45deg at top of line.
3. **Applied to all chart types**: `draw_from_data()`, `_draw_meta_share()`, `_draw_trend()`, `_draw_compare()` — all call `_draw_event_markers()` after plotting data
4. **Dashboard "Show Events" checkbox**: toggle next to Weekly/Daily buttons, default on, instant redraw on toggle — passed as `show_events` param to `draw_from_data()`
5. **Charts tab**: markers appear automatically (no separate toggle needed since Charts tab is less dense)

---

### Session 2026-03-26 (Session 17) — Legacy + Pauper archetype normalization

1. **89 new aliases** for Legacy and Pauper:
   - Legacy: Reanimator (7 variants → Dimir), Cephalid Breakfast (7→canonical), Sneak And Show (5→canonical), Death And Taxes (7→canonical), Doomsday (7→canonical), Omni-Tell (2→canonical), Storm variants, Oops! All Spells
   - Pauper: Affinity (7→Grixis), Bogles (7→Selesnya), Elves (7→Mono Green), Slivers (8→5C), Dredge (7→Jund), WUBRG codes for Cycle Storm, Poison Storm, Turbo Fog, Tron variants
2. **EXCLUDE_ARCHETYPES expanded**: added "Rogue Decklists" (731 Pauper matches), "Others" (356), "Other" (10)
3. **Backfill**: 89 renames applied across all formats
4. **After cleanup**: Standard 1,139 | Pioneer 301 | Modern 731 | Legacy 448 | Pauper 285

---

### Session 2026-03-26 (Session 16) — Legacy + Pauper support, full historical scrapes

1. **Pauper added** to `_FORMAT_MAP` in mtgmelee_scraper.py and heatmap format dropdown
2. **background_fill.bat** updated: Legacy + Pauper added to MTGMelee daily scrape (--pages 3 each)
3. **melee.gg tournament counts** (ceiling): Standard 882, Legacy 800, Modern 778, Pauper 576, Pioneer 225
4. **Full scrapes kicked off**: Modern 30 pages, Pioneer 15 pages, Legacy 10 pages, Pauper 10 pages

---

### Session 2026-03-26 (Session 15) — Major archetype consolidation + min-appearance filter

1. **35 new ALIASES**: Amulet Titan (10 splash variants → canonical), Eldrazi Tron (5 variants), Goryo's Vengeance (5 variants), Murktide (2→Dimir), Merfolk (2→canonical), Burn (2→canonical), 8-Rack (3→canonical), Birthing Ritual (2→Simic), Grinding Breach (3→canonical), Standard: Domain Overlords→Four-Color, Sultai Beanstalk→Four-Color, Azorius Midrange→Azorius Control
2. **min_arch_appearances=10 filter**: `get_real_matchup_winrates()` now pre-filters archetypes with <10 total match appearances, removing one-off junk entries from matchup calculations
3. **Backfill**: 35 renames applied. Key consolidations: Amulet Titan 8,567 matches, Goryo's Vengeance 5,623, Grinding Breach 6,239, Eldrazi Tron 4,578
4. **After cleanup**: Standard 1,151 (was 1,157), Modern 750 (was 782), Pioneer 302 (was 304)

---

### Session 2026-03-26 (Session 14) — Archetype normalization + junk exclusion

1. **EXCLUDE_ARCHETYPES** in win_rates.py: "Decklist" and "All Other Decklists" filtered from all real-match WR calculations via SQL NOT IN clause (1,106 matches excluded from analysis, not deleted from DB)
2. **47 new ALIASES** in archetypes.py: WUBRG codes (W-U-B-G → Four-Color), Five-Color → 5C, apostrophe fix (Goryo'S → Goryo's), UR/UW expansions, 4/5C → Four-Color, Red Deck Wins → Mono Red Aggro
3. **pre_normalize apostrophe fix**: regex fixes title() casing `'S` → `'s` for all names
4. **Backfill applied**: 247 archetype renames across matches table (player1_arch, player2_arch, winner_arch)
5. **After cleanup**: Standard 1,157 archetypes (was 1,235), Modern 782 (was 786), Pioneer 304 (unchanged)

---

### Session 2026-03-26 (Session 13) — Heatmap Overall WR column + Dashboard daily charts

1. **Heatmap Overall WR column**: fixed "Overall" column at index 0 in matchup grid — shows weighted average WR across all matchups for each archetype, color-coded. Tooltip shows "Overall WR: 54% (weighted by sample size), Total matches: n=1,247".
2. **Dashboard daily granularity**: Weekly|Daily toggle buttons next to Popularity/Win Rate mode buttons. `get_archetype_trend()` gains `granularity="daily"` parameter — daily uses 1-day buckets (capped at 90). `fetch_chart_data()` passes through granularity + stores `sample_data` for tooltips. Auto-suggest: timeframe ≤2 weeks defaults to Daily. `_reload_chart()` extracted so granularity toggle reloads without full refresh.

---

### Session 2026-03-26 (Session 12) — Modern heatmap coverage

1. **Modern min_matches lowered to 5** (was 10) — Modern meta is more diverse (786 unique archetypes in 92k matches), so pairings are spread thinner. At min_matches=5, 294 archetypes qualify.
2. **Verified data pipeline**: Modern produces 30-archetype grid via data-density sort. Top deck: Boros Energy (254 matchup cells at threshold 5). Archetype distribution confirmed healthy.
3. **Per-format thresholds**: Standard=20, Pioneer=10, Modern=5.

---

### Session 2026-03-26 (Session 11) — Heatmap archetype name matching fix

1. **Root cause**: melee.gg deck names (real match data) are completely different from MTGTop8/MTGDecks names used in meta standings — only 1/30 overlap even after normalize(). Fuzzy matching produced wrong matches ("Mono Red Control" -> "Mono White Control").
2. **Fix**: `_filter_to_meta` now tries normalized name matching first; if overlap < 40%, falls back to **data-density sort** (archetypes with the most matchup cells). This shows the 30 most data-rich archetypes regardless of naming, giving a full 30x30 grid.
3. **CombinedWorker**: normalizes all archetype keys in real + scraped matrices via `archetypes.normalize()`. Lower min_matches to 10 for Pioneer/Modern.
4. **Verified**: Standard now shows 30 archetypes (was 6), Pioneer/Modern get more coverage with threshold 10.

---

### Session 2026-03-26 (Session 10) — Window hiding to tray during loads + CSS warnings

1. **Window hiding to tray during loads**: `closeEvent` hid to tray on ALL close events, including programmatic ones from widget deletion cascades during heatmap grid replacement. Fixed by checking `event.spontaneous()` — only hide-to-tray for user-initiated close (X button, Alt+F4), ignore programmatic close events.
2. **CSS `min-length` warning**: `min-length` is not a valid Qt stylesheet property; replaced with `min-height` + `min-width` in theme.py scrollbar handle style.

---

### Session 2026-03-26 (Session 9) — Heatmap double-delete crash fix

1. **Root cause**: `_scroll.setWidget(new_grid)` destroys the old widget (Qt6: "will be destroyed when a new widget is set"), then `old_grid.deleteLater()` tried to delete the already-destroyed C++ object → segfault on every grid redraw
2. **Fix**: use `takeWidget()` to detach the old widget from the scroll area BEFORE setting the new one, then `deleteLater()` on the safely-detached reference

---

### Session 2026-03-26 (Session 8) — Heatmap grid replacement crash fix

1. **Root cause found**: `import sip` fails on this system (`sip` is only available as `PyQt6.sip`); the `try/except` silently swallowed the ImportError, so `sip.delete(old_layout)` never ran. On the second grid draw, `QVBoxLayout(self._grid_widget)` tried to set a new layout on a widget that already had one — Qt rejected it, widgets piled up, and eventually something crashed.
2. **Fix**: replaced `sip.delete(old_layout)` pattern with full widget replacement — `_draw_grid` creates a fresh `QWidget`, sets it as `_scroll`'s widget (which takes ownership and deletes the old one), then builds the new layout on the fresh widget. No `sip` import needed.

---

### Session 2026-03-26 (Session 7) — Heatmap gen-counter fix + background scrape time gate

1. **Heatmap gen-counter**: replaced `_is_busy()` debounce with `_load_gen` monotonic counter — all callbacks (`_on_data`, `_on_error`, `_on_combined_data`, `_on_worker_finished`) check `gen == self._load_gen` and silently discard stale results from cancelled loads
2. **Removed `wait(3000)`**: workers use `run()` (no event loop) so `quit()` was a no-op and `wait()` froze the GUI; signal-blocking + gen-counter is sufficient
3. **`_on_worker_finished`**: only calls `_set_busy(False)` if gen matches, preventing premature button re-enable
4. **Background scrape 4-hour time gate**: `_background_scrape()` reads `scrape_state.json` last_updated and skips if <4 hours old

---

### Session 2026-03-26 (Session 6) — Heatmap crash on format+source switch

1. **Crash root cause**: `finished → deleteLater` destroyed the C++ QThread before `_clear_worker_ref` lambda ran, causing `RuntimeError: wrapped C/C++ object has been deleted`
2. **Fix**: replaced split `deleteLater` + `_clear_worker_ref` with single `_on_worker_finished(w_ref)` that guards both with try/except RuntimeError
3. **`_cancel_worker`** now calls `w.quit()` + `w.wait(3000)` to actually stop the thread before starting a new one
4. **Debounce**: `_is_busy()` guard at top of each button handler — returns early if a worker is still running
5. **`_on_data` / `_on_error`**: only call `_set_busy(False)` if no new worker has started, preventing premature UI re-enable

---

### Session 2026-03-26 (Session 5) — Heatmap stability fixes

1. **Worker lifecycle crash fix** — `_wire_worker()` captures worker in a local variable for `deleteLater` lambda; `_clear_worker_ref()` only clears `self._worker` if it still points to the same worker; prevents deleting a newer worker when an old one finishes
2. **Format-aware data flow** — all workers now emit `(format_name, matrix)` tuples; `_on_data` uses the loaded format for filtering (not the current combo value); `_loaded_format` tracks which format the current grid belongs to
3. **Clean source switching** — `_prepare_load()` cancels old worker, clears `_current_matrix`/`_source_map`/`_updated_lbl`, disables format combo during load; all three buttons work at any time without crashing
4. **Low-coverage warning** — shows orange note when <8 archetypes with 20+ matches for non-Standard formats

---

### Session 2026-03-26 (Session 4) — Tournament Prep → Event Optimizer upgrade

1. **Event type selector** — RCQ/RC/PTQ/Custom presets auto-set player range + rounds
2. **New math** — `x_loss_cutoff()`, `day2_conversion_probability()`, `EVENT_PRESETS` in analysis/tournament.py
3. **Renamed** — `_RCQWidget` → `_EventWidget`, "RCQ OPTIMIZER" → "EVENT OPTIMIZER" throughout all files
4. **"Use Meta Distribution" button** — dedicated button always visible, fills field from top 12 meta archetypes scaled to player count
5. **Player count max → 5000** — supports Pro Tour-scale events
6. **Results show** — X-loss cutoff ("Need 8-2 or better"), day-2 conversion % for 2-day events (≥200 players, ≥9 rounds)
7. **`cut_threshold` fix** — now uses `rounds*3 - 6` for 9+ rounds (X-2 heuristic) instead of `(rounds-1)*3`

---

### Session 2026-03-26 (Session 3) — Heatmap rewrite + bug fixes

1. **Heatmap rewrite** — combined view merges real match data (★) + scraped MTGDecks data
   - `_CombinedWorker` builds bidirectional matrix from canonical real data + cached scrapes
   - "Real Match Data (DB)" is now the primary button; MTGDecks Live is secondary
   - `_filter_to_meta()` fixed: uses case-insensitive + substring matching
   - Source shown per cell (★ for real, tooltip says source + sample n=X)
   - Legend updated with ★ = real / no star = scraped

---

### Session 2026-03-26 (Session 2) — Bug fixes

1. **Heatmap "Use Cached" fix** — `_on_data` and `_on_error` now explicitly restore `_scroll`/`_status` visibility and call `self.setVisible(True)` guard
2. **My Decks SB plan CRUD** — Added `_SBPlanDialog` with opponent, difficulty, play/draw IN/OUT fields; `+ Add Plan` and `Delete Plan` buttons on Sideboard Plans sub-tab
3. **Charts Compare Trends polish** — styled compare label, added selection mode to list, Enter key in archetype field adds to compare list when in Compare mode
4. **RCQ auto-populate field** — when field is blank, loads top 12 meta archetypes by share % and populates field input; shows "Field assumed from meta standings"
5. **Recent Top Finishes "This List" tab** — `deck_id` added to recent query, stored in UserRole, passed to ArchetypeDetailDialog which adds "This List" tab showing the exact 75 for that finish

---

### 1. ~~Memory leak audit~~ — **DONE** (2026-03-26)
- Audited all 11 worker threads, 3 FigureCanvasQTAgg instances, ~100 DB connections
- Fixed: `setup_wizard.py` closeEvent now calls deleteLater() for both workers
- Fixed: `deck_analyzer.py` _AnalyzeWorker now has deleteLater + setattr(None) + signal blocking
- Fixed: `ask_claude.py` _StreamWorker now has deleteLater on both done and error signals
- Fixed: `predictions.py` all 5 bare conn.close() wrapped in try/finally
- Fixed: `scrapers/guides.py` conn.close() wrapped in try/finally
- Added: `cleanup()` methods on DashboardTab, HeatmapTab, ChartsTab, DeckAnalyzerTab, AskClaudeTab
- Added: `MainWindow.cleanup()` orchestrator — stops all workers, called via `app.aboutToQuit`
- Added: `run_gui.py` wires `app.aboutToQuit.connect(window.cleanup)`

### 2. ~~My Decks GUI tab~~ — **DONE** (2026-03-26)
- `gui/tabs/my_decks.py` created — full CRUD tab with split-panel layout
- Left: deck list with format filter, Add/Edit/Delete buttons
- Right: deck detail with Decklist and Sideboard Plans sub-tabs
- Add/Edit dialog: name, format, archetype, notes, Arena/MTGO paste
- Export (MTGO/MTGA/decklist.org) and "Open in Event Optimizer" buttons
- Wired in main_window.py as "MY DECKS" tab (3rd position, after Deck Analyzer)
- `open_in_rcq` signal → MainWindow switches to Tournament Prep tab

### 3. Fix remaining smoke test bugs
- ~~"Use Cached" crash in Matchup Data tab~~ — **FIXED** (2026-03-25 session 3): `_cancel_worker()` + `self._worker = None` on finish
- ~~Auto-legality check triggers on Analyze~~ — **FIXED** (2026-03-26): `_AnalyzeWorker` now passes `check_legality=False` to `analyze_deck()`; legality only runs on explicit "Check Legality" button click
- ~~Predictions tab "how this works" info box~~ — **DONE** (2026-03-25 session 3)

### 4. Legend/key for dashboard colors and star badges
- ~~Add tier badge legend~~ — **DONE** (2026-03-25 session 3): tooltip on "Tier" column header
- ~~Tray balloon first-time only~~ — **DONE** (2026-03-25 session 3): `balloon_shown` flag in scrape_state.json

---

## PREVIOUS TOP PRIORITIES (Mar 25 Session 1)

### ~~My Decks GUI tab + Event Optimizer upgrade~~ — **DONE** (2026-03-26)
- `gui/tabs/my_decks.py` — full CRUD tab with split-panel layout, Export Guide
- Event Optimizer: saved deck dropdown at top, populated from saved_decks by format
- Selecting a deck sets archetype and format automatically
- `load_deck()` method on TournamentPrepTab wired from My Decks → Open in Event Optimizer

### 2. ~~Printable tournament guide export~~ — **DONE** (2026-03-26)
- "Export Guide" button on My Decks tab → generates clean HTML in exports/
- Full 75 + per-matchup sections with difficulty badge, ON PLAY / ON DRAW IN/OUT, notes
- Dark theme for screen, print media query for clean B&W printing
- Auto-opens in browser via QDesktopServices

## MEDIUM PRIORITY — Easy wins still TODO (do in order, commit after each)

### 3. ~~Charts Compare Mode~~ — **DONE** (2026-03-26)
- Added "Compare Trends" chart type to Charts tab
- QListWidget for selected archetypes with Add/Remove buttons
- `_CompareLoader` worker fetches trend data for multiple archetypes in parallel
- Overlaid meta share lines on one chart, reusing chart palette and dark theme

### 4. DB layer for My Decks — DONE (2026-03-25)
- `db/saved_decks.py` created and tested
- Tables: `saved_decks`, `saved_sb_plans` (CASCADE delete on deck removal)
- Functions: save_deck / get_decks / get_deck / delete_deck / save_sb_plan / get_sb_plan / get_sb_plans / delete_sb_plan
- Next: GUI tab (`gui/tabs/my_decks.py`)

### 5. ~~Play/draw split in sideboard guides~~ — **DONE** (2026-03-26)
- `parse_sb_plan()` now detects "On the play" / "On the draw" / OTP / OTD markers
- Returns `play_in`, `play_out`, `draw_in`, `draw_out` + `has_play_draw` flag
- `_merge_sb_plans()` merges play/draw fields across multiple guides
- `render_guide_html()` shows ON THE PLAY / ON THE DRAW sections when available
- Falls back to generic IN/OUT when no play/draw markers present

### Remaining lower-priority features
- ~~**User Preferences System**~~ — **DONE** (2026-03-27)
  - Setup wizard now has page 0: format checkboxes (Standard pre-checked), saves `preferences.json` immediately before Scryfall download begins
  - `fill_database.py` reads preferences via `_load_formats()` — `BACKFILL_FORMATS` and `MTGDECKS_FORMATS` now driven by user selection, not hardcoded
  - `scripts/run_fill_from_prefs.py` — new script reads preferences and runs all scraper steps for selected formats only; Legacy/Pauper always get MTGMelee scrapes
  - `background_fill.bat` simplified to single call to `scripts/run_fill_from_prefs.py`
- ~~**Knowledge Base improvements**~~ — **DONE** (2026-03-26): format/archetype filter dropdowns, full-text search across comments

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

### Lower-priority features (all others complete)
- Rate guides thumbs up/down in Knowledge Base
- Match logging personal tracker (opponent arch, result, play/draw, notes)
- Card adoption & progression tracking over time
- Game simulation engine integration

---

## Data status (as of 2026-03-27)

| Format | Decks (MTGTop8/MTGDecks) | Matches (MTGMelee) | Notes |
|---|---|---|---|
| Standard | 37,186 decks / 3,834 events | 108,648 matches / 250 tournaments | Daily 6 AM task active |
| Modern | 6,770 decks / 233 events | 92,420 matches / 347 tournaments | All available scraped |
| Pioneer | 5,657 decks / 210 events | 20,095 matches / 58 tournaments | All available scraped |
| Legacy | 115 decks / 10 events | 25,304 matches / 86 tournaments | Active |
| Pauper | — | 16,174 matches / ~130 tournaments | Active |
| Guides | 331 guides | — | Skill Issue Magic sheet, last synced 2026-03-21 |

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
- `estimate_postboard_wr` clamps output to [0.18, 0.84] — extreme WR values will appear slightly less extreme post-board than they really are. This is intentional conservatism.
- `scripts/run_fill_from_prefs.py` is the canonical place to add new scraper steps — do NOT edit background_fill.bat directly for format changes.
