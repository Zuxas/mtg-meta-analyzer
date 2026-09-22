# CLAUDE.md — MTG Meta Analyzer

Last updated: 2026-09-21 (**Puzzle Trainer T1.1 -- spaced repetition + daily feed SHIPPED** on `fix/data-pipeline-2026-09-20`, spec `docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md`, plan `docs/superpowers/plans/2026-09-21-puzzle-spaced-repetition.md`. Decisions with the user: session with a daily target + auto top-up (C), a ladder for EVERY puzzle (B), and a schedule DERIVED from `puzzle_attempts` -- no new table, no dual-write. `analysis/puzzles/spaced_repetition.py` (pure): `INTERVALS=(1,3,7,14,30,90)`, rung = trailing run of `correct` verdicts, any other verdict resets to rung 0 (due tomorrow), six corrects retire the puzzle; `schedule_for` / `build_session` (due first, most overdue first, then new) / `streak` (consecutive days with attempts >= target, ending today or yesterday). `analysis/puzzles/feed.py` (DB-aware, Qt-free): `todays_feed(category, target, today, top_up=)` -> `Feed(puzzles, done_today, due_count, new_count, generated, remaining, next_due)`; never serves a puzzle attempted today (a miss comes back TOMORROW -- the old queue re-served it immediately, right after the answer was revealed); tops up `drill_outs` only, exactly the shortfall, via `drill_generator.generate_drills` with seed `date*1000 + drills_already_minted_today` (a second top-up the same day continues the sequence instead of replaying the first k), persisted like `scripts/seed_drills.py`; silent when no 60-card decklist is sampleable. `db/puzzles.py`: `get_attempt_log()`, `count_puzzles_created_since()`. Timestamps are UTC `Z`; `attempt_date()` maps them to LOCAL calendar days. Solve tab: `Daily target` spinbox (1-50, default 10, persisted `tabs.puzzles.daily_target`), header `Today n/N · k due · m new · streak s🔥`, done state `Done for today ✓ -- next reviews due <date>` with a **Keep going** button that raises the target in memory only. **Found + fixed on the way:** PyQt6 ABORTS the process on an exception inside a slot (a `str` where `gui.state.PREFERENCES_PATH` expects a `Path` killed pytest silently with exit 127) -- the target-save slot is now guarded; and the feed's due-first order exposed that a BOARD puzzle's `PuzzleSceneWidget` declares a ~720px minimum height, pushing MainWindow to 947px past the 900px GR-7 gate (the old newest-first order happened to land on a boardless drill) -> the board is now inside a `QScrollArea` like the other tall tabs. Live check (read-only): 6 due (the six July attempts were on six distinct puzzles), 43 new, 0 generated, remaining 10. Tests: `test_spaced_repetition.py` (13), `test_puzzle_feed.py` (11), `test_puzzles_tab.py` (+2). Suite **816 passed, 0 skipped**. Also this afternoon: ROADMAP 'Card-name decklist search' was shipped 2026-04-21 (checked off, AND/OR pinned by test).)

