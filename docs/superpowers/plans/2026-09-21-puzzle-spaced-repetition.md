# Puzzle Trainer T1.1 — Spaced Repetition + Daily Feed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Puzzles → Solve tab a daily habit: reviews come back on a 1/3/7/14/30/90-day ladder derived purely from `puzzle_attempts`, a daily target with a streak, and outs-math drills auto-generated when the feed runs short.

**Architecture:** Two new Qt-free modules under `analysis/puzzles/`: `spaced_repetition.py` (pure functions: ladder, session composition, streak) and `feed.py` (reads `puzzle_attempts` + `puzzles`, builds today's ordered feed, tops up drills). `db/puzzles.py` gains two small query helpers. `gui/tabs/puzzles.py` swaps its `get_puzzles(unsolved_only=True)` selection for the feed and gains a target spinbox, a "Today n/N · due · streak" header and a done-state with "Keep going". No schema change.

**Tech Stack:** Python 3.13, sqlite3 via `db.database.get_connection()`, PyQt6 (offscreen in tests), pytest. Spec: `docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md`.

## Global Constraints

- `INTERVALS = (1, 3, 7, 14, 30, 90)` days; rung = trailing run of `verdict == "correct"`; any other verdict (`incorrect`, `partial`, `user_marked`) resets to rung 0; rung 6 = retired.
- "Due" means `due <= today`; dates are **local calendar days**. `puzzle_attempts.attempted_at` and `puzzles.created_at` are UTC ISO strings ending in `Z` (`db.puzzles._utc_now()` → `'2026-09-22T04:35:11Z'`); convert with `.astimezone().date()`.
- Never serve a puzzle attempted today. Order: due (most overdue first, ties id desc), then new (id desc), truncated to `remaining = max(0, target - done_today)`.
- Top-up only for `category in (None, "drill_outs")`; generate exactly the shortfall; seed `S = int(today.strftime("%Y%m%d")) * 1000 + n_generated_today`; persist via `db_puzzles.save_puzzle(...)` with `author="drill_generator"`, `deck_id=None` (as `scripts/seed_drills.py`).
- Streak = consecutive days ending today or yesterday with `attempts >= target` (current target for every day). Nothing stored.
- UI state key `tabs.puzzles.daily_target` (spinbox 1–50, default 10); "Keep going" raises the target **in memory only**.
- Tests never touch the live DB (conftest `_no_live_db` guard is on by default); every DB test calls `init_db()` and `db_puzzles._ensure_tables()`.
- Repo rule: update `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md` before the final commit; run `PYTHONIOENCODING=utf-8 python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_strategy_search_live.py`; commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; stage by explicit path (never `git add -A`).
- Shell: prefix commands with `rtk`. Do not `git push` (the user's hook blocks it; the user pushes).

---

## File map

| File | Responsibility |
|---|---|
| Create `analysis/puzzles/spaced_repetition.py` | Pure: `INTERVALS`, `Schedule`, `schedule_for`, `build_session`, `streak` |
| Create `analysis/puzzles/feed.py` | DB-aware, Qt-free: `attempt_date`, `Feed`, `DailyStats`, `todays_feed`, `daily_stats`, `_top_up` |
| Modify `db/puzzles.py` | Add `get_attempt_log(*, category=None)` and `count_puzzles_created_since(*, author, category, since_iso)` |
| Modify `gui/state_keys.py` | Add `PUZZLES_DAILY_TARGET = "tabs.puzzles.daily_target"` |
| Modify `gui/tabs/puzzles.py` | Header, target spinbox, feed-driven `_load_next_puzzle`, done state + Keep going, `showEvent` hydrate |
| Create `tests/test_spaced_repetition.py` | Pure-function tests |
| Create `tests/test_puzzle_feed.py` | Feed tests on a tmp DB incl. top-up |
| Modify `tests/test_puzzles_tab.py` | Header + done-state smoke tests |
| Modify `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md` | Repo rule |

---

### Task 1: Ladder — `schedule_for`

**Files:**
- Create: `analysis/puzzles/spaced_repetition.py`
- Test: `tests/test_spaced_repetition.py`

**Interfaces:**
- Produces: `INTERVALS: tuple[int, ...]`, `Schedule(state: str, rung: int, due: date | None, last: date | None)` (frozen dataclass), `schedule_for(attempts: Sequence[tuple[date, str]], today: date) -> Schedule`. `attempts` may be in any order; the function sorts by date. `state` is one of `"new" | "due" | "scheduled" | "retired"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_spaced_repetition.py
"""Pure scheduling for the puzzle trainer (T1.1, 2026-09-21).

Ladder 1/3/7/14/30/90 days derived from an attempt history; nothing stored.
Spec: docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md
"""
from datetime import date, timedelta

import pytest

T = date(2026, 9, 21)


def d(days_ago):
    return T - timedelta(days=days_ago)


def test_intervals_are_the_agreed_ladder():
    from analysis.puzzles.spaced_repetition import INTERVALS
    assert INTERVALS == (1, 3, 7, 14, 30, 90)


def test_never_attempted_is_new():
    from analysis.puzzles.spaced_repetition import schedule_for
    s = schedule_for([], T)
    assert (s.state, s.rung, s.due, s.last) == ("new", 0, None, None)


@pytest.mark.parametrize("verdict", ["incorrect", "partial", "user_marked"])
def test_any_non_correct_verdict_resets_to_rung_0_due_tomorrow(verdict):
    from analysis.puzzles.spaced_repetition import schedule_for
    s = schedule_for([(d(5), "correct"), (d(3), "correct"), (d(0), verdict)], T)
    assert s.rung == 0 and s.due == T + timedelta(days=1) and s.state == "scheduled"


def test_trailing_corrects_climb_the_ladder():
    from analysis.puzzles.spaced_repetition import schedule_for, INTERVALS
    hist = [(d(40), "incorrect")]
    for rung in range(6):
        hist.append((d(20 - rung), "correct"))
        s = schedule_for(hist, T)
        if rung < 5:
            assert s.rung == rung + 1
            assert s.due == d(20 - rung) + timedelta(days=INTERVALS[rung + 1])
        else:
            assert s.state == "retired" and s.rung == 6 and s.due is None


def test_due_is_inclusive_of_today_and_scheduled_is_future():
    from analysis.puzzles.spaced_repetition import schedule_for
    # rung 1 after one correct -> due = last + 3
    assert schedule_for([(d(3), "correct")], T).state == "due"        # due == today
    assert schedule_for([(d(4), "correct")], T).state == "due"        # overdue
    assert schedule_for([(d(2), "correct")], T).state == "scheduled"  # due tomorrow


def test_attempts_are_sorted_by_date_before_scoring():
    from analysis.puzzles.spaced_repetition import schedule_for
    unordered = [(d(0), "correct"), (d(2), "incorrect"), (d(1), "correct")]
    assert schedule_for(unordered, T).rung == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'analysis.puzzles.spaced_repetition'`

- [ ] **Step 3: Write the minimal implementation**

```python
# analysis/puzzles/spaced_repetition.py
"""Pure scheduling for the puzzle trainer (T1.1, 2026-09-21).

The schedule is a function of the attempt log -- nothing is stored. A puzzle's
rung is its trailing run of `correct` verdicts; the next due date is the last
attempt plus INTERVALS[rung]. Any other verdict resets the run, so a miss comes
back tomorrow. Six consecutive corrects (past the 90-day rung) retire it.
Spec: docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Sequence

INTERVALS: tuple[int, ...] = (1, 3, 7, 14, 30, 90)   # days; index = rung
CORRECT = "correct"


@dataclass(frozen=True)
class Schedule:
    state: str                 # "new" | "due" | "scheduled" | "retired"
    rung: int
    due: Optional[date]
    last: Optional[date]


def schedule_for(attempts: Sequence[tuple[date, str]], today: date) -> Schedule:
    """Classify one puzzle from its (date, verdict) attempts, any order."""
    if not attempts:
        return Schedule("new", 0, None, None)
    ordered = sorted(attempts, key=lambda a: a[0])
    rung = 0
    for _, verdict in reversed(ordered):
        if verdict != CORRECT:
            break
        rung += 1
    last = ordered[-1][0]
    if rung >= len(INTERVALS):
        return Schedule("retired", rung, None, last)
    due = last + timedelta(days=INTERVALS[rung])
    return Schedule("due" if due <= today else "scheduled", rung, due, last)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
rtk git add analysis/puzzles/spaced_repetition.py tests/test_spaced_repetition.py && rtk git commit -q -m "feat(puzzles): spaced-repetition ladder derived from the attempt log

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Session composition and streak — `build_session`, `streak`

**Files:**
- Modify: `analysis/puzzles/spaced_repetition.py`
- Test: `tests/test_spaced_repetition.py`

**Interfaces:**
- Consumes: `Schedule` from Task 1.
- Produces: `build_session(due: Sequence[tuple[date, T]], new: Sequence[T], remaining: int) -> list[T]` — `due` items are `(due_date, item)`, sorted here most-overdue-first (ties keep input order; the caller passes id-desc); `new` is appended as given; result truncated to `remaining` (≤ 0 → `[]`). `streak(counts_by_day: Mapping[date, int], target: int, today: date) -> int`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_spaced_repetition.py`)

```python
def test_build_session_due_first_most_overdue_first_then_new_truncated():
    from analysis.puzzles.spaced_repetition import build_session
    due = [(d(1), "a"), (d(5), "b"), (d(3), "c")]      # b most overdue
    new = ["n1", "n2", "n3"]
    assert build_session(due, new, remaining=10) == ["b", "c", "a", "n1", "n2", "n3"]
    assert build_session(due, new, remaining=4) == ["b", "c", "a", "n1"]
    assert build_session(due, new, remaining=0) == []
    assert build_session([], new, remaining=2) == ["n1", "n2"]


def test_build_session_ties_keep_input_order():
    from analysis.puzzles.spaced_repetition import build_session
    due = [(d(2), "newer_id"), (d(2), "older_id")]
    assert build_session(due, [], remaining=5) == ["newer_id", "older_id"]


def test_streak_counts_consecutive_days_meeting_target():
    from analysis.puzzles.spaced_repetition import streak
    counts = {d(0): 10, d(1): 12, d(2): 10, d(3): 3, d(4): 10}
    assert streak(counts, target=10, today=T) == 3          # today, -1, -2; -3 breaks it


def test_streak_survives_an_unfinished_today():
    from analysis.puzzles.spaced_repetition import streak
    counts = {d(0): 2, d(1): 10, d(2): 10}
    assert streak(counts, target=10, today=T) == 2          # yesterday + the day before


def test_streak_zero_when_neither_today_nor_yesterday_met_target():
    from analysis.puzzles.spaced_repetition import streak
    assert streak({d(2): 10, d(3): 10}, target=10, today=T) == 0
    assert streak({}, target=10, today=T) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: 5 new tests FAIL with `ImportError: cannot import name 'build_session'` / `'streak'`

- [ ] **Step 3: Write the minimal implementation** (append to `analysis/puzzles/spaced_repetition.py`)

```python
from typing import Mapping, TypeVar

T = TypeVar("T")


def build_session(due: Sequence[tuple[date, T]], new: Sequence[T], remaining: int) -> list[T]:
    """Due first (most overdue first, stable), then new, cut to `remaining`."""
    if remaining <= 0:
        return []
    ordered_due = [item for _, item in sorted(due, key=lambda pair: pair[0])]
    return (ordered_due + list(new))[:remaining]


def streak(counts_by_day: Mapping[date, int], target: int, today: date) -> int:
    """Consecutive days meeting `target`, ending today or (if today is not
    finished yet) yesterday."""
    day = today if counts_by_day.get(today, 0) >= target else today - timedelta(days=1)
    n = 0
    while counts_by_day.get(day, 0) >= target:
        n += 1
        day -= timedelta(days=1)
    return n
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
rtk git add analysis/puzzles/spaced_repetition.py tests/test_spaced_repetition.py && rtk git commit -q -m "feat(puzzles): session composition (due first) and daily streak

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: DB helpers — `get_attempt_log`, `count_puzzles_created_since`

**Files:**
- Modify: `db/puzzles.py` (append after `get_attempts`, around line 199)
- Test: `tests/test_puzzle_feed.py` (new file; the DB fixture built here is reused by Tasks 4–5)

**Interfaces:**
- Produces: `get_attempt_log(*, category: str | None = None) -> list[dict]` — every attempt joined to its puzzle, keys `puzzle_id`, `attempted_at`, `verdict`, `category`, ordered by attempt id asc. `count_puzzles_created_since(*, author: str, category: str, since_iso: str) -> int` — puzzles with that author+category and `created_at >= since_iso` (string compare on the `Z` ISO form).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_puzzle_feed.py
"""Daily feed for the puzzle trainer (T1.1, 2026-09-21) -- tmp DB only.

The conftest live-DB guard points db.database.DB_PATH at an empty tmp file;
`puzzle_db` initialises the schema and seeds puzzles + attempts with
controllable dates. Spec: docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

TODAY = date(2026, 9, 21)


def _utc_iso(day: date, hour: int = 12) -> str:
    """A UTC 'Z' timestamp that falls on `day` in LOCAL time (noon local)."""
    local = datetime.combine(day, time(hour)).astimezone()
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scene():
    return {"arena_match_id": "x", "game_num": 1, "turn_num": 1, "play_or_draw": "draw",
            "you": {"name": "You", "life": 20}, "opp": {"name": "Opp", "life": 20}}


@pytest.fixture
def puzzle_db():
    from db.database import init_db, get_connection
    from db import puzzles as db_puzzles
    init_db()
    db_puzzles._ensure_tables()

    def add_puzzle(category="drill_outs", author="seeder"):
        return db_puzzles.save_puzzle(
            deck_id=None, arena_match_id=None, game_num=None, turn_num=1,
            category=category, difficulty=2, question=f"q-{category}",
            solution_text="42", solution_keywords=[], grading_mode="number",
            author=author, notes="", scene=_scene())

    def add_attempt(puzzle_id, day, verdict="correct"):
        with get_connection() as con:
            con.execute(
                "INSERT INTO puzzle_attempts (puzzle_id, attempted_at, user_answer, verdict, grader_used) "
                "VALUES (?,?,?,?,?)", (puzzle_id, _utc_iso(day), "42", verdict, "self"))

    return {"add_puzzle": add_puzzle, "add_attempt": add_attempt}


def test_get_attempt_log_joins_category_and_orders_by_id(puzzle_db):
    from db import puzzles as db_puzzles
    p1 = puzzle_db["add_puzzle"]("drill_outs")
    p2 = puzzle_db["add_puzzle"]("find_lethal")
    puzzle_db["add_attempt"](p2, TODAY - timedelta(days=1), "incorrect")
    puzzle_db["add_attempt"](p1, TODAY, "correct")
    log = db_puzzles.get_attempt_log()
    assert [(r["puzzle_id"], r["verdict"], r["category"]) for r in log] == \
        [(p2, "incorrect", "find_lethal"), (p1, "correct", "drill_outs")]
    assert [r["puzzle_id"] for r in db_puzzles.get_attempt_log(category="drill_outs")] == [p1]
    assert all(r["attempted_at"].endswith("Z") for r in log)


def test_count_puzzles_created_since(puzzle_db):
    from db import puzzles as db_puzzles
    puzzle_db["add_puzzle"]("drill_outs", author="drill_generator")
    puzzle_db["add_puzzle"]("drill_outs", author="drill_generator")
    puzzle_db["add_puzzle"]("drill_outs", author="seeder")
    puzzle_db["add_puzzle"]("find_lethal", author="drill_generator")
    since = "2000-01-01T00:00:00Z"
    assert db_puzzles.count_puzzles_created_since(author="drill_generator", category="drill_outs", since_iso=since) == 2
    assert db_puzzles.count_puzzles_created_since(author="drill_generator", category="drill_outs", since_iso="2999-01-01T00:00:00Z") == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py -q -p no:cacheprovider`
Expected: 2 FAIL with `AttributeError: module 'db.puzzles' has no attribute 'get_attempt_log'` / `'count_puzzles_created_since'`

- [ ] **Step 3: Write the minimal implementation** (insert in `db/puzzles.py` right after `get_attempts`)

```python
def get_attempt_log(*, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Every attempt with its puzzle's category, oldest first. One query for
    the whole feed instead of one `get_attempts` per puzzle."""
    _ensure_tables()
    sql = ("SELECT a.puzzle_id, a.attempted_at, a.verdict, p.category "
           "FROM puzzle_attempts a JOIN puzzles p ON p.id = a.puzzle_id")
    params: list[Any] = []
    if category:
        sql += " WHERE p.category = ?"; params.append(category)
    sql += " ORDER BY a.id ASC"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_puzzles_created_since(*, author: str, category: str, since_iso: str) -> int:
    """Puzzles by `author` in `category` created at/after `since_iso` (UTC 'Z')."""
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM puzzles WHERE author = ? AND category = ? AND created_at >= ?",
            (author, category, since_iso)).fetchone()
    return int(row[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py -q -p no:cacheprovider`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
rtk git add db/puzzles.py tests/test_puzzle_feed.py && rtk git commit -q -m "feat(puzzles): attempt-log and created-since query helpers for the daily feed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Feed without top-up — `attempt_date`, `todays_feed(top_up=False)`, `daily_stats`

**Files:**
- Create: `analysis/puzzles/feed.py`
- Test: `tests/test_puzzle_feed.py`

**Interfaces:**
- Consumes: `schedule_for`, `build_session`, `streak` (Tasks 1–2); `db_puzzles.get_puzzles`, `get_attempt_log` (Task 3).
- Produces:
  - `attempt_date(ts: str) -> date` — UTC `Z` ISO → local calendar date.
  - `Feed(puzzles: list[dict], done_today: int, due_count: int, new_count: int, generated: int, remaining: int, next_due: date | None)`.
  - `DailyStats(done_today: int, due_count: int, new_count: int, streak: int)`.
  - `todays_feed(category: str | None, target: int, today: date | None = None, *, top_up: bool = True) -> Feed`.
  - `daily_stats(target: int, today: date | None = None, category: str | None = None) -> DailyStats`.
  - `due_count` / `new_count` are the totals in the category (not truncated); `done_today` and `streak` count attempts today in **any** category; `next_due` is the earliest `scheduled` due date in the category (None if none).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_puzzle_feed.py`)

```python
def test_attempt_date_converts_utc_z_to_local_day():
    from analysis.puzzles.feed import attempt_date
    assert attempt_date(_utc_iso(TODAY)) == TODAY
    assert attempt_date(_utc_iso(TODAY - timedelta(days=3))) == TODAY - timedelta(days=3)


def test_feed_orders_due_before_new_and_never_repeats_today(puzzle_db):
    from analysis.puzzles.feed import todays_feed
    add_p, add_a = puzzle_db["add_puzzle"], puzzle_db["add_attempt"]
    solved_today = add_p()                       # attempted today -> excluded
    add_a(solved_today, TODAY, "correct")
    due_3d = add_p()                             # rung 1, due = -3d + 3 = today
    add_a(due_3d, TODAY - timedelta(days=3))
    overdue = add_p()                            # missed 5 days ago -> due 4 days ago
    add_a(overdue, TODAY - timedelta(days=5), "incorrect")
    scheduled = add_p()                          # correct yesterday -> due in 2 days
    add_a(scheduled, TODAY - timedelta(days=1))
    retired = add_p()                            # six corrects
    for k in range(6, 0, -1):
        add_a(retired, TODAY - timedelta(days=100 * k))
    new_old = add_p()
    new_newest = add_p()

    feed = todays_feed(None, target=10, today=TODAY, top_up=False)
    assert [p["id"] for p in feed.puzzles] == [overdue, due_3d, new_newest, new_old]
    assert (feed.done_today, feed.due_count, feed.new_count, feed.generated) == (1, 2, 2, 0)
    assert feed.remaining == 9
    assert feed.next_due == TODAY + timedelta(days=2)


def test_feed_truncates_to_remaining_and_zero_when_target_met(puzzle_db):
    from analysis.puzzles.feed import todays_feed
    add_p, add_a = puzzle_db["add_puzzle"], puzzle_db["add_attempt"]
    ids = [add_p() for _ in range(5)]
    for pid in ids[:3]:
        add_a(pid, TODAY)
    feed = todays_feed(None, target=4, today=TODAY, top_up=False)
    assert feed.remaining == 1 and [p["id"] for p in feed.puzzles] == [ids[4]]
    feed = todays_feed(None, target=3, today=TODAY, top_up=False)
    assert feed.remaining == 0 and feed.puzzles == []


def test_feed_respects_category_filter_but_counts_done_today_globally(puzzle_db):
    from analysis.puzzles.feed import todays_feed
    add_p, add_a = puzzle_db["add_puzzle"], puzzle_db["add_attempt"]
    drill = add_p("drill_outs")
    lethal = add_p("find_lethal")
    add_a(lethal, TODAY)
    feed = todays_feed("drill_outs", target=5, today=TODAY, top_up=False)
    assert [p["id"] for p in feed.puzzles] == [drill]
    assert feed.done_today == 1 and feed.remaining == 4


def test_daily_stats_streak_uses_attempt_counts_per_local_day(puzzle_db):
    from analysis.puzzles.feed import daily_stats
    add_p, add_a = puzzle_db["add_puzzle"], puzzle_db["add_attempt"]
    pid = add_p()
    for back in (1, 2):                          # two full days before today
        for _ in range(2):
            add_a(pid, TODAY - timedelta(days=back))
    add_a(pid, TODAY)                            # today unfinished (1 < 2)
    st = daily_stats(target=2, today=TODAY)
    assert (st.done_today, st.streak) == (1, 2)
    assert st.new_count == 0 and st.due_count == 0   # pid attempted today -> not due
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py -q -p no:cacheprovider`
Expected: 5 new tests FAIL with `ModuleNotFoundError: No module named 'analysis.puzzles.feed'`

- [ ] **Step 3: Write the minimal implementation**

```python
# analysis/puzzles/feed.py
"""Today's puzzle feed (T1.1, 2026-09-21). DB-aware, Qt-free.

Reads `puzzles` + `puzzle_attempts`, classifies every puzzle with
`spaced_repetition.schedule_for`, and returns the ordered session: due
reviews first (most overdue first), then never-seen puzzles, cut to what is
left of today's target. Nothing attempted today is served again today.
Spec: docs/superpowers/specs/2026-09-21-puzzle-spaced-repetition-design.md
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional

from analysis.puzzles.spaced_repetition import build_session, schedule_for, streak
from db import puzzles as db_puzzles

DRILL_CATEGORY = "drill_outs"
DRILL_AUTHOR = "drill_generator"


def attempt_date(ts: str) -> date:
    """`'2026-09-22T04:35:11Z'` (UTC, as db.puzzles writes it) -> local calendar day."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


@dataclass
class Feed:
    puzzles: list[dict]
    done_today: int
    due_count: int
    new_count: int
    generated: int
    remaining: int
    next_due: Optional[date]


@dataclass
class DailyStats:
    done_today: int
    due_count: int
    new_count: int
    streak: int


def _attempts_by_puzzle(category: Optional[str]) -> dict[int, list[tuple[date, str]]]:
    out: dict[int, list[tuple[date, str]]] = defaultdict(list)
    for r in db_puzzles.get_attempt_log(category=category):
        out[r["puzzle_id"]].append((attempt_date(r["attempted_at"]), r["verdict"]))
    return out


def _counts_by_day() -> Counter:
    return Counter(attempt_date(r["attempted_at"]) for r in db_puzzles.get_attempt_log())


def todays_feed(category: Optional[str], target: int, today: Optional[date] = None,
                *, top_up: bool = True) -> Feed:
    today = today or date.today()
    done_today = _counts_by_day().get(today, 0)
    remaining = max(0, int(target) - done_today)

    puzzles = db_puzzles.get_puzzles(category=category)          # newest first (id desc)
    attempts = _attempts_by_puzzle(category)
    due: list[tuple[date, dict]] = []
    new: list[dict] = []
    next_due: Optional[date] = None
    for p in puzzles:
        hist = attempts.get(p["id"], [])
        if any(day == today for day, _ in hist):
            continue                                              # never twice in one day
        s = schedule_for(hist, today)
        if s.state == "due":
            due.append((s.due, p))
        elif s.state == "new":
            new.append(p)
        elif s.state == "scheduled" and (next_due is None or s.due < next_due):
            next_due = s.due

    session = build_session(due, new, remaining)
    generated = 0
    if top_up and len(session) < remaining and category in (None, DRILL_CATEGORY):
        generated = _top_up(remaining - len(session), today)
        if generated:
            fresh = [p for p in db_puzzles.get_puzzles(category=DRILL_CATEGORY)
                     if p["id"] not in {q["id"] for q in session}
                     and p["id"] not in attempts][:generated]
            new = fresh + new
            session = build_session(due, new, remaining)
    return Feed(session, done_today, len(due), len(new), generated, remaining, next_due)


def daily_stats(target: int, today: Optional[date] = None,
                category: Optional[str] = None) -> DailyStats:
    today = today or date.today()
    feed = todays_feed(category, target, today, top_up=False)
    return DailyStats(feed.done_today, feed.due_count, feed.new_count,
                      streak(_counts_by_day(), int(target), today))


def _top_up(shortfall: int, today: date) -> int:
    """Task 5 fills this in; until then the feed never generates."""
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: `18 passed`

- [ ] **Step 5: Commit**

```bash
rtk git add analysis/puzzles/feed.py tests/test_puzzle_feed.py && rtk git commit -q -m "feat(puzzles): daily feed -- due reviews first, never twice a day, daily stats + streak

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Drill top-up

**Files:**
- Modify: `analysis/puzzles/feed.py` (`_top_up`)
- Test: `tests/test_puzzle_feed.py`

**Interfaces:**
- Consumes: `analysis.puzzles.drill_generator.generate_drills(conn, n, *, seed) -> list[Drill]` (fields: `difficulty, question, solution_text, solution_keywords, scene, notes, params, turn_num, grading_mode, category`); `db_puzzles.save_puzzle(...)`; `db_puzzles.count_puzzles_created_since`.
- Produces: `_top_up(shortfall: int, today: date) -> int` — number of drills persisted (0 when `generate_drills` raises `RuntimeError`, i.e. no sampleable decklists).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_puzzle_feed.py`)

```python
@pytest.fixture
def sampleable_deck(puzzle_db):
    """One 60-card Modern deck with card_data so drill_generator can sample it."""
    from db.database import upsert_event, upsert_deck, insert_deck_cards, get_connection
    eid = upsert_event(source="mtgtop8", source_id="evT", name="Modern Challenge T", date="2026-09-01",
                       fmt="modern", url="http://x/T", event_type="mtgo_challenge_32")
    did = upsert_deck(event_id=eid, source_id="dkT", player="pilot", archetype="Burn", placement=1, url="http://x/T/1")
    main = {"Mountain": 20, "Lightning Bolt": 4, "Monastery Swiftspear": 4, "Lava Spike": 4,
            "Rift Bolt": 4, "Skewer the Critics": 4, "Boros Charm": 4, "Eidolon of the Great Revel": 4,
            "Goblin Guide": 4, "Searing Blaze": 4, "Sacred Foundry": 4}
    assert sum(main.values()) == 60
    insert_deck_cards(did, main, {})
    with get_connection() as con:
        for name in main:
            tl = "Land" if name in ("Mountain", "Sacred Foundry") else "Instant"
            con.execute("INSERT OR REPLACE INTO card_data (name, type_line) VALUES (?,?)", (name, tl))
    return did


def test_top_up_generates_exactly_the_shortfall_for_drills(puzzle_db, sampleable_deck):
    from analysis.puzzles.feed import todays_feed
    from db import puzzles as db_puzzles
    puzzle_db["add_puzzle"]("drill_outs")                      # one existing new drill
    feed = todays_feed("drill_outs", target=4, today=TODAY)
    assert feed.generated == 3 and len(feed.puzzles) == 4
    made = [p for p in db_puzzles.get_puzzles(category="drill_outs") if p["author"] == "drill_generator"]
    assert len(made) == 3 and all(p["grading_mode"] == "number" for p in made)


def test_top_up_is_idempotent_within_a_day_and_continues_the_sequence(puzzle_db, sampleable_deck, monkeypatch):
    """Same day + same target -> no second batch; target raised -> only the
    shortfall, from a seed that has advanced by the number already minted
    today (so the generator does not replay its first k drills)."""
    import analysis.puzzles.drill_generator as dg
    from analysis.puzzles.feed import todays_feed
    seeds = []
    real = dg.generate_drills
    monkeypatch.setattr(dg, "generate_drills",
                        lambda conn, n, *, seed: seeds.append((n, seed)) or real(conn, n, seed=seed))
    first = todays_feed("drill_outs", target=3, today=TODAY)
    assert first.generated == 3
    again = todays_feed("drill_outs", target=3, today=TODAY)   # same day, same target
    assert again.generated == 0 and [p["id"] for p in again.puzzles] == [p["id"] for p in first.puzzles]
    raised = todays_feed("drill_outs", target=5, today=TODAY)  # target raised -> just the shortfall
    assert raised.generated == 2 and len(raised.puzzles) == 5
    day = int(TODAY.strftime("%Y%m%d")) * 1000
    assert seeds == [(3, day + 0), (2, day + 3)]


def test_top_up_never_fires_for_positional_categories(puzzle_db, sampleable_deck):
    from analysis.puzzles.feed import todays_feed
    feed = todays_feed("find_lethal", target=5, today=TODAY)
    assert feed.generated == 0 and feed.puzzles == []


def test_top_up_is_silent_when_no_decklists_are_sampleable(puzzle_db):
    from analysis.puzzles.feed import todays_feed
    feed = todays_feed(None, target=5, today=TODAY)          # empty DB: nothing to ground drills in
    assert feed.generated == 0 and feed.puzzles == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py -q -p no:cacheprovider -k top_up`
Expected: `test_top_up_generates_exactly_the_shortfall_for_drills` and `..._idempotent...` FAIL (`generated == 0`); the two "never fires"/"silent" tests PASS already (that is expected — they pin the guard rails).

- [ ] **Step 3: Write the implementation** (replace the `_top_up` stub in `analysis/puzzles/feed.py`)

```python
def _local_midnight_utc_iso(today: date) -> str:
    local_midnight = datetime.combine(today, time(0)).astimezone()
    return local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _top_up(shortfall: int, today: date) -> int:
    """Generate `shortfall` outs-math drills grounded in real decklists and
    persist them exactly as scripts/seed_drills.py does. The seed advances
    with the number already minted today, so a second top-up (target raised,
    Keep going) continues the sequence instead of repeating the first k."""
    from analysis.puzzles.drill_generator import generate_drills
    from db.database import get_connection
    if shortfall <= 0:
        return 0
    already = db_puzzles.count_puzzles_created_since(
        author=DRILL_AUTHOR, category=DRILL_CATEGORY, since_iso=_local_midnight_utc_iso(today))
    seed = int(today.strftime("%Y%m%d")) * 1000 + already
    try:
        with get_connection() as conn:
            drills = generate_drills(conn, n=shortfall, seed=seed)
    except (RuntimeError, sqlite3.OperationalError):
        # RuntimeError: no sampleable 60-card decklists (house rule 8 -- never
        # fabricate). OperationalError: a DB without the decks schema at all
        # (tests that only create the puzzle tables). Either way the feed just
        # runs short; nothing is minted.
        return 0
    for d in drills:
        db_puzzles.save_puzzle(
            deck_id=None, arena_match_id=None, game_num=None, turn_num=d.turn_num,
            category=d.category, difficulty=d.difficulty, question=d.question,
            solution_text=d.solution_text, solution_keywords=d.solution_keywords,
            grading_mode=d.grading_mode, author=DRILL_AUTHOR, notes=d.notes, scene=d.scene)
    return len(drills)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzle_feed.py tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: `22 passed`. If the idempotency test fails on `len(set(questions)) == 5`, the seeds collided: confirm `count_puzzles_created_since` sees the first batch (created_at is UTC `Z`, `since_iso` is local midnight in UTC) — that is the only moving part.

- [ ] **Step 5: Commit**

```bash
rtk git add analysis/puzzles/feed.py tests/test_puzzle_feed.py && rtk git commit -q -m "feat(puzzles): auto top-up outs drills when the daily feed runs short (deterministic per day)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Solve tab — target spinbox, header, feed-driven queue, done state

**Files:**
- Modify: `gui/state_keys.py` (append near the other `tabs.*` keys)
- Modify: `gui/tabs/puzzles.py` — `__init__` (line 35), `_build_solve_panel` top row (lines 61–70), `_load_next_puzzle` (lines 179–202), `_refresh_stats` (line 321), add `showEvent`
- Test: `tests/test_puzzles_tab.py`

**Interfaces:**
- Consumes: `todays_feed`, `daily_stats` (Tasks 4–5); `UIState.instance().get/set`; new key `PUZZLES_DAILY_TARGET`.
- Produces (for tests): `PuzzlesTab._target_spin: QSpinBox`, `PuzzlesTab._keep_going_btn: QPushButton`, header text via the existing `_stats_lbl`, done-state text in `_question_lbl`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_puzzles_tab.py`; the existing `_offscreen_qt` autouse fixture and the conftest tmp-DB guard apply)

