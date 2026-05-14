"""Tests for scrapers.untapped_replay_fetcher.fetch_for_short_ids.

HTTP is mocked. The wrapper composes already-tested storage + indexing
primitives; what we exercise here is the dispatch logic, the
already-fetched skip, the no_content path, and the error path.
"""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    db_path = tmp_path / "fetcher.db"
    replay_dir = tmp_path / "replays"
    replay_dir.mkdir()
    # Disable real sleeps so the suite is fast.
    monkeypatch.setattr(
        "scrapers.untapped_replay_fetcher.time.sleep",
        lambda _: None,
    )
    return {"db": str(db_path), "replay_dir": str(replay_dir)}


def _fake_replay_payload():
    return {
        "deckId": "fake-deck-id",
        "userId": "fake-user",
        "playerId": "fake-player",
        "timestamp": 0,
        "decks": [{
            "game": 1,
            "deck": {
                "mainDeck": [79085] * 4,
                "sideboard": [],
                "name": "Fake Deck",
                "commanders": [],
                "wishboard": [],
            },
        }],
        "log": "",
    }


def test_fetch_for_short_ids_skips_already_cached(tmp_env, monkeypatch):
    from scrapers import untapped_replay_fetcher as urf

    # Seed one row in untapped_replays so the wrapper skips it
    con = sqlite3.connect(tmp_env["db"])
    urf.init_replay_schema(con)
    con.execute(
        "INSERT INTO untapped_replays "
        "(short_id, fetched_at_utc, file_path, status) "
        "VALUES (?, ?, ?, ?)",
        ("already-cached", "2026-05-14T00:00:00", "/tmp/fake.gz", "ok"),
    )
    con.commit()
    con.close()

    # Mock fetch_replay so unintended calls would be obvious
    calls = []
    def _mock_fetch(short_id, max_retries=3):
        calls.append(short_id)
        return 200, _fake_replay_payload()
    monkeypatch.setattr(urf, "fetch_replay", _mock_fetch)

    stats = urf.fetch_for_short_ids(
        ["already-cached"],
        replay_dir=tmp_env["replay_dir"],
        db_path=tmp_env["db"],
    )
    assert stats["skipped"] == 1
    assert stats["fetched"] == 0
    assert calls == []  # never called fetch_replay


def test_fetch_for_short_ids_pulls_and_indexes(tmp_env, monkeypatch):
    from scrapers import untapped_replay_fetcher as urf

    def _mock_fetch(short_id, max_retries=3):
        return 200, _fake_replay_payload()
    monkeypatch.setattr(urf, "fetch_replay", _mock_fetch)

    stats = urf.fetch_for_short_ids(
        ["fresh-1", "fresh-2"],
        replay_dir=tmp_env["replay_dir"],
        db_path=tmp_env["db"],
    )
    assert stats["fetched"] == 2
    assert stats["skipped"] == 0
    assert stats["no_content"] == 0
    assert stats["errors"] == 0
    # Files written
    assert (Path(tmp_env["replay_dir"]) / "fresh-1.json.gz").exists()
    assert (Path(tmp_env["replay_dir"]) / "fresh-2.json.gz").exists()
    # Rows indexed
    con = sqlite3.connect(tmp_env["db"])
    n = con.execute("SELECT COUNT(*) FROM untapped_replays").fetchone()[0]
    con.close()
    assert n == 2


def test_fetch_for_short_ids_handles_204_no_content(tmp_env, monkeypatch):
    from scrapers import untapped_replay_fetcher as urf

    def _mock_fetch(short_id, max_retries=3):
        return 204, None
    monkeypatch.setattr(urf, "fetch_replay", _mock_fetch)

    stats = urf.fetch_for_short_ids(
        ["gone-1"], replay_dir=tmp_env["replay_dir"], db_path=tmp_env["db"]
    )
    assert stats["no_content"] == 1
    assert stats["fetched"] == 0
    # File should NOT be written
    assert not (Path(tmp_env["replay_dir"]) / "gone-1.json.gz").exists()
    # But the no-content row should be indexed so we don't re-probe
    con = sqlite3.connect(tmp_env["db"])
    row = con.execute(
        "SELECT status FROM untapped_replays WHERE short_id=?", ("gone-1",)
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == "no_content_204"


def test_fetch_for_short_ids_records_errors(tmp_env, monkeypatch):
    from scrapers import untapped_replay_fetcher as urf

    def _mock_fetch(short_id, max_retries=3):
        raise RuntimeError("simulated http blowup")
    monkeypatch.setattr(urf, "fetch_replay", _mock_fetch)

    stats = urf.fetch_for_short_ids(
        ["broken-1"], replay_dir=tmp_env["replay_dir"], db_path=tmp_env["db"]
    )
    assert stats["errors"] == 1
    assert stats["fetched"] == 0


def test_fetch_for_short_ids_progress_callback(tmp_env, monkeypatch):
    from scrapers import untapped_replay_fetcher as urf

    def _mock_fetch(short_id, max_retries=3):
        return 200, _fake_replay_payload()
    monkeypatch.setattr(urf, "fetch_replay", _mock_fetch)

    progress = []
    def _cb(i, total, sid, status):
        progress.append((i, total, sid, status))

    stats = urf.fetch_for_short_ids(
        ["a", "b", "c"],
        replay_dir=tmp_env["replay_dir"],
        db_path=tmp_env["db"],
        progress_callback=_cb,
    )
    assert stats["fetched"] == 3
    assert len(progress) == 3
    assert all(p[3] == "ok" for p in progress)
    assert [p[2] for p in progress] == ["a", "b", "c"]


def test_fetch_for_short_ids_empty_input_is_no_op(tmp_env):
    from scrapers import untapped_replay_fetcher as urf
    stats = urf.fetch_for_short_ids(
        [], replay_dir=tmp_env["replay_dir"], db_path=tmp_env["db"]
    )
    assert stats == {"fetched": 0, "no_content": 0, "skipped": 0,
                     "errors": 0, "total_raw_bytes": 0, "total_gz_bytes": 0}
