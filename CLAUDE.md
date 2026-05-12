# CLAUDE.md — MTG Meta Analyzer

Last updated: 2026-05-12

> **Cross-project context:** This project is part of a local multi-repo
> ecosystem alongside mtg-sim and My-Website. Sibling clones at
> `../mtg-sim/` and `../My-Website/` if you want the full picture.

---

## NON-NEGOTIABLE RULES

1. **ALWAYS update CLAUDE.md, NEXT_STEPS.md, and ROADMAP.md before every commit**
2. **ALWAYS `git push` after every commit**
3. **ALWAYS run `--counts` or verify output after any scrape**
4. **Documentation must reflect actual current state, not planned state**

---

## 1. OVERVIEW

**Project:** Automated competitive MTG tournament data analysis tool.
**Goal:** Give Team Resolve a competitive edge for Pro Tour qualification — surface meta trends, identify rising archetypes, evaluate decklists against historical performance.
**GitHub:** https://github.com/Zuxas/mtg-meta-analyzer (public)

**User:** Jermey Wallace (Zuxas), team captain of Team Resolve.
5x RC qualifier. Current format focus: Modern.
Goal: Pro Tour qualification via RC conversion.

**Workspace:**

| Project | Relative path | Purpose |
|---|---|---|
| MTG Meta Analyzer | `./` (this repo) | Tournament data, meta analysis, GUI |
| Team Resolve | `../Team Resolve/` (private, local only) | Sideboard guides, gauntlet, RC prep |
| Road to Pro Tour | `../My-Website/` (private, local only) | Public-facing website source |

**Team Resolve workflow integration:**
- Dashboard meta share → gauntlet archetype selection
- Field Optimizer → best deck vs expected RC field
- Matchup matrix → sideboard guide builds in `Team Resolve/guides/`
- Sideboard guides synced from Skill Issue Magic sheet
- Event Optimizer binomial top-cut probability → RC entry decisions

---

## 2. ENVIRONMENT & SETUP

- **OS:** Windows 11, VS Code, Python 3.13
- **Shell:** cmd (Command Prompt) — set in .vscode/settings.json (avoids path space issues)
- **Project root:** the directory containing this CLAUDE.md
- **User context:** Limited coding experience; AI assistants are primary dev support

### First-Run Setup
1. `fill_database.bat` — builds local DB from scratch
2. Setup wizard on first GUI launch: format selection → Scryfall download → backfill → 50-event unlock
3. First-run UAC dialog (`gui/first_run_setup.py`) → registers 3 Task Scheduler tasks (one-time, never re-shown)

### User Preferences
`data/preferences.json` (gitignored) — format selection, date window, auto-update, API key.
Setup wizard page 0 saves formats immediately. `fill_database.py` and `scripts/run_fill_from_prefs.py` read at runtime.

### Automated Tasks
| Task | Script | Time |
|---|---|---|
| MTG-Meta-Analyzer-Background-6AM | `background_fill.bat` → `scripts/run_fill_from_prefs.py` | 6 AM daily |
| MTG-Meta-Analyzer-Daily | `run_daily.bat` | 5 PM daily |
| MTG-Meta-Analyzer-Scryfall-Weekly | `run_scryfall_weekly.bat` | Sunday midnight |

**Per-source throttling** (inside `scripts/run_fill_from_prefs.py`):
- **MTGDecks: Mon/Wed/Fri only** (added 2026-05-10) — Task Scheduler still fires
  daily at 6 AM, but MTGDecks block is gated by `_dt.date.today().weekday() in (0, 2, 4)`
  to reduce load on the source. Other scrapers (MTGTop8, MTGMelee, Spicerack, Scryfall)
  remain daily. Skipped runs print `MTGDecks SKIPPED (throttled to M/W/F)` to the log.

---

## 3. DATABASE

### Schema
- **Active:** `data/mtg_meta.db` — events within retention window (gitignored)
- **Archive:** `data/mtg_archive.db` — older data (moved, never deleted)
- **Tables:** events, decks, cards, deck_cards, card_data, matches, predictions, guides, bookmarks, saved_decks, saved_sb_plans, matchup_matrix, matchup_notes
- **card_data:** keyed by card name (TEXT PK) — works across both DBs. Populated by `python -m scrapers.scryfall`
- **Use** `get_combined_connection()` to query across both DBs

### Retention Policy
- All formats: 3-year rolling window (1095 days)
- Standard + Foundations (FDN): 5-year window
- Archive-based: old data → `mtg_archive.db`, never deleted
- Configurable per-format in `config.ini`

