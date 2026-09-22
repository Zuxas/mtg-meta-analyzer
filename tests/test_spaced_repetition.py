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
