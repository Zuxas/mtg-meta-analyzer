"""db.maintenance archive copy: ids must be resolved by natural key, not assumed equal.

Traced 2026-10-01 from logs/background_fill.log (`sqlite3.IntegrityError: FOREIGN KEY constraint
failed` in `_copy_events_to_archive`, the deck_cards insert): cards are `UNIQUE(name)` with ids
allocated independently in each DB. The active card "Secrets of the Key" (id 8226397) already
existed in the archive as id 1565854, so `INSERT OR IGNORE INTO cards (id, name)` was silently
ignored and the deck_cards row then referenced a card id the archive does not have -> the archive
connection's foreign-key check failed and Pioneer archiving aborted on every run. The same
assumption could also re-point a deck to a DIFFERENT card when the active id is taken in the
archive by another name (silent corruption). Same for events / decks keyed by their unique keys.
"""
import sqlite3

import pytest

from db.database import _apply_schema
import db.maintenance as maint


def _db(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    _apply_schema(c)
    return c


@pytest.fixture
def dbs(tmp_path):
    act, arc = _db(tmp_path / "active.db"), _db(tmp_path / "archive.db")
    # active: one old event, one deck, three cards
    act.execute("INSERT INTO events (id, source_id, source, name, date, format) VALUES (500, 'e-1', 'mtgtop8', 'Old', '2023-01-02', 'pioneer')")
    act.execute("INSERT INTO decks (id, event_id, source_id, player, archetype, placement) VALUES (900, 500, 'd-1', 'p', 'Arch', 1)")
    for cid, name in ((8226397, "Secrets of the Key"), (77, "Shared Id Card"), (31, "Fresh Card")):
        act.execute("INSERT INTO cards (id, name) VALUES (?, ?)", (cid, name))
        act.execute("INSERT INTO deck_cards (deck_id, card_id, quantity, is_sideboard) VALUES (900, ?, 4, 0)", (cid,))
    # archive: the same name under another id, and the active id 77 taken by a DIFFERENT card
    arc.execute("INSERT INTO cards (id, name) VALUES (1565854, 'Secrets of the Key')")
    arc.execute("INSERT INTO cards (id, name) VALUES (77, 'Some Other Card')")
    act.commit(); arc.commit()
    yield act, arc
    act.close(); arc.close()


def _archived(arc):
    return {(r["name"], r["quantity"]) for r in arc.execute(
        "SELECT c.name, dc.quantity FROM deck_cards dc JOIN cards c ON c.id = dc.card_id")}


def test_copy_maps_cards_by_name_and_keeps_foreign_keys_valid(dbs):
    act, arc = dbs
    ev, dk, dc = maint._copy_events_to_archive(act, arc, [500])
    arc.commit()
    assert (ev, dk, dc) == (1, 1, 3)
    assert arc.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _archived(arc) == {("Secrets of the Key", 4), ("Shared Id Card", 4), ("Fresh Card", 4)}
    assert "Some Other Card" not in {n for n, _q in _archived(arc)}       # never re-pointed to another card
    sk = arc.execute("SELECT id FROM cards WHERE name='Secrets of the Key'").fetchone()[0]
    assert sk == 1565854                                                  # the archive's existing id is used


def test_copy_is_idempotent(dbs):
    act, arc = dbs
    maint._copy_events_to_archive(act, arc, [500])
    maint._copy_events_to_archive(act, arc, [500])
    arc.commit()
    assert arc.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 3
    assert arc.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert arc.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == 1


def test_event_and_deck_already_archived_under_other_ids(dbs):
    act, arc = dbs
    arc.execute("INSERT INTO events (id, source_id, source, name, date, format) VALUES (7, 'e-1', 'mtgtop8', 'Old', '2023-01-02', 'pioneer')")
    arc.execute("INSERT INTO decks (id, event_id, source_id, player, archetype, placement) VALUES (8, 7, 'd-1', 'p', 'Arch', 1)")
    arc.commit()
    maint._copy_events_to_archive(act, arc, [500])
    arc.commit()
    assert arc.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {r[0] for r in arc.execute("SELECT DISTINCT deck_id FROM deck_cards")} == {8}
    assert arc.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
