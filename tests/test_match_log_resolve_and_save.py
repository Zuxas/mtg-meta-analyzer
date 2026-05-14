"""Tests for db.match_log.resolve_and_save — the shared writer that ties
match_log rows to a saved_deck variant_hash."""
import json
import sqlite3
import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    from db.match_log import _ensure_table
    _ensure_table()
    import db.saved_decks
    db.saved_decks._ensure_tables()
    deck_id = db.saved_decks.save_deck(
        name="Test Mono Green",
        format_name="standard",
        archetype="Mono Green",
        mainboard={"Llanowar Elves": 4, "Forest": 20},
        sideboard={"Pithing Needle": 2},
    )
    return db_path, deck_id


def test_resolve_and_save_links_deck_and_variant(seeded_db):
    db_path, deck_id = seeded_db
    from db.match_log import resolve_and_save
    match_id = resolve_and_save(
        event_name="FNM", event_date="2026-05-13", format_name="standard",
        round_num=1, my_deck_id=deck_id, opp_deck="Izzet Prowess",
        result="win", play_draw="play", source="manual",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM match_log WHERE id=?", (match_id,)).fetchone()
    assert row["my_deck_id"] == deck_id
    assert row["my_variant_hash"] is not None
    assert len(row["my_variant_hash"]) == 16
    assert row["source"] == "manual"


def test_resolve_and_save_upserts_deck_variant_row(seeded_db):
    db_path, deck_id = seeded_db
    from db.match_log import resolve_and_save
    resolve_and_save(
        event_name="FNM", event_date="2026-05-13", format_name="standard",
        round_num=1, my_deck_id=deck_id, opp_deck="Izzet Prowess",
        result="win", source="manual",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM deck_variants WHERE deck_id=?", (deck_id,)
        ).fetchall()
    assert len(rows) == 1
    v = rows[0]
    assert v["match_count"] == 1
    assert v["win_count"] == 1
    assert json.loads(v["mainboard_json"]) == {"Llanowar Elves": 4, "Forest": 20}
    assert json.loads(v["sideboard_json"]) == {"Pithing Needle": 2}


def test_resolve_and_save_increments_existing_variant(seeded_db):
    db_path, deck_id = seeded_db
    from db.match_log import resolve_and_save
    resolve_and_save(event_name="FNM", event_date="2026-05-13",
                     format_name="standard", round_num=1, my_deck_id=deck_id,
                     opp_deck="A", result="win", source="manual")
    resolve_and_save(event_name="FNM", event_date="2026-05-13",
                     format_name="standard", round_num=2, my_deck_id=deck_id,
                     opp_deck="B", result="loss", source="manual")
    resolve_and_save(event_name="FNM", event_date="2026-05-13",
                     format_name="standard", round_num=3, my_deck_id=deck_id,
                     opp_deck="C", result="win", source="manual")
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM deck_variants WHERE deck_id=?",
                            (deck_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["match_count"] == 3
    assert rows[0]["win_count"] == 2


def test_resolve_and_save_creates_new_variant_on_deck_edit(seeded_db):
    """Editing the saved deck changes its variant_hash; new resolve_and_save
    after the edit creates a SECOND deck_variants row."""
    db_path, deck_id = seeded_db
    from db.match_log import resolve_and_save
    from db.saved_decks import save_deck
    resolve_and_save(event_name="A", event_date="2026-05-13",
                     format_name="standard", round_num=1, my_deck_id=deck_id,
                     opp_deck="X", result="win", source="manual")
    # Edit the deck: swap a card
    save_deck(name="Test Mono Green", format_name="standard", archetype="Mono Green",
              mainboard={"Elvish Mystic": 4, "Forest": 20},
              sideboard={"Pithing Needle": 2}, deck_id=deck_id)
    resolve_and_save(event_name="B", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck_id=deck_id,
                     opp_deck="Y", result="win", source="manual")
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM deck_variants WHERE deck_id=? ORDER BY first_seen",
            (deck_id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["match_count"] == 1
    assert rows[1]["match_count"] == 1


def test_resolve_and_save_with_null_deck_id_marks_orphan(seeded_db):
    """When my_deck_id is None, the row is inserted with backfill_status='orphan'
    and no variant_hash."""
    db_path, _ = seeded_db
    from db.match_log import resolve_and_save
    match_id = resolve_and_save(
        event_name="FNM", event_date="2026-05-13", format_name="standard",
        round_num=1, my_deck_id=None, opp_deck="Some Deck",
        result="win", source="untapped",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM match_log WHERE id=?", (match_id,)).fetchone()
    assert row["my_deck_id"] is None
    assert row["my_variant_hash"] is None
    assert row["backfill_status"] == "orphan"


def test_resolve_and_save_with_nonexistent_deck_id_marks_orphan(seeded_db):
    """Path 3: caller passes a my_deck_id that's not in saved_decks
    (e.g., user deleted the deck after a match was logged). The row
    must land as orphan with my_deck_id NULL'd out."""
    db_path, _ = seeded_db
    from db.match_log import resolve_and_save
    match_id = resolve_and_save(
        event_name="FNM", event_date="2026-05-13", format_name="standard",
        round_num=1, my_deck_id=99999,  # non-existent
        opp_deck="Some Deck", result="win", source="untapped",
    )
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM match_log WHERE id=?", (match_id,)).fetchone()
    assert row["my_deck_id"] is None
    assert row["my_variant_hash"] is None
    assert row["backfill_status"] == "orphan"


def test_get_variants_for_deck_returns_approximation_flag(seeded_db):
    """A variant where every contributing match is auto-backfilled is approximate.
    A variant where any match is 'live' or 'manual' is NOT approximate."""
    db_path, deck_id = seeded_db
    from db.match_log import resolve_and_save
    from db.deck_variants import get_variants_for_deck

    # Live match -> variant_hash X, not approximate
    resolve_and_save(event_name="A", event_date="2026-05-13",
                     format_name="standard", round_num=1, my_deck_id=deck_id,
                     opp_deck="X", result="win", source="manual")

    # Manually flip the row to 'auto' to simulate a backfilled variant
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE match_log SET backfill_status='auto' "
            "WHERE my_deck_id=? AND my_variant_hash IS NOT NULL",
            (deck_id,),
        )

    variants = get_variants_for_deck(deck_id)
    assert len(variants) == 1
    assert variants[0]["is_approximate"] is True

    # Now add a 'live' match for the SAME variant_hash -> no longer approximate
    resolve_and_save(event_name="B", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck_id=deck_id,
                     opp_deck="Y", result="loss", source="manual")
    variants = get_variants_for_deck(deck_id)
    assert variants[0]["is_approximate"] is False
