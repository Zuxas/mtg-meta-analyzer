# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-05-03

---

## OPEN PRIORITIES

### Deck Intelligence
- [x] Meta clustering by playstyle (Dashboard → Clusters dialog)

### Query & Discovery
- [x] Card-name decklist search (Deck Search → Cards filter, AND + OR)
- [x] Global "All Formats" option (Dashboard). Broader rollout to Charts
      / Predictions / Card Browser filters is the next step.

### Sim Integration
- [x] Standard-format support end-to-end (format dropdowns,
      cross-tab format_hint, fuzzy match lookups, Top-N field,
      sim history)
- [x] Standard goldfish auto-detect (Dimir Midrange Standard wired;
      future mtg-sim goldfish APLs pick up automatically)
- [ ] Author Standard goldfish APLs for the remaining 6 archetypes
      (cross-repo mtg-sim authoring)

### Match Logging
- [x] Event-type summary, trend chart, SB Advice, card-swap tracker

### Testing & Iteration
- [x] Matchup hypothesis tracker (Tournament → Hypotheses)

### Tournament System
- [x] Pre-event prep checklist (Tournament → Prep Checklist)
- [x] Generate Prep Package HTML export (Event Optimizer)
- [x] Round tracking during event (Match Log live event banner)
- [x] Post-event analysis (Match Log → Post-Event dialog)

### UI/UX (audit rollout)
- [x] All 8 audit fixes shipped (colors / spacing / empty state / headers
      / density / dialog sizes / icons / StatusRow helper)
- [x] Deck legality watchdog, card-trend sparkline, similar-decks click
- [ ] Interaction speed — filters update in place (no full refresh)
- [ ] Dashboard + Heatmap empty-state polish
- [ ] Extend icons to remaining text-only buttons (ask_claude / predictions
      / card_browser Search button / h2h / vs-field forms)

### Bug Fixes Applied (2026-05-03)
- [x] Qt 6.10 crash on exit — QThread destroyed while running (all 13 tabs patched, stop_worker() added)
- [x] Best Deck button used all-time data — matches table DD/MM/YY date comparison bug fixed (_MATCH_DATE_KEY)
- [x] Predictions timeframe selector added (was hardcoded 4 weeks)
- [x] Sync Guides now shows count of added/skipped guides + fetches up to 3 sheet tabs

### Packaging
- [ ] PyInstaller .exe packaging + clean machine testing

---

## RECENTLY COMPLETED (2026-05-01)

### Event Hub (competitive event management)
- [x] Event Hub tab (4-view container: Search, Calendar, My Events, My Stores) — replaces EventFinderTab
- [x] DB tables: `event_bookmarks`, `store_bookmarks` in mtg_meta.db
- [x] Calendar view — monthly grid, colored chips by event type, premier events 2026 hardcoded
- [x] My Events — status/notes/result/deck editable inline, .ics export for Google Calendar
- [x] My Stores — bookmark stores, quick-filter to store's events
- [x] MTGO calendar integration — live ICS feed, colored by event type
- [x] RC prep countdown banner — days to next regional championship, urgency color coding
- [x] Drive time estimation — heuristic tooltip on Dist column (55mph avg + 30min overhead)
- [x] Conflict detection — orange banner when two bookmarked events share a date
- [x] Post-event Spicerack enrichment — right-click past attended events, pull top-8, save to notes

### CI/CD + Infrastructure
- [x] GitHub Actions CI/CD for both repos (lint + tests on ubuntu-latest, sim/GUI gates on self-hosted)
- [x] Failure reporter: auto-creates GitHub issues on CI failure, deduplicates recurrences
- [x] Self-hosted runners registered on Windows box (both repos)

### Scrapers
- [x] Spicerack historical scraper (`scrapers/spicerack_scraper.py`) — tournament + top-8 data
- [x] Event Finder (`scrapers/event_finder.py`) — Wizards GraphQL API, geocode + radius search

### Data Quality
- [x] MTGTop8 date normalization — `scrapers/mtgtop8.py` now converts DD/MM/YY → YYYY-MM-DD at extraction; consistent with mtgdecks + mtgmelee scrapers; PT Strixhaven data lands correctly

### Open
- [ ] Update GitHub Actions to Node 24 (actions/checkout@v4, setup-python@v5, github-script@v7) — mandatory before 2026-06-02
- [ ] Event Hub Session 3 — format health dashboard, team events view, competitive history analysis

---

## RECENTLY COMPLETED (2026-04-08)

### Deck Intelligence System
- [x] Card adoption tracking (analysis/card_adoption.py) — week-by-week inclusion rates
- [x] Baseline vs deviation — Deck Analyzer compares your list vs average deck
- [x] Slot analysis (analysis/slot_analysis.py) — role, trend, substitutes, competitors
- [x] Deck recommendation engine (analysis/deck_recommender.py) — "Best Deck" button on Dashboard
- [x] Deck role classification (analysis/deck_roles.py) — Aggro/Midrange/Control/Combo/Tempo on Dashboard

### Meta & Data
- [x] Meta change detection (analysis/meta_change.py) — Dashboard "Meta Shift" upgraded
- [x] Cross-source duplicate detection (analysis/cross_source_dedup.py) — Settings "Scan Duplicates"
- [x] Personal WR vs meta expected — already implemented in Match Log

### Codebase Consolidation
- [x] Phase 1: scrapers/constants.py, db/helpers.py, gui/worker_utils.py, gui/widgets/table_helpers.py
- [x] Phase 2: tournament_prep.py split (1,626→136+486+1,038), win_rates.py split (1,407→1,116+125+188)
- [x] Docs: CLAUDE.md 680→330 lines, NEXT_STEPS.md 725→53, ROADMAP.md 165→101
- [x] Root scripts moved to scripts/

### UX Improvements
- [x] Tab consolidation: 13→7 (Dashboard, Meta, Decks, Search, Tournament, Resources, Settings)
- [x] Tab tooltips on all tabs
- [x] Empty states with helpful guidance (Match Log, Heatmap)
- [x] friendly_error() — 30+ error sites now show user-friendly messages
- [x] Indeterminate progress bars on Heatmap + Event Optimizer

### UI/UX Overhaul + Branding (2026-04-07)
- [x] Inter font, near-black theme, Team Resolve logo everywhere
- [x] Chart readability subtitles, event peers, flex slots, team notes
