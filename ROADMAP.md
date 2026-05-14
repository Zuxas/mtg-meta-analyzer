# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-05-14

---

## OPEN — Deck Intelligence
- [ ] Meta clustering by playstyle

## OPEN — Query & Discovery
- [ ] Card-name decklist search (exact + multi-card AND/OR)
- [ ] Global "All Formats" option everywhere

## OPEN — Testing & Iteration
- [ ] Card swap rationale tracker (why you changed cards)
- [ ] Matchup hypothesis tracker (record + validate theories)
- [ ] Gauntlet builder (auto top decks to test against)
- [ ] Test recommendation engine
- [ ] Testing insights from logged matches

## OPEN — Match Logging Enhancements
- [ ] Track record by event type (RCQ vs Open vs RC)
- [ ] Trend analysis: personal WR over time, improving/declining matchups
- [ ] Integration with SB advisor: "your WR is low vs X, adjust your plan"

## OPEN — Tournament System
- [ ] Pre-event prep mode (deck + SB guide + expected meta)
- [ ] Round tracking during event
- [ ] Post-event analysis (expected vs actual matchups)
- [ ] Blocking/teammate support math

## OPEN — UI/UX
- [ ] Interaction speed (filters update in place)

## OPEN — Format Expansion
- [ ] Premodern support
- [ ] Format-specific banned lists + archetype dictionaries

## OPEN — Team Collaboration
- [ ] Export/import gauntlet results as JSON (share on Discord)

## OPEN — Packaging
- [ ] PyInstaller .exe packaging + clean machine testing

---
---

## COMPLETED

### 2026-05-13 — Match Log Variant Tracking + Timeline Panel
- [x] `deck_variants` table + 5 additive columns on `match_log` (`my_deck_id`, `my_variant_hash`, `opp_grp_ids_json`, `source`, `backfill_status`) + `arena_match_id` for Untapped dedup
- [x] `analysis/wilson.py` — Wilson score interval + validated / promising / noisy classifier
- [x] `analysis/my_deck_classifier.py` — overlap-score classifier mapping grpIds -> saved_decks.id
- [x] `scrapers/untapped_match_log_writer.py` — ingest MTGA replays into match_log (M/W/F pipeline)
- [x] `scripts/backfill_match_log_decks.py` — auto-resolve historical orphan rows by archetype + date proximity
- [x] `gui/widgets/variant_timeline_panel.py` — per-variant match count, WR, Wilson flag, card-swap delta
- [x] Layout B Option C — right panel replaced by VariantTimelinePanel; orphan banner + OrphanResolverDialog
- [x] Match dialog refactored to saved-deck dropdown via `db.match_log.resolve_and_save()`

### 2026-05-13 — GUI Quick Wins (palette + sticky state)
- [x] **Ctrl+K command palette** (`gui/widgets/command_palette.py` + `palette_registry.py` + `_palette_actions.py`) — fuzzy search across tabs / archetypes / saved decks / cards / actions; prefixes `>` `#` `@` `:` `c:`; 80ms debounce; rapidfuzz backend
- [x] **`gui/state.py` UIState singleton** — debounced JSON persistence (250ms), atomic write via `.tmp`+replace, corrupt-recovery, threading.Timer (no Qt dep so unit-testable)
- [x] **`gui/state_keys.py`** — central registry of 17 dotted-path constants for all persisted slices
- [x] **Sticky UI state** across 5 tabs: Dashboard timeframe; My Decks selected deck (Tokyo Prowess id=17 pre-selects on launch via async-safe `_pending_select_id` pattern); Charts timeframe + chart_type + format + top_n + compare archetypes; Heatmap format + timeframe; Scout days + format + top + target archetypes
- [x] **Tab-bar navigation persistence** — `currentChanged` on top-level QTabWidget writes `LAST_ACTIVE_TAB_PATH`; app reopens on last-used tab
- [x] Settings tab "Reset UI state" button + palette `> Reset UI state` action
- [x] Test infra bootstrapped (no prior tests): pytest>=8.0 added, `tests/test_ui_state.py` (9 tests), `tests/test_palette_registry.py` (20 tests)
- [x] Spec at `docs/superpowers/specs/2026-05-13-gui-palette-sticky-state-design.md`; plan at `docs/superpowers/plans/2026-05-13-gui-palette-sticky-state.md`; 14 commits (`6fd084e..1fdd97f`); branch `feat/gui-palette-sticky-state` merged + deleted

