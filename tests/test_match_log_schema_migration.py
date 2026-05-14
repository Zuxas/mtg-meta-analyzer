"""Tests for the additive schema migration on match_log + deck_variants CREATE.

Uses a fresh tmp DB per test. Verifies:
  1. New columns appear on match_log.
  2. deck_variants table is created with the expected schema.
  3. Migration is idempotent: re-running _ensure_table on an already-migrated
     DB is a no-op (no exceptions on duplicate ALTERs).
  4. Existing match_log rows survive the migration with NULL/default values
     for the new columns.
"""
import sqlite3
import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    return db_path


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_match_log_has_5_new_columns_after_ensure(fresh_db):
    from db.match_log import _ensure_table
    _ensure_table()
    with sqlite3.connect(str(fresh_db)) as conn:
        cols = _columns(conn, "match_log")
    assert "my_deck_id" in cols
    assert "my_variant_hash" in cols
    assert "opp_grp_ids_json" in cols
    assert "source" in cols
    assert "backfill_status" in cols


def test_deck_variants_table_exists_after_ensure(fresh_db):
    from db.match_log import _ensure_table
    _ensure_table()
    with sqlite3.connect(str(fresh_db)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='deck_variants'"
        ).fetchall()
    assert len(rows) == 1


def test_deck_variants_has_expected_columns(fresh_db):
    from db.match_log import _ensure_table
    _ensure_table()
    with sqlite3.connect(str(fresh_db)) as conn:
        cols = _columns(conn, "deck_variants")
    for expected in ("variant_hash", "deck_id", "mainboard_json",
                     "sideboard_json", "first_seen", "last_seen",
                     "match_count", "win_count"):
        assert expected in cols, f"missing column: {expected}"


def test_migration_is_idempotent(fresh_db):
    from db.match_log import _ensure_table
    _ensure_table()
    # Run twice — second run must not raise on duplicate ALTERs
    _ensure_table()
    with sqlite3.connect(str(fresh_db)) as conn:
        cols = _columns(conn, "match_log")
    assert "my_deck_id" in cols  # still present, no schema corruption


def test_existing_rows_survive_migration_with_defaults(fresh_db):
    """Seed a row in the OLD schema, then run migration, verify row survives."""
    with sqlite3.connect(str(fresh_db)) as conn:
        # Pre-migration schema (current production state — no new columns)
        conn.execute("""
            CREATE TABLE match_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL DEFAULT '',
                event_date TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT 'standard',
                round INTEGER NOT NULL DEFAULT 0,
                my_deck TEXT NOT NULL DEFAULT '',
                opp_deck TEXT NOT NULL DEFAULT '',
                opp_name TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                play_draw TEXT NOT NULL DEFAULT '',
                g1_result TEXT NOT NULL DEFAULT '',
                g2_result TEXT NOT NULL DEFAULT '',
                g3_result TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO match_log (event_name, my_deck, opp_deck, result, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("FNM", "Boros Energy", "Izzet Prowess", "win", "2026-05-01T18:00:00"),
        )
    from db.match_log import _ensure_table
    _ensure_table()
    with sqlite3.connect(str(fresh_db)) as conn:
        row = conn.execute("SELECT * FROM match_log WHERE event_name='FNM'").fetchone()
        cols = [d[0] for d in conn.execute("SELECT * FROM match_log LIMIT 0").description]
    d = dict(zip(cols, row))
    assert d["my_deck"] == "Boros Energy"
    assert d["my_deck_id"] is None
    assert d["my_variant_hash"] is None
    assert d["source"] == "manual"
    assert d["backfill_status"] == "live"  # default; backfill script will flip orphans later
