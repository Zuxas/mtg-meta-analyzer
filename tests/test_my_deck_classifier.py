"""Tests for analysis.my_deck_classifier.

Uses a fixture in-memory SQLite to seed saved_decks rows, then verifies
the overlap-score classification picks the right deck or returns None.
"""
import sqlite3
import time
from pathlib import Path

import pytest

from analysis.my_deck_classifier import classify_my_deck


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Build a temp DB with two saved_decks rows + card_data lookup."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))

    import db.saved_decks
    db.saved_decks._ensure_tables()

    # card_data with arena_id (grp_id) lookup for name resolution
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_data (
                name TEXT PRIMARY KEY,
                arena_id INTEGER
            )
        """)
        conn.executemany(
            "INSERT INTO card_data (name, arena_id) VALUES (?, ?)",
            [
                ("Lightning Bolt", 1001),
                ("Forest", 1002),
                ("Llanowar Elves", 1003),
                ("Sheoldred, the Apocalypse", 1004),
                ("Swamp", 1005),
                ("Thoughtseize", 1006),
            ],
        )

    db.saved_decks.save_deck(
        name="Mono Green Stompy",
        format_name="standard",
        archetype="Mono Green",
        mainboard={"Llanowar Elves": 4, "Forest": 20},
        sideboard={},
    )
    db.saved_decks.save_deck(
        name="Mono Black Midrange",
        format_name="standard",
        archetype="Mono Black",
        mainboard={"Sheoldred, the Apocalypse": 4, "Swamp": 20, "Thoughtseize": 4},
        sideboard={},
    )
    return db_path


def test_classify_picks_dominant_overlap(seeded_db):
    # Observed 18/24 cards from Mono Green = 75% overlap > 0.70 threshold
    observed = [1003, 1003, 1003, 1003,                       # 4x Elves
                1002, 1002, 1002, 1002, 1002, 1002, 1002, 1002,
                1002, 1002, 1002, 1002, 1002, 1002, 1002, 1002]  # 16x Forest
    deck_id = classify_my_deck(observed, format_name="standard")
    assert deck_id is not None
    # Verify it's the Mono Green deck by re-reading
    from db.saved_decks import get_decks
    deck = next(d for d in get_decks() if d["id"] == deck_id)
    assert deck["archetype"] == "Mono Green"


def test_classify_returns_none_below_threshold(seeded_db):
    # Observed 1 card overlap of 24 = 4% << 0.70 threshold
    observed = [1003, 9999, 9999, 9999]
    assert classify_my_deck(observed, format_name="standard") is None


def test_classify_returns_none_when_no_saved_decks_in_format(seeded_db):
    observed = [1003, 1002]
    assert classify_my_deck(observed, format_name="modern") is None


def test_classify_tie_breaks_by_most_recent_created_at(seeded_db):
    """When two saved decks score identically, the more recent created_at wins.

    Sleep 1.1s before saving V2 to guarantee it gets a strictly later
    created_at timestamp. utc_now() is second-precision (%H:%M:%SZ), so
    sub-second saves within the same tick would collide and make the sort
    order undefined.
    """
    # Both saved decks above are 100% overlap when ALL their cards are observed.
    # Insert a 3rd deck identical in mainboard to Mono Green but created later.
    import db.saved_decks
    time.sleep(1.1)  # ensure V2 gets a strictly later created_at second
    db.saved_decks.save_deck(
        name="Mono Green Stompy V2",
        format_name="standard",
        archetype="Mono Green",
        mainboard={"Llanowar Elves": 4, "Forest": 20},
        sideboard={},
    )
    # All Mono Green cards observed (100% overlap on both Mono Green decks)
    observed = [1003] * 4 + [1002] * 20
    deck_id = classify_my_deck(observed, format_name="standard")
    from db.saved_decks import get_decks
    chosen = next(d for d in get_decks() if d["id"] == deck_id)
    assert chosen["name"] == "Mono Green Stompy V2"


def test_classify_ignores_zero_quantity_cards(seeded_db):
    observed = []  # nothing observed
    assert classify_my_deck(observed, format_name="standard") is None