### 2026-05-13 — RC May 29 Prep Toolkit
- [x] Print SB Guide 1-page fix — `_summarize_notes()` clips primer prose to TL;DR per matchup (Tokyo guide 50KB → 12KB)
- [x] Tokyo Prowess saved (saved_decks.id=17) + 17 SB plans + primer prose backfill
- [x] `analysis/deck_ev.py` — field-weighted EV calculator (paper + Untapped Bo3 + SB difficulty bumps)
- [x] EV vs Field sub-tab in My Decks (`gui/widgets/deck_ev_widget.py`)
- [x] Test Hand mulligan evaluator sub-tab + 1000-hand Monte Carlo study
- [x] `analysis/mulligan_study.py` — Monte Carlo simulator reusing primer-rule evaluator
- [x] SCOUT sub-tab in Tournament Prep (`gui/tabs/scout.py`, `analysis/scout.py`) — top-cut pilots + handle resolution
- [x] Untapped follow-ups closed: opponent classifier from MTGA replay log (91% accuracy), KNN-refined SB plan matching (96%), card-level Mythic inclusion, Untapped Ladder Trend chart type
- [x] Master-detail layout for Sideboard Plans tab
- [x] F5 / Refresh button in main header
- [x] Bo3-only data filter applied to Ladder rollup + leaderboard + chart; Br→My columns retained with responsive hide
- [x] 4 project-scoped skills installed (triage-issue, improve-codebase-architecture, grill-me, modern-python) + playwright + mcp-builder
- [x] Hardcoded path scrubbing across 54 scraper files
- [x] Pre-push hook hardened with cookies-file-aware skip-list

### 2026-05-12 — Untapped.gg Pipeline + DD/MM/YY Sort Fixes
- [x] Untapped scraper suite: mythic ladder, archetype meta WR, matchup matrix, MTGA card db, replay fetcher, sideboard plan extractor
- [x] Untapped Bo3 ladder wired into Matchup Data heatmap as gap-fill 4th source
- [x] Bo3 SB Plans tab in Archetype Detail dialog (real game-to-game SB diffs from Untapped replays)
- [x] Ladder sub-tab in Meta group: mythic rollup + Bo1 skill curve + leaderboard
- [x] Player handle DB — top finisher Twitter/X discovery + tweet fetch
- [x] NBAC API classifier (Videre Project) — alternative to local KNN classifier
- [x] DD/MM/YY date-sort regressions fixed in 3 sites (deck_analysis, archetype_detail, challenges)
- [x] MTGDecks + Untapped throttled to Mon/Wed/Fri in `run_fill_from_prefs.py`

### 2026-05-03 — Bug Fixes + Qt 6.10 Compatibility
- [x] Qt 6.10 crash fix: QThread destroyed while running — all cleanup() methods upgraded to stop_worker() (quit+wait+terminate), main_window cleanup loop expanded from 9 to 15 tabs
- [x] Best Deck timeframe bug: matches table DD/MM/YY dates compared as plain strings; _MATCH_DATE_KEY normalization applied to both real matchup and archetype winrate queries
- [x] Predictions tab: timeframe selector added (was hardcoded to 4 weeks), weeks_back now passed to generate_predictions
- [x] Sync Guides: now fetches up to 3 sheet tabs (not just gid=0), shows added/skipped counts in status bar

### 2026-05-01 — Event Hub + CI/CD + Scrapers
- [x] Event Hub tab (Session 1): Search, Calendar, My Events, My Stores, .ics export, MTGO calendar
- [x] Event Hub tab (Session 2): RC countdown, drive time, conflict detection, Spicerack enrichment
- [x] Spicerack historical scraper — tournament + top-8 data
- [x] Event Finder — Wizards GraphQL API, geocode + radius search
- [x] GitHub Actions CI/CD — lint/tests/imports/GUI gates, self-hosted runners, failure reporter
- [x] MTGTop8 date normalization (DD/MM/YY → YYYY-MM-DD)