```python
def _seed_drills(n):
    from db import puzzles
    ids = []
    for i in range(n):
        ids.append(puzzles.save_puzzle(
            deck_id=None, arena_match_id=None, game_num=None, turn_num=1,
            category="drill_outs", difficulty=1, question=f"Drill {i}: odds?",
            solution_text="42", solution_keywords=[], grading_mode="number",
            author="seeder", notes="", scene={
                "arena_match_id": "drill", "game_num": 0, "turn_num": 1, "play_or_draw": "draw",
                "you": {"name": "You", "life": 20}, "opp": {"name": "Opp", "life": 20}}))
    return ids


def test_solve_header_shows_daily_progress_and_target_spinbox(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.setattr("gui.state.UIState._instance", None)   # fresh singleton, as tests/test_ui_state.py does
    from db.database import init_db; init_db()
    _seed_drills(3)
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    assert tab._target_spin.value() == 10                      # default
    assert "Today 0/10" in tab._stats_lbl.text()
    assert "3 new" in tab._stats_lbl.text()
    tab._target_spin.setValue(2)
    assert "Today 0/2" in tab._stats_lbl.text()
    from gui.state import UIState
    from gui.state_keys import PUZZLES_DAILY_TARGET
    assert UIState.instance().get(PUZZLES_DAILY_TARGET) == 2


def test_solve_reaches_done_state_and_keep_going_serves_more(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.setattr("gui.state.UIState._instance", None)
    from db.database import init_db; init_db()
    _seed_drills(3)
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    tab._target_spin.setValue(1)
    assert "Drill 2" in tab._question_lbl.text()               # newest first
    tab._record_and_next("correct")
    assert "Done for today" in tab._question_lbl.text()
    assert "Today 1/1" in tab._stats_lbl.text()
    assert tab._keep_going_btn.isVisibleTo(tab)
    tab._keep_going_btn.click()
    assert "Drill 1" in tab._question_lbl.text()               # next new one, target raised in memory
    assert tab._target_spin.value() == 1                       # persisted target untouched
    tab._record_and_next("incorrect")                          # a miss: comes back tomorrow, not now
    assert "Done for today" in tab._question_lbl.text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzles_tab.py -q -p no:cacheprovider`