### Primary Format
Standard is primary. Pioneer, Modern, Legacy, and Pauper actively scraped.

---

## 4. DATA COLLECTION

### Scrapers
- **MTGTop8** (`scrapers/mtgtop8.py`) — events, decklists (main + sideboard), player names
- **MTGO Challenges** (`scrapers/challenges.py`) — Challenge-specific scraper
- **MTGDecks.net** (`scrapers/mtgdecks.py`) — uses `cloudscraper` for Cloudflare bypass; Arena export format
- **Historical backfill** (`scrapers/backfill.py`) — pages backwards year-by-year
- **Scryfall** (`scrapers/scryfall.py`) — 3-tier lookup: SQLite → local bulk JSON → live API. Weekly auto-refresh
- **MTGMelee** (`scrapers/mtgmelee_scraper.py`) — real match W/L from melee.gg (not mtgmelee.com)
- **Matchup scraper** (`scrapers/matchup_scraper.py`) — MTGDecks.net `/winrates` table
- **Mythic Spoiler** (`scrapers/mythicspoiler_scraper.py`) — set card lists + Scryfall enrichment
- **Guides** (`scrapers/guides.py`) — Skill Issue Magic Google Sheet → guides table
- **Untapped.gg pipeline** (`scrapers/untapped_*.py`) — mythic ladder, archetype/matchup matrices, replays, sideboard plans. Public endpoints unauthenticated; premium per-archetype data needs `data/untapped/untapped_cookies.txt`. See `scrapers/UNTAPPED_README.md`. Throttled to M/W/F.
- **Player handles** (`scrapers/player_handles.py`) — Twitter/X handle discovery + tweet fetching for top finishers

### MTGMelee Endpoints (verified 2026-03-25)
- Tournament list: `POST https://melee.gg/Tournament/TournamentSearch`
- Pairings: `GET /Tournament/View/{tid}` → parse round buttons → `POST /Match/GetRoundMatches/{roundId}`
- Match JSON: `Competitors[i].Team.Players[0].DisplayName`, `Competitors[i].Decklists[0].DecklistName`, `Competitors[i].GameWins`
- Swagger API (`/swagger/ui/index`) requires staff auth — not usable

### Archetype Normalization (`analysis/archetypes.py`)
Three-layer system: (1) `pre_normalize()` for spacing/WUBRG codes, (2) 250+ ALIASES, (3) optional fuzzy match.
Card-based dedup: `find_card_based_duplicates()` finds similar-named archetypes with ≥67% card overlap.

---

## 5. ANALYSIS ENGINES

| Module | Purpose |
|---|---|
| `analysis/win_rates.py` | Meta standings, weekly trend, H2H, matchup matrix, field optimizer, real match WR |
| `analysis/deck_analysis.py` | Average deck calculator, deck comparison |
| `analysis/predictions.py` | Auto-generated predictions, validation, accuracy tracking |
| `analysis/blunders.py` | Deck scoring: land count, curve, color consistency, interaction (Major/Moderate/Minor) |
| `analysis/chapin.py` | 6-principle evaluation: Threats/Answers/Consistency/Velocity/Mana/Clock (0-10 each) |
| `analysis/sideboard_guides.py` | Guide parsing (regex IN/OUT), post-board WR model, flip detection |
| `analysis/tournament.py` | Event equity, standings, ID recommendation, EVENT_PRESETS, x-loss cutoff |
| `analysis/meta_scoring.py` | Prep priority (0-100), status labels (Pillar/Trap/Underplayed/Fringe) |
| `analysis/ratings.py` | Glicko-2 power ratings, weekly periods, 262k+ matches, 120s TTL cache |
| `analysis/equilibrium.py` | Nash LP solver, replicator dynamics, RPS cycle detection, Monte Carlo sim |
| `analysis/card_embeddings.py` | 768-dim ModernBERT vectors for 32k cards (HuggingFace parquet) |
| `analysis/cooccurrence_embeddings.py` | Card2Vec — Word2Vec trained on local decklists |
| `analysis/knn_classifier.py` | KNN archetype classifier using deck embeddings |
| `analysis/nbac_classifier.py` | NBAC API wrapper (Videre Project Naive Bayes archetype classifier) |
| `db/untapped_queries.py` | Untapped Bo3 matchup matrix + archetype-color resolver + SB plans by color identity |

