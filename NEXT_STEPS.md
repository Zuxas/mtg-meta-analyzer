# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-05-12

---

## TOP OF MIND

**May 29 Standard RC DC (Day 1 qualified).** Deck lock window per
post-PT analysis (PT SOS findings 2026-05-03):
- Selesnya Landfall is the data call (63.81% PT WR, best deck)
- Izzet Lessons beats Selesnya 75% but is -WR overall vs Mono-Green field
- Izzet Spellementals is the sleeper: beats Prowess, Mono-Green; even vs Selesnya

**Outstanding from May 11-12 RC:** post-event debrief not yet logged.
Time-sensitive while memory is fresh — log matches, capture which SB plans
worked / didn't, expected vs actual matchups.

---

## OPEN PRIORITIES

### Untapped Follow-Ups (after 2026-05-12 pipeline landed)
- [ ] **Time-series chart of Untapped meta share + WR** — 16 snapshots over
      ~2 weeks. Add as series on existing Charts tab so paper-meta and
      ladder-meta sit side by side. Early-signal use case: "is this deck
      rising on MTGA before paper catches up?"
- [ ] **Opponent archetype on SB plans** — `untapped_sideboard_plans` has
      no opponent reference. Plans are keyed only on the friendly player's
      color combo. To enable per-matchup SB advice, parse the raw replay
      JSON for opponent deck data and write an `opponent_pgid` column.
- [ ] **Finer archetype matching for SB plans** — currently color-only
      (`Azorius Control` → WU pulls in *every* WU plan). Try matching on
      deck_name substring or pass plans through the KNN/NBAC classifier
      using the friendly player's game-1 list.
- [ ] **Card-level Untapped data** — which cards have the highest WR at
      Mythic? `untapped_meta_archetypes.key_cards` is grpid-indexed; joining
      to `untapped_card_db` gives names. Surface in Card Browser or
      slot_analysis substitutes view.
- [ ] **Untapped premium ranks scrape cadence** — `last_7_days` flag has
      tiny samples right now (1-18 rows per tier). Confirm the scraper is
      cycling enough to keep the recent window populated.
- [ ] **Filter SB plans by recency** — drop plans older than N days
      (data is timestamped via `replay.match_timestamp`).

### Sim Integration (cross-repo mtg-sim)
- [ ] Author Standard goldfish APLs for the remaining 6 archetypes
      (Selesnya Landfall, Mono-Green Landfall, Izzet Spellementals,
      Izzet Prowess, Selesnya Ouroboroid, Azorius Tempo).
- [ ] Standard match APLs (not just goldfish) — IMPERFECTION filed
      2026-05-03: goldfish-only Standard APLs are not suitable for
      matchup WR. PT official matrix is the only authoritative source
      until match APLs exist.

### UI/UX
- [ ] Interaction speed — filters update in place (no full refresh)
- [ ] Dashboard + Heatmap empty-state polish
- [ ] Extend icons to remaining text-only buttons (ask_claude / predictions
      / card_browser Search button / h2h / vs-field forms)
- [ ] Global "All Formats" option rollout to Charts / Predictions /
      Card Browser filters (Dashboard already has it).

### Bug Fixes Applied (2026-05-12)
- [x] DD/MM/YY date-sort regressions on `ORDER BY date DESC` — `analysis/deck_analysis.py::get_recent_event`, `gui/widgets/archetype_detail.py::_load_archetype_data`, `scrapers/challenges.py::get_latest_challenge` now normalize mixed DD/MM/YY + YYYY-MM-DD ordering via CASE WHEN

### Bug Fixes Applied (2026-05-03)
- [x] Qt 6.10 crash on exit — QThread destroyed while running (all 13 tabs patched, stop_worker() added)
- [x] Best Deck button used all-time data — matches table DD/MM/YY date comparison bug fixed (_MATCH_DATE_KEY)
- [x] Predictions timeframe selector added (was hardcoded 4 weeks)
- [x] Sync Guides now shows count of added/skipped guides + fetches up to 3 sheet tabs

### Data Sources Added (2026-05-12)
- [x] Untapped.gg scraper pipeline — mythic leaderboard, premium archetype WR/matchup matrices, replay fetcher + sideboard plan extractor, MTGA card db loader. Public endpoints free; premium needs cookies. M/W/F throttling.
- [x] Player handle DB — `scrapers/player_handles.py` discovers top finishers' Twitter/X handles + fetches recent MTG tweets
- [x] NBAC archetype classifier wrapper — `analysis/nbac_classifier.py` calls Videre Project's Naive Bayes API (free, no key)

### GUI Integrations (2026-05-12)
- [x] F5 / ↻ Refresh button in the main header — reloads the current tab's data from DB. Walks nested QTabWidget containers to find leaf tab; calls `reload()` / `refresh()` / known load methods. Useful after CLI DB edits (saved decks / SB plans).
- [x] Untapped Bo3 ladder data wired into Matchup Data heatmap as 4th source. Priority: real★ > scraped > untapped•. `db/untapped_queries.py` aggregates premium view across rank tiers, weighted by `observed_match_count`. Standard / Pioneer only (other formats not on MTGA).
- [x] Bo3 SB Plans tab added to Archetype Detail dialog. Surfaces real game-to-game sideboard diffs from Untapped Mythic-level replays, matched to archetype via color identity (`archetype_colors()` resolves "Azorius Control" → WU, "Mono Green Landfall" → G, etc.). Top section aggregates most-common IN/OUT cards; below shows individual plans.
- [x] Ladder sub-tab added to Meta group. Mythic archetype rollup, Bo1 skill curve (Bronze→Plat WR per archetype + climb delta — positive delta = scales with skill), Mythic top-30 leaderboard. Standard / Pioneer / Historic / Timeless / Alchemy supported.

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
- [x] Update GitHub Actions to Node 24 (checkout@v5, setup-python@v6, github-script@v8) — shipped 2026-05-03
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
