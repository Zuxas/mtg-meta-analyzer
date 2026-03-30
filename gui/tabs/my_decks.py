"""
Tab — My Decks

Left panel : list of saved decks with name, format, archetype, card count.
Right panel: selected deck details — full 75, sideboard plans, actions.

Actions:
  - Add deck (paste Arena/MTGO list)
  - Edit / Delete deck
  - Export (MTGO / MTGA / decklist.org)
  - Open in Event Optimizer (switches to Tournament Prep tab)
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
# Add / Edit sideboard plan dialog
# ---------------------------------------------------------------------------

class _SBPlanDialog(QDialog):
    """Dialog to add or edit a sideboard plan for a specific matchup."""

    def __init__(self, parent=None, plan=None, exclude_opponents=None,
                 format_name="standard"):
        super().__init__(parent)
        self.setWindowTitle("Edit Sideboard Plan" if plan else "Add Sideboard Plan")
        self.setMinimumSize(500, 480)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._opp = QComboBox()
        self._opp.setEditable(True)
        self._opp.lineEdit().setPlaceholderText("e.g. Boros Energy")
        # Populate with top meta archetypes for this deck's format
        already = exclude_opponents or set()
        try:
            from analysis.win_rates import get_meta_standings
            top = get_meta_standings(format_name, top=20)
            self._opp.addItems([s["archetype"] for s in top
                                if s["archetype"] not in already])
        except Exception:
            pass
        form.addRow("Opponent Archetype:", self._opp)

        self._diff = QComboBox()
        self._diff.addItems(["Easy", "Medium", "Hard"])
        self._diff.setCurrentText("Medium")
        form.addRow("Difficulty:", self._diff)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Optional notes")
        form.addRow("Notes:", self._notes)
        layout.addLayout(form)

        _style = (f"background: {theme.INPUT}; color: {theme.TEXT}; "
                  f"border: 1px solid {theme.BORDER}; font-family: Consolas, monospace; font-size: 11px;")

        layout.addWidget(QLabel("On the Play — IN (one per line: Card Name):"))
        self._play_in = QTextEdit()
        self._play_in.setMaximumHeight(60)
        self._play_in.setStyleSheet(_style)
        layout.addWidget(self._play_in)

        layout.addWidget(QLabel("On the Play — OUT:"))
        self._play_out = QTextEdit()
        self._play_out.setMaximumHeight(60)
        self._play_out.setStyleSheet(_style)
        layout.addWidget(self._play_out)

        layout.addWidget(QLabel("On the Draw — IN:"))
        self._draw_in = QTextEdit()
        self._draw_in.setMaximumHeight(60)
        self._draw_in.setStyleSheet(_style)
        layout.addWidget(self._draw_in)

        layout.addWidget(QLabel("On the Draw — OUT:"))
        self._draw_out = QTextEdit()
        self._draw_out.setMaximumHeight(60)
        self._draw_out.setStyleSheet(_style)
        layout.addWidget(self._draw_out)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Pre-fill if editing
        if plan:
            self._opp.setCurrentText(plan.get("opponent_archetype", ""))
            self._diff.setCurrentText(plan.get("difficulty", "Medium"))
            self._notes.setText(plan.get("notes", ""))
            self._play_in.setPlainText("\n".join(plan.get("play_in", [])))
            self._play_out.setPlainText("\n".join(plan.get("play_out", [])))
            self._draw_in.setPlainText("\n".join(plan.get("draw_in", [])))
            self._draw_out.setPlainText("\n".join(plan.get("draw_out", [])))

    def get_data(self) -> dict:
        def _lines(te):
            return [l.strip() for l in te.toPlainText().splitlines() if l.strip()]
        return {
            "opponent_archetype": self._opp.currentText().strip(),
            "difficulty":         self._diff.currentText(),
            "notes":              self._notes.text().strip(),
            "play_in":            _lines(self._play_in),
            "play_out":           _lines(self._play_out),
            "draw_in":            _lines(self._draw_in),
            "draw_out":           _lines(self._draw_out),
        }


# ---------------------------------------------------------------------------
# My Decks Tab
# ---------------------------------------------------------------------------

class MyDecksTab(QWidget):
    # Emitted when user clicks "Open in Event Optimizer" — main_window wires this
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

        self._import_json_btn = QPushButton("Import JSON")
        self._import_json_btn.setStyleSheet(theme.btn_secondary())
        self._import_json_btn.setToolTip("Import a deck + SB plans from a shared JSON file")
        self._import_json_btn.clicked.connect(self._import_json)
        btn_row.addWidget(self._import_json_btn)

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

        self._guide_btn = QPushButton("Export Guide")
        self._guide_btn.setEnabled(False)
        self._guide_btn.setToolTip("Generate a printable HTML tournament guide with SB plans")
        self._guide_btn.clicked.connect(self._export_guide)
        exp_row.addWidget(self._guide_btn)

        self._share_btn = QPushButton("Share JSON")
        self._share_btn.setEnabled(False)
        self._share_btn.setToolTip("Export deck + SB plans as JSON for teammates")
        self._share_btn.clicked.connect(self._share_json)
        exp_row.addWidget(self._share_btn)

        self._rcq_btn = QPushButton("Open in Event Optimizer")
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

        sb_btn_row = QHBoxLayout()
        self._add_plan_btn = QPushButton("+ Add Plan")
        self._add_plan_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        self._add_plan_btn.setEnabled(False)
        self._add_plan_btn.clicked.connect(self._add_sb_plan)
        sb_btn_row.addWidget(self._add_plan_btn)

        self._edit_plan_btn = QPushButton("Edit Plan")
        self._edit_plan_btn.setEnabled(False)
        self._edit_plan_btn.setStyleSheet(theme.btn_secondary())
        self._edit_plan_btn.clicked.connect(self._edit_sb_plan)
        sb_btn_row.addWidget(self._edit_plan_btn)

        self._del_plan_btn = QPushButton("Delete Plan")
        self._del_plan_btn.setEnabled(False)
        self._del_plan_btn.setStyleSheet(f"color: {theme.ERR};")
        self._del_plan_btn.clicked.connect(self._delete_sb_plan)
        sb_btn_row.addWidget(self._del_plan_btn)

        self._sb_guide_btn = QPushButton("Print SB Guide")
        self._sb_guide_btn.setEnabled(False)
        self._sb_guide_btn.setStyleSheet(theme.btn_primary())
        self._sb_guide_btn.setToolTip("Print-friendly sideboard guide (plans only, no decklist)")
        self._sb_guide_btn.clicked.connect(self._export_sb_only)
        sb_btn_row.addWidget(self._sb_guide_btn)

        self._suggest_btn = QPushButton("Suggest Plans")
        self._suggest_btn.setEnabled(False)
        self._suggest_btn.setStyleSheet(theme.btn_secondary())
        self._suggest_btn.setToolTip(
            "Auto-generate SB plans from your actual sideboard cards\n"
            "Uses community guides + card role analysis")
        self._suggest_btn.clicked.connect(self._suggest_sb_plans)
        sb_btn_row.addWidget(self._suggest_btn)
        sb_btn_row.addStretch()
        sb_layout.addLayout(sb_btn_row)

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
        self._guide_btn.setEnabled(True)
        self._share_btn.setEnabled(True)
        self._rcq_btn.setEnabled(True)
        self._add_plan_btn.setEnabled(True)
        self._edit_plan_btn.setEnabled(True)
        self._del_plan_btn.setEnabled(True)
        self._sb_guide_btn.setEnabled(True)
        self._suggest_btn.setEnabled(True)

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
        self._guide_btn.setEnabled(False)
        self._rcq_btn.setEnabled(False)
        self._add_plan_btn.setEnabled(False)
        self._edit_plan_btn.setEnabled(False)
        self._del_plan_btn.setEnabled(False)
        self._sb_guide_btn.setEnabled(False)
        self._suggest_btn.setEnabled(False)

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
    # Sideboard plan CRUD
    # ------------------------------------------------------------------

    def _add_sb_plan(self):
        if not self._current_deck:
            return
        # Collect existing opponents so the dialog can exclude them
        existing_opps = set()
        for row in range(self._sb_table.rowCount()):
            item = self._sb_table.item(row, 0)
            if item:
                existing_opps.add(item.text())
        fmt = self._current_deck.get("format", "standard")
        dlg = _SBPlanDialog(self, exclude_opponents=existing_opps, format_name=fmt)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["opponent_archetype"]:
            QMessageBox.warning(self, "Missing Opponent", "Enter an opponent archetype.")
            return
        from db.saved_decks import save_sb_plan
        save_sb_plan(
            deck_id=self._current_deck["id"],
            opponent_archetype=data["opponent_archetype"],
            play_in=data["play_in"],
            play_out=data["play_out"],
            draw_in=data["draw_in"],
            draw_out=data["draw_out"],
            notes=data["notes"],
            difficulty=data["difficulty"],
        )
        self._load_sb_plans(self._current_deck["id"])

    def _edit_sb_plan(self):
        """Edit an existing SB plan — opens the dialog pre-filled with current data."""
        if not self._current_deck:
            return
        row = self._sb_table.currentRow()
        if row < 0:
            return
        opp_item = self._sb_table.item(row, 0)
        if not opp_item:
            return
        opp = opp_item.text()

        # Load the plan from DB
        from db.saved_decks import get_sb_plan
        plan = get_sb_plan(self._current_deck["id"], opp)
        if not plan:
            return

        fmt = self._current_deck.get("format", "modern")
        dlg = _SBPlanDialog(self, plan=plan, format_name=fmt)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        from db.saved_decks import save_sb_plan
        save_sb_plan(
            deck_id=self._current_deck["id"],
            opponent_archetype=data["opponent_archetype"],
            play_in=data["play_in"],
            play_out=data["play_out"],
            draw_in=data["draw_in"],
            draw_out=data["draw_out"],
            notes=data["notes"],
            difficulty=data["difficulty"],
        )
        self._load_sb_plans(self._current_deck["id"])

    def _delete_sb_plan(self):
        if not self._current_deck:
            return
        row = self._sb_table.currentRow()
        if row < 0:
            return
        opp_item = self._sb_table.item(row, 0)
        if not opp_item:
            return
        opp = opp_item.text()
        reply = QMessageBox.question(
            self, "Delete Plan",
            f"Delete sideboard plan for vs {opp}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from db.saved_decks import delete_sb_plan
        delete_sb_plan(self._current_deck["id"], opp)
        self._load_sb_plans(self._current_deck["id"])

    # ------------------------------------------------------------------
    # Export & RCQ
    # ------------------------------------------------------------------

    def _suggest_sb_plans(self):
        """Auto-generate SB plans from sideboard cards using guides + role analysis."""
        if not self._current_deck:
            return
        deck = self._current_deck
        sideboard = deck.get("sideboard", {})
        if not sideboard:
            QMessageBox.warning(self, "No Sideboard",
                                "This deck has no sideboard cards. Add your 15 first.")
            return

        fmt = deck.get("format", "modern")
        deck_id = deck.get("id")
        self._suggest_btn.setEnabled(False)

        # Get existing plans to skip
        existing = set()
        for row in range(self._sb_table.rowCount()):
            item = self._sb_table.item(row, 0)
            if item:
                existing.add(item.text())

        def _do():
            from analysis.sb_advisor import suggest_all_plans
            from analysis.win_rates import get_meta_standings
            from datetime import datetime, timedelta
            since_4w = datetime.now() - timedelta(weeks=4)
            standings = get_meta_standings(fmt, top=15, since=since_4w)
            meta_names = [s["archetype"] for s in standings
                          if s["archetype"] not in existing and s["appearances"] >= 15]
            mainboard = deck.get("mainboard", {})
            return suggest_all_plans(sideboard, meta_names, fmt, mainboard=mainboard)

        def _done(suggestions):
            self._suggest_btn.setEnabled(True)
            if not suggestions:
                QMessageBox.information(self, "No Suggestions",
                                        "No SB suggestions found. Add guides to Knowledge Base "
                                        "or the advisor needs more card data.")
                return

            # Show suggestions in a dialog for review before saving
            dlg = QDialog(self)
            dlg.setWindowTitle("SB Plan Suggestions")
            dlg.setMinimumSize(600, 450)
            dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
            layout = QVBoxLayout(dlg)

            layout.addWidget(QLabel(
                f"Suggested SB plans for {len(suggestions)} matchups based on your 15 sideboard cards.\n"
                f"Review and click Save to create plans."))

            tbl = QTableWidget(len(suggestions), 5)
            tbl.setHorizontalHeaderLabels(["Opponent", "Bring IN", "Take OUT", "Source", "#"])
            tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            tbl.verticalHeader().setVisible(False)

            for ri, s in enumerate(suggestions):
                tbl.setItem(ri, 0, QTableWidgetItem(s["opponent"]))
                in_cards = ", ".join(f"+{b['qty']} {b['card']}" for b in s["bring_in"])
                in_item = QTableWidgetItem(in_cards)
                in_item.setForeground(QColor(theme.OK))
                tbl.setItem(ri, 1, in_item)
                out_cards = ", ".join(f"-{b['qty']} {b['card']}" for b in s.get("take_out", []))
                out_item = QTableWidgetItem(out_cards or "(edit after saving)")
                if out_cards:
                    out_item.setForeground(QColor(theme.ERR))
                else:
                    out_item.setForeground(QColor(theme.TEXT_DIM))
                tbl.setItem(ri, 2, out_item)
                tbl.setItem(ri, 3, QTableWidgetItem(s["coverage"]))
                total = sum(b["qty"] for b in s["bring_in"])
                tbl.setItem(ri, 4, QTableWidgetItem(str(total)))

            layout.addWidget(tbl, 1)

            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            # Save all suggested plans
            from db.saved_decks import save_sb_plan
            saved = 0
            for s in suggestions:
                in_cards = [b["card"] for b in s["bring_in"]]
                out_cards = [b["card"] for b in s.get("take_out", [])]
                if in_cards:
                    save_sb_plan(
                        deck_id=deck_id,
                        opponent_archetype=s["opponent"],
                        play_in=in_cards, play_out=out_cards,
                        draw_in=in_cards, draw_out=out_cards,
                        notes=f"Auto-suggested: {s['coverage']}",
                        difficulty="Medium",
                    )
                    saved += 1

            self._load_sb_plans(deck_id)
            QMessageBox.information(self, "Plans Saved",
                                    f"Created {saved} SB plans. Review and edit as needed.")

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            QMessageBox.warning(self, "Error", str(e)),
            self._suggest_btn.setEnabled(True),
        ))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _share_json(self):
        """Export deck + SB plans as JSON for teammates."""
        if not self._current_deck:
            return
        import json, os
        from datetime import datetime
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        deck = self._current_deck
        deck_id = deck.get("id")

        # Get SB plans
        from db.saved_decks import get_sb_plans
        plans = get_sb_plans(deck_id) if deck_id else []

        export = {
            "name": deck.get("name", ""),
            "format": deck.get("format", ""),
            "archetype": deck.get("archetype", ""),
            "mainboard": deck.get("mainboard", {}),
            "sideboard": deck.get("sideboard", {}),
            "notes": deck.get("notes", ""),
            "sb_plans": [{
                "opponent": p.get("opponent_archetype", ""),
                "difficulty": p.get("difficulty", "Medium"),
                "play_in": p.get("play_in", []),
                "play_out": p.get("play_out", []),
                "draw_in": p.get("draw_in", []),
                "draw_out": p.get("draw_out", []),
                "notes": p.get("notes", ""),
            } for p in plans],
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        exports = os.path.join(root, "exports")
        os.makedirs(exports, exist_ok=True)
        safe = deck.get("name", "deck").replace("/", "_").replace(":", "_")
        path = os.path.join(exports, f"{safe}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        QDesktopServices.openUrl(QUrl.fromLocalFile(exports))

    def _import_json(self):
        """Import a deck + SB plans from a shared JSON file."""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Deck JSON", "", "JSON files (*.json)")
        if not path:
            return
        import json
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Import Error", f"Could not read file: {e}")
            return

        name = data.get("name", "Imported Deck")
        fmt = data.get("format", "modern")
        arch = data.get("archetype", "")
        main = data.get("mainboard", {})
        side = data.get("sideboard", {})
        notes = data.get("notes", "")

        from db.saved_decks import save_deck, save_sb_plan
        deck_id = save_deck(name=name, format_name=fmt, archetype=arch,
                            mainboard=main, sideboard=side, notes=notes)

        for p in data.get("sb_plans", []):
            save_sb_plan(
                deck_id=deck_id,
                opponent_archetype=p.get("opponent", ""),
                play_in=p.get("play_in", []),
                play_out=p.get("play_out", []),
                draw_in=p.get("draw_in", []),
                draw_out=p.get("draw_out", []),
                notes=p.get("notes", ""),
                difficulty=p.get("difficulty", "Medium"),
            )

        self._load_decks()
        QMessageBox.information(self, "Imported",
                                f"Imported '{name}' with {len(data.get('sb_plans', []))} SB plans.")

    def _export_sb_only(self):
        """Print-friendly SB guide: plans only, no decklist, two-column layout."""
        if not self._current_deck:
            return
        deck = self._current_deck
        deck_id = deck.get("id")

        def _do():
            from db.saved_decks import get_sb_plans
            plans = get_sb_plans(deck_id) if deck_id else []
            return _generate_sb_print_html(deck, plans)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_guide_generated)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

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

    def _export_guide(self):
        if not self._current_deck:
            return
        deck = self._current_deck
        deck_id = deck.get("id")

        def _do():
            from db.saved_decks import get_sb_plans
            plans = get_sb_plans(deck_id) if deck_id else []
            return _generate_guide_html(deck, plans)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_guide_generated)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_guide_generated(self, html: str):
        import os
        from datetime import datetime
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        exports = os.path.join(root, "exports")
        os.makedirs(exports, exist_ok=True)

        name = self._current_deck.get("name", "deck") if self._current_deck else "deck"
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(exports, f"guide_{safe}_{ts}.html")

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_in_rcq(self):
        if not self._current_deck:
            return
        self.open_in_rcq.emit(self._current_deck)


# ---------------------------------------------------------------------------
# Tournament guide HTML generator
# ---------------------------------------------------------------------------

_DIFF_COLORS = {"Easy": "#3cb44b", "Medium": "#f58231", "Hard": "#e6194b"}


def _card_list_html(cards: list, label: str, color: str) -> str:
    """Format a list of card name strings as an HTML line."""
    if not cards:
        return ""
    items = ", ".join(cards)
    return f'<span style="color:{color}; font-weight:bold;">{label}:</span> {items}<br>\n'


def _generate_sb_print_html(deck: dict, plans: list[dict]) -> str:
    """Generate a compact, print-friendly HTML with SB plans only (no decklist).
    Two-column grid layout that fits on one printed page."""
    name = deck.get("name", "Deck")
    fmt  = deck.get("format", "").capitalize()
    arch = deck.get("archetype", "")

    parts = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{name} — SB Guide</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 10px; color: #222; }}
  h1 {{ font-size: 16px; margin: 0 0 6px 0; border-bottom: 2px solid #333; padding-bottom: 4px; }}
  .meta {{ color: #666; font-size: 11px; margin-bottom: 8px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
  .mu {{ border: 1px solid #ccc; border-radius: 4px; padding: 6px 8px; font-size: 11px; break-inside: avoid; }}
  .mu-name {{ font-weight: bold; font-size: 12px; margin-bottom: 3px; }}
  .diff {{ font-size: 10px; font-weight: bold; }}
  .easy {{ color: #2a7a2a; }} .medium {{ color: #b87800; }} .hard {{ color: #c22; }}
  .label {{ font-weight: bold; font-size: 10px; }}
  .in {{ color: #2a7a2a; }} .out {{ color: #c22; }}
  .notes {{ color: #666; font-style: italic; font-size: 10px; margin-top: 2px; }}
  @media print {{
    body {{ margin: 0; }} .grid {{ gap: 6px; }}
    .mu {{ border: 1px solid #999; padding: 4px 6px; }}
  }}
</style>
</head><body>
<h1>{name} SB Guide</h1>
<div class="meta">{fmt} &bull; {arch} &bull; {len(plans)} matchups</div>
<div class="grid">
"""]

    for p in plans:
        opp  = p.get("opponent_archetype", "?")
        diff = p.get("difficulty", "Medium")
        dc   = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}.get(diff, "medium")
        pn   = p.get("notes", "")
        play_in  = p.get("play_in", [])
        play_out = p.get("play_out", [])
        draw_in  = p.get("draw_in", [])
        draw_out = p.get("draw_out", [])

        parts.append(f'<div class="mu">')
        parts.append(f'<div class="mu-name">{opp} <span class="diff {dc}">[{diff}]</span></div>')
        if play_in or play_out:
            parts.append(f'<b>Play:</b> ')
            if play_in:
                parts.append(f'<span class="in">+{", +".join(play_in)}</span> ')
            if play_out:
                parts.append(f'<span class="out">-{", -".join(play_out)}</span>')
            parts.append('<br>')
        if draw_in or draw_out:
            parts.append(f'<b>Draw:</b> ')
            if draw_in:
                parts.append(f'<span class="in">+{", +".join(draw_in)}</span> ')
            if draw_out:
                parts.append(f'<span class="out">-{", -".join(draw_out)}</span>')
            parts.append('<br>')
        if not (play_in or play_out or draw_in or draw_out):
            parts.append('<span class="notes">No IN/OUT saved</span><br>')
        if pn:
            parts.append(f'<div class="notes">{pn}</div>')
        parts.append('</div>\n')

    parts.append('</div></body></html>')
    return "".join(parts)


