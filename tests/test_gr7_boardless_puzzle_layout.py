"""Tests for GR-7 (boardless puzzle layout): gui/tabs/puzzles.py + gui/widgets/puzzle_scene.py.

GR-7 gate (harness/handoffs/mta-gui-polish-2026-07-10.md):
  "for a drill_outs puzzle, PuzzleSceneWidget is not visible (widget
  assert) and the question panel occupies >= 60% width (screenshot);
  board-having puzzles still render the scene (regression screenshot)."

Offscreen-Qt pattern per tests/test_gr4_empty_on_open.py /
tests/test_dashboard_filter_row.py (QT_QPA_PLATFORM=offscreen,
QApplication.instance() or QApplication([]), a real QMainWindow so
isVisible() reflects the real ancestor-visibility chain, resize + show +
pump processEvents so the splitter layout settles before measuring).

PuzzlesTab.cleanup() is a no-op (Solve mode is synchronous DB reads, no
QThread worker) so this file does not need the _quiesce() worker-drain
dance from test_gr4_empty_on_open.py -- win.close() in a finally is enough.

card_image_cache.load_pixmap is monkeypatched to return None in every
test here: PuzzleSceneWidget.set_scene() otherwise tries a real
(blocking, up-to-8s-per-card) Scryfall network fetch for any battlefield
card, which must never run in a unit test. With it patched, cards render
via the text-placeholder QLabel path -- exactly what lets the regression
test assert the card's name actually rendered.
"""
import pytest

from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_network_card_images(monkeypatch):
    """Never let a puzzle scene render attempt a real Scryfall fetch."""
    monkeypatch.setattr("gui.widgets.puzzle_scene.load_pixmap", lambda **kw: None)


def _windowed_tab(app, tab, width=1000, height=650):
    win = QMainWindow()
    win.setCentralWidget(tab)
    win.resize(width, height)
    win.show()
    for _ in range(3):
        app.processEvents()
    return win


def _seed_puzzle(db_puzzles, *, category, scene, difficulty=2, grading_mode="self"):
    return db_puzzles.save_puzzle(
        deck_id=None, arena_match_id=None, game_num=None, turn_num=1,
        category=category, difficulty=difficulty,
        question="Test question",
        solution_text="Test solution.",
        solution_keywords=[], grading_mode=grading_mode,
        author="seeder", notes="",
        scene=scene,
    )


def test_drill_outs_puzzle_hides_scene_and_expands_question_panel(
    app, tmp_path, monkeypatch
):
    """A boardless drill_outs puzzle: PuzzleSceneWidget must not be
    visible, and the question panel must occupy >= 60% of the tab
    width (the compact question-card layout, not a full empty
    battlefield)."""
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from db import puzzles as db_puzzles

    # Mirrors analysis.puzzles.drill_generator._drill_scene: a valid but
    # boardless Scene -- life + library_count only, no hand/battlefield.
    _seed_puzzle(
        db_puzzles, category="drill_outs", grading_mode="number",
        scene={
            "arena_match_id": "drill", "game_num": 0, "turn_num": 1,
            "play_or_draw": "draw",
            "you": {"name": "You", "life": 20, "library_count": 40},
            "opp": {"name": "Opp", "life": 20},
        },
    )

    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    win = _windowed_tab(app, tab)
    try:
        assert tab._current_puzzle is not None
        assert tab._current_puzzle["category"] == "drill_outs"

        assert not tab._scene_widget.isVisible(), (
            "PuzzleSceneWidget must be hidden entirely for a boardless "
            "(drill_outs) puzzle"
        )

        tab_width = tab.width()
        panel_width = tab._question_panel.width()
        fraction = panel_width / tab_width if tab_width else 0
        assert fraction >= 0.6, (
            f"question panel occupies {fraction:.2f} of tab width "
            f"({panel_width}/{tab_width}), expected >= 0.6"
        )
    finally:
        tab.cleanup()
        win.close()


def test_board_having_puzzle_still_renders_scene(app, tmp_path, monkeypatch):
    """Regression: a puzzle whose scene has real battlefield content must
    render the full board -- PuzzleSceneWidget stays visible and shows
    the card, unaffected by the GR-7 boardless-layout change."""
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "p.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "p_arc.db")
    from db import puzzles as db_puzzles

    _seed_puzzle(
        db_puzzles, category="find_lethal", difficulty=3,
        scene={
            "arena_match_id": "m-board", "game_num": 1, "turn_num": 8,
            "play_or_draw": "play",
            "you": {
                "name": "You", "life": 14,
                "battlefield_creatures": [
                    {"name": "Grizzly Bears", "power": 2, "toughness": 2},
                ],
            },
            "opp": {"name": "Opp", "life": 6},
        },
    )

    from gui.tabs.puzzles import PuzzlesTab
    tab = PuzzlesTab()
    win = _windowed_tab(app, tab)
    try:
        assert tab._current_puzzle is not None
        assert tab._current_puzzle["category"] == "find_lethal"

        assert tab._scene_widget.isVisible(), (
            "PuzzleSceneWidget must still render for a board-having puzzle"
        )
        card_labels = [
            lbl.text() for lbl in tab._scene_widget.findChildren(QLabel)
        ]
        assert any("Grizzly Bears" in t for t in card_labels), (
            "battlefield creature did not render inside PuzzleSceneWidget"
        )
    finally:
        tab.cleanup()
        win.close()


def test_is_boardless_pure_function():
    """Unit-level check on the payload classifier itself (no Qt needed)."""
    from analysis.puzzles.scene_builder import Scene, PlayerState, CardInZone
    from gui.widgets.puzzle_scene import is_boardless

    empty = Scene(
        arena_match_id="x", game_num=0, turn_num=1, play_or_draw="draw",
        you=PlayerState(name="You", library_count=40),
        opp=PlayerState(name="Opp"),
    )
    assert is_boardless(empty) is True

    with_hand = Scene(
        arena_match_id="x", game_num=0, turn_num=1, play_or_draw="draw",
        you=PlayerState(name="You", hand=[CardInZone(name="Bolt")]),
        opp=PlayerState(name="Opp"),
    )
    assert is_boardless(with_hand) is False

    with_opp_board = Scene(
        arena_match_id="x", game_num=0, turn_num=1, play_or_draw="draw",
        you=PlayerState(name="You"),
        opp=PlayerState(
            name="Opp",
            battlefield_creatures=[CardInZone(name="Tarmogoyf")],
        ),
    )
    assert is_boardless(with_opp_board) is False
