# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-05-14

---

## TOP OF MIND

**May 29 Standard RC Cincinnati (Day 1 qualified).** Deck lock: **Izzet
Prowess (Worldly Council "Tokyo" list)**. Saved as `saved_decks.id=17`
with 17 SB plans (Nick's primer + Tokyo SB map). Current field-weighted
EV vs 14d Standard meta: **53.6%** (Spellementals worst -10.8pp,
Golgari best +24.5pp Easy SB bump).

**Status:** Skipping RC Cincinnati 5/15-5/17. Focus is RC DC 5/29-5/31
(15 days out as of 2026-05-14). Practice match data on Arena is the
freshest input to the variant-tracking pipeline; Sync Untapped after
play sessions to populate Match Log.

---

## OPEN PRIORITIES

### RC Prep Follow-Ups
- [ ] Side-by-side deck comparison (Chapin radar overlay) — useful if Tokyo
      slot becomes uncertain after another data refresh.
- [ ] RC-realistic field model — replace 14d paper-meta default in
      `analysis/deck_ev.py` with an RCQ-weighted blend (recent RCQ top-8s +
      Untapped Mythic), since RC fields differ from MTGO/online.
- [ ] Sideboard quick-reference printout — 1-page exportable card (PDF
      or PNG) of the 12-matchup SB grid for Tokyo Prowess.

### Sim Integration (cross-repo mtg-sim)
- [ ] Author Standard goldfish APLs for the remaining 6 archetypes
      (Selesnya Landfall, Mono-Green Landfall, Izzet Spellementals,
      Izzet Prowess, Selesnya Ouroboroid, Azorius Tempo).
- [ ] Standard match APLs (not just goldfish) — IMPERFECTION filed
      2026-05-03: goldfish-only Standard APLs are not suitable for
      matchup WR. PT official matrix is the only authoritative source
      until match APLs exist.

### UI/UX
- [x] **GUI ergonomics — Direction A SHIPPED 2026-05-13** —
      Ctrl+K command palette + sticky state across Dashboard / My Decks / Charts / Heatmap / Scout.
      Spec: `docs/superpowers/specs/2026-05-13-gui-palette-sticky-state-design.md`.
      Plan: `docs/superpowers/plans/2026-05-13-gui-palette-sticky-state.md`.
      Branch: `feat/gui-palette-sticky-state`.
- [ ] Direction C arc — design language pass + tab reorganization.
      Drive priorities from one week of palette-recents data + sticky-state usage.
      Spec to be written after 2026-05-20.
- [x] Defer-card-registration polish — `register_card_entries` now scheduled
      via `QTimer.singleShot(0, ...)` in `MainWindow.__init__` so first paint
      isn't blocked by the ~120ms 32k-card iteration. Shipped 2026-05-13.
- [x] Card-slug collision — `_palette_actions._card_slug()` helper extracted;
      `[:60]` truncation dropped so DFC/split/Adventure names with shared
      prefixes no longer collide in palette IDs. New test
      `tests/test_palette_actions.py` (3 cases). Shipped 2026-05-13.
- [x] Sub-tab persistence bug fix — `MainWindow._on_top_tab_changed` only
      wrote the top-level label; sub-tab clicks (DECKS/MY DECKS, META/CHARTS,
      etc.) persisted nothing. Replaced with `_compute_active_tab_path()` +
      `_on_active_tab_changed` wired to every nested QTabWidget. Verified via
      manual smoke (close + relaunch returns to leaf path). Shipped 2026-05-13.
- [ ] Interaction speed — filters update in place (no full refresh)
- [ ] Dashboard + Heatmap empty-state polish
- [ ] Extend icons to remaining text-only buttons (ask_claude / predictions
      / card_browser Search button / h2h / vs-field forms)
- [x] **Global "All Formats" option rollout (2026-05-14).** The "all" option
      existed on Dashboard / Charts / Predictions dropdowns but the underlying
      queries filtered `WHERE lower(format) = lower('all')` and returned zero
      rows. Added `analysis.win_rates.is_all_formats()` helper recognizing
      None / "" / "all" / "All Formats" / "(any)" / "any" (case-insensitive).
      Patched 7 analysis sites + 2 GUI inline-SQL sites (Charts archetype
      dropdown, Dashboard top-finishes panel). Card Browser's "(any)" sentinel
      was already a legality filter, out of scope. Regression test confirms
      `get_archetype_trend(arch, format_name='all')` now returns cross-format
      data (was 0). `tests/test_is_all_formats.py` covers the helper + the
      trend regression. 89/89 tests green.

### Untapped Tail-Off (low priority)
- [x] **Untapped premium scrape — drop `--last-7-days` from M/W/F cadence.**
      Shipped 2026-05-14: re-pulling without the flag widened Standard Bo3
      from 18 rows → 121 (Platinum 17 → 79, Mythic 0 → 4). The
      `last_7_days` filter was suppressing most upstream data. Pipeline
      change persisted 2026-05-14: `scripts/run_fill_from_prefs.py:96`
      now invokes the premium scraper without `--last-7-days`, so the
      M/W/F automated run inherits the wider window automatically.
- [ ] **Untapped mythic decklist ingestion — BIG FEATURE, scoped 2026-05-14
      end-of-night, build tomorrow.** Pull canonical decklists for
      top-30 mythic players into a new `untapped_decklists` table via
      cookie-authed API (recon first turn — `/api/v1/deck/<id>` likely;
      fallback to upload-log replay parse). GUI: decklist panel below
      Mythic leaderboard, right-click "Save to My Decks" copies into
      `saved_decks` for comparison. M/W/F pipeline integration. ~3-4h.
- [ ] Filter SB plans by recency — drop plans older than N days
      (data is timestamped via `replay.match_timestamp`).

### Bug Fixes Applied (2026-05-14)
- [x] **Dashboard "Win Rate Over Time" chart x-axis scrambled.** Cause:
      year was stripped from date labels (`w[5:]`) then matplotlib used
      first-archetype's insertion order as categorical axis, so 2025 data
      appeared after 2026. Fix: parse to real datetime, use
      `matplotlib.dates` formatter, show `YYYY-MM-DD` when data spans years,
      `MM-DD` otherwise. Also relaxed `n>=3` per-bucket filter to `n>=1`
      (short windows were dropping most archetypes). `gui/widgets/chart_canvas.py`.
- [x] **Win Rate Over Time is now the Dashboard default.** One-line change
      in `gui/tabs/dashboard.py:225`. Popularity Over Time still one click away.
- [x] **Mythic leaderboard deck linkout 404.** First URL pattern
      `/profile/<user_id>/decks/<short_id>` returned 404; correct pattern is
      `mtga.untapped.gg/decks/<short_id>` (no profile prefix). Fixed in
      `db/untapped_queries.untapped_deck_url`.
- [x] **Match Log first-launch crash post-schema-upgrade.** Worker thread
      hadn't run the migration when `_refresh_orphan_banner` SQL fired on the
      GUI thread → `no such column: backfill_status`. Defensive
      `_ensure_table()` call at top of `_refresh_orphan_banner`. Shipped
      late 2026-05-13 / early 2026-05-14.
- [x] **"May 11-12 RC" memory hallucination cleanup.** Memory blocks across
      `harness/MEMORY.md`, `mtg-meta-analyzer/NEXT_STEPS.md`, the
      variant-tracking spec, and the pre-authored chain all referenced a
      May 11-12 RC that was never on the calendar. Corrected by referencing
      the canonical Google Sheet calendar where only RC DC 5/29-5/31 has
      Flight+Hotel=yes. Cleaned across all docs 2026-05-14.

### GUI Integrations (2026-05-14)
- [x] **Mythic leaderboard deck linkout.** Ladder tab's Mythic
      leaderboard rows are now interactive: double-click opens that
      player's deck on Untapped.gg in your default browser; right-click
      gives "Open deck on Untapped.gg" + "Copy deck URL".
      `gui/tabs/ladder_meta.py`; URL builder in
      `db/untapped_queries.untapped_deck_url`.

### Bug Fixes Applied (2026-05-13)
- [x] Print SB Guide blew past 1 page after primer-prose backfill — `_summarize_notes()` in `gui/tabs/my_decks.py` strips `---` prior-notes appendage, prefers `PLAN:` markers, caps at 170 chars on word boundary. Tokyo guide: 50KB → 12KB, longest notes block 165 chars

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

## RECENTLY COMPLETED (2026-05-13)

### Match Log — Variant Tracking
- [x] **Match Log refresh — auto-import + variant tracking + Timeline panel.**
      Schema: `deck_variants` table + 5 additive columns on `match_log`
      (`my_deck_id`, `my_variant_hash`, `opp_grp_ids_json`, `source`, `backfill_status`)
      plus `arena_match_id` for Untapped dedup.
      Ingest: `scrapers/untapped_match_log_writer.py` writes match_log rows
      from local `data/untapped/replays/` (wired into M/W/F via
      `scripts/run_fill_from_prefs.py`). Manual dialog refactored to a saved-deck
      dropdown via `db.match_log.resolve_and_save()`.
      Backfill: `scripts/backfill_match_log_decks.py` auto-resolves unambiguous
      historical rows by archetype + date proximity; ambiguous -> orphan.
      UI: Layout B Option C (right panel replaced by `VariantTimelinePanel`
      -- matchup-stats table + SB Advice + trend chart removed, reversible via
      git history), variant column on table, Sync Untapped button, orphan
      banner + `OrphanResolverDialog`.
      Spec: `docs/superpowers/specs/2026-05-13-match-log-variant-tracking-design.md`.
      Plan: `docs/superpowers/plans/2026-05-13-match-log-variant-tracking.md`.
- [x] **Variant-tracking cosmetic followups (2026-05-14).** Format-filtered
      saved-deck dropdown in `_MatchDialog` (now reloads on format change via
      `_repopulate_my_deck`); inlined trivial `_load_variants` wrapper in
      `VariantTimelinePanel` to call `get_variants_for_deck` directly; removed
      unused `skipped_already_resolved` counter from
      `scripts/backfill_match_log_decks.py` (SELECT already filters resolved
      rows, so counter was always 0).

### RC May 29 Prep Tooling
- [x] Tokyo Prowess saved as `saved_decks.id=17` + 17 SB plans with
      primer prose backfill (`scripts/backfill_prowess_primer_notes.py`)
- [x] **EV vs Field** sub-tab in My Decks (`analysis/deck_ev.py` +
      `gui/widgets/deck_ev_widget.py`) — field-weighted WR with per-matchup
      breakdown, source color-coding, low-N flagging. Lives in own module
      to avoid win_rates ↔ field_optimizer circular import.
- [x] **Test Hand** sub-tab in My Decks (`gui/widgets/mulligan_evaluator.py`)
      — primer-rule mulligan evaluator with KEEP/MARGINAL/MULL verdict by
      play-draw and matchup.
- [x] **1000-hand mulligan study** (`analysis/mulligan_study.py` + dialog) —
      Monte Carlo over primer's 5 matchups × play/draw, ~12k hands per
      run. Tokyo Prowess: 86.2% keep-on-7 overall.
- [x] **SCOUT** sub-tab in Tournament Prep (`analysis/scout.py` +
      `gui/tabs/scout.py`) — top-cut pilots playing target archetypes in
      last K days, repeat-offender ranker, right-click open decklist or
      @handle on x.com. Handles from `data/player_handles.json`.

### Untapped Follow-Ups (closed)
- [x] **Time-series chart of Untapped meta** — "Untapped Ladder Trend"
      chart type with Bo3 Plat/Diamond/Mythic lines per archetype
      (`gui/tabs/charts.py` + `chart_canvas.plot_untapped_trend`).
- [x] **Opponent archetype on SB plans** — `scrapers/untapped_opponent_classifier.py`
      parses MTGA replay log (GREMessageType_GameStateMessage gameObjects),
      writes `opponent_archetype` + `opp_grp_ids_json` columns. 40/44
      classified (91%).
- [x] **Finer SB plan matching via KNN** — `friendly_archetype` column on
      `saved_sb_plans` (47/49 = 96% classified from game-1 deck), surfaced
      via `db/untapped_queries.get_sideboard_plans_for_archetype` opponent
      filter dropdown in Bo3 SB Plans tab.
- [x] **Card-level Untapped Mythic data** — `db.untapped_queries.get_mythic_card_inclusion`
      adds "Mythic % (N=X)" column to Average Deck tab with ↑/↓
      tech-divergence arrows.

### GUI / UX
- [x] F5 / ↻ Refresh button in main header (`gui/main_window.py::_refresh_current_tab`) —
      walks nested QTabWidgets to find leaf, calls reload/refresh
- [x] Master-detail layout for Sideboard Plans tab — compact pilot list +
      detail panel showing G1→G2 / G2→G3 transitions
- [x] Bo3-only data for Ladder rollup + leaderboard (filtered by
      `Traditional_<format>` source), Bronze→Mythic columns retained with
      responsive hide of Br/Si/Go on narrow viewport
- [x] Bo3-only Untapped Ladder Trend chart

### Skills + Tooling
- [x] 4 project-scoped skills installed (`triage-issue`,
      `improve-codebase-architecture`, `grill-me`, `modern-python`)
- [x] Playwright + mcp-builder skills added (optional tier)
- [x] Hardcoded path scrubbing across 54 scraper files (now uses
      `Path(__file__).resolve().parent.parent` pattern)
- [x] Pre-push hook hardened with cookies-file-aware skip-list and
      tightened COOKIES regex word boundaries

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
