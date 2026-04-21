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

        self._format = ""
        self.setWindowTitle(f"Event: {event_name}" if event_name else "Event Decks")
        self.resize(*theme.DIALOG_MD)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        self._build_ui()
        # Load in background to avoid blocking UI on large events
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self._load_decks)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_SM)

        # Header
        hdr = QHBoxLayout()
        title = QLabel(self._event_name or "Event")
        title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
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
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            ["Place", "Archetype", "Player"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.itemDoubleClicked.connect(self._on_row_click)
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
        try:
            from db.database import get_connection
            conn = get_connection()
            try:
                # Get event format
                ev_row = conn.execute(
                    "SELECT format FROM events WHERE id = ?", [self._event_id]
                ).fetchone()
                self._format = ev_row[0] if ev_row else ""

                # Simpler query without card count subqueries for speed
                rows = conn.execute("""
                    SELECT d.id, d.archetype, d.player, d.placement, d.url
                    FROM decks d
                    WHERE d.event_id = ?
                    ORDER BY d.placement ASC
                """, [self._event_id]).fetchall()
            finally:
                conn.close()

            self._decks = [dict(r) for r in rows]
            self._populate(self._decks)
        except Exception as e:
            self._info_lbl.setText(f"Error loading decks: {e}")

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

        self._table.setSortingEnabled(True)

        n = len(decks)
        archetypes = len({d.get("archetype", "") for d in decks if d.get("archetype")})
        fmt_label = f" ({self._format})" if self._format else ""
        self._info_lbl.setText(
            f"{n} decks from {archetypes} archetypes{fmt_label}"
        )

    def _on_row_click(self, item):
        row = self._table.currentRow()
        arch_item = self._table.item(row, 1)
        if not arch_item:
            return
        d = arch_item.data(Qt.ItemDataRole.UserRole)
        if not d:
            return
        try:
            from gui.widgets.archetype_detail import ArchetypeDetailDialog
            dlg = ArchetypeDetailDialog(
                archetype=d.get("archetype", ""),
                format_name=getattr(self, "_format", "") or "standard",
                initial_weeks=None,
                parent=self,
                deck_id=d.get("id"),
            )
            dlg.exec()
        except Exception:
            pass
