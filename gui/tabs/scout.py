"""
Tab -- Scout (Tournament Prep sub-tab).

Pre-event scout intel. Given a set of target archetypes (default:
Tokyo Prowess's hardest matchups), surface every top-8 finisher
playing those decks in the last N days, group by pilot to find
repeat offenders, and link out to their decklist URLs and known
Twitter handles.

No live Twitter fetch -- handles come from data/player_handles.json
(confirmed players + candidates scraped from guides).
"""

from __future__ import annotations
import webbrowser

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QListWidget, QListWidgetItem, QSplitter, QMenu, QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QAction

import gui.theme as theme
from analysis.scout import (
    get_priority_finishers, get_pilot_counts, get_pilot_history,
)
from gui.state import UIState
from gui.state_keys import SCOUT_DAYS, SCOUT_FORMAT, SCOUT_TOP, SCOUT_TARGET_ARCHETYPES


# Tokyo Prowess priority opponents (per Nick's SB notes + matchup matrix)
_DEFAULT_TARGETS = [
    "Selesnya Landfall", "Mono Green Landfall",
    "Spellementals", "Azorius Control",
    "Boros Convoke", "Golgari Midrange",
    "Izzet Lessons", "Dimir Aggro",
]


class ScoutTab(QWidget):
    """Top-cut pilots playing target archetypes, with handle resolution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hydrated_state = False
        self._finishers = []
        self._build_ui()
        self._run_query()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                theme.SPACE_MD, theme.SPACE_SM)
        root.setSpacing(8)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["Standard", "Pioneer", "Modern", "Legacy", "Pauper"])
        self._fmt.currentTextChanged.connect(
            lambda txt: UIState.instance().set(SCOUT_FORMAT, txt)
        )
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("  Last"))
        self._days = QSpinBox()
        self._days.setRange(7, 365)
        self._days.setValue(30)
        self._days.setSuffix(" days")
        self._days.valueChanged.connect(
            lambda v: UIState.instance().set(SCOUT_DAYS, int(v))
        )
        ctrl.addWidget(self._days)

        ctrl.addWidget(QLabel("  Top:"))
        self._top = QSpinBox()
        self._top.setRange(1, 32)
        self._top.setValue(8)
        self._top.setPrefix("≤ ")
        self._top.valueChanged.connect(
            lambda v: UIState.instance().set(SCOUT_TOP, int(v))
        )
        ctrl.addWidget(self._top)

        self._run_btn = QPushButton("Run Scout")
        self._run_btn.setStyleSheet(theme.btn_primary())
        self._run_btn.clicked.connect(self._run_query)
        ctrl.addWidget(self._run_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # Splitter: targets list | results
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT: target archetypes (multi-select)
        target_box = QGroupBox("Target archetypes")
        tb_layout = QVBoxLayout(target_box)
        tb_layout.setContentsMargins(8, 14, 8, 8)
        self._targets = QListWidget()
        self._targets.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for arch in _DEFAULT_TARGETS:
            self._targets.addItem(QListWidgetItem(arch))
        self._targets.selectAll()
        self._targets.itemSelectionChanged.connect(self._persist_scout_targets)
        tb_layout.addWidget(self._targets)
        hint = QLabel("Ctrl-click to toggle. Defaults to Tokyo Prowess priority matchups.")
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        hint.setWordWrap(True)
        tb_layout.addWidget(hint)
        splitter.addWidget(target_box)

        # RIGHT: results (pilot summary on top, finisher table below)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet("font-size: 12px;")
        rl.addWidget(self._summary_lbl)

        self._pilot_tbl = QTableWidget(0, 5)
        self._pilot_tbl.setHorizontalHeaderLabels([
            "Pilot", "Top-cuts", "Best", "Archetypes", "Handle"
        ])
        self._pilot_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pilot_tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pilot_tbl.verticalHeader().setVisible(False)
        hh = self._pilot_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._pilot_tbl.setMaximumHeight(180)
        self._pilot_tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pilot_tbl.customContextMenuRequested.connect(self._on_pilot_menu)
        rl.addWidget(QLabel("<b>Repeat offenders (most top-cuts in window)</b>"))
        rl.addWidget(self._pilot_tbl)

        rl.addWidget(QLabel("<b>All finishes</b>"))
        self._fin_tbl = QTableWidget(0, 7)
        self._fin_tbl.setHorizontalHeaderLabels([
            "Pilot", "Archetype", "Top", "Event", "Date", "Source", "Handle"
        ])
        self._fin_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._fin_tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._fin_tbl.verticalHeader().setVisible(False)
        fhh = self._fin_tbl.horizontalHeader()
        fhh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        fhh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        fhh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._fin_tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._fin_tbl.customContextMenuRequested.connect(self._on_fin_menu)
        self._fin_tbl.doubleClicked.connect(self._on_fin_double_click)
        rl.addWidget(self._fin_tbl, 1)

        splitter.addWidget(right)
        splitter.setSizes([220, 700])
        root.addWidget(splitter, 1)

    def _selected_targets(self) -> list:
        return [self._targets.item(i).text()
                for i in range(self._targets.count())
                if self._targets.item(i).isSelected()]

    def _run_query(self):
        targets = self._selected_targets()
        if not targets:
            self._summary_lbl.setText(
                f"<span style='color:{theme.WARN};'>"
                "Select at least one target archetype.</span>"
            )
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = get_priority_finishers(
                targets,
                days=self._days.value(),
                format_name=self._fmt.currentText().lower(),
                placement_cap=self._top.value(),
                limit=300,
            )
        except Exception as exc:
            # Show the failure in the tab instead of crashing the whole GUI
            self._summary_lbl.setText(
                f"<span style='color:{theme.WARN};'>"
                f"Scout query failed: {exc}</span>"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._finishers = rows
        self._render(rows)

    def _render(self, rows: list):
        targets = self._selected_targets()
        days = self._days.value()
        pilots = get_pilot_counts(rows)
        n_finishes = len(rows)
        n_pilots = len(pilots)
        n_known = sum(1 for v in pilots if v.get("handle"))

        self._summary_lbl.setText(
            f"<b>{n_finishes}</b> top-{self._top.value()} finishes "
            f"across <b>{n_pilots}</b> distinct pilots in last {days} days "
            f"<span style='color:{theme.TEXT_DIM};'>"
            f"({n_known} with known handles, {len(targets)} archetypes selected)"
            "</span>"
        )

        # Pilot summary
        self._pilot_tbl.setRowCount(len(pilots))
        for ri, v in enumerate(pilots):
            self._pilot_tbl.setItem(ri, 0, QTableWidgetItem(v["player"]))
            ct = QTableWidgetItem(str(v["count"]))
            ct.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if v["count"] >= 3:
                ct.setForeground(QColor(theme.OK))
                f = QFont(); f.setBold(True); ct.setFont(f)
            self._pilot_tbl.setItem(ri, 1, ct)
            best = QTableWidgetItem(f"#{v['best']}")
            best.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pilot_tbl.setItem(ri, 2, best)
            self._pilot_tbl.setItem(ri, 3,
                QTableWidgetItem(", ".join(v["archetypes"])))
            h = v.get("handle")
            h_item = QTableWidgetItem(f"@{h}" if h else "")
            if h:
                h_item.setForeground(QColor(theme.ACCENT))
            self._pilot_tbl.setItem(ri, 4, h_item)

        # Finisher table
        self._fin_tbl.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            self._fin_tbl.setItem(ri, 0, QTableWidgetItem(r["player"]))
            self._fin_tbl.setItem(ri, 1, QTableWidgetItem(r["archetype"]))
            p_item = QTableWidgetItem(f"#{r['placement']}")
            p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r["placement"] == 1:
                p_item.setForeground(QColor(theme.OK))
                f = QFont(); f.setBold(True); p_item.setFont(f)
            self._fin_tbl.setItem(ri, 2, p_item)
            self._fin_tbl.setItem(ri, 3, QTableWidgetItem(r["event_name"]))
            self._fin_tbl.setItem(ri, 4, QTableWidgetItem(r["date"]))
            self._fin_tbl.setItem(ri, 5, QTableWidgetItem(r["source"]))
            h = r.get("handle")
            h_item = QTableWidgetItem(f"@{h}" if h else "")
            if h:
                h_item.setForeground(QColor(theme.ACCENT))
            self._fin_tbl.setItem(ri, 6, h_item)

    def _on_pilot_menu(self, pos):
        idx = self._pilot_tbl.indexAt(pos)
        if not idx.isValid():
            return
        ri = idx.row()
        player = self._pilot_tbl.item(ri, 0).text()
        handle_cell = self._pilot_tbl.item(ri, 4).text().lstrip("@")
        menu = QMenu(self)
        a1 = QAction(f"Show all finishes for {player}", menu)
        a1.triggered.connect(lambda: self._show_pilot_history(player))
        menu.addAction(a1)
        if handle_cell:
            a2 = QAction(f"Open @{handle_cell} on x.com", menu)
            a2.triggered.connect(
                lambda: webbrowser.open(f"https://x.com/{handle_cell}")
            )
            menu.addAction(a2)
        a3 = QAction("Copy player name", menu)
        a3.triggered.connect(
            lambda: QApplication.clipboard().setText(player)
        )
        menu.addAction(a3)
        menu.exec(self._pilot_tbl.viewport().mapToGlobal(pos))

    def _on_fin_menu(self, pos):
        idx = self._fin_tbl.indexAt(pos)
        if not idx.isValid():
            return
        ri = idx.row()
        if ri >= len(self._finishers):
            return
        row = self._finishers[ri]
        menu = QMenu(self)
        if row.get("url"):
            a1 = QAction("Open decklist URL", menu)
            a1.triggered.connect(lambda: webbrowser.open(row["url"]))
            menu.addAction(a1)
        if row.get("handle"):
            h = row["handle"]
            a2 = QAction(f"Open @{h} on x.com", menu)
            a2.triggered.connect(
                lambda: webbrowser.open(f"https://x.com/{h}")
            )
            menu.addAction(a2)
        a3 = QAction("Copy player name", menu)
        a3.triggered.connect(
            lambda: QApplication.clipboard().setText(row["player"])
        )
        menu.addAction(a3)
        menu.exec(self._fin_tbl.viewport().mapToGlobal(pos))

    def _on_fin_double_click(self, idx):
        ri = idx.row()
        if 0 <= ri < len(self._finishers):
            url = self._finishers[ri].get("url")
            if url:
                webbrowser.open(url)

    def _show_pilot_history(self, player_name: str):
        from PyQt6.QtWidgets import QDialog
        history = get_pilot_history(player_name,
                                     format_name=self._fmt.currentText().lower(),
                                     days=365)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Pilot history -- {player_name}")
        dlg.resize(640, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            f"<b>{player_name}</b>  ·  {len(history)} finishes in last 365 days "
            f"({self._fmt.currentText()})"
        ))
        tbl = QTableWidget(len(history), 6)
        tbl.setHorizontalHeaderLabels([
            "Archetype", "Place", "Event", "Date", "Source", "URL"
        ])
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        thh = tbl.horizontalHeader()
        thh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        thh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for ri, h in enumerate(history):
            tbl.setItem(ri, 0, QTableWidgetItem(h["archetype"]))
            p_item = QTableWidgetItem(f"#{h['placement']}")
            p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 1, p_item)
            tbl.setItem(ri, 2, QTableWidgetItem(h["event_name"]))
            tbl.setItem(ri, 3, QTableWidgetItem(h["date"]))
            tbl.setItem(ri, 4, QTableWidgetItem(h["source"]))
            tbl.setItem(ri, 5, QTableWidgetItem(h.get("url") or ""))
        tbl.doubleClicked.connect(
            lambda idx: history[idx.row()].get("url")
            and webbrowser.open(history[idx.row()]["url"])
        )
        v.addWidget(tbl)
        dlg.exec()

    # ------------------------------------------------------------------
    # Sticky state
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        self._hydrate_from_state()
        self._hydrated_state = True

    def _hydrate_from_state(self) -> None:
        state = UIState.instance()

        # Days window (QSpinBox) — actual attr: self._days
        days = state.get(SCOUT_DAYS)
        if days is not None and hasattr(self, "_days"):
            self._days.blockSignals(True)
            self._days.setValue(int(days))
            self._days.blockSignals(False)

        # Format (QComboBox) — actual attr: self._fmt
        fmt = state.get(SCOUT_FORMAT)
        if fmt and hasattr(self, "_fmt"):
            self._fmt.blockSignals(True)
            idx = self._fmt.findText(fmt)
            if idx >= 0:
                self._fmt.setCurrentIndex(idx)
            self._fmt.blockSignals(False)

        # Top placement cap (QSpinBox) — actual attr: self._top
        top = state.get(SCOUT_TOP)
        if top is not None and hasattr(self, "_top"):
            self._top.blockSignals(True)
            self._top.setValue(int(top))
            self._top.blockSignals(False)

        # Target archetypes (QListWidget, MultiSelection — NOT checkable)
        # NOTE: plan guessed checkState; this widget uses isSelected() instead.
        targets = state.get(SCOUT_TARGET_ARCHETYPES, [])
        if targets and hasattr(self, "_targets"):
            self._targets.blockSignals(True)
            for i in range(self._targets.count()):
                item = self._targets.item(i)
                item.setSelected(item.text() in targets)
            self._targets.blockSignals(False)

    def _persist_scout_targets(self) -> None:
        """Persist the selected target archetypes to UIState."""
        if not hasattr(self, "_targets"):
            return
        selected = [
            self._targets.item(i).text()
            for i in range(self._targets.count())
            if self._targets.item(i).isSelected()
        ]
        UIState.instance().set(SCOUT_TARGET_ARCHETYPES, selected)

    def reload(self):
        self._run_query()
