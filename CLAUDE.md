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
- Shell: Git Bash (use Unix path syntax in scripts)
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
- Daily automated scraper via Windows Task Scheduler (`run_daily.bat`)
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
- Claude Code project permissions (`.claude/settings.json`)
  - Read-only query commands auto-approved (no confirmation prompt)

### Primary Format
Standard is the primary focus. Pioneer, Modern, Legacy supported but secondary.

## Database

### Active DB
`data/mtg_meta.db` — events within the retention window; used by all analysis.

### Archive DB
`data/mtg_archive.db` — data older than retention window; moved here not deleted.
Use `--include-archive` flag (via `get_combined_connection()`) to query across both.

Both DB files are gitignored. After cloning: `python main.py --init-only`

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
main.py                     CLI entry point (default: Standard, 1 page, 10 events)
scrapers/mtgtop8.py         Core MTGTop8 scraper
scrapers/challenges.py      MTGO Challenge-specific scraper
scrapers/mtgdecks.py        MTGDecks.net scraper (cloudscraper, Cloudflare bypass)
scrapers/backfill.py        Historical backfill (year-by-year, stops at cutoff)
scrapers/scryfall.py        Scryfall local card database + enrichment
db/database.py              Schema, connections, active + archive DB helpers
db/maintenance.py           Format-aware archive maintenance + orphan cleanup
analysis/deck_analysis.py   Average deck + deck comparison functions
analysis/win_rates.py       Performance tracking, matchup matrix, field optimizer
analysis/archetypes.py      Archetype name normalization + alias table + DB migration
analysis/predictions.py     Self-validation & prediction logging system
analysis/blunders.py        Deck scoring & blunder detection (weighted severity)
analysis/chapin.py          Chapin Principles Evaluation (6 principles, 0-10 scored)
analysis/query.py           CLI query interface (all subcommands)
config.example.ini          Committed config template
config.ini                  Local config (gitignored)
run_daily.bat               Daily scraper (Task Scheduler, 5 PM PST)
run_scryfall_weekly.bat     Weekly Scryfall refresh (Task Scheduler, Sunday midnight)
schedule_task.bat           One-time setup: register daily scraper task
schedule_scryfall.bat       One-time setup: register weekly Scryfall refresh task
.claude/settings.json       Claude Code project permissions
.vscode/settings.json       VS Code workspace settings
logs/                       Daily log files (gitignored)
data/                       Local DB + Scryfall bulk files (gitignored)
```

## How to Run

```bash
# Scrape latest Standard events
python main.py

# Full backfill (Standard, back to 3-year cutoff)
python -m scrapers.backfill

# Scryfall enrichment (run once after backfill, auto-refreshes weekly)
python -m scrapers.scryfall                        # enrich all unenriched cards
python -m scrapers.scryfall --download             # force-refresh bulk file
python -m scrapers.scryfall --stats                # coverage report
python -m scrapers.scryfall --card "Opt"           # look up one card

# Meta analysis queries (all run without confirmation prompt)
python -m analysis.query meta --format standard
python -m analysis.query meta --range "last 30 days"
python -m analysis.query trend "Izzet Prowess" --weeks 8
python -m analysis.query trend "Izzet Prowess" --range "feb2-mar9"
python -m analysis.query h2h "Izzet Prowess" "Azorius Control"
python -m analysis.query matchups "Izzet Prowess" --range "last 60 days"
python -m analysis.query matrix --top 12
python -m analysis.query field-optimizer --field "Izzet Prowess x4, Mono Green x3, Azorius Control x2"
python -m analysis.query average "Izzet Prowess"
python -m analysis.query search "Prowess"

# Card lookups (query local Scryfall database — no API calls)
python -m analysis.query card "Sheoldred, the Apocalypse"
python -m analysis.query card "what does sheoldred do"
python -m analysis.query card "lightning bolt" --format standard
python -m analysis.query card "sheoldred" --search    # show all fuzzy matches
python -m analysis.query enrich-stats

# Archetype normalization
python -m analysis.query normalize "UR Prowess"       # -> "Izzet Prowess"
python -m analysis.query suggest-aliases               # find likely duplicates
python -m analysis.archetypes                          # dry run migration
python -m analysis.archetypes --apply                  # commit alias migration to DB

