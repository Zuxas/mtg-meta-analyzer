# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-04-07

---

## OPEN — Data Engine
- [ ] Cross-source duplicate detection with confidence scoring
- [ ] Meta change detection (compare two time periods)

## OPEN — Query & Discovery
- [ ] Card-name decklist search (exact + multi-card AND/OR)
- [ ] Global "All Formats" option everywhere

## OPEN — Deck Intelligence
- [ ] Card adoption & progression tracking over time
- [ ] Baseline vs deviation comparison (user list vs stock)
- [ ] Deck role classification (proactive/reactive/combo/tempo)
- [ ] Meta clustering by playstyle
- [ ] Meta-based deck recommendation engine
- [ ] "Why this card?" slot analysis

## OPEN — Testing & Iteration
- [ ] Card swap rationale tracker (why you changed cards)
- [ ] Matchup hypothesis tracker (record + validate theories)
- [ ] Gauntlet builder (auto top decks to test against)
- [ ] Test recommendation engine
- [ ] Testing insights from logged matches

## OPEN — Match Logging Enhancements
- [ ] Compare personal WR vs meta expected WR per matchup
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
