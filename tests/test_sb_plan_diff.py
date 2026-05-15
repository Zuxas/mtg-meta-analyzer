"""Tests for analysis.sb_plan_diff -- canonical vs actual SB plans."""
import json
import sqlite3
import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "diff.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))

    import db.match_log
    import db.saved_decks
    db.match_log._ensure_table()
    db.saved_decks._ensure_tables()

    return db_path


def _save_canonical_plan(deck_id, opp, play_in, play_out, difficulty="Medium"):
    """Helper to seed saved_sb_plans rows directly."""
    from db.database import get_connection
    from db.helpers import utc_now
    with get_connection() as c:
        c.execute(
            "INSERT INTO saved_sb_plans "
            "(deck_id, opponent_archetype, play_in, play_out, "
            " draw_in, draw_out, difficulty, updated_at) "
            "VALUES (?, ?, ?, ?, '[]', '[]', ?, ?)",
            (deck_id, opp, json.dumps(play_in), json.dumps(play_out),
             difficulty, utc_now()),
        )
        c.commit()


def test_diff_when_actual_matches_canonical_fully(env):
    """If you brought in exactly what the canonical plan said, pct=100%."""
    from db.match_log import save_match
    from db.match_sb_plans import save_plans_for_match
    from analysis.sb_plan_diff import compare_match_to_canonical
    from db.database import get_connection

    # Save a deck
    import db.saved_decks
    deck_id = db.saved_decks.save_deck(
        name="Test Deck", format_name="standard", archetype="Test",
        mainboard={"A": 4}, sideboard={"B": 2},
    )

    # Save a canonical plan: bring in 2 Annul, 1 Negate; take out 3 Hex
    _save_canonical_plan(deck_id, "Selesnya Landfall",
                          play_in=["Annul", "Annul", "Negate"],
                          play_out=["Hex", "Hex", "Hex"])

    # Save a match
    match_id = save_match(
        event_name="Test", event_date="2026-05-14", format_name="standard",
        round_num=1, my_deck="", opp_deck="Selesnya Landfall",
        result="win",
    )
    # Set my_deck_id
    with get_connection() as c:
        c.execute("UPDATE match_log SET my_deck_id=? WHERE id=?", (deck_id, match_id))
        c.commit()

    # Save SB plan that exactly matches canonical
    save_plans_for_match(match_id, [
        {"main": [], "sb": []},  # game 1: placeholder
        {"main": [], "sb": []},  # game 2
    ])
    # Override the saved plans with exact-match cards
    with get_connection() as c:
        c.execute(
            "UPDATE match_log_sb_plans SET cards_in_json=?, cards_out_json=? "
            "WHERE match_log_id=?",
            (json.dumps({"Annul": 2, "Negate": 1}),
             json.dumps({"Hex": 3}), match_id),
        )
        c.commit()

    diff = compare_match_to_canonical(match_id)
    assert diff is not None
    assert diff["canonical_archetype"] == "Selesnya Landfall"
    assert len(diff["transitions"]) == 1
    t = diff["transitions"][0]
    assert t["in_match_pct"] == 100.0
    assert t["in_missing"] == {}
    assert t["in_unplanned"] == {}


def test_diff_partial_match_reports_missing_and_unplanned(env):
    """If canonical says bring 2 Annul, you brought 1 + something else,
    we should report 1 missing Annul and 1 unplanned card."""
    from db.match_log import save_match
    from db.match_sb_plans import save_plans_for_match
    from analysis.sb_plan_diff import compare_match_to_canonical
    from db.database import get_connection
    import db.saved_decks
    deck_id = db.saved_decks.save_deck(
        name="Test", format_name="standard", archetype="X",
        mainboard={}, sideboard={},
    )
    _save_canonical_plan(deck_id, "Foo",
                          play_in=["Annul", "Annul", "Negate"],
                          play_out=["Hex"])
    mid = save_match(event_name="T", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck="",
                     opp_deck="Foo", result="loss")
    with get_connection() as c:
        c.execute("UPDATE match_log SET my_deck_id=? WHERE id=?", (deck_id, mid))
        c.commit()
    save_plans_for_match(mid, [{"main": [], "sb": []},
                                {"main": [], "sb": []}])
    with get_connection() as c:
        c.execute(
            "UPDATE match_log_sb_plans SET cards_in_json=?, cards_out_json=? "
            "WHERE match_log_id=?",
            (json.dumps({"Annul": 1, "Spell Pierce": 2}),
             json.dumps({"Hex": 1}), mid),
        )
        c.commit()

    diff = compare_match_to_canonical(mid)
    t = diff["transitions"][0]
    # 1 Annul followed + 0 Negate followed = 1 of 3 canonical IN = 33%
    assert abs(t["in_match_pct"] - 33.3) < 1.0
    assert t["in_missing"] == {"Annul": 1, "Negate": 1}
    assert t["in_unplanned"] == {"Spell Pierce": 2}


def test_returns_none_when_no_canonical_for_opp(env):
    from db.match_log import save_match
    from analysis.sb_plan_diff import compare_match_to_canonical
    from db.database import get_connection
    import db.saved_decks
    deck_id = db.saved_decks.save_deck(
        name="T", format_name="standard", archetype="X",
        mainboard={}, sideboard={},
    )
    mid = save_match(event_name="T", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck="",
                     opp_deck="No Plan Exists For This", result="win")
    with get_connection() as c:
        c.execute("UPDATE match_log SET my_deck_id=? WHERE id=?", (deck_id, mid))
        c.commit()
    assert compare_match_to_canonical(mid) is None


def test_returns_none_when_no_my_deck_id(env):
    from db.match_log import save_match
    from analysis.sb_plan_diff import compare_match_to_canonical
    mid = save_match(event_name="T", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck="",
                     opp_deck="X", result="win")
    # my_deck_id stays None
    assert compare_match_to_canonical(mid) is None


def test_fuzzy_archetype_match_drops_parenthetical(env):
    """Plan with '(Stormchaser)' suffix should match opp 'Izzet Lessons'."""
    from db.match_log import save_match
    from db.match_sb_plans import save_plans_for_match
    from analysis.sb_plan_diff import compare_match_to_canonical
    from db.database import get_connection
    import db.saved_decks
    deck_id = db.saved_decks.save_deck(
        name="T", format_name="standard", archetype="X",
        mainboard={}, sideboard={},
    )
    _save_canonical_plan(deck_id, "Izzet Lessons (Stormchaser)",
                          play_in=["Spell Pierce"], play_out=["Show-Off"])
    mid = save_match(event_name="T", event_date="2026-05-14",
                     format_name="standard", round_num=1, my_deck="",
                     opp_deck="Izzet Lessons", result="win")
    with get_connection() as c:
        c.execute("UPDATE match_log SET my_deck_id=? WHERE id=?", (deck_id, mid))
        c.commit()
    save_plans_for_match(mid, [{"main": [], "sb": []},
                                {"main": [], "sb": []}])
    diff = compare_match_to_canonical(mid)
    assert diff is not None
    assert "Izzet Lessons" in diff["canonical_archetype"]