Expected: the 2 new tests FAIL with `AttributeError: 'PuzzlesTab' object has no attribute '_target_spin'`; the 3 existing tests still PASS.

- [ ] **Step 3: Add the state key** (`gui/state_keys.py`, after the Scout block)

```python
# Puzzles
PUZZLES_DAILY_TARGET = "tabs.puzzles.daily_target"  # int 1-50; Solve tab daily session target
```

- [ ] **Step 4: Wire the Solve tab** (`gui/tabs/puzzles.py`)

Imports (top of file, with the other project imports):

```python
from datetime import date

from PyQt6.QtWidgets import QSpinBox   # add to the existing PyQt6.QtWidgets import list
from analysis.puzzles.feed import todays_feed, daily_stats
from gui.state import UIState
from gui.state_keys import PUZZLES_DAILY_TARGET
```

`__init__` — add one attribute before `_build_ui()`:

```python
        self._target_override: Optional[int] = None   # "Keep going" raises the target in memory only
```

`_build_solve_panel` — replace the `top` row block (from `top = QHBoxLayout()` through `v.addLayout(top)`) with:

```python
        top = QHBoxLayout()
        self._category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._category_combo.addItem(label, value)
        self._category_combo.currentIndexChanged.connect(self._on_category_changed)
        top.addWidget(QLabel("Category:"))
        top.addWidget(self._category_combo)
        top.addSpacing(12)
        top.addWidget(QLabel("Daily target:"))
        self._target_spin = QSpinBox()
        self._target_spin.setRange(1, 50)
        self._target_spin.setValue(10)
        self._target_spin.setToolTip("Puzzles per day. Reviews that are due come first, then new ones; "
                                     "outs-math drills are generated when the feed runs short.")
        self._target_spin.valueChanged.connect(self._on_target_changed)
        top.addWidget(self._target_spin)
        top.addStretch(1)
        self._stats_lbl = QLabel("")
        top.addWidget(self._stats_lbl)
        v.addLayout(top)
```

