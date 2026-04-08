"""
Shared table helpers — sort-aware items and table factory.

Consolidates _NumItem, _DateSortItem, _SortItem from multiple tabs.
"""

from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt


# ── Custom sort role ──────────────────────────────────────────────────────
SORT_ROLE = Qt.ItemDataRole.UserRole + 100


# ── Sort-aware QTableWidgetItem subclasses ────────────────────────────────

class SortItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a numeric/string key stored in SORT_ROLE."""

    def __lt__(self, other):
        a = self.data(SORT_ROLE)
        b = other.data(SORT_ROLE)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return super().__lt__(other)


class NumItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically (handles plain numbers and % strings)."""

    def __lt__(self, other):
        try:
            return float(self.text().rstrip('%')) < float(other.text().rstrip('%'))
        except (ValueError, TypeError):
            return super().__lt__(other)


class DateItem(QTableWidgetItem):
    """QTableWidgetItem that sorts dates correctly regardless of display format."""

    def __init__(self, display: str, sort_key: str = ""):
        super().__init__(display)
        self._sort_key = sort_key or display

    def __lt__(self, other):
        if isinstance(other, DateItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


def date_sort_key(raw: str) -> str:
    """Convert DD/MM/YYYY or YYYY-MM-DD or ISO to YYYYMMDD for sorting."""
    s = (raw or "").strip()[:10]
    if not s:
        return ""
    if len(s) == 10 and s[2] == "/" and s[5] == "/":
        return s[6:10] + s[3:5] + s[0:2]
    if len(s) == 10 and s[4] == "-":
        return s.replace("-", "")
    return s


# ── Table factory ─────────────────────────────────────────────────────────

def make_table(headers: list[str], *,
               stretch_columns: list[int] | None = None,
               sortable: bool = True,
               alternating: bool = True) -> QTableWidget:
    """
    Create a read-only QTableWidget with standard configuration.

    Args:
        headers: Column header labels.
        stretch_columns: Column indices to stretch (rest get ResizeToContents).
                        If None, stretches column 0 only.
        sortable: Enable column sort headers.
        alternating: Alternate row background colors.
    """
    tbl = QTableWidget(0, len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    tbl.setAlternatingRowColors(alternating)
    tbl.verticalHeader().setVisible(False)
    tbl.setSortingEnabled(sortable)

    if stretch_columns is None:
        stretch_columns = [0]

    hh = tbl.horizontalHeader()
    for i in range(len(headers)):
        if i in stretch_columns:
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        else:
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    return tbl
