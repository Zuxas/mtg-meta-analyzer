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
import re

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
from gui.state import UIState
from gui.state_keys import MY_DECKS_SELECTED_DECK_ID

_FORMATS = ["standard", "pioneer", "modern", "legacy"]

# Matches the "<Archetype> (auto-imported YYYY-MM-DD)" suffix that
# analysis/auto_save_deck.py appends to a deck's DB `name` when it
# auto-creates a saved deck from an unrecognized MTGA match. GR-6 (e):
# this is display-only -- the raw name (with suffix) stays exactly as
# stored; only the rendered table/header text drops the suffix in favor
# of a small secondary badge.
_AUTO_IMPORT_RE = re.compile(
    r"^(.*?)\s*\(auto-imported\s+(\d{4}-\d{2}-\d{2})\)\s*$", re.IGNORECASE
)


def _split_auto_imported(name: str) -> tuple[str, str | None]:
    """Split '<name> (auto-imported YYYY-MM-DD)' into (display_name, date).
    Returns (name, None) unchanged if the suffix isn't present. Callers
    MUST keep using the original raw `name` for anything that reaches the
    DB (save_deck/delete_deck/_DeckDialog prefill/...) -- this is a
    render-time-only split."""
    m = _AUTO_IMPORT_RE.match(name or "")
    if not m:
        return (name or "", None)
    return (m.group(1).strip(), m.group(2))


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
        self.setMinimumSize(*theme.DIALOG_SM)
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
        self.setMinimumSize(*theme.DIALOG_SM)
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
        self._pending_select_id = None  # for deferred deck pre-select after table loads
        self._hydrated_state = False  # sticky state hydration guard
        self._build_ui()
        QTimer.singleShot(200, self._load_decks)

    def cleanup(self):
        """Stop running workers. Called by MainWindow on app exit."""
        from gui.worker_utils import stop_worker
        for w in self._workers:
            stop_worker(w)
        self._workers.clear()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        root.setSpacing(theme.SPACE_XS)

        from gui.widgets.summary_bar import SummaryBar
        self._summary_bar = SummaryBar()
        root.addWidget(self._summary_bar)

        outer = QHBoxLayout()
        root.addLayout(outer, 1)

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
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Format", "Archetype", "Cards", "Legal"])
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
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.clicked.connect(self._on_deck_clicked)
        lv.addWidget(self._table, 1)

        self._empty_state = theme.empty_state_label(
            "No saved decks yet",
            "Click <b>+ Add Deck</b> below to paste your first list "
            "(Arena or MTGO format). Saved decks show up here and can be "
            "sent to SIMULATE or the Event Optimizer."
        )
        self._empty_state.setVisible(False)
        lv.addWidget(self._empty_state, 1)

        # Buttons
        from gui.icons_util import btn_icon
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton(btn_icon("add", color=theme.BTN_FG), "Add Deck")
        self._add_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        self._add_btn.clicked.connect(self._add_deck)
        btn_row.addWidget(self._add_btn)

        self._edit_btn = QPushButton(btn_icon("edit"), "Edit")
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._edit_deck)
        btn_row.addWidget(self._edit_btn)

        self._del_btn = QPushButton(btn_icon("delete", color=theme.ERR), "Delete")
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
        from gui.widgets.decklist_pane import DecklistPane
        dl_widget = QWidget()
        dl_layout = QVBoxLayout(dl_widget)
        dl_layout.setContentsMargins(4, 4, 4, 4)
        self._decklist_pane = DecklistPane()
        dl_layout.addWidget(self._decklist_pane, 1)

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

        # -- Sideboard Plans sub-tab (master-detail layout) --
        sb_widget = QWidget()
        sb_layout = QVBoxLayout(sb_widget)
        sb_layout.setContentsMargins(4, 4, 4, 4)
        sb_layout.setSpacing(6)

        sb_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Master: compact list (Matchup | Difficulty | Swap count)
        self._sb_table = QTableWidget()
        self._sb_table.setColumnCount(3)
        self._sb_table.setHorizontalHeaderLabels(["Matchup", "Diff", "Swaps"])
        self._sb_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._sb_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._sb_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._sb_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sb_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._sb_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._sb_table.verticalHeader().setVisible(False)
        self._sb_table.setAlternatingRowColors(True)
        self._sb_table.itemSelectionChanged.connect(self._on_sb_plan_selected)
        sb_splitter.addWidget(self._sb_table)

        # Detail: full plan view (scrollable)
        self._sb_detail = QScrollArea()
        self._sb_detail.setWidgetResizable(True)
        self._sb_detail.setFrameShape(QFrame.Shape.NoFrame)
        self._sb_detail_inner = QWidget()
        self._sb_detail_layout = QVBoxLayout(self._sb_detail_inner)
        self._sb_detail_layout.setContentsMargins(12, 10, 12, 10)
        self._sb_detail_layout.setSpacing(8)
        ph = QLabel("Select a matchup on the left to see the full IN / OUT lists and notes.")
        ph.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setWordWrap(True)
        self._sb_detail_layout.addWidget(ph)
        self._sb_detail_layout.addStretch()
        self._sb_detail.setWidget(self._sb_detail_inner)
        sb_splitter.addWidget(self._sb_detail)

        sb_splitter.setStretchFactor(0, 2)
        sb_splitter.setStretchFactor(1, 3)
        sb_layout.addWidget(sb_splitter, 1)

        # Storage for full plan dicts (parallel to _sb_table rows)
        self._sb_plans_data = []

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

        # -- Test Hand (mulligan evaluator) sub-tab --
        from gui.widgets.mulligan_evaluator import MulliganEvaluator
        self._mull_eval = MulliganEvaluator()
        self._detail_tabs.addTab(self._mull_eval, "Test Hand")

        # -- EV vs Field sub-tab --
        from gui.widgets.deck_ev_widget import DeckEvWidget
        self._deck_ev = DeckEvWidget()
        self._detail_tabs.addTab(self._deck_ev, "EV vs Field")

        # -- Match History sub-tab --
        from gui.widgets.deck_match_history import DeckMatchHistory
        self._deck_match_history = DeckMatchHistory()
        self._detail_tabs.addTab(self._deck_match_history, "Match History")

        rv.addWidget(self._detail_tabs, 1)

        splitter.addWidget(right)
        splitter.setSizes([350, 550])

        outer.addWidget(splitter)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    def _find_banned_cards(decks: list) -> dict:
        """Return {deck_id: [banned_card_names]} for any mainboard card
        banned in the deck's format. Empty list = all legal. Silently
        returns {} on DB errors so the table still loads."""
        if not decks:
            return {}
        names = set()
        for d in decks:
            names.update((d.get("mainboard") or {}).keys())
            names.update((d.get("sideboard") or {}).keys())
        if not names:
            return {}
        import json
        try:
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                placeholders = ",".join("?" * len(names))
                rows = conn.execute(
                    f"SELECT name, legalities FROM card_data "
                    f"WHERE name IN ({placeholders})",
                    list(names),
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            return {}

        legality_map = {}
        for row in rows:
            try:
                legality_map[row["name"]] = json.loads(row["legalities"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass

        result = {}
        for d in decks:
            fmt = (d.get("format") or "").lower()
            if not fmt:
                continue
            banned_here = []
            for card in (d.get("mainboard") or {}):
                status = (legality_map.get(card, {}) or {}).get(fmt)
                if status == "banned":
                    banned_here.append(card)
            for card in (d.get("sideboard") or {}):
                status = (legality_map.get(card, {}) or {}).get(fmt)
                if status == "banned" and card not in banned_here:
                    banned_here.append(card)
            if banned_here:
                result[d.get("id")] = banned_here
        return result

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

    def reload(self):
        """Re-query saved_decks + saved_sb_plans from the DB.

        Preserves the currently selected deck's SB plan view if any. Wired
        to the main-window F5 / Refresh button via MainWindow._refresh_current_tab.
        """
        # Remember which deck (if any) is selected so we can re-show its plans
        current_row = self._table.currentRow() if hasattr(self, "_table") else -1
        current_deck_id = None
        if current_row >= 0:
            item = self._table.item(current_row, 0)
            if item is not None:
                current_deck_id = item.data(Qt.ItemDataRole.UserRole)

        self._load_decks()

        if current_deck_id is not None:
            self._load_sb_plans(current_deck_id)

    def _on_decks_loaded(self, decks: list):
        self._empty_state.setVisible(not decks)
        self._table.setVisible(bool(decks))
        self._decks = decks
        banned_by_deck = self._find_banned_cards(decks)
        self._table.setRowCount(len(decks))
        for row, d in enumerate(decks):
            main = d.get("mainboard", {})
            side = d.get("sideboard", {})
            total = sum(main.values()) + sum(side.values())

            raw_name = d.get("name", "")
            display_name, auto_date = _split_auto_imported(raw_name)
            name_item = QTableWidgetItem(display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, d.get("id"))
            if auto_date:
                # GR-6e: suffix moved out of the displayed name (render-only
                # -- the DB row's `name` column is untouched) into a
                # tooltip badge so the info isn't lost, just de-emphasized.
                name_item.setToolTip(f"Auto-imported {auto_date}")
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(d.get("format", "")))

            arch_item = QTableWidgetItem(d.get("archetype", ""))
            arch_item.setForeground(QColor(theme.ACCENT))
            self._table.setItem(row, 2, arch_item)

            ct_item = QTableWidgetItem(str(total))
            ct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, ct_item)

            banned = banned_by_deck.get(d.get("id"), [])
            if banned:
                legal_item = QTableWidgetItem(f"\u26A0 {len(banned)}")
                legal_item.setForeground(QColor(theme.ERR))
                legal_item.setToolTip(
                    "Banned in " + (d.get("format") or "?").capitalize() + ":\n  "
                    + "\n  ".join(banned)
                )
            else:
                legal_item = QTableWidgetItem("\u2713")
                legal_item.setForeground(QColor(theme.OK))
                legal_item.setToolTip("All cards legal in this format.")
            legal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, legal_item)

        # Summary bar
        n = len(decks)
        formats = set(d.get("format", "") for d in decks if d.get("format"))
        stats = [f"{n} saved deck{'s' if n != 1 else ''}"]
        if formats:
            stats.append(f"Formats: {', '.join(sorted(formats))}")
        self._summary_bar.update("MY DECKS", stats)

        # Clear detail panel if selected deck was deleted
        if self._current_deck:
            ids = {d["id"] for d in decks}
            if self._current_deck.get("id") not in ids:
                self._clear_detail()

        # If a deck-id was pending from a hydrate-before-load showEvent,
        # apply it now that the table is populated.
        pending = getattr(self, "_pending_select_id", None)
        if pending is not None and self.select_deck_by_id(pending):
            self._pending_select_id = None

    # ------------------------------------------------------------------
    # Sticky state — hydrate once on first show
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_hydrated_state", False):
            return
        # Read persisted selection but defer applying it — the deck table
        # is populated asynchronously via DataLoadWorker. select_deck_by_id
        # at this point would iterate 0 rows. _on_decks_loaded consumes
        # _pending_select_id once the table has been populated.
        deck_id = UIState.instance().get(MY_DECKS_SELECTED_DECK_ID)
        if deck_id is not None:
            self._pending_select_id = deck_id
            # Try immediately in case the table is already populated
            # (e.g., user already visited the tab once and navigates back).
            if self.select_deck_by_id(deck_id):
                self._pending_select_id = None
        self._hydrated_state = True

    # ------------------------------------------------------------------
    # Deck selection
    # ------------------------------------------------------------------

    def select_deck_by_id(self, deck_id: int) -> bool:
        """Select the deck row matching deck_id. Returns True if found.

        Used by MainWindow.open_saved_deck (palette deck-jump) and showEvent
        hydration to programmatically activate a saved deck by its DB id.
        """
        if not hasattr(self, "_table"):
            return False
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == deck_id:
                self._table.setCurrentCell(i, 0)
                # Reuse the existing click handler to trigger full detail panel
                self._on_deck_clicked(self._table.model().index(i, 0))
                return True
        return False

    def _on_deck_clicked(self, index):
        row = index.row()
        if row < 0 or row >= len(self._decks):
            return
        deck = self._decks[row]
        self._current_deck = deck
        self._show_deck(deck)
        if hasattr(self, "_mull_eval"):
            self._mull_eval.set_deck(deck)
        if hasattr(self, "_deck_ev"):
            self._deck_ev.set_deck(deck)
        if hasattr(self, "_deck_match_history"):
            self._deck_match_history.set_deck(deck.get("id"))
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
        # Persist selected deck so it can be restored on next session/tab-show
        deck_id = deck.get("id")
        if deck_id is not None:
            UIState.instance().set(MY_DECKS_SELECTED_DECK_ID, deck_id)

    def _show_deck(self, deck):
        raw_name = deck.get("name", "Unnamed")
        display_name, auto_date = _split_auto_imported(raw_name)
        arch = deck.get("archetype", "")
        fmt  = deck.get("format", "")
        main = deck.get("mainboard", {})
        side = deck.get("sideboard", {})

        self._header.setText(display_name)
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
        if auto_date:
            # Secondary badge segment -- the "(auto-imported <date>)" info
            # moved out of the deck name itself (GR-6e), still surfaced
            # here so provenance isn't lost, just de-emphasized.
            parts.append(f"Auto-imported {auto_date}")
        self._meta_lbl.setText("  \u2022  ".join(parts))

        self._decklist_pane.set_deck(deck)

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
        self._sb_plans_data = plans
        self._sb_table.setRowCount(len(plans))
        diff_colors = {"Easy": theme.OK, "Medium": theme.WARN, "Hard": theme.ERR}
        for row, p in enumerate(plans):
            opp = p.get("opponent_archetype", "")
            diff = p.get("difficulty", "Medium")
            play_in  = p.get("play_in", [])
            play_out = p.get("play_out", [])
            draw_in  = p.get("draw_in", [])
            draw_out = p.get("draw_out", [])

            # Col 0: matchup name
            name_item = QTableWidgetItem(opp)
            if (p.get("notes", "") or "").strip():
                name_item.setToolTip("Has notes \u2014 select to view in detail panel")
            self._sb_table.setItem(row, 0, name_item)

            # Col 1: difficulty (colored, centered)
            diff_item = QTableWidgetItem(diff)
            diff_item.setForeground(QColor(diff_colors.get(diff, theme.TEXT)))
            diff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sb_table.setItem(row, 1, diff_item)

            # Col 2: swap count with imbalance warning
            p_swap = max(len(play_in), len(play_out))
            d_swap = max(len(draw_in), len(draw_out))
            same = (play_in == draw_in and play_out == draw_out)
            if same:
                swap_text = f"\u00b1{p_swap}"
            else:
                swap_text = f"P\u00b1{p_swap}  D\u00b1{d_swap}"
            imb = (len(play_in) != len(play_out)) or (len(draw_in) != len(draw_out))
            if imb:
                swap_text = "\u26a0 " + swap_text
            swap_item = QTableWidgetItem(swap_text)
            swap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if imb:
                swap_item.setForeground(QColor(theme.WARN))
                swap_item.setToolTip(
                    f"Plan is imbalanced: cards IN \u2260 cards OUT "
                    f"({len(play_in)}/{len(play_out)} P, "
                    f"{len(draw_in)}/{len(draw_out)} D). Tournament-legal SB requires equal counts."
                )
            self._sb_table.setItem(row, 2, swap_item)

        # Clear / reset detail panel
        self._render_sb_detail(None)

    # ------------------------------------------------------------------
    # SB plans \u2014 detail panel rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _consolidate_cards(cards: list) -> list:
        """[A, A, B, A] -> [(3, 'A'), (1, 'B')] preserving first-seen order."""
        counts = {}
        order = []
        for c in cards:
            if c not in counts:
                order.append(c)
            counts[c] = counts.get(c, 0) + 1
        return [(counts[c], c) for c in order]

    def _on_sb_plan_selected(self):
        row = self._sb_table.currentRow()
        if 0 <= row < len(self._sb_plans_data):
            self._render_sb_detail(self._sb_plans_data[row])
        else:
            self._render_sb_detail(None)

    def _render_sb_detail(self, plan):
        """Rebuild the right-hand detail panel for the selected plan."""
        # Clear existing widgets
        while self._sb_detail_layout.count():
            item = self._sb_detail_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if plan is None:
            ph = QLabel("Select a matchup on the left to see full IN / OUT lists and notes.")
            ph.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setWordWrap(True)
            self._sb_detail_layout.addWidget(ph)
            self._sb_detail_layout.addStretch()
            return

        opp      = plan.get("opponent_archetype", "")
        diff     = plan.get("difficulty", "Medium")
        play_in  = plan.get("play_in", [])
        play_out = plan.get("play_out", [])
        draw_in  = plan.get("draw_in", [])
        draw_out = plan.get("draw_out", [])
        notes    = (plan.get("notes", "") or "").strip()

        # Header: matchup name + difficulty pill
        diff_colors = {"Easy": theme.OK, "Medium": theme.WARN, "Hard": theme.ERR}
        pill_color  = diff_colors.get(diff, theme.TEXT_DIM)
        header = QHBoxLayout()
        title = QLabel(opp)
        title.setStyleSheet(f"color: {theme.ACCENT}; font-size: 15px; font-weight: 600;")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        pill = QLabel(diff.upper())
        pill.setStyleSheet(
            f"color: {pill_color}; background: {theme.PANEL}; "
            f"border: 1px solid {pill_color}; border-radius: 9px; "
            f"padding: 2px 10px; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        pill.setFixedHeight(22)
        header.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        header_wrap = QWidget()
        header_wrap.setLayout(header)
        self._sb_detail_layout.addWidget(header_wrap)

        # Imbalance warning row
        p_imb = len(play_in) - len(play_out)
        d_imb = len(draw_in) - len(draw_out)
        if p_imb != 0 or d_imb != 0:
            parts = []
            if p_imb != 0:
                parts.append(f"play {p_imb:+d}")
            if d_imb != 0:
                parts.append(f"draw {d_imb:+d}")
            warn = QLabel(f"\u26a0  Imbalanced ({'; '.join(parts)}) \u2014 cards in must equal cards out for tournament legality.")
            warn.setStyleSheet(
                f"color: {theme.WARN}; background: {theme.WARN_BG}; "
                f"border: 1px solid {theme.WARN}; border-radius: 4px; "
                f"padding: 4px 8px; font-size: 11px;"
            )
            warn.setWordWrap(True)
            self._sb_detail_layout.addWidget(warn)

        # Play section
        self._sb_detail_layout.addWidget(self._make_sb_section("ON THE PLAY", play_in, play_out))

        # Draw section: collapse if identical to play
        same_as_play = (play_in == draw_in and play_out == draw_out)
        if same_as_play and (draw_in or draw_out):
            same_lbl = QLabel("ON THE DRAW \u2014 same plan as on the play.")
            same_lbl.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 11px; font-style: italic; "
                f"padding-top: 8px; padding-bottom: 4px;"
            )
            self._sb_detail_layout.addWidget(same_lbl)
        elif draw_in or draw_out:
            self._sb_detail_layout.addWidget(self._make_sb_section("ON THE DRAW", draw_in, draw_out))

        # Notes section
        if notes:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"background: {theme.BORDER}; max-height: 1px;")
            self._sb_detail_layout.addWidget(sep)

            notes_hdr = QLabel("NOTES")
            notes_hdr.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 700; "
                f"letter-spacing: 1.5px; padding-top: 4px;"
            )
            self._sb_detail_layout.addWidget(notes_hdr)

            notes_text = QTextEdit()
            notes_text.setPlainText(notes)
            notes_text.setReadOnly(True)
            notes_text.setStyleSheet(
                f"background: {theme.PANEL}; color: {theme.TEXT}; "
                f"border: 1px solid {theme.BORDER}; border-radius: 4px; "
                f"font-size: 11px; padding: 6px;"
            )
            # Sized to content (60-300px)
            h = min(300, max(60, notes.count("\n") * 16 + 50))
            notes_text.setFixedHeight(h)
            self._sb_detail_layout.addWidget(notes_text)

        self._sb_detail_layout.addStretch()

    def _make_sb_section(self, title: str, in_cards: list, out_cards: list) -> QWidget:
        """One section (Play or Draw) with IN/OUT side-by-side columns."""
        section = QWidget()
        sl = QVBoxLayout(section)
        sl.setContentsMargins(0, 8, 0, 0)
        sl.setSpacing(4)

        hdr = QLabel(title)
        hdr.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;"
        )
        sl.addWidget(hdr)

        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(self._make_card_column("IN",  in_cards,  theme.OK,  "+"), 1)
        cols.addWidget(self._make_card_column("OUT", out_cards, theme.ERR, "\u2212"), 1)
        sl.addLayout(cols)
        return section

    def _make_card_column(self, label: str, cards: list, color: str, sign: str) -> QWidget:
        """One IN or OUT column with consolidated card counts + card-image tooltips."""
        from gui.widgets.card_tooltip import install_card_tooltip

        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)

        head = QLabel(f"<b style='color:{color};'>{label}</b> "
                      f"<span style='color:{theme.TEXT_DIM};'>({sign}{len(cards)})</span>")
        head.setStyleSheet("font-size: 11px;")
        cl.addWidget(head)

        consolidated = self._consolidate_cards(cards)
        if not consolidated:
            empty = QLabel("(none)")
            empty.setStyleSheet(f"color: {theme.TEXT_DIM}; font-style: italic; font-size: 11px;")
            cl.addWidget(empty)
            cl.addStretch()
            return col

        t = QTableWidget()
        t.setRowCount(len(consolidated))
        t.setColumnCount(2)
        t.horizontalHeader().setVisible(False)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)
        t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t.setStyleSheet(
            f"QTableWidget {{ background: transparent; border: none; font-size: 11px; }}"
            f"QTableWidget::item {{ padding: 0px 2px; }}"
        )
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        for r, (qty, card) in enumerate(consolidated):
            qty_item = QTableWidgetItem(f"{qty}\u00d7")
            qty_item.setForeground(QColor(color))
            qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            qty_font = QFont()
            qty_font.setBold(True)
            qty_item.setFont(qty_font)
            t.setItem(r, 0, qty_item)
            t.setItem(r, 1, QTableWidgetItem(card))

        t.resizeRowsToContents()
        row_h = max(18, t.rowHeight(0)) if consolidated else 20
        t.setFixedHeight(row_h * len(consolidated) + 4)

        install_card_tooltip(t, card_name_column=1)
        cl.addWidget(t)
        return col

    def _clear_detail(self):
        self._current_deck = None
        self._header.setText("Select a deck to view details")
        self._meta_lbl.setText("")
        self._decklist_pane.clear()
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


