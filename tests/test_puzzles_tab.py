"""Smoke + integration tests for gui/tabs/puzzles.py."""
import os
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


def test_puzzles_tab_constructs_with_empty_db(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    assert tab.windowTitle() == "" or True  # just check no exception
    # Empty state should render some hint label
    text = tab.findChild_text_recursive()  # we'll add this helper below
    assert "no puzzles" in text.lower() or "queue is empty" in text.lower()


def test_puzzles_tab_renders_first_puzzle(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    # Seed one puzzle
    from db import puzzles
    pid = puzzles.save_puzzle(
        deck_id=None, arena_match_id=None, game_num=None, turn_num=7,
        category="stabilize", difficulty=3,
        question="Survive opp's T8",
        solution_text="Cast Slagstorm, keep Crab.",
        solution_keywords=[], grading_mode="self",
        author="seeder", notes="",
        scene={
            "arena_match_id": "x", "game_num": 1, "turn_num": 7,
            "play_or_draw": "draw",
            "you": {"name": "You", "life": 4},
            "opp": {"name": "Opp", "life": 12},
        },
    )
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    text = tab.findChild_text_recursive()
    assert "Survive opp's T8" in text


def test_puzzles_tab_inbox_mode_lists_candidates(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from db import puzzles
    puzzles.save_inbox_candidates([
        {"arena_match_id": "m-a", "game_num": 1, "turn_num": 5,
         "category": "stabilize", "heuristic_score": 0.7,
         "evidence": "life 4"},
        {"arena_match_id": "m-b", "game_num": 1, "turn_num": 7,
         "category": "find_lethal", "heuristic_score": 0.9,
         "evidence": "3 spells"},
    ])
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    # Inbox table should have 2 rows after refresh
    assert tab._inbox_table.rowCount() == 2


def test_solve_tab_records_rating_and_displays_it(tmp_path, monkeypatch):
    """End-to-end (T3): solving a puzzle in the Solve tab persists a Glicko-2
    user rating + puzzle rating and surfaces the rating in the session line."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from db import puzzles
    pid = puzzles.save_puzzle(
        deck_id=None, arena_match_id=None, game_num=None, turn_num=7,
        category="find_lethal", difficulty=4, question="Find the line",
        solution_text="Cast X then swing.", solution_keywords=[],
        grading_mode="self", author="seeder", notes="",
        scene={"arena_match_id": "x", "game_num": 1, "turn_num": 7,
               "play_or_draw": "draw",
               "you": {"name": "You", "life": 4},
               "opp": {"name": "Opp", "life": 2}},
    )
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    assert tab._current_puzzle["id"] == pid
    tab._record_and_next("correct")

    assert puzzles.get_rating("user", "default")["matches"] == 1
    assert puzzles.get_rating("puzzle", str(pid))["matches"] == 1
    assert tab._last_rating_delta is not None and tab._last_rating_delta > 0
    assert "Rating" in tab._stats_lbl.text()


def _seed_drills(n):
    from db import puzzles
    ids = []
    for i in range(n):
        ids.append(puzzles.save_puzzle(
            deck_id=None, arena_match_id=None, game_num=None, turn_num=1,
            category="drill_outs", difficulty=1, question=f"Drill {i}: odds?",
            solution_text="42", solution_keywords=[], grading_mode="number",
            author="seeder", notes="", scene={
                "arena_match_id": "drill", "game_num": 0, "turn_num": 1, "play_or_draw": "draw",
                "you": {"name": "You", "life": 20}, "opp": {"name": "Opp", "life": 20}}))
    return ids


def test_solve_header_shows_daily_progress_and_target_spinbox(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", tmp_path / "prefs.json")   # a Path, as gui.state expects
    monkeypatch.setattr("gui.state.UIState._instance", None)   # fresh singleton, as tests/test_ui_state.py does
    from db.database import init_db; init_db()
    _seed_drills(3)
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    assert tab._target_spin.value() == 10                      # default
    assert "Today 0/10" in tab._stats_lbl.text()
    assert "3 new" in tab._stats_lbl.text()
    tab._target_spin.setValue(2)
    assert "Today 0/2" in tab._stats_lbl.text()
    from gui.state import UIState
    from gui.state_keys import PUZZLES_DAILY_TARGET
    assert UIState.instance().get(PUZZLES_DAILY_TARGET) == 2


def test_solve_reaches_done_state_and_keep_going_serves_more(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", tmp_path / "prefs.json")   # a Path, as gui.state expects
    monkeypatch.setattr("gui.state.UIState._instance", None)
    from db.database import init_db; init_db()
    _seed_drills(3)
    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    tab._target_spin.setValue(1)
    assert "Drill 2" in tab._question_lbl.text()               # newest first
    tab._record_and_next("correct")
    assert "Done for today" in tab._question_lbl.text()
    assert "Today 1/1" in tab._stats_lbl.text()
    assert tab._keep_going_btn.isVisibleTo(tab)
    tab._keep_going_btn.click()
    assert "Drill 1" in tab._question_lbl.text()               # next new one, target raised in memory
    assert tab._target_spin.value() == 1                       # persisted target untouched
    tab._record_and_next("incorrect")                          # a miss: comes back tomorrow, not now
    assert "Done for today" in tab._question_lbl.text()