### Sideboard WR Model (calibration constants)
`opp_per_card=0.013, my_per_card=0.010, cap=0.13, clamp=[0.18, 0.84]`

---

## 6. GUI

**Entry point:** `run_gui.py` | **Theme:** `gui/theme.py` — modern dark theme, Inter font, Team Resolve branding
**7 top-level tabs** (consolidated from 13): Dashboard, Meta (Charts/Matchup Data/Predictions/Simulate/Calibration/Ladder), Decks (Analyze/My Decks), Search, Tournament (Event Optimizer/Match Log), Resources (Guides/Ask Claude/Set Analysis), Settings

### Dashboard (Untapped.gg-inspired)
- Three-column top: Recent Top Finishes / Win Rate / Popular
- Win Rate panel columns: Pips | Archetype | Win% | Change | Rating | Prep | Status | Tier | Role
- "Meta Shift" button: compare current vs prior period (rising/falling/new/gone)
- "Best Deck" button: meta-based deck recommendation with composite scoring
- Popularity/Win Rate Over Time charts with Weekly|Daily toggle, event markers, archetype checkboxes
- Dynamic panel titles update with timeframe selector
- Dedup-aware Meta Impact bar shows filter effects

### Key GUI Features
- **Archetype detail dialog:** 7 tabs (This List / Average Deck / Recent Lists / Tech Choices / Bo3 SB Plans / Card Trends / Resources) + "View Event" + Export
- **Bo3 SB Plans tab:** Sideboard plans extracted from Untapped Mythic-level ladder replays via game-to-game decklist diffs. Matched to archetype by color identity. Top section aggregates most-common cards IN/OUT; below lists individual plans (deck name, pilot, G1→G2 / G2→G3 transitions).
- **Ladder sub-tab (Meta group):** MTGA-ladder meta surface. Format selector (Standard / Pioneer / Historic / Timeless / Alchemy). Mythic archetype rollup at top, Bo1 skill curve (Bronze→Silver→Gold→Plat WR per archetype + climb delta) on the left, Mythic leaderboard top-30 on the right. Bo3 ranked WR is NULL in the public Untapped meta endpoint, so the skill curve uses Bo1.
- **Tech Choices:** Flex slots (15-80% inclusion) grouped by role (Threat/Removal/Card Advantage/Mana/Protection/Utility)
- **Event peers:** Click Event column → `EventPeersDialog` showing all decks from tournament
- **Card image tooltips:** Scryfall API, in-memory cache, floating widget
- **Matchup Data:** Three sources merged (real★ + scraped + paste), team notes via right-click, equilibrium button
- **My Decks:** CRUD + SB plans + export (MTGO/MTGA/decklist.org) + Share/Import JSON
- **Deck Analyzer:** Arena/URL paste → Blunder + Chapin + Legality + auto-classify (KNN) + baseline comparison vs average deck
- **Card Browser:** Scryfall query syntax, Similar Cards + Functional Substitutes
- **Tournament Prep:** Event Optimizer (binomial top-cut, matchup breakdown, SB recommendations) + Breaker Math
- **System tray:** Team Resolve logo + green/orange/red status dot, close-to-tray, Run Now menu

### Timeframe System
`theme.TIMEFRAME_OPTIONS`: 1w/2w/4w/8w/3m/6m/1y/2y/All Time. `None` = All Time = no date filter.
All query functions handle `since=None` via `if since:` guards.
Special case: `get_archetype_trend()` uses `window_start = since or (window_end - timedelta(weeks=weeks or 520))`.

---

## 7. KEY FILES

