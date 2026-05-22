# Full-Depth Replay Viewer — Design

**Date:** 2026-05-22
**Author:** brainstorming session with the pilot
**Status:** approved by user, ready for implementation plan
**Driver:** The MTGA Watch Replay path lost the pilot a recent replay because the lazy
on-click cache was overwritten by log rotation before they viewed it. The 5/22
auto-cache patch (`gui/mtga_log_watcher.py::_build_missing_transcripts`) closes
that hole — every completed match now lands as a permanent JSON. With persistence
solved, the viewer itself is the next bottleneck: the current dump-text dialog
is too shallow to support real "relive the game" review.

## Problem

The existing `gui/widgets/replay_transcript_dialog.py` renders the cached
transcript as a single QTextEdit dump grouped by turn. That format conceals
exactly the information a competitive player needs when reviewing a match:

- **No phase or step granularity** — the post-combat main 2 mistake looks
  identical to the precombat main 1 mistake because both collapse into a turn
  bucket.
- **Priority passes invisible** — the moment the pilot held priority and
  chose not to act is the single most reviewable decision point in MTG, and
  it's nowhere in the output.
- **Stack contents never shown** — when a counter war happens, the viewer
  shows individual cast lines but not the stack state between them.
- **Board state never rendered** — the pilot can't see "I had Lightning Strike
  in hand at T4 and chose not to cast" because no zones are visualized.
- **Actions are pre-formatted strings** — they can't be filtered, can't be
  linked back to a source annotation, and can't be re-rendered for any
  structured UI.

The cached JSON shape (`{games:[{game_num,turns:[{turn,active_seat,active_label,actions:[str]}]}]}`)
optimizes for a text dump. Anything richer requires both a new extractor and
a new viewer.

## Goal

Build a full-depth replay/event viewer matching the polished mockup at
[`assets/2026-05-22-replay-viewer-mockup.png`](assets/2026-05-22-replay-viewer-mockup.png)
that lets the pilot step through any cached match at
event-level granularity — every phase, every step, every priority pass, every
stack interaction, every zone change — with the board state synced to the
event cursor.

Non-goals for this spec: rendering animations (we'll add an Animate toggle but
not implement playback in this scope), simulating "what-if" branches, editing
or annotating game-state directly.

## Architecture

Two-module split deliberately separating data from presentation so each can
ship and be validated independently.

### `analysis/replay_events.py` (new)

A second extractor over the same JSON blob stream that `replay_transcript.py`
already walks. Emits a flat event list plus a match-meta header. Reuses the
existing `_iter_json_blobs(log_path)` generator and the `_load_grpid_names()`
helper from `replay_transcript.py` so we don't duplicate log parsing.

**Public API:**

```python
def build_event_stream(arena_match_id: str,
                       force_refresh: bool = False) -> Optional[dict]:
    """Build (or load cached) event stream for one match.

    Returns dict with shape:
        {
          "arena_match_id": str,
          "schema_version": 1,
          "capabilities": {...},
          "match_meta": {...},
          "events": [...],
        }
    Returns None if the match isn't found in Player.log/Player-prev.log."""
```

**Cache header — self-describing capabilities.** Every cached replay JSON
carries a `capabilities` block declaring what data it contains. Future
consumers (Odds Engine, future puzzle scanner upgrades, line-EV module,
coaching tools) check capability flags rather than assuming a key exists.
This makes safe migration mechanical: when a new capability is added to the
extractor, old caches automatically rebuild on first read by any consumer
that requires it.

```python
"schema_version": 1,
"capabilities": {
  "turns": True,         # legacy text dump (existing classic dialog)
  "events": True,        # M1 event stream
  "board_diff": True,    # M1 board reconstruction inputs
  "public_info": True,   # M1 revealed_cards + shuffle_cause
  "per_game_decklists": True,  # M1 match_meta.games[i] sideboard tracking
  "odds_ready": False,   # Odds Engine consumer not yet present
  "stack_history": True, # M1 stack_after on every event
  "log_offsets": True,   # M1 log_offset for "View Raw JSON"
}
```

