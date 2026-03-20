# MTG Meta Analyzer

A tool for scraping and analyzing competitive Magic: The Gathering tournament data.
Built for Pioneer, Standard, Modern, and Legacy (60-card formats).

## Setup

**Requirements:** Python 3.10+, Git

```bash
git clone https://github.com/Zuxas/mtg-meta-analyzer.git
cd mtg-meta-analyzer
pip install -r requirements.txt
python main.py --init-only
```

`--init-only` creates both the active database and the archive database locally.
Neither DB is tracked by git — they stay on your machine.

## Usage

```bash
# Scrape Standard (default), 1 page, up to 10 events
python main.py

# Scrape a specific format
python main.py --format modern
python main.py --format standard --pages 2 --max-events 20

# Scrape MTGO Challenges only
python -m scrapers.challenges --format pioneer
python -m scrapers.challenges --format pioneer --list-only   # preview only

# Run database maintenance manually
python -m db.maintenance
python -m db.maintenance --dry-run
```

## Configuration

Copy `config.ini` (created on first run) to change:
- **Database path** — store the DB on a different drive
- **Archive path** — where out-of-window data is moved (not deleted)
- **Retention windows** — per-format, in days (default 1095 = 3 years)
- **Foundations extended window** — Standard events with Foundations cards kept 5 years

## Database

Two local SQLite files (both excluded from git):
- `data/mtg_meta.db` — active dataset, within the retention window
- `data/mtg_archive.db` — historical data moved out of the active window

Analysis queries run against the active DB by default.
Pass `--include-archive` (once analysis module is built) to query across both.

## Project Structure

```
scrapers/       scraper scripts (MTGTop8, MTGO Challenges)
db/             database schema, connection helpers, maintenance
analysis/       meta analysis and card combination logic (in progress)
data/           local SQLite databases and log files (not in git)
exports/        output files for review
```
