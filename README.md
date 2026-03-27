# MTG Meta Analyzer

A personal desktop tool for competitive Magic: The Gathering players. Scrapes tournament results from multiple sources, stores years of data locally, and surfaces the meta insights you need to prepare for RCQs, Regional Championships, and Pro Tours.

---

## TL;DR

1. Clone the repo, run `pip install -r requirements.txt`
2. Double-click `fill_database.bat` to build your local database (takes 1–3 hours)
3. Run `python run_gui.py` to launch the app
4. Register the daily tasks once (`schedule_background_fill.bat` as Admin) — after that the DB stays current automatically

**262,641 real match records** across 5 formats. **37,186 decklists** with full card data. All on your local machine.

---

## What It Does

**Data collection — 262k+ real matches across 5 formats**
- Scrapes MTGTop8, MTGDecks.net, and melee.gg across Standard, Pioneer, Modern, Legacy, and Pauper
- **262,641 real match results** from melee.gg (round-by-round W/L, not placement estimates)
- 37,186+ decklists with full card data in local SQLite database
- Daily automated updates via Windows Task Scheduler — no manual scraping needed

| Format | Real Matches | Tournaments | Decklists |
|--------|-------------|-------------|-----------|
| Standard | 108,648 | 250 | 37,186 |
| Modern | 92,420 | 347 | 6,770 |
| Legacy | 25,304 | 86 | 115 |
| Pioneer | 20,095 | 58 | 5,657 |
| Pauper | 16,174 | ~130 | — |

**Meta analysis**
- Meta share and archetype trend charts (weekly or daily granularity)
- Real match win rates from melee.gg data; falls back to placement-based estimates when stale
- Archetype tier badges: S (dominant) / A (strong) / B (solid) / C (declining)
- NxN matchup heatmap: combined real match data (starred) + scraped MTGDecks data fills gaps
- Format event markers on charts (set releases, B&R announcements, rotation dates)
- Cross-source deduplication so the same deck counted on two sites isn't double-counted

**Deck tools**
- Blunder detection: land count, curve, color consistency, interaction, threats, deck size
- Chapin Principles evaluation: six scored principles (Threats, Answers, Consistency, Velocity, Mana, Clock)
- Decklist legality checker for any format
- Average deck calculator — see the consensus 75 for any archetype over any timeframe

**Tournament prep**
- Event Optimizer: RCQ / Regional Championship / PTQ presets with auto player count and round structure
- Binomial top-cut probability, X-loss cutoff, day-2 conversion probability for 2-day events
- Matchup breakdown with G1 and G2/G3 win rates, sideboard flip detection
- Sideboard guide integration: parses Skill Issue Magic guides for ON PLAY / ON DRAW IN/OUT plans
- Breaker Math: live W/L/D tracker, ID calculator, draw equity, pair-down warning
- Printable tournament guide export (HTML) from saved decks

**My Decks**
- Save decks with full 75, archetype, format, notes
- Add sideboard plans per matchup (play/draw IN/OUT, difficulty rating)
- Export to MTGO/MTGA/decklist.org or printable HTML tournament guide
- "Open in Event Optimizer" loads deck directly into tournament analysis

**Other features**
- Weekly meta predictions with accuracy tracking (which signals are most reliable)
- Knowledge Base: bookmark articles and guides; sync Skill Issue Magic Google Sheet
- Ask Claude tab: optional AI assistant with full meta context (requires Anthropic API key)
- System tray with status dot and right-click menu — runs in the background after window close
- All data stays on your machine — nothing is ever pushed to GitHub

---

## System Requirements