In the right column, right after the `verdict_row` block (before `splitter.addWidget(right)`):

```python
        self._keep_going_btn = QPushButton("Keep going →")
        self._keep_going_btn.setToolTip("Serve more reviews / new puzzles beyond today's target "
                                        "(the saved target is not changed).")
        self._keep_going_btn.clicked.connect(self._on_keep_going)
        self._keep_going_btn.hide()
        right_v.addWidget(self._keep_going_btn)
```

Replace `_on_category_changed` / `_load_next_puzzle` and add the new slots:

```python
    def _on_category_changed(self, _idx: int) -> None:
        self._load_next_puzzle()

    def _on_target_changed(self, value: int) -> None:
        self._target_override = None
        UIState.instance().set(PUZZLES_DAILY_TARGET, int(value))
        self._load_next_puzzle()

    def _on_keep_going(self) -> None:
        stats = daily_stats(self._effective_target(), date.today(),
                            self._category_combo.currentData() or None)
        self._target_override = stats.done_today + 1
        self._load_next_puzzle()

    def _effective_target(self) -> int:
        return self._target_override or int(self._target_spin.value())

    def _load_next_puzzle(self) -> None:
        cat = self._category_combo.currentData() or None
        feed = todays_feed(cat, self._effective_target(), date.today())
        self._refresh_stats()
        self._keep_going_btn.hide()
        if not feed.puzzles:
            self._current_puzzle = None
            if feed.remaining == 0:
                nxt = (f"next reviews due {feed.next_due.isoformat()}" if feed.next_due
                       else "nothing scheduled yet")
                self._question_lbl.setText(
                    f"<b style='color:#80c890;'>Done for today ✓</b> "
                    f"<span style='color:{theme.TEXT_DIM};'>— {nxt}</span>")
                self._keep_going_btn.show()
            else:
                self._question_lbl.setText(
                    f"<i style='color:{theme.TEXT_DIM};'>Queue is empty. "
                    "Promote a candidate from the Inbox tab or run "
                    "scripts/scan_for_puzzles.py to populate it.</i>")
            self._answer_edit.clear(); self._answer_edit.setEnabled(False)
            self._reveal_btn.setEnabled(False)
            self._solution_lbl.hide()
            self._verdict_chip.hide()
            self._got_it_btn.hide(); self._missed_btn.hide()
            self._scene_widget.set_scene(_empty_scene())
            self._apply_board_layout(boardless=True)
            return
        puzzle = feed.puzzles[0]
        self._current_puzzle = puzzle
        self._render_puzzle(puzzle)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        self._hydrated_state = True
        saved = UIState.instance().get(PUZZLES_DAILY_TARGET)
        if saved is not None and hasattr(self, "_target_spin"):
            self._target_spin.blockSignals(True)
            self._target_spin.setValue(max(1, min(50, int(saved))))
            self._target_spin.blockSignals(False)
            self._load_next_puzzle()
```

