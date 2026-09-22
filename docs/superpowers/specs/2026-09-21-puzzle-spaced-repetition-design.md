# Puzzle Trainer T1.1 — Spaced Repetition + Daily Feed — Design Spec

**Date:** 2026-09-21
**Status:** Approved in conversation (pending spec review)
**Scope source:** ROADMAP "T1.1 — spaced repetition — re-queue missed drills; daily feed";
`harness/specs/2026-07-03-puzzle-trainer-v0.md` boundary "NO spaced repetition / daily feed (D4 re-queue) -- v0.1".

## Goal

Turn the Puzzles → Solve tab into a daily habit: a session with a finish line
("Today 3/10"), a streak, reviews that come back on a growing interval, and a
feed that never runs dry for outs-math drills.

## Decisions taken (with the user, 2026-09-21)

- **C** — session with a target + auto top-up of drills (over "ordering only").
- **B** — ladder for everything: every puzzle comes back on a growing interval;
  a miss resets it (over "only misses come back" and rating-aware spacing).
- **Derived schedule** — the schedule is a pure function of `puzzle_attempts`;
  no new table, no dual-write, no migration.

## Current behaviour being replaced

`gui/tabs/puzzles.py::_load_next_puzzle` serves `get_puzzles(category,
unsolved_only=True)[0]` (newest first). Consequences: a puzzle solved
correctly once never returns; a missed puzzle is re-served *immediately*
(right after the answer was revealed). Live data 2026-09-21: 49 puzzles
(40 `drill_outs`, 5 `find_lethal`, 3 `tempo`, 1 `stabilize`), 6 attempts,
all `correct`, on 4 puzzles.

## 1. Scheduling — `analysis/puzzles/spaced_repetition.py` (pure)

```
INTERVALS = (1, 3, 7, 14, 30, 90)      # days, index = rung
```

For one puzzle's attempts (oldest → newest, each `(date, verdict)`):

- `rung` = length of the trailing run of `verdict == "correct"`. Any other
  verdict (`incorrect`, `partial`, `user_marked`) ends the run.
- `state`:
  - no attempts → `new`
  - `rung >= len(INTERVALS)` (6 consecutive corrects, i.e. passed the 90-day
    rung) → `retired`, never served again
  - else `due = last_attempt_date + INTERVALS[rung]`; a miss therefore means
    rung 0 → due tomorrow.
- "Due" means `due <= today`. Dates are local calendar days (`date`), derived
  from `puzzle_attempts.attempted_at` (ISO timestamp, local).

API (pure, no DB):

```
schedule_for(attempts: list[tuple[date, str]], today: date) -> Schedule
    Schedule(state: "new"|"due"|"scheduled"|"retired", rung: int, due: date|None,
             last: date|None)
build_session(due: list[T], new: list[T], remaining: int) -> list[T]
    due first (most overdue first), then new (as given), truncated to `remaining`
streak(attempt_counts_by_day: dict[date, int], target: int, today: date) -> int
    consecutive days ending today or yesterday with count >= target
```

## 2. Feed — `analysis/puzzles/feed.py` (DB-aware, Qt-free)

```
todays_feed(category: str|None, target: int, today: date, *, top_up=True) -> Feed
    Feed(puzzles: list[dict], done_today: int, due_count: int, new_count: int,
         generated: int, remaining: int)
daily_stats(target: int, today: date) -> DailyStats(done_today, due_count, new_count, streak)
```

Rules:

1. Load every puzzle in `category` (None = all) with its attempts; classify via
   `schedule_for`.
2. **Never serve a puzzle attempted today.** A miss comes back tomorrow, not
   now.
3. `remaining = max(0, target - done_today)` where `done_today` = number of
   attempts recorded today (any verdict, any category).
4. Order: due (most overdue first, ties by id desc), then new (id desc — the
   current "newest first"), truncated to `remaining`.
