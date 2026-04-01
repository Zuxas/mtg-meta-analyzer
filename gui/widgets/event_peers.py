"""
Event Peers Dialog — shows all decks from a single tournament event.

Opened by clicking the Event column in the Dashboard's Recent Top Finishes panel.
Shows placement, archetype, player, and card count for every deck in the event.
Click any row to open the archetype detail dialog.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QFont, QColor, QDesktopServices

import gui.theme as theme


class EventPeersDialog(QDialog):
    def __init__(self, event_id: int, event_name: str = "",
                 event_url: str = "", parent=None):
        super().__init__(parent)
        self._event_id = event_id
        self._event_name = event_name
        self._event_url = event_url
        self._decks = []

        self.setWindowTitle(f"Event: {event_name}" if event_name else "Event Decks")
        self.resize(700, 500)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        self._build_ui()
        self._load_decks()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel(self._event_name or "Event")
        title.setFont(QFont("Orbitron", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.ACCENT};")
        title.setWordWrap(True)
        hdr.addWidget(title, 1)

        if self._event_url:
            link_btn = QPushButton("Open Source")
            link_btn.setStyleSheet(theme.btn_secondary())
            link_btn.setToolTip(self._event_url)
            link_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(self._event_url)))
            hdr.addWidget(link_btn)

        layout.addLayout(hdr)

        self._info_lbl = QLabel("Loading...")
        self._info_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self._info_lbl)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Place", "Archetype", "Player", "Main", "Side"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in (0, 3, 4):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.itemDoubleClicked.connect(self._on_row_click)

        # Card tooltip on archetype column
        try:
            from gui.widgets.card_tooltip import install_card_tooltip
            install_card_tooltip(self._table, card_name_column=1)
        except Exception:
            pass

        layout.addWidget(self._table, 1)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load_decks(self):
        from db.database import get_connection
        conn = get_connection()
        try:
            rows = conn.execute("""
                SELECT d.id, d.archetype, d.player, d.placement,
                       d.url,
                       (SELECT SUM(dc.quantity) FROM deck_cards dc
                        WHERE dc.deck_id = d.id AND dc.is_sideboard = 0) AS main_ct,
                       (SELECT SUM(dc.quantity) FROM deck_cards dc
                        WHERE dc.deck_id = d.id AND dc.is_sideboard = 1) AS side_ct
                FROM decks d
                WHERE d.event_id = ?
                ORDER BY d.placement ASC
            """, [self._event_id]).fetchall()
        finally:
            conn.close()

        self._decks = [dict(r) for r in rows]
        self._populate(self._decks)

    def _populate(self, decks: list):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(decks))

        for ri, d in enumerate(decks):
            pl = d.get("placement", 0)
            pl_item = QTableWidgetItem()
            pl_item.setData(Qt.ItemDataRole.DisplayRole, pl)
            if pl <= 4:
                pl_item.setForeground(QColor(theme.ACCENT))
                f = pl_item.font()
                f.setBold(True)
                pl_item.setFont(f)
            pl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 0, pl_item)

            arch = d.get("archetype", "") or "Unknown"
            arch_item = QTableWidgetItem(arch)
            arch_item.setData(Qt.ItemDataRole.UserRole, d)
            arch_item.setForeground(QColor(theme.ACCENT))
            self._table.setItem(ri, 1, arch_item)

            player = d.get("player", "") or ""
            self._table.setItem(ri, 2, QTableWidgetItem(player))

            main_ct = d.get("main_ct") or 0
            main_item = QTableWidgetItem()
            main_item.setData(Qt.ItemDataRole.DisplayRole, int(main_ct))
            main_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 3, main_item)

            side_ct = d.get("side_ct") or 0
            side_item = QTableWidgetItem()
            side_item.setData(Qt.ItemDataRole.DisplayRole, int(side_ct))
            side_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 4, side_item)

        self._table.setSortingEnabled(True)

        # Info label
        n = len(decks)
        archetypes = len({d.get("archetype", "") for d in decks if d.get("archetype")})
        self._info_lbl.setText(
            f"{n} decks from {archetypes} archetypes"
        )

    def _on_row_click(self, item):
        row = self._table.currentRow()
        arch_item = self._table.item(row, 1)
        if not arch_item:
            return
        d = arch_item.data(Qt.ItemDataRole.UserRole)
        if not d:
            return
        # Open archetype detail for this specific deck
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        dlg = ArchetypeDetailDialog(
            archetype=d.get("archetype", ""),
            format_name="",  # will detect from event
            initial_weeks=None,
            parent=self,
            deck_id=d.get("id"),
        )
        dlg.exec()
