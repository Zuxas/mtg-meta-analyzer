# Data Engine

## Purpose
Everything that gets data into the system and keeps it clean.
This is the foundation all other systems depend on.

## Responsibilities
- Scraping tournament data from external sources (MTGTop8, MTGDecks, MTGMelee)
- Card enrichment via Scryfall (local bulk file + live API fallback)
- SQLite schema, connections, and archive policy
- Archetype name normalization (pre-normalize, alias table, fuzzy merge)
- Duplicate detection across sources (name similarity + card overlap)
- Scheduled background scrapes and historical backfill
- Import of sideboard guides from external sheets

## Current file ownership (existing code — not moved yet)

| File | Role |
|---|---|
| `scrapers/mtgtop8.py` | Primary tournament scraper |
| `scrapers/mtgdecks.py` | Second source (Cloudflare bypass) |
| `scrapers/mtgmelee_scraper.py` | Real match W/L scraper |
| `scrapers/challenges.py` | MTGO Challenge-specific scraper |
| `scrapers/backfill.py` | Historical year-by-year backfill |
| `scrapers/scryfall.py` | Card enrichment (3-tier: DB → bulk → API) |
| `scrapers/matchup_scraper.py` | External matchup matrix scraper |
| `scrapers/guides.py` | Skill Issue Magic sheet importer |
| `db/database.py` | Schema, connections, archive DB helpers |
| `db/maintenance.py` | Archive policy, orphan cleanup |
| `db/matches_queries.py` | Real match W/L DB layer |
| `db/matchup_queries.py` | Matchup matrix DB layer |
| `analysis/archetypes.py` | Normalization + alias table + merge tools |
| `fill_database.py` | First-run orchestration |

## Planned features (from ROADMAP)
- Memory/resource leak audit and fix
- Cross-source duplicate detection with confidence scoring
- Manual force scrape button with progress display
- Data normalization improvements
- Meta change detection (compare two time periods)