**Cache file location:** same as transcript today
(`data/match_replays/<arena_match_id>.json`). We extend the existing JSON
object with new top-level keys (`schema_version`, `capabilities`, `events`,
`match_meta`) **alongside** the existing `games` key. The classic dialog
keeps reading `games` and never sees the new fields. This is
forward-compatible — old caches without `events` get auto-rebuilt on first
Full viewer open. Auto-rebuild trigger: any consumer reading the cache that
finds `capabilities.<required_feature> != True` re-runs `build_event_stream(force_refresh=True)`.

### `gui/widgets/replay_viewer_window.py` (new)

`QMainWindow` (not QDialog) housing the full mockup layout: left timeline
tree + center event table + bottom board panel + right detail tabs. Opens
from Match History via a new "Watch (Full)" button. The existing "Watch
Replay" button stays, opens the classic dialog, and is renamed to
"Watch (Classic)" so users can fall back. Classic is removed in M4 after
Full has been the default for ~1 week with no regressions reported.

## Source of Truth Hierarchy

The replay event model is becoming the foundation that multiple downstream
systems (Odds Engine, puzzle scanner, line-EV module, coaching tools,
matchup analytics) will share. To prevent architectural rot as those systems
land, the layering is explicit and the boundaries are one-way:

```
Layer 1 · Player.log raw blobs      (immutable, on disk; the ground truth)
            ↓ extraction
Layer 2 · events[]                  (immutable once written; the data contract)
            ↓ derivation
Layer 3 · board reconstruction      (derived on demand; never stored)
            ↓ analysis
Layer 4 · derived analytics         (Odds Engine, puzzle scanner, EV, etc.)
            ↓ presentation
Layer 5 · UI                        (viewer windows, dialogs, overlays)
```

**Allowed dependencies (downward only):**
- UI → analytics → board reconstruction → events → raw blobs
- Any layer may read from any layer below it.

**Forbidden:**
- UI → analytics shortcuts (e.g., a viewer widget that re-parses `Player.log`
  directly instead of going through `events[]`)
- Analytics → UI inversions (e.g., the Odds Engine reading widget state
  instead of `events[]`)
- Layer 2 events being mutated after write — once an event is in
  `events[]`, only the extractor can change it via a re-extract; consumers
  treat it as immutable
- Layer 3 board state being cached to disk — board reconstruction is
  always reproducible from `events[]` and lives only in memory

This hierarchy is enforced by **module placement** (the `analysis/`
package depends on the cache JSON but not on `gui/`; the `gui/` package
imports from `analysis/` and never re-parses logs directly) and **API
shape** (`build_event_stream` is the only function that reads
`Player.log` for replay purposes — anything else is a bug).

## Data model

Every event in the `events[]` array has this shape:

```python
{
  "seq": 312,                    # global, monotonic across the whole match
  "game_state_id": 1234,         # raw MTGA gameStateId (sequencing primary key)
  "game_num": 1,
  "turn_num": 7,
  "phase": "Phase_Main1",        # raw enum from log
  "step": None,                  # filled for Beginning/Combat phases
  "active_seat": 1,
  "priority_seat": 2,            # who holds priority right now
  "actor_seat": 2,               # who took this action (differs from priority for triggers/SBAs)
  "kind": "cast_spell",          # normalized — see "Event kinds" below
  "card_name": "Lightning Strike",
  "card_grpid": 70404,
  "targets": [
    {"name": "Make Disappear", "grpid": 81234, "kind": "spell"},
  ],
  "details": {                    # kind-specific payload
    "damage": 3,
    "stack_position": "top",
  },
  "life_after": {"you": 8, "opp": 14},
  "mana_pool_after": {"you": "{R}", "opp": ""},
  "stack_after": [
    {"name": "Lightning Strike", "controller": "you", "targets": ["Make Disappear"]},
    {"name": "Make Disappear", "controller": "opp", "targets": ["Lightning Strike"]},
  ],
  "board_diff": [                 # only the zone changes since prev event
    {"card": "Lightning Strike", "grpid": 70404, "from": "hand", "to": "stack", "controller": "you"},
  ],
  "log_offset": 142853,           # byte offset into Player.log (for "View Raw JSON")
}
```