Earlier 2026-09-21: (**Date-normalization sweep (NEXT_STEPS #6) DONE** on `fix/data-pipeline-2026-09-20`, while the full MTGTop8 backfill runs: every inline `CASE WHEN instr(date,'/')...` copy (14 SQL sites across `analysis/win_rates.py` (`_DATE_KEY`/`_MATCH_DATE_KEY`/`_dt_to_db_str`/`_parse_match_date`), `card_adoption.py` x2, `scout.py` x2, `deck_analysis.py` x2, `cross_source_dedup.py` (+ its Python `_normalize_date` copy), `scrapers/challenges.py`, `gui/tabs/dashboard.py`, `gui/widgets/archetype_detail.py` x2, `gui/tabs/ask_claude.py`, `gui/tabs/set_analysis.py`, `gui/tabs/search.py` (+ its Python `_to_sortable` copy), `scripts/generate_site_data.py`) now uses `db.helpers.SQL_NORM_DATE`, and every `since`/`until`/bucket literal beside them went from `%Y%m%d` to ISO in the SAME edit (a half-migration returns an empty result, not an error -- `card_adoption` compares the SQL key in Python). `analysis/field_optimizer.py`'s two sites lived in `_legacy_unused_compute_deck_ev_moved_to_deck_ev_module` (191 lines, zero callers) -> deleted. `gui/tabs/search.py`'s query builder lifted out of the worker closure as `_deck_search_sql()` so the ISO bounds are testable; the date inputs are no longer compacted. WHY: the census (read-only) showed `events.date` 2,278 ISO + 4,926 dd/mm/yy, `matches.event_date` 320k ISO + 10k dd/mm/yy, and `guides.date` 754/754 **dd/mm/yyyy** -- the inline 2-branch copies read a 4-digit year as `'20'+'20'` = 2020 (the two guides sites already carried a hand-patched 3-branch variant). `tests/test_date_normalization_sweep.py` (19): one tmp-DB fixture with ISO + dd/mm/yy + dd/mm/yyyy rows exercises every site end-to-end (16 were RED on the old code via the dd/mm/yyyy row) plus a multi-line-aware regex guard that no `CASE WHEN instr(..date..,'/')` copy remains (probe-verified) and a pin that `cross_source_dedup._score_confidence` still treats the three shapes of one date as equal. Live-DB equivalence (read-only, one transaction per table): `replace(SQL_NORM_DATE,'-','') <> old` = **0** on 7,244 events / 330,491 matches / 754 guides; positive control: variant A on guides = 752/754 wrong. Suite **783 passed** (+ `test_drill_generator::test_generation_is_deterministic` deselected: it samples the LIVE `decks` table `ORDER BY id DESC` and the backfill inserts between its two calls -- pre-existing, passes when nothing is writing). The 06:00 pipeline's log now reads `[prefs] Active formats: modern, standard, pioneer, legacy, pauper` and `scrape_state.json` has all five per-format entries (07:03) -- Bug 1 + Bug 3 verified in production. **Crash-log litter fixed:** `tests/test_crash_handler.py` set `crash_handler._LOG_DIR` to ITSELF (a no-op stub), so every suite run appended an empty `=== <ts> ===` header to the real `logs/gui_crash_<today>.log` (8 today); now `tmp_path` + an assertion the header lands there. **Live-DB test guard** (`tests/conftest.py::_no_live_db`, the DB analogue of the network guard): every test gets an EMPTY tmp `DB_PATH`/`ARCHIVE_PATH` unless `@pytest.mark.live_db`; because ~25 modules capture `DB_PATH as CENTRAL_DB_PATH` at import, the fixture sweeps `sys.modules` for captured copies on the way in and restores them on the way out (a module first imported inside a guarded test would otherwise keep the tmp path forever). It exposed **15 tests silently reading the live DB** (9 `test_mcp_server`, 3 GR-4 auto-populate, 2 MainWindow min-height, the `is_all_formats` regression) and **3 that were skipping instead of testing** (`test_conversion` reference case, both drill seeds) -- all now explicitly `live_db` (21 tests). `test_generation_is_deterministic` wraps its two calls in one `BEGIN` read snapshot so a concurrent scrape cannot flake it (3/3 green under the running backfill). Suite **789 passed, 0 skipped**. `tests/test_live_db_guard.py` (4).)

Earlier 2026-09-21: (**Two crashes surfaced by the first real `fill_database.py` run, both fixed** on `fix/data-pipeline-2026-09-20`. **(1) `data/preferences.json` was corrupt** -- valid JSON + a stale tail, `formats` gone -- written at 03:50 DURING the test suite. Root cause: `UIState` saves via a `threading.Timer`; `tests/test_ui_state.py` monkeypatches `PREFERENCES_PATH` to a tmp file but a test that sets state without `flush()` leaves a timer that fires AFTER teardown restores the real path (every dashboard test does the same through the format combo -> `UIState.set`); several such timers racing `open('w')` with PER-INSTANCE locks wrote a shorter payload over a longer one. Reproduced. This is the most likely mechanism behind the July `formats` loss too. Fix: process-wide `_FILE_LOCK`, atomic `.tmp` + `os.replace()` (the old 'leftover tail bytes' comment blamed tmp+replace -- it was this race), `UIState.cancel_all_pending()` over a weakref registry, and an AUTOUSE `tests/conftest.py` fixture that cancels pending saves after EVERY test. File restored from the 11:17 backup; corrupt copy kept as `preferences.json.bak-<stamp>-corrupt`; a full suite run now leaves it intact (verified). **(2) `fill_database.py` step 3 raised `ImportError: cannot import name 'HEADERS' from 'scrapers.mtgtop8'`** -- `scrapers/backfill.py` imported a name that `mtgtop8` stopped exporting in `a397da8` (2026-07-01) and never used it; nothing imported `backfill` at test time, so the 3-year backfill has been unrunnable for 11 weeks independently of Scryfall. Fixed + `tests/test_scraper_imports.py` (every real `scrapers/` module imports; the 46 `_*.py` one-off scripts are excluded). That test then hit the stdout double-wrap in `scrapers/mtgmelee_scraper.py` (closed pytest's capture) -> swept for good: `db/helpers.py::force_utf8_stdio()` (in-place `reconfigure`) replaces the six remaining unguarded sites (`main.py`, `mtgmelee_scraper.py`, `scripts/analyze_duplicates.py`, `scripts/backfill_fingerprints.py`, `scripts/sync_archetypes.py`, `analysis/query.py`; scripts call it AFTER their `sys.path` insert) and `fill_database.py` / `run_fill_from_prefs.py` delegate; `tests/test_stdio_hygiene.py` AST-scans main/fill_database/run_gui/scrapers/scripts/analysis/db and rejects any unguarded module-level re-wrap. Suite **740 passed, 0 failed**. `fill_database.py` relaunched 2026-09-21 ~04:20: step 3 confirmed running (modern, standard, pioneer, legacy, pauper; cutoff 2023-09-22) -> `logs/fill_database_2026-09-21.log`. **EV field-share fallback (NEXT_STEPS #8) shipped:** `deck_ev._default_field_shares(format, con=)` -> `(shares, source)`; when the 14d `decks` window is empty it falls back to matches-derived field shares from `conversion_by_archetype`; `compute_deck_ev` reports `field_source` (`explicit` | `decks-14d` | `matches-14d`), shown in the EV widget subtitle; 4 tests. **The 04:20 backfill run then "completed" in 39 min with exit 0 after a DNS blip** -- `_scrape_year_page` treated ANY fetch failure as `hit_cutoff=True`, so every remaining year/format finished in seconds at +0 (Modern got +101 events / +1,116 decks before the blip). Fixed: `BackfillFetchError` + same-page retry (4 attempts, 30/60/120s) then abort the format; `fill_database.main()` prints `*** BACKFILL INCOMPLETE ***` and exits 2 when any format failed. **Bigger finding while adding Pauper's ids: `YEAR_META` was WRONG for Pioneer/Modern/Legacy 2022-2025** (extrapolated from Standard; e.g. Modern 2025 = 310, live = 315). An unknown id makes MTGTop8 serve the format's CURRENT listing, so every historical backfill of those years re-listed the current year and stored nothing -- why Modern has 959 events to Standard's 4,070. No cross-format pollution (probed). Now `fetch_year_metas()` parses the live format page's 'All YYYY Decks' links; the table (rewritten from live, incl. pauper + vintage) is a fallback and a staleness warning. 11 tests in `tests/test_backfill_resilience.py`. **Then:** `db/scrape_state.py` write made locked + atomic (same race class as UIState); `backfill._process_event` now stores an event only if FULLY fetched (event page + every deck page), else rolls it back (`_delete_event`) -- `existing_ids` would otherwise skip a partial event forever; `run_backfill` tolerates isolated event failures but aborts the format after 5 consecutive (outage), summary carries `event_failures`; 25 zero-deck / card-less mtgtop8 events (22 from the blip, 3 older) deleted from the live DB for re-fetch. **Test hygiene:** `tests/conftest.py` blocks real network access at DNS unless `@pytest.mark.network` -- a `test_backfill_resilience` fixture with an unstubbed `_get` had scraped 20 real Vintage events (199 decks, complete) into the live DB; kept. Suite **761 passed, 0 failed** incl. the live Pinecone tests (skip without a key). **Pagination bug (pre-existing):** `_scrape_year_page` returned only NEW events, so a page of already-known events was indistinguishable from an empty page and `run_backfill` ended the year after two such pages -- Modern 2026 Jan-Aug was never fetched (pages 1-2 are always known from the daily scrape). Now the page also reports every id it saw; a year ends only on cutoff, an empty page, a repeated page (MTGTop8 serves the last page past the end) or `MAX_PAGES_PER_YEAR=400`. 2 tests; suite **766 passed**. FULL backfill relaunched ~07:05 with `POLITE_MAX_REQUESTS_PER_RUN=200000` (rate gate unchanged) -> `logs/fill_database_2026-09-21_full.log`; baseline in the session scratchpad: mtgtop8 events per year showed Modern 2026+2023 only, Pioneer/Legacy/Pauper 2026 only.)

Earlier 2026-09-21: (**CHAPIN_METRICS.md Task 2 -- conversion ratio + the Cascade status** on `fix/data-pipeline-2026-09-20`: new `analysis/conversion.py::conversion_by_archetype(format, since, until=, min_players=16, cut=8, con=)` -> `{arch: {field_share, top_share, conversion, match_wr, matches, events, events_total, ci_low, ci_high}}` -- field AND top cut from the `matches` table only (never `decks`: top-cut biased, different scraper's labels); top cut approximated by win count per event, flat top-8, no tiebreakers/drops/byes (a signal, not a standing); Wilson CI via `analysis.wilson.wilson_bounds`; dates via `SQL_NORM_DATE` (the reference filtered `LIKE '____-__-__'` and silently dropped every dd/mm/yy row). Ported from `scripts/data_health_report.py` and verified **digit-for-digit** against it on the same DB; the script now delegates to the module (output byte-identical). `meta_scoring.classify_status(share, wr, conversion=None)` returns **`Cascade` `#e67e22`** when share >= 3%, conversion <= 1.02 and 48% <= WR <= 52% (Chapin IC-02: popular because it is popular); the 4 original statuses and the 2-arg call are unchanged. `score_standings(..., conversions=None)` plumbs it; the dashboard computes conversions in `_load_panel_data` (worker; 0.3s typical, 1.8s All-Time/all-formats) so the Win Rate panel's Status column shows Cascade, with a tooltip explaining the ratio (`_status_tooltip`). **The doc's fixture table is stale by one scrape**: it was computed on the 09-19 DB (106 qualifying events); today's DB has 112 (Boros 9.55/11.94/1.25 vs 9.63/12.50/1.30) -- the live test pins to the doc within scrape-drift tolerance and asserts the flagged set {Jeskai Blink, Izzet Prowess, Goryo's Vengeance, Amulet Titan} exactly. 10 tests in `tests/test_conversion.py`; suite **578 passed, 0 failed**. **Task 3 -- Bo3 match math (MG-12) also shipped:** new pure `analysis/match_math.py` -- `match_winrate(p1, q) = p1(2q-q^2) + (1-p1)q^2`, `implied_q(p1, P)` (closed-form '+' root of the quadratic; `P` at p1=0.5), `required_q(p1, target)` (None when q would exceed 1); Chapin's three worked cases reproduce to 3dp, round-trips + boundaries tested. `deck_ev.compute_deck_ev(..., use_match_math=False)`: default path is the old flat bump (unchanged numbers, one release); `True` applies the sideboard bump to the post-board game WR `q` implied by the observed match WR and recomposes the Bo3. **Game 1 is held at the observed match WR** on every row (scraped rows are match-level only; p1/q are not separately observable); the GLOBAL G1 prior from `match_log` (`_game_one_prior()`, 56.9% n=109) is reported as `g1_prior` for the UI, not used per row. Every row now carries `math` ('flat-bump'|'implied-q'), `p1`, `implied_q`, `required_q_for_even`. EV widget: new **'Q for 50%'** column (only for matchups still under 50% post-board; tooltip = the sentence RC prep wants) + G1 prior in the subtitle. **Honest magnitude on real data** (Esper Blink, matches-derived Modern field): flat vs math differ 0-0.5pp per matchup, field-weighted WR identical at 2dp -- the refinement the doc predicted, not a headline. Note: `_default_field_shares` (decks-derived, 14d) is EMPTY for Modern until the MTGTop8 backfill runs, so `compute_deck_ev` errors on Modern decks without explicit `field_shares`; the matches-derived `conversion_by_archetype` field shares are a working substitute (follow-up: fall back to them). 24 tests in `tests/test_match_math.py`; suite **602 passed, 0 failed**.)

Earlier 2026-09-20: (**Data-pipeline fixes, Bug 2 of `docs/prompts/DATA_PIPELINE_FIXES.md`** on `fix/data-pipeline-2026-09-20`: **Scryfall bulk API changed shape** (~2026-07-26) -- the `/bulk-data` index dropped `download_uri`+`size` for `jsonl_download_uri` (gzipped JSONL, `application/gzip`, no Content-Encoding) + `compressed_size`; `scrapers/scryfall.py::download_bulk_data` raised `KeyError: 'download_uri'`, which was fatal inside `fill_database.py` step 2 so steps 3-6 (incl. the 3-year MTGTop8 backfill) **never ran**, and card data went 8 weeks stale. Fix = `_pick_bulk_download()` (prefers `jsonl_download_uri`, falls back to legacy `download_uri`, raises naming the keys present) + `_stream_to_json_array()` (gunzip -> validate one object per line -> single JSON array; on-disk format UNCHANGED so `_build_bulk_cache`/`enrich_cards` are untouched; writes `BULK_PATH+'.tmp'` then `os.replace()` so a failed download cannot leave a truncated 200 MB file) + `_ProgressReader`; `scryfall_meta.json` now also records `format` + `card_count`. `fill_database.py::main` wraps steps 2 and 5 in `_run_optional()` -- Scryfall is enrichment, a failure warns and continues (KeyboardInterrupt still propagates). **Second, undocumented crash fixed in the same file:** module-level `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)` orphaned the previous wrapper, whose `__del__` closed the shared buffer -- any caller that had already wrapped stdout (the scratch backfill runner, pytest capture) died with `ValueError: I/O operation on closed file` (this morning's `logs/backfill_mtgtop8_2026-09-20.log`). Now `_force_utf8_stdio()` calls `reconfigure()` in place. Verified: real download 24 MB gz -> 204 MB array, **38,906 cards**, no `.tmp`, `_bulk_is_fresh()` True, `_get_bulk_cache()` 40,256 variants; 8 new tests in `tests/test_scryfall_bulk_download.py`; suite **527 passed, 1 failed** -- the failure (`test_is_all_formats.py::test_regression_archetype_trend_all_returns_data`, `fmt='all'` -> 0 rows while `standard` has rows) is PRE-EXISTING (stash-confirmed) and smells like the mixed `dd/mm/yy`/ISO date comparison that Bug 3 targets. **Still open from the same doc:** Bug 1 code work (loud defaulted-vs-configured warning in `load_formats`, dedupe with `fill_database._load_formats` into `db/helpers.py`, GUI `formats` write path, tests) and Bug 3 / `CHAPIN_METRICS.md` Task 1 (per-format freshness guard). Data state today: Modern match rows are flowing again after the `formats` config repair (11,218 in 2026-09); **Pioneer has zero `matches` rows since 2026-05** even after a 20-page melee pass, so melee has nothing for it -- the unblocked MTGTop8 backfill (step 3) is the untested source. `.gitignore` now covers `data/preferences.json.bak-*` + `_claude_probe*.py`. **Bug 1 (same doc) also shipped, same branch:** ONE implementation of the active-format decision -- `db/helpers.py::load_active_formats(prefs_path, log=print)` + `DEFAULT_FORMATS` -- and both drivers (`fill_database._load_formats`, `scripts/run_fill_from_prefs.load_formats`) delegate to it. A fallback never looks like a setting: missing file / malformed JSON / no `formats` key / empty list / non-list all print `[prefs] WARNING: <reason> -- DEFAULTING to standard only. Modern/Pioneer will not be scraped. Fix: ...` before the `[prefs] Active formats:` line. **The GUI write path that lost the key was NOT Settings** (it does write `formats`) -- it was `gui/state.py::UIState._save_now`, which merged its LAUNCH-TIME snapshot (`disk.update(self._prefs)`) over the file, so a freshly saved Settings format selection was reverted by the next debounced UI-state save (reproduced), and an unreadable file at both load and save time produced a `ui_state`-only file. UIState now owns ONLY `ui_state`: disk is the source of truth for every other key, the snapshot is just the fallback when disk is unreadable. `run_fill_from_prefs.py` also carried the stdout double-wrap crash at import; fixed with in-place `reconfigure()`. 11 new tests (`tests/test_active_formats.py` 9 + 2 in `test_ui_state.py`); suite **538 passed, 1 failed** (same pre-existing `test_is_all_formats`). Follow-up, NOT done: 4 more module-level `sys.stdout = TextIOWrapper(...)` sites (`analysis/query.py`, `main.py`, `scripts/analyze_duplicates.py`, `scripts/backfill_fingerprints.py`) have the same import hazard -- sweep them the same way. **Bug 3 / `CHAPIN_METRICS.md` Task 1 (per-format freshness guard) shipped, same branch:** `db/helpers.py::normalize_event_date()` (Python) + `SQL_NORM_DATE` (SQL template, `.format(col=...)`) both yield ISO `YYYY-MM-DD` for `YYYY-MM-DD` / `dd/mm/yy` / `dd/mm/yyyy`; `analysis/deck_ev.py` refactored onto it (output byte-identical). New `analysis/data_health.py::format_freshness(formats=None, con=, today=)` -> `{fmt: {last_match_date, last_event_date, matches_30d, matches_prev_30d, days_stale, status}}` with fresh (<10d) / stale (10-30d) / dead (>30d or 0 rows in 60d), MAX() over normalized dates only, junk rows ignored; live DB 0.7s. Dashboard: freshness chip (`QLabel#freshnessChip`, green/amber/red, tooltip = `describe_freshness`) beside the format combo, computed in `_load_panel_data` (worker thread) and applied by `_apply_freshness`; when the selected format is dead, a red banner (`QLabel#staleBanner`, new `theme.ERR_BG`) appears on ALL THREE panels + the chart area; the 'all' view reports the worst format and lists dead ones. `scrape_state.json` is per-format: Qt-free `db/scrape_state.py` (`read_scrape_state` / `write_scrape_state(status, error, fmt)` / `format_scrape_state(fmt)` -> `scope: format|global`), old flat shape still read + written for the global fields, `gui/tray_icon.py` delegates; **the scheduled driver now records a per-format outcome** (`run_fill_from_prefs.record_format_outcomes`) -- it never wrote scrape state before, which is why the file only ever reflected GUI runs. **Also fixed:** `win_rates._archetype_trend_from_matches` filtered `format='all'` literally (the fallback path the earlier is_all_formats fix missed) -- this was the `test_is_all_formats` failure, NOT a date bug; it surfaced only because Standard's decks table thinned out. 40 new tests (`test_data_health.py` 23, `test_dashboard_freshness.py` 4, +1 driver, +1 fallback); suite **568 passed, 0 failed**. Live freshness 2026-09-20: Modern/Standard/Legacy fresh (last 09-13), Pauper fresh (09-19), **Pioneer dead (134d, last 2026-05-09)**. Follow-ups: ~18 more inline `CASE WHEN instr(date,'/')` copies (win_rates `_DATE_KEY`/`_MATCH_DATE_KEY`, scout, field_optimizer, card_adoption, dashboard recent, archetype_detail, ...) still produce compact `YYYYMMDD` -- migrate to `SQL_NORM_DATE` one call site at a time (each needs its `since` literal switched to ISO); Modern/Standard/Legacy all stopping at 09-13 while Pauper reaches 09-19 is worth a melee check.)

Earlier 2026-07-11: (**GUI polish Wave C — arc COMPLETE, all 9 gripes closed** on `bob/bob-20260710-231652-ed02`: **GR-3** compact 32px icon-only chart toolbar (objectName-scoped QSS `QToolBar#mplNavToolbar`) + shared `_place_legend()` putting every multi-series legend OUTSIDE the axes (entry-per-series, `ncol=ceil(n/10)` so Top-N=20 doesn't collapse the axes) + `constrained_layout` (all sticky `tight_layout()` calls removed); **GR-6** Decklist sub-tab rebuilt as `gui/widgets/decklist_pane.py::DecklistPane` — type groups w/ counts (read-only card_data), mana-curve mini-bar, pips, card-hover; "(auto-imported <date>)" display-stripped, DB rows byte-identical; **GR-7** boardless scenes (drill_outs) render question-card layout via `puzzle_scene.is_boardless()` + splitter collapse, board puzzles unaffected; **min-height** EventWidget/SettingsTab/DeckAnalyzerTab QScrollArea-wrapped — MainWindow minimumSizeHint ~1460→746px. Suite **515 passed, 2 skipped** (+40). Known NEW finding (pre-existing, FIXED 2026-07-12 cc90c75): settings.py "Storage" QGroupBox never added to a layout — wired into the scroll content; renders for the first time. GUI polish handoff `../harness/handoffs/mta-gui-polish-2026-07-10.md` EXECUTED.)

Earlier 2026-07-11: (**GUI polish Wave B** on `bob/bob-20260710-231652-ed02`: **GR-4** CHARTS auto-generates last-used/Meta-Share and MATCHUP DATA auto-loads cache on first show (one-shot `showEvent` guards, async, no double-fire); **GR-2** matchup columns fill the viewport (0 dead gutter, 48px floor + scrollbar) with unique middle-out-elided headers + full-name tooltips via new `gui/widgets/header_elide.py`, legend on FlowLayout (HeatmapTab min-width ~1660→~520px); **GR-8** new additive `theme.winrate_bg_n(wr, n)` alpha-ramps cell tint by sample size (floor 70 at N=0, opaque N>=20; `winrate_bg`/`fg` untouched + test-pinned), N in cell tooltips, low-N legend key. 31 new tests; suite **472 passed, 2 skipped**; independent verifier 9/9 gates + refute-council 0/3. Known: 23 archetype headers hit a geometric ceiling (unique stubs + tooltips by design); app min-height ~1460px root-caused to `event_optimizer.py::EventWidget` (un-scrolled, 3 tab levels deep) — deferred. Test-infra rule: Qt 6.10 kills pytest if a QThread worker is still running at teardown — drain workers before `cleanup()`.)

Earlier 2026-07-11: (**GUI polish Wave A** on `bob/bob-20260710-231652-ed02`, from the 9-gripe handoff `../harness/handoffs/mta-gui-polish-2026-07-10.md`: **GR-1** maximize-on-first-launch + persisted window geometry (`ui_state` WINDOW_GEOMETRY/WINDOW_MAXIMIZED, off-screen rects clamped to connected screens, synchronous flush in `cleanup()`) + dashboard filter row wraps via new `gui/widgets/flow_layout.py::FlowLayout` (1200x700 safe) + Win Rate archetype column un-elided (1:2:1 panel stretch); **GR-9** summary strip relabeled "Top meta share (<window>): ..." and fixed to pick the true meta-share leader (max appearances, not points-sorted `standings[0]`); **GR-5** heatmap toolbar grouped into labeled Sources|Analysis|Export clusters with separators, wrapping between clusters at narrow widths, header button renamed "Reload Tab". Independent verifier + 3-seat refute-council + live 1200x700/maximized screenshots; suite **441 passed, 2 skipped** (+29 tests). Waves B/C pending — see ROADMAP.)

Earlier 2026-06-19: (**5th MCP tool `search_strategy_docs`** on `feat/strategy-doc-search`: semantic search over the `../mtg-sim/docs/` strategy corpus (17 curated archetype audits/oracles/rules refs → 284 chunks) via **Pinecone integrated inference** (Pinecone hosts the embedding model; upsert raw text, query raw text — no separate embedding key). Pure chunking + result-shaping in `mcp_server/strategy_search.py` (heading-split + size/overlap, archetype/doc_type metadata from filename); thin lazy Pinecone adapter in `mcp_server/pinecone_index.py` behind `get_index()`; key from `config.ini [pinecone]` (env override `PINECONE_API_KEY`) via `mcp_server/config.py`; ingest CLI `scripts/ingest_strategy_docs.py`; thin `@mcp.tool` wrapper that returns a structured `index_unavailable` error (server + other 4 tools unaffected) when no key/index. **STATUS: code-complete + offline-verified (382 tests green), but the LIVE gate is UNVERIFIED** — the Pinecone connectivity spike (Task 0) and the live ingest + acceptance query (Task 7, "double strike delirium prowess" → Izzet Prowess audit) were NOT run because no Pinecone API key is available. The actual Pinecone SDK calls (`create_index_for_model`/`upsert_records`/`search`) have never executed. **To finish:** add a key to `config.ini [pinecone]`, run `python scripts/ingest_strategy_docs.py`, then `pytest tests/test_strategy_search_live.py`. Spec: `docs/superpowers/specs/2026-06-19-strategy-doc-search-design.md`; plan: `docs/superpowers/plans/2026-06-19-strategy-doc-search.md`.)

Earlier 2026-06-18: (**Replay zone-tracking fix** on `feat/replay-zone-tracking`: the last open half of the M1 data-quality work. `build_event_stream` treated every MTGA `GameStateMessage`'s `zones[]` as a complete snapshot, but the game sends mostly partial `GameStateType_Diff` messages (measured **1395 Diff : 5 Full**), so any zone a diff omitted got its instances wrongly evicted (~50k spurious evictions/match) — Hand/Lib/GY/Exile read ~0. Fix = new pure `analysis.replay_events.reconcile_zones()` that reconciles membership **per `zoneId`, only for zones present in each message** (membership-then-evict, so a library→hand draw reads as a MOVE). Hidden-zone cards (your library, opp hand/library — absent from `gameObjects`) are attributed to the zone's `ownerSeatId`, so **both seats'** zone counts are accurate. MTGA reuses instanceIds across games, so zone tracking is cleared at each `gameNumber` change to force the new game's opening Full to re-sync (verified: zones conserve ~60/seat in **both** games). `SCHEMA_VERSION` 2→3 + new `zone_counts` capability auto-rebuilds stale caches. Board panel header now shows Hand/Lib/GY/Exile (was Battlefield-only). Real-data verify across both games: library ~49-50 decreasing from 53, all zones populate. **Still deferred** (not in the `events[]`/`board_diff` contract): tap-state, +1/+1 counters, auras, combat highlighting. 11 new tests; full suite **364 green**.)

Earlier 2026-06-18: (**CI hardening**: the two `self-hosted` CI jobs in `.github/workflows/ci.yml` (`gui-imports`, `predictions-gate`) had **never run** — they only triggered on `pull_request` (this repo merges locally, never via PRs) and the runner (`NETWORK SERVICE`, `C:\Program Files\Python313`) was never provisioned: no pip, no PyQt6, `MTG_META_DB` unset. Confirmed via a throwaway `workflow_dispatch` env-dump job on the runner. Fix: **`gui-imports` moved to hosted `ubuntu-latest`**, runs on push/PR, installs `requirements.txt`+`PyQt6`+Qt libs (`libegl1 libgl1 libxkbcommon0 libdbus-1-3`), headless via `QT_QPA_PLATFORM=offscreen`, **pinned to Python 3.12** (lxml 5.3.0 has no cp313 wheel → source build fails on 3.13). **`predictions-gate` removed** (needs the local DB; can't run on a hosted runner). Self-hosted runner dependency dropped; the runner service can be left registered but is now unused. Both CI + tests workflows green on `c9b8dc7`. Also restored the **local dev env** the same day — a 6/16 event had wiped pip + all deps from both Python 3.13 installs; reinstalled into the shared user-site without admin (see §2 *Python interpreter layout*); 355 tests green.)

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
  **Puzzle Trainer v0 — Track T1 (2026-07-03):** new `drill_outs` category —
  hypergeometric "odds to hit an out" drills grounded in real decklists
  sampled from `mtg_meta.db` (attribution in `notes`; house rule 8).
  `analysis/puzzles/drill_generator.py` (raw / scry-keep-or-bottom / compound
  templates, all 5 difficulty tiers) + `scripts/seed_drills.py`
  (`python -m scripts.seed_drills --count 40 --replace`). New exact-number
  grader `graders.py::grade_number` (`grading_mode="number"`) — accepts the
  [exact, looks×outs-shorthand] band ±3pp; fixes fuzzy keyword false-positives
  on short numbers. Solve tab has a "🎲 Outs math" filter. Gates T1-G1
  (solver vs independent oracle + scipy) + T1-G2 green. Spec:
  `../harness/specs/2026-07-03-puzzle-trainer-v0.md`.
  **Track T2 (2026-07-03, goldfish slice):** sim-mined `find_lethal` puzzles.
  `mtg-sim/scripts/mine_lethal_puzzles.py` mines "you have lethal this turn —
  find the line" positions (play-dependent lethal, engine-`run_combat` oracle,
  replay-gated); `scripts/import_lethal_puzzles.py` -> `puzzle_inbox` (scene +
  line in `evidence`). The Inbox Promote path now prefers an embedded scene
  (`_prefill_from_evidence` in `gui/tabs/puzzles.py`; optional pre-fill kwargs
  on `PuzzleAuthorDialog`) so synthetic candidates promote into solvable
  Solve-tab puzzles without a cached replay. 42 candidates from a 500-game run.
  **Track T3 (2026-07-03) — Glicko-2 puzzle ratings.** Each attempt is a
  one-game Glicko-2 match (correct=win / incorrect=loss / partial=draw). New
  `puzzle_ratings` table + `get_rating`/`upsert_rating` in `db/puzzles.py`;
  `analysis/puzzles/rating_loop.py` reuses `analysis.ratings._update_rating`
  (no reimplementation), cold-starts each puzzle's mu from its difficulty stars
  (`1500+(d-3)*150`), updates user + puzzle simultaneously. Solve tab shows the
  solver's rating + last-attempt delta in the session line
  (`_record_and_next`, best-effort try/except). Gates T3-G1 (matches
  `_update_rating` on literal-input reference) + T3-G2 (survives restart) green;
  `tests/test_puzzle_ratings.py` (11) + GUI smoke in `test_puzzles_tab.py`.
  Known limit (tracked): rating farmable on re-attempt — IMPERFECTIONS
  `puzzle-rating-farmable-on-reattempt`. **Puzzle Trainer v0 COMPLETE.**
  **T1.1 spaced repetition + daily feed (2026-09-21):** the Solve tab serves
  `analysis/puzzles/feed.py::todays_feed` -- overdue reviews first (ladder
  1/3/7/14/30/90d derived from `puzzle_attempts`, a miss resets to tomorrow),
  then new puzzles, up to a persisted daily target; outs drills are
  auto-generated when the feed runs short. Header shows `Today n/N`, due/new
  counts and the streak; done state offers **Keep going**. Board scrolls.
- **System tray:** Team Resolve logo + green/orange/red status dot, close-to-tray, Run Now menu
- **F5 / ↻ Reload Tab button** in branded header — reloads current tab's data from DB (walks nested QTabWidgets to find leaf, calls reload/refresh). Renamed from "Refresh" in Wave A (GR-5) so the dashboard filter-row "Refresh" is the only Refresh-labeled control.

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

## Verification & Hot-Zone Protocol

- **State verification first.** Before starting any work, state how you will verify it.
- **Verify after.** After finishing, run that verification and report the results -- evidence, not just assertion.
- **Hot zones require sign-off.** Before changing any code in a hot zone, ASK first and explain the blast radius (what breaks if it's wrong, and how far it reaches). Hot zones in this project: the live `mtg_meta.db` schema and write paths, the scrapers, and the MTGA log parser (`mtga_log_parser.py`). Blast radius = corrupted tournament/meta data feeding every downstream analysis.
