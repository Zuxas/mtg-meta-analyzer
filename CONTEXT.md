# CONTEXT — mtg-meta-analyzer

Purpose: PyQt6 app + SQLite warehouse of tournament + ladder metagame data;
source of truth for archetypes, decklists, matchups, and card legality.

## Vocabulary (as used in THIS repo)
- archetype / alias_layer / pre_normalize / fuzzy_match — name normalization stack (250+ aliases)
- ModernBERT / KNN / NBAC — card-embedding + classifiers for archetype ID
- melee_record / Untapped.gg — real Bo3 W/L sources (tournament / MTGA ladder)
- Glicko-2 / Wilson score — power rating + confidence scoring
- FastMCP — MCP server exposing the DB (list_decks, get_matchup, get_field_position)
- Scryfall / card_data — 3-tier card lookup; card_data PK = name TEXT
- post-board WR — sideboard-game WR model (calibration constants)
- data_quality_flags — deck-file audit markers (audit:intentional, audit:custom_variant)

## Key tables (data/mtg_meta.db)
events(format,date) / decks(archetype,placement) / deck_cards(qty,is_sideboard)
cards(name) / card_data(name,legalities) / untapped_decklists(mainboard_json)
untapped_meta_archetypes (MTGA LADDER ONLY — not tournament)

## Gotchas
- Modern tournament data lives in events/decks/deck_cards, NOT untapped_meta_archetypes
- Legality: card_data.legalities JSON, check format key == "legal"
- DB is consumed cross-repo by mtg-sim (db_bridge.py, meta_bridge.py)

## Key paths
data/mtg_meta.db  db/database.py  db/untapped_decklists.py  .claude/skills/
