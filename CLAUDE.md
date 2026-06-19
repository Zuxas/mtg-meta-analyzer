# CLAUDE.md — MTG Meta Analyzer

Last updated: 2026-06-18 (**CI hardening**: the two `self-hosted` CI jobs in `.github/workflows/ci.yml` (`gui-imports`, `predictions-gate`) had **never run** — they only triggered on `pull_request` (this repo merges locally, never via PRs) and the runner (`NETWORK SERVICE`, `C:\Program Files\Python313`) was never provisioned: no pip, no PyQt6, `MTG_META_DB` unset. Confirmed via a throwaway `workflow_dispatch` env-dump job on the runner. Fix: **`gui-imports` moved to hosted `ubuntu-latest`**, runs on push/PR, installs `requirements.txt`+`PyQt6`+Qt libs (`libegl1 libgl1 libxkbcommon0 libdbus-1-3`), headless via `QT_QPA_PLATFORM=offscreen`, **pinned to Python 3.12** (lxml 5.3.0 has no cp313 wheel → source build fails on 3.13). **`predictions-gate` removed** (needs the local DB; can't run on a hosted runner). Self-hosted runner dependency dropped; the runner service can be left registered but is now unused. Both CI + tests workflows green on `c9b8dc7`. Also restored the **local dev env** the same day — a 6/16 event had wiped pip + all deps from both Python 3.13 installs; reinstalled into the shared user-site without admin (see §2 *Python interpreter layout*); 355 tests green.)

Earlier: 2026-06-11 (**MCP server** shipped on `feat/mcp-server`: `mcp_server/` exposes the meta DB as four read-only, agent-callable tools over FastMCP/stdio — `list_decks`, `get_matchup`, `get_field_position`, `search_matchups`. Pure, tested logic in `mcp_server/tools.py` wraps the existing `analysis/win_rates.py`; thin `@mcp.tool` registrations + entry point in `mcp_server/server.py`. Key design decision = **explicit provenance**: the data has two different win-rate signals (real melee.gg matches vs a placement-based proxy), so every result carries a `source` field, prefers real data, and preserves the analysis layer's data-quality notes. Unknown deck names return structured `deck_not_found` with fuzzy suggestions via the app's own `analysis.archetypes.normalize`. Registered at project scope (`.mcp.json`, `python -m mcp_server.server`; one-time approval in `claude`). `mcp>=1.27` added to requirements. 9 tests in `tests/test_mcp_server.py`; full suite **347 green**. README at `mcp_server/README.md`. NEXT (deferred): `search_strategy_docs` semantic search over the mtg-sim doc corpus backed by Pinecone.)

Previous: 2026-06-04 — Event Finder UX overhaul on `feat/event-finder-ux` (numeric sort, Time column, "When" filter, 300 mi radius, RCQ row tint, Google Maps right-click, persisted filters; 26 tests). 2026-05-25 — Replay-viewer M4 review annotation. M3: board panel. M2: viewer window. M1: data layer.

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

### Python interpreter layout (Windows)
Two Python **3.13** installs coexist: all-users `C:\Program Files\Python313` (what bare `python`/`pythonw` and the `.bat` launchers resolve to via machine PATH) and a per-user one under `%LOCALAPPDATA%\Programs\Python\Python313` (the `py` launcher default). Because both are 3.13 they **share** the user-site dir `%APPDATA%\Python\Python313\site-packages`, which is on the import path of both and is user-writable.

**Reinstall deps without admin** (the Program Files `site-packages` needs elevation; the shared user-site does not):
```bat
python -m ensurepip --user --upgrade
python -m pip install --user --no-warn-script-location -r requirements.txt PyQt6
```
`PyQt6` is **not** pinned in `requirements.txt` (only `qtawesome`/`matplotlib`) — install it explicitly. Bare `pip` won't be on PATH (scripts land in the user-site `Scripts` dir); use `python -m pip`. Verify with `python -m pytest -q` (baseline 355 green as of 2026-06-18). On 2026-06-18 the deps had been wiped (cause unidentified, correlated with a restart) and were restored exactly this way.

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
- **MTGDecks: AUTO-PULL DISABLED** (2026-06-04) — the M/W/F throttle was replaced with a hard skip per user request. Task Scheduler still fires the pipeline daily; the MTGDecks block prints `MTGDecks SKIPPED (auto-pull disabled)` and moves on. Manual escape hatches preserved: `fill_database.bat` (full rebuild), Settings tab refresh button, Matchup Data tab "scrape" action. To re-enable, restore `MTGDECKS_DAYS = (0, 2, 4)` and the surrounding `if today_dow in MTGDECKS_DAYS:` gate.

---

## 3. DATABASE

### Schema
- **Active:** `data/mtg_meta.db` — events within retention window (gitignored)
- **Archive:** `data/mtg_archive.db` — older data (moved, never deleted)
- **Tables:** events, decks, cards, deck_cards, card_data, matches, predictions, guides, bookmarks, saved_decks, saved_sb_plans, matchup_matrix, matchup_notes, match_log, deck_variants, untapped_decklists (per-player canonical decklist from local replay corpus), match_log_sb_plans (per-match SB plan extracted from MTGA Player.log SubmitDeckReq events), match_log_games (per-game stats: life endpoints, mull-to, turn count), rank_snapshots (MTGA constructed/limited rank time series)
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
| `analysis/ratings.py` | Glicko-2 power ratings, weekly periods, 260k+ matches, 120s TTL cache |
| `analysis/equilibrium.py` | Nash LP solver, replicator dynamics, RPS cycle detection, Monte Carlo sim |
| `analysis/card_embeddings.py` | 768-dim ModernBERT vectors for 32k cards (HuggingFace parquet) |
| `analysis/cooccurrence_embeddings.py` | Card2Vec — Word2Vec trained on local decklists |
| `analysis/knn_classifier.py` | KNN archetype classifier using deck embeddings |
| `analysis/nbac_classifier.py` | NBAC API wrapper (Videre Project Naive Bayes archetype classifier) |
| `analysis/deck_ev.py` | Single-deck field-weighted EV: paper WR + Untapped Bo3 + SB difficulty bumps |
| `analysis/mulligan_study.py` | Monte Carlo mulligan simulator (1000+ hands) reusing primer-rule evaluator |
| `analysis/scout.py` | Pre-event pilot intel: top-cut finishers by archetype + handle resolution |
| `db/untapped_queries.py` | Untapped Bo3 matchup matrix + archetype-color resolver + SB plans by color identity + card-level Mythic inclusion |
| `analysis/wilson.py` | Wilson score interval + tweak classifier (validated / promising / noisy) |
| `analysis/my_deck_classifier.py` | Overlap-score classifier mapping observed grpIds -> saved_decks.id |
| `db/untapped_decklists.py` | Per-player Untapped decklist storage — extract from local replay corpus, grpId resolver, upsert/query, batch populate |

### Sideboard WR Model (calibration constants)
`opp_per_card=0.013, my_per_card=0.010, cap=0.13, clamp=[0.18, 0.84]`

---

## 6. GUI

**Entry point:** `run_gui.py` | **Theme:** `gui/theme.py` — modern dark theme, Inter font, Team Resolve branding
**8 top-level tabs** (consolidated from 13): Dashboard, Meta (Charts/Matchup Data/Predictions/Simulate/Calibration/Ladder), Decks (Analyze/My Decks), Search, Tournament (Event Optimizer/Match Log), Resources (Guides/Ask Claude/Set Analysis), Puzzles (Solve), Settings

### Dashboard (Untapped.gg-inspired)
- Three-column top: Recent Top Finishes / Win Rate / Popular
- Win Rate panel columns: Pips | Archetype | Win% | Change | Rating | Prep | Status | Tier | Role
- "Meta Shift" button: compare current vs prior period (rising/falling/new/gone)
- "Best Deck" button: meta-based deck recommendation with composite scoring
- Popularity/Win Rate Over Time charts with Weekly|Daily toggle, event markers, archetype checkboxes. **Default = Win Rate Over Time** (2026-05-14). X-axis uses real datetime objects (not categorical strings) so chronological order is invariant to archetype plot order; year shows in tick labels only when data crosses a year boundary. Per-bucket appearance threshold is `n>=1` (was `n>=3`, too aggressive for short windows).
- Dynamic panel titles update with timeframe selector
- Dedup-aware Meta Impact bar shows filter effects

### Key GUI Features
- **Archetype detail dialog:** 7 tabs (This List / Average Deck / Recent Lists / Tech Choices / Bo3 SB Plans / Card Trends / Resources) + "View Event" + Export. Average Deck tab includes Mythic % column with ↑/↓ tech-divergence arrows.
- **Bo3 SB Plans tab:** Sideboard plans extracted from Untapped Mythic-level ladder replays via game-to-game decklist diffs. Matched to archetype by color identity. KNN-refined matching when game-1 deck is available. Opponent archetype classified from MTGA replay log. Matchup filter dropdown narrows plans by opponent. Top section aggregates most-common cards IN/OUT; below lists individual plans.
- **Ladder sub-tab (Meta group):** MTGA-ladder meta surface. Format selector (Standard / Pioneer / Historic / Timeless / Alchemy). Mythic archetype rollup at top (Mythic-having archetypes pinned), Bo3-only skill curve with 8 columns (Bronze→Silver→Gold→Platinum→Diamond→Mythic + Br→My delta) — Br/Si/Go responsively hide on narrow viewport. Mythic leaderboard top-30 on the right with **deck linkout**: double-click a row to open that player's deck on Untapped.gg, right-click for "Open deck" / "Copy deck URL" / "Save to My Decks". URL builder lives at `db.untapped_queries.untapped_deck_url` (`mtga.untapped.gg/decks/<short_id>` — no profile prefix). **Decklist panel** below the leaderboard table populates on row selection — main + SB from `db.untapped_decklists.get_decklist(short_id)`. Two toolbar buttons: **↻ Cache local** extracts pre-board mainDeck/sideboard from every locally-stored Untapped replay (no network — pulls from the corpus the replay fetcher already downloaded). **↻ Pull current top 30** fetches replays for the currently-displayed leaderboard from Untapped (rate-limited 2 req/sec), then runs the cache step — use this to see today's leaderboard decks, not older snapshot decks. Save-to-My-Decks copies the canonical decklist into `saved_decks` for side-by-side EV comparison vs your build. Bo3-filtered everywhere via `Traditional_<format>` data source.
- **Tech Choices:** Flex slots (15-80% inclusion) grouped by role (Threat/Removal/Card Advantage/Mana/Protection/Utility)
- **Event peers:** Click Event column → `EventPeersDialog` showing all decks from tournament
- **Card image tooltips:** Scryfall API, in-memory cache, floating widget
- **Matchup Data:** Three sources merged (real★ + scraped + paste) + Untapped Bo3 ladder as 4th gap-fill source, team notes via right-click, equilibrium button
- **My Decks:** CRUD + SB plans + export (MTGO/MTGA/decklist.org) + Share/Import JSON. Deck-detail panel has 5 sub-tabs: Decklist / Sideboard Plans (master-detail layout) / Test Hand / EV vs Field / Match History.
- **Test Hand sub-tab:** Primer-rule mulligan evaluator — random 7-card draw, classifies cards (land/cantrip/threat/answer), KEEP/MARGINAL/MULL verdict with reasoning by play-draw and matchup. "Run 1000-hand study" button opens MulliganStudyDialog (12k Monte Carlo simulations across primer's 5 matchups × play/draw, keep/mull-to-6/mull-to-5/mull-to-4 rates).
- **EV vs Field sub-tab:** Field-weighted WR for the saved deck — combines paper matchup data + Untapped Bo3 + SB difficulty bumps (Easy +5pp / Hard -5pp). Headline EV number, top favorable/unfavorable matchups, per-matchup breakdown table with source color-coding (paper/untapped/mirror/guess) and low-N flagging.
- **Match History sub-tab (2026-05-14):** Per-deck match log filtered by `my_deck_id`. Summary header shows overall W-L + WR%, plus per-category breakdown (Ranked Bo3 / Ranked Bo1 / Unranked / Limited / Other) sourced from the raw MTGA event_name. Filter dropdown narrows to one category. Matchup aggregation table sums W-L per opponent archetype. Recent-matches list (top 50, newest first) with date / event / opponent / archetype / result / play-draw. **Click a recent-matches row** → right pane (horizontal splitter) shows per-game W/L + class (close/blowout/normal) + turn count + mull-to + life endpoints, followed by the SB plan (G1→G2 / G2→G3 with +N CardName in / -N CardName out from `match_log_sb_plans` table). A **`▶ Watch` split button** (`QToolButton`) on the detail panel: primary action opens the full-depth viewer (`gui/widgets/replay_viewer_window.py::ReplayViewerWindow`, M2 — 2026-05-24); the dropdown also offers **Watch (Classic)** (the legacy `gui/widgets/replay_transcript_dialog.py` text dump). Last-used mode persists in `tabs.match_history.replay_viewer_mode` and becomes the primary click. The full viewer (a non-modal QMainWindow with `WA_DeleteOnClose` + reopen guard) shows a left timeline tree (Game→Turn→Phase→Step→Event), a lazy `QAbstractTableModel` event table with kind-filter chips + substring search, right detail tabs (Event Details / Stack / read-only Notes) + card preview, Jump-To-key-events menu, and nav buttons — all driven off the M1 `events[]` data layer (`analysis/replay_events.build_event_stream`). All display logic is Qt-free in `gui/replay_view_model.py` (timeline tree, event summaries, kind groups, navigation, jump-to, detail/stack rows — fully unit-tested). The bottom board panel (M3, `gui/widgets/replay_board_panel.py::ReplayBoardPanel`, fed by `analysis.replay_events.replay_board_at`) renders a two-row board — life/mana + Hand/Lib/GY/Exile counts + battlefield card thumbnails — synced to the cursor, with a current-card highlight, a Show-Board-Changes toggle, and hover-to-full-image (`card_tooltip.install_card_hover`). Tap/counters/auras/combat are deferred (not in the M1 `events[]`/`board_diff` data contract). Speed/Animate are M5 placeholders. **M4 review annotation:** the right-pane **Notes** tab is editable and persists to `match_log.replay_notes` (`db.match_log.get_replay_notes`/`save_replay_notes`; saved on the Save button + on window close); a top-bar **★ Mark** toggle flags the current event (marks persist + appear as a section in the Jump-To menu); an **Export review** button writes a Markdown summary (notes + marked events) via `gui.replay_view_model.replay_markdown`. Both viewers cache to `data/match_replays/<arena_match_id>.json`. Lives at `gui/widgets/deck_match_history.py`.
- **Deck Analyzer:** Arena/URL paste → Blunder + Chapin + Legality + auto-classify (KNN) + baseline comparison vs average deck
- **Card Browser:** Scryfall query syntax, Similar Cards + Functional Substitutes
- **Tournament Prep:** 6 sub-tabs — Prep Checklist / Event Optimizer / Event Hub / Scout / Breaker Math / Hypotheses.
- **Scout sub-tab:** Pre-event pilot intel. Surfaces top-N finishers playing target archetypes (defaults to Tokyo Prowess priority matchups) in last K days. "Repeat offenders" table ranks pilots by top-cut count; "All finishes" table lists every result. Right-click context menu opens decklist URL or `@handle` on x.com (handles from `data/player_handles.json`). Double-click finisher row opens deck URL.
- **Match Log (refreshed 2026-05-13):** Each row links to a specific saved-deck variant (mainboard+sideboard hash). Right-side **Variant Timeline** panel renders the deck's history when you filter to one deck: per-variant match count, WR, Wilson-significance flag (validated / promising / noisy), +/- card-swap delta from the previous variant. "↻ Sync Untapped" button kicks off `scrapers.untapped_match_log_writer.run()` ad-hoc; same writer runs in the M/W/F pipeline. Orphan banner + "Resolve..." dialog walks historical rows where `my_deck_id IS NULL`.
- **Puzzles tab (Phase 2)**: MTGA-style "find-the-line" practice with
  Solve | Inbox sub-modes. Solve = render saved scenes (life circles,
  mirrored zones, fanned hand, Scryfall card images) + typed-answer +
  reveal + self-grade; attempts recorded in `puzzle_attempts`. Inbox =
  scanner-extracted candidates from `data/match_replays/` ranked by
  per-category heuristics (find_lethal / stabilize / simplified-tempo);
  Promote opens the Author dialog with scene preview pre-loaded; Dismiss
  hides the row. Author dialog (`gui/widgets/puzzle_author_dialog.py`)
  also reachable from Match History recent-matches right-click → "Create
  puzzle from this turn". Scanner CLI: `python scripts/scan_for_puzzles.py`.
  Card data verified via `db.card_data` at every authoring path —
  invented cards can't ship. Spec at
  `docs/superpowers/specs/2026-05-16-puzzle-tool-design.md`. **Phase 3
  shipped 2026-05-17:** `analysis/puzzles/graders.py` provides
  `grade_keyword` (rapidfuzz partial_ratio threshold 80 for typo tolerance),
  `grade_llm` (inline Anthropic claude-haiku-4-5 ~$0.001/grading),
  and a `grade()` dispatcher with fallback chain
  (llm → keyword → self). Verdict appears as a colored chip below the
  author's solution on Reveal; self-grade ✓/✗ buttons remain as user override.
- **System tray:** Team Resolve logo + green/orange/red status dot, close-to-tray, Run Now menu
- **F5 / ↻ Refresh button** in branded header — reloads current tab's data from DB (walks nested QTabWidgets to find leaf, calls reload/refresh).

### Timeframe System
`theme.TIMEFRAME_OPTIONS`: 1w/2w/4w/8w/3m/6m/1y/2y/All Time. `None` = All Time = no date filter.
All query functions handle `since=None` via `if since:` guards.
Special case: `get_archetype_trend()` uses `window_start = since or (window_end - timedelta(weeks=weeks or 520))`.

### Persisted UI state (sticky)
`gui/state.py::UIState` is a singleton wrapping `data/preferences.json` under a `ui_state` key. Tabs hydrate from it in `showEvent` (with `blockSignals(True)` to avoid loops) and persist on widget change. Slices today (paths centralized in `gui/state_keys.py`):
- `global.last_active_tab_path` — app reopens where you closed it
- `global.format` — written by palette `act:format-*`, read by archetype detail dialog
- `tabs.dashboard.timeframe`
- `tabs.my_decks.selected_deck_id` — Tokyo Prowess (id=17) pre-selects on launch via async-safe `_pending_select_id` pattern
- `tabs.charts.timeframe` + `chart_type` + `format` + `top_n` + `compare_archetypes`
- `tabs.matchup_data.format` + `timeframe` (heatmap top_n / source_filter widgets don't exist on the tab)
- `tabs.scout.days` + `format` + `top` + `target_archetypes`
- `palette_recents` — last 20 palette command IDs

Schema-tolerant (`get(path, default)` always returns the default for missing paths). Reset via palette `> Reset UI state` or Settings tab "Reset UI state" button.

### Command palette
**Ctrl+K** opens `gui/widgets/command_palette.py::CommandPalette`. Fuzzy-searches `gui/widgets/palette_registry.py::PaletteRegistry`, populated at startup by `gui/widgets/_palette_actions.py::register_all`. Categories: TAB / ARCH / DECK / CARD / ACT. Prefixes: `>` actions, `#` tabs, `@` archetypes, `:` decks, `c:` cards. Recents persisted in `ui_state.palette_recents` (top 20, stale entries pruned by `PaletteRegistry.prune_recents`). 80ms debounce on input; `rapidfuzz` is the C-backed fuzzy backend (added to `requirements.txt` for `c:` card-search performance).

---

## 7. KEY FILES

```
# ── Launchers ──────────────────────────────────────────────
run_gui.py                      GUI entry point (--register-tasks mode)
main.py                         CLI entry point
fill_database.py                Standalone DB builder (reads preferences.json)
mcp_server/server.py            MCP server entry (FastMCP/stdio; agent-callable analytics)
mcp_server/tools.py             MCP tool logic (pure, wraps analysis/win_rates.py)
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
analysis/deck_ev.py             Single-deck field-weighted EV (paper + Untapped + SB bumps)
analysis/mulligan_study.py      Monte Carlo mulligan simulator (primer-rule evaluator backend)
analysis/scout.py               Pre-event pilot intel (priority finishers + handle resolution)
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
gui/tabs/tournament_prep.py     Tournament Prep wrapper (composes 6 sub-tabs)
gui/tabs/event_optimizer.py     Event Optimizer sub-tab
gui/tabs/breaker_math.py        Breaker Math sub-tab
gui/tabs/scout.py               Scout sub-tab -- pilot intel + handle linkout
gui/widgets/mulligan_evaluator.py  Test Hand sub-tab + 1000-hand mulligan study dialog
gui/widgets/deck_ev_widget.py   EV vs Field sub-tab
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

### Single-instance enforcement
`gui/single_instance.py::SingleInstanceLock` wraps `QLockFile` with a 30s stale-lock TTL. `run_gui.py` acquires at startup (after `QApplication(sys.argv)` since the error dialog needs an event loop) and releases via `aboutToQuit`. Lock at `data/.run_gui.lock` (gitignored). A second launch attempt shows a `QMessageBox` and exits with code 1. After an ungraceful crash, wait ~30s for the stale-lock to clear before relaunching.

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
| `mcp-builder` | anthropics/skills | Patterns for building MCP servers. Used to build `mcp_server/` (2026-06-11), which exposes the meta DB as agent-callable tools — see `mcp_server/README.md` |

To restore on a fresh clone: `npx skills experimental_install` (reads `skills-lock.json`).

---
*Last documentation update: 2026-05-15 (1:41 AM after huge 5/14 build day) — MTGA live import +
  Match History + Watch Replay + Rank Progression shipped end-to-end. Concrete additions:
  scrapers/mtga_log_parser migrated to resolve_and_save + auto-classification + auto-create-deck fallback;
  db/match_sb_plans.py (per-match SB plan from SubmitDeckReq, alt-art name-collapsed);
  db/match_games.py (per-game stats, classify_game close/blowout/normal);
  analysis/auto_save_deck.find_or_create_deck (alt-art-safe, Limited-skip, sideboard auto-fill);
  analysis/replay_transcript.build_transcript v0.6 (annotations + ClientToGREMessage + opening hand
  with locked-iid pattern + counter-spell look-ahead attribution + scry top/bottom resolution +
  per-game state reset for Arena's reused instance IDs); gui/widgets/deck_match_history.py
  (Match History sub-tab on My Decks, ranked-filter default, mulligan analysis UI);
  gui/widgets/replay_transcript_dialog.py (popup transcript viewer);
  analysis/sb_plan_diff.compare_match_to_canonical (fuzzy archetype matching);
  db/rank_snapshots.py + analysis/rank_tracker.capture_current_rank (dedup on insert,
  Player-prev.log iterated first so latest wins); gui/widgets/rank_progression_dialog.py
  (matplotlib chart, tier-name Y-axis); Dashboard rank label clickable; 3-layer MTGA freshness
  (↻ Sync button + auto-sync on launch + 30s live-tail gui/mtga_log_watcher.py QThread);
  watcher additionally runs _build_missing_transcripts after each parse + as a one-shot
  startup backfill so completed matches in the current Player.log rotation window get
  data/match_replays/<arena_match_id>.json cached BEFORE MTGA overwrites the raw lines
  (5/22; was the silent "Watch replay missing" failure mode);
  db/untapped_decklists.py (Mythic decklist ingestion from local replay corpus). 143/143 tests green.
  As of M1 (2026-05-22), `_build_missing_transcripts` also invokes `analysis.replay_events.build_event_stream` so every newly-cached transcript also lands with the structured `events[]` data layer populated. Existing caches get auto-upgraded via the capabilities check on next read.
  Tomorrow's chain staged in harness/plan-2026-05-16-execution-chain.md
  (crash logger -> MTGA QA -> thread audit -> responsiveness -> Maps deeplink -> transparent overlay).*

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
