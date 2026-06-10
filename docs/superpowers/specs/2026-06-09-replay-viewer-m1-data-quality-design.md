# Replay Viewer — M1 Data-Quality Fix (design)

Date: 2026-06-09
Status: approved (pending spec review)
Module: `analysis/replay_events.py` (`build_event_stream`, `replay_board_at`)
Related: `docs/superpowers/specs/2026-05-22-replay-viewer-design.md` (original M1–M-future design)

---

## 1. Problem

The M1 event-stream layer (`build_event_stream`) feeds the full-depth replay
viewer (M2 window, M3 board panel, M4 annotations). It has two confirmed
data-quality defects. Both were reproduced against real data, not inferred.

### Bug 1 — Event multiplication / non-monotonic `game_num`

> **Root cause correction (2026-06-09, during implementation).** The dominant
> cause is **not** duplication — it is that `build_event_stream` never scopes
> GameStateMessage / client-message processing to the requested match. It sets
> `target_found` from the room event but then processes **every** GSM in
> **both** log files, including other matches that share the file. Measured for
> one target match: the extractor saw **4005 GSMs / 14 MulliganResp** (all
> matches, both files) instead of the **980 / 4** that belong to the match —
> and the buggy build's `keep_hand(11)+mulligan_decision(3)=14` matched the
> unscoped count exactly. Duplication (below) is a real but secondary effect.
> The fix therefore adds match-scoping **as well as** the idempotent dedup.

`build_event_stream` walks `Player.log` **and** `Player-prev.log` and **appends**
every emitted event to a flat `events[]` list. Two further sources multiply a
single match's events on top of the cross-match pollution above:

1. **Cross-file duplication** — during log rotation a match can be present in
   both `Player.log` and `Player-prev.log` (full copies).
2. **In-file GSM resends** — MTGA re-emits `GameStateMessage`s. Measured: **551
   of 980** GameStateMessages in one live match carried a `gameStateId` that had
   already appeared.

Because the extractor appends rather than keying by identity (unlike the classic
`build_transcript`, which keys `games[n]`/`turns[n]` into dicts and is therefore
idempotent), the event stream is multiplied. Evidence from a cached replay
(`094442b9-…json`, schema 1):

- `game_num` transition sequence: `[1,2,3,1,2,3,1,2,1,2,1,2,3,1,2,1,2,1,2,1,2,3,1,2,3,1]` (26 transitions for a 3-game match)
- `keep_hand` = 27 (expected ≤3 — we only track "you")
- `mulligan_decision` = 9 (expected 1)
- only 3 real `game_end` events, at game_nums 1/2/3

`replay_board_at` currently *compensates* by resetting its instance map on every
`game_num` change — its docstring explicitly describes the oscillation as
expected. After this fix `game_num` is monotonic, so reset-on-change still holds,
but the workaround rationale must be re-documented.

### Bug 2 — Sparse hand / library / graveyard / exile reconstruction

The live log is **977 `GameStateType_Diff` vs 3 `GameStateType_Full`** GSMs. A
Diff message carries the **full current membership of only the zones it
mentions** — e.g. a sampled Diff listed `ZoneType_Hand`=7 and
`ZoneType_Library`=53 objects and **no other zones**.

The extractor builds `current_zones` from whatever zones the message contains,
then runs a "disappeared-instance" sweep (current code lines ~324–336) that pops
**every** tracked instance not present in `current_zones`. On a Diff that only
reports Hand+Library, every battlefield/graveyard/exile instance is wrongly
flagged as having left all zones (`to=None`) and then re-added by a later
message. Battlefield mostly survives because it is reported more often/fully;
hand/library/GY/exile counts churn and are unreliable. This is why M3's board
panel hides those zone counts.

### Supporting log-structure facts (verified against the live log)

- `gameStateId` **resets to 1 at each game start**, each reset marked by a
  `GameStateType_Full` message (observed 431→1 entering game 2, 297→1 entering
  game 3). Therefore game-state identity is `(game_num, gameStateId)`, not
  `gameStateId` alone.
- Client-to-GRE messages (`MulliganResp`, `SubmitAttackersReq`,
  `SubmitBlockersReq`) carry a unique **`transactionId`** (UUID) at the envelope
  level. They have no `gameStateId`.
- A zone is "reported" by a GSM only when its entry includes an
  `objectInstanceIds` key. A zone entry absent from `zones[]` (or lacking the
  key) means "not reported," **not** "empty."

---

## 2. Fix

### 2.1 Bug 1 — match-scoping (primary) + idempotent dedup

**Match-scoping (primary fix).** Track `active_room_match` from every
`matchGameRoomStateChangedEvent`. Skip any GSM / client-to-GRE blob unless
`active_room_match == arena_match_id`. This excludes the other matches that
share the log file (the dominant corruption source) and also makes
cross-match state bleed (life totals, instance maps) impossible.

On top of scoping, make emission idempotent within the match:

- **GameStateMessages:** maintain `seen_game_states: set[tuple[int, int]]`.
  Update `current_game` from `gameInfo.gameNumber` **first**, then compute key
  `(current_game, gameStateId)`. If the key is already in the set, **skip the
  entire GSM** (resend / cross-file copy). Otherwise add it and process. First
  occurrence wins (a resend is an identical state snapshot).
- **Client-to-GRE messages:** maintain `seen_transaction_ids: set[str]`. Skip
  any blob whose `transactionId` is already seen.
