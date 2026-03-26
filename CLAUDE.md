# CLAUDE.md - MTG Meta Analyzer Project Context

Last updated: 2026-03-26

---

## NON-NEGOTIABLE RULES

1. **ALWAYS update CLAUDE.md, NEXT_STEPS.md, and ROADMAP.md before every commit — no exceptions**
2. **ALWAYS `git push` after every commit**
3. **ALWAYS run `--counts` or verify output after any scrape**
4. **Documentation must reflect actual current state, not planned state**

---

## Project Purpose
Build an automated tool to analyze competitive Magic: The Gathering tournament
data. Primary goal: give the user a competitive edge preparing for the Pro Tour
by surfacing meta trends, identifying rising archetypes, and evaluating decklists
against historical performance data.

## GitHub
https://github.com/Zuxas/mtg-meta-analyzer (private repo)

## Environment
- Windows 11, VS Code
- Python 3.13
- Shell: **cmd (Command Prompt)** — default terminal set to cmd in .vscode/settings.json
- Project root: `E:\vscode ai project\mtg-meta-analyzer`
- Always open VS Code from the project folder so Claude Code registers the correct project path
- User has limited coding experience; AI assistants are primary dev support

## Current State (as of 2026-03-25)

### Working
- MTGTop8 scraper pulls events, decklists (main + sideboard), player names
- MTGO Challenge-specific scraper (`scrapers/challenges.py`)
- Historical backfill scraper (`scrapers/backfill.py`) — pages backwards
  year-by-year using MTGTop8 year-specific meta filters
- SQLite database storing events, decks, cards, deck_cards, card_data
- Format-aware archive-based retention policy (not deletion)
- Daily automated scraper via Windows Task Scheduler:
  - `run_daily.bat` — 5 PM daily (Standard latest events + archive maintenance)
  - `background_fill.bat` — 6 AM daily (Standard + Pioneer + Modern, both sources)
- Average deck calculator and deck comparison (`analysis/deck_analysis.py`)
- CLI query tool (`analysis/query.py`) with subcommands:
    average, compare, search, top-cards, last-challenge
    meta, trend, h2h, matchups, matrix, field-optimizer
    card, enrich-stats, suggest-aliases, normalize
    chart meta, chart trend, chart heatmap
    predict, validate-predictions, prediction-report
    blunder, chapin
- Win rate / performance tracking (`analysis/win_rates.py`):
  - Placement-based estimated match W/L per archetype
  - Meta standings, weekly trend, head-to-head, full matchup breakdown
  - NxN matchup matrix; Field Optimizer (weighted win% vs expected field)
  - Natural language date range filtering ("last 30 days", "feb2-mar9")
  - `get_archetype_trend()` handles `weeks=None` as "All Time" (no date filter)
- Scryfall card enrichment (`scrapers/scryfall.py`):
  - 3-tier lookup: SQLite → local bulk JSON → live API (last resort only)
  - Bulk Oracle Cards downloaded to data/scryfall_oracle.json (~162 MB)
  - Loaded into memory once per process; auto-refreshes weekly (Sunday midnight)
  - Enriches card_data table: mana cost, CMC, colors, type, oracle text,
    power/toughness, rarity, set, format legalities
  - `get_card_data()`, `get_cards_data()`, `is_legal()` helpers
  - `search_local(query)`: fuzzy + NL search in local file (no API calls)
  - `get_deck_usage(name, format)`: tournament presence stats
- Archetype name normalization (`analysis/archetypes.py`) — three-layer system:
  - Layer 1: `pre_normalize()` — fixes spacing/hyphens/color abbreviations before alias lookup
    ("Mono-Green Landfall", "MonoGreen Landfall", "monogreen landfall" → "Mono Green Landfall";
    "UR Prowess" → "Izzet Prowess"; "UWR Control" → "Jeskai Control" — automatic, no alias needed)
  - Layer 2: ALIASES table — hard-coded exact mappings (fast, deterministic)
  - Layer 3: optional fuzzy match via thefuzz
  - `suggest_aliases()` scans DB for likely duplicate names
  - `find_card_based_duplicates(format, name_threshold, card_overlap)` — finds pairs sharing
    both similar names (fuzzy) AND similar mainboards (≥67% card overlap at 10% inclusion);
    returns 125 pairs for Standard — use `--card-similarity --apply` for interactive merge
  - `merge_archetypes(keep, remove)` — renames all decks from one name to another
  - `apply_normalization(dry_run, fuzzy)` — retroactive DB migration
  - CLI: `python -m analysis.archetypes --apply`
  - CLI: `python -m analysis.archetypes --card-similarity --format standard --apply`
  - CLI: `python -m analysis.archetypes --pre-normalize` (preview format-only fixes)