def _consolidate(cards: list) -> str:
    """[A, A, B, A] -> '3× A, 1× B' preserving first-seen order."""
    counts: dict = {}
    order: list = []
    for c in cards:
        if c not in counts:
            order.append(c)
        counts[c] = counts.get(c, 0) + 1
    return ", ".join(
        f"{counts[c]}× {c}" if counts[c] > 1 else c for c in order
    )


# Per-archetype mulligan rules. Keyed by deck archetype string (case-
# insensitive substring match). Falls back to _GENERIC_MULL_RULES if no
# entry matches. Originally hardcoded with Izzet Prowess content from
# the Worldly Council primer, which leaked onto every deck's export.
_IZZET_PROWESS_MULL_RULES = """
<b>One-landers:</b> on the draw, double-cantrip hand is 95% to hit land 2; single-cantrip 86%. On the play, you spend turn 1 cantripping so the math is worse — be choosier.<br>
<b>Mirror & Spellementals:</b> cantrip-heavy hands are best; bottom-most-of-range, a hand with no cantrips needs to be very good. Stormchaser's Talent is the best card to have in your opening on the play.<br>
<b>vs Landfall:</b> don't keep one-landers liberally — you need to impact the board, not dig for lands. Must kill turn-one Llanowar Elves on the draw.<br>
<b>Threat-less hands:</b> keepable IF you have a way to pull ahead (Flow State to find threats, Steaming Sauna fallback). Burst Lightning vs Sapling Nursery is dead.<br>
<b>Resource discipline:</b> cantrips are a resource. Ask "what do I want to find?" If it's a common card (land 3), wait to dig naturally and preserve selection late.
""".strip()

