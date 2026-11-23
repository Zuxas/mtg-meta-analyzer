"""#24: include_archive must key decks by (db, id), not by bare id.

The archive half of the UNION was built by text-replacing "FROM decks" /
"FROM events", but the base query joins with "JOIN events e" (not "FROM
events"), so archive decks joined to ACTIVE events by integer id. And
_fetch_deck_cards ran the active and archive card queries with the same mixed
id list, so a colliding id crossed cards between decks.

Setup: active deck 42 is a Standard "Mono-Red Aggro" (Lightning Strike);
archive deck 42 is a Modern "Burn" (Lightning Bolt). Same id in each DB.
Each deck must return its OWN event/format and its OWN cards.
"""
import sqlite3

import pytest

import db.database as dbm
from db.database import _apply_schema
from analysis.deck_analysis import get_average_deck


def _db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    _apply_schema(c)
    return c


@pytest.fixture
def colliding_dbs(tmp_path, monkeypatch):
    act, arc = _db(tmp_path / "active.db"), _db(tmp_path / "archive.db")

    # Active: Standard event, deck 42 Mono-Red Aggro (Lightning Strike + Mountains)
    act.execute("INSERT INTO events (id, source_id, source, name, date, format) "
                "VALUES (1, 'a-e1', 'mtgtop8', 'SCG Standard', '2026-09-01', 'standard')")
    act.execute("INSERT INTO decks (id, event_id, source_id, player, archetype, placement) "
                "VALUES (42, 1, 'a-d42', 'P1', 'Mono-Red Aggro', 1)")
    act.execute("INSERT INTO cards (id, name) VALUES (10, 'Lightning Strike')")
    act.execute("INSERT INTO cards (id, name) VALUES (11, 'Mountain')")
    act.execute("INSERT INTO deck_cards (deck_id, card_id, quantity, is_sideboard) VALUES (42, 10, 4, 0)")
    act.execute("INSERT INTO deck_cards (deck_id, card_id, quantity, is_sideboard) VALUES (42, 11, 20, 0)")

    # Archive: Modern event, deck 42 Burn (Lightning Bolt) -- ids collide with active
    arc.execute("INSERT INTO events (id, source_id, source, name, date, format) "
                "VALUES (1, 'r-e1', 'mtgtop8', 'Old Modern', '2023-01-01', 'modern')")
    arc.execute("INSERT INTO decks (id, event_id, source_id, player, archetype, placement) "
                "VALUES (42, 1, 'r-d42', 'P2', 'Burn', 1)")
    arc.execute("INSERT INTO cards (id, name) VALUES (10, 'Lightning Bolt')")   # same id 10 = Strike in active
    arc.execute("INSERT INTO cards (id, name) VALUES (11, 'Mountain')")
    arc.execute("INSERT INTO deck_cards (deck_id, card_id, quantity, is_sideboard) VALUES (42, 10, 4, 0)")
    arc.execute("INSERT INTO deck_cards (deck_id, card_id, quantity, is_sideboard) VALUES (42, 11, 18, 0)")

    act.commit(); arc.commit(); act.close(); arc.close()
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "active.db"))
    monkeypatch.setattr(dbm, "ARCHIVE_PATH", str(tmp_path / "archive.db"))
    yield


def _names(avg):
    return {c["name"] for c in avg["mainboard"]}


def test_active_deck_does_not_get_archive_decks_cards(colliding_dbs):
    avg = get_average_deck("Mono-Red Aggro", "standard", min_inclusion=0.1, include_archive=True)
    assert avg is not None
    assert "Lightning Strike" in _names(avg)
    assert "Lightning Bolt" not in _names(avg)          # archive deck 42's card must not leak in


def test_archive_deck_keeps_its_own_format_and_cards(colliding_dbs):
    # Burn exists only in the archive, under Modern.
    avg = get_average_deck("Burn", "modern", min_inclusion=0.1, include_archive=True)
    assert avg is not None                              # was None: archive deck joined to the active Standard event
    assert "Lightning Bolt" in _names(avg)
    assert "Lightning Strike" not in _names(avg)
    # And the archive Modern deck must not surface as a Standard deck.
    assert get_average_deck("Burn", "standard", min_inclusion=0.1, include_archive=True) is None


def test_active_only_is_unaffected(colliding_dbs):
    avg = get_average_deck("Mono-Red Aggro", "standard", min_inclusion=0.1, include_archive=False)
    assert avg is not None
    assert "Lightning Strike" in _names(avg)
    assert "Lightning Bolt" not in _names(avg)