```
# ── Launchers ──────────────────────────────────────────────
run_gui.py                      GUI entry point (--register-tasks mode)
main.py                         CLI entry point
fill_database.py                Standalone DB builder (reads preferences.json)
mtg.bat                         Consolidated menu launcher (7 options)
launch_app.bat                  Double-click GUI launcher

# ── Scrapers ───────────────────────────────────────────────
scrapers/mtgtop8.py             MTGTop8 events + decklists
scrapers/challenges.py          MTGO Challenge scraper
scrapers/mtgdecks.py            MTGDecks.net (cloudscraper)
scrapers/backfill.py            Historical backfill
scrapers/scryfall.py            Card database + enrichment
scrapers/mtgmelee_scraper.py    Real match W/L from melee.gg
scrapers/matchup_scraper.py     MTGDecks.net win-rate matrix
scrapers/mythicspoiler_scraper.py  Set spoiler scraper
scrapers/guides.py              Skill Issue Magic sheet sync
scrapers/constants.py           Shared headers, format maps, delays, base URLs

# ── Database ───────────────────────────────────────────────
db/database.py                  Schema, connections, active + archive
db/maintenance.py               Archive maintenance + orphan cleanup
db/saved_decks.py               Saved decks + SB plans (CASCADE delete, upsert)
db/matches_queries.py           Match records CRUD
db/matchup_queries.py           Matchup matrix + team notes
db/helpers.py                   Shared DB helpers (ensure_table, utc_now, JSON)

# ── Analysis ──────────────────────────────────────────────
analysis/win_rates.py           Performance tracking, matchup matrix, field optimizer
analysis/archetypes.py          Name normalization + alias table + migration
analysis/deck_analysis.py       Average deck + comparison
analysis/predictions.py         Self-validation predictions
analysis/blunders.py            Deck scoring / blunder detection
analysis/chapin.py              Chapin Principles evaluation
analysis/tournament.py          Event equity, ID recommendation, presets
analysis/sideboard_guides.py    Guide parsing, post-board WR model
analysis/meta_scoring.py        Prep priority + trap detection
analysis/ratings.py             Glicko-2 power ratings
analysis/equilibrium.py         Nash equilibrium, RPS cycles, Monte Carlo
analysis/card_embeddings.py     ModernBERT embeddings
analysis/cooccurrence_embeddings.py  Card2Vec (Word2Vec on decklists)
analysis/knn_classifier.py      KNN archetype classifier
analysis/meta_change.py         Compare two time periods (rising/falling/new/gone)
analysis/deck_roles.py          Classify archetypes as Aggro/Midrange/Control/Combo/Tempo
analysis/deck_recommender.py    Meta-based deck recommendation engine
analysis/card_adoption.py       Card inclusion rate tracking over time
analysis/slot_analysis.py       "Why this card?" — role, trend, substitutes, competitors
analysis/cross_source_dedup.py  Cross-source duplicate event detection + confidence scoring
analysis/date_parsing.py        Natural language date range parsing
analysis/field_optimizer.py     Weighted WR vs expected field
analysis/query.py               CLI query interface

# ── GUI ────────────────────────────────────────────────────
gui/theme.py                    Design system: colors, fonts, Inter, TIMEFRAME_OPTIONS
gui/main_window.py              Main window, branded header, tab container
gui/setup_wizard.py             First-time setup wizard
gui/tray_icon.py                System tray (Team Resolve logo + status dot)
gui/first_run_setup.py          UAC dialog + task registration
gui/worker_threads.py           QThread workers
gui/worker_utils.py             Shared cancel_worker() pattern
gui/widgets/table_helpers.py    SortItem, NumItem, DateItem, make_table()
gui/widgets/chart_canvas.py     Matplotlib FigureCanvasQTAgg
gui/widgets/archetype_detail.py Archetype detail (6 tabs + View Event)
gui/widgets/event_peers.py      Event peers dialog
gui/widgets/card_tooltip.py     Card image tooltips
gui/widgets/deck_export.py      MTGO/MTGA/decklist.org export
gui/tabs/dashboard.py           Dashboard (3-panel + charts)
gui/tabs/deck_analyzer.py       Deck Analyzer
gui/tabs/my_decks.py            My Decks CRUD
gui/tabs/match_log.py           Match Log (personal results)
gui/tabs/search.py              Card Browser / Deck Search / H2H
gui/tabs/tournament_prep.py     Tournament Prep wrapper (composes sub-tabs)
gui/tabs/event_optimizer.py     Event Optimizer sub-tab
gui/tabs/breaker_math.py        Breaker Math sub-tab
gui/tabs/heatmap_tab.py         Matchup Data grid + team notes
gui/tabs/charts.py              Interactive chart controls
gui/tabs/card_browser.py        Scryfall-style card search
gui/tabs/knowledge_base.py      Bookmarks + guides
gui/tabs/predictions.py         Prediction management
gui/tabs/ask_claude.py          AI chat (API-gated)
gui/tabs/set_analysis.py        New Set Break Protocol (API-gated)
gui/tabs/settings.py            Preferences UI
gui/icons/                      Team Resolve logo (16-256px + .ico)
gui/fonts/                      Inter (Regular/Medium/SemiBold/Bold) + Orbitron

# ── Config ─────────────────────────────────────────────────
config.example.ini              Committed config template
config.ini                      Local config (gitignored)
data/preferences.json           User preferences (gitignored)
data/rules_reference/           MTG Comprehensive Rules + Scryfall rulings/oracle cards
```