- **Python 3.10+** — [python.org](https://python.org)
- **Git** (for cloning)
- Windows 10/11 (Linux/macOS should work but are untested)
- ~500 MB disk space for a full database build

---

## Installation

```bash
git clone https://github.com/Zuxas/mtg-meta-analyzer.git
cd mtg-meta-analyzer
pip install -r requirements.txt
```

---

## Building the Database

**Double-click `fill_database.bat`** (or run `python fill_database.py` in a terminal).

| Step | What happens |
|------|-------------|
| 1 | Initialize database schema |
| 2 | Download Scryfall card database (~75 MB, skipped if fresh) |
| 3 | Backfill MTGTop8 — Standard, Pioneer, Modern (3 years of history) |
| 4 | Scrape MTGDecks — Standard, Pioneer, Modern (recent pages) |
| 5 | Enrich card data via Scryfall lookups |
| 6 | Normalize archetype names |

- Safe to re-run at any time — existing events are skipped automatically
- Press **Ctrl+C** to stop; progress is saved and you can resume later
- Steps 3 and 4 are the slowest — expect 1–3 hours for a full first build
- The GUI is usable as soon as 50+ events are collected

---

## Launching the GUI

```bash
python run_gui.py
```

Or double-click `launch_app.bat`. Run `create_shortcut.bat` once to put a shortcut on your Desktop.

On first launch the app walks you through setup (Scryfall download + initial backfill). After that it opens directly to the Dashboard.

---

## Tabs

| Tab | What's in it |
|-----|-------------|
| **Dashboard** | Meta standings with tier badges, win rates (real or estimated), popularity/win rate charts with weekly/daily toggle + format event markers, per-archetype click-through with exact decklist tab |
| **Deck Analyzer** | Paste an Arena decklist — blunder detection, Chapin Principles scoring, legality checker, export to MTGO/MTGA/decklist.org |
| **My Decks** | Save decks with sideboard plans (play/draw IN/OUT), export printable HTML tournament guides, open in Event Optimizer |
| **Search** | Card lookup, deck search by archetype, head-to-head matchup comparison |
| **Charts** | Meta share trend, archetype trend, compare trends (multi-archetype overlay), matchup heatmap |
| **Predictions** | Generate and validate weekly meta predictions; accuracy report by prediction type |
| **Knowledge Base** | Bookmark articles and guides; sync Skill Issue Magic sideboard guides |
| **Tournament Prep** | Event Optimizer (RCQ/RC/PTQ presets, top-cut equity, matchup breakdown, flip detection) + Breaker Math (live W/L/D + ID calc) |
| **Matchup Data** | NxN heatmap: Real Match Data (262k matches) + MTGDecks Live scrapes + paste CSV/JSON. Overall WR column, source indicators (★ = real) |
| **Ask Claude** | AI assistant with meta context — hidden until API key is set in Settings |
| **Settings** | Format selection, data window, auto-update frequency, AI key |

---

## Supported Formats

| Format | MTGTop8 | MTGDecks.net | melee.gg (real W/L) | Matches |
|--------|---------|--------------|---------------------|---------|
| Standard | Yes | Yes | 108,648 | Full |
| Modern | Yes | Yes | 92,420 | Full |
| Legacy | Yes | Yes | 25,304 | Active |
| Pioneer | Yes | Yes | 20,095 | Full |
| Pauper | — | — | 16,174 | Active |

---

## Data Sources

| Source | What it provides |
|--------|-----------------|
| **MTGTop8** | Placement-ranked decklists for all major formats going back years |
| **MTGDecks.net** | Second source for decklists + NxN win-rate matrix (256 archetypes) |
| **melee.gg** | Round-by-round match results — real W/L, not estimated from placement |
| **Scryfall** | Card data: mana cost, types, legalities, oracle text |
| **Skill Issue Magic** | Sideboard guides imported from a community Google Sheet |

---

## Project Structure

```
fill_database.bat       Double-click to build the database (first time)
fill_database.py        Database builder script
run_gui.py              Launch the desktop GUI
launch_app.bat          Double-click launcher shortcut
background_fill.bat     6 AM daily background scrape (all formats, 7 steps)
run_daily.bat           5 PM daily Standard update

scrapers/               Data scrapers
  mtgtop8.py            MTGTop8 scraper
  mtgdecks.py           MTGDecks.net scraper (Cloudflare bypass)
  mtgmelee_scraper.py   melee.gg real match W/L scraper
  scryfall.py           Scryfall card data (bulk + enrichment)
  matchup_scraper.py    MTGDecks.net win-rate matrix scraper
  guides.py             Skill Issue Magic Google Sheet importer

analysis/               Analysis modules
  win_rates.py          Meta standings, win rates, matchup matrix
  archetypes.py         Archetype name normalization (3-layer system)
  deck_analysis.py      Average deck calculator
  blunders.py           Blunder detection (Major/Moderate/Minor)
  chapin.py             Chapin Principles evaluation
  sideboard_guides.py   Guide parsing + post-board WR model
  tournament.py         RCQ equity, breaker math
  predictions.py        Weekly prediction generation + validation

db/                     Database layer
  database.py           Schema, connections, active + archive DB
  matches_queries.py    Real match W/L storage and retrieval
  matchup_queries.py    Matchup matrix storage
  saved_decks.py        User-saved decks and sideboard plans
  maintenance.py        Archive rotation + orphan cleanup

gui/                    PyQt6 desktop application
  theme.py              Design system (colors, fonts, TIMEFRAME_OPTIONS)
  main_window.py        10-tab main window
  tabs/                 One file per tab
  widgets/              Reusable widgets (chart canvas, meta table, deck export)
  tray_icon.py          System tray with status dot and right-click menu

data/                   Local databases and exports (not in git)
logs/                   Daily scrape logs (not in git)
```

---

## Configuration

Copy `config.example.ini` to `config.ini` to customize:

- **Database path** — point to a different drive if needed
- **Retention windows** — per-format, in days (default 1095 = 3 years)

---

## Database Notes

Two local SQLite files are created in `data/` — both are excluded from git:

- `data/mtg_meta.db` — active dataset (within retention window)
- `data/mtg_archive.db` — historical data rotated out of the active window

Use `--include-archive` flags on CLI commands to query across both.

**Databases are never pushed to GitHub.** Each machine builds its own local copy by running `fill_database.bat`.

---

## Scheduling Automatic Updates

Three Windows Task Scheduler tasks keep the database current. The first-run wizard registers them automatically. To register manually:

| Task | Time | Script | How to register |
|------|------|--------|-----------------|
| Background fill (all formats) | 6:00 AM daily | `background_fill.bat` | Right-click `schedule_background_fill.bat` → Run as Admin |
| Daily Standard update | 5:00 PM daily | `run_daily.bat` | Right-click `schedule_task.bat` → Run as Admin |
| Scryfall card data refresh | Sunday midnight | `run_scryfall_weekly.bat` | Right-click `schedule_scryfall.bat` → Run as Admin |

All output is logged to `logs/background_fill.log` and `logs/YYYY-MM-DD.log`.

The background fill runs 7 steps: MTGTop8 (Standard / Pioneer / Modern), MTGDecks (Standard / Pioneer / Modern), MTGMelee real match data (Standard / Pioneer / Modern / Legacy / Pauper), Scryfall enrichment, archetype normalization.

---

## Manual Scrape Commands

```bash
# Quick update (recent Standard events from MTGTop8)
python main.py

# Full historical backfill for a format
python -m scrapers.backfill --format pioneer

# Scryfall card data
python -m scrapers.scryfall                # enrich new cards
python -m scrapers.scryfall --download     # force-refresh bulk file

# Real match W/L from melee.gg
python -m scrapers.mtgmelee_scraper --format standard --pages 5
python -m scrapers.mtgmelee_scraper --counts   # show totals

# Matchup win-rate matrix from MTGDecks
python -m scrapers.matchup_scraper --format standard --save

# Archetype normalization
python -m analysis.archetypes --apply
```

---

## Updating

```bash
git pull
pip install -r requirements.txt   # pick up any new dependencies
```

The GUI runs a background update automatically on startup. The database schema migrates automatically when new tables are added.

---

## Known Limitations

- **MTGTop8 decklist data**: Scraper had a Unicode crash on non-ASCII player names that went undetected for months (fixed 2026-03-26). Data will recover as daily scrapes run. In the meantime, the dashboard uses real match data from melee.gg as a fallback.
- **Pioneer/Modern heatmap coverage**: Fewer tournaments on melee.gg than Standard, so the real match data heatmap is sparser. MTGDecks Live scrapes fill the gaps.
- **Sideboard guides**: Require manually syncing the Skill Issue Magic Google Sheet via the Knowledge Base tab. Guides are community-contributed and may not cover all matchups.
- **Ask Claude tab**: Requires an Anthropic API key set in Settings. Uses Claude claude-opus-4-6 with adaptive thinking.
- **Pauper/Legacy decklists**: melee.gg has real match W/L data for these formats, but MTGTop8/MTGDecks decklist scraping is limited. Heatmap and match data work; deck analysis features need more data.
- **Windows only**: Scheduled tasks use Windows Task Scheduler. The GUI itself should work on macOS/Linux but automated updates are not set up for those platforms.

---

## Acknowledgements

- **MTGTop8** and **MTGDecks.net** for tournament data
- **melee.gg** for real match results
- **Scryfall** for card data API
- **Skill Issue Magic** for the sideboard guide database
- Built with Python 3.13, PyQt6, matplotlib, SQLite, cloudscraper