_ESPER_BLINK_MULL_RULES = """
<b>Auto-keeps:</b> Phelia + Solitude/Ephemerate + 2-3 lands. Thoughtseize + interaction + 2 lands on the play vs unknown. Riddler + Overlord + 3 lands with any 1MV play.<br>
<b>Interaction density:</b> need at least one piece of MD interaction (Battle / Solitude / Thoughtseize / Prismatic) in every 7. Hands with zero interaction mulligan against unknown opponents — this deck plays reactive, not proactive.<br>
<b>vs combo (Belcher / Storm / Titan / Living End / Goryo's):</b> mull aggressively for Thoughtseize + cheap interaction. 1MV plays beat 4MV value. Don't keep 7s with 3+ five-drops.<br>
<b>vs aggro (Energy / Zoo / Affinity / Prowess):</b> mull for Battle + early defensive plays. Bowmasters on T2 is a snap-keep enabler. Phelia + removal stabilizes.<br>
<b>vs control / mirror:</b> Thoughtseize is gold — keep info hands. Riddler + Overlord wins long games. Don't mulligan into 5 — control loves your draw step.<br>
<b>One-landers:</b> only with Solitude pitch + Witch Enchanter cycle, or 2 cantrip lands (Meticulous Archive / Shadowy Backstreet / Undercity Sewers / Bleachbone Verge) — those count as half-spells.<br>
<b>Solitude math:</b> need 1 other white card to pitch. If your only white is Solitude itself, treat it as a 6-mana spell, not free interaction.
""".strip()

