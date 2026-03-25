# SYSTEM_MAP.md — Existing files mapped to system ownership

> This is a planning document. No files have been moved yet.
> Use this as the migration guide when each system is ready to absorb its modules.
> "Owner" = which core/ system this file logically belongs to.

---

## scrapers/

| File | Owner | Notes |
|---|---|---|
| `scrapers/mtgtop8.py` | Data Engine | Primary scraper |
| `scrapers/mtgdecks.py` | Data Engine | Second source, Cloudflare bypass |
| `scrapers/mtgmelee_scraper.py` | Data Engine | Real match W/L; needs fix |
| `scrapers/challenges.py` | Data Engine | MTGO Challenge-specific scraper |
| `scrapers/backfill.py` | Data Engine | Historical year-by-year backfill |
| `scrapers/scryfall.py` | Data Engine | Card enrichment (3-tier lookup) |
| `scrapers/matchup_scraper.py` | Data Engine | External matchup matrix (MTGDecks) |
| `scrapers/guides.py` | Data Engine | Skill Issue Magic sheet importer |

## db/

| File | Owner | Notes |
|---|---|---|
| `db/database.py` | Data Engine | Schema, connections, archive helpers |
| `db/maintenance.py` | Data Engine | Archive policy, orphan cleanup |
| `db/matches_queries.py` | Data Engine | Real match W/L DB layer |
| `db/matchup_queries.py` | Data Engine | Matchup matrix DB layer |

## analysis/

| File | Owner | Notes |
|---|---|---|
| `analysis/archetypes.py` | Data Engine | Normalization, alias table, dedup |
| `analysis/query.py` | Query Engine | CLI entry point (all subcommands) |
| `analysis/win_rates.py` | Query Engine | Meta standings, matchup matrix, field optimizer |
| `analysis/deck_analysis.py` | Query Engine | Average deck + comparison |
| `analysis/charts.py` | Query Engine | Matplotlib chart generation (Agg backend) |
| `analysis/predictions.py` | Query Engine | Prediction logging + validation |
| `analysis/blunders.py` | Deck Intelligence | Deck scoring (Major/Moderate/Minor) |
| `analysis/chapin.py` | Deck Intelligence | Chapin Principles (6 weighted principles) |
| `analysis/sideboard_guides.py` | Deck Intelligence | Guide parsing, G2/G3 WR model, flip detection |
| `analysis/tournament.py` | Tournament System | RCQ equity, binomial top-cut math |

## gui/

| File | Owner | Notes |
|---|---|---|
| `gui/theme.py` | — (shared) | Design system, TIMEFRAME_OPTIONS; no system owns this |
| `gui/main_window.py` | — (shared) | Tab container; no system owns this |
| `gui/worker_threads.py` | Data Engine | Scrape workers; memory leak suspects live here |
| `gui/setup_wizard.py` | Data Engine | First-run DB build flow |
| `gui/first_run_setup.py` | Data Engine | UAC elevation + task registration |
| `gui/tray_icon.py` | Data Engine | Status dots reflect scrape state |
| `gui/tabs/dashboard.py` | Query Engine | Meta standings display |
| `gui/tabs/deck_analyzer.py` | Deck Intelligence | Blunder + Chapin + Legality UI |
| `gui/tabs/search.py` | Query Engine | Card lookup, deck search, H2H |
| `gui/tabs/charts.py` | Query Engine | Interactive chart controls |
| `gui/tabs/predictions.py` | Query Engine | Prediction display |
| `gui/tabs/heatmap_tab.py` | Query Engine | Live matchup matrix tab |
| `gui/tabs/tournament_prep.py` | Tournament System | RCQ Optimizer + Breaker Math |
| `gui/tabs/knowledge_base.py` | — (shared) | Bookmarks + guides; cross-system |
| `gui/tabs/settings.py` | Data Engine | Format prefs, data window, scrape schedule |
| `gui/tabs/ask_claude.py` | — (shared) | AI chat; cross-system |
| `gui/widgets/archetype_detail.py` | Query Engine | Avg deck, recent lists, tech choices |
| `gui/widgets/chart_canvas.py` | Query Engine | FigureCanvasQTAgg wrapper |
| `gui/widgets/deck_export.py` | Deck Intelligence | MTGO/MTGA/decklist.org export |
| `gui/widgets/meta_table.py` | Query Engine | Meta standings table widget |

## Root-level

| File | Owner | Notes |
|---|---|---|
| `main.py` | Data Engine | CLI scrape entry point |
| `fill_database.py` | Data Engine | First-run DB builder |
| `run_gui.py` | — (shared) | App entry point |
| `register_tasks.py` | Data Engine | Task Scheduler registration |

---

## Files with no system owner (shared infrastructure)

These files serve multiple systems and should stay at root level permanently:

- `gui/theme.py` — design tokens used everywhere
- `gui/main_window.py` — tab container wiring
- `run_gui.py` — app entry point
- `gui/tabs/ask_claude.py` — cross-system AI chat
- `gui/tabs/knowledge_base.py` — cross-system reference store

---

## Migration notes (read before moving anything)

- **Do not move any file until its system's `core/` module has been built out.**
- Moving `analysis/archetypes.py` requires updating imports in `scrapers/`,
  `analysis/win_rates.py`, `analysis/query.py`, and several GUI tabs — do last.
- `analysis/charts.py` sets `matplotlib.use("Agg")` at import time.
  Never allow it to be imported inside GUI code regardless of where it lives.
- `db/database.py` is imported by nearly every other module — move it last
  within the Data Engine migration, after all other db/ files are settled.