# Self-validation & predictions
python -m analysis.query predict --format standard     # log predictions for next week
python -m analysis.query validate-predictions          # validate pending predictions
python -m analysis.query prediction-report             # accuracy report by type

# Deck analysis: Blunder Detection + Chapin Principles
python -m analysis.query blunder "Izzet Prowess" --format standard
python -m analysis.query chapin "Izzet Prowess" --format standard

# MTGDecks.net second source
python -m scrapers.mtgdecks --pages 3 --dry-run
python -m scrapers.mtgdecks --pages 3

# Database maintenance
python -m db.maintenance --dry-run
python -m db.maintenance
```

## Automated Tasks
- Daily at 5:00 PM PST: `run_daily.bat` (scrape Standard + archive maintenance)
- Weekly Sunday midnight: `run_scryfall_weekly.bat` (refresh Scryfall bulk DB)
- Setup: run `schedule_task.bat` and `schedule_scryfall.bat` once as Administrator

## Event Types Tracked
- `mtgo_challenge_32` / `mtgo_challenge_64` — MTGO Challenge events
- `mtgo_league` — MTGO League 5-0 results
- `mtgo_preliminary` — MTGO Preliminary events
- `paper` — in-store and regional paper events (RCQs, RCs, Pro Tours)

## Architecture Notes (for future GUI)
Backend is cleanly separated from CLI layer:
- All analysis functions return data dicts (no print statements in library code)
- `analysis/` module exposes pure functions for GUI to call directly
- `scrapers/scryfall.py` query helpers (`get_card_data`, `is_legal`) are the
  foundation for blunder detection and Chapin evaluation modules
- When ready: wrap with PyQt6; package with PyInstaller
- Installed: pandas, matplotlib, plotly, thefuzz, python-Levenshtein

## What's Next

### Immediate Priorities (see NEXT_STEPS.md)
PyQt6 GUI is in progress (Phase 3). CLI backend is complete — do not rebuild it.

### GUI Phase (in progress as of 2026-03-20)
- Entry point: `run_gui.py` — sets `matplotlib.use("QtAgg")` BEFORE any imports
- Main window: `gui/main_window.py` — dark Fusion palette, 5-tab QTabWidget
- First-time setup wizard (`gui/setup_wizard.py`): auto-detects missing/empty DB,
  downloads Scryfall bulk file, runs backfill scraper, shows live event counter,
  unlocks analysis features at 50 events
- Dashboard tab: meta standings table (click row → trend chart updates)
- Deck Analyzer tab: paste Arena export → Blunder Detection + Chapin principles
- Search tab: card lookup (Scryfall local), deck search (SQL), head-to-head
- Charts tab: fully interactive live charts (Meta Share / Trend / Heatmap),
  controls panel on left, FigureCanvasQTAgg on right, Save PNG button
- Predictions tab: generate/validate/view prediction accuracy

**IMPORTANT matplotlib note**: `analysis/charts.py` calls `matplotlib.use("Agg")`
at import time. Never import `analysis.charts` inside GUI code — use
`gui/widgets/chart_canvas.py` which draws directly to FigureCanvasQTAgg.

### Long-term Roadmap

#### v2 Feature — Card Image Preview (NOT a current priority)
Mouseover/hover card image popup inside the GUI.
Implementation approach when ready:
- Download card images on demand from Scryfall image API (`/cards/named?exact=NAME&format=image`)
- Cache to `data/card_images/` directory
- Show as QLabel tooltip or small floating QDialog on hover in deck analyzer / search tabs
- No images embedded in .exe — cache stays external like the DB

#### Game Simulation Engine Integration
Integrate with XMage or a custom MTG rules engine for automated simulation
of theoretical decklists against predicted meta fields. Gives predicted win
percentages before physical testing — a "paper backtest" for deck building.
Phase order: meta analysis + deck building features complete first.

## Always Do at End of Session
Update this CLAUDE.md to reflect any new features completed or design decisions made.
Create/update NEXT_STEPS.md with the immediate priorities for the next session.
