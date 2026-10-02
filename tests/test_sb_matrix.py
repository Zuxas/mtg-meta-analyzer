"""Tests for analysis.sb_matrix + db.saved_decks.save_sb_plans_atomic + the CLI.

Spec: harness/specs/2026-09-26-session-assets-intake.md (gate G1).
Every test here is one a wrong implementation would fail.
"""
import json
import os
from collections import Counter

import pytest

from analysis import sb_matrix as sbm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_JSON = os.path.join(ROOT, "data", "sb_matrices", "izzet_prowess_locked_2026-09-25.json")
FIX_TXT = os.path.join(ROOT, "data", "sb_matrices", "izzet_prowess_locked_2026-09-25.txt")

MAIN = {"Lightning Bolt": 4, "Expressive Iteration": 3, "Witch Enchanter // Witch-Blessed Meadow": 2,
        "Mutagenic Growth": 4, "Island": 47}
SIDE = {"Unholy Heat": 3, "Consign to Memory": 4, "Spell Pierce": 2, "Meltdown": 2, "Plains": 4}


def _m(matchups, **kw):
    d = {"schema": sbm.SCHEMA, "source": "test", "matchups": matchups}
    d.update(kw)
    return d


def _resolve(matchups):
    return sbm.resolve_against_deck(sbm.parse_matrix(_m(matchups)), MAIN, SIDE)


# --------------------------------------------------------------------------- parse

def test_parse_reports_every_problem_not_just_the_first():
    bad = _m({"A": {"out": {"Lightning Bolt": "3"}, "in": {"Unholy Heat": -1}, "bogus": 1},
              "B": {"out": {}, "in": {}, "difficulty": "Brutal"}}, schema="sb-matrix/0")
    with pytest.raises(sbm.MatrixError) as ei:
        sbm.parse_matrix(bad)
    text = str(ei.value)
    for needle in ("schema", "must be an integer", "negative", "unknown keys", "difficulty"):
        assert needle in text, needle
    assert len(ei.value.problems) >= 5


def test_duplicate_matchup_names_case_insensitive_rejected():
    with pytest.raises(sbm.MatrixError, match="duplicate"):
        sbm.parse_matrix(_m({"Eldrazi Tron": {}, "eldrazi tron": {}}))


def test_zero_counts_are_dropped_not_errors():
    r, p = _resolve({"A": {"out": {"Lightning Bolt": 1, "Mutagenic Growth": 0},
                           "in": {"Unholy Heat": 1}}})
    assert p == []
    assert r.matchups[0].play.out == Counter({"Lightning Bolt": 1})


# --------------------------------------------------------------------------- validate

def test_unbalanced_column_is_rejected():
    _, p = _resolve({"A": {"out": {"Lightning Bolt": 3}, "in": {"Unholy Heat": 2}}})
    assert any("3 out vs 2 in" in x for x in p)


def test_out_is_bounded_by_main_copies_and_in_by_side_copies():
    _, p = _resolve({"A": {"out": {"Expressive Iteration": 4}, "in": {"Consign to Memory": 4}},
                     "B": {"out": {"Lightning Bolt": 4}, "in": {"Unholy Heat": 4}}})
    assert any("OUT 4 Expressive Iteration but the main deck has 3" in x for x in p)
    assert any("IN 4 Unholy Heat but the sideboard has 3" in x for x in p)


def test_card_on_wrong_side_gets_a_hint():
    _, p = _resolve({"A": {"out": {"Unholy Heat": 1}, "in": {"Lightning Bolt": 1}}})
    assert any("not in the main deck (it is in the SIDEBOARD)" in x for x in p)
    assert any("not in the sideboard (it is in the MAIN deck)" in x for x in p)


def test_unknown_card_rejected():
    _, p = _resolve({"A": {"out": {"Lightning Bolt": 1}, "in": {"Surgical Extraction": 1}}})
    assert any("Surgical Extraction" in x for x in p)


def test_card_both_in_and_out_rejected():
    main = dict(MAIN, **{"Unholy Heat": 1})
    m = sbm.parse_matrix(_m({"A": {"out": {"Unholy Heat": 1}, "in": {"Unholy Heat": 1}}}))
    _, p = sbm.resolve_against_deck(m, main, SIDE)
    assert any("both boarded out and in" in x for x in p)


def test_names_match_despite_case_apostrophes_and_mdfc_front_face():
    r, p = _resolve({"A": {"out": {"witch enchanter": 2, "LIGHTNING  BOLT": 1},
                           "in": {"Consign to Memory": 3}}})
    assert p == []
    out = r.matchups[0].play.out
    assert out["Witch Enchanter // Witch-Blessed Meadow"] == 2   # respelled as the deck has it
    assert out["Lightning Bolt"] == 1
    assert sbm.resolve_name("Thalia’s Lieutenant", ["Thalia's Lieutenant"]) == "Thalia's Lieutenant"