Replace `_refresh_stats`:

```python
    def _refresh_stats(self) -> None:
        target = self._effective_target()
        today = daily_stats(target, date.today(), self._category_combo.currentData() or None)
        parts = [f"<b>Today {today.done_today}/{target}</b>"]
        if today.due_count:
            parts.append(f"{today.due_count} due")
        if today.new_count:
            parts.append(f"{today.new_count} new")
        if today.streak >= 2:
            parts.append(f"streak {today.streak}🔥")
        stats = db_puzzles.get_session_stats()
        wr_pct = stats["wr_overall"] * 100
        self._stats_lbl.setText(
            " · ".join(parts)
            + f" <span style='color:{theme.TEXT_DIM};'>| Session:</span> "
            f"<b style='color:#80c890;'>{stats['n_solved']} ✓</b> · "
            f"<b style='color:#d88060;'>{stats['n_missed']} ✗</b> · "
            f"{wr_pct:.0f}%"
            + self._rating_html()
        )
```

`_record_and_next` is unchanged (it already ends with `self._load_next_puzzle()`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_puzzles_tab.py tests/test_puzzle_feed.py tests/test_spaced_repetition.py -q -p no:cacheprovider`
Expected: all pass (5 tab tests + 22). `test_puzzles_tab_constructs_with_empty_db` (existing) constructs the tab on a DB that has ONLY the puzzle tables — the feed's top-up hits `no such table: decks`, which `_top_up` swallows (Task 5); if it does not, that catch is what broke. `test_puzzles_tab_renders_first_puzzle` seeds one never-attempted `stabilize` puzzle — `new`, so the feed serves it and the test must still pass; investigate before touching it.

- [ ] **Step 6: Commit**

```bash
rtk git add gui/state_keys.py gui/tabs/puzzles.py tests/test_puzzles_tab.py && rtk git commit -q -m "feat(puzzles): Solve tab runs on the daily feed -- target, Today n/N header, streak, done state + Keep going

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Live check, full suite, docs, final commit

**Files:**
- Modify: `CLAUDE.md` (new "Last updated" paragraph; previous becomes "Earlier"), `NEXT_STEPS.md` (9/21 afternoon block), `ROADMAP.md` (T1.1 line `[~]` → `[x]`, add a COMPLETED entry)

- [ ] **Step 1: Live check (read-only)** — the real DB has 49 puzzles and 6 attempts on 4 puzzles (all `correct`, 3+ days old), so the spec predicts 4 due + 6 new, 0 generated for target 10:

```bash
PYTHONIOENCODING=utf-8 python -c "
from datetime import date
from analysis.puzzles.feed import todays_feed, daily_stats
f = todays_feed(None, 10, date.today(), top_up=False)
print('feed:', [(p['id'], p['category']) for p in f.puzzles])
print('due', f.due_count, 'new', f.new_count, 'generated', f.generated, 'remaining', f.remaining, 'next_due', f.next_due)
print(daily_stats(10, date.today()))"
```

Expected: 10 puzzles listed, the 4 previously-solved ids first, `generated 0`, `remaining 10` (no attempts today). Record the actual numbers in the docs.

- [ ] **Step 2: Full suite**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_strategy_search_live.py 2>&1 | tail -2`
Expected: `NNN passed` (790 + 11 + 11 + 2 = 814), 0 failed, 0 skipped.

- [ ] **Step 3: Docs**

CLAUDE.md — new first paragraph `Last updated: 2026-09-21 (**Puzzle Trainer T1.1 -- spaced repetition + daily feed SHIPPED** ...)` naming the modules, the ladder, the derived-schedule decision, the top-up seed rule, the header/done-state UI, the live-check numbers and the suite count; the previous paragraph becomes `Earlier 2026-09-21:`. Also update the Puzzles bullet in §6 (after "**Puzzle Trainer v0 COMPLETE.**") with two sentences on the feed.
NEXT_STEPS.md — under "9/21 afternoon", replace the T1.1 line with `- **T1.1 spaced repetition SHIPPED** (...)`.
ROADMAP.md — `- [x] **T1.1 — spaced repetition + daily feed** (2026-09-21) — ...` and a `### 2026-09-21 — Puzzle Trainer T1.1 (spaced repetition + daily feed)` COMPLETED entry.

- [ ] **Step 4: Commit**

```bash
rtk git add CLAUDE.md NEXT_STEPS.md ROADMAP.md && rtk git commit -q -m "docs: puzzle trainer T1.1 shipped -- spaced repetition + daily feed

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

- **Spec coverage:** §1 ladder → Task 1; `build_session`/`streak` → Task 2; §2 rules 1–4, 6 and `daily_stats` → Task 4; rule 5 top-up + seed → Task 5; §3 UI (header, spinbox + persistence, done state, Keep going in-memory, empty-queue message kept) → Task 6; §4 behaviour changes fall out of Tasks 4/6 (`get_puzzles(unsolved_only=)` untouched, `seed_drills.py` untouched); §5 tests → Tasks 1–6, live check + suite + docs → Task 7.
- **Types:** `schedule_for(attempts, today) -> Schedule`, `build_session(due: [(date, T)], new, remaining)`, `streak(counts, target, today)`, `todays_feed(category, target, today=None, *, top_up=True) -> Feed`, `daily_stats(target, today=None) -> DailyStats`, `get_attempt_log(*, category=None)`, `count_puzzles_created_since(*, author, category, since_iso)` — used with these exact names/arities in every task.
- **Timezones:** attempts and puzzle `created_at` are UTC `Z`; `attempt_date` and `_local_midnight_utc_iso` do the local conversion; the test helper `_utc_iso(day)` produces noon-local so the mapping is unambiguous on any machine.