### 2026-04-08 — Deck Intelligence + Codebase Consolidation + UX
- [x] Card adoption tracking (analysis/card_adoption.py) — week-by-week inclusion rates per archetype
- [x] Baseline vs deviation — Deck Analyzer compares pasted list vs average deck
- [x] Slot analysis (analysis/slot_analysis.py) — role, trend, substitutes, competitors
- [x] Deck recommendation engine (analysis/deck_recommender.py) — "Best Deck" button on Dashboard
- [x] Deck role classification (analysis/deck_roles.py) — Aggro/Midrange/Control/Combo/Tempo column
- [x] Meta change detection (analysis/meta_change.py) — Dashboard "Meta Shift" with share + WR deltas
- [x] Cross-source duplicate detection (analysis/cross_source_dedup.py) — Settings "Scan Duplicates"
- [x] Codebase Phase 1: shared utilities (scrapers/constants, db/helpers, gui/worker_utils, table_helpers)
- [x] Codebase Phase 2: split tournament_prep (1,626→3 files), split win_rates (1,407→3 files)
- [x] Tab consolidation: 13→7 (Meta, Decks, Tournament, Resources merge related tabs)
- [x] UX: tab tooltips, empty states, friendly_error() on 30+ sites, progress bars
- [x] Docs reorganized: CLAUDE.md 680→330, NEXT_STEPS 725→53, ROADMAP 165→101

### 2026-04-07 — Quick Wins + UI/UX Overhaul
- [x] UI/UX overhaul: Inter font, near-black dark theme, Team Resolve branding
- [x] Team Resolve logo: window icon, tray icon, branded header, setup wizard
- [x] Chart readability: sample size + timeframe subtitles on all 6 chart types
- [x] Event peer navigation: "View Event" button in ArchetypeDetailDialog
- [x] Flex slot competition view: Tech Choices tab grouped by role
- [x] Team notes on heatmap cells: right-click context menu, matchup_notes DB table
- [x] MTG rules reference downloaded (Comprehensive Rules + Scryfall rulings/oracle)

### 2026-04-06 — Advanced Analytics (6 phases)
- [x] `analysis/meta_scoring.py` — prep_priority (0-100), classify_status (Pillar/Trap/Underplayed/Fringe)
- [x] `analysis/ratings.py` — Glicko-2 power ratings, weekly periods, 262k+ matches
- [x] `analysis/equilibrium.py` — Nash LP, replicator dynamics, RPS cycles, Monte Carlo
- [x] `analysis/card_embeddings.py` — ModernBERT 768-dim embeddings, 32k cards
- [x] `analysis/cooccurrence_embeddings.py` — Card2Vec on 33k+ decklists
- [x] `analysis/knn_classifier.py` — KNN archetype classifier, hybrid_classify()
- [x] Dashboard: Prep, Status, Rating, Change columns on Win Rate panel
- [x] Card Browser: Similar Cards + Functional Substitutes
- [x] Deck Analyzer: Deck Similarity + auto-classify archetype
- [x] Heatmap: Equilibrium button, timeframe selector

### 2026-03-29/30 — Match Log + Set Analysis + Card Browser
- [x] Match logging: opponent deck, W/L/D, play/draw, game-by-game, notes
- [x] Set Analysis tab: Mythic Spoiler scraper, AI card classification, format legality
- [x] Card Browser: Scryfall query syntax, filters, meta usage, card detail
- [x] Hypergeometric encounter probability in Event Optimizer
- [x] "Collect More Data" button in Settings
- [x] Quick-glance summary bars (reusable SummaryBar widget)
- [x] Share/Import JSON for decks + SB plans

### 2026-03-25/26/27 — Core Infrastructure
- [x] MTGMelee scraper rewrite — real match W/L pipeline (262k+ matches)
- [x] User Preferences System — format selection wired end-to-end
- [x] My Decks tab — CRUD + SB plans + export
- [x] Heatmap rewrite — combined real+scraped data, Overall WR, source indicators
- [x] Archetype normalization — 250+ aliases, card-based dedup
- [x] Dashboard performance: 918 queries → 1, load time 9s → 0.07s
- [x] Worker lifecycle audit — all workers cleaned up properly
- [x] Card image tooltips, URL import, Charts Compare Mode
- [x] Event type presets, x-loss cutoff, day-2 conversion math
- [x] Legacy + Pauper format support
- [x] System tray icon, first-run UAC wizard, consolidated mtg.bat launcher
