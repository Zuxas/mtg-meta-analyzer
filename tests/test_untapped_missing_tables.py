"""Guard: the untapped_* tables are optional, so their absence must never
crash the app.

ROOT CAUSE THIS PINS
--------------------
Every table and view db/untapped_queries.py reads (untapped_entries,
untapped_snapshots, untapped_replays, untapped_sideboard_plans, the
v_untapped_* views ...) is created by the Untapped scrapers
(scrapers/untapped_mythic_scraper.py), NOT by db.database.init_db. A database
built by the normal first-run path but without the Untapped pipeline having
run simply does not have them -- verified: init_db() creates 8 tables and
untapped_entries is not among them.

Before the fix that was not a degraded feature, it was a HARD LAUNCH FAILURE:

    LadderMetaTab.__init__ -> self.refresh()            (ladder_meta.py:38)
      -> get_mythic_archetype_rollup()                  (untapped_queries.py)
        -> sqlite3.OperationalError: no such table: untapped_entries
          -> propagates out of MainWindow._build_ui     (main_window.py:559)
            -> MainWindow() raises -> the app never opens

So anyone with a DB but no Untapped data (a fresh clone, a new teammate)
could not start the program at all.

The guard is deliberately NARROW -- only "no such table" is swallowed. A
corrupt or unreadable database must still raise, which the last test pins:
silently returning empty for real corruption would hide data loss.
"""
import sqlite3

import pytest


ALL_DB_QUERIES = [
    # (callable name, kwargs, expected empty value)
    ("get_untapped_matchup_matrix", {"format_name": "standard"}, dict),
    ("get_sideboard_plans_for_archetype", {"archetype": "Izzet Prowess"}, list),
    ("get_mythic_card_inclusion", {"archetype": "Izzet Prowess"}, dict),
    ("get_known_sb_opponents", {"archetype": "Izzet Prowess"}, list),
    ("get_skill_curve", {"format_name": "standard"}, list),
    ("get_bo3_tier_wrs", {}, dict),
    ("get_mythic_leaderboard", {}, list),
    ("get_mythic_archetype_rollup", {}, list),
]


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """A real SQLite database with no untapped_* tables at all."""
    db = tmp_path / "no_untapped.db"
    sqlite3.connect(str(db)).close()  # valid, simply empty
    import db.untapped_queries as uq
    monkeypatch.setattr(uq, "DB_PATH", db)
    return uq


@pytest.mark.parametrize("fn_name,kwargs,empty_type", ALL_DB_QUERIES)
def test_query_returns_empty_when_untapped_tables_absent(
    empty_db, fn_name, kwargs, empty_type
):
    """No untapped_* table -> an empty result of the right type, never a raise."""
    fn = getattr(empty_db, fn_name)
    result = fn(**kwargs)
    assert isinstance(result, empty_type), (
        f"{fn_name} returned {type(result).__name__}, expected {empty_type.__name__}"
    )
    assert not result, f"{fn_name} should be empty on a DB with no untapped data"


def test_corrupt_database_still_raises(tmp_path, monkeypatch):
    """The guard must NOT swallow real database damage.

    Only "no such table" is caught; a file that is not a database at all has
    to keep raising, otherwise genuine corruption would silently read as
    "no untapped data yet".
    """
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"\x00\x01\x02 this is not a sqlite file " * 64)
    import db.untapped_queries as uq
    monkeypatch.setattr(uq, "DB_PATH", bad)

    with pytest.raises(sqlite3.DatabaseError):
        uq.get_mythic_archetype_rollup()


def test_ladder_tab_constructs_without_untapped_tables(empty_db):
    """The specific launch-blocking path: LadderMetaTab builds and eagerly
    refreshes in __init__, so it must survive a DB with no untapped data."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from gui.tabs.ladder_meta import LadderMetaTab

    tab = LadderMetaTab()  # pre-fix: sqlite3.OperationalError -> app never opened
    try:
        assert tab is not None
    finally:
        try:
            tab.cleanup()
        except Exception:
            pass
        app.processEvents()
