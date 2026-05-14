"""Tests for scripts.backfill_match_log_decks.

The backfill walks match_log rows with my_deck_id NULL and attempts to attach
them to saved_decks by archetype + date proximity."""
import sqlite3
import pytest


@pytest.fixture
def seeded_history(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    from db.match_log import _ensure_table, save_match
    _ensure_table()
    import db.saved_decks
    db.saved_decks._ensure_tables()
    deck_id = db.saved_decks.save_deck(
        name="Test Boros", format_name="standard", archetype="Boros Energy",
        mainboard={"Lightning Helix": 4}, sideboard={},
    )
    # Three historical rows in the old free-text style
    save_match(event_name="RCQ 1", event_date="2026-04-15", format_name="standard",
               round_num=1, my_deck="Boros Energy", opp_deck="Izzet Prowess",
               result="win")
    save_match(event_name="RCQ 2", event_date="2026-04-22", format_name="standard",
               round_num=1, my_deck="Boros Energy", opp_deck="Dimir Midrange",
               result="loss")
    save_match(event_name="FNM 1", event_date="2026-04-20", format_name="standard",
               round_num=1, my_deck="Some Unknown Deck", opp_deck="X",
               result="win")
    return db_path, deck_id


def test_backfill_links_unambiguous_rows(seeded_history):
    db_path, deck_id = seeded_history
    from scripts.backfill_match_log_decks import run
    summary = run()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT my_deck_id, my_deck, backfill_status FROM match_log"
        ).fetchall()
    boros_rows = [r for r in rows if r["my_deck"] == "Boros Energy"]
    assert len(boros_rows) == 2
    for r in boros_rows:
        assert r["my_deck_id"] == deck_id
        assert r["backfill_status"] == "auto"
    # Summary reflects the result
    assert summary["auto"] == 2
    assert summary["orphan"] == 1


def test_backfill_marks_orphans_for_no_match(seeded_history):
    db_path, _ = seeded_history
    from scripts.backfill_match_log_decks import run
    run()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM match_log WHERE my_deck='Some Unknown Deck'"
        ).fetchone()
    assert row["my_deck_id"] is None
    assert row["backfill_status"] == "orphan"


def test_backfill_skips_rows_already_resolved(seeded_history):
    """Rows with non-NULL my_deck_id are left alone — second runs are no-ops on them."""
    db_path, _ = seeded_history
    from scripts.backfill_match_log_decks import run
    run()  # first pass
    # Verify second run is idempotent: summary shows 0 new auto-resolutions
    summary2 = run()
    assert summary2["auto"] == 0


def test_backfill_marks_orphan_when_multiple_candidates_match(tmp_path, monkeypatch):
    """If two saved_decks share the same archetype + format and both are within
    +/-90 days of the match date, the row is ambiguous -> orphan, not auto."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    from db.match_log import _ensure_table, save_match
    _ensure_table()
    import db.saved_decks
    db.saved_decks._ensure_tables()
    db.saved_decks.save_deck(
        name="Boros v1", format_name="standard", archetype="Boros Energy",
        mainboard={"Lightning Helix": 4}, sideboard={},
    )
    db.saved_decks.save_deck(
        name="Boros v2", format_name="standard", archetype="Boros Energy",
        mainboard={"Lightning Helix": 4}, sideboard={},
    )
    save_match(event_name="FNM", event_date="2026-04-15", format_name="standard",
               round_num=1, my_deck="Boros Energy", opp_deck="X", result="win")

    from scripts.backfill_match_log_decks import run
    summary = run()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM match_log").fetchone()
    assert r["my_deck_id"] is None
    assert r["backfill_status"] == "orphan"
    assert summary["orphan"] == 1
