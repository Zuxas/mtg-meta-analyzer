# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-05-01

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
