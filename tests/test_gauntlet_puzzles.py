"""Gauntlet lethal puzzles (spec harness/specs/2026-09-29-gauntlet-lethal-puzzles.md).

mtg-sim's `mine_gauntlet_puzzles.py` mines "lethal this turn" positions from
two-player sim games, so each scene has a REAL opponent board (untapped
blockers, other permanents) and a revealed hand the kill was verified against.
Covers the analyzer side: scene loading, the promote pre-fill, the import
bridge (dry run by default), and the scene widget.

Fixtures are synthetic (the repo is public) but shaped exactly like the miner's
JSONL lines.
"""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from analysis.puzzles.scene_builder import Scene
from gui.tabs.puzzles import _prefill_from_evidence


def _card(name, p=None, t=None, tapped=False, sick=False, **extra):
    d = {"name": name, "tapped": tapped, "summoning_sick": sick}
    if p is not None:
        d.update(power=p, toughness=t)
    d.update(extra)
    return d


def _miner_scene() -> dict:
    """What mine_gauntlet_puzzles._scene emits (plus an unknown future key)."""
    return {
        "arena_match_id": "", "game_num": 0, "turn_num": 5, "play_or_draw": "play",
        "you": {
            "name": "You", "archetype": "Boros Energy", "life": 23,
            "hand": [_card("Galvanic Discharge")], "hand_count": 1,
            "battlefield_lands": [_card("Sacred Foundry")],
            "battlefield_creatures": [_card("Guide of Souls", 1, 2),
                                      _card("Ocelot Pride", 1, 1, sick=True)],
            "battlefield_other": [_card("Goblin Bombardment")],
            "graveyard_count": 3, "library_count": 45, "mana_available": {},
        },
        "opp": {
            "name": "Dimir Midrange", "archetype": "Dimir Midrange", "life": 9,
            "hand": [_card("Polluted Delta")], "hand_count": 1,
            "battlefield_lands": [_card("Watery Grave")],
            "battlefield_creatures": [_card("Subtlety", 3, 3),
                                      _card("Orcish Bowmasters", 1, 1, tapped=True)],
            "battlefield_other": [_card("Kaito, Bane of Nightmares",
                                        future_field="ignored")],
            "graveyard_count": 2, "library_count": 44, "mana_available": {},
        },
        "notes": "Sim position vs Dimir Midrange, turn 5.",
    }


def _gauntlet_row(apl_found=False) -> dict:
    return {"evidence": json.dumps({
        "source": "gauntlet-miner",
        "solution_line": ["Galvanic Discharge"],
        "scene": _miner_scene(),
        "opp_deck": "Dimir Midrange", "apl_found": apl_found,
        "live_blockers": 1, "caveats": ["engine truth"],
    })}


# ---------------------------------------------------------------- scene model

def test_scene_loads_miner_dict_and_ignores_unknown_card_keys():
    scene = Scene.from_dict(_miner_scene())
    assert scene.opp.battlefield_other[0].name == "Kaito, Bane of Nightmares"
    assert scene.you.battlefield_creatures[1].summoning_sick is True
    assert scene.opp.battlefield_creatures[1].tapped is True
    assert scene.opp.hand_count == 1 and scene.opp.hand[0].name == "Polluted Delta"


def test_old_scene_dicts_still_load():
    d = _miner_scene()
    for side in ("you", "opp"):
        d[side].pop("hand_count")
        for zone in ("hand", "battlefield_lands", "battlefield_creatures",
                     "battlefield_other"):
            for c in d[side][zone]:
                c.pop("summoning_sick", None)
                c.pop("future_field", None)
    scene = Scene.from_dict(d)
    assert scene.opp.hand_count is None
    assert scene.you.battlefield_creatures[1].summoning_sick is False


def test_hand_size_uses_count_when_cards_hidden():
    from gui.widgets.puzzle_scene import hand_size
    scene = Scene.from_dict(_miner_scene())
    assert hand_size(scene.opp) == 1
    scene.opp.hand = []
    scene.opp.hand_count = 4
    assert hand_size(scene.opp) == 4
    scene.opp.hand_count = None
    assert hand_size(scene.opp) == 0


# ---------------------------------------------------------------- promote pre-fill

def test_prefill_gauntlet_question_names_opponent_blockers_and_hand():
    scene, kw = _prefill_from_evidence(_gauntlet_row())
    q = kw["suggested_question"]
    assert "Dimir Midrange is at 9" in q
    assert "1 untapped creature" in q          # Subtlety; the tapped Bowmasters can't block
    assert "hand revealed" in q
    assert kw["suggested_keywords"] == ["Galvanic Discharge"]
    assert "Cast Galvanic Discharge" in kw["suggested_solution"]
    assert scene.opp.life == 9


def test_prefill_gauntlet_difficulty_tracks_whether_the_pilot_found_it():
    assert _prefill_from_evidence(_gauntlet_row(apl_found=False))[1]["suggested_difficulty"] == 4
    assert _prefill_from_evidence(_gauntlet_row(apl_found=True))[1]["suggested_difficulty"] == 3