def test_play_and_draw_overrides_are_validated_separately():
    r, p = _resolve({"A": {"out": {"Lightning Bolt": 2}, "in": {"Unholy Heat": 2},
                           "draw": {"out": {"Expressive Iteration": 3}, "in": {"Spell Pierce": 2}}}})
    assert any("[draw]: 3 out vs 2 in" in x for x in p)
    assert not any("[play]" in x for x in p)


# --------------------------------------------------------------------------- rows / round trip

def test_rows_use_repeated_name_lists_like_the_db_and_sb_plan_diff():
    r, _ = _resolve({"A": {"out": {"Lightning Bolt": 2, "Mutagenic Growth": 1},
                           "in": {"Unholy Heat": 3}}})
    row = sbm.to_plan_rows(r, "abcdefabcdef")[0]
    assert Counter(row["play_out"]) == Counter({"Lightning Bolt": 2, "Mutagenic Growth": 1})
    assert row["play_in"] == ["Unholy Heat"] * 3
    assert row["draw_in"] == row["play_in"]          # no override -> identical draw side


def test_round_trip_matrix_rows_matrix_is_semantically_identical():
    src = _m({"A": {"out": {"Lightning Bolt": 2}, "in": {"Unholy Heat": 2}, "note": "kill stuff",
                    "difficulty": "Hard",
                    "draw": {"out": {"Expressive Iteration": 1}, "in": {"Spell Pierce": 1}}},
              "B": {"out": {"Mutagenic Growth": 4}, "in": {"Consign to Memory": 4}}})
    r1, p = sbm.resolve_against_deck(sbm.parse_matrix(src), MAIN, SIDE)
    assert p == []
    back = sbm.plans_to_matrix(sbm.to_plan_rows(r1, "0" * 12))
    r2, p2 = sbm.resolve_against_deck(sbm.parse_matrix(back), MAIN, SIDE)
    assert p2 == []
    for a, b in zip(r1.matchups, r2.matchups):
        assert (a.opponent, a.note, a.difficulty) == (b.opponent, b.note, b.difficulty)
        assert (a.play.out, a.play.inn, a.draw.out, a.draw.inn) == \
               (b.play.out, b.play.inn, b.draw.out, b.draw.inn)
    assert "draw" in back["matchups"]["A"] and "draw" not in back["matchups"]["B"]


def test_plans_to_matrix_tolerates_dirty_legacy_rows():
    rows = [{"opponent_archetype": "Old", "play_in": "not json", "play_out": None,
             "draw_in": ["X", 3, ""], "draw_out": '["Y"]', "notes": None, "difficulty": None}]
    doc = sbm.plans_to_matrix(rows)
    assert doc["matchups"]["Old"]["draw"] == {"out": {"Y": 1}, "in": {"X": 1}}
    html = sbm.render_html("t", MAIN, SIDE, rows)         # must not raise either
    assert "Old" in html


# --------------------------------------------------------------------------- fingerprint

def test_fingerprint_ignores_spelling_but_not_counts_or_placement():
    fp = sbm.deck_fingerprint(MAIN, SIDE)
    respelled = {k.upper(): v for k, v in MAIN.items()}
    assert sbm.deck_fingerprint(respelled, SIDE) == fp
    assert sbm.deck_fingerprint(dict(MAIN, **{"Lightning Bolt": 3}), SIDE) != fp
    moved_main = dict(MAIN); moved_main.pop("Expressive Iteration")
    moved_side = dict(SIDE, **{"Expressive Iteration": 3})
    assert sbm.deck_fingerprint(moved_main, moved_side) != fp


def test_stale_detection():
    r, _ = _resolve({"A": {"out": {"Lightning Bolt": 1}, "in": {"Unholy Heat": 1}}})
    row = sbm.to_plan_rows(r, sbm.deck_fingerprint(MAIN, SIDE), "src")[0]
    assert sbm.plan_is_stale(row, MAIN, SIDE) is False
    assert sbm.plan_is_stale(row, dict(MAIN, **{"Lightning Bolt": 3}), SIDE) is True
    assert sbm.plan_is_stale({"notes": "typed in the GUI"}, MAIN, SIDE) is None
    # provenance never leaks into the exported note
    assert sbm.plans_to_matrix([row])["matchups"]["A"].get("note") is None


def test_html_escapes_and_flags_imbalance():
    rows = [{"opponent_archetype": "<script>x</script>", "play_in": ["Unholy Heat"],
             "play_out": ["Lightning Bolt", "Lightning Bolt"], "draw_in": ["Unholy Heat"],
             "draw_out": ["Lightning Bolt", "Lightning Bolt"], "notes": "a & b"}]
    html = sbm.render_html("T", MAIN, SIDE, rows)
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert 'class="x">2/1<' in html


# --------------------------------------------------------------------------- decklist

