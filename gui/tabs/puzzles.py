"""PUZZLES tab — Solve mode (Phase 1).

Loads one unsolved puzzle at a time, renders the scene, takes the user's
typed answer, reveals the author's solution on demand, and records the
self-grade verdict. Author and Inbox modes ship in Phase 2.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QSplitter, QFrame,
)

from analysis.puzzles.scene_builder import Scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("All", ""),
    ("🎯 Find lethal", "find_lethal"),
    ("🛡 Stabilize", "stabilize"),
    ("⚡ Tempo / Race", "tempo"),
]


class PuzzlesTab(QWidget):
    """Solo solve loop. Author / Inbox sub-modes deferred to Phase 2."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_puzzle: Optional[dict] = None
        self._reveal_t0_ms: Optional[int] = None
        self._build_ui()
        self._load_next_puzzle()

    # ── Construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Top bar — category filter + session stats
        top = QHBoxLayout()
        self._category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._category_combo.addItem(label, value)
        self._category_combo.currentIndexChanged.connect(self._on_category_changed)
        top.addWidget(QLabel("Category:"))
        top.addWidget(self._category_combo)
        top.addStretch(1)
        self._stats_lbl = QLabel("")
        top.addWidget(self._stats_lbl)
        outer.addLayout(top)

        # Split: scene on left, answer panel on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._scene_widget = PuzzleSceneWidget()
        splitter.addWidget(self._scene_widget)

        right = QFrame()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(8, 8, 8, 8)
        right_v.setSpacing(6)
        self._question_lbl = QLabel("")
        self._question_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._question_lbl.setWordWrap(True)
        right_v.addWidget(self._question_lbl)

        self._answer_edit = QTextEdit()
        self._answer_edit.setPlaceholderText("Step-by-step play...")
        right_v.addWidget(self._answer_edit, 1)

        btn_row = QHBoxLayout()
        self._reveal_btn = QPushButton("Reveal solution")
        self._reveal_btn.clicked.connect(self._on_reveal)
        btn_row.addWidget(self._reveal_btn)
        right_v.addLayout(btn_row)

        self._solution_lbl = QLabel("")
        self._solution_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._solution_lbl.setWordWrap(True)
        self._solution_lbl.setStyleSheet(
            f"QLabel {{ background: {theme.PANEL}; padding: 6px; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        self._solution_lbl.hide()
        right_v.addWidget(self._solution_lbl)

        verdict_row = QHBoxLayout()
        self._got_it_btn = QPushButton("✓ I had it")
        self._got_it_btn.clicked.connect(lambda: self._record_and_next("correct"))
        self._missed_btn = QPushButton("✗ Missed it")
        self._missed_btn.clicked.connect(lambda: self._record_and_next("incorrect"))
        for b in (self._got_it_btn, self._missed_btn):
            b.hide()
            verdict_row.addWidget(b)
        right_v.addLayout(verdict_row)

        splitter.addWidget(right)
        splitter.setSizes([720, 320])
        outer.addWidget(splitter, 1)

    # ── Data flow ──────────────────────────────────────────────
    def _on_category_changed(self, _idx: int) -> None:
        self._load_next_puzzle()

    def _load_next_puzzle(self) -> None:
        cat = self._category_combo.currentData() or None
        candidates = db_puzzles.get_puzzles(category=cat, unsolved_only=True)
        self._refresh_stats()
        if not candidates:
            self._current_puzzle = None
            self._question_lbl.setText(
                f"<i style='color:{theme.TEXT_DIM};'>Queue is empty. "
                "No puzzles yet — author one via the seeder script, "
                "or come back after Phase 2 ships the Inbox.</i>"
            )
            self._answer_edit.clear(); self._answer_edit.setEnabled(False)
            self._reveal_btn.setEnabled(False)
            self._solution_lbl.hide()
            self._got_it_btn.hide(); self._missed_btn.hide()
            self._scene_widget.set_scene(_empty_scene())
            return
        puzzle = candidates[-1]  # oldest first (queue style)
        self._current_puzzle = puzzle
        self._render_puzzle(puzzle)

    def _render_puzzle(self, puzzle: dict) -> None:
        self._reveal_t0_ms = int(time.monotonic() * 1000)
        self._answer_edit.clear(); self._answer_edit.setEnabled(True)
        self._reveal_btn.setEnabled(True)
        self._solution_lbl.hide()
        self._got_it_btn.hide(); self._missed_btn.hide()
        cat_label = {
            "find_lethal": "🎯 Find lethal",
            "stabilize": "🛡 Stabilize",
            "tempo": "⚡ Tempo / Race",
        }.get(puzzle["category"], puzzle["category"])
        stars = "★" * puzzle["difficulty"] + "☆" * (5 - puzzle["difficulty"])
        self._question_lbl.setText(
            f"<div style='color:{theme.ACCENT};font-size:11px;'>{cat_label} · {stars}</div>"
            f"<div style='font-size:14px;font-weight:bold;margin-top:4px;'>"
            f"{puzzle['question']}</div>"
            f"<div style='color:{theme.TEXT_DIM};font-size:11px;margin-top:6px;'>"
            f"{puzzle.get('notes', '') or ''}</div>"
        )
        scene = Scene.from_dict(puzzle["scene"])
        self._scene_widget.set_scene(scene)

    def _on_reveal(self) -> None:
        if self._current_puzzle is None:
            return
        self._solution_lbl.setText(
            f"<b>Author's solution:</b><br/>"
            + (self._current_puzzle["solution_text"]
               .replace("\n", "<br/>"))
        )
        self._solution_lbl.show()
        self._got_it_btn.show(); self._missed_btn.show()
        self._reveal_btn.setEnabled(False)

    def _record_and_next(self, verdict: str) -> None:
        if self._current_puzzle is None:
            return
        ms = None
        if self._reveal_t0_ms is not None:
            ms = int(time.monotonic() * 1000) - self._reveal_t0_ms
        db_puzzles.record_attempt(
            puzzle_id=self._current_puzzle["id"],
            user_answer=self._answer_edit.toPlainText(),
            verdict=verdict,
            grader_used="self",
            time_spent_ms=ms,
        )
        self._load_next_puzzle()

    def _refresh_stats(self) -> None:
        stats = db_puzzles.get_session_stats()
        wr_pct = stats["wr_overall"] * 100
        self._stats_lbl.setText(
            f"<span style='color:{theme.TEXT_DIM};'>Session:</span> "
            f"<b style='color:#80c890;'>{stats['n_solved']} ✓</b> · "
            f"<b style='color:#d88060;'>{stats['n_missed']} ✗</b> · "
            f"{wr_pct:.0f}%"
        )

    # Test helper — returns concatenated text of all visible labels
    def findChild_text_recursive(self) -> str:
        out = []
        for lbl in self.findChildren(QLabel):
            out.append(lbl.text())
        for te in self.findChildren(QTextEdit):
            out.append(te.placeholderText() or "")
            out.append(te.toPlainText() or "")
        return " ".join(out)

    def cleanup(self) -> None:
        """Stop running workers. Phase 1 has none."""
        pass


# ── Module-level helpers ────────────────────────────────────────

def _empty_scene() -> Scene:
    from analysis.puzzles.scene_builder import PlayerState
    return Scene(
        arena_match_id="", game_num=0, turn_num=0, play_or_draw="play",
        you=PlayerState(name="You"), opp=PlayerState(name="Opp"),
        notes="",
    )