5. **Top-up** — only when `category in (None, "drill_outs")` and the list is
   still shorter than `remaining`: generate exactly the shortfall with
   `drill_generator.generate_drills(conn, n=shortfall, seed=S)` and persist
   each via `db_puzzles.save_puzzle(...)` exactly as `scripts/seed_drills.py`
   does (`author="drill_generator"`, `deck_id=None`). Idempotency: generated
   puzzles are unattempted, so they join the `new` pool and shrink the next
   shortfall by themselves; and `S = int(today.strftime("%Y%m%d")) * 1000 +
   n_generated_today` (count of `drill_outs` rows by `drill_generator` created
   today) so a second top-up on the same day (target raised, Keep going)
   continues the sequence instead of re-minting the same first k drills.
   Positional categories never top up.
6. `todays_feed(..., top_up=False)` is the read-only variant (used by
   `daily_stats` and by tests/live checks).

Streak: consecutive calendar days, ending today or yesterday, on which
`attempts >= target`. Computed from `puzzle_attempts`; nothing stored. The
current target is used for every day (a changed target re-reads history with
the new bar — acceptable, documented).

## 3. UI — `gui/tabs/puzzles.py`, Solve header only

- Header line becomes: `Today 3/10 · 2 due · streak 4🔥` followed by the
  existing session W/L and rating HTML. Streak segment only when `>= 2`.
- New `QSpinBox` "target" (1–50, default 10) beside the category combo,
  persisted in `ui_state.tabs.puzzles.daily_target` (`gui/state_keys.py`
  entry, hydrate in `showEvent` with `blockSignals`, save on change — the
  existing sticky-state pattern).
- `_load_next_puzzle`: `feed = todays_feed(cat, target, date.today())`; serve
  `feed.puzzles[0]`. When `feed.remaining == 0` show
  `Done for today ✓ — next reviews due <earliest due date or "none scheduled">`
  with a **Keep going** button that reloads with an in-memory
  `target = done_today + 1` (the persisted target is untouched; extra work
  never hurts the streak). When `remaining > 0` but the list is
  empty (positional category exhausted, nothing due): the existing
  "Queue is empty" message.
- `_record_and_next` unchanged: the attempt row *is* the schedule.

## 4. Behaviour changes (explicit)

- Correctly solved puzzles return on the ladder (3d, 7d, 14d, 30d, 90d) instead
  of disappearing; after the 90-day rung they retire.
- Missed puzzles return tomorrow instead of immediately.
- The 6 existing attempts fit without migration: the 4 puzzles sit at rung 1,
  due 3 days after they were solved (already due).
- `db_puzzles.get_puzzles(unsolved_only=)` is untouched (Inbox/Author paths).
- `scripts/seed_drills.py` untouched; the feed's top-up is the only new writer
  of `drill_outs` rows and uses the same `save_puzzle` call.

## 5. Tests and verification

- `tests/test_spaced_repetition.py` (pure): ladder per rung; reset on
  `incorrect` / `partial` / `user_marked`; `new`; `retired` at 6; due vs
  scheduled boundary (`due == today` is due); `build_session` ordering and
  truncation; `streak` — met today, met yesterday only, broken by a gap,
  zero when today and yesterday both miss the bar.
- `tests/test_puzzle_feed.py` (tmp DB via the conftest guard; `init_db()` +
  `db_puzzles._ensure_tables()`): due-before-new ordering; nothing attempted
  today is served; `remaining` arithmetic; top-up generates exactly the
  shortfall, is idempotent for the same day, and does not fire for
  `find_lethal`; `daily_stats` counts. Drill generation in the tmp DB needs
  decks with cards — reuse the seeding pattern from
  `tests/test_date_normalization_sweep.py::mixed_db` (events/decks/deck_cards).
- `tests/test_puzzles_tab.py` addition (offscreen Qt, tmp DB): header shows
  `Today 0/N`; after N recorded attempts the done-state text and the
  Keep-going button appear.
- Live check (read-only, after implementation): `todays_feed(None, 10,
  date.today(), top_up=False)` against the real DB — expect 4 due, 6 new,
  0 generated on the 2026-09-21 data.
- Full suite green; repo docs (CLAUDE.md / NEXT_STEPS.md / ROADMAP.md) updated
  before the commit.

## Out of scope (YAGNI)

Rating-aware intervals, snooze / manual reschedule, notifications or tray
reminders, per-category targets, a stored schedule table, SM-2 ease factors.
