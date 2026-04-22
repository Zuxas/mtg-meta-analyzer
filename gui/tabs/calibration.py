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
    QProgressBar, QApplication, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor

import gui.theme as theme
from gui.tabs.simulate import (
    _ARCHETYPES as _SIM_ARCHETYPES,
    _MTG_SIM_PATH, _check_mtg_sim_available, _format_of,
)

# Sort by (format, name) so the matrix forms visible per-format blocks
# instead of interleaving Modern and Standard archetypes alphabetically.
_FMT_ORDER = {"modern": 0, "standard": 1, "pioneer": 2, "legacy": 3, "pauper": 4}
_ARCHETYPES = sorted(_SIM_ARCHETYPES,
                     key=lambda r: (_FMT_ORDER.get(_format_of(r[0]), 99), r[0]))


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
    """Return (real_a_pct, sample_size) or (None, 0) if unavailable.

    Derives format from the labels — calibration pairs are always
    same-format (cross-format pairs are filtered out in the worker).
    """
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
        real = get_real_matchup_winrates(_format_of(a_label), min_matches=5)

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
    """Runs the sim sweep. Mode: 'full' = upper triangle; 'row' = one row only."""
    progress = pyqtSignal(int, int, str)   # current, total, label
    cell_ready = pyqtSignal(int, int, dict) # row, col, {sim_pct, real_pct, sample_size}
    done = pyqtSignal(float)               # total elapsed seconds
    error = pyqtSignal(str)

    def __init__(self, archetypes: list, n_games: int,
                 row_only: int = None, parent=None):
        """
        archetypes  : list of _ARCHETYPES tuples
        n_games     : games per pair
        row_only    : if set, only re-run matchups for that archetype index
                       (row i vs every other archetype). Full matrix if None.
        """
        super().__init__(parent)
        self._archetypes = archetypes
        self._n_games = n_games
        self._row_only = row_only
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
            fmts = [_format_of(a[0]) for a in self._archetypes]
            if self._row_only is not None:
                pairs = [(self._row_only, j) for j in range(n)
                         if j != self._row_only
                         and fmts[j] == fmts[self._row_only]]
            else:
                pairs = [(i, j) for i in range(n) for j in range(i + 1, n)
                         if fmts[i] == fmts[j]]
            total_pairs = len(pairs)
            current = 0
            for (i, j) in pairs:
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
                # Mirror cell (B vs A) — inverse of sim, inverse of real
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

    def __init__(self, on_cell_activate=None):
        """
        on_cell_activate: optional callable(a_label: str, b_label: str).
        Called when the user double-clicks a cell — lets the main window
        wire this to 'jump to SIMULATE tab with these archetypes loaded'.
        """
        super().__init__()
        self._worker = None
        self._on_cell_activate = on_cell_activate
        # Active archetype list — filtered by format dropdown. Starts empty;
        # _build populates it before the table gets its first layout.
        self._active = []
        self._build()

    def _formats_in_registry(self) -> list:
        """Return formats actually present in _ARCHETYPES, preserving _FMT_ORDER."""
        seen = []
        for r in _ARCHETYPES:
            f = _format_of(r[0])
            if f not in seen:
                seen.append(f)
        return seen

    def _filtered_archetypes(self, fmt: str) -> list:
        """Subset of _ARCHETYPES matching the given format."""
        return [r for r in _ARCHETYPES if _format_of(r[0]) == fmt]

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG)
        layout.setSpacing(theme.SPACE_MD)

        hdr = QLabel("Calibration Matrix")
        hdr.setStyleSheet(theme.h1_style())
        layout.addWidget(hdr)

        desc = QLabel(
            "Runs sim matchups for every archetype pair and compares the predicted "
            "win rate to real-match data from the scraped DB."
        )
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        legend = QLabel(
            "<b>How to read:</b> each cell is ROW's win rate against COLUMN.  "
            "Top line = <b>sim% / real%</b>.  Bottom line = <b>delta</b> (sim minus real). "
            "Pick a format above — the matrix shows only that format's archetypes. "
            "&nbsp;&nbsp; "
            "<span style='background:#2e7846;color:white;padding:2px 6px'>green</span> "
            "|delta| &lt; 3 &nbsp; "
            "<span style='background:#9b8232;color:white;padding:2px 6px'>amber</span> "
            "&lt; 7 &nbsp; "
            "<span style='background:#963737;color:white;padding:2px 6px'>red</span> "
            "&ge; 7 &nbsp; "
            "<span style='background:#1f2133;color:#7a8194;padding:2px 6px'>dim</span> "
            "no real data"
        )
        legend.setStyleSheet(f"color: {theme.TEXT}; font-size: 11px;")
        legend.setWordWrap(True)
        layout.addWidget(legend)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        for f in self._formats_in_registry():
            self._fmt.addItem(f.capitalize(), userData=f)
        self._fmt.setFixedWidth(120)
        self._fmt.currentIndexChanged.connect(self._on_format_change)
        ctrl.addWidget(self._fmt)
        ctrl.addSpacing(12)

        ctrl.addWidget(QLabel("Games per pair:"))
        self._n_games = QSpinBox()
        self._n_games.setRange(50, 2000)
        self._n_games.setSingleStep(50)
        self._n_games.setValue(150)
        ctrl.addWidget(self._n_games)
        ctrl.addStretch(1)
        from gui.icons_util import btn_icon
        self._copy_btn = QPushButton(btn_icon("copy"), "Copy as TSV")
        self._copy_btn.setToolTip(
            "Copy the full matrix to the clipboard as tab-separated values "
            "(paste into Excel / Google Sheets)."
        )
        self._copy_btn.clicked.connect(self._on_copy_tsv)
        ctrl.addWidget(self._copy_btn)
        self._rerun_row_btn = QPushButton(btn_icon("refresh"), "Re-run selected row")
        self._rerun_row_btn.setToolTip(
            "Re-run calibration for just the currently-selected archetype's row. "
            "Useful after tuning an APL — 10x faster than a full matrix re-run."
        )
        self._rerun_row_btn.clicked.connect(self._on_rerun_row)
        ctrl.addWidget(self._rerun_row_btn)
        self._run_btn = QPushButton(btn_icon("run"), "Run full calibration")
        self._run_btn.clicked.connect(self._on_run)
        ctrl.addWidget(self._run_btn)
        layout.addLayout(ctrl)

        from gui.widgets.status_row import StatusRow
        self._status_row = StatusRow()
        self._status_row.done("Idle.")
        self._status = self._status_row.label()        # back-compat alias
        self._progress = self._status_row.progress()   # back-compat alias
        layout.addWidget(self._status_row)

        self._table = QTableWidget()
        self._init_table()
        self._table.cellDoubleClicked.connect(self._on_cell_double_click)
        layout.addWidget(self._table, 1)

        hint = QLabel(
            "Double-click any cell to open that matchup in the SIMULATE tab."
        )
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(hint)

    def _init_table(self):
        # Initialize self._active from the current dropdown, then build the
        # matrix for just that format's archetypes.
        if hasattr(self, "_fmt"):
            cur_fmt = self._fmt.currentData()
            if cur_fmt:
                self._active = self._filtered_archetypes(cur_fmt)
        if not self._active:
            # Fallback: first format in registry order
            fmts = self._formats_in_registry()
            if fmts:
                self._active = self._filtered_archetypes(fmts[0])

        n = len(self._active)
        self._table.setRowCount(n)
        self._table.setColumnCount(n)

        def _short(a_label):
            for suf in (" (Modern)", " (Standard)", " (Pioneer)", " (Legacy)"):
                if a_label.endswith(suf):
                    return a_label[:-len(suf)].strip()
            return a_label

        labels = [_short(a[0]) for a in self._active]
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

    def _start_worker(self, row_only: int = None):
        """Shared worker-kickoff for full matrix and single-row modes."""
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self._status.setText(msg.split("\n")[0])
            return

        self._run_btn.setEnabled(False)
        self._rerun_row_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        n = len(self._active)
        if row_only is not None:
            total_pairs = n - 1
            for j in range(n):
                if j != row_only:
                    self._table.setItem(row_only, j, QTableWidgetItem(""))
                    self._table.setItem(j, row_only, QTableWidgetItem(""))
        else:
            total_pairs = n * (n - 1) // 2
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    self._table.setItem(i, j, QTableWidgetItem(""))
        self._progress.setMaximum(total_pairs)

        self._worker = CalibrationWorker(self._active, self._n_games.value(),
                                         row_only=row_only)
        self._worker.progress.connect(self._on_progress)
        self._worker.cell_ready.connect(self._on_cell)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_format_change(self, _idx):
        """Swap the matrix to the newly-selected format's archetypes."""
        # If a worker is mid-run, stop it — it'd emit cells into a table
        # that's about to be repopulated for a different format.
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(500)
            self._run_btn.setEnabled(True)
            self._rerun_row_btn.setEnabled(True)
            self._progress.setVisible(False)
        self._init_table()
        fmt = self._fmt.currentData() or ""
        self._status.setText(
            f"Switched to {fmt.capitalize()} — {len(self._active)} archetypes. "
            f"Click 'Run full calibration' to populate the matrix."
        )

    def _on_run(self):
        self._start_worker(row_only=None)

    def _on_rerun_row(self):
        row = self._table.currentRow()
        if row < 0:
            self._status.setText(
                "Select a cell first — the row-re-run uses the selected row's archetype."
            )
            return
        self._status.setText(
            f"Re-running row: {self._active[row][0]} vs all opponents ..."
        )
        self._start_worker(row_only=row)

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
        self._rerun_row_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(f"Calibration complete in {elapsed:.1f}s.")

    def _on_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._rerun_row_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status.setText(f"Error: {msg.splitlines()[0]}")

    def _on_copy_tsv(self):
        """Serialize the matrix as TSV (tabs + newlines) to the clipboard."""
        n_rows = self._table.rowCount()
        n_cols = self._table.columnCount()
        if n_rows == 0 or n_cols == 0:
            return

        lines = []
        # Header row: blank corner cell + column labels
        headers = [""] + [self._table.horizontalHeaderItem(c).text()
                          if self._table.horizontalHeaderItem(c) else f"col{c}"
                          for c in range(n_cols)]
        lines.append("\t".join(headers))
        for r in range(n_rows):
            row_label = (self._table.verticalHeaderItem(r).text()
                         if self._table.verticalHeaderItem(r) else f"row{r}")
            row_cells = [row_label]
            for c in range(n_cols):
                item = self._table.item(r, c)
                txt = item.text() if item else ""
                # Flatten newlines inside cells (sim/real/delta lives on 2 lines)
                txt = txt.replace("\n", " | ")
                row_cells.append(txt)
            lines.append("\t".join(row_cells))
        QApplication.clipboard().setText("\n".join(lines))

        prev = self._status.text()
        self._status.setText(f"Copied {n_rows}x{n_cols} matrix to clipboard as TSV.")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self._status.setText(prev))

    def _on_cell_double_click(self, row: int, col: int):
        if row == col:
            return  # diagonal — no meaningful matchup
        if self._on_cell_activate is None:
            return
        if row < 0 or col < 0 or row >= len(self._active) or col >= len(self._active):
            return
        a_label = self._active[row][0]
        b_label = self._active[col][0]
        try:
            self._on_cell_activate(a_label, b_label)
        except Exception:
            # Best-effort jump; don't break the calibration tab if the
            # hook throws.
            pass

    def cleanup(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(2000)
