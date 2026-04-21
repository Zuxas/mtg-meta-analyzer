"""
Tab - Calibration

Runs sim matchups across every archetype pair and compares the predicted
win rate against real-match data scraped from melee.gg. Renders a
color-coded matrix so you can spot at a glance which sim predictions
are aligned with reality and which are off.

Uses the same mtg-sim discovery logic as the SIMULATE tab (MTG_SIM_PATH
env var, then ../mtg-sim sibling clone).
"""
import os
import sys
import importlib
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor

import gui.theme as theme
from gui.tabs.simulate import _ARCHETYPES, _MTG_SIM_PATH, _check_mtg_sim_available


def _sim_matchup_headless(a_meta: tuple, b_meta: tuple, n_games: int) -> float:
    """Run a single sim matchup, return A's win rate (0-100).

    a_meta / b_meta are tuples from _ARCHETYPES. No result-dict
    construction; just the win percent for the matrix cell.
    """
    ok, msg = _check_mtg_sim_available()
    if not ok:
        raise RuntimeError(msg)
    from data.deck import load_deck_from_file
    from engine.match_engine import run_match_set

    _lab_a, _g_mod_a, _g_cls_a, m_mod_a, m_cls_a, deck_a = a_meta
    _lab_b, _g_mod_b, _g_cls_b, m_mod_b, m_cls_b, deck_b = b_meta

    apl_a = getattr(importlib.import_module(m_mod_a), m_cls_a)()
    apl_b = getattr(importlib.import_module(m_mod_b), m_cls_b)()

    a_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, deck_a))
    b_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, deck_b))

    results = run_match_set(apl_a, a_deck, apl_b, b_deck,
                            n=n_games, mix_play_draw=True, seed=42)
    return results.win_pct_a()


def _lookup_real_pct(a_label: str, b_label: str) -> tuple:
    """Return (real_a_pct, sample_size) or (None, 0) if unavailable."""
    try:
        from analysis.win_rates import get_real_matchup_winrates
        from analysis.archetypes import normalize as norm_arch

        def _strip_fmt(s):
            for suf in (" (Modern)", " (Standard)", " (Pioneer)", " (Legacy)"):
                if s.endswith(suf):
                    return s[:-len(suf)].strip()
            return s.strip()

        a_arch = norm_arch(_strip_fmt(a_label))
        b_arch = norm_arch(_strip_fmt(b_label))
        real = get_real_matchup_winrates("modern", min_matches=5)

        if a_arch in real and b_arch in real[a_arch]:
            entry = real[a_arch][b_arch]
            return round(entry["win_rate"] * 100, 1), entry["total"]
        if b_arch in real and a_arch in real[b_arch]:
            entry = real[b_arch][a_arch]
            return round((1.0 - entry["win_rate"]) * 100, 1), entry["total"]
    except Exception:
        pass
    return (None, 0)


class CalibrationWorker(QThread):
    """Runs the full sim sweep, emitting per-pair progress as it goes."""
    progress = pyqtSignal(int, int, str)   # current, total, label
    cell_ready = pyqtSignal(int, int, dict) # row, col, {sim_pct, real_pct, sample_size}
    done = pyqtSignal(float)               # total elapsed seconds
    error = pyqtSignal(str)

    def __init__(self, archetypes: list, n_games: int, parent=None):
        super().__init__(parent)
        self._archetypes = archetypes
        self._n_games = n_games
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self.error.emit(msg)
            return

        try:
            t0 = time.perf_counter()
            n = len(self._archetypes)
            # Iterate upper triangle (i < j) + diagonal skipped
            total_pairs = n * (n - 1) // 2
            current = 0
            for i in range(n):
                for j in range(i + 1, n):
                    if self._stop:
                        return
                    current += 1
                    a_meta = self._archetypes[i]
                    b_meta = self._archetypes[j]
                    self.progress.emit(current, total_pairs,
                                       f"{a_meta[0]} vs {b_meta[0]}")

                    sim_pct = _sim_matchup_headless(a_meta, b_meta, self._n_games)
                    real_pct, sample = _lookup_real_pct(a_meta[0], b_meta[0])

                    payload = {"sim_pct": sim_pct,
                               "real_pct": real_pct,
                               "sample_size": sample}
                    self.cell_ready.emit(i, j, payload)
                    # Mirror cell (B vs A)
                    mirror_sim = round(100.0 - sim_pct, 1)
                    mirror_real = (round(100.0 - real_pct, 1)
                                   if real_pct is not None else None)
                    self.cell_ready.emit(j, i, {"sim_pct": mirror_sim,
                                                "real_pct": mirror_real,
                                                "sample_size": sample})
            self.done.emit(time.perf_counter() - t0)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}")


