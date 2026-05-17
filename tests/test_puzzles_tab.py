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