- Self-Validation & Prediction Logging (`analysis/predictions.py`):
  - Auto-generates top_meta / trending_up / trending_down predictions from meta data
  - Stores in `predictions` SQLite table; validates after target week passes
  - Accuracy tracked per prediction type (which signals are most reliable)
  - Run: `python -m analysis.query predict`, `validate-predictions`, `prediction-report`
- Deck Scoring & Blunder Detection (`analysis/blunders.py`):
  - Checks: land count, mana curve, color consistency, interaction, threats, deck size, legality
  - Severity tiers: Major (10pt), Moderate (4pt), Minor (1pt) → Construction Quality rating
  - Run: `python -m analysis.query blunder "Izzet Prowess"`
- Chapin Principles Evaluation (`analysis/chapin.py`):
  - Six principles: Threats (20%), Answers (20%), Consistency (18%), Velocity (15%), Mana (17%), Clock (10%)
  - Each scored 0-10 with bar display; overall weighted average + recommendation
  - Run: `python -m analysis.query chapin "Izzet Prowess"`
- Trend charts (`analysis/charts.py`) — wired into `chart` subcommand:
  - `chart meta` — line chart, meta share % per week for top N archetypes
  - `chart trend` — dual-axis: bars=appearances, lines=meta/win/top8 rates
  - `chart heatmap` — NxN matchup heatmap with RdYlGn colormap
  - Dark theme, saves PNG to `data/charts/`, auto-opens on Windows
- VS Code workspace settings (`.vscode/settings.json`)
  - Default terminal: Command Prompt (cmd) — NOT Git Bash
- Claude Code project permissions (`.claude/settings.json`)
  - Read-only query commands auto-approved (no confirmation prompt)
- **Sideboard Guide Integration** (`analysis/sideboard_guides.py`):
  - `parse_sb_plan(comment)`: parses free-text guides for IN/OUT card lists
    using regex patterns for `+N Name`, `-N Name`, `IN:`, `OUT:`, `bring in`, etc.
    Supports play/draw split via "On the play"/"On the draw"/OTP/OTD markers;
    returns `play_in`, `play_out`, `draw_in`, `draw_out`, `has_play_draw`
  - `get_matchup_guides(my_arch, opp_arch, fmt)`: queries DB for guides tagged
    with either archetype, separates into my_guides/opp_guides, merges SB plans
  - `estimate_postboard_wr(g1_wr, my_sb_in, opp_sb_in)`: models G2/G3 WR shift:
    opp_impact = min(opp_sb_in × 0.013, 0.13), my_impact = min(my_sb_in × 0.010, 0.13)
    g23_wr = clamp(g1_wr - opp_impact + my_impact, 0.18, 0.84)
  - `flip_analysis(g1_wr, g23_wr, has_guide_data)`: detects FLIPPED matchups,
    significant WR drops, favorable post-board swings
  - `render_guide_html(guide_data, my_arch, opp_arch)`: HTML with IN/OUT for both sides
