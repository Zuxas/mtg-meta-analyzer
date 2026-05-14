# Match Log — Auto-Import + Variant Tracking + Performance Timeline

**Status:** PROPOSED
**Created:** 2026-05-13
**Project:** mtg-meta-analyzer
**Estimated time:** 1-2 sessions (~10-14 hours)
**Arc:** Match Log feature deepening. Successor to manual-only logging; pairs with the GUI ergonomics direction A ship from earlier on 2026-05-13.

---

## Goal

Turn Match Log from a manual free-text record into a deck-aware history that
auto-captures Arena matches via the existing Untapped pipeline, links every
match to a specific saved-deck variant (hashed mainboard+sideboard snapshot),
and surfaces an inline Variant Timeline so single-card tweaks can be evaluated
against actual win rate — "I swapped 1 card and played 5 more games, did it
help?" becomes a question the GUI can answer directly.

## Scope

**In scope:**

1. Additive schema migration on `match_log` (5 new columns: `my_deck_id`, `my_variant_hash`, `opp_grp_ids_json`, `source`, `backfill_status`) + new `deck_variants` table.
2. Untapped sync extension: walk `data/untapped/replays/` and write `match_log` rows alongside the existing `saved_sb_plans` writes.
3. Refresh `gui/tabs/match_log.py` — Layout B (right-sidebar Timeline panel), saved-deck dropdown replacing free-text "My Deck" input, variant column on rows.
4. Variant Timeline panel — per-variant rows with match count, WR, Wilson-significance band, +/- card-swap delta from prior variant.
5. Auto-backfill script for historical `match_log` rows (`scripts/backfill_match_log_decks.py`).
6. "Resolve…" manual UI for orphan historical rows (saved-deck dropdown per row).
7. Manual entry dialog refresh — preserves paper/MTGO/non-Arena flow with the same deck-linked variant capture.
8. Unit + integration tests (Qt-free where possible, real-SQLite for migration paths).

**Out of scope:**

- Live-tail MTGA log watcher. Untapped Companion already captures Arena matches; Untapped sync covers the same data. Documented in the design rationale; not implemented.
- Paper/MTGO auto-import (no realistic source exists).
- Variant comparison across **different decks** (this is intra-deck only — Tokyo v1 vs Tokyo v2, not Tokyo vs some Boros build).
- Cross-archetype timeline analytics (lives elsewhere if needed).
- Untapped scraper changes — the M/W/F throttle stays. We only consume local data.
- Predictive WR forecasting from variant trends (just descriptive stats).

## Architecture

Three components, sequentially dependent:

1. **Schema layer** (`db/match_log.py`, new `db/deck_variants.py`) — additive ALTERs + new CREATE; idempotent on every app launch.
2. **Ingest layer** — two parallel writers into `match_log`:
   - `scrapers/untapped_match_log_writer.py` — walks `data/untapped/replays/` (already pulled, free to read), reuses `untapped_opponent_classifier` primitives, writes match_log rows with `source='untapped'`.
   - `gui/tabs/match_log.py::_MatchDialog` (refreshed) — manual entry path, writes with `source='manual'`.
3. **Surface layer** (`gui/tabs/match_log.py` refresh + new `gui/widgets/variant_timeline.py`) — Layout B sidebar, variant grouping, Wilson math, delta-from-prior rendering.

Each writer path resolves the same three new fields at insert time (`my_deck_id`, `my_variant_hash`, `deck_variants` upsert) via a shared helper `db/match_log.resolve_and_save(...)`.

## Schema

### New table

```sql
CREATE TABLE IF NOT EXISTS deck_variants (
    variant_hash    TEXT PRIMARY KEY,
    deck_id         INTEGER NOT NULL REFERENCES saved_decks(id) ON DELETE CASCADE,
    mainboard_json  TEXT    NOT NULL,
    sideboard_json  TEXT    NOT NULL,
    first_seen      TEXT    NOT NULL,
    last_seen       TEXT    NOT NULL,
    match_count     INTEGER NOT NULL DEFAULT 0,
    win_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deck_variants_deck ON deck_variants(deck_id);
```

### Additive ALTERs on `match_log`

```sql
ALTER TABLE match_log ADD COLUMN my_deck_id INTEGER;
ALTER TABLE match_log ADD COLUMN my_variant_hash TEXT;
ALTER TABLE match_log ADD COLUMN opp_grp_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE match_log ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE match_log ADD COLUMN backfill_status TEXT NOT NULL DEFAULT 'live';
```

`arena_match_id` already exists (added by `mtga_log_parser._ensure_arena_match_id_column`).

Values:
- `source`: `'untapped' | 'manual' | 'mtga_log'` (mtga_log preserved for archives even though live tail is out of scope).
- `backfill_status`: `'live' | 'auto' | 'manual' | 'orphan'`. `live` = captured at deploy or later; `auto` = backfilled by migration script (approximate variant_hash); `manual` = resolved by user in Resolve…; `orphan` = no saved_decks match.

