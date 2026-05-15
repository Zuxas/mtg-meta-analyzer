"""Tests for db.rank_snapshots."""
import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "ranks.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    return db_path


def test_rank_score_ordering():
    from db.rank_snapshots import rank_score
    assert rank_score("Bronze", 1) < rank_score("Silver", 1)
    assert rank_score("Silver", 4) < rank_score("Gold", 1)
    assert rank_score("Diamond", 1) < rank_score("Diamond", 4)
    assert rank_score("Diamond", 4) < rank_score("Mythic", 1)


def test_save_and_get_latest(env):
    from db.rank_snapshots import save_snapshot, get_latest
    save_snapshot("constructed", 89, "Platinum", 3, 25, 28,
                  captured_at_utc="2026-05-14T10:00:00")
    save_snapshot("constructed", 89, "Platinum", 2, 27, 28,
                  captured_at_utc="2026-05-14T18:00:00")
    latest = get_latest("constructed")
    assert latest["class"] == "Platinum"
    assert latest["level"] == 2
    assert latest["wins"] == 27


def test_delta_today_climb(env):
    from db.rank_snapshots import save_snapshot, delta_today
    from datetime import date
    today = date.today().isoformat()
    save_snapshot("constructed", 89, "Platinum", 4, 25, 28,
                  captured_at_utc=f"{today}T08:00:00")
    save_snapshot("constructed", 89, "Diamond", 1, 28, 28,
                  captured_at_utc=f"{today}T20:00:00")
    delta = delta_today("constructed")
    assert delta is not None
    assert delta["start_class"] == "Platinum"
    assert delta["end_class"] == "Diamond"
    assert delta["rank_delta"] > 0  # climbed
    assert delta["wins_today"] == 3
    assert delta["losses_today"] == 0


def test_delta_today_returns_none_for_no_snapshots(env):
    from db.rank_snapshots import delta_today
    assert delta_today("constructed") is None


def test_get_recent_returns_newest_first(env):
    from db.rank_snapshots import save_snapshot, get_recent
    save_snapshot("constructed", 89, "Bronze", 1, 0, 0,
                  captured_at_utc="2026-05-01T00:00:00")
    save_snapshot("constructed", 89, "Silver", 1, 5, 4,
                  captured_at_utc="2026-05-07T00:00:00")
    save_snapshot("constructed", 89, "Gold", 1, 10, 8,
                  captured_at_utc="2026-05-14T00:00:00")
    rows = get_recent("constructed", limit=5)
    assert len(rows) == 3
    assert rows[0]["class"] == "Gold"  # newest first
    assert rows[-1]["class"] == "Bronze"
