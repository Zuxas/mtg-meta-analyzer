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
from typing import Mapping, Optional, Sequence, TypeVar

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
