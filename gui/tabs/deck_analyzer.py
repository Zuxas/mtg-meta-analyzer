"""
Tab 2 — Deck Analyzer
Paste any decklist in Arena export format, run Blunder Detection +
Chapin Principles evaluation, see results side-by-side.

"Load avg deck" row lets you pick any archetype from the DB and populate
the text box with its average decklist, ready to analyze or export.
"""
import re
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QComboBox, QFrame, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import gui.theme as theme
from gui.worker_threads import DataLoadWorker


# ------------------------------------------------------------------
# Decklist parser
# ------------------------------------------------------------------

def parse_arena_decklist(text: str):
    """
    Parse a decklist in any common tournament/client export format.

    Section headers recognised (case-insensitive, leading // or trailing : ok):
      Mainboard  : "Deck", "Commander"
      Sideboard  : "Sideboard", "Sideboard:", "SIDEBOARD:", "SB:",
                   "// Sideboard", "// SB"
      Inline SB  : "SB: 2 Negate"  (prefix form used by some tools)

    Blank-line fallback: when NO explicit sideboard marker is present in the
    text, a blank line between two card groups is treated as the main/side
    boundary (standard MTGO copy-paste without the 'Sideboard' header).

    Card lines: "4 Lightning Bolt", "4x Lightning Bolt",
                "4 Lightning Bolt (M11) 149"  — set/collector suffix stripped.

    Returns (mainboard, sideboard) as {name: quantity} dicts.
    """
    _SIDE_KEYWORDS = {"sideboard", "sideboard:", "sb:", "// sideboard", "// sb"}
    _MAIN_KEYWORDS = {"deck", "commander"}

    lines = text.splitlines()

    # Decide whether a blank line should act as main→side boundary.
    # Only use blank-line fallback when there is no explicit sideboard marker.
    has_explicit_side = any(
        l.strip().lower() in _SIDE_KEYWORDS
        or l.strip().lower().startswith("// sideboard")
        or l.strip().lower().startswith("sb:")
        for l in lines
    )

    main, side = {}, {}
    section = main
    blank_pending = False   # True after blank line (for fallback mode only)

    def _add(dest: dict, raw_name: str, qty: int):
        name = re.sub(r'\s+\(\w{2,5}\)\s+\d+.*$', '', raw_name).strip()
        if name:
            dest[name] = dest.get(name, 0) + qty

    for raw in lines:
        stripped = raw.strip()
        low = stripped.lower()

        # ── Blank line ────────────────────────────────────────────────
        if not stripped:
            if not has_explicit_side and section is main and main:
                blank_pending = True
            continue

        # ── Mainboard headers ─────────────────────────────────────────
        if low in _MAIN_KEYWORDS:
            section = main
            blank_pending = False
            continue

        # ── Sideboard headers (standalone line) ───────────────────────
        if (low in _SIDE_KEYWORDS
                or low.startswith("// sideboard")
                or low.startswith("// sb")):
            section = side
            blank_pending = False
            continue

        # ── Inline "SB: 4 Lightning Bolt" prefix ─────────────────────
        sb_inline = re.match(r'^(?:sb|sideboard):\s+(\d+)x?\s+(.+)',
                             stripped, re.IGNORECASE)
        if sb_inline:
            _add(side, sb_inline.group(2), int(sb_inline.group(1)))
            blank_pending = False
            continue

        # ── Regular card line ─────────────────────────────────────────
        m = re.match(r'^(\d+)x?\s+(.+)', stripped)
        if m:
            # Blank-line fallback: first card after a blank switches to side
            if blank_pending and section is main:
                section = side
            blank_pending = False
            _add(section, m.group(2), int(m.group(1)))

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
        self._worker  = None
        self._workers = []          # keep refs alive
        self._parsed_main = {}
        self._parsed_side = {}
        self._build_ui()
        self._refresh_archetypes()  # populate combo on first show

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
        self._fmt.currentIndexChanged.connect(self._refresh_archetypes)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Archetype:"))
        self._arch = QLineEdit()
        self._arch.setPlaceholderText("optional label, e.g. Izzet Prowess")
        self._arch.setFixedWidth(210)
        ctrl.addWidget(self._arch)

        self._analyze_btn = QPushButton("Analyze Deck")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.clicked.connect(self._run)
        ctrl.addWidget(self._analyze_btn)

        self._export_btn = QPushButton("Export ▾")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        ctrl.addWidget(self._export_btn)

        self._status = QLabel("")
        ctrl.addWidget(self._status)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── Load avg deck row ─────────────────────────────────────────
        load_row = QHBoxLayout()
        load_row.setSpacing(8)

        lbl = QLabel("Load avg deck:")
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM};")
        load_row.addWidget(lbl)

        self._arch_combo = QComboBox()
        self._arch_combo.setEditable(True)
        self._arch_combo.setMinimumWidth(220)
        self._arch_combo.setPlaceholderText("Select archetype…")
        load_row.addWidget(self._arch_combo, 1)

        load_row.addWidget(QLabel("over"))
        self._load_weeks = QComboBox()
        self._load_weeks.addItems(["2 weeks", "4 weeks", "8 weeks", "12 weeks", "all time"])
        self._load_weeks.setCurrentText("4 weeks")
        self._load_weeks.setFixedWidth(90)
        load_row.addWidget(self._load_weeks)

        self._load_btn = QPushButton("Load")
        self._load_btn.setStyleSheet(theme.btn_secondary())
        self._load_btn.setFixedHeight(26)
        self._load_btn.clicked.connect(self._load_avg_deck)
        load_row.addWidget(self._load_btn)

        load_row.addStretch()
        layout.addLayout(load_row)

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
        rv.addWidget(self._score_lbl)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
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
        self._overall_lbl.setWordWrap(True)
        rv.addWidget(self._overall_lbl)
        rv.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([360, 460])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Load average deck from DB
    # ------------------------------------------------------------------

    def _refresh_archetypes(self):
        """Populate the archetype combo with top archetypes for current format."""
        fmt = self._fmt.currentText()

        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT d.archetype, COUNT(*) AS cnt
                    FROM decks d
                    JOIN events e ON e.id = d.event_id
                    WHERE lower(e.format) = lower(?)
                    GROUP BY d.archetype
                    ORDER BY cnt DESC
                    LIMIT 120
                """, [fmt]).fetchall()
            finally:
                conn.close()
            return [r[0] for r in rows]

        w = DataLoadWorker(_do)
        w.result.connect(self._on_archetypes_loaded)
        w.start()
        self._workers.append(w)

    def _on_archetypes_loaded(self, archetypes: list):
        current = self._arch_combo.currentText()
        self._arch_combo.blockSignals(True)
        self._arch_combo.clear()
        self._arch_combo.addItems(archetypes)
        # Restore previous selection if still present
        idx = self._arch_combo.findText(current)
        if idx >= 0:
            self._arch_combo.setCurrentIndex(idx)
        else:
            self._arch_combo.setCurrentIndex(-1)
        self._arch_combo.blockSignals(False)

    def _load_avg_deck(self):
        arch = self._arch_combo.currentText().strip()
        if not arch:
            self._status.setText("Select an archetype first.")
            return

        fmt = self._fmt.currentText()
        weeks_text = self._load_weeks.currentText()
        if weeks_text == "all time":
            since_dt = None
        else:
            weeks = int(weeks_text.split()[0])
            since_dt = datetime.now() - timedelta(weeks=weeks)

        self._load_btn.setEnabled(False)
        self._status.setText(f"Loading {arch}…")

        from gui.widgets.archetype_detail import _load_archetype_data
        w = DataLoadWorker(_load_archetype_data, {
            "archetype": arch,
            "format_name": fmt,
            "since_dt": since_dt,
        })
        w.result.connect(self._on_avg_deck_loaded)
        w.error.connect(lambda e: (
            self._status.setText(f"Error: {e}"),
            self._load_btn.setEnabled(True),
        ))
        w.finished.connect(lambda: self._load_btn.setEnabled(True))
        w.start()
        self._workers.append(w)

    def _on_avg_deck_loaded(self, data):
        if not data:
            self._status.setText("No decklists found for that archetype/timeframe.")
            return

        # Build Arena-format text from average deck
        lines = ["Deck"]
        for card in data["mainboard"]:
            qty = max(1, round(card["avg_qty"]))
            lines.append(f"{qty} {card['name']}")
        if data["sideboard"]:
            lines.append("")
            lines.append("Sideboard")
            for card in data["sideboard"]:
                qty = max(1, round(card["avg_qty"]))
                lines.append(f"{qty} {card['name']}")

        self._deck_input.setPlainText("\n".join(lines))
        self._arch.setText(data["archetype"])

        total_main = sum(max(1, round(c["avg_qty"])) for c in data["mainboard"])
        total_side = sum(max(1, round(c["avg_qty"])) for c in data["sideboard"])
        self._status.setText(
            f"Loaded {data['archetype']} avg ({data['deck_count']} decks — "
            f"{total_main} main / {total_side} side)"
        )

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _on_export(self):
        from gui.widgets.deck_export import show_export_menu
        arch = self._arch.text().strip() or "Pasted Deck"
        show_export_menu(
            self._export_btn,
            self._parsed_main,
            self._parsed_side,
            arch,
            self._fmt.currentText(),
        )

    def _run(self):
        text = self._deck_input.toPlainText().strip()
        if not text:
            self._status.setText("Paste a decklist first.")
            return
        main, side = parse_arena_decklist(text)
        if not main:
            self._status.setText("Could not parse decklist — use Arena export format.")
            return

        self._parsed_main = main
        self._parsed_side = side
        self._export_btn.setEnabled(True)

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
