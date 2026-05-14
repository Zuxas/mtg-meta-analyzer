"""Tests for scrapers.untapped_match_log_writer.

Uses a synthetic minimal replay JSON fixture (not the full Untapped schema)
to verify the writer extracts what it needs and writes match_log rows."""
import gzip
import json
import sqlite3
import pytest


@pytest.fixture
def seeded_replays(tmp_path, monkeypatch):
    """Build a temp DB + replay dir with one fixture replay."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))

    from db.match_log import _ensure_table
    _ensure_table()
    import db.saved_decks
    db.saved_decks._ensure_tables()

    # Seed card_data so my-deck classifier works
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS card_data "
                     "(name TEXT PRIMARY KEY, arena_id INTEGER)")
        conn.executemany(
            "INSERT INTO card_data (name, arena_id) VALUES (?, ?)",
            [("Llanowar Elves", 1003), ("Forest", 1002)],
        )

    db.saved_decks.save_deck(
        name="Mono Green Stompy", format_name="standard", archetype="Mono Green",
        mainboard={"Llanowar Elves": 4, "Forest": 20}, sideboard={},
    )

    replay_dir = tmp_path / "untapped_replays"
    replay_dir.mkdir()

    # Minimal replay fixture: enough log lines for the classifier to work.
    # The writer should read these via untapped_opponent_classifier primitives.
    replay = {
        "matchId": "test-match-001",
        "userId": "test-user-42",
        "log": "\n".join([
            '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": {"gameRoomConfig": '
            '{"reservedPlayers": [{"userId": "test-user-42", "systemSeatId": 1},'
            '{"userId": "opp-user", "systemSeatId": 2}]}}}}',
            # Player grpIds (my cards on battlefield)
            '{"greToClientEvent": {"greToClientMessages": [{"type": "GREMessageType_GameStateMessage",'
            '"gameStateMessage": {"gameObjects": ['
            '{"ownerSeatId": 1, "grpId": 1003},'
            '{"ownerSeatId": 1, "grpId": 1003},'
            '{"ownerSeatId": 1, "grpId": 1003},'
            '{"ownerSeatId": 1, "grpId": 1003},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            '{"ownerSeatId": 1, "grpId": 1002},'
            # Opponent grpIds (don't need to match any saved deck)
            '{"ownerSeatId": 2, "grpId": 9001},'
            '{"ownerSeatId": 2, "grpId": 9002}'
            ']}}]}}'
        ]),
        "matchResult": "win",
        "format": "Traditional_Standard",
        "matchDate": "2026-05-13",
    }
    rp = replay_dir / "test-match-001.json.gz"
    with gzip.open(rp, "wt", encoding="utf-8") as f:
        json.dump(replay, f)
    return db_path, replay_dir


def test_writer_creates_match_log_row(seeded_replays):
    db_path, replay_dir = seeded_replays
    from scrapers.untapped_match_log_writer import run
    n = run(replay_dir=replay_dir)
    assert n == 1
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM match_log").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "untapped"
    assert r["arena_match_id"] == "test-match-001"
    assert r["my_deck_id"] is not None  # classifier matched Mono Green
    assert r["my_variant_hash"] is not None
    assert r["backfill_status"] == "live"


def test_writer_dedups_by_arena_match_id(seeded_replays):
    _, replay_dir = seeded_replays
    from scrapers.untapped_match_log_writer import run
    assert run(replay_dir=replay_dir) == 1
    # Second run should not insert again
    assert run(replay_dir=replay_dir) == 0


def test_writer_marks_orphan_when_classifier_returns_none(tmp_path, monkeypatch):
    """If no saved_decks match the observed cards, the row still lands
    with backfill_status='orphan' and my_deck_id NULL."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    from db.match_log import _ensure_table
    _ensure_table()
    import db.saved_decks
    db.saved_decks._ensure_tables()
    # NO saved decks seeded -> classifier returns None
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS card_data "
                     "(name TEXT PRIMARY KEY, arena_id INTEGER)")

    replay_dir = tmp_path / "untapped_replays"
    replay_dir.mkdir()
    replay = {
        "matchId": "orphan-1", "userId": "u",
        "log": '{"matchGameRoomStateChangedEvent": {"gameRoomInfo": '
               '{"gameRoomConfig": {"reservedPlayers": '
               '[{"userId": "u", "systemSeatId": 1},'
               '{"userId": "o", "systemSeatId": 2}]}}}}',
        "matchResult": "loss", "format": "Traditional_Standard",
        "matchDate": "2026-05-13",
    }
    rp = replay_dir / "orphan-1.json.gz"
    with gzip.open(rp, "wt", encoding="utf-8") as f:
        json.dump(replay, f)

    from scrapers.untapped_match_log_writer import run
    assert run(replay_dir=replay_dir) == 1
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM match_log").fetchone()
    assert r["my_deck_id"] is None
    assert r["backfill_status"] == "orphan"
