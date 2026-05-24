"""Full-depth replay viewer (M2).

A QMainWindow that steps through one cached match at event granularity:
left timeline tree, center lazy event table, right detail tabs + card
preview. Consumes analysis.replay_events.build_event_stream output via a
background worker; never re-parses Player.log itself.

See docs/superpowers/specs/2026-05-22-replay-viewer-design.md (M2).
Display logic lives in gui/replay_view_model.py (Qt-free, unit-tested).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex

from gui import replay_view_model as vm


class ReplayEventTableModel(QAbstractTableModel):
    """Lazy table over events[], showing only visible_seqs rows.

    Columns: # / Turn / Player / Event. Lazy in the sense that data() formats
    one row on demand; a 2000-event match builds no per-row widgets.
    """

    COLUMNS = ["#", "Turn", "Player", "Event"]

    def __init__(self, events: list[dict], visible_seqs: list[int],
                 my_seat: Optional[int], opp_seat: Optional[int],
                 opp_name: str = "Opp", parent=None):
        super().__init__(parent)
        self._events = events
        self._by_seq = {e.get("seq"): e for e in events}
        self._visible = list(visible_seqs)
        self._my_seat = my_seat
        self._opp_seat = opp_seat
        self._opp_name = opp_name or "Opp"

    # -- lazy reset on filter change ---------------------------------------
    def set_visible_seqs(self, seqs: list[int]) -> None:
        self.beginResetModel()
        self._visible = list(seqs)
        self.endResetModel()

    # -- seq <-> row mapping (for selection sync) --------------------------
    def seq_for_row(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def row_for_seq(self, seq: int) -> Optional[int]:
        try:
            return self._visible.index(seq)
        except ValueError:
            return None

    def event_for_row(self, row: int) -> Optional[dict]:
        seq = self.seq_for_row(row)
        return self._by_seq.get(seq) if seq is not None else None

    # -- QAbstractTableModel API ------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        ev = self.event_for_row(index.row())
        if ev is None:
            return None
        row = vm.format_event_row(ev, self._my_seat, self._opp_seat, self._opp_name)
        col = index.column()
        if col == 0:
            return str(row["seq"])
        if col == 1:
            return str(row["turn"]) if row["turn"] is not None else ""
        if col == 2:
            return row["player"]
        if col == 3:
            return row["summary"]
        return None