_GENERIC_MULL_RULES = """
<b>Lands:</b> keep 2-5 lands in 7-card hands; 2-4 in 6; 2-3 in 5. One-landers only with cheap card selection or a way to find a second land.<br>
<b>Interaction:</b> at least one piece of removal or disruption in every 7 vs unknown opponents. Threat-only hands are mulligans against combo and control.<br>
<b>Curve:</b> mulligan hands with no plays before turn 4, or hands with 3+ five-drops. Reactive decks need cheap reactive cards.<br>
<b>vs aggro:</b> mull for early interaction; threat-light is fine if you can stabilize.<br>
<b>vs combo:</b> mull for hand disruption + counters/answers; pure value hands lose.<br>
<b>vs control:</b> mull for threats + protection or proactive disruption; pure reactive hands get out-carded.
""".strip()

# Order matters: longer / more specific keys first.
_ARCHETYPE_MULL_RULES: dict[str, str] = {
    "esper blink":   _ESPER_BLINK_MULL_RULES,
    "esper flicker": _ESPER_BLINK_MULL_RULES,
    "izzet prowess": _IZZET_PROWESS_MULL_RULES,
}


def _mull_rules_for(archetype: str | None) -> str:
    """Return mulligan rules HTML for the given archetype, falling back
    to generic rules if no archetype-specific block is registered."""
    if not archetype:
        return _GENERIC_MULL_RULES
    key = archetype.strip().lower()
    for k, v in _ARCHETYPE_MULL_RULES.items():
        if k in key:
            return v
    return _GENERIC_MULL_RULES


