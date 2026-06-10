# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-06-04

---

## OPEN — Event Discovery
- [x] **Event Finder UX overhaul** (2026-06-04, branch `feat/event-finder-ux`) — numeric sort on Distance/Entry; new Time column from `scheduledStartTime`; Date column shows "Sat Jun 7" with ISO sort; new "When" filter (`Next 2 wk / 4 wk default / 8 wk / 6 mo / All upcoming`); 300 mi radius option + API limit 500; RCQ row tint replaces foreground accent; right-click row → Open in Google Maps (uses new `venue { city state }` GraphQL field); all filters persisted to `tabs.event_finder.*` UIState keys. 26 new tests; 328/328 green. Plan: `docs/superpowers/plans/2026-06-04-event-finder-ux-fix.md`.
- [ ] **Event Finder bookmarks + calendar export** — saved-events column with star toggle; CSV / `.ics` export. (Scope B from the 6/4 brainstorm; deferred.)
- [ ] **Event Finder dashboard** — saved searches + background polling + Tournament Prep integration. (Scope C from the 6/4 brainstorm; deferred.)

## OPEN — Deck Intelligence
- [ ] Meta clustering by playstyle

## OPEN — Query & Discovery
- [ ] Card-name decklist search (exact + multi-card AND/OR)
- [x] **Global "All Formats" option everywhere** (2026-05-14) — `analysis.win_rates.is_all_formats()` helper rolled across 7 analysis sites + 2 GUI inline-SQL sites

## OPEN — Testing & Iteration
- [ ] Card swap rationale tracker (why you changed cards)
- [ ] Matchup hypothesis tracker (record + validate theories)
- [ ] Gauntlet builder (auto top decks to test against)
- [ ] Test recommendation engine
- [ ] Testing insights from logged matches

## OPEN — Match Logging Enhancements
- [x] **Track record by event type** (2026-05-14) — Match History sub-tab shows per-category breakdown (Ranked Bo3 / Ranked Bo1 / Unranked / Limited / Other) with filter dropdown
- [x] **Mulligan analysis from logged matches** (2026-05-14) — `db.match_games.keep_stats_for_deck` aggregates keep-7 / mull-to-6 / mull-to-5 / mull-to-4 buckets with per-bucket WR; surfaced in Match History sub-tab with reliability coloring + actionable warning
- [x] **Canonical vs Actual SB plan diff** (2026-05-14) — `analysis.sb_plan_diff.compare_match_to_canonical` shows IN-match % colored by reliability under each plan line in Match Detail panel
- [ ] Trend analysis: personal WR over time, improving/declining matchups
- [ ] Integration with SB advisor: "your WR is low vs X, adjust your plan"

