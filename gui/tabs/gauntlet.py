"""
Tab -- Gauntlet (Tournament Prep sub-tab, #9).

Builds a testing gauntlet from the current metagame (analysis/gauntlet.py):
pick a format, window and field size, then include / exclude archetypes and
override weights before saving the snapshot. The saved JSON is the export
mtg-sim and the harness read.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

import gui.theme as theme

_COLS = ["Test", "Archetype", "Share", "Weight", "Testing %", "Representative list", "Warnings"]
C_TEST, C_ARCH, C_SHARE, C_WEIGHT, C_PCT, C_LIST, C_WARN = range(len(_COLS))


class GauntletTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._g = None
        self._worker = None
        self._filling = False
        self._build_ui()

    # -- layout -------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM)
        root.setSpacing(theme.SPACE_SM)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["Modern", "Standard", "Pioneer", "Legacy", "Pauper"])
        ctrl.addWidget(self._fmt)
        ctrl.addWidget(QLabel("  Last"))
        self._days = QSpinBox()
        self._days.setRange(3, 365)
        self._days.setValue(14)
        self._days.setSuffix(" days")
        ctrl.addWidget(self._days)
        ctrl.addWidget(QLabel("  Field size:"))
        self._size = QSpinBox()
        self._size.setRange(1, 40)
        self._size.setValue(8)
        ctrl.addWidget(self._size)
        ctrl.addWidget(QLabel("  Min share:"))
        self._min = QDoubleSpinBox()
        self._min.setRange(0.0, 50.0)
        self._min.setDecimals(1)
        self._min.setValue(2.0)
        self._min.setSuffix(" %")
        ctrl.addWidget(self._min)
        self._stale = QCheckBox("Allow lists older than the window")
        ctrl.addWidget(self._stale)
        self._build_btn = QPushButton("Build")
        self._build_btn.setStyleSheet(theme.btn_primary())
        self._build_btn.clicked.connect(self.build)
        ctrl.addWidget(self._build_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        add = QHBoxLayout()
        self._add_edit = QLineEdit()
        self._add_edit.setPlaceholderText("Add an archetype by name (rebuilds with it included)")
        self._add_edit.returnPressed.connect(self._add_archetype)
        add.addWidget(self._add_edit, 1)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_archetype)
        add.addWidget(add_btn)
        root.addLayout(add)

        self._summary = QLabel("Build a gauntlet to see the field.")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color: {theme.TEXT_DIM};")
        root.addWidget(self._summary)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        for c in (C_TEST, C_SHARE, C_WEIGHT, C_PCT):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(C_ARCH, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(C_LIST, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(C_WARN, QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        bottom.addWidget(self._status, 1)
        self._save_btn = QPushButton("Save gauntlet")
        self._save_btn.setStyleSheet(theme.btn_success())
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self.save)
        bottom.addWidget(self._save_btn)
        root.addLayout(bottom)

    # -- build (worker) -------------------------------------------------------
    def _params(self, include=()):
        return {"format_name": self._fmt.currentText().lower(), "days": self._days.value(),
                "size": self._size.value(), "min_share": self._min.value() / 100,
                "include": tuple(include), "allow_stale": self._stale.isChecked()}

    def build(self, include=()):
        from analysis.gauntlet import build_gauntlet
        from gui.worker_threads import DataLoadWorker
        from gui.worker_utils import cancel_worker
        cancel_worker(self._worker)
        self._build_btn.setEnabled(False)
        self._status.setText("Building...")
        # The worker gets plain values only; it never touches widgets.
        self._worker = DataLoadWorker(build_gauntlet, self._params(include))
        self._worker.result.connect(self._on_built)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _add_archetype(self):
        name = self._add_edit.text().strip()
        if not name:
            return
        keep = [e["archetype"] for e in (self._g or {}).get("entries", []) if e["included"]]
        self._add_edit.clear()
        self.build(include=keep + [name])

    def _on_error(self, msg):
        try:
            self._build_btn.setEnabled(True)
            self._status.setText(theme.friendly_error(msg))
        except RuntimeError:
            pass

    def _on_built(self, g):
        try:
            self._build_btn.setEnabled(True)
            self.show_gauntlet(g)
        except RuntimeError:          # tab torn down while the worker ran
            pass
        except Exception as e:        # never raise inside a slot (PyQt6 aborts)
            self._status.setText(theme.friendly_error(e))

    # -- table ----------------------------------------------------------------
    def show_gauntlet(self, g):
        self._g = g
        self._filling = True
        try:
            self._table.setRowCount(len(g["entries"]))
            for r, e in enumerate(g["entries"]):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(Qt.CheckState.Checked if e["selected"] else Qt.CheckState.Unchecked)
                self._table.setItem(r, C_TEST, chk)
                arch = QTableWidgetItem(e["archetype"] + ("  (added)" if e["included"] else ""))
                if e.get("aliases"):
                    arch.setToolTip("Also stored as: " + ", ".join(e["aliases"]))
                self._table.setItem(r, C_ARCH, _ro(arch))
                self._table.setItem(r, C_SHARE, _ro(QTableWidgetItem(f"{e['share'] * 100:.1f}%")))
                w = (e["weight_override"] if e["weight_override"] is not None else e["share"]) * 100
                wi = QTableWidgetItem(f"{w:g}")
                wi.setToolTip("Relative weight. Defaults to the observed share; edit to override.")
                self._table.setItem(r, C_WEIGHT, wi)
                self._table.setItem(r, C_PCT, _ro(QTableWidgetItem("")))
                d = e["decklist"]
                li = QTableWidgetItem(_list_text(d))
                if d:
                    li.setToolTip(f"{d['url'] or ''}\n\n{d['text']}")
                self._table.setItem(r, C_LIST, _ro(li))
                warn = QTableWidgetItem("; ".join(e["warnings"]))
                if e["warnings"]:
                    warn.setForeground(QColor(theme.WARN))
                self._table.setItem(r, C_WARN, _ro(warn))
        finally:
            self._filling = False
        self._refresh_weights()
        self._save_btn.setEnabled(True)

    def _on_item_changed(self, item):
        if self._filling or not self._g:
            return
        if item.column() in (C_TEST, C_WEIGHT):
            try:
                self._refresh_weights()
            except Exception as e:     # never raise inside a slot (PyQt6 aborts)
                self._status.setText(theme.friendly_error(e))

    def _refresh_weights(self):
        """Read the include boxes and weight cells, renormalize, show Testing %."""
        from analysis.gauntlet import reweight
        g = self._g
        selected, weights = [], {}
        for r, e in enumerate(g["entries"]):
            if self._table.item(r, C_TEST).checkState() == Qt.CheckState.Checked:
                selected.append(e["archetype"])
            txt = self._table.item(r, C_WEIGHT).text().strip()
            default = f"{e['share'] * 100:g}"
            if txt and txt != default:
                try:
                    weights[e["archetype"]] = max(float(txt), 0.0) / 100
                except ValueError:
                    pass
        reweight(g, selected=selected, weights=weights)
        self._filling = True
        try:
            for r, e in enumerate(g["entries"]):
                self._table.item(r, C_PCT).setText(f"{e['weight'] * 100:.1f}%" if e["selected"] else "")
        finally:
            self._filling = False
        src = {"decks": "tournament placements", "matches": "melee.gg match seats"}[g["field_source"]]
        n = f"{g['total_field']:,} decks" if g["total_field"] else "match data"
        self._summary.setText(
            f"{g['format'].capitalize()} · {g['window']['since']} to {g['window']['until']} · "
            f"field share from {src} ({n}) · {sum(e['selected'] for e in g['entries'])} selected")
        self._status.setText("; ".join(g["warnings"]))

    # -- save -----------------------------------------------------------------
    def save(self):
        from analysis.gauntlet import save_gauntlet
        if not self._g:
            return
        self._refresh_weights()
        try:
            path = save_gauntlet(self._g)
            self._status.setText(f"Saved: {path}")
        except OSError as e:
            self._status.setText(f"Could not save: {e}")
        return self._status.text()

    def cleanup(self):
        from gui.worker_utils import cancel_worker
        cancel_worker(self._worker)


def _ro(item):
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _list_text(d):
    if not d:
        return "none"
    place = f"#{d['placement']} " if d["placement"] else ""
    return f"{place}{d['player'] or '?'} · {d['event']} · {d['event_date']}"