# Backward-compat alias for any external callers that imported the old name.
_GENERAL_MULL_RULES = _GENERIC_MULL_RULES


_PLAN_MARKER_RE = None  # lazy compiled below


def _summarize_notes(text: str, max_len: int = 170) -> str:
    """
    Compress primer prose to a short TL;DR line for the 1-page SB guide.

    Strategy:
      1. Strip anything after a '---' separator (older 'Prior notes:'
         appendage from backfill_prowess_primer_notes.py).
      2. If a 'PLAN:' marker exists, lift the sentence after it.
      3. Otherwise take the first complete sentence (or clause) and cap
         at max_len chars, ending on a word boundary.
      4. Collapse whitespace; no embedded line breaks in the output.
    """
    import re
    global _PLAN_MARKER_RE
    if _PLAN_MARKER_RE is None:
        _PLAN_MARKER_RE = re.compile(
            r"\bPLAN\s*:\s*(.+?)(?:\n\n|\Z)", re.DOTALL | re.IGNORECASE
        )

    if not text:
        return ""
    body = text.split("---", 1)[0].strip()
    if not body:
        return ""

    m = _PLAN_MARKER_RE.search(body)
    if m:
        body = m.group(1).strip()

    # Single-line
    flat = re.sub(r"\s+", " ", body).strip()
    if not flat:
        return ""

    if len(flat) <= max_len:
        return flat

    # Prefer cutting at sentence boundary inside max_len.
    window = flat[:max_len]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut >= 60:
        return window[:cut + 1]
    # Fallback: cut at last word boundary, add ellipsis.
    word_cut = window.rfind(" ")
    if word_cut >= 60:
        return window[:word_cut] + "…"
    return window + "…"


