"""The live-DB guard in tests/conftest.py (2026-09-21).

Tests must not touch E:\\mtg-data\\mtg_meta.db unless they say so. Two incidents
this week: a backfill test scraped 20 real Vintage events into it, and
`test_generation_is_deterministic` flaked because the running backfill
inserted decks between its two calls. Same class as the network guard:
default-deny, opt in with `@pytest.mark.live_db`.

The subtle part: ~25 modules do `from db.database import DB_PATH as
CENTRAL_DB_PATH` at import, so patching `db.database.DB_PATH` alone leaves
every captured copy pointing at the live file.
"""
import os

import pytest

from tests.conftest import LIVE_DB_PATHS


def _is_live(path) -> bool:
    return os.path.normcase(os.path.abspath(str(path))) in LIVE_DB_PATHS


def test_unmarked_test_gets_a_tmp_db_path():
    import db.database as dbm
    assert not _is_live(dbm.DB_PATH)
    assert not _is_live(dbm.ARCHIVE_PATH)
    assert "mtg_meta.db" in dbm.DB_PATH          # same basename, different dir


def test_unmarked_test_connection_is_empty_not_the_live_schema():
    """A fresh tmp file: no tables. A test that forgot its fixture fails
    loudly (`no such table`) instead of silently reading real data."""
    import sqlite3
    from db.database import get_connection
    with get_connection() as con:
        tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert tables == []


def test_import_time_captured_copies_are_redirected_too():
    """Modules that captured the path at import must see the redirect."""
    import analysis.scout as scout            # `DB_PATH as CENTRAL_DB_PATH`
    import db.untapped_queries as uq
    assert not _is_live(scout.CENTRAL_DB_PATH)
    assert not _is_live(uq.CENTRAL_DB_PATH)
    import db.database as dbm
    assert scout.CENTRAL_DB_PATH == dbm.DB_PATH


@pytest.mark.live_db
def test_live_db_marker_restores_the_real_path():
    import db.database as dbm
    import analysis.scout as scout
    assert _is_live(dbm.DB_PATH)
    assert _is_live(scout.CENTRAL_DB_PATH)
