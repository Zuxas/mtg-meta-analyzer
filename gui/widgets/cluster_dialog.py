"""
MetaClusterDialog — shows the current meta grouped by card-shell similarity.

Two archetypes that share most of their mainboard end up in the same
cluster (e.g., Jeskai Blink + Jeskai Control). Helps you see the meta
in terms of real playstyle buckets, not alphabetical lists.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QComboBox, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


class MetaClusterDialog(QDialog):
    def __init__(self, parent=None, format_name: str = "modern"):
        super().__init__(parent)
        self.setWindowTitle("Meta Clusters")
        self.setMinimumSize(*theme.DIALOG_MD)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        self._fmt = format_name
        self._workers = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                theme.SPACE_MD, theme.SPACE_MD)
        lay.setSpacing(theme.SPACE_SM)

        hdr = QLabel("Meta Clusters by Card Shell")
        hdr.setStyleSheet(theme.h1_style())
        lay.addWidget(hdr)

        desc = QLabel(
            "Archetypes in each cluster share ≥30% of their average "
            "mainboard. Use it to see the meta in terms of real playstyle "
            "buckets, not alphabetical lists."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(desc)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Threshold:"))
        self._thr = QComboBox()
        self._thr.addItems(["Loose (0.25)", "Default (0.30)",
                             "Tight (0.40)", "Strict (0.50)"])
        self._thr.setCurrentIndex(1)
        self._thr.currentIndexChanged.connect(lambda _: self._reload())
        ctrl.addWidget(self._thr)
        ctrl.addStretch()
        self._status = QLabel("Loading…")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        ctrl.addWidget(self._status)
        lay.addLayout(ctrl)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Archetype", "Meta %"])
        hh = self._tree.header()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self._tree, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        lay.addLayout(close_row)

        self._reload()

    def _threshold(self) -> float:
        values = [0.25, 0.30, 0.40, 0.50]
        return values[self._thr.currentIndex()]

    def _reload(self):
        self._status.setText("Clustering…")
        self._tree.clear()
        fmt = self._fmt
        threshold = self._threshold()

        def _do():
            from analysis.meta_clustering import cluster_archetypes
            return cluster_archetypes(fmt, top=20, threshold=threshold)

        w = DataLoadWorker(_do)
        w.result.connect(self._render)
        w.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _render(self, clusters: list):
        self._tree.clear()
        total_share = 0.0
        for c in clusters:
            share = c["meta_share"] * 100
            total_share += share
            n_arches = len(c["archetypes"])
            label = f"{c['label']}  ({n_arches} archetype{'s' if n_arches > 1 else ''})"
            parent = QTreeWidgetItem([label, f"{share:.1f}%"])
            font = QFont()
            font.setBold(True)
            parent.setFont(0, font)
            if n_arches > 1:
                parent.setForeground(0, QColor(theme.ACCENT))
            self._tree.addTopLevelItem(parent)
            for arch in c["archetypes"]:
                if arch == c["label"] and n_arches == 1:
                    continue   # don't duplicate the singleton
                child = QTreeWidgetItem([f"  · {arch}", ""])
                child.setForeground(0, QColor(theme.TEXT_DIM))
                parent.addChild(child)
            parent.setExpanded(True)
        self._status.setText(
            f"{len(clusters)} clusters · {total_share:.1f}% of field covered"
        )
