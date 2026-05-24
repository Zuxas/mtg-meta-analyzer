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
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QSplitter, QHeaderView, QSizePolicy, QAbstractItemView,
)

import gui.theme as theme
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


class ReplayViewerWindow(QMainWindow):
    """Top-level, non-modal full-depth replay viewer."""

    def __init__(self, arena_match_id: str, opp_name: str = "",
                 my_deck_label: str = "", parent=None, *, defer_load: bool = False):
        super().__init__(parent)
        self._arena_match_id = arena_match_id
        self._opp_name = opp_name or "Opp"
        self._my_deck_label = my_deck_label
        self._stream: Optional[dict] = None
        self._model: Optional[ReplayEventTableModel] = None
        self._current_seq: Optional[int] = None
        self._my_seat: Optional[int] = None
        self._opp_seat: Optional[int] = None
        self._worker = None

        self.setWindowTitle(f"Replay Viewer — {arena_match_id}")
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        # Non-modal window: free its memory when the user closes it.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._build_ui()
        if not defer_load:
            self._start_load(force=False)

    # ── UI skeleton ────────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                 theme.SPACE_MD, theme.SPACE_SM)
        outer.setSpacing(theme.SPACE_SM)

        # Top bar: match meta + nav (nav buttons wired in Task 9)
        self._topbar = QHBoxLayout()
        self._meta_lbl = QLabel("Loading…")
        self._meta_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._topbar.addWidget(self._meta_lbl, 1)
        self._counter_lbl = QLabel("")
        self._counter_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._topbar.addWidget(self._counter_lbl)
        outer.addLayout(self._topbar)

        # Center: event table (tree + detail added in later tasks)
        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            f"QTableView {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            f"gridline-color: {theme.BORDER_LO}; alternate-background-color: {theme.INPUT}; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; padding: 4px; }}"
        )
        outer.addWidget(self._table, 1)

    # ── data load ─────────────────────────────────────────────────────
    def _start_load(self, force: bool) -> None:
        from gui.worker_threads import DataLoadWorker
        self._meta_lbl.setText("Loading replay…")

        def _do():
            from analysis.replay_events import build_event_stream
            return build_event_stream(self._arena_match_id, force_refresh=force)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_data_ready)
        w.error.connect(lambda msg: self._meta_lbl.setText(f"Load failed: {msg}"))
        w.finished.connect(w.deleteLater)
        w.start()
        self._worker = w

    def _on_data_ready(self, stream: Optional[dict]) -> None:
        if stream is None:
            self._meta_lbl.setText(
                "Match not found in Player.log / Player-prev.log "
                "(log may have rotated)."
            )
            return
        self._stream = stream
        self._my_seat = stream.get("my_seat")
        self._opp_seat = stream.get("opp_seat")
        self._opp_name = stream.get("opp_name") or self._opp_name
        events = stream.get("events") or []

        self._model = ReplayEventTableModel(
            events, [e.get("seq") for e in events],
            self._my_seat, self._opp_seat, self._opp_name,
        )
        self._table.setModel(self._model)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.selectionModel().selectionChanged.connect(
            self._on_table_selection
        )

        meta = stream.get("match_meta") or {}
        self._meta_lbl.setText(
            f"{meta.get('event_name') or 'Match'}  ·  vs {self._opp_name}  ·  "
            f"{len(events)} events"
        )
        if events:
            self._select_seq(events[0].get("seq"))

    # ── selection ─────────────────────────────────────────────────────────
    def _select_seq(self, seq: Optional[int]) -> None:
        """The one place that moves the cursor. Later tasks extend this to
        also sync the tree, detail tabs, and card preview."""
        if seq is None or self._model is None:
            return
        self._current_seq = seq
        row = self._model.row_for_seq(seq)
        if row is not None:
            self._table.selectRow(row)
        total = self._model.rowCount()
        cur = (self._model.row_for_seq(seq) or 0) + 1
        self._counter_lbl.setText(f"Event {cur}/{total}")

    def _on_table_selection(self, *args) -> None:
        idxs = self._table.selectionModel().selectedRows()
        if not idxs or self._model is None:
            return
        seq = self._model.seq_for_row(idxs[0].row())
        if seq is not None and seq != self._current_seq:
            self._select_seq(seq)
