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

### Match Replay v0.5 -- look-ahead counterspell targets (2026-05-14)
- [x] **Cast line now carries the countered target.** User pointed out
      that since we're walking the whole log in one pass, we can
      forward-attach the countered card to the original counter-spell
      cast line. Previously v0.4 only suffixed the Countered event;
      the cast line was bare.
- [x] **Implementation: in-place edit of buffered cast line.** When a
      counter spell is cast, we remember `(name, turn_entry, action_idx)`
      in `pending_counters`. When the next Countered event arrives, we
      pop the most-recent entry and mutate the earlier cast line in
      place to append "→ targets: X". Both lines remain (cast + countered)
      so the timeline is intact.
- [x] **Result for vs Kajar G2 T4:**
        You cast Annul → targets: High Noon
        High Noon countered (by Annul)
        Annul resolves
- [x] **133/133 green. Cache cleared.**

### Match Replay v0.4 -- scry top/bottom + counterspell attribution (2026-05-14)
- [x] **Scry top/bottom resolution.** Annotation Scry carries
      details.topIds and details.bottomIds (instance ID lists).
      Resolved to card names: "scry 1 → top: Kaito, Bane of Nightmares".
      Previously just emitted "scry 2" with no detail.
- [x] **Counterspell attribution heuristic.** Arena doesn't emit a
      target annotation when a counter spell is cast (the targeting
      is implicit via UI state). We track recent casts of known
      counter spells (_COUNTER_SPELLS list: Annul, Negate, Spell
      Pierce, Disdainful Stroke, Three Steps Ahead, Tishana's
      Tidebinder, etc.) and tie the next "X countered" event back
      to the most-recent counter spell on the stack: "High Noon
      countered (by Annul)".
- [x] **Target line fallback.** When PlayerSubmittedTargets annotation
      fires but the target instance isn't yet in our grpid map (e.g.
      opp's hidden card just revealed), we emit "→ targets: instance#N"
      instead of silently dropping the line, so the user knows
      targeting happened.
- [x] **133/133 tests green. Cache cleared.**

### Match Replay v0.3 -- draws, mulligans, attackers, bottoming (2026-05-14)
- [x] **ZoneTransfer Draw extraction.** Cards drawn each turn now in
      the transcript: "You draw Bitter Triumph" for your draws (named),
      "Kajar draws a card" for opponent draws (hidden per Arena).
      Fixed "?" attribution issue with default_opp=True fallback on
      _who_for(): for hidden-card events where ownership map is empty,
      assume opponent (always correct since your own cards are in
      gameObjects before they hit any logged event).
- [x] **Surveil + Put + Return + Exile + Sacrifice ZoneTransfer
      categories.** Surveil events ("You surveil → X" when a card you
      see is involved, "Kajar surveils" otherwise). Put (bottoming /
      scry-bottom / hand-to-library): "You bottom/place X". Return,
      Exile, Sacrifice each get their own line.
- [x] **Mulligan keep/mull decisions.** Reads
      ClientToMatchServiceMessageType_ClientToGREMessage messages with
      payload.type=ClientMessageType_MulliganResp -- emits "You KEEP
      hand" or "You MULL". Currently only your decisions (Arena
      doesn't forward opp's mulligan choice to your client).
- [x] **Declare attackers + declare blockers.** Same
      ClientToMatchService walker. SubmitAttackersReq -> "You declare
      attackers: Spyglass Siren, Floodpits Drowner". SubmitBlockersReq
      -> "You declare blockers: Kaito blocks High Noon".
- [x] **RevealedCardCreated annotation.** "Kajar reveal: X" when opp
      reveals a card via mulligan-reveal / Surveil-reveal / etc.
- [x] **Verified vs Kajar Bo3:** Game 1 turn 5 now shows full play
      sequence: "You draw Spyglass Siren, You cast Spyglass Siren,
      Spyglass Siren resolves, token created: Map, 1 counter on
      Floodpits Drowner, You bottom/place Day of Black Sun, You life
      16->14, You play Multiversal Passage, 3 damage -> opponent" --
      complete narrative.
- [x] **Cache cleared** so next Watch Replay click rebuilds with v0.3.
- [x] **133/133 tests green.**