## OPEN — MTGA Live Integration (next: 5/16 chain)
- [x] **Auto-import MTGA Player.log into match_log** (2026-05-14) — wired into M/W/F pipeline + auto-sync on GUI launch + 30s live-tail QThread
- [x] **Per-match SB plan extraction** (2026-05-14) — `match_log_sb_plans` from SubmitDeckReq events, alt-art collapsed at name level
- [x] **Per-game stats** (2026-05-14) — `match_log_games` with life endpoints, mull-to, turn count, close/blowout classifier
- [x] **Auto-create saved deck on unknown match** (2026-05-14) — alt-art-safe grpId/name overlap classifier with 70% threshold; creates `<archetype> (auto-imported YYYY-MM-DD)` deck when no existing match clears threshold; sideboard auto-fill on creation + on opportunistic backfill
- [x] **Turn-by-turn replay viewer** (2026-05-14, v0.6) — `analysis/replay_transcript.build_transcript` walks gameStateMessage.annotations + ClientToGREMessage; covers opening hand, mulligans, draws, surveils, scry top/bottom, lands played, casts with countered-target attribution via look-ahead, abilities + targets, declared attackers/blockers, damage, tokens, life trajectory
- [x] **Auto-cache replay transcripts before MTGA log rotation** (2026-05-22) — `gui/mtga_log_watcher.py::_build_missing_transcripts` runs after every parse + once at startup. Eagerly calls `build_transcript` for every completed match in the current rotation window that lacks `data/match_replays/<arena_match_id>.json`. Skips in-progress games. Closes the silent failure mode where the user lost replays because the lazy "Watch replay" path was the only thing that ever wrote a cache.
- [x] **Replay-viewer M1: event-stream data layer** (2026-05-22) — `analysis/replay_events.py::build_event_stream` extracts a flat events[] list with phase/step/priority/stack/board_diff/revealed_cards/shuffle_cause coverage. match_meta header with per-game decklists + key_events_by_turn. schema_version + self-describing capabilities block enable safe migration. Watcher invokes both builders. CLI dump at `scripts/replay_event_dump.py`. 25+ tests covering all M1 acceptance gates including surveil_top/surveil_gy distinction. Zero GUI changes — data layer only. Data contract locked in for future Odds Engine.
- [x] **Replay-viewer M2: full-depth viewer window** (2026-05-24) — `gui/widgets/replay_viewer_window.py` (QMainWindow): left timeline tree (Game→Turn→Phase→Step→Event) + lazy `QAbstractTableModel` event table + kind-filter chips + search proxy + right detail tabs (Event Details / Stack / read-only Notes) + card preview + Jump-To menu + nav buttons + bottom controls (board panel is an M3 placeholder; speed/Animate are M5 placeholders). Qt-free view-model logic in `gui/replay_view_model.py` (fully unit-tested). "Watch (Full)" / "Watch (Classic)" split button from Match History with persisted mode (`tabs.match_history.replay_viewer_mode`). 35 new tests; 270/270 green. Plan: `docs/superpowers/plans/2026-05-23-replay-viewer-m2.md`.
- [x] **Replay-viewer M3: board state panel** (2026-05-25) — `analysis.replay_events.replay_board_at(events, seq)` (per-game zone reconstruction from `board_diff`, never stored) + `gui/widgets/replay_board_panel.py::ReplayBoardPanel` (two-row board: life/mana + Hand/Lib/GY/Exile counts + battlefield thumbnails via card_image_cache + current-card highlight + Show-Board-Changes + hover-full-image via generalized `card_tooltip.install_card_hover`). Driven from `_select_seq`. Built subagent-driven over 5 TDD tasks; 14 new tests; 285/285 green. **Deferred (not in the M1 data contract):** tap rotation, +1/+1 counters, attached auras, combat highlighting (opp combat absent), lands/creatures split — these need an M1 extractor extension and are M4/future. Plan: `docs/superpowers/plans/2026-05-24-replay-viewer-m3.md`.
- [x] **Replay-viewer M4: review annotation** (2026-05-25) — editable per-replay notes persisted to a new `match_log.replay_notes` column (JSON `{text, marks}`, keyed by arena_match_id, stub-row created if the match isn't in the log); ★ Mark-important event toggle (marks feed the Jump-To menu); Markdown export of a replay review (`gui/replay_view_model.replay_markdown`). Event search / kind chips / Jump-To were already shipped in M2. Built subagent-driven over 6 TDD tasks; 15 new tests; 300/300 green. Plan: `docs/superpowers/plans/2026-05-25-replay-viewer-m4.md`.
- [ ] **Replay-viewer: retire classic dialog** — remove the "Watch (Classic)" button + `gui/widgets/replay_transcript_dialog.py` once Full has been the default ~1 week with no regressions (Full shipped 2026-05-24 → revisit ~2026-06-01).
- [x] **M1 data-quality fix** (2026-06-09, `feat/replay-viewer-m1-dq`) — root cause was **missing match-scoping**: `build_event_stream` processed every match's GSMs in both log files (4005 GSMs/14 mulligans vs the real 980/4), not just the dual-log duplication first assumed. Fixes: (1) match-scoping via `active_room_match` + a guard; (2) idempotent dedup — GSMs by `(game_num, gameStateId)`, client msgs by `transactionId`; (3) diff-aware zones — sweep only zones the message reported + attribute hidden-zone instances by zone `ownerSeatId`. `SCHEMA_VERSION` 1→2 + schema gate + serve-stale on rebuild-miss; `capabilities.log_offsets` corrected to `False`. Real-data: game_num `[1,2,3]` monotonic, you/opp library 60 + hand 7. 10 new tests; 338/338 green. Spec: `docs/superpowers/specs/2026-06-09-replay-viewer-m1-data-quality-design.md`. **GUI smoke of board zone-counts still pending.** (Deferred tap/+1+1/auras unchanged — not in this scope.)
- [ ] **Replay-viewer M-future: Odds Engine** — analysis/deck_odds.py + out_calculator.py + line_ev.py consuming the events[] data contract; right-side Odds tab in replay viewer + live overlay mode mirroring Untapped.gg. Deferred — separate spec + plan when ready to start.
- [x] **Rank progression tracking** (2026-05-14) — `rank_snapshots` table + `analysis.rank_tracker.capture_current_rank()` + Dashboard rank label with clickable chart popup + dedup-on-insert
- [x] **Crash logger** (2026-05-15) — `gui/crash_handler.py` with sys.excepthook + qInstallMessageHandler writing to `logs/gui_crash_*.log` and `logs/qt_msgs_*.log`; QApplication-instance guard prevents C++ abort path on early-failure modals
- [x] **Transparent overlay for MTGA** (2026-05-15) — frameless always-on-top + WA_TranslucentBackground + conditional WindowTransparentForInput when locked; Win32 RegisterHotKey listener for true global Ctrl+Shift+M / Ctrl+Shift+L / Ctrl+Shift+Q; horizontal 240×44 compact pip at bottom-right with click-anywhere-to-expand; foreground watcher auto-shows when MTGA or meta-analyzer has focus, auto-hides on alt-tab elsewhere; deck dropdown + matchup dropdown with Auto fallback; record vs archetype + per-game chips; cards-seen-vs-archetype aggregated; notes panel (saved_sb_plans.notes); decklist quick-reference; opacity slider; 8+ state slices persisted
- [x] **Google Maps deeplink for events** (2026-05-17) — right-click event row in Event Hub RCQ search → "Open store in Google Maps" → URL built from `store + lat,lng` (already in event dict). No API key; uses `maps.google.com/maps/search/?api=1&query=`. `gui/tabs/event_hub_tab.py::SearchView._open_in_maps`.
- [x] **Single-instance enforcement** (2026-05-16) — `gui/single_instance.py::SingleInstanceLock` wrapping `QLockFile` with 30s stale-lock TTL; 2nd-launch attempts get a `QMessageBox` and exit; crash-recovery verified end-to-end (Ctrl+C kill + relaunch shows refusal; 31s wait clears stale lock). 6 unit tests.
- [x] **Crash handler BaseException fix** (2026-05-17) — defensive wrappers in `gui/crash_handler.py` changed from `except Exception` to `except BaseException` so KeyboardInterrupt + SystemExit raised inside Python 3.13's buggy traceback formatter (when SIGINT arrives mid-format) don't propagate. 3 regression tests.
- [x] **Thread lifecycle audit** (2026-05-15) — 4 real bugs: dead-coded closeEvent in main_window.py:357 (watcher.stop never ran), tournament_prep.cleanup walked only 2 of 6 sub-tabs, hypotheses + prep_checklist used pre-Qt-6.10 raw blockSignals pattern; all fixed
- [x] **Responsiveness profiling** (2026-05-15) — `_refresh_orphan_banner` cache+invalidate, Watch Replay async via DataLoadWorker, recent-matches table wraps populate with setUpdatesEnabled(False)+setSortingEnabled(False)
- [x] **Force-quit + smart-X-button** (2026-05-15) — Ctrl+Shift+Q global hotkey (Win32 + local ApplicationShortcut fallback), `closeEvent` checks `tray.isVisible()` before hiding; prevents zombie process accumulation when tray icon is hidden
- [x] **UIState atomic-write robustness** (2026-05-15) — switched from tmp+replace (was leaving leftover tail bytes corrupting preferences.json) to truncate+write+fsync with re-read+merge of non-ui_state keys

## OPEN — Puzzle Tool (RC training)
- [x] **Phase 1 — Solve mode + hand-authored seeder** (2026-05-16) — `db/puzzles.py` schema + CRUD, `analysis/puzzles/scene_builder.py`, `gui/widgets/puzzle_scene.py` MTGA-style renderer, `gui/widgets/card_image_cache.py` Scryfall JPEG cache, PUZZLES top-level tab. `scripts/seed_puzzles.py` with 3 hand-authored puzzles + `_card()` assertion against `card_data` so invented cards can't ship.
- [x] **Phase 2 — Scanner + Inbox + Author + Match-History right-click** (2026-05-16) — `analysis/puzzles/scanner.py` walks `data/match_replays/*.json` with 3 heuristics (find_lethal / stabilize / simplified-tempo); regex matches the real transcript format (`You life: 20 → 18 (-2)` and `<OppName> life: ...`). `gui/widgets/puzzle_author_dialog.py` reused by Inbox-promote AND Match-History right-click. PUZZLES tab restructured to `Solve | Inbox` sub-tabs.
- [x] **Phase 3 — Keyword + LLM graders** (2026-05-17, 5 days early vs 5/22 plan) — `analysis/puzzles/graders.py` with `grade_keyword` (rapidfuzz threshold 80, typo-tolerant), `grade_llm` (inline Anthropic claude-haiku-4-5, ~$0.001/grading), and `grade()` dispatcher with fallback chain (llm → keyword → self). Verdict appears as colored chip below author's solution on Reveal; self-grade ✓/✗ buttons remain as override.
- [x] **5 real-data puzzles seeded from cached replays** (2026-05-17) — `scripts/seed_real_puzzles.py` references real `arena_match_id`s (ViewtifulYosh + Drosme), uses verified cards from Tokyo Prowess (saved_decks.id=17), all with `grading_mode='keyword'` so Phase 3 graders auto-grade. `scripts/enrich_puzzle_notes.py` patches notes with GY state + card abilities (until Scene gets a graveyard field).
- [ ] **Phase 4 — Sharing format** (JSON import/export of puzzles) — deferred
- [ ] **Scene enhancement: graveyard zone** (data + render) — currently captured in notes text only

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

### 2026-05-14 / 2026-05-15 — MTGA Live Import + Match History + Replay Viewer
**Huge build day. RC DC 14 days out. Everything below shipped in one session.**

- [x] **MTGA Player.log auto-import** — `scrapers/mtga_log_parser.py` migrated from `save_match` -> `db.match_log.resolve_and_save` with `source='mtga_log'`, auto-classified `my_deck_id`, `opp_grp_ids_json` for future re-classification. Wired into M/W/F pipeline.
- [x] **classify_opponent_deck SQL fix** — was referencing non-existent `dc.card_name`; now JOINs `cards` table for `c.name`. Backfilled 15 historical rows with real archetypes.
- [x] **classify_my_deck schema fix + alt-art bug** — was querying `card_data.arena_id` which doesn't exist in production (lives in `untapped_card_db.grpid`); also fixed name-overwrite bug for basic lands. Rewrote name-based comparison, alt-art-safe.
- [x] **`analysis/auto_save_deck.find_or_create_deck`** — when classifier returns None, auto-creates `<archetype> (auto-imported YYYY-MM-DD)` deck. Skips Limited + <20 unique grpids. Sideboard auto-populated from connectResp.deckMessage.sideboardCards. Backfilled 4 pre-fix decks (Dimir Aggro, Izzet Looting, Bant Rhythm, Esper Pixie).
- [x] **`db/match_sb_plans.py`** — per-match SB plan extraction from SubmitDeckReq events. Diff at card-name level (alt-art swaps net to zero). 17 plan rows backfilled across 14 multi-game matches.
- [x] **`db/match_games.py`** — per-game stats (life_min/end, mull_to, n_turns) + `classify_game(stat, my_won)` returning close/blowout/normal from winner's perspective. 57 stat rows backfilled. `keep_stats_for_deck` aggregates mull buckets.
- [x] **Match History sub-tab** (`gui/widgets/deck_match_history.py`) — 5th sub-tab on My Decks deck-detail panel. Horizontal QSplitter: Recent Matches left, Match Detail right. Summary header + per-category breakdown + filter dropdown (default "Ranked (any)"). Matchup aggregation table. Recent-matches list (top 50). Click a row -> per-game W/L/class/turn/mull/life + SB plan diff + Watch Replay button.
- [x] **`analysis/replay_transcript.build_transcript`** (v0.6) — cached file-per-match transcript at `data/match_replays/<arena_match_id>.json`. Walks gameStateMessage.annotations (ZoneTransfer/AbilityInstanceCreated/PlayerSubmittedTargets/DamageDealt/TokenCreated/CounterAdded/Scry/RevealedCardCreated) + ClientToGREMessage (MulliganResp/SubmitAttackersReq/SubmitBlockersReq). Resets instance_to_grpid + current_turn + prev_life on game change (Arena reuses instance IDs).
- [x] **Counter-spell target attribution via look-ahead** — track pending_counters as (name, turn_entry, action_idx); on Countered event, pop and mutate earlier cast line in-place to append "-> targets: X". Both lines remain.
- [x] **Scry top/bottom resolution** — details.topIds/bottomIds resolved to card names ("scry 1 -> top: Kaito, Bane of Nightmares").
- [x] **`gui/widgets/replay_transcript_dialog.ReplayTranscriptDialog`** — popup QDialog with monospace QTextEdit; HTML coloring for life changes; Refresh-from-log button.
- [x] **`analysis/sb_plan_diff.compare_match_to_canonical`** — fuzzy archetype matching (exact -> normalized -> first-word with W/U/B/R/G excluded); per-transition cards-followed/missing/unplanned with IN-match % colored.
- [x] **Mulligan analysis UI on Match History** — keep-7/mull-to-6/mull-to-5/mull-to-4 buckets with reliability coloring. Yellow warning when mull-to-6 has n>=3 AND WR<30%.
- [x] **3-layer MTGA freshness** — ↻ Sync MTGA button on Match Log toolbar + auto-sync on GUI launch (QTimer.singleShot(500)) + 30s live-tail QThread (`gui/mtga_log_watcher.py`). Clean shutdown via closeEvent. Effective latency: 30s from match end to Match History appearance.
- [x] **`db/rank_snapshots.py`** + **`analysis/rank_tracker.capture_current_rank`** — scans both Player.log + Player-prev.log (older first so latest wins) for rank objects; dedup'd on insert (only inserts when class/level/wins/losses actually changed). Captures constructed + limited.
- [x] **Dashboard rank label** — `⚔ MTGA: Platinum 3 (25-28)` (ranked-only constructed W-L). Underlined + clickable; opens `RankProgressionDialog` with matplotlib chart (tier-name Y-axis ticks, format dropdown). Click refreshes the label first.
- [x] **Spicerack HTTP 400 fix** — title-case `Standard`/`Modern` at API boundary so either casing works from callers.
- [x] **Untapped pipeline expansion** — meta_scraper + matchup_scraper + replay_fetcher (--top 50) + mtga_log_parser + capture_current_rank + populate_for_all_local_replays wired into M/W/F pipeline.
- [x] **Mythic decklist ingestion** — `db/untapped_decklists.py` schema + extract_decklist_from_replay + resolve_grpids + populate_for_short_ids + populate_for_all_local_replays. Ladder sub-tab gets ↻ Cache local + ↻ Pull current top 30 buttons + decklist panel below leaderboard + right-click Save to My Decks.

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