def test_prefill_goldfish_path_unchanged():
    d = _miner_scene()
    row = {"evidence": json.dumps({"solution_line": ["Lightning Bolt"],
                                   "greedy_misses": False, "scene": d})}
    kw = _prefill_from_evidence(row)[1]
    assert kw["suggested_question"].startswith("You have lethal this turn")
    assert kw["suggested_difficulty"] == 2


# ---------------------------------------------------------------- import bridge

@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "a.db")
    return tmp_path


def _jsonl(tmp_path):
    cand = {
        "arena_match_id": "gauntlet:Boros Energy|Dimir Midrange|77", "game_num": 1,
        "turn_num": 5, "category": "find_lethal", "heuristic_score": 3.6,
        "solution_line": ["Galvanic Discharge"], "scene": _miner_scene(),
        "source": "gauntlet-miner", "our_deck": "Boros Energy",
        "opp_deck": "Dimir Midrange", "apl_found": False, "live_blockers": 1,
        "opp_permanents": 3, "caveats": ["engine truth"],
    }
    p = tmp_path / "cands.jsonl"
    p.write_text(json.dumps(cand) + "\n", encoding="utf-8")
    return p


def test_import_row_carries_source_and_gauntlet_extras():
    from scripts.import_lethal_puzzles import _to_inbox_row
    cand = json.loads(json.dumps({
        "arena_match_id": "gauntlet:x", "turn_num": 5, "solution_line": ["A"],
        "scene": _miner_scene(), "source": "gauntlet-miner",
        "opp_deck": "Dimir Midrange", "apl_found": True, "live_blockers": 1}))
    ev = json.loads(_to_inbox_row(cand)["evidence"])
    assert ev["source"] == "gauntlet-miner"
    assert ev["opp_deck"] == "Dimir Midrange" and ev["apl_found"] is True
    # goldfish lines (no source) keep their old label
    ev2 = json.loads(_to_inbox_row({"arena_match_id": "g", "turn_num": 1})["evidence"])
    assert ev2["source"] == "goldfish-miner"


def test_import_is_dry_run_by_default_then_commits(tmp_db, capsys):
    from db import puzzles as db_puzzles
    from scripts.import_lethal_puzzles import main
    path = _jsonl(tmp_db)

    assert main([str(path)]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (tmp_db / "t.db").exists() or \
        db_puzzles.get_inbox(category="find_lethal", top_n=100) == []

    assert main([str(path), "--commit"]) == 0
    rows = db_puzzles.get_inbox(category="find_lethal", top_n=100)
    assert len(rows) == 1
    # the committed row promotes straight into a pre-filled gauntlet puzzle
    scene, kw = _prefill_from_evidence(rows[0])
    assert "Dimir Midrange is at 9" in kw["suggested_question"]

    main([str(path)])
    assert "0 would be new, 1 already" in capsys.readouterr().out


# ---------------------------------------------------------------- scene widget

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # never fetch real card images in a unit test -> text placeholders
    monkeypatch.setattr("gui.widgets.puzzle_scene.load_pixmap", lambda **kw: None)
    return QApplication.instance() or QApplication([])


def test_widget_renders_real_opponent_board(app):
    from gui.widgets.puzzle_scene import PuzzleSceneWidget
    w = PuzzleSceneWidget(Scene.from_dict(_miner_scene()))
    try:
        text = " ".join(l.text() for l in w.findChildren(QLabel))
        assert "opp hand (1)<br>revealed" in text
        assert "lands: 1" in text           # no recorded pool -> land count, not 'mana: 0'
        assert "Polluted Delta" in text
        assert "opp other" in text and "Kaito, Bane of Nightmares" in text
        assert "your other" in text and "Goblin Bombardment" in text
        assert "hand: 1" in text
        bowmasters = next(l for l in w.findChildren(QLabel)
                          if "Orcish Bowmasters" in l.text())
        assert "TAPPED" in bowmasters.text()
        subtlety = next(l for l in w.findChildren(QLabel) if "Subtlety" in l.text())
        assert "TAPPED" not in subtlety.text() and "3/3" in subtlety.text()
        ocelot = next(l for l in w.findChildren(QLabel) if "Ocelot Pride" in l.text())
        assert "summoning sick" in ocelot.toolTip()
    finally:
        w.deleteLater()


def test_widget_without_other_permanents_or_revealed_hand_unchanged(app):
    from gui.widgets.puzzle_scene import PuzzleSceneWidget
    d = _miner_scene()
    d["opp"]["hand"] = []
    d["opp"]["battlefield_other"] = []
    d["you"]["battlefield_other"] = []
    w = PuzzleSceneWidget(Scene.from_dict(d))
    try:
        text = " ".join(l.text() for l in w.findChildren(QLabel))
        assert "revealed" not in text
        assert "opp other" not in text and "your other" not in text
        assert "hand: 1" in text        # hidden hand still counted
    finally:
        w.deleteLater()
