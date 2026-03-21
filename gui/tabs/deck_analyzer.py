"""
Tab 2 — Deck Analyzer
Paste any decklist in Arena export format, run Blunder Detection +
Chapin Principles evaluation, see results side-by-side.
"""
import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QComboBox, QFrame, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont


# ------------------------------------------------------------------
# Decklist parser
# ------------------------------------------------------------------

def parse_arena_decklist(text: str):
    """
    Parse an Arena export decklist.
    Handles:  "4 Lightning Bolt", "4x Lightning Bolt",
              "(BLB) 123" set/collector suffixes stripped.
    Returns (mainboard, sideboard) as {name: quantity} dicts.
    """
    main, side = {}, {}
    section = main
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low in ("deck", "commander"):
            section = main
            continue
        if low == "sideboard":
            section = side
            continue
        m = re.match(r'^(\d+)x?\s+(.+)', line)
        if m:
            qty  = int(m.group(1))
            name = m.group(2).strip()
            # Strip Arena set/collector suffixes: " (BLB) 123"
            name = re.sub(r'\s+\(\w+\)\s+\d+.*$', '', name).strip()
            if name:
                section[name] = section.get(name, 0) + qty
    return main, side


# ------------------------------------------------------------------
# Background worker
# ------------------------------------------------------------------

class _AnalyzeWorker(QThread):
    blunder_done = pyqtSignal(object)
    chapin_done  = pyqtSignal(object)
    error        = pyqtSignal(str)

    def __init__(self, mainboard, sideboard, format_name, archetype, parent=None):
        super().__init__(parent)
        self._main  = mainboard
        self._side  = sideboard
        self._fmt   = format_name
        self._arch  = archetype

    def run(self):
        try:
            from analysis.blunders import analyze_deck
            from analysis.chapin   import evaluate_deck
            blunder = analyze_deck(self._main, self._side, self._fmt, self._arch)
            self.blunder_done.emit(blunder)
            chapin = evaluate_deck(self._main, self._side, self._fmt, self._arch)
            self.chapin_done.emit(chapin)
        except Exception as e:
            self.error.emit(str(e))


# ------------------------------------------------------------------
# Tab widget
# ------------------------------------------------------------------

_SEV_COLORS = {"Major": "#e6194b", "Moderate": "#f58231", "Minor": "#bfef45"}
_PRINCIPLES  = ["Threats", "Answers", "Consistency", "Velocity", "Mana", "Clock"]


class DeckAnalyzerTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Top controls ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(120)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Archetype:"))
        self._arch = QLineEdit()
        self._arch.setPlaceholderText("optional label, e.g. Izzet Prowess")
        self._arch.setFixedWidth(210)
        ctrl.addWidget(self._arch)

        self._analyze_btn = QPushButton("Analyze Deck")
        self._analyze_btn.setStyleSheet(
            "QPushButton { background: #00bcd4; color: #0a0e1a; border: none; "
            "padding: 5px 16px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #00ddf0; }"
            "QPushButton:disabled { background: #2a2a4e; color: #555; }"
        )
        self._analyze_btn.clicked.connect(self._run)
        ctrl.addWidget(self._analyze_btn)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888888;")
        ctrl.addWidget(self._status)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── Horizontal splitter: input | results ─────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: decklist input
        left = QFrame()
        lv   = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        lv.addWidget(QLabel("Paste decklist (Arena export format):"))
        self._deck_input = QPlainTextEdit()
        self._deck_input.setPlaceholderText(
            "Deck\n4 Lightning Bolt\n4 Monastery Swiftspear\n"
            "...\n\nSideboard\n2 Negate\n3 Mystical Dispute\n..."
        )
        self._deck_input.setFont(QFont("Consolas", 10))
        lv.addWidget(self._deck_input)
        splitter.addWidget(left)

        # Right: results
        right = QFrame()
        rv    = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(8)

        # Blunder section
        blunder_hdr = QLabel("Blunder Detection")
        blunder_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rv.addWidget(blunder_hdr)

        self._blunder_table = QTableWidget(0, 3)
        self._blunder_table.setHorizontalHeaderLabels(["Severity", "Category", "Issue"])
        self._blunder_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._blunder_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._blunder_table.setAlternatingRowColors(True)
        self._blunder_table.verticalHeader().setVisible(False)
        self._blunder_table.setMaximumHeight(200)
        rv.addWidget(self._blunder_table)

        self._score_lbl = QLabel("\u2014")
        self._score_lbl.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        rv.addWidget(self._score_lbl)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #2a2a4e;")
        rv.addWidget(div)

        # Chapin section
        chapin_hdr = QLabel("Chapin Principles")
        chapin_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rv.addWidget(chapin_hdr)

        self._chapin_bars: dict = {}
        for p in _PRINCIPLES:
            row_layout = QHBoxLayout()
            lbl = QLabel(f"{p}:")
            lbl.setFixedWidth(92)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("")          # we'll show score in the separate label
            bar.setStyleSheet(
                "QProgressBar { border: 1px solid #1e3a4a; border-radius: 3px; "
                "background: #101525; height: 18px; }"
                "QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #007a8a, stop:1 #00bcd4); border-radius: 2px; }"
            )
            score_lbl = QLabel("\u2014")
            score_lbl.setFixedWidth(36)
            score_lbl.setAlignment(Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(lbl)
            row_layout.addWidget(bar, 1)
            row_layout.addWidget(score_lbl)
            rv.addLayout(row_layout)
            self._chapin_bars[p] = (bar, score_lbl)

        self._overall_lbl = QLabel("")
        self._overall_lbl.setStyleSheet(
            "color: #cccccc; font-size: 12px; margin-top: 4px;"
        )
        self._overall_lbl.setWordWrap(True)
        rv.addWidget(self._overall_lbl)
        rv.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([360, 460])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _run(self):
        text = self._deck_input.toPlainText().strip()
        if not text:
            self._status.setText("Paste a decklist first.")
            return
        main, side = parse_arena_decklist(text)
        if not main:
            self._status.setText("Could not parse decklist — use Arena export format.")
            return

        fmt  = self._fmt.currentText()
        arch = self._arch.text().strip() or "Pasted Deck"
        total = sum(main.values())
        self._status.setText(f"Analyzing {total} cards\u2026")
        self._analyze_btn.setEnabled(False)
        self._clear_results()

        self._worker = _AnalyzeWorker(main, side, fmt, arch)
        self._worker.blunder_done.connect(self._show_blunder)
        self._worker.chapin_done.connect(self._show_chapin)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(
            lambda: self._analyze_btn.setEnabled(True)
        )
        self._worker.start()

    def _clear_results(self):
        self._blunder_table.setRowCount(0)
        self._score_lbl.setText("\u2014")
        self._overall_lbl.setText("")
        for bar, lbl in self._chapin_bars.values():
            bar.setValue(0)
            lbl.setText("\u2014")

    def _show_blunder(self, report):
        issues = getattr(report, "issues", [])
        self._blunder_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            sev  = getattr(issue, "severity", "")
            cat  = getattr(issue, "category", "")
            desc = getattr(issue, "description", "")

            sev_item = QTableWidgetItem(sev)
            color    = _SEV_COLORS.get(sev, "#aaaaaa")
            sev_item.setForeground(QColor(color))
            sev_item.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            self._blunder_table.setItem(row, 0, sev_item)
            self._blunder_table.setItem(row, 1, QTableWidgetItem(cat))
            self._blunder_table.setItem(row, 2, QTableWidgetItem(desc))

        score   = getattr(report, "blunder_score",        0)
        quality = getattr(report, "construction_quality", "")
        main_ct = getattr(report, "mainboard_count",      0)
        side_ct = getattr(report, "sideboard_count",      0)
        self._score_lbl.setText(
            f"Score: {score} pts  |  Quality: {quality}  |  "
            f"{main_ct} main / {side_ct} side"
        )
        self._status.setText("Blunder analysis complete.")

    def _show_chapin(self, report):
        for ps in getattr(report, "scores", []):
            name  = getattr(ps, "name",  "")
            score = getattr(ps, "score", 0.0)
            if name in self._chapin_bars:
                bar, lbl = self._chapin_bars[name]
                bar.setValue(int(score * 10))
                lbl.setText(f"{score:.1f}")

        overall = getattr(report, "overall_score",   0.0)
        rating  = getattr(report, "overall_rating",  "")
        rec     = getattr(report, "recommendation",  "")
        self._overall_lbl.setText(
            f"Overall: {overall:.1f}/10  [{rating}]\n{rec}"
        )
        self._status.setText("Analysis complete.")

    def _on_error(self, msg):
        self._status.setText(f"Error: {msg}")
        self._analyze_btn.setEnabled(True)