def test_parse_decklist_header_and_blank_line_styles():
    a = sbm.parse_decklist("4 Bolt\n2 Heat\n\n// Sideboard\n3 Pierce\n")
    b = sbm.parse_decklist("4 Bolt\n2 Heat\n\n3 Pierce\n")
    c = sbm.parse_decklist("4x Bolt\nSideboard:\n3 Pierce")
    assert a == b == ({"Bolt": 4, "Heat": 2}, {"Pierce": 3})
    assert c == ({"Bolt": 4}, {"Pierce": 3})


def test_shipped_prowess_matrix_validates_against_its_75():
    """Gate G3: the real matrix committed alongside this module."""
    with open(FIX_TXT, encoding="utf-8") as fh:
        main, side = sbm.parse_decklist(fh.read())
    assert (sum(main.values()), sum(side.values())) == (60, 15)
    with open(FIX_JSON, encoding="utf-8") as fh:
        m = sbm.parse_matrix(json.load(fh))
    r, p = sbm.resolve_against_deck(m, main, side)
    assert p == []
    assert len(r.matchups) == 20


# --------------------------------------------------------------------------- DB (tmp DB via the guard)

@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", str(tmp_path / "sbm.db"))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    import db.saved_decks
    db.saved_decks._ensure_tables()
    return db.saved_decks


def test_atomic_save_writes_all_or_nothing(db_env):
    sd = db_env
    deck_id = sd.save_deck("D", "modern", "Izzet Prowess", MAIN, SIDE)
    r, _ = _resolve({"A": {"out": {"Lightning Bolt": 1}, "in": {"Unholy Heat": 1}},
                     "B": {"out": {"Mutagenic Growth": 2}, "in": {"Spell Pierce": 2}}})
    rows = sbm.to_plan_rows(r, sbm.deck_fingerprint(MAIN, SIDE))
    assert sd.save_sb_plans_atomic(deck_id, rows) == 2
    assert {p["opponent_archetype"] for p in sd.get_sb_plans(deck_id)} == {"A", "B"}

    # A batch whose LAST row is bad must not leave its first row behind.
    bad = [dict(rows[0], opponent_archetype="C"), {"opponent_archetype": "  "}]
    with pytest.raises(ValueError):
        sd.save_sb_plans_atomic(deck_id, bad)
    assert {p["opponent_archetype"] for p in sd.get_sb_plans(deck_id)} == {"A", "B"}

    with pytest.raises(ValueError, match="does not exist"):
        sd.save_sb_plans_atomic(deck_id + 99, rows)


def test_persisted_plans_round_trip_and_feed_sb_plan_diff_shape(db_env):
    sd = db_env
    deck_id = sd.save_deck("D", "modern", "Izzet Prowess", MAIN, SIDE)
    src = _m({"Eldrazi Tron": {"out": {"Expressive Iteration": 3}, "in": {"Consign to Memory": 3},
                               "note": "Consign Trinisphere."}})
    r, _ = sbm.resolve_against_deck(sbm.parse_matrix(src), MAIN, SIDE)
    sd.save_sb_plans_atomic(deck_id, sbm.to_plan_rows(r, sbm.deck_fingerprint(MAIN, SIDE)))
    plan = sd.get_sb_plan(deck_id, "Eldrazi Tron")
    # what sb_plan_diff does with it:
    assert dict(Counter(plan["play_in"])) == {"Consign to Memory": 3}
    assert sbm.plan_is_stale(plan, MAIN, SIDE) is False
    back = sbm.plans_to_matrix(sd.get_sb_plans(deck_id))
    assert back["matchups"]["Eldrazi Tron"] == {"out": {"Expressive Iteration": 3},
                                               "in": {"Consign to Memory": 3},
                                               "note": "Consign Trinisphere."}


def test_cli_dry_run_writes_nothing_and_commit_writes(db_env, tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "import_sb_matrix", os.path.join(ROOT, "scripts", "import_sb_matrix.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    sd = db_env
    deck_id = sd.save_deck("D", "modern", "Izzet Prowess", MAIN, SIDE)
    mpath = tmp_path / "m.json"
    mpath.write_text(json.dumps(_m({"A": {"out": {"Lightning Bolt": 1}, "in": {"Unholy Heat": 1}}})),
                     encoding="utf-8")
    assert cli.main(["--matrix", str(mpath), "--deck-id", str(deck_id)]) == 0
    assert sd.get_sb_plans(deck_id) == []
    assert "DRY RUN" in capsys.readouterr().out
    assert cli.main(["--matrix", str(mpath), "--deck-id", str(deck_id), "--commit"]) == 0
    assert len(sd.get_sb_plans(deck_id)) == 1

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_m({"Z": {"out": {"Lightning Bolt": 2}, "in": {"Unholy Heat": 1}}})),
                   encoding="utf-8")
    assert cli.main(["--matrix", str(bad), "--deck-id", str(deck_id), "--commit"]) == 1
    assert {p["opponent_archetype"] for p in sd.get_sb_plans(deck_id)} == {"A"}

    out_html = tmp_path / "m.html"
    assert cli.main(["--deck-id", str(deck_id), "--html", str(out_html)]) == 0
    assert "Lightning Bolt" in out_html.read_text(encoding="utf-8")
