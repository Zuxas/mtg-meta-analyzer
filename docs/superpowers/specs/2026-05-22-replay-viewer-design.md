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
          "match_meta": {...},
          "events": [...],
          "schema_version": 1,
        }
    Returns None if the match isn't found in Player.log/Player-prev.log."""
```

Cache file: same as transcript today (`data/match_replays/<arena_match_id>.json`).
We extend the existing JSON object with two new top-level keys (`events`,
`match_meta`, `schema_version`) **alongside** the existing `games` key. The
classic dialog keeps reading `games` and never sees the new fields. This is
forward-compatible — old caches without `events` get auto-rebuilt on first
Full viewer open, with a small "Building event stream…" status message.

### `gui/widgets/replay_viewer_window.py` (new)

`QMainWindow` (not QDialog) housing the full mockup layout: left timeline
tree + center event table + bottom board panel + right detail tabs. Opens
from Match History via a new "Watch (Full)" button. The existing "Watch
Replay" button stays, opens the classic dialog, and is renamed to
"Watch (Classic)" so users can fall back. Classic is removed in M4 after
Full has been the default for ~1 week with no regressions reported.

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
  "decklist_my_grpids": [...],
  "decklist_opp_observed_grpids": [...],
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
`attack_declared`, `block_declared`, `combat_damage_assigned`,
`game_end`. Any annotation we don't yet map falls through to `kind="raw"`
with the full annotation dict in `details.raw` — so we never silently drop
events.

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

Reversibility: deletable in one commit. Old caches still work. Watcher still
works. Classic dialog still works.

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
   keys gracefully (e.g., `stack_after` defaulting to `[]`) so a future M5
   adding new fields doesn't break older cached events.

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