**Match meta** (top-level alongside `events`):

```python
"match_meta": {
  "format": "Traditional Ranked",
  "event_name": "Constructed_BestOf3_Ranked",
  "start_time": "2026-05-22T14:31:00Z",
  "end_time": "2026-05-22T14:49:42Z",
  "duration_sec": 1122,
  "winner_seat": 1,
  "winner_reason": "OpponentConceded",  # or "Lethal" / "Decking" / "Forfeit"
  "decklist_my_grpids": [...],          # pre-board game 1 (mainboard)
  "decklist_opp_observed_grpids": [...],
  "games": [                              # per-game decklists (required for postboard odds)
    {"game_num": 1, "decklist_my_grpids": [...], "sideboard_in": [], "sideboard_out": []},
    {"game_num": 2, "decklist_my_grpids": [...], "sideboard_in": [...], "sideboard_out": [...]},
    {"game_num": 3, "decklist_my_grpids": [...], "sideboard_in": [...], "sideboard_out": [...]},
  ],
  "key_events_by_turn": [
    {"turn": 1, "kind": "mulligan_to_6", "actor": "you", "seq": 7},
    {"turn": 3, "kind": "first_spell", "actor": "you", "seq": 42, "card": "Stormchaser's Talent"},
    {"turn": 7, "kind": "first_combat", "seq": 287},
    {"turn": 9, "kind": "low_life_threshold", "actor": "you", "seq": 411, "detail": "3 life"},
    {"turn": 10, "kind": "lethal_attack", "seq": 1402},
    {"turn": 10, "kind": "concede", "actor": "opp", "seq": 1476},
  ],
}
```

### Event kinds

Normalized from MTGA's raw annotation types into a closed enum the viewer can
dispatch on:

`phase_change`, `step_change`, `priority_grant`, `priority_pass`,
`mulligan_decision`, `keep_hand`, `draw_card`, `play_land`, `cast_spell`,
`activate_ability`, `trigger_ability`, `target_chosen`, `mana_paid`,
`mana_added`, `resolve`, `counter_spell`, `counter_ability`,
`damage_dealt`, `life_change`, `zone_change`, `token_created`,
`counter_added`, `counter_removed`, `scry`, `surveil`, `shuffle`, `reveal`,
`cascade`, `library_look`, `attack_declared`, `block_declared`,
`combat_damage_assigned`, `game_end`. Any annotation we don't yet map falls
through to `kind="raw"` with the full annotation dict in `details.raw` — so
we never silently drop events.

### Public-information fields (required for future Odds Engine)

Every event carries two additional optional fields that ship in M1 but only
get populated when the underlying annotation provides the data:

```python
"revealed_cards": [                # public info visible to both players
  {"grpid": 70404, "name": "Lightning Strike",
   "source": "scry_top" | "surveil_top" | "surveil_gy" | "cascade" |
             "reveal_to_opp" | "look_at_top" | "search_library" |
             "opp_reveal" | "exile_face_up",
   "seat": 1, "library_position": "top" | "bottom" | None},
  ...
],
"shuffle_cause": "fetch" | "effect" | "etb" | "turn_end" | "unknown" | None,
```

These fields are how the Odds Engine reconstructs the public-information
state at any seq: known-top-of-library, known-shuffled-away cards,
known-bottomed cards, known-exiled cards from cascade-style effects, opp's
revealed-but-not-cast cards. M1 ships the data; the Odds Engine consumes it
later.

### Board snapshots are reconstructed, not stored

