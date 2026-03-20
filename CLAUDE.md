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
analysis/                 Meta analysis module (in progress)
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
- Analysis module: top cards, archetype trends, meta share over time
- Average deck calculator per archetype
- Deck comparison: specific list vs archetype average
- Scryfall API integration (card oracle text, set data, legality)
- Patrick Chapin deck evaluation scoring
- MTGDecks.net as a second data source
- Cross-source verification layer
- GUI (PyQt6 + matplotlib/plotly charts)
- PyInstaller standalone .exe packaging

## Always Do at End of Session
Update this CLAUDE.md to reflect any new features completed or design decisions made.
