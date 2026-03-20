# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-20

## Immediate priorities (in order)

### 1. Retroactive archetype normalization
Apply the ALIASES table in `analysis/archetypes.py` to existing DB records.
One-time UPDATE pass: for each known alias, update `decks.archetype` to the
canonical name. Then run `suggest-aliases` to find any remaining duplicates.

```bash
# After writing the migration script:
python -m analysis.query suggest-aliases --threshold 80
```

The normalization module is built; just needs the DB migration script.
Suggested approach: add `python -m analysis.archetypes --apply` CLI that
does the UPDATE pass with a `--dry-run` option.

### 2. MTGDecks.net second data source
Build `scrapers/mtgdecks.py` mirroring the structure of `scrapers/mtgtop8.py`.
MTGDecks.net has a different HTML structure but similar event/deck data.
Cross-reference events by date + format to detect duplicates before inserting.
Adds a `source` field already present in the `events` table.

### 3. Trend charts
matplotlib is already installed. Add a `chart` subcommand (or `--chart` flag)
to `analysis/query.py` that renders:
- Meta share over time (line chart, top N archetypes)
- Win rate trend for one archetype (with confidence bands)
- Matchup heatmap (from matrix data)

For CLI: save as PNG to `data/charts/`. For future GUI: return figure objects.

### 4. Deck Scoring & Blunder Detection
New module: `analysis/blunders.py`
Requires Scryfall enrichment (done) for CMC, type line, colors.
Detection rules:
  - Mana curve: flag if avg CMC > threshold for the format's aggro/midrange norms
  - Color consistency: flag if color_identity doesn't match mana base
  - Land count: flag if land count outside 18-26 for non-combo decks
  - Win condition: flag if no cards with "wins the game" or low threat density
  - Interaction: flag if <8 interactive spells (removal + counterspells)
  - Format legality: flag any card with `is_legal(name, format) == False`
Feeds into Chapin Principles Evaluation (next after blunders).

### 5. Chapin Principles Evaluation
New module: `analysis/chapin.py`
Maps blunder categories to Chapin's framework:
  threat density, consistency, redundancy, answers, clock, mana efficiency
Input: decklist + format. Output: per-principle score + overall rating.

---

## Already complete (do not rebuild)
- MTGTop8 scraper (backfill + daily)
- SQLite DB (active + archive)
- Scryfall local card database (162 MB bulk, 3-tier lookup, weekly refresh)
- Average deck calculator + deck comparison diff
- Win rates, meta standings, weekly trend, H2H, matchup matrix
- Field Optimizer (weighted win% against expected field)
- Natural language date range filtering
- Natural language card lookup ("what does sheoldred do")
- Archetype normalization module (needs DB migration pass)
- Daily + weekly Task Scheduler automation
- .claude/settings.json (read-only queries auto-approved)
- .vscode/settings.json (terminal cwd set to project root)

## Known issues / notes
- Claude Code project ID is registered under `C:\Users\jerme\Downloads` from
  initial session. Always open VS Code from project folder going forward so
  future sessions register under the correct path.
- Archetype normalization is built but NOT yet applied to existing DB data.
  Running analysis queries now may show "UR Prowess" and "Izzet Prowess" as
  separate archetypes. Fix: run the retroactive migration (priority #1 above).
- `data/scryfall_oracle.json` is 162 MB and gitignored. Regenerate with:
  `python -m scrapers.scryfall --download`
