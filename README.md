# MTG Meta Analyzer

A desktop tool for scraping, storing, and analyzing competitive Magic: The Gathering tournament data. Tracks meta share, win rates, archetype trends, and matchup heatmaps across Standard, Pioneer, and Modern.

---

## What It Does

- **Scrapes** tournament results from MTGTop8 and MTGDecks across multiple formats
- **Stores** up to 3 years of event and decklist data in a local SQLite database
- **Analyzes** meta share, archetype trends, estimated win rates, and matchup data
- **GUI** — interactive PyQt6 desktop application with embedded live charts
- **Deck Analyzer** — paste any Arena decklist and get blunder detection + Chapin Principles evaluation
- **Predictions** — generates and validates weekly archetype rank/share predictions
- **Search** — card lookup, deck search by archetype, and head-to-head matchup comparison
- All data stays on your machine — no database is ever pushed to GitHub

---

## System Requirements

- **Python 3.10 or newer** — [python.org](https://python.org)
- **Git** (for cloning)
- Windows 10/11 (Linux/macOS should work but are untested)
- ~500 MB disk space for the full database

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

This does everything in one shot:

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
- Steps 3 and 4 are the slowest (network scraping) — expect 1-3 hours for a full build
- The GUI is usable as soon as 50+ events are collected

---

## Launching the GUI

```bash
python run_gui.py
```

The GUI opens with five tabs:

| Tab | Description |
|-----|-------------|
| **Dashboard** | Meta standings table + live interactive chart (meta share or archetype trend) |
| **Deck Analyzer** | Paste an Arena decklist — blunder detection and Chapin Principles scoring |
| **Search** | Card lookup, deck search by archetype, head-to-head matchup data |
| **Charts** | Generate meta share, archetype trend, and matchup heatmap charts |
| **Predictions** | Generate and validate weekly meta predictions |

---

## Supported Formats

| Format | MTGTop8 | MTGDecks |
|--------|---------|----------|
| Standard | Yes | Yes |
| Pioneer | Yes | Yes |
| Modern | Yes | Yes |
| Legacy | Backfill supported | Yes |

---

## Project Structure

```
fill_database.bat   Double-click to build the database
fill_database.py    Database builder script (called by the .bat)
run_gui.py          Launch the desktop GUI

scrapers/           Data scrapers (MTGTop8, MTGDecks, Scryfall)
analysis/           Meta analysis, blunder detection, predictions
db/                 Database schema, connection helpers, maintenance
gui/                PyQt6 desktop GUI (tabs, widgets, theme)
  tabs/             Dashboard, Deck Analyzer, Search, Charts, Predictions
  widgets/          Reusable widgets (chart canvas, meta table)
  fonts/            Bundled Orbitron font
data/               Local SQLite databases and exports (not in git)
logs/               Daily scrape logs (not in git)
```

---

## Configuration

Copy `config.example.ini` to `config.ini` to customize:

- **Database path** — store the DB on a different drive
- **Retention windows** — per-format, in days (default 1095 = 3 years)

---

## Database Notes

Two local SQLite files are created in `data/` — both are excluded from git:

- `data/mtg_meta.db` — active dataset (within retention window)
- `data/mtg_archive.db` — historical data rotated out of the active window

**Databases are never pushed to GitHub.** Each machine builds its own local copy by running `fill_database.bat`.

---

## Updating

To pull new tournament data after the initial build:

```bash
# Quick update (recent events only)
python main.py

# Or just re-run the full builder (existing events are skipped)
fill_database.bat
```

The GUI also runs a background update automatically on startup.
