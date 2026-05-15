"""Tests for db.match_sb_plans -- per-match sideboard plan storage."""
import sqlite3
import pytest


def _seed_card_db(db_path):
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS untapped_card_db ("
                "grpid INTEGER PRIMARY KEY, name TEXT)")
    con.executemany(
        "INSERT INTO untapped_card_db (grpid, name) VALUES (?, ?)",
        [
            (101, "Lightning Bolt"),
            (102, "Lightning Bolt"),  # alt-art, same name
            (103, "Forest"),
            (104, "Counterspell"),
            (105, "Path to Exile"),
            (106, "Negate"),
            (107, "Rest in Peace"),
            (108, "Mountain"),
        ],
    )
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "sb.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    _seed_card_db(db_path)
    return db_path


def test_save_plans_for_match_writes_correct_diff(env):
    from db.match_sb_plans import save_plans_for_match, get_plans_for_match
    # Game 1: 4 Bolt, 16 Forest. Game 2 (post-SB): 2 Bolt + 2 Path, 16 Forest.
    per_game = [
        {"main": [101] * 4 + [103] * 16, "sb": [105, 105, 106]},
        {"main": [101] * 2 + [105, 105] + [103] * 16, "sb": [101, 101, 106]},
    ]
    n = save_plans_for_match(match_log_id=42, per_game_decks=per_game)
    assert n == 1
    plans = get_plans_for_match(42)
    assert len(plans) == 1
    p = plans[0]
    assert p["from_game"] == 1 and p["to_game"] == 2
    assert p["cards_in"] == {"Path to Exile": 2}
    assert p["cards_out"] == {"Lightning Bolt": 2}
    assert p["n_swapped"] == 2


def test_handles_three_games(env):
    from db.match_sb_plans import save_plans_for_match, get_plans_for_match
    per_game = [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [101] * 2 + [105] * 2 + [103] * 16, "sb": []},
        {"main": [101] * 4 + [106] + [103] * 15, "sb": []},
    ]
    n = save_plans_for_match(match_log_id=43, per_game_decks=per_game)
    assert n == 2  # 1->2 and 2->3 transitions
    plans = get_plans_for_match(43)
    assert len(plans) == 2
    # plan 1: game 1 -> 2: -2 Bolt, +2 Path
    p1 = plans[0]
    assert p1["from_game"] == 1 and p1["to_game"] == 2
    assert p1["cards_in"] == {"Path to Exile": 2}
    assert p1["cards_out"] == {"Lightning Bolt": 2}
    # plan 2: game 2 -> 3: -2 Path -1 Forest, +2 Bolt +1 Negate
    p2 = plans[1]
    assert p2["from_game"] == 2 and p2["to_game"] == 3
    assert p2["cards_in"] == {"Lightning Bolt": 2, "Negate": 1}
    assert p2["cards_out"] == {"Path to Exile": 2, "Forest": 1}


def test_alt_art_aggregates_under_one_name(env):
    """grpid 101 and 102 both resolve to 'Lightning Bolt'. A swap from
    101 to 102 should NOT register as a swap (same card name)."""
    from db.match_sb_plans import save_plans_for_match, get_plans_for_match
    per_game = [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [102] * 4 + [103] * 16, "sb": []},  # all 4 Bolts changed art
    ]
    save_plans_for_match(99, per_game)
    plans = get_plans_for_match(99)
    p = plans[0]
    # alt-art swap collapses to net zero by name
    assert p["cards_in"] == {}
    assert p["cards_out"] == {}
    # but the raw n_swapped is from grpid counts (will be non-zero for the
    # underlying grpid diff). Acceptable -- the user-facing diff dict is
    # what matters for the SB plan view.


def test_idempotent_upsert(env):
    from db.match_sb_plans import save_plans_for_match, get_plans_for_match
    per_game = [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [101] * 2 + [105, 105] + [103] * 16, "sb": []},
    ]
    save_plans_for_match(50, per_game)
    save_plans_for_match(50, per_game)  # call twice
    plans = get_plans_for_match(50)
    assert len(plans) == 1  # not duplicated


def test_empty_or_single_game_does_nothing(env):
    from db.match_sb_plans import save_plans_for_match, get_plans_for_match
    assert save_plans_for_match(60, []) == 0
    assert save_plans_for_match(60, [{"main": [101], "sb": []}]) == 0
    assert get_plans_for_match(60) == []


def test_get_plans_for_match_unknown_returns_empty(env):
    from db.match_sb_plans import get_plans_for_match
    assert get_plans_for_match(9999) == []


def test_get_plans_for_deck_aggregates_by_opponent(env, monkeypatch):
    """Across matches piloting deck #5, plans are grouped by opp archetype
    and card-in/out totals are summed."""
    import db.match_log
    db.match_log._ensure_table()

    # Insert 2 fake match_log rows, both my_deck_id=5, one vs Izzet,
    # one also vs Izzet, one vs Azorius.
    from db.database import get_connection
    with get_connection() as c:
        c.execute(
            "INSERT INTO match_log (event_date, format, my_deck_id, opp_deck, result, created_at) "
            "VALUES ('2026-05-14', 'standard', 5, 'Izzet Prowess', 'win', '2026-05-14T00:00:00')"
        )
        m1 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO match_log (event_date, format, my_deck_id, opp_deck, result, created_at) "
            "VALUES ('2026-05-14', 'standard', 5, 'Izzet Prowess', 'loss', '2026-05-14T00:00:00')"
        )
        m2 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute(
            "INSERT INTO match_log (event_date, format, my_deck_id, opp_deck, result, created_at) "
            "VALUES ('2026-05-14', 'standard', 5, 'Azorius Control', 'win', '2026-05-14T00:00:00')"
        )
        m3 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.commit()

    from db.match_sb_plans import save_plans_for_match, get_plans_for_deck
    # m1, m2 (vs Izzet) both bring in 2 Path
    save_plans_for_match(m1, [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [101] * 2 + [105, 105] + [103] * 16, "sb": []},
    ])
    save_plans_for_match(m2, [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [101] * 2 + [105, 105] + [103] * 16, "sb": []},
    ])
    # m3 (vs Azorius) brings in 1 Negate
    save_plans_for_match(m3, [
        {"main": [101] * 4 + [103] * 16, "sb": []},
        {"main": [101] * 3 + [106] + [103] * 16, "sb": []},
    ])

    agg = get_plans_for_deck(5)
    assert len(agg) == 2
    by_opp = {a["opp_archetype"]: a for a in agg}
    assert by_opp["Izzet Prowess"]["total_matches"] == 2
    # 2 matches x 2 Path each = 4 total
    assert by_opp["Izzet Prowess"]["cards_in"]["Path to Exile"] == 4
    assert by_opp["Azorius Control"]["total_matches"] == 1
    assert by_opp["Azorius Control"]["cards_in"]["Negate"] == 1
