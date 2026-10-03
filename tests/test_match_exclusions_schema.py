"""Schema compatibility of the exclusion tables (db/match_exclusions.py), 2026-10-02.

A fresh DB and a pre-cleanup DB both get excluded_events + matches_excluded on first use of
`matches`; re-running initialisation changes nothing; save_matches never fails on a DB without them."""
import sqlite3

import pytest

from db import database, matches_queries as mq

PRE_CLEANUP_MATCHES = """CREATE TABLE matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, round INTEGER, player1 TEXT,
    player2 TEXT, player1_arch TEXT NOT NULL, player2_arch TEXT NOT NULL, winner_arch TEXT, result TEXT,
    format TEXT NOT NULL, event_date TEXT, source TEXT NOT NULL DEFAULT 'mtgmelee',
    UNIQUE(event_id, round, player1, player2))"""


def _row(i=0):
    return {"event_id": "mtgmelee_1", "round": 1, "player1": f"a{i}", "player2": f"b{i}",
            "player1_arch": "X", "player2_arch": "Y", "winner_arch": "X", "result": "player1",
            "format": "modern", "event_date": "2026-01-01", "source": "mtgmelee"}


def _schema(con):
    return sorted(con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


def _data(con):
    return {t: sorted(con.execute(f"SELECT * FROM {t}")) for (t,) in
            con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def test_fresh_db_gets_the_tables_indexes_and_constraints():
    database.init_db()                                      # app/CLI start on an empty DB
    assert mq.save_matches([_row()]) == 1                   # first write works, nothing missing
    con = sqlite3.connect(database.DB_PATH)
    names = {n for (n,) in con.execute("SELECT name FROM sqlite_master")}
    assert {"matches", "excluded_events", "matches_excluded", "ux_excluded_events",
            "idx_matches_excluded_event"} <= names
    con.execute("INSERT INTO excluded_events (source, event_id, round, scope, reason, created_at) "
                "VALUES ('mtgmelee','e',NULL,'event','r','t')")
    with pytest.raises(sqlite3.IntegrityError):             # whole-event entry is unique
        con.execute("INSERT INTO excluded_events (source, event_id, round, scope, reason, created_at) "
                    "VALUES ('mtgmelee','e',NULL,'event','r','t')")
    with pytest.raises(sqlite3.IntegrityError):             # scope must agree with round
        con.execute("INSERT INTO excluded_events (source, event_id, round, scope, reason, created_at) "
                    "VALUES ('mtgmelee','e',3,'event','r','t')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO excluded_events (source, event_id, round, scope, reason, created_at) "
                    "VALUES ('mtgmelee','e',NULL,'banana','r','t')")


def test_pre_cleanup_db_upgrades_idempotently():
    con = sqlite3.connect(database.DB_PATH)
    con.execute(PRE_CLEANUP_MATCHES)
    con.execute("INSERT INTO matches (event_id, round, player1, player2, player1_arch, player2_arch, "
                "winner_arch, result, format, event_date, source) VALUES "
                "('mtgmelee_9',1,'p','q','A','B','A','player1','modern','2026-01-01','mtgmelee')")
    con.commit()
    rows_before = sorted(con.execute("SELECT * FROM matches"))
    assert mq.get_matches("modern")                         # first read upgrades the schema
    con = sqlite3.connect(database.DB_PATH)
    assert {"excluded_events", "matches_excluded"} <= {n for (n,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert sorted(con.execute("SELECT * FROM matches")) == rows_before       # data untouched
    database.init_db()                                      # the app's full init (other tables too)
    con = sqlite3.connect(database.DB_PATH)
    schema, data = _schema(con), _data(con)
    mq._ensure_table()                                      # re-run initialisation
    database.init_db()
    mq.save_matches([])
    con = sqlite3.connect(database.DB_PATH)
    assert _schema(con) == schema and _data(con) == data    # no schema or data change


def test_save_matches_on_a_db_without_exclusion_tables_does_not_fail():
    con = sqlite3.connect(database.DB_PATH)
    con.execute(PRE_CLEANUP_MATCHES)
    con.commit()
    assert mq.save_matches([_row(1), _row(2)]) == 2
    assert mq.LAST_SAVE_SKIPPED == []
    assert sqlite3.connect(database.DB_PATH).execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2


_GUARD_OBJECTS = {"matches", "excluded_events", "matches_excluded", "ux_excluded_events",
                  "idx_matches_excluded_event"}


def _names():
    return {n for (n,) in sqlite3.connect(database.DB_PATH).execute("SELECT name FROM sqlite_master")}


def test_init_db_alone_creates_the_guard_on_a_fresh_db():
    """main.py / fill_database.py (the scheduled scraper) call init_db() and nothing else before
    scraping -- the guard must exist from that call, not from a later first use of `matches`."""
    database.init_db()
    assert _GUARD_OBJECTS <= _names()


def test_init_db_alone_upgrades_a_pre_cleanup_db_and_is_idempotent():
    con = sqlite3.connect(database.DB_PATH)
    con.execute(PRE_CLEANUP_MATCHES)
    con.execute("INSERT INTO matches (event_id, round, player1, player2, player1_arch, player2_arch, "
                "winner_arch, result, format, event_date, source) VALUES "
                "('mtgmelee_9',1,'p','q','A','B','A','player1','modern','2026-01-01','mtgmelee')")
    con.commit()
    rows_before = sorted(con.execute("SELECT * FROM matches"))
    database.init_db()
    assert _GUARD_OBJECTS <= _names()
    con = sqlite3.connect(database.DB_PATH)
    assert sorted(con.execute("SELECT * FROM matches")) == rows_before
    schema, data = _schema(con), _data(con)
    database.init_db()
    con = sqlite3.connect(database.DB_PATH)
    assert _schema(con) == schema and _data(con) == data


def test_init_db_does_not_put_the_guard_in_the_archive_db():
    """matches and its quarantine live in the active DB only."""
    database.init_db()
    archive = {n for (n,) in sqlite3.connect(database.ARCHIVE_PATH).execute(
        "SELECT name FROM sqlite_master")}
    assert not ({"matches_excluded", "excluded_events"} & archive)
