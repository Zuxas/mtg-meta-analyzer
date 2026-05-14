"""Tests for db.untapped_decklists -- per-player decklist storage."""
import gzip
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest


def _seed_card_db(db_path):
    """Create a minimal untapped_card_db with a few grpid->name mappings."""
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS untapped_card_db (
            grpid INTEGER PRIMARY KEY,
            title_id INTEGER,
            name TEXT,
            set_code TEXT,
            collector_number TEXT,
            rarity INTEGER,
            casting_cost TEXT,
            cmc REAL,
            types TEXT,
            last_refreshed_utc TEXT
        )
    """)
    con.executemany(
        "INSERT OR REPLACE INTO untapped_card_db (grpid, name) VALUES (?, ?)",
        [
            (79085, "Lightning Helix"),
            (79086, "Lightning Helix"),  # alt-art same name
            (82326, "Boros Charm"),
            (82327, "Boros Charm"),
            (82747, "Sacred Foundry"),
            (82853, "Path to Exile"),  # in sideboard
            (86781, "Rest in Peace"),  # in sideboard
        ],
    )
    con.commit()
    con.close()


def _make_replay_gz(replay_dir: Path, short_id: str,
                    main_grpids: list, side_grpids: list):
    replay_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "deckId": "test-deck-id",
        "userId": "test-user",
        "decks": [
            {
                "game": 1,
                "deck": {
                    "mainDeck": main_grpids,
                    "sideboard": side_grpids,
                    "name": "Test Deck",
                    "commanders": [],
                    "wishboard": [],
                },
            }
        ],
        "log": "",
        "timestamp": 0,
    }
    path = replay_dir / f"{short_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "decklists.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    _seed_card_db(db_path)
    return db_path


def test_extract_decklist_from_replay_returns_grpid_counts(tmp_path):
    path = _make_replay_gz(
        tmp_path / "replays", short_id="abc",
        main_grpids=[79085, 79085, 82326, 82326, 82326, 82747],
        side_grpids=[82853, 82853, 86781],
    )
    from db.untapped_decklists import extract_decklist_from_replay
    out = extract_decklist_from_replay(path)
    assert out is not None
    assert out["mainboard"] == Counter({79085: 2, 82326: 3, 82747: 1})
    assert out["sideboard"] == Counter({82853: 2, 86781: 1})


def test_extract_decklist_returns_none_for_missing_or_empty(tmp_path):
    from db.untapped_decklists import extract_decklist_from_replay
    assert extract_decklist_from_replay(tmp_path / "does-not-exist.json.gz") is None


def test_resolve_grpids_aggregates_alt_arts_under_same_name(tmp_db):
    from db.untapped_decklists import resolve_grpids
    con = sqlite3.connect(str(tmp_db))
    try:
        # 79085 and 79086 both -> "Lightning Helix"
        names = resolve_grpids(con, {79085: 2, 79086: 1, 82326: 4})
        assert names == {"Lightning Helix": 3, "Boros Charm": 4}
    finally:
        con.close()


def test_save_and_get_decklist_roundtrip(tmp_db):
    from db.untapped_decklists import save_decklist, get_decklist
    mb = {"Lightning Helix": 4, "Boros Charm": 4}
    sb = {"Rest in Peace": 2}
    save_decklist("test-id-1", mainboard=mb, sideboard=sb,
                  archetype="Boros Burn", source_replay_path="/tmp/foo.json.gz")
    got = get_decklist("test-id-1")
    assert got is not None
    assert got["short_id"] == "test-id-1"
    assert got["mainboard"] == mb
    assert got["sideboard"] == sb
    assert got["archetype"] == "Boros Burn"
    assert got["source_replay_path"] == "/tmp/foo.json.gz"
    assert "T" in got["fetched_at"]


def test_save_decklist_is_idempotent_upsert(tmp_db):
    from db.untapped_decklists import save_decklist, get_decklist
    save_decklist("dup-id", mainboard={"A": 4}, sideboard={})
    save_decklist("dup-id", mainboard={"A": 4, "B": 1}, sideboard={"C": 2},
                  archetype="UpdatedArch")
    got = get_decklist("dup-id")
    assert got["mainboard"] == {"A": 4, "B": 1}
    assert got["sideboard"] == {"C": 2}
    assert got["archetype"] == "UpdatedArch"


def test_get_decklist_returns_none_for_unknown(tmp_db):
    from db.untapped_decklists import get_decklist
    assert get_decklist("never-saved") is None


def test_populate_for_short_ids_writes_decklists(tmp_db, tmp_path):
    replay_dir = tmp_path / "replays"
    _make_replay_gz(
        replay_dir, "player-1",
        main_grpids=[79085] * 4 + [82326] * 4 + [82747] * 4,
        side_grpids=[82853] * 2,
    )
    _make_replay_gz(
        replay_dir, "player-2",
        main_grpids=[82326] * 4,
        side_grpids=[],
    )

    from db.untapped_decklists import populate_for_short_ids, get_decklist
    stats = populate_for_short_ids(
        ["player-1", "player-2", "player-missing-replay"],
        replay_dir=replay_dir,
        archetype_lookup={"player-1": "Boros Burn"},
    )
    assert stats["written"] == 2
    assert stats["missing_replay"] == 1
    assert stats["malformed"] == 0

    d1 = get_decklist("player-1")
    assert d1["mainboard"] == {"Lightning Helix": 4, "Boros Charm": 4,
                                "Sacred Foundry": 4}
    assert d1["sideboard"] == {"Path to Exile": 2}
    assert d1["archetype"] == "Boros Burn"

    d2 = get_decklist("player-2")
    assert d2["mainboard"] == {"Boros Charm": 4}


def test_populate_skips_existing_by_default(tmp_db, tmp_path):
    replay_dir = tmp_path / "replays"
    _make_replay_gz(
        replay_dir, "player-1",
        main_grpids=[79085] * 4,
        side_grpids=[],
    )
    from db.untapped_decklists import populate_for_short_ids
    s1 = populate_for_short_ids(["player-1"], replay_dir=replay_dir)
    assert s1["written"] == 1
    s2 = populate_for_short_ids(["player-1"], replay_dir=replay_dir)
    assert s2["written"] == 0
    assert s2["skipped_existing"] == 1


def test_populate_handles_malformed_replay(tmp_db, tmp_path):
    replay_dir = tmp_path / "replays"
    replay_dir.mkdir(parents=True)
    # Empty file -> gzip read fails -> malformed
    (replay_dir / "bad.json.gz").write_bytes(b"")
    from db.untapped_decklists import populate_for_short_ids
    stats = populate_for_short_ids(["bad"], replay_dir=replay_dir)
    assert stats["written"] == 0
    assert stats["malformed"] == 1


def test_populate_handles_unresolvable_grpids(tmp_db, tmp_path):
    replay_dir = tmp_path / "replays"
    # grpids 99999 and 99998 are not in the seeded untapped_card_db
    _make_replay_gz(
        replay_dir, "unknown-cards",
        main_grpids=[99999] * 4 + [99998] * 4,
        side_grpids=[],
    )
    from db.untapped_decklists import populate_for_short_ids
    stats = populate_for_short_ids(["unknown-cards"], replay_dir=replay_dir)
    assert stats["written"] == 0
    assert stats["no_card_resolution"] == 1