def _generate_sb_print_html(deck: dict, plans: list[dict]) -> str:
    """Generate a print-friendly HTML: general mulligan rules at top,
    per-matchup play patterns + SB swaps in a two-column grid.
    Fits on one printed page -- notes are TL;DR-summarized via
    _summarize_notes (full prose lives in the SB Plans tab)."""
    name = deck.get("name", "Deck")
    fmt  = deck.get("format", "").capitalize()
    arch = deck.get("archetype", "")

    # Sort: Easy → Hard so the rough matchups are at the bottom (where you
    # have time to read carefully); easy matchups quick to scan at top.
    diff_rank = {"Easy": 0, "Medium": 1, "Hard": 2}
    plans = sorted(
        plans,
        key=lambda p: (diff_rank.get(p.get("difficulty", "Medium"), 1),
                       (p.get("opponent_archetype") or "").lower()),
    )

    parts = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{name} — Play & SB Guide</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 10px; color: #1a1a1a; line-height: 1.35; }}
  h1 {{ font-size: 16px; margin: 0 0 4px 0; border-bottom: 2px solid #333; padding-bottom: 3px; }}
  h2 {{ font-size: 12px; margin: 10px 0 4px 0; color: #444; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; }}
  .meta {{ color: #666; font-size: 11px; margin-bottom: 8px; }}
  .mull {{ background: #f5f3eb; border-left: 3px solid #b87800; padding: 6px 10px; font-size: 11px; margin-bottom: 10px; break-inside: avoid; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
  .mu {{ border: 1px solid #aaa; border-radius: 4px; padding: 6px 8px; font-size: 11px; break-inside: avoid; }}
  .mu-name {{ font-weight: bold; font-size: 12px; margin-bottom: 3px; }}
  .diff {{ font-size: 10px; font-weight: bold; padding: 1px 6px; border-radius: 8px; }}
  .easy   {{ color: #2a7a2a; background: #e6f5e6; border: 1px solid #2a7a2a; }}
  .medium {{ color: #b87800; background: #fbf3e0; border: 1px solid #b87800; }}
  .hard   {{ color: #c22;    background: #fbe6e6; border: 1px solid #c22; }}
  .sb-line {{ font-size: 11px; margin: 2px 0; }}
  .in  {{ color: #1a7a1a; font-weight: 600; }}
  .out {{ color: #c22;   font-weight: 600; }}
  .notes {{ color: #333; font-size: 10.5px; margin-top: 5px; padding-top: 4px; border-top: 1px dashed #ccc; }}
  @media print {{
    body {{ margin: 0; }} .grid {{ gap: 6px; }}
    .mu {{ border: 1px solid #999; padding: 4px 6px; }}
    .mull {{ break-after: avoid; }}
  }}
</style>
</head><body>
<h1>{name}</h1>
<div class="meta">{fmt} &bull; {arch} &bull; {len(plans)} matchups</div>

<h2>General mulligan rules</h2>
<div class="mull">{_mull_rules_for(arch)}</div>

<h2>Per-matchup play patterns + SB swaps</h2>
<div class="grid">
"""]

    for p in plans:
        opp  = p.get("opponent_archetype", "?")
        diff = p.get("difficulty", "Medium")
        dc   = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}.get(diff, "medium")
        pn   = (p.get("notes", "") or "").strip()
        play_in  = p.get("play_in", [])
        play_out = p.get("play_out", [])
        draw_in  = p.get("draw_in", [])
        draw_out = p.get("draw_out", [])

        parts.append('<div class="mu">')
        parts.append(
            f'<div class="mu-name">{opp} '
            f'<span class="diff {dc}">{diff.upper()}</span></div>'
        )

        same_pd = (play_in == draw_in and play_out == draw_out)

        if play_in or play_out:
            label = "Play+Draw" if same_pd else "Play"
            parts.append(f'<div class="sb-line"><b>{label}:</b> ')
            if play_in:
                parts.append(f'<span class="in">+ {_consolidate(play_in)}</span>')
            if play_in and play_out:
                parts.append('&nbsp;&nbsp; ')
            if play_out:
                parts.append(f'<span class="out">− {_consolidate(play_out)}</span>')
            parts.append('</div>')

        if (draw_in or draw_out) and not same_pd:
            parts.append('<div class="sb-line"><b>Draw:</b> ')
            if draw_in:
                parts.append(f'<span class="in">+ {_consolidate(draw_in)}</span>')
            if draw_in and draw_out:
                parts.append('&nbsp;&nbsp; ')
            if draw_out:
                parts.append(f'<span class="out">− {_consolidate(draw_out)}</span>')
            parts.append('</div>')

        if not (play_in or play_out or draw_in or draw_out):
            parts.append('<div class="sb-line"><i>No swaps (matchup is even, '
                         'or plan not entered).</i></div>')

        # Notes -- TL;DR summary only (full prose lives in SB Plans tab).
        # Long primer prose (post-backfill) would otherwise blow out the
        # 1-page printer-friendly target.
        if pn:
            summary = _summarize_notes(pn)
            if summary:
                parts.append(f'<div class="notes">{summary}</div>')

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
  h1 {{ color: #5eb5cf; border-bottom: 2px solid #5eb5cf; padding-bottom: 8px; }}
  h2 {{ color: #5eb5cf; margin-top: 24px; }}
  h3 {{ color: #bfef45; margin-top: 16px; margin-bottom: 4px; }}
  .meta {{ color: #8a9aaa; font-size: 13px; margin-bottom: 16px; }}
  .decklist {{ background: #1f2133; padding: 12px; border-radius: 6px;
               font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap; }}
  .matchup {{ background: #1f2133; padding: 10px 14px; border-radius: 6px;
              margin-bottom: 12px; border-left: 4px solid #5eb5cf; }}
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