Indexes:
```sql
CREATE INDEX IF NOT EXISTS idx_match_log_deck_id   ON match_log(my_deck_id);
CREATE INDEX IF NOT EXISTS idx_match_log_variant   ON match_log(my_variant_hash);
CREATE INDEX IF NOT EXISTS idx_match_log_backfill  ON match_log(backfill_status);
```

## Variant hashing

```python
def compute_variant_hash(mainboard: dict[str, int],
                         sideboard: dict[str, int]) -> str:
    canon = json.dumps({
        "mb": sorted(mainboard.items()),
        "sb": sorted(sideboard.items()),
    }, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
```

- Strict mainboard + sideboard. Any change in either board → new variant. SB-only changes intentionally cluster the user's SB tuning iterations as separate variants; UI offers a "main-board roll-up" view for the user who wants to compress them.
- 16 hex chars = 64 bits of entropy. Collision risk negligible at the scale of one player's history.
- Sort-order invariance enforced by the canonical sort; tests verify reordering inputs returns the same hash.

## Variant diff

```python
def variant_diff(v_prev: dict, v_curr: dict) -> dict:
    """Returns {'mainboard': {'added': [(name, qty), ...],
                              'removed': [(name, qty), ...]},
                'sideboard': {...}}
    Quantity changes render as paired (remove old qty, add new qty)."""
```

Used in Timeline rendering: "+2 Lightning Helix, -2 Dismember".

## Wilson significance for "did the tweak help?"

For each variant pair (v_prev, v_curr):

```python
def wilson_bounds(wins: int, total: int, conf: float = 0.95) -> tuple[float, float]:
    # standard Wilson score interval, two-sided
```

UI surfaces:
- The WR delta `Δ = v_curr.wr - v_prev.wr` (always)
- Both Wilson bands
- A flag: `"validated"` if bands don't overlap **or** both variants have N ≥ 10 with |Δ| ≥ 10pp; `"promising"` if |Δ| ≥ 10pp but bands overlap; `"noisy"` otherwise.

No predictive claim — the user judges from the bands and the flag.

## Ingest paths

### Untapped sync (`scrapers/untapped_match_log_writer.py`)

```
data/untapped/replays/*.json.gz
    │
    │ (gzip-stream JSON lines, reuse untapped_opponent_classifier primitives)
    │
    ├─→ extract: arena_match_id, my_grp_ids, opp_grp_ids, results, mulligans
    │
    ├─→ classify my_deck_id  (overlap score vs saved_decks.mainboard;
    │                          threshold 70%, else orphan)
    │
    ├─→ classify opp_deck  (existing classify_opponent_deck)
    │
    ├─→ resolve_and_save():
    │     - compute_variant_hash(saved_decks[deck_id].mainboard,
    │                            saved_decks[deck_id].sideboard)
    │     - upsert deck_variants row
    │     - insert match_log row with source='untapped'
    │
    └─→ skip if arena_match_id already in match_log
```

Runs as part of the M/W/F Untapped pipeline (no new schedule) — invoked from `scripts/run_fill_from_prefs.py` after the existing Untapped writers.

### Manual entry (`gui/tabs/match_log.py::_MatchDialog`)

The current dialog already collects most fields. Changes:

- "My Deck" combobox becomes non-editable, populated from `saved_decks` by name with id badge.
- On accept, look up the chosen `saved_decks` row, compute variant_hash from its current state, call `resolve_and_save()`.
- Format dropdown stays, but is auto-set from the chosen deck's format (still overridable).
- A new "Sync from Untapped…" button at the top of the Match Log tab triggers the Untapped writer ad-hoc (calls the same code path the M/W/F job calls).

### Active deck inference for Untapped

Reuse the overlap-scoring pattern from `mtga_log_parser.classify_opponent_deck`, applied to **my** observed grpIds vs the user's saved_decks mainboards. Score = `|cards_observed ∩ saved_deck.mainboard_card_ids| / |saved_deck.mainboard_card_ids|` (fraction of the candidate deck explained by what we saw). Highest score above 0.70 wins; ties broken by `last_seen` recency. Below threshold → `my_deck_id = NULL`, `backfill_status='orphan'`, surfaced in the Resolve… UI.

## UI — Layout B (right sidebar)

Match Log tab refresh:

```
┌── Format: standard ▾ ── Deck: Tokyo Prowess (id=17) ▾ ── [↻ Sync Untapped] [+ Log Match] ─┐
│                                                                                              │
│  ┌──────────────────────────────────────────────────┬────────── Variant Timeline ─────────┐ │
│  │  Date │ Event │ vs │ Result │ P/D │ Var │ Swap   │ 3 variants · 16 matches · 62.5% WR  │ │
│  │  May11│ RC R7 │ S.L│   W    │  p  │ v3b │  kept  │                                      │ │
│  │  May11│ RC R6 │ S.E│   L    │  d  │ v3b │   —    │ │ v1  · 3 mtch · 33%                 │ │
│  │  ...                                              │ │     · Apr 22-25 · initial          │ │
│  │                                                   │ │                                      │ │
│  │                                                   │ │ v2  · 5 mtch · 80%  ← validated    │ │
│  │                                                   │ │     · May 1-4                      │ │
│  │                                                   │ │     · +2 Helix, -2 Dismember       │ │
│  │                                                   │ │                                      │ │
│  │                                                   │ │ v3b · 8 mtch · 62%  ← promising    │ │
│  │                                                   │ │     · May 6-11                     │ │
│  │                                                   │ │     · +1 Pierce, -1 Counter        │ │
│  └──────────────────────────────────────────────────┴────────────────────────────────────┘ │
│                                                                                              │
│  ⚠ 12 historical matches need a deck — [Resolve…]                                          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Splitter between table and sidebar; sidebar collapsible.
- Variant cards in sidebar are clickable — clicking filters the left table to that variant.
- Approximate variants (from auto-backfill) prefix the label with `~`.
- Wilson flag rendered as a small badge next to WR.
- Sidebar empty state ("Pick a deck above to see its variant history") when no deck filter is set.

New module `gui/widgets/variant_timeline.py` owns the sidebar. Match Log tab composes it.

## Backfill / migration

One-shot script `scripts/backfill_match_log_decks.py` invoked from the schema migration:

1. For each `match_log` row with `my_deck_id IS NULL`:
   - Find `saved_decks` rows where normalized `archetype` matches the row's `my_deck` free-text, AND `created_at <= match_log.event_date` (within ±90 days).
   - **Unambiguous** (exactly 1 candidate): link `my_deck_id`, compute `my_variant_hash` from current state, upsert `deck_variants`, set `backfill_status='auto'`.
   - **Ambiguous or none**: leave `my_deck_id IS NULL`, set `backfill_status='orphan'`.
2. Write summary log `data/migrations/match_log_variant_backfill_<date>.log` (counts auto-resolved / orphan / total).

Caveat: auto-backfilled hashes use **current** saved_decks state, not as-of-match. UI marks these with `~` so the user knows the variant is approximate.

Resolve… dialog (in `gui/widgets/orphan_resolver.py`) walks orphan rows one at a time:

- Shows event / date / opp / free-text `my_deck`
- Presents a saved-decks dropdown + "skip — keep as free-text" button
- Each resolution: writes `my_deck_id`, `my_variant_hash`, flips `backfill_status='manual'`
- Closes when queue empties

## Testing

**Pure-Python unit tests** (Qt-free, fast):

- `tests/test_variant_hash.py` — canonical hashing, sort-order invariance, mainboard vs SB sensitivity, collision impossibility at our scale.
- `tests/test_variant_diff.py` — diff math, add/remove pairs, quantity changes.
- `tests/test_wilson_significance.py` — band math, overlap detection, "validated" / "promising" / "noisy" classification rules.
- `tests/test_my_deck_classifier.py` — overlap scoring against saved_decks fixtures; 70% threshold; orphan behavior.
- `tests/test_match_log_backfill.py` — auto-backfill resolution given fixture saved_decks + match_log rows; orphan cases.

**Integration tests** (in-memory SQLite):

- `tests/test_match_log_schema_migration.py` — additive ALTERs + deck_variants CREATE on an existing match_log fixture; idempotent re-run.
- `tests/test_untapped_match_log_writer.py` — fixture replay JSON → match_log row with all 3 new fields populated; arena_match_id dedup; orphan path when classifier scores below threshold.

**Manual smoke** (added to a session-start chain after deploy):

- Sync Untapped on the May 11-12 RC replays → verify rows land with correct my_deck_id and variant_hash.
- Edit Tokyo Prowess SB plans → log a manual match → verify NEW variant_hash, deck_variants gets a second row.
- Open Match Log filtered to Tokyo → verify Timeline sidebar shows both variants with correct match counts + WR.
- Run Resolve… dialog on a synthetic orphan row → verify backfill_status flips, row links cleanly.

## Open questions

None at design-approval time. Surface during implementation if they arise.

## Why not just use Untapped.gg directly

User asked this explicitly during brainstorming (2026-05-13). Answer:

- Untapped does NOT track variant-tweak attribution — they aggregate WR per archetype, not per personal variant. "Tokyo v3 vs Tokyo v3-with-Dismember-swap" doesn't exist anywhere on their platform.
- Untapped is Arena-only — paper RC matches (the user's primary competitive surface) have no Untapped representation.
- Untapped doesn't know about your saved_decks (Tokyo Prowess id=17 with 17 SB plans + primer notes).
- The original "live-tail MTGA watcher" plan WAS partial duplication; that part was dropped. Remaining build leverages Untapped data, doesn't rebuild it.

## Implementation order

Per writing-plans, but at design time:

1. Schema migration + `db/deck_variants.py` + tests.
2. Variant hashing/diff/Wilson helpers + tests.
3. `resolve_and_save()` helper + my-deck classifier + tests.
4. Untapped match_log writer + tests.
5. Backfill script + tests.
6. GUI: dialog refresh + saved-deck dropdown.
7. GUI: Variant Timeline widget.
8. GUI: Match Log tab Layout B integration.
9. GUI: Resolve… dialog.
10. CLAUDE.md / NEXT_STEPS.md / ROADMAP.md updates.

Steps 1-5 are Qt-free and fully test-coverable. Steps 6-9 are GUI surface, smoke-test-verified.