Storing a full board snapshot per event would blow the cache size up ~5x.
Instead each event records only `board_diff` (the zone changes from the
previous event), plus `life_after`, `mana_pool_after`, and `stack_after`
(small, always-current). A helper `analysis.replay_events.replay_board_at(events, seq)`
walks events[0..seq] applying each diff to a state dict. Cached in memory by
`(arena_match_id, seq)` for smooth scrubbing. ~1ms per event rebuild on a
1500-event match.

## Milestones

### **M1 · Event-model parser + CLI sanity check (~2 days, ~400 LOC)**

The smallest safe first patch. **Ship this first; commit; validate; only then
start M2.**

1. New `analysis/replay_events.py` implementing `build_event_stream()`.
2. Cache file gains `events`, `match_meta`, `schema_version` top-level keys.
   Existing `games` key is untouched — classic viewer keeps working.
3. `gui/mtga_log_watcher.py::_build_missing_transcripts` calls both builders
   so new caches land with both fields.
4. New `scripts/replay_event_dump.py <arena_match_id>` — CLI that prints the
   event stream as a pretty table. Validates extraction without any GUI work.
5. Tests in `tests/test_replay_events.py`:
   - **Round-trip invariant** — re-rendering `events[]` reproduces the
     existing `turns[].actions[]` (proves nothing was lost going from the
     old format).
   - **Event count fixture** — known count for each of the 4 cached matches.
   - **Phase coverage fixture** — at least one event per phase + step pair
     that MTGA emits (Beginning/Untap, Beginning/Upkeep, Beginning/Draw,
     Main1, Combat/Begin, Combat/DeclareAttackers, Combat/DeclareBlockers,
     Combat/Damage, Combat/End, Main2, Ending/End, Ending/Cleanup).
   - **Priority sequencing** — every event between a `priority_grant` and
     the next `priority_pass`/`priority_grant` has the same `priority_seat`.
   - **Board diff validity** — applying all diffs from seq=0 to seq=N
     produces the same battlefield/hand/GY zone counts that the raw
     `zones[]` array reports at the message with `seq=N`.
   - **Public-information capture** — for every `scry`, `surveil`,
     `reveal`, `cascade`, or library-look annotation, the resulting event
     must populate `revealed_cards` so the future Odds Engine can build
     a public-information set. Test asserts ≥1 revealed entry per
     surveil/scry annotation in the fixture matches.
   - **Shuffle cause capture** — every `shuffle` event includes
     `details.cause` (`fetch` / `effect` / `etb` / `turn_end` / `unknown`)
     so the Odds Engine knows when library knowledge resets.

Reversibility: deletable in one commit. Old caches still work. Watcher still
works. Classic dialog still works.

**M1 discipline guardrail — what M1 explicitly does NOT do.**
M1 is the foundation that everything downstream depends on. To prevent
scope drift and protect schedule, the following are explicitly out of
scope for M1 and any pull request that adds them must be rejected:

- ❌ No new GUI changes. M1 is data + CLI only. The Full viewer ships in M2.
- ❌ No board state simulator beyond what M1 acceptance tests require
  (round-trip + zone-count assertions against raw `zones[]`).
- ❌ No odds computation, no hypergeometric helpers, no probability code.
- ❌ No Monte Carlo, no line-EV, no AI coaching, no card-suggestion logic.
- ❌ No new card-data dependencies beyond `db.card_data` lookups.
- ❌ No changes to `gui/widgets/transparent_overlay.py` (live overlay).
- ❌ No card-name normalization beyond what Scryfall already provides.
- ❌ No speculative abstractions — concrete shapes only. If a second
  consumer doesn't exist yet, the abstraction waits until it does.
- ❌ No schema additions beyond the documented event/match_meta fields.
  New fields go through schema_version + capabilities, not ad-hoc
  additions.

If a need arises mid-implementation that requires one of the above, the
correct action is: pause, document the requirement as a future-milestone
addition, and ship M1 without it. The data contract is more valuable than
any individual convenience.