- **Real Match W/L Pipeline** (`scrapers/mtgmelee_scraper.py` + `db/matches_queries.py`):
  - Source: **melee.gg** (not mtgmelee.com — that domain doesn't resolve)
  - Stores in `matches` table: (event_id, round, player1, player2, player1_arch, player2_arch, winner_arch, result, format, event_date, source)
  - `source` values: 'mtgmelee' (live scrape), 'bracket_finals', 'bracket_sf' (inferred)
  - Bracket inference: `--infer-brackets` flag derives finals + SF matches from existing top-8 placement data
  - `get_real_matchup_winrates(format, since, min_matches=20)` in `analysis/win_rates.py`
  - `get_real_archetype_winrates(format, since, min_matches=20)` in `analysis/win_rates.py`
  - Dashboard WIN RATE panel uses real match W/L where n≥20; shows "54.3%★" (star = real data)
    tooltip shows "Match W/L (n=142): 85W – 57L – 0D" vs "Estimated from placement tier"
  - CLI: `python -m scrapers.mtgmelee_scraper --format standard --pages 9`
  - CLI: `python -m scrapers.mtgmelee_scraper --test` (verify endpoints and print sample data)
  - CLI: `python -m scrapers.mtgmelee_scraper --infer-brackets`
  - CLI: `python -m scrapers.mtgmelee_scraper --counts`
  - **Current endpoints (updated 2026-03-25 — scraper fully rewritten):**
    - Tournament list: `POST https://melee.gg/Tournament/TournamentSearch`
      body: `{ordering, mode, filters[]=["Standard","MagicTheGathering","Ended"], variables[draw/start/length/...]}`
      response: `{recordsTotal, data: [{id, name, formatString, startDate, enrolledPlayerCount, gameDescription, ...}]}`
    - Pairings (3-step flow):
      1. `GET /Tournament/View/{tid}` — establishes session cookies
      2. Parse `<button class="round-selector" data-id="{roundId}" data-is-started="True">` from HTML
      3. `POST /Match/GetRoundMatches/{roundId}` with DataTables column payload
         columns (exact order): TableNumber, PodNumber, Teams, Decklists, ResultString
         headers: `X-Requested-With: XMLHttpRequest`, `Referer: /Tournament/View/{tid}`
    - Match JSON: `Competitors[i].Team.Players[0].DisplayName` (player name),
      `Competitors[i].Decklists[0].DecklistName` (deck), `Competitors[i].GameWins` (result)
    - "No started rounds" warnings on bundle events are expected (bundles have no direct pairings)
  - **Swagger API** at `https://melee.gg/swagger/ui/index` — all 21 endpoints require staff auth (401); not usable without credentials

- **Dashboard Meta Impact bar** (`gui/tabs/dashboard.py`):
  - `_impact_bar` QFrame between mode selector and chart — shows dedup filter effect
  - `_compute_impact(standings, raw_standings)` compares raw vs deduplicated appearance counts
  - Displays: rows removed, % removed, top-3 most-affected archetypes (with delta), most stable archetype
  - Hidden when dedup filters are off or remove zero rows
- **Worker lifecycle & cleanup** (audited 2026-03-26):
  - All worker threads now connect `finished → deleteLater()` and `finished → setattr(None)`
  - All tabs with workers expose `cleanup()` — stops workers, blocks signals, clears refs
  - `MainWindow.cleanup()` calls each tab's `cleanup()` + stops `_scrape_worker`
  - `run_gui.py` wires `app.aboutToQuit.connect(window.cleanup)` for clean exit
  - `_cancel_worker()` pattern: `blockSignals(True)` with `RuntimeError` guard for dead C++ objects
  - DB connections in `analysis/predictions.py` and `scrapers/guides.py` wrapped in try/finally
- **Trend denominator fix** (`analysis/win_rates.py`):
  - `get_archetype_trend()` denominator uses `COUNT(DISTINCT COALESCE(d.deck_fingerprint || '|' || e.event_fingerprint_cs, CAST(d.id AS TEXT)))` when `dedup_cross_source=True`
  - Mirrors Python dedup filter logic; NULL fingerprints fall back to `d.id`
- **My Decks DB backend** (`db/saved_decks.py`):
  - Tables: `saved_decks` (id, name, format, archetype, mainboard JSON, sideboard JSON, notes, created_at)
            `saved_sb_plans` (id, deck_id, opponent_archetype, play_in/out/draw_in/out JSON, notes, difficulty, updated_at)
  - CASCADE delete: removing a deck removes all its SB plans
  - `ON CONFLICT ... DO UPDATE` for upsert on (deck_id, opponent_archetype)
  - Functions: `save_deck`, `get_deck`, `get_decks`, `delete_deck`, `save_sb_plan`, `get_sb_plan`, `get_sb_plans`, `delete_sb_plan`

- **Live Matchup Data** (`scrapers/matchup_scraper.py` + `db/matchup_queries.py` + `gui/tabs/heatmap_tab.py`):
  - Scrapes MTGDecks.net `/winrates` page using existing `cloudscraper` setup
  - Parses `data-winrate` attribute from the NxN HTML table (256 archetypes, ~3,181 cells for Standard)
  - Stores in new `matchup_matrix` SQLite table (format, archetype_a, archetype_b, winrate, matches, fetched_at)
  - New **MATCHUP DATA** tab: Fetch Live / Use Cached / Paste Data (CSV or JSON)
  - Color-coded QTableWidget grid: deep green ≥60%, light green 55-59%, grey ~even, red shades for unfavored
  - Tooltip per cell: archetype names, win%, verdict (Favored/Even/Unfavored), sample size
  - Paste dialog accepts CSV (Frank Karsten format) or JSON matchup tables
  - CLI: `python -m scrapers.matchup_scraper --format standard --save`

- **PyQt6 GUI** — fully wired, personal website theme applied:
  - Entry point: `run_gui.py`
  - Theme: `gui/theme.py` — #3b3c4d bg, #65bcd5 cyan, Orbitron heading font
  - **9 tabs**: Dashboard, Deck Analyzer, My Decks, Search, Charts, Tournament Prep, Knowledge Base, Matchup Data, Ask Claude (optional), Settings
  - Setup wizard on first run (Scryfall download + backfill + 50-event unlock)
  - Interactive embedded matplotlib charts (FigureCanvasQTAgg)
  - Background QuickScrapeWorker on startup for returning users
  - **System tray icon** (`gui/tray_icon.py`) — green/orange/red status dot, right-click menu, close-to-tray
  - **One-time UAC first-run wizard** (`gui/first_run_setup.py`) — registers all 3 Task Scheduler tasks once, never asked again
  - `app.setQuitOnLastWindowClosed(False)` — app stays alive when window is closed
  - **Dashboard performance fix**: `get_meta_standings` uses single bulk SQL query (was 918 queries → 1); load time 9s → 0.07s
  - Dashboard auto-populates on startup; Weeks filter applies to both table and chart
  - **Untapped.gg-inspired layout**: three-column top panel (Recent Top Finishes / Win Rate / Popular), Popularity Over Time + Win Rate Over Time toggleable charts, archetype checkboxes
  - Panel titles are **dynamic**: "WIN RATE — 2 WEEKS", "POPULAR — 4 WEEKS" etc. update with timeframe selector
  - **Archetype detail dialog** (`gui/widgets/archetype_detail.py`): single-click any archetype → avg decklist (inclusion % + avg copies), recent 5 lists side-by-side, tech choices (15–80% inclusion)
  - **Date filter fix**: all panels use SQLite CASE expression (`_DATE_KEY`) to normalize `DD/MM/YY` (MTGTop8) and `YYYY-MM-DD` (MTGDecks) to `YYYYMMDD` for correct filtering/ordering everywhere
  - **Click handler fix**: Recent Top Finishes archetype cell stores raw name in `UserRole`; color-identity prefix no longer breaks deck detail lookup
  - **Player column**: Recent Top Finishes shows Place / Colors / Archetype / Player / Event / Date (6 columns)
  - **Mana color pips**: `theme.make_pip_widget()` uses `QPainter.drawEllipse()` with antialiasing — guaranteed true circles regardless of Qt stylesheet limitations
  - **Trend color-coding**: Win Rate and Popular panel rows tinted dark green (rising) / dark red (falling) vs the prior equivalent period
  - **Meta tier badges**: Win Rate panel has a "Tier" column — S (gold, >55% WR + >8% share), A (green, >52% WR or >5% share), B (cyan, top N rest), C (red, declining trend)
  - **Deck export** (`gui/widgets/deck_export.py`): Export button on archetype detail + Deck Analyzer + My Decks → MTGO .txt, MTGA .txt, or decklist.org tournament registration sheet (opens in browser)
  - **My Decks tab** (`gui/tabs/my_decks.py`): split-panel CRUD for saved decks
    - Left panel: format-filtered deck list with Add/Edit/Delete buttons
    - Right panel: deck detail with Decklist and Sideboard Plans sub-tabs
    - Add/Edit dialog: name, format, archetype, notes, Arena/MTGO paste
    - Export and "Open in RCQ Optimizer" buttons on deck detail
    - `open_in_rcq` signal wired to MainWindow → switches to Tournament Prep tab
  - **Load Average Deck**: Deck Analyzer has archetype dropdown + weeks filter + Load button; populates text box with avg deck in Arena format, ready to analyze or export
  - **Deck parser**: handles all sideboard formats — `Sideboard`, `SIDEBOARD:`, `SB:`, `// Sideboard`, `SB: 4 Card`, blank-line fallback
  - **Decklist Legality Checker**: Deck Analyzer tab has a "Check Legality" button that:
    - Parses the decklist textarea (main + side)
    - Queries `card_data.legalities` (JSON column) for all cards in one `IN` query
    - Falls back to `get_card_data()` for any missing cards
    - Checks deck size (main=60, side≤15) and per-card legal status
    - Color-coded table: red=banned, orange=restricted/not_legal, yellow=size issues
    - Shows ✓ or ✗ summary label with issue count
  - **Card images**: Card Lookup tab fetches card art from Scryfall API on first search, cached to `data/card_images/`
  - **Deck search click-to-detail**: clicking any row in Deck Search opens ArchetypeDetailDialog
  - **Charts autocomplete**: Archetype field is now an editable dropdown populated from DB, refreshes on format change
  - **Charts Compare Mode**: "Compare Trends" chart type — select multiple archetypes, overlay meta share lines on one chart; `_CompareLoader` worker in chart_canvas.py
  - **Desktop shortcut**: `launch_app.bat` (double-click launcher) + `create_shortcut.bat` (creates `MTG Meta Analyzer` shortcut on OneDrive Desktop)
  - **Knowledge Base tab**: add/browse bookmarks + guides table, Sync Guides button
  - **Ask Claude tab** (optional): hidden until API key set in Settings; streams meta-aware chat via `claude-opus-4-6` with adaptive thinking
  - **Tournament Prep tab** (2 sub-tabs):
    - **RCQ Optimizer**: enter format/player count/archetype/field → binomial top-cut probability, field grade, matchup breakdown with G1 WR%, G2/G3 WR%, guide-aware flip detection, sideboard recommendations
    - **Breaker Math**: real-time W/L/D tracker, ID calculator, draw equity, pair-down warning, seeding impact, breaker education

### Centralized Timeframe Selector (all tabs)
`gui/theme.py` exports `TIMEFRAME_OPTIONS` and `TIMEFRAME_DEFAULT`:
```python
TIMEFRAME_OPTIONS = [
    ("1 week", 1), ("2 weeks", 2), ("4 weeks", 4), ("8 weeks", 8),
    ("3 months", 13), ("6 months", 26), ("1 year", 52),
    ("2 years", 104), ("All Time", None),
]
TIMEFRAME_DEFAULT = "2 weeks"
```
`None` = All Time = no date filter. All tabs that use a timeframe selector
(Dashboard, Charts, Deck Analyzer load-avg, Deck Detail, Search H2H, RCQ Optimizer)
read from this list and pass `since=None` when All Time is selected.
All SQL query functions already handle `since=None` via `if since:` guards.

### Primary Format
Standard is the primary focus. Pioneer and Modern actively scraped. Legacy supported but not scheduled.

## Database

### Active DB
`data/mtg_meta.db` — events within the retention window; used by all analysis.

### Archive DB
`data/mtg_archive.db` — data older than retention window; moved here not deleted.
Use `--include-archive` flag (via `get_combined_connection()`) to query across both.

Both DB files are gitignored. After cloning: run `fill_database.bat`

### Current data (as of 2026-03-25)
- Standard: 2,043+ events, ~24,289+ decks (Nov 2024 – Mar 2026), 99.98% card coverage
- Pioneer: 109 events, 3,125 decks (MTGDecks 20-page scrape completed 2026-03-21)
- Modern: scraping in background; enrich after with `python -m scrapers.scryfall`
- Matches (MTGMelee): 221,163 real match records across all formats (as of 2026-03-26)
  - Standard: 108,648 matches (250 tournaments, 9-page run)
  - Pioneer:   20,095 matches  (58 tournaments, all available data)
  - Modern:    92,420 matches (347 tournaments, all available data)
- Daily 6 AM task registered — maintains Standard + Pioneer + Modern going forward
- Guides: 331 guides from Skill Issue Magic sheet (last synced 2026-03-21)

### card_data table
Keyed by card name (TEXT PRIMARY KEY) — not card_id — so it works seamlessly
across both active and archive DBs. Populated by `python -m scrapers.scryfall`.

## Retention Policy
- All formats: 3-year rolling window (1095 days) by default
- Standard + Foundations (FDN): 5-year window for events with FDN cards
- Archive-based: old data moves to mtg_archive.db, never deleted
- Configurable per-format in config.ini (see config.example.ini)

- MTGDecks.net second data source (`scrapers/mtgdecks.py`):
  - Uses `cloudscraper` (Chrome TLS fingerprint) to bypass Cloudflare 403s
  - Parses tournament lists, event detail pages, and deck card lists
  - Card lists from `<textarea id="arena_deck">` (Arena export format — reliable)
  - Filters: MTGO Challenges always included; others need 50+ players or signal keyword
  - `source="mtgdecks"` in events table to separate from mtgtop8 data

## Key Files

```
main.py                         CLI entry point (default: Standard, 1 page, 10 events)
run_gui.py                      GUI entry point — also handles --register-tasks mode
fill_database.py                Standalone full DB builder (first-time use)
fill_database.bat               Double-click launcher for fill_database.py
background_fill.bat             6 AM daily background scrape (all formats)
schedule_background_fill.bat    One-time setup: register 6 AM Task Scheduler task
register_tasks.py               Elevated task registration (called by first-run wizard)
schedule_task.bat               One-time setup: register 5 PM daily task
schedule_scryfall.bat           One-time setup: register weekly Scryfall refresh task
run_daily.bat                   5 PM daily task (Standard latest events + maintenance)
run_scryfall_weekly.bat         Weekly Scryfall refresh (Sunday midnight)
update_claude_code.bat          Self-elevating helper: npm i -g @anthropic-ai/claude-code

scrapers/mtgtop8.py             Core MTGTop8 scraper
scrapers/challenges.py          MTGO Challenge-specific scraper
scrapers/mtgdecks.py            MTGDecks.net scraper (cloudscraper, Cloudflare bypass)
scrapers/backfill.py            Historical backfill (year-by-year, stops at cutoff)
scrapers/scryfall.py            Scryfall local card database + enrichment
scrapers/guides.py              Imports Skill Issue Magic Google Sheet → guides table
scrapers/matchup_scraper.py     Scrapes MTGDecks.net /winrates table → win-rate matrix dict

db/saved_decks.py               saved_decks + saved_sb_plans tables; save/get/delete helpers
db/matches_queries.py           matches table: save_matches / get_matches / get_stored_event_ids / get_match_counts
db/matchup_queries.py           matchup_matrix table: save/get/get_last_updated helpers
db/database.py                  Schema, connections, active + archive DB helpers
db/maintenance.py               Format-aware archive maintenance + orphan cleanup
analysis/deck_analysis.py       Average deck + deck comparison functions
analysis/win_rates.py           Performance tracking, matchup matrix, field optimizer
analysis/archetypes.py          Archetype name normalization + alias table + DB migration
analysis/predictions.py         Self-validation & prediction logging system
analysis/blunders.py            Deck scoring & blunder detection (weighted severity)
analysis/chapin.py              Chapin Principles Evaluation (6 principles, 0-10 scored)
analysis/tournament.py          RCQ equity, standing analysis, ID recommendation
analysis/sideboard_guides.py    Guide parsing, post-board WR model, flip detection
analysis/query.py               CLI query interface (all subcommands)

gui/theme.py                    Single source of truth: colors, fonts, stylesheets, TIMEFRAME_OPTIONS
gui/fonts/Orbitron.ttf          Bundled heading font (personal website match)
gui/main_window.py              8-tab main window, startup wizard check
gui/setup_wizard.py             First-time setup (Scryfall + backfill + event counter)
gui/worker_threads.py           QThread workers: scrape, download, load
gui/widgets/chart_canvas.py     FigureCanvasQTAgg: plot_meta_share/trend/heatmap
gui/widgets/meta_table.py       Meta standings table with click signal
gui/widgets/archetype_detail.py 4 tabs: Average Deck / Recent Lists / Tech Choices / Resources
gui/widgets/deck_export.py      MTGO/MTGA .txt export + decklist.org tournament sheet
gui/tabs/dashboard.py           Table + chart, format/weeks/top-N controls
gui/tabs/deck_analyzer.py       Arena paste → Blunder + Chapin analysis + Legality Checker
gui/tabs/search.py              Card lookup, deck search, head-to-head (with timeframe)
gui/tabs/charts.py              Interactive controls + live chart canvas (TIMEFRAME_OPTIONS)
gui/tabs/predictions.py         Generate/validate/view predictions
gui/tabs/knowledge_base.py      Add/browse bookmarks + guides table, Sync Guides button
gui/tabs/ask_claude.py          Optional streaming chat (hidden until API key set in Settings)
gui/tabs/settings.py            Settings tab: formats, data window, auto-update, AI key
gui/tabs/tournament_prep.py     RCQ Optimizer + Breaker Math sub-tabs (with timeframe)
gui/tabs/my_decks.py            MY DECKS tab: saved decks CRUD, export, open in RCQ Optimizer
gui/tabs/heatmap_tab.py         MATCHUP DATA tab: live scrape / cached / paste, colour-coded grid
gui/tray_icon.py                System tray icon, status dots, right-click menu
gui/first_run_setup.py          First-run UAC dialog + elevated task registration

config.example.ini              Committed config template
config.ini                      Local config (gitignored)
.claude/settings.json           Claude Code project permissions
.vscode/settings.json           VS Code workspace settings (default terminal: cmd)
logs/                           Daily log files (gitignored)
data/                           Local DB + Scryfall bulk files (gitignored)
```

## How to Run

```bash
# First-time database build (double-click or run in terminal)
fill_database.bat

# Launch the GUI
python run_gui.py

# Scrape latest Standard events (manual)
python main.py

# Full historical backfill for a specific format
python -m scrapers.backfill --format pioneer

# Scryfall enrichment
python -m scrapers.scryfall                        # enrich all unenriched cards
python -m scrapers.scryfall --download             # force-refresh bulk file
python -m scrapers.scryfall --stats                # coverage report

# Meta analysis queries
python -m analysis.query meta --format standard
python -m analysis.query meta --range "last 30 days"
python -m analysis.query trend "Izzet Prowess" --weeks 8
python -m analysis.query h2h "Izzet Prowess" "Azorius Control"
python -m analysis.query matrix --top 12
python -m analysis.query field-optimizer --field "Izzet Prowess x4, Mono Green x3"
python -m analysis.query average "Izzet Prowess"

# Card lookups
python -m analysis.query card "Sheoldred, the Apocalypse"
python -m analysis.query card "lightning bolt" --format standard

# Archetype normalization
python -m analysis.archetypes --apply

# Predictions
python -m analysis.query predict --format standard
python -m analysis.query validate-predictions
python -m analysis.query prediction-report

# Deck analysis
python -m analysis.query blunder "Izzet Prowess" --format standard
python -m analysis.query chapin "Izzet Prowess" --format standard

# Sync guides from Skill Issue Magic sheet
python -m scrapers.guides

# Database maintenance
python -m db.maintenance --dry-run
python -m db.maintenance
```

## Automated Tasks
- **6 AM daily**: `background_fill.bat` — Standard + Pioneer + Modern from MTGTop8 + MTGDecks + MTGMelee (3 pages each), Scryfall enrich, normalize (7 steps total)
  - Register: double-click `schedule_background_fill.bat` (self-elevates to Admin)
  - Log: `logs/background_fill.log`
- **5 PM daily**: `run_daily.bat` — Standard latest events + archive maintenance
  - Register: double-click `schedule_task.bat`
  - Log: `logs/YYYY-MM-DD.log`
- **Sunday midnight**: `run_scryfall_weekly.bat` — refresh Scryfall bulk DB
  - Register: double-click `schedule_scryfall.bat`

## Event Types Tracked
- `mtgo_challenge_32` / `mtgo_challenge_64` — MTGO Challenge events
- `mtgo_league` — MTGO League 5-0 results
- `mtgo_preliminary` — MTGO Preliminary events
- `paper` — in-store and regional paper events (RCQs, RCs, Pro Tours)

## Critical Notes

### matplotlib backend
`analysis/charts.py` calls `matplotlib.use("Agg")` at import time.
**Never import `analysis.charts` inside GUI code** — use `gui/widgets/chart_canvas.py`
which draws directly to FigureCanvasQTAgg. `run_gui.py` must call
`matplotlib.use("QtAgg")` before all other imports.

### Default terminal
VS Code default terminal is set to **Command Prompt (cmd)**, not Git Bash.
This prevents path issues with spaces in `E:\vscode ai project\`.

### Database location
`data/mtg_meta.db` — gitignored, never pushed. Each machine builds its own copy.

### TIMEFRAME_OPTIONS and None handling
All timeframe combos read from `theme.TIMEFRAME_OPTIONS`. When the selected
value is `None` (All Time), `_since_dt()` returns `None` and all downstream
query functions skip the date filter via `if since:` guards. The one special
case is `get_archetype_trend()` which uses `weeks` in arithmetic — fixed with:
`window_start = since or (window_end - timedelta(weeks=weeks or 520))`

### Sideboard guide parsing
`analysis/sideboard_guides.py` uses regex patterns against free-form guide
`comment` text. Archetype matching is fuzzy: substring both ways + first-two-words
check handles "Dimir Midrange" matching "Big Dimir Midrange". When `has_guide_data`
is False, `flip_analysis` returns a neutral "No data" verdict rather than a
misleading 0-delta flip. The G2/G3 WR model is calibrated conservatively:
opp_per_card=0.013, my_per_card=0.010, cap=0.13, clamp=[0.18, 0.84].

## User Preferences System (CORE — implement before packaging)

### Overview
Users should only download and maintain data for the formats they actually play.
A Standard-only player should never wait for Pioneer/Modern data.
Preferences are stored in `data/preferences.json` (gitignored) and a
`user_preferences` table in the database.

### preferences.json schema
```json
{
  "formats": ["standard"],
  "date_window": "1year",
  "timezone": "America/Los_Angeles",
  "auto_update": "daily",
  "updated_at": "2026-03-21T12:00:00"
}
```
- `formats`: list from `["standard", "pioneer", "modern", "legacy"]`
- `date_window`: `"2weeks"` | `"1month"` | `"3months"` | `"1year"` | `"3years"` (default)
- `timezone`: IANA timezone string; used for display and scheduled-task timing
- `auto_update`: `"daily"` | `"twice_daily"` | `"weekly"`

### Database: user_preferences table
```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
Scrapers read preferences before running:
- `background_fill.bat` and `fill_database.py` check formats list and skip unselected formats
- `_load_cutoff()` in `backfill.py` respects `date_window` preference

### GUI: Settings Tab (implemented)
`gui/tabs/settings.py` registered in `main_window.py` as the last tab.

Controls:
- **Formats to track**: checkboxes for Standard / Pioneer / Modern / Legacy
- **Data window**: dropdown (2 weeks / 1 month / 3 months / 1 year / 3 years)
- **Timezone**: dropdown or text field (default: auto-detect from Windows)
- **Auto-update frequency**: radio buttons (Daily / Twice daily / Weekly)
- **AI Assistant**: API key input (stored in preferences.json, gitignored)
- **Storage usage**: per-format event/deck counts and estimated DB size
- **Save button**: writes preferences.json + updates user_preferences table

### Setup Wizard: Format Selection as Step 1
Add a format-selection page before the Scryfall download step:
- Page 0: Format selection (checkboxes, default = Standard only)
- Page 1: Scryfall download (as now)
- Page 2: Backfill (only selected formats)

Saves preferences.json immediately when user clicks Next from format page.

### Files to create/modify
```
data/preferences.json           Local preferences (gitignored)
gui/tabs/settings.py            Settings tab (done)
gui/main_window.py              Settings tab wired (done)
gui/setup_wizard.py             Add format-selection page 0 (TODO)
scrapers/backfill.py            Read formats + date_window from preferences (TODO)
fill_database.py                Read formats from preferences before scraping (TODO)
background_fill.bat             Pass format list from preferences (TODO)
db/database.py                  Add user_preferences table to schema (TODO)
```

### Implementation priority
1. `data/preferences.json` load/save helpers (simple JSON, no DB needed)
2. Format selection in setup wizard (prevents wasted first-run scrape time)
3. Wire scrapers to read preferences

---

## Standalone .exe UX Requirements (CORE — do not skip)

These are firm requirements for the PyInstaller packaging phase.
They are partially implemented already — complete before packaging.

### 1. One-time UAC elevation (IMPLEMENTED)
- On first launch, `gui/first_run_setup.py` checks `config.ini [setup] tasks_registered`
- If not set, shows `FirstRunSetupDialog` — explains the three background tasks
- Single "Set Up Automatic Updates" button → PowerShell `Start-Process -Verb RunAs`
  launches `register_tasks.py` (or `.exe --register-tasks`) elevated
- `register_tasks.py` registers all three Task Scheduler tasks and writes the flag
- Flag is checked at every launch via `is_setup_complete()` — wizard never re-shown

### 2. Three auto-registered tasks
| Task name | Script | Time |
|---|---|---|
| MTG-Meta-Analyzer-Background-6AM | background_fill.bat | 6:00 AM daily |
| MTG-Meta-Analyzer-Daily | run_daily.bat | 5:00 PM daily |
| MTG-Meta-Analyzer-Scryfall-Weekly | run_scryfall_weekly.bat | Sunday midnight |

### 3. System tray icon (IMPLEMENTED)
- `gui/tray_icon.py` — `TrayIcon(QSystemTrayIcon)` created in `run_gui.py`
- `app.setQuitOnLastWindowClosed(False)` — app stays alive when window is closed
- `MainWindow.closeEvent` hides window to tray + shows balloon notification (first time only — `balloon_shown` flag in `scrape_state.json`)
- Status dot colors:
  - Green (`#3cb44b`) — data current (STATUS_IDLE)
  - Orange (`#f58231`) — update running (STATUS_RUNNING)
  - Red (`#e6194b`) — last run failed (STATUS_ERROR)
- Icon drawn programmatically: dark rounded square + "M" + colored dot
- Right-click menu: Last updated | Next run | (separator) | Open App | Run Now | (separator) | Exit
- Double-click → show/restore window
- "Last updated" reads `data/scrape_state.json` written by `write_scrape_state()`
- "Next run" calculates next 6 AM or 5 PM from current time
- `MainWindow.set_tray(tray)` wires `_background_scrape` to "Run Now"
- `write_scrape_state()` called in `_on_scrape_done` to persist timestamp

### 4. Key files for tray/UAC system
```
register_tasks.py           Elevated task registration (run as Admin)
gui/first_run_setup.py      First-run dialog + UAC launch helper
gui/tray_icon.py            System tray icon, status dots, right-click menu
run_gui.py                  Wires everything: --register-tasks mode, tray, first-run
gui/main_window.py          set_tray(), closeEvent (hide-to-tray), scrape → tray status
data/scrape_state.json      Persists last_updated timestamp for tray menu
```

### 5. PyInstaller packaging notes (when ready)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" \
  --add-data "gui/fonts;gui/fonts"
```
- The `--register-tasks` arg re-uses the same .exe elevated — no second binary needed
- `data/` stays external; include `fill_database.bat` alongside the .exe
- Test on a clean machine without Python installed
- `anthropic` package should be optional (only needed if Ask Claude is used)

---

## Long-term Roadmap

### v2 Feature — Card Image Preview (NOT a current priority)
Mouseover/hover card image popup inside the GUI.
Implementation approach when ready:
- Download card images on demand from Scryfall image API (`/cards/named?exact=NAME&format=image`)
- Cache to `data/card_images/` directory
- Show as QLabel tooltip or small floating QDialog on hover in deck analyzer / search tabs
- No images embedded in .exe — cache stays external like the DB

### Game Simulation Engine Integration
Integrate with XMage or a custom MTG rules engine for automated simulation
of theoretical decklists against predicted meta fields.
Phase order: meta analysis + deck building features complete first.

### Charts Compare Mode
Overlay multiple archetype trend lines on one chart (multi-select archetype combo in Charts tab).

## Installed Skills (mattpocock/skills)

Three skills are installed at `.claude/skills/` and available in every session.
Invoke them by describing the intent — Claude Code will recognize the trigger.

| Skill | Trigger | What it does |
|---|---|---|
| `triage-issue` | User reports a bug, says "triage", wants to file an issue, or wants to investigate and plan a fix | Explores the codebase to find root cause, then creates a GitHub issue with a TDD-based fix plan |
| `improve-codebase-architecture` | User wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make the codebase more AI-navigable | Explores the codebase for architectural improvement opportunities, focusing on deeper/more testable modules |
| `grill-me` | User wants to stress-test a plan, get grilled on a design decision, or says "grill me" | Interviews the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree |

Installed via: `npx skills@latest add mattpocock/skills/<name> -a claude-code -y`

---

## Always Do at End of Session
1. Update CLAUDE.md — current state, new files, changed endpoints, design decisions
2. Update NEXT_STEPS.md — accurate priorities, completed items marked done
3. Update ROADMAP.md — check off completed items
4. `git add` all changed files, commit with a clear message, `git push`
5. After any scrape: run `--counts` or equivalent to verify output before closing

**These steps are NON-NEGOTIABLE. See the rules section at the top of this file.**
