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
- User has limited coding experience; AI assistants are primary dev support

## Current State (as of 2026-03-20)

### Working
- MTGTop8 scraper pulls events, decklists (main + sideboard), player names
- MTGO Challenge-specific scraper (`scrapers/challenges.py`)
- Historical backfill scraper (`scrapers/backfill.py`) — pages backwards
  year-by-year using MTGTop8 year-specific meta filters
- SQLite database storing events, decks, cards, deck_cards
- Format-aware archive-based retention policy (not deletion)
- Daily automated scraper via Windows Task Scheduler (`run_daily.bat`)
- Average deck calculator and deck comparison (`analysis/deck_analysis.py`)
- CLI query tool (`analysis/query.py`) with: average, compare, search,
  top-cards, last-challenge, meta, trend, h2h, matchups, matrix,
  field-optimizer, card, enrich-stats, suggest-aliases, normalize subcommands
- Win rate / performance tracking (`analysis/win_rates.py`):
  - Placement-based estimated match W/L per archetype
  - Meta standings, weekly trend, head-to-head, full matchup breakdown
  - NxN matchup matrix; Field Optimizer (weighted win% vs expected field)
  - Natural language date range filtering ("last 30 days", "feb2-mar9")
- Scryfall card enrichment (`scrapers/scryfall.py`):
  - Bulk Oracle Cards download (~75 MB, refreshed weekly)
  - Enriches `card_data` table: mana cost, CMC, colors, type, oracle text,
    power/toughness, rarity, set, format legalities
  - Fuzzy API fallback for cards not found in bulk
  - `get_card_data()`, `get_cards_data()`, `is_legal()` query helpers
- Archetype name normalization (`analysis/archetypes.py`):
  - ALIASES table maps raw scraper names to canonical names
  - `normalize(name, fuzzy=True)` for analysis queries
  - `suggest_aliases()` scans DB for likely duplicate names
  - `thefuzz` fuzzy matching (threshold-gated, opt-in for safety)

### Primary Format
Standard is the primary focus format. All scraper defaults are Standard.
Pioneer, Modern, Legacy are supported but secondary.

## Database

### Active DB
`data/mtg_meta.db` — events within the retention window; used by all analysis.

### Archive DB
`data/mtg_archive.db` — data older than retention window; moved here not deleted.
Use `--include-archive` flag (via `get_combined_connection()`) to query across both.

Both DB files are gitignored and never pushed to GitHub.
After cloning: run `python main.py --init-only` to create fresh local DBs.

## Retention Policy
- All formats: 3-year rolling window (1095 days) by default
- Standard + Foundations set (FDN): 5-year extended window (1825 days)
  for events that contain Foundations cards
- Retention is archive-based: old data moves to `mtg_archive.db`, never deleted
- Maintenance runs automatically after every scraper session
- Configurable per-format in `config.ini` (gitignored; use `config.example.ini`)

## Key Files

```
main.py                   CLI entry point (default: Standard, 1 page, 10 events)
scrapers/mtgtop8.py       Core MTGTop8 scraper
scrapers/challenges.py    MTGO Challenge-specific scraper
scrapers/backfill.py      Historical backfill (year-by-year, stops at cutoff)
db/database.py            Schema, connections, active + archive DB helpers
db/maintenance.py         Format-aware archive maintenance + orphan cleanup
analysis/deck_analysis.py Average deck + deck comparison functions
analysis/win_rates.py     Performance tracking, matchup matrix, field optimizer
analysis/archetypes.py    Archetype name normalization + alias table
analysis/query.py         CLI query interface (all subcommands)
scrapers/scryfall.py      Scryfall bulk download + card enrichment
config.example.ini        Committed config template
config.ini                Local config (gitignored)
run_daily.bat             Daily scraper script called by Task Scheduler
schedule_task.bat         One-time setup script to register the Task Scheduler job
logs/                     Daily log files (gitignored)
data/                     Local DB files (gitignored)
```

## How to Run

```bash
# Scrape latest Standard events
python main.py

# Full backfill (Standard, back to 3-year cutoff)
python -m scrapers.backfill

# Backfill with custom start date
python -m scrapers.backfill --since 2025-01-01

# MTGO Challenges only
python -m scrapers.challenges --format standard

# Database maintenance (runs automatically, but can run manually)
python -m db.maintenance --dry-run
python -m db.maintenance

# Scryfall enrichment (run once after backfill, then weekly auto-refresh)
python -m scrapers.scryfall                        # enrich all unenriched cards
python -m scrapers.scryfall --download             # force-refresh bulk file
python -m scrapers.scryfall --card "Opt"           # look up one card
python -m analysis.query enrich-stats             # coverage report

# Archetype normalization
python -m analysis.query normalize "UR Prowess"   # -> "Izzet Prowess"
python -m analysis.query suggest-aliases           # find likely duplicates

# Meta analysis queries
python -m analysis.query meta --format standard
python -m analysis.query meta --range "last 30 days"
python -m analysis.query trend "Izzet Prowess" --weeks 8
python -m analysis.query trend "Izzet Prowess" --range "feb2-mar9"
python -m analysis.query h2h "Izzet Prowess" "Azorius Control"
python -m analysis.query matchups "Izzet Prowess"
python -m analysis.query matrix --top 12
python -m analysis.query field-optimizer --field "Izzet Prowess x4, Mono Green x3, Azorius Control x2"
python -m analysis.query average "Izzet Prowess"
python -m analysis.query search "Prowess"
```

