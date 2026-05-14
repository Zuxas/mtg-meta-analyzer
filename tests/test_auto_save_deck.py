"""Tests for analysis.auto_save_deck.find_or_create_deck.

Validates:
- Limited events are skipped.
- Below-threshold observations are skipped.
- Existing saved deck with matching archetype+format is reused.
- New saved deck is created when no match exists.
- classify_event correctly maps MTGA event names to categories.
"""
import sqlite3
import pytest


@pytest.fixture
def seeded_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))

    import db.saved_decks
    db.saved_decks._ensure_tables()

    # Seed untapped_card_db for grpid -> name resolution
    con = sqlite3.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS untapped_card_db (
            grpid INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    con.executemany(
        "INSERT INTO untapped_card_db (grpid, name) VALUES (?, ?)",
        [
            (1001, "Spyglass Siren"),
            (1002, "Floodpits Drowner"),
            (1003, "Kaito, Bane of Nightmares"),
            (1004, "Watery Grave"),
            (1005, "Island"),
            (1006, "Swamp"),
            (1007, "Deep-Cavern Bat"),
            (1008, "Enduring Curiosity"),
            (1009, "Bitter Triumph"),
            (1010, "Tishana's Tidebinder"),
            (1011, "Gloomlake Verge"),
            (1012, "Restless Reef"),
            (1013, "Cecil, Dark Knight"),
            (1014, "Multiversal Passage"),
            (1015, "Shoot the Sheriff"),
            (1016, "Phantom Interference"),
            (1017, "Preacher of the Schism"),
            (1018, "Day of Black Sun"),
            (1019, "Requiting Hex"),
            (1020, "Soulstone Sanctuary"),
            (1021, "Super Shredder"),
            (1022, "Dream Beavers"),
        ],
    )
    con.commit()
    con.close()
    return tmp_path


def test_classify_event_categories():
    from analysis.auto_save_deck import classify_event
    assert classify_event("Traditional_Ladder") == "ranked-bo3"
    assert classify_event("Ladder") == "ranked-bo1"
    assert classify_event("Constructed_BestOf3_Ranked") == "ranked-bo3"
    assert classify_event("Constructed_BestOf3") == "unranked"
    assert classify_event("Sealed_SOS_20260421") == "limited"
    assert classify_event("Premier_Draft") == "limited"
    assert classify_event("RCQ @ Local") == "other"
    assert classify_event("") == "other"


def test_skips_limited_events(seeded_env):
    from analysis.auto_save_deck import find_or_create_deck
    result = find_or_create_deck(
        observed_grp_ids=list(range(1001, 1023)),
        format_name="standard",
        event_category="limited",
    )
    assert result is None


def test_skips_below_threshold(seeded_env):
    from analysis.auto_save_deck import find_or_create_deck
    # Only 10 unique grpIds -- below the 20 minimum
    result = find_or_create_deck(
        observed_grp_ids=list(range(1001, 1011)),
        format_name="standard",
        event_category="ranked-bo3",
    )
    assert result is None


def test_skips_empty_grpids(seeded_env):
    from analysis.auto_save_deck import find_or_create_deck
    assert find_or_create_deck([], "standard", "ranked-bo3") is None


def test_reuses_existing_archetype_match(seeded_env, monkeypatch):
    """If a saved deck already has the classified archetype + format,
    we link to it instead of creating a duplicate."""
    import db.saved_decks
    existing_id = db.saved_decks.save_deck(
        name="My Dimir Build",
        format_name="standard",
        archetype="Dimir Midrange",
        mainboard={"Spyglass Siren": 4},
        sideboard={},
    )
    # Stub classify_opponent_deck to return "Dimir Midrange"
    monkeypatch.setattr(
        "scrapers.mtga_log_parser.classify_opponent_deck",
        lambda ids, fmt: "Dimir Midrange",
    )

    from analysis.auto_save_deck import find_or_create_deck
    result = find_or_create_deck(
        observed_grp_ids=list(range(1001, 1023)),
        format_name="standard",
        event_category="ranked-bo3",
    )
    assert result == existing_id

    # No new deck was created
    decks = db.saved_decks.get_decks(format_name="standard")
    assert len(decks) == 1


def test_creates_new_deck_when_no_match(seeded_env, monkeypatch):
    """When no saved deck matches the archetype, create a new one."""
    monkeypatch.setattr(
        "scrapers.mtga_log_parser.classify_opponent_deck",
        lambda ids, fmt: "Dimir Midrange",
    )

    import db.saved_decks
    assert len(db.saved_decks.get_decks(format_name="standard")) == 0

    from analysis.auto_save_deck import find_or_create_deck
    new_id = find_or_create_deck(
        observed_grp_ids=list(range(1001, 1023)),
        format_name="standard",
        event_category="ranked-bo3",
    )
    assert new_id is not None

    decks = db.saved_decks.get_decks(format_name="standard")
    assert len(decks) == 1
    deck = decks[0]
    assert deck["archetype"] == "Dimir Midrange"
    assert "auto-imported" in deck["name"].lower()
    assert len(deck["mainboard"]) >= 20  # the seeded cards
    assert deck["sideboard"] == {}


def test_does_not_create_unknown_archetype(seeded_env, monkeypatch):
    """If the deck can't be classified to a known archetype, don't pollute
    saved_decks with an 'Unknown Archetype' row."""
    monkeypatch.setattr(
        "scrapers.mtga_log_parser.classify_opponent_deck",
        lambda ids, fmt: "Unknown",
    )

    from analysis.auto_save_deck import find_or_create_deck
    result = find_or_create_deck(
        observed_grp_ids=list(range(1001, 1023)),
        format_name="standard",
        event_category="ranked-bo3",
    )
    assert result is None
    import db.saved_decks
    assert len(db.saved_decks.get_decks(format_name="standard")) == 0


def test_idempotent_across_multiple_calls(seeded_env, monkeypatch):
    """Calling find_or_create_deck twice for the same deck should reuse,
    not duplicate."""
    monkeypatch.setattr(
        "scrapers.mtga_log_parser.classify_opponent_deck",
        lambda ids, fmt: "Dimir Midrange",
    )

    from analysis.auto_save_deck import find_or_create_deck
    id1 = find_or_create_deck(list(range(1001, 1023)), "standard", "ranked-bo3")
    id2 = find_or_create_deck(list(range(1001, 1023)), "standard", "ranked-bo3")
    assert id1 == id2

    import db.saved_decks
    assert len(db.saved_decks.get_decks(format_name="standard")) == 1
