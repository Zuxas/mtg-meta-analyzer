# CLAUDE.md - MTG Meta Analyzer Project Context

Last updated: 2026-03-20

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

## Current State (as of 2026-03-20)

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
- Scryfall card enrichment (`scrapers/scryfall.py`):
  - 3-tier lookup: SQLite → local bulk JSON → live API (last resort only)
  - Bulk Oracle Cards downloaded to data/scryfall_oracle.json (~162 MB)
  - Loaded into memory once per process; auto-refreshes weekly (Sunday midnight)
  - Enriches card_data table: mana cost, CMC, colors, type, oracle text,
    power/toughness, rarity, set, format legalities
  - `get_card_data()`, `get_cards_data()`, `is_legal()` helpers
  - `search_local(query)`: fuzzy + NL search in local file (no API calls)
  - `get_deck_usage(name, format)`: tournament presence stats
- Archetype name normalization (`analysis/archetypes.py`):
  - ALIASES table maps raw scraper names to canonical names
  - `normalize(name, fuzzy=True)` for analysis queries
  - `suggest_aliases()` scans DB for likely duplicate names
  - `apply_normalization(dry_run, fuzzy)` — retroactive DB migration (13 mappings applied)
  - Run: `python -m analysis.archetypes --apply`
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
- **PyQt6 GUI** — fully wired, personal website theme applied:
  - Entry point: `run_gui.py`
  - Theme: `gui/theme.py` — #3b3c4d bg, #65bcd5 cyan, Orbitron heading font
  - **6 tabs**: Dashboard, Deck Analyzer, Search, Charts, Predictions, Settings
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
  - **Date filter fix**: all panels use SQLite CASE expression (`_DATE_KEY`) to normalize `DD/MM/YY` (MTGTop8) and `YYYY-MM-DD` (MTGDecks) to `YYYYMMDD` for correct filtering/ordering everywhere. Applied in `win_rates.py`, `dashboard.py`, `archetype_detail.py`
  - **`get_meta_standings` fix**: was comparing `e.date >= ?` with YYYY-MM-DD format — all MTGTop8 events were excluded. Fixed with `_DATE_KEY` CASE expression + `_dt_to_db_str` returning `%Y%m%d`
  - **Click handler fix**: Recent Top Finishes archetype cell stores raw name in `UserRole`; color-identity prefix no longer breaks deck detail lookup
  - **Player column**: Recent Top Finishes shows Place / Colors / Archetype / Player / Event / Date (6 columns)
  - **Mana color pips**: `theme.make_pip_widget()` uses `QFrame` + `WA_StyledBackground` + `border-radius: 5px` for proper circles. Official Wizards hex values: W=#F9FAF4, U=#0E68AB, B=#150B00 (displayed as #6a5a50 for visibility), R=#D3202A, G=#00733E
  - **Izzet Prowess fix**: `refresh()` fetches `top=50` from standings so high-frequency archetypes aren't excluded by performance ranking; `_populate_winrate` and `_populate_popularity` then slice to user's selected top N
  - **Desktop shortcut**: `launch_app.bat` (double-click launcher) + `create_shortcut.bat` (creates `MTG Meta Analyzer` shortcut on OneDrive Desktop)

### Primary Format
Standard is the primary focus. Pioneer and Modern actively scraped. Legacy supported but not scheduled.

## Database

### Active DB
`data/mtg_meta.db` — events within the retention window; used by all analysis.

### Archive DB
`data/mtg_archive.db` — data older than retention window; moved here not deleted.
Use `--include-archive` flag (via `get_combined_connection()`) to query across both.

Both DB files are gitignored. After cloning: run `fill_database.bat`

### Current data (as of 2026-03-20)
- Standard: 2,043 events, ~24,289 decks (Nov 2024 – Mar 2026), 99.98% card coverage
- Pioneer: 10 events (MTGTop8 has almost no Pioneer data — use MTGDecks scraper)
- Modern: 0 events from MTGTop8; use `python -m scrapers.mtgdecks --format modern --pages 20`
- Daily 6 AM task now registered — will maintain Standard going forward

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
db/database.py                  Schema, connections, active + archive DB helpers
db/maintenance.py               Format-aware archive maintenance + orphan cleanup
analysis/deck_analysis.py       Average deck + deck comparison functions
analysis/win_rates.py           Performance tracking, matchup matrix, field optimizer
analysis/archetypes.py          Archetype name normalization + alias table + DB migration
analysis/predictions.py         Self-validation & prediction logging system
analysis/blunders.py            Deck scoring & blunder detection (weighted severity)
analysis/chapin.py              Chapin Principles Evaluation (6 principles, 0-10 scored)
analysis/query.py               CLI query interface (all subcommands)

gui/theme.py                    Single source of truth: colors, fonts, stylesheets
gui/fonts/Orbitron.ttf          Bundled heading font (personal website match)
gui/main_window.py              5-tab main window, startup wizard check
gui/setup_wizard.py             First-time setup (Scryfall + backfill + event counter)
gui/worker_threads.py           QThread workers: scrape, download, load
gui/widgets/chart_canvas.py     FigureCanvasQTAgg: plot_meta_share/trend/heatmap
gui/widgets/meta_table.py       Meta standings table with click signal
gui/tabs/dashboard.py           Table + chart, format/weeks/top-N controls
gui/tabs/deck_analyzer.py       Arena paste → Blunder + Chapin analysis
gui/tabs/search.py              Card lookup, deck search, head-to-head
gui/tabs/charts.py              Interactive controls + live chart canvas
gui/tabs/predictions.py         Generate/validate/view predictions
gui/tabs/settings.py            Settings tab: format checkboxes, data window, auto-update, storage info
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

# Database maintenance
python -m db.maintenance --dry-run
python -m db.maintenance
```

## Automated Tasks
- **6 AM daily**: `background_fill.bat` — Standard + Pioneer + Modern from MTGTop8 + MTGDecks, Scryfall enrich, normalize
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
  "updated_at": "2026-03-20T12:00:00"
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

### GUI: Settings Tab (6th tab)
Add `gui/tabs/settings.py` and register in `main_window.py` as tab 6.

Controls:
- **Formats to track**: checkboxes for Standard / Pioneer / Modern / Legacy
  - Changing deselected formats shows warning: "Existing data is kept but no new events will be scraped"
- **Data window**: dropdown (2 weeks / 1 month / 3 months / 1 year / 3 years)
- **Timezone**: dropdown or text field (default: auto-detect from Windows)
- **Auto-update frequency**: radio buttons (Daily / Twice daily / Weekly)
  - Changing frequency re-registers Task Scheduler tasks automatically (no UAC needed after first setup)
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
gui/tabs/settings.py            Settings tab (new)
gui/main_window.py              Add Settings tab
gui/setup_wizard.py             Add format-selection page 0
scrapers/backfill.py            Read formats + date_window from preferences
fill_database.py                Read formats from preferences before scraping
background_fill.bat             Pass format list from preferences (or use fill_database.py)
db/database.py                  Add user_preferences table to schema
```

### Implementation priority
1. `data/preferences.json` load/save helpers (simple JSON, no DB needed)
2. Format selection in setup wizard (prevents wasted first-run scrape time)
3. Settings tab in GUI
4. Wire scrapers to read preferences

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
- `MainWindow.closeEvent` hides window to tray + shows balloon notification
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

### Packaging
```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer"
```
- `data/` stays external (DB + Scryfall bulk file too large to embed)
- Test on a clean machine without Python installed

## Always Do at End of Session
Update this CLAUDE.md to reflect any new features completed or design decisions made.
Create/update NEXT_STEPS.md with the immediate priorities for the next session.
