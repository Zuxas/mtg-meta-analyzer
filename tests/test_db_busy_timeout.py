"""Writers must queue on a lock, not fail after SQLite's 5 s default: the
2026-09-21 backfill lost modern/legacy/pauper to 'database is locked' when a
scheduled scrape held the write lock."""
from db.database import get_connection


def test_connections_wait_60s_for_a_lock():
    with get_connection() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 60000
