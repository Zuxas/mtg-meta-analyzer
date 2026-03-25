# Query Engine

## Purpose
Everything that reads, aggregates, filters, and surfaces data to the user.
Sits between the Data Engine (storage) and the GUI/CLI (display).

## Responsibilities
- Meta standings: archetype share, win rate, trend, head-to-head
- Matchup matrix and field optimizer
- Average deck calculation and deck comparison
- Chart generation (meta share, trend lines, heatmap)
- CLI query interface (`python -m analysis.query ...`)
- Natural language date range filtering
- Card-level queries (tournament presence, usage stats)
- Prediction generation and validation

## Current file ownership (existing code — not moved yet)

| File | Role |
|---|---|
| `analysis/query.py` | CLI entry point for all query subcommands |
| `analysis/win_rates.py` | Win rate, meta standings, matchup matrix, field optimizer |
| `analysis/deck_analysis.py` | Average deck + deck comparison |
| `analysis/charts.py` | Matplotlib chart generation (CLI/Agg backend) |
| `analysis/predictions.py` | Prediction logging + validation + accuracy tracking |

## Planned features (from ROADMAP)
- Card-name decklist search (exact + multi-card AND/OR)
- Global "All Formats" option everywhere
- URL import in Deck Analyzer (Moxfield, Archidekt, MTGGoldfish, MTGTop8, MTGMelee)
- Event peer navigation (all decks from same event)
- Flex slot competition view (cards competing for same slot)