### Match Replay transcript v0.2 -- annotations stream (2026-05-14)
- [x] **Replay transcript now parses `gameStateMessage.annotations[]`.**
      The annotations stream is the authoritative game-event log
      (Arena's own "what happened" log). Built an instance-to-grpId
      map across all gameObjects messages so annotation
      `affectedIds` references can be resolved to card names.
- [x] **Event types extracted** (one human-readable line per event):
      - **ZoneTransfer** with category PlayLand / CastSpell / Resolve /
        Destroy / Countered / Discard / Mill -- "You play Multiversal
        Passage (land)", "You cast Annul", "High Noon countered",
        "Spyglass Siren resolves"
      - **AbilityInstanceCreated** -- "You ability: Kaito, Bane of
        Nightmares" (covers triggered + activated)
      - **PlayerSubmittedTargets** -- "→ targets: <card name(s)>"
      - **DamageDealt** -- "3 damage → opponent"
      - **TokenCreated** -- "token created: Map"
      - **CounterAdded** -- "+1/+1 counter on Floodpits Drowner"
      - **Scry** -- "scry 2"
      - **Shuffle** -- "shuffle library"
      - Life changes (already in v0.1)
- [x] **Verified on Kajar match (id=67):** The Annul-countering-High-
      Noon clutch play is now visible in the transcript, along with
      Floodpits Drowner ETB tokens, Kaito loyalty swings, damage
      exchanges. Real play-by-play.
- [x] **Cache invalidated** (cleared `data/match_replays/*.json`) so
      future Watch Replay clicks rebuild with the v0.2 detail.
- [x] **133/133 tests green** (no test regressions).

### Match Replay transcript popup v0.1 (2026-05-14)
- [x] **`analysis/replay_transcript.build_transcript(arena_match_id)`.**
      On-demand parse of MTGA Player.log + Player-prev.log for one
      match. Captures per-turn active player + life-total changes from
      `gameStateMessage.players[].lifeTotal` diffs. Caches result to
      `data/match_replays/<arena_match_id>.json` so subsequent views
      load instantly (file-per-match, not a new DB table per advisor
      recommendation -- it's slow-path, on-click only).
- [x] **`gui/widgets/replay_transcript_dialog.ReplayTranscriptDialog`.**
      QDialog popup (like the deck-viewer popout) rendered as
      monospace QTextEdit with HTML coloring: red for damage taken
      (life -N), green for healing (life +N), accent for game header.
      Refresh-from-log button forces a re-parse.
- [x] **`Watch replay` button on Match Detail panel.** Enabled when
      a Recent Matches row has `arena_match_id`. Clicking opens the
      transcript dialog for that match.
- [x] **Layout: horizontal splitter on Match History sub-tab.** Recent
      Matches on left, Match Detail (game stats + SB plan + Watch
      Replay button) on right. Splitter is draggable.
- [x] **Scope notes (deferred to v0.2):** Card-cast events (cast which
      spell on which turn) require parsing
      `gameStateMessage.annotations[]` which is a deeper structural
      walk -- v0.1 ships life-trajectory only. Full board reconstruction
      (creatures on each side per turn) requires a state-machine over
      every `gameObject` zone transition, advisor flagged it as 6-10h
      not 3-4h, deferred. Visual board layout view also deferred.
- [x] **Tests:** 4 cases in `tests/test_replay_transcript.py` covering
      cache-path determinism, cached-load, unknown-match-None,
      force-refresh behavior. 133/133 total green.

### Per-game mulligan + life trajectory (2026-05-14)
- [x] **`db/match_games.py` + parser per-game tracking.**
      `mtga_log_parser` now snapshots `lifeTotal`, `mulliganCount`, and
      `turnInfo.turnNumber` from every GameStateMessage per player.
      Captures the min and end-of-game life for both seats plus the
      mull-to (computed `7 - mulliganCount`) and total turn count.
      Stored in `m["per_game_stats"][game_num]` and persisted to
      `match_log_games` (UNIQUE on `match_log_id, game_num`).
- [x] **`classify_game(stat, my_won)` decisive-vs-close-vs-normal.**
      Judged from the WINNER's perspective: `close` = winner ended at
      <=3 life (nailbiter), `blowout` = winner ended at >=15 life
      (never threatened), `normal` = winner ended 4-14. Useful for
      contextualizing matchup data ("I'm 0-3 but all losses were
      close" vs "I'm 0-3 and got blown out three times").
- [x] **`keep_stats_for_deck` mulligan aggregation.** Returns
      keep-7/mull-to-6/mull-to-5/mull-to-4/3-or-less buckets with
      per-bucket WR. Future: compare against
      `analysis/mulligan_study.py` Monte Carlo to validate in-game
      decisions empirically.
- [x] **GUI: extended Match History sub-tab detail panel.** Selecting
      a Recent Matches row now shows per-game W/L + class
      (close/blowout/normal) + T#_turns + mull-to + life endpoints
      alongside the SB plan. Visual example: "Game 1 W &#9679; close
      &middot; T11 &middot; keep 7 &middot; my life 2 / opp life 0".
- [x] **Backfill on existing matches:** 57 per-game stat rows written
      across today's matches. Verified vs Tokyo Prowess matches:
      Rawdogger g1 won at 20 life (blowout), g2 lost at 0 life,
      g3 won at 20 -- mixed outcomes per game now visible.
- [x] **Tests:** 6 cases in `tests/test_match_games.py` covering
      roundtrip, idempotent upsert, classifier (blowout/close/normal),
      and keep-stats aggregation. 129/129 total green.

### Per-game SB plan extraction from Player.log (2026-05-14)
- [x] **`db/match_sb_plans.py` + parser per-game capture.** Each Bo3 Arena
      match emits `GREMessageType_ConnectResp` (game 1 mainboard) followed
      by `GREMessageType_SubmitDeckReq` messages at games 2 and 3 start --
      the SubmitDeckReq carries the player's most-recently-committed
      post-board deck. `mtga_log_parser.parse_log_file` now collects all
      three into `m["per_game_decks"]`. `save_matches_to_db` calls
      `db.match_sb_plans.save_plans_for_match` which diffs consecutive
      games at the CARD-NAME level (alt-art swaps net to zero) and writes
      one row per game transition to the new `match_log_sb_plans` table.
- [x] **GUI surface on Match History sub-tab.** Click a row in Recent
      Matches -> below the table, a "Sideboard plan" detail panel
      renders each game transition with green `+N CardName` (in) and red
      `-N CardName` (out) lists. Falls back to "no SB plan stored" for
      Bo1 / single-game matches / pre-feature imports.
- [x] **Backfill on existing matches:** 14 multi-game matches got 17
      plan rows from today's Player.log. Verified vs Kajar (Azorius
      Aggro): +2 Annul, +2 Deceit, +1 Preacher, +1 Unagi, +1 Tishana,
      +1 Vren in; -1 Cecil, -1 DoBS, -1 Bat, -1 Curiosity, -1 Kaito,
      -3 Hex out. Cleanly matches the user's documented Dimir Aggro SB
      plan vs aggro.
- [x] **Tests:** 7 cases in `tests/test_match_sb_plans.py` covering
      diff correctness, three-game chains, alt-art name collapse,
      idempotent upsert, empty/single-game no-op, unknown-match query,
      per-deck aggregation by opponent. 123/123 total green.

### Auto-create: sideboard capture (2026-05-14, follow-up)
- [x] **find_or_create_deck now accepts sideboard_grp_ids.** Previously it
      wrote `sideboard={}` even though the parser already captured
      `connectResp.deckMessage.sideboardCards` via
      `m["sideboard_card_ids"]`. Now resolves SB grpIds the same way as
      mainboard. On NEW deck creation, SB lands populated. On EXISTING
      matching-archetype deck where SB is empty (typical for an
      auto-imported deck created before this fix), the SB is filled in
      opportunistically. Non-empty SB on existing decks is preserved
      (no stomping of curated lists).
- [x] **Backfilled the 4 pre-fix auto-imported decks:** Dimir Aggro
      (id=18), Izzet Looting (id=19), Bant Rhythm (id=20), Esper Pixie
      (id=21) all got their 15-card sideboards filled from
      sideboard_card_ids of a linked match. Verified Dimir Aggro
      sideboard matches the user's pasted decklist exactly (Annul x2,
      Day of Black Sun x2, Deceit x2, Tishana's Tidebinder x1, etc.).

### Auto-create saved deck on unknown match (2026-05-14)
- [x] **`analysis/auto_save_deck.find_or_create_deck()`.** When
      `mtga_log_parser` writes a match where `classify_my_deck` returns
      None (overlap <70% with every existing saved_deck), the parser now
      falls back to this helper:
      1. Skips Limited events (Sealed / Draft / Cube).
      2. Skips matches with <20 unique observed cards.
      3. Classifies the user's grpIds against meta archetype card lists
         (reusing `classify_opponent_deck`).
      4. If a saved deck with that archetype + format already exists,
         links to it (existing match's my_deck_id gets set).
      5. Otherwise creates a new saved_deck named
         `<archetype> (auto-imported YYYY-MM-DD)` with observed cards as
         mainboard, empty sideboard, "edit My Decks to fill in" note.
      Idempotent on (archetype, format) so re-running the parser doesn't
      duplicate decks. Limited and 'Unknown Archetype' cases are
      intentionally skipped so saved_decks doesn't get polluted.
      `classify_event` moved to `analysis/auto_save_deck.py` (was inline
      in the GUI widget) so headless CLI scrapers don't load Qt.
      Tests: `tests/test_auto_save_deck.py` -- 8 cases. 113/113 green.

### Match History sub-tab on My Decks (2026-05-14)
- [x] **5th sub-tab on My Decks deck-detail panel: "Match History".**
      Shows all match_log rows for the selected deck (filtered by
      `my_deck_id`). Summary header: overall W-L + WR%, plus per-event
      breakdown (Ranked Bo3 / Ranked Bo1 / Unranked / Limited / Other)
      sourced from raw MTGA event_name. Filter dropdown narrows to one
      category. Matchup table aggregates W-L per opponent archetype.
      Recent-matches list shows last 50 with date/event/vs/archetype/
      result/play-draw. Lives at `gui/widgets/deck_match_history.py`.
      Wired into `gui/tabs/my_decks.py` `_on_deck_clicked` so it
      switches with the selected deck.

### MTGA Auto-Import + Match Classification (2026-05-14)
- [x] **MTGA Player.log parser wired into daily background_fill.** Previously
      `scrapers/mtga_log_parser.py` was a manual CLI-only tool; ranked matches
      never showed up in Match Log until the user remembered to run the
      parser. Now it runs every 6 AM (and every other invocation of
      `scripts/run_fill_from_prefs.py`), parsing both Player.log and
      Player-prev.log. Failure path is non-fatal -- if the user doesn't
      have MTGA on this machine, the chain continues.
- [x] **classify_opponent_deck SQL fix.** Query referenced `dc.card_name`
      which doesn't exist on `deck_cards` -- column is `c.name` via JOIN
      to `cards`. The try/except silently returned "Unknown" for every
      opponent, so all 48 historical rows had empty opp_deck despite
      having opp_card_ids. Fixed at `scrapers/mtga_log_parser.py:506-516`.
      Backfill via `--classify-opponents` updated 15 historical rows with
      real archetypes (Gruul Aggro, Izzet Elementals, Golgari Control,
      Simic Rhythm, Azorius Control, Selesnya Aggro, etc.).
- [x] **classify_my_deck schema mismatch + alt-art bug.** The classifier
      queried `card_data.arena_id` which doesn't exist in production --
      the canonical mapping lives in `untapped_card_db.grpid`. Tests
      seeded `card_data.arena_id` directly so the test suite never caught
      this. Also fixed: original `name -> arena_id` dict overwrote on
      duplicate names (basic lands have many printings = many grpids per
      name), causing the deck/observed-set intersection to miss alt-art
      copies. Rewrote to compare by card NAME via reverse `grpid -> name`
      lookup, alt-art-safe. Falls back to `card_data.arena_id` first for
      test compatibility, then `untapped_card_db.grpid` in production.
- [x] **mtga_log_parser migrated from save_match -> resolve_and_save.**
      Now writes with `source='mtga_log'`, auto-classifies `my_deck_id`
      via the fixed classifier, and stores `opp_grp_ids_json` for future
      re-classification. Tokyo Prowess (deck id=17) is auto-linked on
      every match where the user's grpIds overlap >=70% with the saved
      deck.

### Pipeline + Data Freshness (2026-05-14)
- [x] **Spicerack HTTP 400 root-caused + fixed.** Pipeline call passed
      `--format standard` (lowercase) but the Spicerack API requires
      title-case (`Standard`, `Modern`, etc.). `fetch_tournaments()`
      now title-cases at the API boundary so either casing works from
      callers. Probed live with both casings to confirm.
- [x] **Untapped meta_scraper + matchup_scraper + replay_fetcher
      wired into M/W/F pipeline.** Previously only the mythic +
      premium scrapers + match_log writer + decklist populator ran
      automatically; the other three required manual invocation and
      had been stale since 5/10. `scripts/run_fill_from_prefs.py`
      now runs all five Untapped scrapers on M/W/F (replay fetch
      throttled `--top 50` by matches_count to cap network usage
      at ~12.5MB per run).
- [x] **Untapped Premium partial-capture investigated -- not a bug.**
      Of the 5 Bo3 formats targeted, 2-3 return data per run; the
      other 2-3 return HTTP 202 with empty body (insufficient upstream
      sample volume for Alchemy/Historic/Timeless in current meta
      period). Captured behavior in 5/13 6AM run log: Traditional_Ladder
      22 rows (plat=20), Traditional_Explorer 1 row, Alchemy/Historic/
      Timeless all "no data / 202". Behavior is upstream-driven.

### Untapped Tail-Off (low priority)
- [x] **Untapped premium scrape — drop `--last-7-days` from M/W/F cadence.**
      Shipped 2026-05-14: re-pulling without the flag widened Standard Bo3
      from 18 rows → 121 (Platinum 17 → 79, Mythic 0 → 4). The
      `last_7_days` filter was suppressing most upstream data. Pipeline
      change persisted 2026-05-14: `scripts/run_fill_from_prefs.py:96`
      now invokes the premium scraper without `--last-7-days`, so the
      M/W/F automated run inherits the wider window automatically.
- [x] **Untapped mythic decklist ingestion (2026-05-14) — BIG FEATURE
      shipped same day as scoped.** Recon revealed the local replay
      corpus already contains full pre-board mainboard + sideboard as
      `decks[0].deck.mainDeck` / `.sideboard` (lists of grpIds), so
      no new network requests, no cookie-auth, no throttling concern.
      Module: `db/untapped_decklists.py` (extract_decklist_from_replay,
      resolve_grpids, save_decklist, get_decklist, populate_for_short_ids,
      populate_for_all_local_replays). Schema: new `untapped_decklists`
      table with short_id PK + mainboard_json + sideboard_json + archetype
      + fetched_at + source_replay_path. GUI: Ladder tab gained '↻ Fetch
      decklists' button (runs in worker thread); decklist panel below the
      Mythic leaderboard populates from `get_decklist(short_id)` on row
      selection; right-click context menu adds 'Save to My Decks' which
      copies the deck into `saved_decks` for side-by-side EV comparison.
      M/W/F pipeline integration: `scripts/run_fill_from_prefs.py` now
      calls `populate_for_all_local_replays` after the match_log writer.
      Tests: `tests/test_untapped_decklists.py` — 10 cases covering
      grpId aggregation (alt-art collapse), roundtrip, idempotent upsert,
      malformed-replay handling, unresolved-grpId handling, skip-existing.
      First populate against real DB: 98/98 decklists written from local
      replay corpus.
- [x] **Auto-pull replays for current Mythic leaderboard (2026-05-14).**
      The local-only decklist populator only covers historical snapshots.
      Added `scrapers.untapped_replay_fetcher.fetch_for_short_ids()`
      programmatic wrapper (rate-limited 2 req/sec, skips already-cached,
      handles 204 no-content, records errors, optional progress_callback).
      Ladder tab gained "↻ Pull current top 30" button: snapshots the
      currently-displayed leaderboard short_ids → fetches replays from
      Untapped → chains into the decklist populator → status line shows
      combined `fetch + decklists` stats. Network-touching, only fires
      on explicit click. Tests: `tests/test_untapped_replay_fetcher.py`
      — 6 cases with HTTP mocked covering skip-cached, 200-success,
      204-no-content, error path, progress callback, empty input. 105/105
      tests green.
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
