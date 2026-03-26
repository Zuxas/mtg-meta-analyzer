"""
Tab — My Decks

Left panel : list of saved decks with name, format, archetype, card count.
Right panel: selected deck details — full 75, sideboard plans, actions.

Actions:
  - Add deck (paste Arena/MTGO list)
  - Edit / Delete deck
  - Export (MTGO / MTGA / decklist.org)
  - Open in RCQ Optimizer (switches to Tournament Prep tab)
"""
import json

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QTextEdit, QFrame, QDialog, QFormLayout,
    QDialogButtonBox, QMessageBox, QScrollArea, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker

_FORMATS = ["standard", "pioneer", "modern", "legacy"]


# ---------------------------------------------------------------------------
# Deck list parser (Arena / MTGO format)
# ---------------------------------------------------------------------------

def _parse_decklist(text: str) -> tuple[dict, dict]:
    """Parse Arena/MTGO decklist text into (mainboard, sideboard) dicts.

    Returns ({card: qty}, {card: qty}).
    """
    main, side = {}, {}
    target = main
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low in ("deck", "companion", "commander"):
            continue
        if low in ("sideboard", "sideboard:", "sb:", "// sideboard"):
            target = side
            continue
        if line.startswith("SB: "):
            line = line[4:].strip()
            target = side
        # "4 Lightning Bolt" or "4x Lightning Bolt"
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            qty = int(parts[0].rstrip("x"))
        except ValueError:
            continue
        name = parts[1].strip()
        # Strip set codes like (DMU) 123 at end
        if "(" in name:
            name = name[:name.index("(")].strip()
        target[name] = target.get(name, 0) + qty
    return main, side