class CalibrationTab(QWidget):
    """Whole-matrix sim-vs-real-match calibration view."""

    def __init__(self):
        super().__init__()
        self._worker = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hdr = QLabel("<b>Calibration Matrix</b>")
        hdr.setStyleSheet(f"color: {theme.TEXT}; font-size: 18px;")
        layout.addWidget(hdr)

        desc = QLabel(
            "Runs sim matchups for every archetype pair and compares the predicted "
            "win rate to real-match data. Cells show the delta (sim minus real). "
            "Green = sim aligns with reality; red = sim is off by 7+ points."
        )
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Games per pair:"))
        self._n_games = QSpinBox()
        self._n_games.setRange(50, 2000)
        self._n_games.setSingleStep(50)
        self._n_games.setValue(150)
        ctrl.addWidget(self._n_games)
        ctrl.addStretch(1)
        self._run_btn = QPushButton("Run full calibration")
        self._run_btn.clicked.connect(self._on_run)
        ctrl.addWidget(self._run_btn)
        layout.addLayout(ctrl)

        self._status = QLabel("Idle.")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(4)
        layout.addWidget(self._progress)

        self._table = QTableWidget()
        self._init_table()
        layout.addWidget(self._table, 1)

    def _init_table(self):
        n = len(_ARCHETYPES)
        self._table.setRowCount(n)
        self._table.setColumnCount(n)
        labels = [a[0].replace(" (Modern)", "") for a in _ARCHETYPES]
        self._table.setHorizontalHeaderLabels(labels)
        self._table.setVerticalHeaderLabels(labels)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"gridline-color: {theme.BORDER}; font-size: 11px;"
        )

        # Diagonal: blank with subtle shade
        for i in range(n):
            item = QTableWidgetItem("-")
            item.setBackground(QColor(theme.SURFACE))
            item.setForeground(QColor(theme.TEXT_OFF))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(i, i, item)

    def _on_run(self):
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self._status.setText(msg.split("\n")[0])
            return

        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        n = len(_ARCHETYPES)
        total_pairs = n * (n - 1) // 2
        self._progress.setMaximum(total_pairs)

        # Clear any prior cell data
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                self._table.setItem(i, j, QTableWidgetItem(""))

        self._worker = CalibrationWorker(_ARCHETYPES, self._n_games.value())
        self._worker.progress.connect(self._on_progress)
        self._worker.cell_ready.connect(self._on_cell)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_progress(self, current: int, total: int, label: str):
        self._progress.setValue(current)
        self._status.setText(f"({current}/{total}) {label} ...")

    def _on_cell(self, row: int, col: int, data: dict):
        sim = data["sim_pct"]
        real = data["real_pct"]
        sample = data["sample_size"]

        if real is None:
            # No real data — show sim only
            text = f"{sim:.0f}%\n(no real)"
            bg = QColor(theme.INPUT)
            tooltip = (f"Sim: {sim:.1f}%\nReal: no data "
                       f"({sample} matches on record)")
        else:
            delta = round(sim - real, 1)
            text = f"{sim:.0f}% / {real:.0f}%\n{'+' if delta >= 0 else ''}{delta}"
            bg = self._color_for_delta(delta)
            tooltip = (f"Sim: {sim:.1f}%\nReal: {real:.1f}% (n={sample})\n"
                       f"Delta: {delta:+.1f} pts")

        item = QTableWidgetItem(text)
        item.setBackground(bg)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(tooltip)
        self._table.setItem(row, col, item)

    @staticmethod
    def _color_for_delta(delta: float) -> QColor:
        """Green when sim matches reality, red when way off."""
        abs_d = abs(delta)
        if abs_d < 3:
            return QColor(46, 120, 70)    # green — aligned
        if abs_d < 7:
            return QColor(155, 130, 50)   # amber — close
        return QColor(150, 55, 55)        # red — off

    def _on_done(self, elapsed: float):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(f"Calibration complete in {elapsed:.1f}s.")

    def _on_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(f"Error: {msg.splitlines()[0]}")

    def cleanup(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(2000)