- The existing `seen_annotations` set becomes secondary: duplicate GSMs are now
  skipped wholesale, so their annotations never re-reach the annotation loop.

**Rejected alternatives:**
- *Dedup by `gameStateId` only* — collides across games (ids reset per game).
- *Pick the single most-complete match occurrence* — silently loses a game when
  a match is split across the rotation boundary (e.g. games 1–2 in prev.log,
  game 3 in current.log). Idempotent-merge handles resends, the cross-file copy,
  and the rotation split uniformly.

### 2.2 Bug 2 — scope the disappeared-sweep to reported zones

- Compute `present_zones`: the set of normalized zone names for which **this**
  GSM's `zones[]` entry carries an `objectInstanceIds` key (empty list counts as
  reported → authoritative).
- Build `current_zones` from those reported zones (as today).
- Zone-change diffs for instances in `current_zones` are computed as today.
- The disappeared/departure detection only pops + emits a departure for tracked
  instances whose **old zone ∈ `present_zones`** and that are absent from
  `current_zones`. Instances tracked in zones this message did not report are
  left untouched.
- **Hidden-zone ownership (added during implementation).** Library cards and the
  opponent's hand never appear in `gameObjects`, so `instance_to_owner` can't
  attribute them and `replay_board_at` excludes `controller=None` instances —
  leaving library counts near zero. Each zone entry carries an `ownerSeatId`;
  apply it as a **fallback** owner (`setdefault`, so battlefield control from
  `gameObjects` still wins). This is what makes hand/library counts correct for
  both players (verified on real data: you/opp library reach 60, hand 7).

### 2.3 Cache invalidation & capability honesty

- Bump `SCHEMA_VERSION` to **2**.
- The cache-load gate (`build_event_stream`, currently capabilities-only) must
  also require `cached.get("schema_version") == SCHEMA_VERSION`. On a mismatch,
  fall through to rebuild.
- **Serve-stale on rebuild-miss (decision):** if a rebuild is triggered but the
  match is no longer present in the current logs (`target_found` is False),
  return the existing stale cache rather than `None`, so the viewer still opens
  on old matches. Only return `None` when there is no cache at all and the match
  is not in the logs. New/recent matches rebuild cleanly to schema 2.
- **`log_offsets` capability:** today `capabilities.log_offsets` is advertised
  `True` but `log_offset` is always `None`. Set the capability to `False` and
  remove it from the required-capability tuple. (Populating real byte offsets is
  out of scope.)

### 2.4 Out of scope (deferred)

Tap state, +1/+1 counters, auras, combat-damage assignment refinement, and the
M-future Odds Engine. This milestone is strictly data-correctness for the
zones/events already in the M1 contract.

---

## 3. Data contract impact

No new top-level keys. Shapes of `events[]`, `match_meta`, `board_diff`, and
`replay_board_at`'s return are unchanged. The fix changes *values*: fewer,
de-duplicated events; monotonic `game_num`; accurate per-zone counts.
`capabilities.log_offsets` flips `True`→`False`; `schema_version` `1`→`2`.

Downstream consumers to re-verify (no API change, but value-sensitive):
- `replay_board_at` — re-document the reset rationale; behavior unchanged.
- `_extract_key_events` — `mulligan_to_{7-mull_count}` now computes from the
  correct (un-inflated) mulligan count.
- M3 `replay_board_panel` — hidden hand/library/GY/exile counts become reliable.

---

## 4. Testing (TDD)

All via the existing monkeypatch of `_iter_json_blobs` (synthetic blob lists; no
real-log dependency). New tests:

1. **Duplication regression (the missing guard):** feed one match's blob list
   **twice** (simulating two log files). Assert total `events` count, `game_num`
   sequence `[1,2,3]`, and `keep_hand` count are identical to the single-feed
   case.
2. **In-file GSM resend:** repeat a GSM with the same `(game_num, gameStateId)`;
   assert a single emission.
3. **Cross-game `gameStateId` reuse:** game 2 reuses `gameStateId` values from
   game 1 (after a Full reset); assert both games' states are processed (no
   false dedup).
4. **Diff zone scoping:** a Full establishes battlefield+hand+library; a
   following Diff mentions only Hand (a card leaves hand); assert battlefield
   instances are **not** marked gone and hand count is correct.
5. **Client-message dedup:** duplicate `MulliganResp` blobs sharing a
   `transactionId` produce one event.
6. **`mulligan_to_N` correctness** after dedup.
7. **Schema gate:** a cached file with `schema_version: 1` triggers a rebuild; a
   `schema_version: 2` file with valid capabilities is served from cache.
8. **Serve-stale:** schema-1 cache + match absent from logs → returns the stale
   cache (not `None`).

Then run the **full** suite (PowerShell, read exit code — not `| tail`, per the
Windows pytest pipe-truncation gotcha) and **update** any pinned expectations in
`test_board_diff_validity` / board tests that the zone-scoping change shifts.
Expect to edit some pinned values, not only add tests.

---

## 5. Rollout

- Branch: `feat/replay-viewer-m1-dq` (in-place feature branch, **not** a
  worktree — the live `data/` DB and cached replays must stay intact for tests +
  manual smoke).
- After merge: a manual GUI smoke of the board panel on a freshly-rebuilt
  (schema-2) recent match to confirm hand/library/GY/exile counts now render.
