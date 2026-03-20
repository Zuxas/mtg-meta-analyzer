# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-20

## Immediate priorities (in order)

### 1. Retroactive archetype normalization — DONE
Applied 13 alias mappings to existing DB records (144 "Red Deck Wins" → "Mono Red Aggro", etc.)
- `python -m analysis.archetypes` (dry run)
- `python -m analysis.archetypes --apply` (commit)
- Run `suggest-aliases` periodically to find new duplicates as data grows.

### 2. MTGDecks.net second data source — DONE
`scrapers/mtgdecks.py` complete. Uses `cloudscraper` (Chrome TLS fingerprint) to bypass Cloudflare.
- Card lists from `<textarea id="arena_deck">` (Arena export — most reliable parser)
- `python -m scrapers.mtgdecks --pages 3 --dry-run`
- `python -m scrapers.mtgdecks --pages 3` (live scrape)

### 3. Trend charts — DONE
`analysis/charts.py` complete. Wired into `analysis/query.py` as `chart` subcommand.
- `python -m analysis.query chart meta --format standard --top 8 --weeks 8`
- `python -m analysis.query chart trend "Izzet Prowess"`
- `python -m analysis.query chart heatmap --top 12`

### 4. Self-Validation & Prediction Logging — DONE
`analysis/predictions.py` complete. Stores predictions in `predictions` SQLite table.
- `python -m analysis.query predict --format standard` (log predictions)
- `python -m analysis.query validate-predictions` (validate after target week passes)
- `python -m analysis.query prediction-report` (accuracy by prediction type)
- Prediction types: top_meta (rank 1-5), trending_up, trending_down
- Accuracy tracked per type so signals that work gain credibility over time

### 5. Blunder Detection — DONE
`analysis/blunders.py` complete. Analyzes average archetype deck for construction issues.
- `python -m analysis.query blunder "Izzet Prowess" --format standard`
- Severity tiers: Major (10pt), Moderate (4pt), Minor (1pt)
- Checks: deck size, land count, mana curve, color consistency, interaction, threats, legality
- Construction Quality: Excellent (<5pts), Good (<15), Fair (<35), Poor (35+)

### 6. Chapin Principles Evaluation — DONE
`analysis/chapin.py` complete. Scores decks on 6 principles with weighted average.
- `python -m analysis.query chapin "Izzet Prowess" --format standard`
- Principles: Threats (20%), Answers (20%), Consistency (18%), Velocity (15%), Mana (17%), Clock (10%)
- Each scored 0-10, bar chart display in terminal

---

## Next up: GUI Phase

### PyQt6 GUI
Build a desktop UI wrapping all analysis functions:
- Dashboard: meta standings + trend charts side by side
- Deck Analyzer tab: paste a decklist, run blunder + Chapin analysis
- Search tab: card lookup, deck search, h2h lookup
- Charts tab: embedded matplotlib figures (meta share, trend, heatmap)
- Predictions tab: view logged predictions + accuracy report

### PyInstaller packaging
- `pyinstaller --onefile main.py` with all deps bundled
- Standalone `.exe` that includes SQLite DB path config
- Scryfall bulk file downloaded separately (162 MB, gitignored)

---

## Already complete (do not rebuild)
- MTGTop8 scraper (backfill + daily)
- MTGDecks.net scraper (cloudscraper, Cloudflare bypass)
- SQLite DB (active + archive, `predictions` table)
- Scryfall local card database (162 MB bulk, 3-tier lookup, weekly refresh)
- Average deck calculator + deck comparison diff
- Win rates, meta standings, weekly trend, H2H, matchup matrix
- Field Optimizer (weighted win% against expected field)
- Natural language date range filtering
- Natural language card lookup ("what does sheoldred do")
- Archetype normalization (ALIASES table, DB migration applied)
- Self-validation / prediction logging system
- Blunder Detection (weighted severity scoring)
- Chapin Principles Evaluation (6 principles, 0-10 scored)
- Trend charts (meta share, archetype trend, matchup heatmap)
- Daily + weekly Task Scheduler automation
- .claude/settings.json (read-only queries auto-approved)
- .vscode/settings.json (terminal cwd set to project root)

## Known issues / notes
- Claude Code project ID is registered under `C:\Users\jerme\Downloads` from
  initial session. Always open VS Code from project folder going forward so
  future sessions register under the correct path.
- `data/scryfall_oracle.json` is 162 MB and gitignored. Regenerate with:
  `python -m scrapers.scryfall --download`
- MTGDecks.net scraper depends on `cloudscraper`. If it starts 403ing again,
  try: `pip install --upgrade cloudscraper`
- After new backfill/scrape runs, enrich new cards:
  `python -m scrapers.scryfall`
- Blunder/Chapin scores on average decks show lower card counts (inclusion
  threshold filters partial copies) — this is expected, not a bug.