### **M2 · Full-depth viewer (~2-3 days, ~600 LOC)**

New `gui/widgets/replay_viewer_window.py`. Mirrors the mockup:

- **Left pane** — `QTreeWidget` rooted at Games, with Turn → Phase → Step →
  Event children. Bottom "Key Events" section as flat clickable items.
  Search-events bar at the bottom uses `QSortFilterProxyModel`.
- **Center pane top** — `QTableView` over a custom `QAbstractTableModel`
  (lazy-populated so 1500+ event matches scroll smoothly). Columns:
  `#` / `Time` / `Player` / `Event`. Filters bar above (kind chips).
- **Center pane bottom** — board state panel rendered as a placeholder in
  M2 ("Board view ships in M3"). Stack list view is functional in M2 since
  `stack_after` ships in M1.
- **Right pane** — `QTabWidget` with `Event Details`, `Stack`, `Notes` tabs.
  Card preview at bottom uses `gui/widgets/card_image_cache.py` (already
  disk-caches Scryfall images per grpid).
- **Top bar** — match ID + event navigation buttons (◀◀, ◀, "Event N/M", ▶,
  ▶▶, |▶ jump-to-end) + Jump-To dropdown + Filters.
- **Bottom controls** — speed selector (placeholder), Animate toggle
  (placeholder), Show Board Changes toggle, Always Visible dropdown (binds
  which event field is always rendered in the preview pane).

Match History's "Watch Replay" button becomes a split button: primary
"Watch (Full)" opens the new window; menu option "Watch (Classic)" opens the
old dialog. Both write to the same `_cached_dialog` reference so we don't
leak. Selection persists in `gui/state.py` as `tabs.match_history.replay_viewer_mode`.

### **M3 · Board state panel (~2 days, ~400 LOC)**

Brings the board panel below the event table to life. Two-row layout (opp top,
you bottom) mirroring MTGO:

- Per row: avatar + life total + hand count + library/GY/exile counts + mana
  pool + battlefield strip (lands left, creatures right, separator).
- Battlefield cards render as small JPEG thumbnails via
  `gui/widgets/card_image_cache.py`. Hovering opens the full Scryfall image
  via a generalized `CardTooltip` (M3 also extends `install_card_tooltip` to
  accept arbitrary widgets with a `card_name` property, not just
  `QTableWidget` cells).
- Tap state, attack/block declarations, +1/+1 counters, attached auras all
  reflected in the rendering (tap = 90° rotation, attacking = red border,
  blocking = arrow to attacker, counters = small chip overlay).
- Highlight ring on whichever card the currently-selected event involves
  (`card_grpid` or any item in `targets[]`).
- Reconstructor lives at `analysis.replay_events.replay_board_at(events, seq)`.

### **M-future · Odds Engine (post-M4, deferred — not in this implementation plan)**

The Untapped.gg overlay's odds panel is the explicit visual reference. The
Odds Engine is a separate future milestone that **consumes** the event stream
and board-state reconstruction; M1's job is to **preserve enough data** that
M-future doesn't have to re-parse Player.log.

**Goals (deferred):**

1. **Next-draw odds** — P(target card is top of library | known zones,
   known shuffles, known reveals)
2. **Multi-draw odds** — P(see target within N draws) via hypergeometric
3. **Grouped-category odds** — P(any land | any threat | any removal |
   any counter | any sweeper) using user-tagged card roles from
   `analysis/deck_roles.py`
