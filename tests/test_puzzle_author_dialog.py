"""Smoke tests for gui/widgets/puzzle_author_dialog.py."""
import os
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "p.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    yield db_path


def _sample_scene_dict() -> dict:
    return {
        "arena_match_id": "test-m", "game_num": 1, "turn_num": 7,
        "play_or_draw": "draw",
        "you": {"name": "You", "life": 4},
        "opp": {"name": "Opp", "life": 12},
    }


def test_dialog_constructs_with_scene(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene)
    # Form fields exist
    assert dlg._question_edit is not None
    assert dlg._solution_edit is not None
    assert dlg._category_combo is not None


def test_dialog_save_writes_puzzle_to_db(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    from db import puzzles
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene)
    dlg._question_edit.setText("Test Q")
    dlg._solution_edit.setPlainText("Test solution")
    dlg._category_combo.setCurrentIndex(0)  # first category
    pid = dlg._save_and_return_id()
    assert pid is not None
    assert pid >= 1
    p = puzzles.get_puzzle(pid)
    assert p["question"] == "Test Q"
    assert p["solution_text"] == "Test solution"


def test_dialog_inbox_promotion_links_id(tmp_db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from analysis.puzzles.scene_builder import Scene
    from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog
    from db import puzzles
    # Seed an inbox candidate
    puzzles.save_inbox_candidates([{
        "arena_match_id": "m-1", "game_num": 1, "turn_num": 7,
        "category": "stabilize", "heuristic_score": 0.5,
        "evidence": "test",
    }])
    inbox_id = puzzles.get_inbox()[0]["id"]
    scene = Scene.from_dict(_sample_scene_dict())
    dlg = PuzzleAuthorDialog(scene=scene, inbox_id=inbox_id)
    dlg._question_edit.setText("Q")
    dlg._solution_edit.setPlainText("S")
    pid = dlg._save_and_return_id()
    # After save with inbox_id, the inbox row should be promoted
    assert pid is not None
    assert len(puzzles.get_inbox()) == 0  # promoted out