---

## 8. HOW TO RUN

```bash
# GUI
python run_gui.py

# Build database from scratch
fill_database.bat

# Manual scrapes
python main.py                                          # Standard latest
python -m scrapers.backfill --format pioneer             # Historical backfill
python -m scrapers.mtgmelee_scraper --format standard --pages 9
python -m scrapers.scryfall --download                   # Refresh Scryfall bulk

# Analysis queries
python -m analysis.query meta --format standard
python -m analysis.query trend "Izzet Prowess" --weeks 8
python -m analysis.query h2h "Izzet Prowess" "Azorius Control"
python -m analysis.query matrix --top 12
python -m analysis.query field-optimizer --field "Izzet Prowess x4, Mono Green x3"
python -m analysis.query average "Izzet Prowess"
python -m analysis.query blunder "Izzet Prowess" --format standard
python -m analysis.query chapin "Izzet Prowess" --format standard
python -m analysis.query card "Sheoldred, the Apocalypse"

# Maintenance
python -m analysis.archetypes --apply
python -m scrapers.guides
python -m db.maintenance
```

---

## 9. CRITICAL IMPLEMENTATION NOTES

### matplotlib backend
`analysis/charts.py` sets `matplotlib.use("Agg")` at import. **Never import it in GUI code.**
GUI uses `gui/widgets/chart_canvas.py`. `run_gui.py` calls `matplotlib.use("QtAgg")` first.

### Worker lifecycle
All workers: `finished → deleteLater()`. All tabs expose `cleanup()`. `_cancel_worker()` uses `blockSignals(True)` with `RuntimeError` guard.

### PyInstaller packaging (when ready)
```bash
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" \
  --add-data "gui/fonts;gui/fonts" --add-data "gui/icons;gui/icons"
```
`--register-tasks` reuses same .exe elevated. `data/` stays external. `anthropic` package optional.

### Event types tracked
`mtgo_challenge_32`, `mtgo_challenge_64`, `mtgo_league`, `mtgo_preliminary`, `paper`

---

## 10. END-OF-SESSION PROTOCOL

1. Update CLAUDE.md — current state, new files, design decisions
2. Update NEXT_STEPS.md — accurate priorities
3. Update ROADMAP.md — check off completed items
4. `git add`, commit with clear message, `git push`
5. After any scrape: verify output with `--counts`

**These steps are NON-NEGOTIABLE.**

---

## Installed Skills

Project-scoped (in `.agents/skills/`, managed via `npx skills`):

| Skill | Source | Trigger |
|---|---|---|
| `triage-issue` | local | Bug reports, "triage", investigate and plan a fix |
| `improve-codebase-architecture` | local | Architecture review, refactoring opportunities |
| `grill-me` | local | Stress-test a plan or design decision |
| `modern-python` | trailofbits/skills | Configuring pyproject.toml, ruff/uv/pytest, migrating off Poetry/black |
| `pdf` | anthropics/skills | Reading + manipulating PDFs (MTG Comp Rules in `data/rules_reference/`) |
| `xlsx` | anthropics/skills | Excel/tabular work (Skill Issue Magic guide exports, .csv data) |
| `query` | duckdb/duckdb-skills | DuckDB SQL queries — can `ATTACH 'data/mtg_meta.db'` for fast OLAP on the project DB without writing Python |
| `playwright` | openai/skills | Real-browser scraping via playwright-cli. For sites the cloudscraper path can't handle (JS-rendered, complex session capture) |
| `mcp-builder` | anthropics/skills | Patterns for building MCP servers — if/when `mtg_meta.db` gets exposed as an MCP so Claude can query the data layer directly |

To restore on a fresh clone: `npx skills experimental_install` (reads `skills-lock.json`).

---
*Last documentation update: 2026-05-12 — Untapped.gg pipeline session.
  Shipped: scraper suite (mythic ladder + premium archetype/matchup +
  replays + SB extractor), `db/untapped_queries.py` query layer,
  3 GUI surfaces (Matchup Data heatmap 4th source, Bo3 SB Plans tab in
  Archetype Detail, Meta→Ladder sub-tab with skill curve + leaderboard),
  player_handles (Twitter/X discovery), NBAC API classifier, DD/MM/YY
  date-sort fixes, MTGDecks+Untapped M/W/F throttling, pre-push hook
  hardened with cookies-file-aware skip-list. 7 commits.*

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