## Automated Daily Scraper
- Runs every day at 5:00 PM PST via Windows Task Scheduler
- Setup: run `schedule_task.bat` once as Administrator
- Logs output to `logs/YYYY-MM-DD.log`

## Event Types Tracked
Events are tagged by `event_type` in the DB:
- `mtgo_challenge_32` / `mtgo_challenge_64` — MTGO Challenge events
- `mtgo_league` — MTGO League results
- `mtgo_preliminary` — MTGO Preliminary events
- `paper` — in-store and regional paper events (RCQs, RCs, Pro Tours, etc.)

## Architecture Notes (for future GUI)
Backend is cleanly separated from CLI layer:
- All scraper functions return data (no UI coupling)
- `analysis/` module will expose pure functions for GUI to call
- When ready: wrap with PyQt6 or Tkinter; package with PyInstaller
- `get_combined_connection(include_archive=True)` enables archive queries
  without duplicating any query logic

## What's Next (not yet built)

### Near-term
- Run `python -m scrapers.scryfall` to enrich all cards with Scryfall data
- MTGDecks.net as a second data source + cross-source verification
- Trend charts in CLI output (matplotlib / plotly — deps already installed)
- Apply archetype normalization retroactively to existing DB records
  (one-time UPDATE pass using `analysis/archetypes.py` ALIASES table)

### Deck Scoring & Blunder Detection
Inspired by the mage-bench blunder index concept. Score theoretical decklists
for construction errors using weighted severity tiers:

- **Minor** (low weight): suboptimal card choices, off-curve slots, marginal
  sideboard picks
- **Moderate** (medium weight): mana base inconsistencies, color screw risk,
  curve gaps, over-reliance on a single threat type
- **Major** (high weight): missing win conditions, no interaction, poor matchup
  coverage against the expected meta field

Each issue is flagged with a severity level, a description, and a suggested
fix. The deck receives an overall Blunder Score (lower = cleaner build) and a
Construction Quality rating.

This module feeds directly into the **Chapin Principles Evaluation** layer,
which maps blunders to Patrick Chapin's framework for deck construction
quality (threat density, consistency, redundancy, answers, clock). The two
systems share the same input (decklist + meta context) and output a combined
evaluation report.

### GUI Phase
- PyQt6 GUI wrapping all analysis/query functions
- matplotlib/plotly charts for trend lines, meta share, matchup heatmaps
- PyInstaller standalone .exe packaging

### Self-Validation & Prediction Learning System
Track and improve prediction accuracy over time:

- **Prediction logger**: every meta prediction (rising archetype, expected
  field shift, matchup call) is stored in the DB with a timestamp and
  the signal(s) that drove it.
- **Validation runner**: after N weeks, checks each prediction against what
  actually happened in subsequent tournament results. Marks correct/wrong.
- **Confidence scoring**: per prediction type (meta share rise, matchup call,
  win rate trend) — tracks historical accuracy rate.
- **Automatic weight adjustment**: signals that have historically been accurate
  (e.g. MTGO 5-0 lists) get higher weight in future predictions. Signals
  with poor track records (e.g. Regional Championship data for near-term
  meta calls) get lower weight. Weights stored in DB, updated each validation run.
- **Prediction history log**: queryable via CLI (`python -m analysis.query predictions`).

This enables the tool to get measurably better over time rather than using
static weights. Implementation requires: prediction schema in DB, a
`analysis/predictions.py` module, and a validation cron job.

### Long-term Roadmap

#### Game Simulation Engine Integration
Eventually integrate with a simulation engine (e.g. XMage or a custom MTG
rules engine) to allow theoretical decklists to be tested against predicted
meta fields through automated simulation. This would give predicted win
percentages for untested lists before physical testing — a "paper backtest"
for deck building.

Phase order: meta analysis + deck building features complete first, then
simulation layer built on top as a validation/prediction tool.

This is a long-term future phase requiring significant ML/automation work.

## Always Do at End of Session
Update this CLAUDE.md to reflect any new features completed or design decisions made.
