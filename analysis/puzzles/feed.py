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
            seen = {q["id"] for q in session}
            fresh = [p for p in db_puzzles.get_puzzles(category=DRILL_CATEGORY)
                     if p["id"] not in seen and p["id"] not in attempts][:generated]
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