def _generate_guide_html(deck: dict, plans: list[dict]) -> str:
    """Generate a printable HTML tournament guide."""
    name = deck.get("name", "Deck")
    fmt  = deck.get("format", "").capitalize()
    arch = deck.get("archetype", "")
    main = deck.get("mainboard", {})
    side = deck.get("sideboard", {})
    notes = deck.get("notes", "")

    parts = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{name} — Tournament Guide</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 20px auto;
         background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
  h1 {{ color: #65bcd5; border-bottom: 2px solid #65bcd5; padding-bottom: 8px; }}
  h2 {{ color: #65bcd5; margin-top: 24px; }}
  h3 {{ color: #bfef45; margin-top: 16px; margin-bottom: 4px; }}
  .meta {{ color: #8a9aaa; font-size: 13px; margin-bottom: 16px; }}
  .decklist {{ background: #2e3848; padding: 12px; border-radius: 6px;
               font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap; }}
  .matchup {{ background: #2e3848; padding: 10px 14px; border-radius: 6px;
              margin-bottom: 12px; border-left: 4px solid #65bcd5; }}
  .diff {{ font-weight: bold; font-size: 11px; padding: 2px 8px; border-radius: 3px; }}
  .notes {{ color: #8a9aaa; font-style: italic; font-size: 12px; }}
  @media print {{
    body {{ background: white; color: black; }}
    .decklist, .matchup {{ background: #f5f5f5; border-color: #333; }}
    h1, h2, h3 {{ color: #333; }}
  }}
</style>
</head><body>
<h1>{name}</h1>
<div class="meta">{fmt} &bull; {arch}{(' &bull; ' + notes) if notes else ''}</div>
"""]

    # Decklist
    main_ct = sum(main.values())
    side_ct = sum(side.values())
    parts.append(f'<h2>Decklist ({main_ct} main / {side_ct} side)</h2>\n<div class="decklist">')
    for card, qty in sorted(main.items()):
        parts.append(f"{qty} {card}\n")
    if side:
        parts.append("\nSideboard\n")
        for card, qty in sorted(side.items()):
            parts.append(f"{qty} {card}\n")
    parts.append("</div>\n")

    # Sideboard plans
    if plans:
        parts.append(f"<h2>Sideboard Guide ({len(plans)} matchups)</h2>\n")
        for p in plans:
            opp  = p.get("opponent_archetype", "Unknown")
            diff = p.get("difficulty", "Medium")
            dc   = _DIFF_COLORS.get(diff, "#f58231")
            pn   = p.get("notes", "")

            parts.append(f'<div class="matchup">\n')
            parts.append(f'<b>{opp}</b> <span class="diff" style="color:{dc};">[{diff}]</span><br>\n')

            play_in  = p.get("play_in", [])
            play_out = p.get("play_out", [])
            draw_in  = p.get("draw_in", [])
            draw_out = p.get("draw_out", [])

            has_play_draw = play_in or play_out or draw_in or draw_out
            if has_play_draw:
                parts.append('<b>On the Play:</b><br>\n')
                parts.append(_card_list_html(play_in, "IN", "#3cb44b"))
                parts.append(_card_list_html(play_out, "OUT", "#e6194b"))
                parts.append('<b>On the Draw:</b><br>\n')
                parts.append(_card_list_html(draw_in, "IN", "#3cb44b"))
                parts.append(_card_list_html(draw_out, "OUT", "#e6194b"))
            else:
                parts.append('<span class="notes">No play/draw split saved.</span><br>\n')

            if pn:
                parts.append(f'<div class="notes">{pn}</div>\n')
            parts.append("</div>\n")
    else:
        parts.append('<h2>Sideboard Guide</h2>\n<p class="notes">No sideboard plans saved yet. '
                     'Create them in the Event Optimizer tab.</p>\n')

    parts.append("</body></html>")
    return "".join(parts)
