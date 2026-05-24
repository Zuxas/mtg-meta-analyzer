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

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, QSortFilterProxyModel
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QSplitter, QHeaderView, QSizePolicy, QAbstractItemView,
    QToolButton, QLineEdit, QButtonGroup, QCheckBox,
    QTreeWidget, QTreeWidgetItem,
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

        # Nav buttons (added to the existing topbar, left of the counter)
        self._nav_btns = {}
        for key, glyph, tip in (("first", "◀◀", "First event"),
                                ("prev", "◀", "Previous"),
                                ("next", "▶", "Next"),
                                ("last", "▶▶", "Last event")):
            b = QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.setStyleSheet(theme.btn_secondary())
            b.clicked.connect(lambda _=False, k=key: self._on_nav(k))
            self._topbar.insertWidget(self._topbar.count() - 1, b)
            self._nav_btns[key] = b

        # Filter row: kind-group chips + search box
        filt = QHBoxLayout()
        filt.setSpacing(theme.SPACE_XS)
        self._chip_boxes = {}
        for group in vm.KIND_GROUPS:
            cb = QCheckBox(group)
            cb.setChecked(group not in vm.DEFAULT_OFF_GROUPS)
            cb.setStyleSheet(f"color: {theme.TEXT_DIM};")
            cb.stateChanged.connect(self._on_chip_changed)
            filt.addWidget(cb)
            self._chip_boxes[group] = cb
        filt.addStretch()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search events…")
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 3px 8px; }}"
        )
        self._search.textChanged.connect(self._on_search_changed)
        filt.addWidget(self._search)
        outer.addLayout(filt)

        self._active_groups = {
            g for g in vm.KIND_GROUPS if g not in vm.DEFAULT_OFF_GROUPS
        }
        self._proxy = None

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
        body = QSplitter(Qt.Orientation.Horizontal)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; }}"
        )
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        body.addWidget(self._tree)
        body.addWidget(self._table)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 3)
        outer.addWidget(body, 1)

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
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterKeyColumn(3)  # Event column
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._table.setModel(self._proxy)
        self._populate_tree()
        self._apply_kind_filter()   # already present from Task 9; tree now precedes it
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
        if seq is None or self._model is None:
            return
        src_row = self._model.row_for_seq(seq)
        if src_row is None:
            return  # seq filtered out of the visible set; leave the cursor put
        self._current_seq = seq
        if self._proxy is not None:
            proxy_idx = self._proxy.mapFromSource(self._model.index(src_row, 0))
            if proxy_idx.isValid():
                self._table.selectRow(proxy_idx.row())
        total = self._model.rowCount()
        self._counter_lbl.setText(f"Event {src_row + 1}/{total}")
        leaf = getattr(self, "_leaf_by_seq", {}).get(seq)
        if leaf is not None:
            self._tree.setCurrentItem(leaf)
            self._tree.scrollToItem(leaf)

    def _on_table_selection(self, *args) -> None:
        idxs = self._table.selectionModel().selectedRows()
        if not idxs or self._model is None or self._proxy is None:
            return
        src_idx = self._proxy.mapToSource(idxs[0])
        seq = self._model.seq_for_row(src_idx.row())
        if seq is not None and seq != self._current_seq:
            self._select_seq(seq)

    def _on_nav(self, direction: str) -> None:
        if self._model is None or self._proxy is None:
            return
        # Navigate among rows currently visible in the proxy (kind filter AND
        # search), so Next/Prev never jumps to a row the search hides.
        visible = []
        for pr in range(self._proxy.rowCount()):
            src = self._proxy.mapToSource(self._proxy.index(pr, 0))
            seq = self._model.seq_for_row(src.row())
            if seq is not None:
                visible.append(seq)
        target = vm.nav_target(visible, self._current_seq, direction)
        if target is not None:
            self._select_seq(target)

    def _on_chip_changed(self, *args) -> None:
        self._active_groups = {
            g for g, cb in self._chip_boxes.items() if cb.isChecked()
        }
        self._apply_kind_filter()

    def _apply_kind_filter(self) -> None:
        if self._model is None or self._stream is None:
            return
        events = self._stream.get("events") or []
        allowed = vm.kinds_for_groups(self._active_groups)
        self._model.set_visible_seqs(vm.filter_events(events, allowed))
        if self._model.rowCount() == 0:
            self._counter_lbl.setText("0 events")
            self._current_seq = None
            return
        # Keep cursor valid after the row set changes.
        if self._model.row_for_seq(self._current_seq) is None:
            visible = [self._model.seq_for_row(r) for r in range(self._model.rowCount())]
            self._select_seq(vm.nav_target(visible, self._current_seq, "next"))

    def _populate_tree(self) -> None:
        if self._stream is None:
            return
        from gui import replay_view_model as _vm
        self._tree.clear()
        self._leaf_by_seq = {}
        tree = _vm.build_timeline_tree(
            self._stream.get("events") or [], self._my_seat, self._opp_seat,
            self._opp_name,
        )

        def _add(parent_item, node):
            item = QTreeWidgetItem([node.get("label", "")])
            if node.get("type") == "event":
                item.setData(0, Qt.ItemDataRole.UserRole, node.get("seq"))
                self._leaf_by_seq[node.get("seq")] = item
            if parent_item is None:
                self._tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for child in node.get("children", []):
                _add(item, child)
            return item

        for game_node in tree:
            top = _add(None, game_node)
            top.setExpanded(True)

    def _find_tree_leaf(self, seq):
        return getattr(self, "_leaf_by_seq", {}).get(seq)

    def _on_tree_item_clicked(self, item, _col) -> None:
        seq = item.data(0, Qt.ItemDataRole.UserRole)
        if seq is not None:
            self._select_seq(seq)

    def _on_search_changed(self, text: str) -> None:
        if self._proxy is not None:
            self._proxy.setFilterFixedString(text)
