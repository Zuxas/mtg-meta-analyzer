"""Personal match stats must see BOTH ways a match is linked to your deck.

`match_log` carries two links: the legacy free-text `my_deck` column and
`my_deck_id`, the FK to `saved_decks` that the MTGA importer + the Resolve
dialog populate. `get_matchup_stats` / `get_overall_stats` / `get_trend_data`
filtered on the TEXT column only, so a row linked by id with a blank
`my_deck` was invisible -- on the live DB (2026-09-22) that is 15 of 109
rows, and it silently emptied every consumer: Event Optimizer's personal
column, the hypotheses tab's evidence, the prep checklist, Simulate's prior
and `analysis/matchup_advisor.get_advice`.

Matching is by `my_deck` text OR the linked saved deck's archetype/name
(case-insensitive), which is what every caller passes.
"""
import pytest


@pytest.fixture
def log_db():
    from db.database import init_db, get_connection
    import db.saved_decks as saved_decks
    from db.match_log import _ensure_table
    init_db()
    _ensure_table()
    saved_decks._ensure_tables()
    deck_id = saved_decks.save_deck(
        name="Izzet Prowess (auto-imported 2026-05-14)", format_name="standard",
        archetype="Izzet Prowess", mainboard={"Monastery Swiftspear": 4}, sideboard={})

    def add(result, *, my_deck="", deck_id_=None, opp="Dimir Aggro", date="2026-05-10",
            fmt="standard", play_draw="play"):
        with get_connection() as con:
            con.execute(
                "INSERT INTO match_log (event_name, event_date, format, round, my_deck, opp_deck, "
                "opp_name, result, play_draw, my_deck_id, source, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("Ranked", date, fmt, 1, my_deck, opp, "opp", result, play_draw, deck_id_,
                 "mtga", date + "T12:00:00Z"))

    return {"deck_id": deck_id, "add": add}


def test_matchup_stats_counts_rows_linked_only_by_deck_id(log_db):
    from db.match_log import get_matchup_stats
    add, did = log_db["add"], log_db["deck_id"]
    add("win", my_deck="Izzet Prowess")                    # legacy text link
    add("loss", deck_id_=did)                              # id link, blank text
    add("win", deck_id_=did)
    stats = get_matchup_stats("Izzet Prowess", "standard")
    assert stats["Dimir Aggro"]["total"] == 3
    assert stats["Dimir Aggro"]["wins"] == 2 and stats["Dimir Aggro"]["losses"] == 1


def test_a_row_linked_both_ways_is_counted_once(log_db):
    from db.match_log import get_matchup_stats
    log_db["add"]("win", my_deck="Izzet Prowess", deck_id_=log_db["deck_id"])
    assert get_matchup_stats("Izzet Prowess", "standard")["Dimir Aggro"]["total"] == 1


def test_matching_is_case_insensitive_on_the_linked_archetype(log_db):
    from db.match_log import get_matchup_stats
    log_db["add"]("win", deck_id_=log_db["deck_id"])
    assert get_matchup_stats("izzet prowess", "standard")["Dimir Aggro"]["total"] == 1


def test_other_decks_are_not_swept_in(log_db):
    from db.database import get_connection
    from db.match_log import get_matchup_stats
    import db.saved_decks as saved_decks
    other = saved_decks.save_deck(name="Dimir Aggro", format_name="standard",
                                  archetype="Dimir Aggro", mainboard={"Island": 4}, sideboard={})
    log_db["add"]("win", deck_id_=log_db["deck_id"])
    log_db["add"]("loss", deck_id_=other, opp="Boros Energy")
    stats = get_matchup_stats("Izzet Prowess", "standard")
    assert set(stats) == {"Dimir Aggro"} and stats["Dimir Aggro"]["total"] == 1


def test_format_and_since_filters_still_apply_to_linked_rows(log_db):
    from db.match_log import get_matchup_stats
    add, did = log_db["add"], log_db["deck_id"]
    add("win", deck_id_=did, date="2026-05-01")
    add("win", deck_id_=did, date="2026-06-01")
    add("win", deck_id_=did, date="2026-06-02", fmt="modern")
    assert get_matchup_stats("Izzet Prowess", "standard")["Dimir Aggro"]["total"] == 2
    assert get_matchup_stats("Izzet Prowess", "standard", since="2026-05-15")["Dimir Aggro"]["total"] == 1
    assert get_matchup_stats("Izzet Prowess", "modern")["Dimir Aggro"]["total"] == 1


def test_overall_stats_and_trend_see_linked_rows_too(log_db):
    from db.match_log import get_overall_stats, get_trend_data
    add, did = log_db["add"], log_db["deck_id"]
    add("win", my_deck="Izzet Prowess", date="2026-05-10")
    add("loss", deck_id_=did, date="2026-05-11")
    overall = get_overall_stats("Izzet Prowess", "standard")
    assert (overall["wins"], overall["losses"], overall["total"]) == (1, 1, 2)
    trend = get_trend_data("Izzet Prowess", "standard")
    assert [(d["date"], d["wins"], d["losses"]) for d in trend] == \
        [("2026-05-10", 1, 0), ("2026-05-11", 0, 1)]


def test_unlinked_rows_stay_out(log_db):
    """73 live rows have neither link -- they are the Resolve-dialog backlog,
    not this deck's matches, and must not be attributed to it."""
    from db.match_log import get_matchup_stats
    log_db["add"]("win")                                   # no text, no id
    assert get_matchup_stats("Izzet Prowess", "standard") == {}


def test_get_matches_filters_by_either_link_with_a_format_filter(log_db):
    """Ordering trap: get_matches appends the format filter BEFORE the deck
    clause, so numbered (?1) placeholders in the clause would bind to the
    format string instead. Plain placeholders + one param each avoid it."""
    from db.match_log import get_matches
    add, did = log_db["add"], log_db["deck_id"]
    add("win", my_deck="Izzet Prowess", date="2026-05-10")
    add("loss", deck_id_=did, date="2026-05-11")
    add("win", deck_id_=did, date="2026-05-12", fmt="modern")
    rows = get_matches(format_name="standard", my_deck="Izzet Prowess")
    assert len(rows) == 2 and {r["result"] for r in rows} == {"win", "loss"}
    assert len(get_matches(my_deck="Izzet Prowess")) == 3
