"""
Reusable QTableWidget showing meta standings.
Emits archetype_selected(str) when a row is clicked.
"""
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class MetaTable(QTableWidget):
    archetype_selected = pyqtSignal(str)

    _COLUMNS = ["Archetype", "Appearances", "Top 8%", "Est Win%", "Avg Pts"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self._COLUMNS))
        self.setHorizontalHeaderLabels(self._COLUMNS)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        self.setSortingEnabled(True)

        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(self._COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        self.itemSelectionChanged.connect(self._on_selection)

    def populate(self, standings: list):
        """
        standings: list of dicts from get_meta_standings().
        Expected keys: archetype, appearances, top8_rate, est_winpct, avg_pts
        """
        # Temporarily disable sorting so rows insert in correct order
        self.setSortingEnabled(False)
        self.setRowCount(0)
        self.setRowCount(len(standings))

        for row, s in enumerate(standings):
            arch  = s.get("archetype", "")
            apps  = s.get("appearances", 0)
            top8  = s.get("top8_rate")
            win   = s.get("est_winpct")
            pts   = s.get("avg_pts")

            self._set(row, 0, arch,  align_left=True)
            self._set(row, 1, str(apps),                    num=float(apps))
            self._set(row, 2, f"{top8*100:.1f}%" if top8 is not None else "\u2014",
                      num=top8 * 100 if top8 is not None else 0)
            self._set(row, 3, f"{win*100:.1f}%"  if win  is not None else "\u2014",
                      num=win  * 100 if win  is not None else 0)
            self._set(row, 4, f"{pts:.2f}"        if pts  is not None else "\u2014",
                      num=pts if pts is not None else 0)

        self.setSortingEnabled(True)

    def _set(self, row, col, text, num=None, align_left=False):
        item = QTableWidgetItem(text)
        flag = (Qt.AlignmentFlag.AlignVCenter |
                (Qt.AlignmentFlag.AlignLeft if align_left
                 else Qt.AlignmentFlag.AlignHCenter))
        item.setTextAlignment(flag)
        if num is not None:
            item.setData(Qt.ItemDataRole.UserRole, num)
        self.setItem(row, col, item)

    def _on_selection(self):
        rows = self.selectedItems()
        if rows:
            arch_item = self.item(self.currentRow(), 0)
            if arch_item:
                self.archetype_selected.emit(arch_item.text())