def _deck_to_text(main: dict, side: dict) -> str:
    """Format mainboard + sideboard as Arena-style text."""
    lines = []
    for card, qty in sorted(main.items()):
        lines.append(f"{qty} {card}")
    if side:
        lines.append("")
        lines.append("Sideboard")
        for card, qty in sorted(side.items()):
            lines.append(f"{qty} {card}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Add / Edit deck dialog
# ---------------------------------------------------------------------------

class _DeckDialog(QDialog):
    """Dialog to add or edit a deck."""

    def __init__(self, parent=None, deck=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Deck" if deck else "Add Deck")
        self.setMinimumSize(500, 500)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. My RCQ Pile")
        form.addRow("Deck Name:", self._name)

        self._format = QComboBox()
        self._format.addItems(_FORMATS)
        form.addRow("Format:", self._format)

        self._archetype = QLineEdit()
        self._archetype.setPlaceholderText("e.g. Izzet Prowess")
        form.addRow("Archetype:", self._archetype)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Optional notes")
        form.addRow("Notes:", self._notes)

        layout.addLayout(form)

        layout.addWidget(QLabel("Decklist (Arena/MTGO format):"))
        self._text = QTextEdit()
        self._text.setPlaceholderText(
            "Paste your decklist here...\n\n"
            "4 Lightning Bolt\n2 Counterspell\n...\n\n"
            "Sideboard\n2 Negate\n..."
        )
        self._text.setStyleSheet(
            f"background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; font-family: Consolas, monospace; font-size: 11px;"
        )
        layout.addWidget(self._text, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Pre-fill if editing
        if deck:
            self._name.setText(deck.get("name", ""))
            idx = self._format.findText(deck.get("format", ""), Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self._format.setCurrentIndex(idx)
            self._archetype.setText(deck.get("archetype", ""))
            self._notes.setText(deck.get("notes", ""))
            self._text.setPlainText(
                _deck_to_text(deck.get("mainboard", {}), deck.get("sideboard", {}))
            )

    def get_data(self) -> dict:
        """Return the dialog data as a dict."""
        main, side = _parse_decklist(self._text.toPlainText())
        return {
            "name":      self._name.text().strip(),
            "format":    self._format.currentText(),
            "archetype": self._archetype.text().strip(),
            "notes":     self._notes.text().strip(),
            "mainboard": main,
            "sideboard": side,
        }


# ---------------------------------------------------------------------------
# My Decks Tab
# ---------------------------------------------------------------------------

class MyDecksTab(QWidget):
    # Emitted when user clicks "Open in RCQ Optimizer" — main_window wires this
    open_in_rcq = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._current_deck = None  # currently selected deck dict
        self._build_ui()
        QTimer.singleShot(200, self._load_decks)

    def cleanup(self):
        """Stop running workers. Called by MainWindow on app exit."""
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: deck list ──────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        # Filter row
        filt = QHBoxLayout()
        filt.addWidget(QLabel("Format:"))
        self._filter_fmt = QComboBox()
        self._filter_fmt.addItems(["All"] + _FORMATS)
        self._filter_fmt.currentIndexChanged.connect(self._load_decks)
        filt.addWidget(self._filter_fmt)
        filt.addStretch()
        lv.addLayout(filt)

        # Deck table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Format", "Archetype", "Cards"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.clicked.connect(self._on_deck_clicked)
        lv.addWidget(self._table, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("+ Add Deck")
        self._add_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        self._add_btn.clicked.connect(self._add_deck)
        btn_row.addWidget(self._add_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_deck)
        btn_row.addWidget(self._edit_btn)

        self._del_btn = QPushButton("Delete")
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(f"color: {theme.ERR};")
        self._del_btn.clicked.connect(self._delete_deck)
        btn_row.addWidget(self._del_btn)

        btn_row.addStretch()
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # ── Right panel: deck detail ───────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)

        # Deck header
        self._header = QLabel("Select a deck to view details")
        self._header.setFont(QFont(theme.HEADING_FONT or "Arial", 14, QFont.Weight.Bold))
        self._header.setStyleSheet(f"color: {theme.ACCENT};")
        rv.addWidget(self._header)

        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        rv.addWidget(self._meta_lbl)

        # Tabs: Decklist / Sideboard Plans
        self._detail_tabs = QTabWidget()

        # -- Decklist sub-tab --
        dl_widget = QWidget()
        dl_layout = QVBoxLayout(dl_widget)
        dl_layout.setContentsMargins(4, 4, 4, 4)
        self._decklist_text = QTextEdit()
        self._decklist_text.setReadOnly(True)
        self._decklist_text.setStyleSheet(
            f"background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; font-family: Consolas, monospace; font-size: 11px;"
        )
        dl_layout.addWidget(self._decklist_text, 1)

        # Export row
        exp_row = QHBoxLayout()
        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_deck)
        exp_row.addWidget(self._export_btn)

        self._rcq_btn = QPushButton("Open in RCQ Optimizer")
        self._rcq_btn.setEnabled(False)
        self._rcq_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        self._rcq_btn.clicked.connect(self._open_in_rcq)
        exp_row.addWidget(self._rcq_btn)
        exp_row.addStretch()
        dl_layout.addLayout(exp_row)

        self._detail_tabs.addTab(dl_widget, "Decklist")

        # -- Sideboard Plans sub-tab --
        sb_widget = QWidget()
        sb_layout = QVBoxLayout(sb_widget)
        sb_layout.setContentsMargins(4, 4, 4, 4)

        self._sb_table = QTableWidget()
        self._sb_table.setColumnCount(4)
        self._sb_table.setHorizontalHeaderLabels(["Opponent", "Difficulty", "Play IN/OUT", "Draw IN/OUT"])
        self._sb_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for col in (1, 2, 3):
            self._sb_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self._sb_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._sb_table.verticalHeader().setVisible(False)
        self._sb_table.setAlternatingRowColors(True)
        sb_layout.addWidget(self._sb_table, 1)

        sb_info = QLabel("Sideboard plans are created in the RCQ Optimizer tab.")
        sb_info.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        sb_layout.addWidget(sb_info)

        self._detail_tabs.addTab(sb_widget, "Sideboard Plans")

        rv.addWidget(self._detail_tabs, 1)

        splitter.addWidget(right)
        splitter.setSizes([350, 550])

        outer.addWidget(splitter)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_decks(self):
        fmt = self._filter_fmt.currentText()
        fmt_arg = None if fmt == "All" else fmt

        def _do():
            from db.saved_decks import get_decks
            return get_decks(fmt_arg)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_decks_loaded)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_decks_loaded(self, decks: list):
        self._decks = decks
        self._table.setRowCount(len(decks))
        for row, d in enumerate(decks):
            main = d.get("mainboard", {})
            side = d.get("sideboard", {})
            total = sum(main.values()) + sum(side.values())

            name_item = QTableWidgetItem(d.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, d.get("id"))
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(d.get("format", "")))

            arch_item = QTableWidgetItem(d.get("archetype", ""))
            arch_item.setForeground(QColor(theme.ACCENT))
            self._table.setItem(row, 2, arch_item)

            ct_item = QTableWidgetItem(str(total))
            ct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, ct_item)

        # Clear detail panel if selected deck was deleted
        if self._current_deck:
            ids = {d["id"] for d in decks}
            if self._current_deck.get("id") not in ids:
                self._clear_detail()

    # ------------------------------------------------------------------
    # Deck selection
    # ------------------------------------------------------------------

    def _on_deck_clicked(self, index):
        row = index.row()
        if row < 0 or row >= len(self._decks):
            return
        deck = self._decks[row]
        self._current_deck = deck
        self._show_deck(deck)
        self._edit_btn.setEnabled(True)
        self._del_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._rcq_btn.setEnabled(True)

    def _show_deck(self, deck):
        name = deck.get("name", "Unnamed")
        arch = deck.get("archetype", "")
        fmt  = deck.get("format", "")
        main = deck.get("mainboard", {})
        side = deck.get("sideboard", {})

        self._header.setText(name)
        parts = []
        if fmt:
            parts.append(fmt.capitalize())
        if arch:
            parts.append(arch)
        main_ct = sum(main.values())
        side_ct = sum(side.values())
        parts.append(f"{main_ct} main / {side_ct} side")
        notes = deck.get("notes", "")
        if notes:
            parts.append(notes)
        self._meta_lbl.setText("  \u2022  ".join(parts))

        self._decklist_text.setPlainText(_deck_to_text(main, side))

        # Load SB plans
        self._load_sb_plans(deck.get("id"))

    def _load_sb_plans(self, deck_id):
        if not deck_id:
            self._sb_table.setRowCount(0)
            return

        def _do():
            from db.saved_decks import get_sb_plans
            return get_sb_plans(deck_id)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_sb_plans_loaded)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_sb_plans_loaded(self, plans: list):
        self._sb_table.setRowCount(len(plans))
        for row, p in enumerate(plans):
            opp = p.get("opponent_archetype", "")
            diff = p.get("difficulty", "Medium")
            play_in  = p.get("play_in", [])
            play_out = p.get("play_out", [])
            draw_in  = p.get("draw_in", [])
            draw_out = p.get("draw_out", [])

            self._sb_table.setItem(row, 0, QTableWidgetItem(opp))

            diff_item = QTableWidgetItem(diff)
            diff_colors = {
                "Easy": theme.OK, "Medium": theme.WARN, "Hard": theme.ERR,
            }
            diff_item.setForeground(QColor(diff_colors.get(diff, theme.TEXT)))
            self._sb_table.setItem(row, 1, diff_item)

            play_str = ""
            if play_in:
                play_str += "IN: " + ", ".join(play_in)
            if play_out:
                if play_str:
                    play_str += " | "
                play_str += "OUT: " + ", ".join(play_out)
            self._sb_table.setItem(row, 2, QTableWidgetItem(play_str or "\u2014"))

            draw_str = ""
            if draw_in:
                draw_str += "IN: " + ", ".join(draw_in)
            if draw_out:
                if draw_str:
                    draw_str += " | "
                draw_str += "OUT: " + ", ".join(draw_out)
            self._sb_table.setItem(row, 3, QTableWidgetItem(draw_str or "\u2014"))

    def _clear_detail(self):
        self._current_deck = None
        self._header.setText("Select a deck to view details")
        self._meta_lbl.setText("")
        self._decklist_text.clear()
        self._sb_table.setRowCount(0)
        self._edit_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._export_btn.setEnabled(False)
        self._rcq_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # CRUD actions
    # ------------------------------------------------------------------

    def _add_deck(self):
        dlg = _DeckDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["name"]:
            QMessageBox.warning(self, "Missing Name", "Please enter a deck name.")
            return
        if not data["mainboard"]:
            QMessageBox.warning(self, "Empty Deck", "Please paste a decklist.")
            return

        from db.saved_decks import save_deck
        save_deck(
            name=data["name"],
            format_name=data["format"],
            archetype=data["archetype"],
            mainboard=data["mainboard"],
            sideboard=data["sideboard"],
            notes=data["notes"],
        )
        self._load_decks()

    def _edit_deck(self):
        if not self._current_deck:
            return
        dlg = _DeckDialog(self, deck=self._current_deck)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["name"]:
            return

        from db.saved_decks import save_deck
        save_deck(
            name=data["name"],
            format_name=data["format"],
            archetype=data["archetype"],
            mainboard=data["mainboard"],
            sideboard=data["sideboard"],
            notes=data["notes"],
            deck_id=self._current_deck["id"],
        )
        self._load_decks()
        # Re-select to refresh detail panel
        self._current_deck["name"] = data["name"]
        self._current_deck["format"] = data["format"]
        self._current_deck["archetype"] = data["archetype"]
        self._current_deck["mainboard"] = data["mainboard"]
        self._current_deck["sideboard"] = data["sideboard"]
        self._current_deck["notes"] = data["notes"]
        self._show_deck(self._current_deck)

    def _delete_deck(self):
        if not self._current_deck:
            return
        name = self._current_deck.get("name", "this deck")
        reply = QMessageBox.question(
            self, "Delete Deck",
            f"Delete \"{name}\" and all its sideboard plans?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from db.saved_decks import delete_deck
        delete_deck(self._current_deck["id"])
        self._clear_detail()
        self._load_decks()

    # ------------------------------------------------------------------
    # Export & RCQ
    # ------------------------------------------------------------------

    def _export_deck(self):
        if not self._current_deck:
            return
        from gui.widgets.deck_export import show_export_menu
        show_export_menu(
            btn_widget=self._export_btn,
            mainboard=self._current_deck.get("mainboard", {}),
            sideboard=self._current_deck.get("sideboard", {}),
            archetype=self._current_deck.get("name", "Deck"),
            format_name=self._current_deck.get("format", "standard"),
        )

    def _open_in_rcq(self):
        if not self._current_deck:
            return
        self.open_in_rcq.emit(self._current_deck)
