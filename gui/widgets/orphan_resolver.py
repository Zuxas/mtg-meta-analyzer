"""Modal that walks match_log rows with backfill_status='orphan' and lets the
user attach each one to a saved_deck. Closes when the queue is empty.

Used from MatchLogTab via a Resolve... banner that appears whenever any orphan
rows exist."""
from __future__ import annotations

import sqlite3

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QDialogButtonBox, QPushButton, QMessageBox,
)

import gui.theme as theme
from db.database import get_connection
from db.deck_variants import upsert_variant
from db.saved_decks import get_decks


class OrphanResolverDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resolve orphan matches")
        self.setMinimumSize(560, 220)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        self._queue: list[sqlite3.Row] = []
        self._current: sqlite3.Row | None = None

        layout = QVBoxLayout(self)

        self._summary = QLabel("")
        self._summary.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 11px;")
        layout.addWidget(self._summary)

        self._desc = QLabel("")
        self._desc.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px;")
        self._desc.setWordWrap(True)
        layout.addWidget(self._desc)

        row = QHBoxLayout()
        row.addWidget(QLabel("Attach to:"))
        self._combo = QComboBox()
        for d in get_decks():
            self._combo.addItem(f"{d['name']} ({d.get('archetype','?')})", d["id"])
        row.addWidget(self._combo, 1)
        layout.addLayout(row)

        btns = QHBoxLayout()
        self._attach_btn = QPushButton("Attach")
        self._attach_btn.clicked.connect(self._on_attach)
        btns.addWidget(self._attach_btn)
        self._skip_btn = QPushButton("Skip (keep as orphan)")
        self._skip_btn.clicked.connect(self._on_skip)
        btns.addWidget(self._skip_btn)
        btns.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btns.addWidget(self._close_btn)
        layout.addLayout(btns)

        self._load_queue()
        self._next()

    def _load_queue(self) -> None:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            self._queue = list(conn.execute(
                "SELECT * FROM match_log WHERE backfill_status='orphan' "
                "AND my_deck_id IS NULL ORDER BY event_date DESC, id DESC"
            ).fetchall())

    def _next(self) -> None:
        if not self._queue:
            self._current = None
            self._summary.setText("All resolved.")
            self._desc.setText("Queue empty.")
            self._attach_btn.setEnabled(False)
            self._skip_btn.setEnabled(False)
            return
        self._current = self._queue.pop(0)
        m = self._current
        remaining = len(self._queue)
        self._summary.setText(f"{remaining+1} orphan match{'es' if remaining else ''} remaining")
        self._desc.setText(
            f"<b>{m['event_date']}</b> · {m['event_name']} · "
            f"my_deck was '<i>{m['my_deck'] or '(blank)'}</i>' · "
            f"opp: {m['opp_deck'] or '(blank)'} · result: {m['result']}"
        )

    def _on_attach(self) -> None:
        if self._current is None:
            return
        deck_id = self._combo.currentData()
        if deck_id is None:
            QMessageBox.warning(self, "Pick a deck", "Select a saved deck first.")
            return
        decks = [d for d in get_decks() if d["id"] == deck_id]
        if not decks:
            return
        deck = decks[0]
        variant_hash = upsert_variant(
            deck_id=deck_id,
            mainboard=deck.get("mainboard", {}) or {},
            sideboard=deck.get("sideboard", {}) or {},
            won=(self._current["result"] == "win"),
        )
        with get_connection() as conn:
            conn.execute(
                "UPDATE match_log SET my_deck_id=?, my_variant_hash=?, "
                "backfill_status='manual' WHERE id=?",
                (deck_id, variant_hash, self._current["id"]),
            )
        self._next()

    def _on_skip(self) -> None:
        # Leave as orphan; just advance the cursor.
        self._next()
