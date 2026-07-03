"""PUZZLES tab — Solve | Inbox | Author sub-modes (Phase 2)."""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QSplitter, QFrame, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
)

from analysis.puzzles.scene_builder import Scene, PlayerState, build_scene
from db import puzzles as db_puzzles
from gui.widgets.puzzle_scene import PuzzleSceneWidget
from gui.widgets.puzzle_author_dialog import PuzzleAuthorDialog

import gui.theme as theme


_CATEGORY_OPTIONS = [
    ("All", ""),
    ("🎯 Find lethal", "find_lethal"),
    ("🛡 Stabilize", "stabilize"),
    ("⚡ Tempo / Race", "tempo"),
    ("🎲 Outs math", "drill_outs"),
]


class PuzzlesTab(QWidget):
    """Solo solve loop + Inbox candidate review. Author opens as a dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_puzzle: Optional[dict] = None
        self._reveal_t0_ms: Optional[int] = None
        self._build_ui()
        self._load_next_puzzle()
        self._refresh_inbox()

    # ── Construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self._sub_tabs = QTabWidget()
        self._sub_tabs.addTab(self._build_solve_panel(), "Solve")
        self._sub_tabs.addTab(self._build_inbox_panel(), "Inbox")
        outer.addWidget(self._sub_tabs, 1)

    def _build_solve_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

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
        v.addLayout(top)

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

        self._verdict_chip = QLabel("")
        self._verdict_chip.setTextFormat(Qt.TextFormat.RichText)
        self._verdict_chip.setWordWrap(True)
        self._verdict_chip.hide()
        right_v.addWidget(self._verdict_chip)

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
        v.addWidget(splitter, 1)
        return panel

    def _build_inbox_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)

        # Toolbar: refresh + category filter
        top = QHBoxLayout()
        self._inbox_category_combo = QComboBox()
        for label, value in _CATEGORY_OPTIONS:
            self._inbox_category_combo.addItem(label, value)
        self._inbox_category_combo.currentIndexChanged.connect(self._refresh_inbox)
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self._inbox_category_combo)
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._refresh_inbox)
        top.addWidget(refresh_btn)
        top.addStretch(1)
        v.addLayout(top)

        # Table: id / category / score / match / game / turn / evidence
        self._inbox_table = QTableWidget(0, 7)
        self._inbox_table.setHorizontalHeaderLabels(
            ["id", "category", "score", "match", "game", "turn", "evidence"]
        )
        self._inbox_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self._inbox_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._inbox_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        v.addWidget(self._inbox_table, 1)

        # Action buttons
        btns = QHBoxLayout()
        promote_btn = QPushButton("📥 Promote → Author")
        promote_btn.clicked.connect(self._on_promote_selected)
        dismiss_btn = QPushButton("✗ Dismiss")
        dismiss_btn.clicked.connect(self._on_dismiss_selected)
        btns.addWidget(promote_btn)
        btns.addWidget(dismiss_btn)
        btns.addStretch(1)
        v.addLayout(btns)
        return panel

    # ── Solve mode data flow ───────────────────────────────────
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
                "Promote a candidate from the Inbox tab or run "
                "scripts/scan_for_puzzles.py to populate it.</i>"
            )
            self._answer_edit.clear(); self._answer_edit.setEnabled(False)
            self._reveal_btn.setEnabled(False)
            self._solution_lbl.hide()
            self._verdict_chip.hide()
            self._got_it_btn.hide(); self._missed_btn.hide()
            self._scene_widget.set_scene(_empty_scene())
            return
        puzzle = candidates[0]  # newest first (get_puzzles returns DESC by id)
        self._current_puzzle = puzzle
        self._render_puzzle(puzzle)

    def _render_puzzle(self, puzzle: dict) -> None:
        self._reveal_t0_ms = int(time.monotonic() * 1000)
        self._answer_edit.clear(); self._answer_edit.setEnabled(True)
        self._reveal_btn.setEnabled(True)
        self._solution_lbl.hide()
        self._verdict_chip.hide()
        self._got_it_btn.hide(); self._missed_btn.hide()
        cat_label = {
            "find_lethal": "🎯 Find lethal",
            "stabilize": "🛡 Stabilize",
            "tempo": "⚡ Tempo / Race",
            "drill_outs": "🎲 Outs math",
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

    def _render_verdict_chip(self, result: dict) -> None:
        """Show the auto-grader verdict as a colored chip below the
        author's solution. Self-grade buttons remain for user override."""
        requested = (self._current_puzzle or {}).get("grading_mode") or "self"
        colors = {
            "correct":     "#80c890",
            "partial":     "#d4a050",
            "incorrect":   "#d88060",
            "user_marked": "#808080",
        }
        color = colors.get(result.get("verdict"), "#808080")
        fallback_tag = ""
        if result.get("grader_used") != requested and requested != "self":
            fallback_tag = (
                f" <span style='color:#808080;font-size:9px;'>"
                f"(fallback from {requested})</span>"
            )
        self._verdict_chip.setText(
            f"<div style='border-left:3px solid {color};padding:4px 8px;"
            f"background:#1a1a22;color:#e6e6e6;font-size:11px;'>"
            f"<b style='color:{color};'>{result.get('verdict', '?').upper()}</b>"
            f"{fallback_tag}<br/>"
            f"<span style='color:#aaa;'>{result.get('explanation', '')}</span></div>"
        )
        self._verdict_chip.show()

    def _on_reveal(self) -> None:
        if self._current_puzzle is None:
            return
        self._solution_lbl.setText(
            f"<b>Author's solution:</b><br/>"
            + (self._current_puzzle["solution_text"]
               .replace("\n", "<br/>"))
        )
        self._solution_lbl.show()
        # Auto-grade if puzzle's grading_mode is keyword or llm
        from analysis.puzzles.graders import grade
        user_answer = self._answer_edit.toPlainText().strip()
        if user_answer:
            try:
                result = grade(self._current_puzzle, user_answer)
                self._render_verdict_chip(result)
            except BaseException:
                # Defensive: grading should never crash the reveal
                pass
        else:
            self._verdict_chip.hide()
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

    # ── Inbox mode ─────────────────────────────────────────────
    def _refresh_inbox(self) -> None:
        cat = self._inbox_category_combo.currentData() or None
        rows = db_puzzles.get_inbox(category=cat, top_n=200)
        self._inbox_table.setUpdatesEnabled(False)
        self._inbox_table.setSortingEnabled(False)
        self._inbox_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._inbox_table.setItem(r, 0, QTableWidgetItem(str(row["id"])))
            self._inbox_table.setItem(r, 1, QTableWidgetItem(row["category"]))
            self._inbox_table.setItem(r, 2, QTableWidgetItem(
                f"{row['heuristic_score']:.2f}"))
            self._inbox_table.setItem(r, 3, QTableWidgetItem(row["arena_match_id"]))
            self._inbox_table.setItem(r, 4, QTableWidgetItem(
                str(row["game_num"] or "")))
            self._inbox_table.setItem(r, 5, QTableWidgetItem(str(row["turn_num"])))
            self._inbox_table.setItem(r, 6, QTableWidgetItem(row.get("evidence") or ""))
        self._inbox_table.setSortingEnabled(True)
        self._inbox_table.setUpdatesEnabled(True)

    def _selected_inbox_row(self) -> Optional[dict]:
        sel = self._inbox_table.currentRow()
        if sel < 0:
            return None
        rows = db_puzzles.get_inbox(top_n=200)
        if sel >= len(rows):
            return None
        return rows[sel]

    def _on_promote_selected(self) -> None:
        row = self._selected_inbox_row()
        if row is None:
            QMessageBox.information(self, "No selection", "Pick a candidate row first.")
            return
        scene = build_scene(
            arena_match_id=row["arena_match_id"],
            game_num=int(row["game_num"] or 1),
            turn_num=int(row["turn_num"]),
        )
        if scene is None:
            QMessageBox.warning(
                self, "Scene unavailable",
                f"No cached replay for {row['arena_match_id']}. "
                "Run replay_fetcher or play the match again.",
            )
            return
        dlg = PuzzleAuthorDialog(
            scene=scene, inbox_id=row["id"],
            suggested_category=row["category"], parent=self,
        )
        if dlg.exec():
            self._refresh_inbox()
            self._load_next_puzzle()

    def _on_dismiss_selected(self) -> None:
        row = self._selected_inbox_row()
        if row is None:
            return
        db_puzzles.dismiss_inbox(row["id"])
        self._refresh_inbox()

    # Test helper
    def findChild_text_recursive(self) -> str:
        out = []
        for lbl in self.findChildren(QLabel):
            out.append(lbl.text())
        for te in self.findChildren(QTextEdit):
            out.append(te.placeholderText() or "")
            out.append(te.toPlainText() or "")
        return " ".join(out)

    def cleanup(self) -> None:
        pass


def _empty_scene() -> Scene:
    return Scene(
        arena_match_id="", game_num=0, turn_num=0, play_or_draw="play",
        you=PlayerState(name="You"), opp=PlayerState(name="Opp"),
        notes="",
    )
