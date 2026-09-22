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
