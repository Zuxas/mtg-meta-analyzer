"""PuzzleAuthorDialog — form + scene preview for creating a new puzzle.

Reused by:
  - PUZZLES tab Inbox sub-mode: "promote candidate" flow (pass inbox_id)
  - Match History sub-tab right-click: "Create puzzle from this turn"
    (no inbox_id; pure manual authoring)

On save: writes via db.puzzles.save_puzzle, and if inbox_id was provided,
calls db.puzzles.promote_inbox to link the candidate row.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QTextEdit,
    QComboBox, QSpinBox, QPushButton, QLabel, QSplitter, QFrame,
)

from analysis.puzzles.scene_builder import Scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("Find lethal", "find_lethal"),
    ("Stabilize", "stabilize"),
    ("Tempo / Race", "tempo"),
]
_GRADING_OPTIONS = [
    ("Self-grade (reveal + Got it / Missed it)", "self"),
    ("Tagged keywords", "keyword"),
    ("LLM-graded (Claude API)", "llm"),
]


class PuzzleAuthorDialog(QDialog):
    """Author / edit one puzzle. Scene is locked at dialog-open time."""

    def __init__(
        self,
        scene: Scene,
        *,
        inbox_id: Optional[int] = None,
        suggested_category: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._scene = scene
        self._inbox_id = inbox_id
        self.setWindowTitle("New puzzle" if inbox_id is None
                            else f"Promote candidate (inbox #{inbox_id})")
        self.setMinimumSize(960, 640)
        self._build_ui()
        if suggested_category:
            self._set_category(suggested_category)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: scene preview (read-only PuzzleSceneWidget)
        self._scene_widget = PuzzleSceneWidget(self._scene)
        splitter.addWidget(self._scene_widget)

        # Right: form
        right = QFrame()
        form_layout = QVBoxLayout(right)
        form = QFormLayout()
        self._category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._category_combo.addItem(label, value)
        form.addRow("Category:", self._category_combo)

        self._difficulty_spin = QSpinBox()
        self._difficulty_spin.setRange(1, 5)
        self._difficulty_spin.setValue(3)
        form.addRow("Difficulty (1-5):", self._difficulty_spin)

        self._question_edit = QLineEdit()
        self._question_edit.setPlaceholderText("e.g. Find lethal — opp at 8")
        form.addRow("Question:", self._question_edit)

        self._solution_edit = QTextEdit()
        self._solution_edit.setPlaceholderText("Step-by-step...")
        self._solution_edit.setMinimumHeight(120)
        form.addRow("Solution:", self._solution_edit)

        self._keywords_edit = QLineEdit()
        self._keywords_edit.setPlaceholderText("comma,separated,tags")
        form.addRow("Keywords (optional):", self._keywords_edit)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText(
            "Hints, alternate lines, primer references..."
        )
        self._notes_edit.setMinimumHeight(60)
        form.addRow("Notes:", self._notes_edit)

        self._grading_combo = QComboBox()
        for label, value in _GRADING_OPTIONS:
            self._grading_combo.addItem(label, value)
        form.addRow("Grading mode:", self._grading_combo)

        form_layout.addLayout(form)
        form_layout.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save puzzle")
        save.clicked.connect(self._on_save)
        save.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; "
            f"color: {theme.BTN_FG}; font-weight: bold; padding: 6px 14px; "
            "border-radius: 4px; }}"
        )
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        form_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([640, 320])
        outer.addWidget(splitter, 1)

    def _set_category(self, value: str) -> None:
        for i in range(self._category_combo.count()):
            if self._category_combo.itemData(i) == value:
                self._category_combo.setCurrentIndex(i)
                break

    def _save_and_return_id(self) -> Optional[int]:
        """Persist the puzzle. Returns the new puzzle id, or None on cancel
        (currently never cancels mid-save, but kept for symmetry)."""
        keywords = [
            k.strip() for k in (self._keywords_edit.text() or "").split(",")
            if k.strip()
        ]
        pid = db_puzzles.save_puzzle(
            deck_id=None,
            arena_match_id=self._scene.arena_match_id or None,
            game_num=self._scene.game_num or None,
            turn_num=self._scene.turn_num or None,
            category=self._category_combo.currentData() or "stabilize",
            difficulty=self._difficulty_spin.value(),
            question=self._question_edit.text() or "(no question)",
            solution_text=self._solution_edit.toPlainText() or "(no solution)",
            solution_keywords=keywords,
            grading_mode=self._grading_combo.currentData() or "self",
            author="user",
            notes=self._notes_edit.toPlainText() or "",
            scene=self._scene.to_dict(),
        )
        if self._inbox_id is not None:
            db_puzzles.promote_inbox(self._inbox_id, puzzle_id=pid)
        return pid

    def _on_save(self) -> None:
        self._save_and_return_id()
        self.accept()