4. **Conditional outs** — P(target | "I survive this attack" | "I draw a
   land first")
5. **Replay-analysis percentages** — retrospective: "at T6, you had 24%
   to hit your out for the next turn"
6. **EV comparison between lines** — given two candidate plays at a
   priority point, Monte Carlo / analytic EV across remaining outcomes

**M1 data-preservation requirements (ALREADY IN SPEC ABOVE):**

| Need | Where it lives in M1 |
|---|---|
| Known zones at any seq | `board_diff[]` reconstructable via `replay_board_at()` |
| Revealed cards (scry tops, surveil reveals, cascade exiles, opp reveals) | `revealed_cards[]` field on each event |
| Surveil/scry decisions with chosen action | `details.topIds` / `details.bottomIds` / `details.action` on `scry`/`surveil` events |
| Shuffle events with cause | `kind="shuffle"`, `details.cause` |
| Library counts | reconstructable from `board_diff` zone counts |
| Public information tracking | union of `revealed_cards[]` across events[0..seq] |
| Sideboard tracking for postboard games | `match_meta.games[i].decklist_my_grpids` |

The M1 acceptance gate **already includes** the public-information capture
and shuffle-cause capture tests — those exist to lock the data contract for
the future Odds Engine even though no consumer exists yet.

**Future modules (post-M4):**

- `analysis/deck_odds.py` — hypergeometric + conditional probability over
  known/unknown zones; given `(remaining_library, target_set, public_info)`
  returns `P(draw_target | conditions)`
- `analysis/out_calculator.py` — given a board position, enumerate the
  cards-in-library that beat the current threat; surfaces "what beats
  this?" answers
- `analysis/line_ev.py` — given two candidate plays at a priority point,
  compute expected outcome via short Monte Carlo (~1000 rollouts) or
  analytic decomposition when the branching is small

**Future UI surfaces (post-M4):**

- **Right-side Odds tab** in the replay viewer — switches the right pane
  from Event Details to a live-as-you-scrub odds panel. Shows P(top
  card), grouped category odds, per-card outs against the current threat.
  Bindings: cursor on a hand card → "P(this is drawn in next 2 turns)";
  cursor on an opp creature → "P(I draw removal next turn)".
- **Live overlay mode** — extends the existing transparent overlay
  (shipped 2026-05-15, `gui/widgets/transparent_overlay.py`) with the
  same odds panel for real-time decision support during MTGA play.
  Mirrors Untapped.gg's overlay form factor.
- **"What were my outs?" panel** — retrospective view for any past
  event: enumerates the cards that would have beaten the position and
  the probability the user had of drawing each. The decision-quality
  feedback loop the pilot uses for review.

**Explicit non-goal for M1-M4:** No odds computation happens in this spec.
M1 ships the data fields populated and tested; the Odds Engine is its own
spec + plan when the pilot is ready to start it.

### **M4 · Polish (~1-2 days, ~300 LOC)**

- Full event-text search via `QSortFilterProxyModel` over the events model
- Kind filter chips (casts only / combat only / stack only / hide priority
  passes)
- Jump-To dropdown menu items: mulligan / first spell / first combat / first
  damage taken / low life threshold / lethal / concede
- Mark-important-event + per-replay notes saved to new `match_log.replay_notes`
  TEXT column (schema migration in `db/database.py::_apply_schema`)
- Export Markdown summary ("Replay review — Game 1 Turn 7: passed priority
  with Lightning Strike in hand, should have…")
- Remove "Watch (Classic)" button + `gui/widgets/replay_transcript_dialog.py`
  module once Full has been default for ~1 week with no regressions.

**Total: ~7-9 days end-to-end, but each milestone ships independently and is
reversible.**

## Risks and open questions

1. **State simulator drift on edge cases.** Copies, tokens, transform DFCs,
   attached auras, exile-with-return, ETB-with-counters, modal DFCs, day/night,
   adventure splits — each is a potential source of board-diff inaccuracy.
   Mitigation: per-mechanic fixture tests in M1 + a "compare reconstructed
   zone counts vs raw `zones[]` array" assertion that runs on every cached
   match.

2. **Opp hand is structurally hidden.** Arena's log only sees opp cards when
   they're cast or otherwise revealed. The board view shows opp's hand as N
   face-down chips with `card_name=None`; cast events that originated from
   opp's hand can be back-referenced to show what they had at cast time,
   but unknown opp-hand cards stay unknown forever. Document this clearly
   in the viewer with a tooltip on the face-down chips.

3. **Performance on long matches.** A 30-minute Bo3 can produce 2000+ events.
   Lazy table model + reconstruct-on-scrub keep memory bounded. Tested target:
   first paint < 200ms after open, scrub < 16ms per event.

4. **Cache size growth.** Adding `events[]` roughly doubles cache size (from
   ~30 KB to ~60-80 KB per match). At ~hundreds of matches this is negligible
   in absolute terms but worth noting. Compression deferred to M4+ if needed.

5. **Classic viewer removal timing.** Keep it through all 4 milestones so the
   pilot always has a fallback. Don't delete until Full has shipped, run on
   the pilot's own next-day matches, and survived a week without crash
   reports.

6. **Animation playback.** The mockup shows speed controls (0.5x / 1x / 2x /
   4x) and an Animate toggle. Out of scope for M1-M4. Add as M5 if the
   pilot finds the manual scrubbing inadequate.

7. **Schema versioning forward.** `schema_version: 1` lets us evolve the
   event model later without breaking caches. M2 viewer must handle missing
   keys gracefully (e.g., `stack_after` defaulting to `[]`, `revealed_cards`
   defaulting to `[]`, `shuffle_cause` defaulting to `None`) so a future
   milestone adding new fields doesn't break older cached events.

8. **Odds Engine data contract is locked in M1.** The `revealed_cards[]`
   list, `shuffle_cause` field, and per-game decklist tracking in
   `match_meta.games[]` are the data contract for the future Odds Engine.
   If M1 ships without these fields populated correctly, we'd have to
   re-extract the entire replay cache when the Odds Engine lands.
   Mitigation: the M1 acceptance gate explicitly tests public-information
   capture and shuffle-cause capture.

## Files touched

**New:**
- `analysis/replay_events.py`
- `scripts/replay_event_dump.py`
- `tests/test_replay_events.py`
- `gui/widgets/replay_viewer_window.py` (M2)

**Modified:**
- `gui/mtga_log_watcher.py` — wire both builders into `_build_missing_transcripts`
- `gui/widgets/deck_match_history.py` — split "Watch Replay" button into Full / Classic
- `gui/widgets/card_tooltip.py` — generalize `install_card_tooltip` to non-table widgets (M3)
- `gui/state.py` + `gui/state_keys.py` — add `tabs.match_history.replay_viewer_mode`
- `db/database.py::_apply_schema` — add `match_log.replay_notes TEXT` (M4)

**Removed in M4:**
- `gui/widgets/replay_transcript_dialog.py` — after the classic→full transition stabilizes

**Future (post-M4, not in this implementation plan):**
- `analysis/deck_odds.py` — Odds Engine: hypergeometric + conditional probability
- `analysis/out_calculator.py` — Odds Engine: enumerate outs vs current position
- `analysis/line_ev.py` — Odds Engine: EV comparison between candidate lines
- New right-side **Odds** tab in `gui/widgets/replay_viewer_window.py`
- Odds panel addition to `gui/widgets/transparent_overlay.py` (live mode)

## Acceptance criteria

- [ ] **M1** — All 4 cached match transcripts re-extracted into `events[]`;
  round-trip test green; CLI dump readable; classic dialog still opens
  unchanged.
- [ ] **M2** — Full viewer opens from Match History; left tree expands all
  the way to Phase/Step/Event; center table scrolls smoothly on a 1500+
  event match; right detail tabs populate; classic dialog still selectable.
- [ ] **M3** — Board panel renders battlefield card thumbnails for both
  players; hover shows full Scryfall art; current-event card highlighted;
  mana pool / counts update as you scrub.
- [ ] **M4** — Event search returns instantly; jump-to-key-events works;
  notes saved per match; markdown export produces readable output;
  classic dialog removed.

---
