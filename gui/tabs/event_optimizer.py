"""
Event Optimizer sub-tab — equity analysis for a given expected field.

Split from tournament_prep.py for maintainability.
"""
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QTextEdit, QComboBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QCheckBox, QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from gui.worker_threads import DataLoadWorker
import gui.theme as theme


# ---------------------------------------------------------------------------
# Event Optimizer sub-tab
# ---------------------------------------------------------------------------

class EventWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._saved_decks = []
        self._loaded_deck = None
        self._build_ui()
        # Load saved decks for the initial format after UI is built
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(300, self._refresh_deck_combo)

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # ── Left: inputs ──────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(270)
        left.setMaximumWidth(340)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD)
        lv.setSpacing(theme.SPACE_SM)

        # ── Event group ───────────────────────────────────────────────
        event_box = QGroupBox("Event")
        event_lv = QVBoxLayout(event_box)
        event_lv.setSpacing(theme.SPACE_XS)

        event_lv.addWidget(QLabel("Event type:"))
        self._event_type = QComboBox()
        self._event_type.addItems([
            "RCQ", "Regional Championship", "Pro Tour Qualifier / Open", "Custom"
        ])
        self._event_type.currentTextChanged.connect(self._on_event_type_changed)
        event_lv.addWidget(self._event_type)

        event_lv.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        event_lv.addWidget(self._fmt)
        self._fmt.currentTextChanged.connect(self._on_fmt_changed)

        event_lv.addWidget(QLabel("Player count:"))
        self._players = QSpinBox()
        self._players.setRange(4, 5000)
        self._players.setValue(48)
        self._players.setSuffix(" players")
        event_lv.addWidget(self._players)

        self._struct_lbl = QLabel("")
        self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        self._struct_lbl.setWordWrap(True)
        event_lv.addWidget(self._struct_lbl)
        self._players.valueChanged.connect(self._update_struct_lbl)
        self._update_struct_lbl(48)

        lv.addWidget(event_box)

        # ── Deck group ────────────────────────────────────────────────
        deck_box = QGroupBox("Your Deck")
        deck_lv = QVBoxLayout(deck_box)
        deck_lv.setSpacing(theme.SPACE_XS)

        deck_lv.addWidget(QLabel("Timeframe:"))
        self._tf = QComboBox()
        for label, _ in theme.TIMEFRAME_OPTIONS:
            self._tf.addItem(label)
        self._tf.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._tf.currentIndexChanged.connect(
            lambda _: self._populate_arch_combo(self._fmt.currentText())
        )
        deck_lv.addWidget(self._tf)

        deck_lv.addWidget(QLabel("Load saved deck:"))
        self._deck_combo = QComboBox()
        self._deck_combo.addItem("— none —")
        self._deck_combo.currentIndexChanged.connect(self._on_deck_selected)
        deck_lv.addWidget(self._deck_combo)
        self._loaded_deck = None

        deck_lv.addWidget(QLabel("My archetype:"))
        self._my_arch = QComboBox()
        self._my_arch.setEditable(True)
        self._my_arch.lineEdit().setPlaceholderText("e.g. Boros Energy")
        deck_lv.addWidget(self._my_arch)

        lv.addWidget(deck_box)

        # ── Field group ───────────────────────────────────────────────
        field_box = QGroupBox("Expected Field")
        field_lv = QVBoxLayout(field_box)
        field_lv.setSpacing(theme.SPACE_XS)

        help_lbl = QLabel("One per line: 'Deck Name x4' or 'Deck Name 4'")
        help_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        help_lbl.setWordWrap(True)
        field_lv.addWidget(help_lbl)

        self._field_input = QTextEdit()
        self._field_input.setPlaceholderText(
            "Boros Energy x8\nAzorius Blink x5\nDimir Midrange x4\nMono Red Aggro x3"
        )
        self._field_input.setMinimumHeight(130)
        self._field_input.setMaximumHeight(220)
        field_lv.addWidget(self._field_input)

        self._meta_btn = QPushButton("Use Meta Distribution")
        self._meta_btn.setStyleSheet(theme.btn_secondary())
        self._meta_btn.setToolTip("Auto-fill field from current top meta archetypes by share %")
        self._meta_btn.clicked.connect(self._auto_populate_field)
        field_lv.addWidget(self._meta_btn)

        lv.addWidget(field_box)

        self._analyze_btn = QPushButton("Analyze Field")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.clicked.connect(self._run)
        lv.addWidget(self._analyze_btn)

        self._prep_btn = QPushButton("Generate Prep Package")
        self._prep_btn.setStyleSheet(theme.btn_secondary())
        self._prep_btn.setToolTip("Printable HTML: your 75 + field analysis + SB plans + gap warnings")
        self._prep_btn.clicked.connect(self._generate_prep_package)
        lv.addWidget(self._prep_btn)

        self._gauntlet_btn = QPushButton("Export Gauntlet CSV")
        self._gauntlet_btn.setStyleSheet(theme.btn_secondary())
        self._gauntlet_btn.setToolTip("Export top meta decks as CSV for Team Resolve gauntlet pipeline")
        self._gauntlet_btn.clicked.connect(self._export_gauntlet)
        lv.addWidget(self._gauntlet_btn)

        from gui.widgets.status_row import StatusRow
        self._status_row = StatusRow()
        self._status = self._status_row.label()        # back-compat alias
        self._progress = self._status_row.progress()   # back-compat alias
        lv.addWidget(self._status_row)

        lv.addStretch()

        splitter.addWidget(left)

        # ── Right: results ─────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD)
        rv.setSpacing(theme.SPACE_SM)

        # Header: grade + equity score
        hdr = QHBoxLayout()
        self._grade_lbl = QLabel("—")
        self._grade_lbl.setFont(QFont("Arial", 36, QFont.Weight.Bold))
        self._grade_lbl.setFixedWidth(70)
        hdr.addWidget(self._grade_lbl)

        info_col = QVBoxLayout()
        self._equity_lbl = QLabel("Run an analysis to see field positioning")
        self._equity_lbl.setFont(QFont("Arial", 13))
        self._wwr_lbl = QLabel("")
        self._wwr_lbl.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self._top8_lbl = QLabel("")
        self._top8_lbl.setStyleSheet(f"color: {theme.ACCENT};")
        info_col.addWidget(self._equity_lbl)
        info_col.addWidget(self._wwr_lbl)
        info_col.addWidget(self._top8_lbl)
        hdr.addLayout(info_col)
        hdr.addStretch()
        rv.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        rv.addWidget(sep)

        # Matchup breakdown table
        rv.addWidget(QLabel("Matchup breakdown:"))
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Archetype", "Count", "Encounter %", "G1 WR%", "G2/G3 WR%", "Exp. Rds", "Guides", "Verdict"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 8):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setMaximumHeight(230)
        self._table.itemSelectionChanged.connect(self._on_matchup_selected)
        rv.addWidget(self._table)

        # Recommendations / guide detail panel
        guide_hdr = QHBoxLayout()
        guide_hdr.addWidget(QLabel("Sideboard recommendations & guide analysis:"))
        self._guide_arch_lbl = QLabel("")
        self._guide_arch_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        guide_hdr.addWidget(self._guide_arch_lbl)
        guide_hdr.addStretch()
        rv.addLayout(guide_hdr)

        self._recs = QTextEdit()
        self._recs.setReadOnly(True)
        self._recs.setFont(QFont("Consolas", 10))
        self._recs.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        rv.addWidget(self._recs, 1)

        self._last_result = None

        splitter.addWidget(right)
        splitter.setSizes([300, 700])

        self._populate_arch_combo("standard")

    # ------------------------------------------------------------------
    def _update_struct_lbl(self, n=None):
        if n is None:
            n = self._players.value()
        from analysis.tournament import tournament_structure, RCQ_MIN_PLAYERS, x_loss_cutoff
        s = tournament_structure(n)
        if n < RCQ_MIN_PLAYERS:
            self._struct_lbl.setText(
                f"\u26a0  {n} players \u2014 below minimum ({RCQ_MIN_PLAYERS} required)")
            self._struct_lbl.setStyleSheet(f"color: #e6194b; font-size: 11px;")
        elif s["single_elim"]:
            self._struct_lbl.setText(
                f"3 rounds, single elimination  \u2022  All {n} in bracket")
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        else:
            max_l = x_loss_cutoff(n, s["rounds"], s["top_cut"])
            min_w = s["rounds"] - max_l
            self._struct_lbl.setText(
                f"{s['rounds']} rounds  \u2022  Top {s['top_cut']}  \u2022  "
                f"{s['threshold']} pts  \u2022  Need {min_w}-{max_l} or better")
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")

    def _on_event_type_changed(self, event_type: str):
        from analysis.tournament import EVENT_PRESETS
        preset = EVENT_PRESETS.get(event_type, EVENT_PRESETS["Custom"])
        lo, hi = preset["players_range"]
        self._players.setRange(lo, hi)
        self._players.setValue(preset["default_players"])

    def _on_fmt_changed(self, fmt):
        self._populate_arch_combo(fmt)
        self._refresh_deck_combo()

    def _refresh_deck_combo(self):
        """Populate the saved deck dropdown for the current format."""
        fmt = self._fmt.currentText()

        def _do():
            from db.saved_decks import get_decks
            return get_decks(fmt)

        def _done(decks):
            self._deck_combo.blockSignals(True)
            self._deck_combo.clear()
            self._deck_combo.addItem("— none —")
            self._saved_decks = decks
            for d in decks:
                label = f"{d['name']} ({sum(d.get('mainboard', {}).values())} cards)"
                self._deck_combo.addItem(label)
            self._deck_combo.blockSignals(False)

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_deck_selected(self, idx):
        if idx <= 0:
            self._loaded_deck = None
            return
        decks = getattr(self, "_saved_decks", [])
        if idx - 1 >= len(decks):
            return
        deck = decks[idx - 1]
        self._loaded_deck = deck
        # Set archetype and format from the saved deck
        arch = deck.get("archetype", "")
        if arch:
            self._my_arch.setCurrentText(arch)
        fmt = deck.get("format", "")
        if fmt:
            self._fmt.setCurrentText(fmt)

    def load_deck(self, deck: dict):
        """Called externally (from My Decks tab) to load a specific deck."""
        fmt = deck.get("format", "")
        if fmt:
            self._fmt.setCurrentText(fmt)
        arch = deck.get("archetype", "") or deck.get("name", "")
        if arch:
            # Set the text directly in the editable combo (works even if not in dropdown)
            self._my_arch.setEditText(arch)
        self._loaded_deck = deck
        self._refresh_deck_combo()
        self._status.setText(f"Loaded: {deck.get('name', arch)}")

    def _since_dt(self):
        from datetime import datetime, timedelta
        weeks = theme.TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        return (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None

    def _populate_arch_combo(self, fmt):
        current  = self._my_arch.currentText()
        since    = self._since_dt()

        def _do():
            from analysis.win_rates import get_meta_standings
            rows = get_meta_standings(fmt, top=30, since=since)
            return [r["archetype"] for r in rows]

        def _done(archs):
            self._my_arch.blockSignals(True)
            self._my_arch.clear()
            self._my_arch.addItems(archs or [])
            self._my_arch.setCurrentText(current)
            self._my_arch.blockSignals(False)

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda _: None)
        w.start()
        self._workers.append(w)

    def _parse_field(self) -> dict | None:
        field = {}
        for line in self._field_input.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^(.+?)\s+x\s*(\d+)$', line, re.IGNORECASE)
            if m:
                field[m.group(1).strip()] = int(m.group(2))
                continue
            m = re.match(r'^(.+?)\s+(\d+)$', line)
            if m:
                field[m.group(1).strip()] = int(m.group(2))
                continue
            field[line] = 1
        return field if field else None

    def _auto_populate_field(self):
        """Fill the field textarea from current meta standings."""
        fmt   = self._fmt.currentText()
        since = self._since_dt()
        player_ct = self._players.value()
        self._analyze_btn.setEnabled(False)
        self._status.setText("Loading meta distribution\u2026")
        self._progress.setVisible(True)

        def _auto():
            from analysis.win_rates import get_meta_standings
            standings = get_meta_standings(fmt, top=12, since=since)
            total_app = max(1, sum(x.get("appearances", 1) for x in standings))
            lines = []
            for s in standings:
                a = s["archetype"]
                n = max(1, round(s.get("appearances", 1) / total_app * player_ct))
                lines.append(f"{a} x{n}")
            return "\n".join(lines)

        tf_label = theme.TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]

        def _done(text):
            self._field_input.setPlainText(text)
            self._status.setText(f"Field loaded from {tf_label} meta standings.")
            self._meta_btn.setToolTip(f"Data from {tf_label} meta share for {fmt.capitalize()}")
            self._analyze_btn.setEnabled(True)
            self._progress.setVisible(False)

        w = DataLoadWorker(_auto)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(f"Could not load meta: {theme.friendly_error(e)}"),
            self._analyze_btn.setEnabled(True),
            self._progress.setVisible(False),
        ))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _export_gauntlet(self):
        """Export top N meta decks as CSV for Team Resolve gauntlet pipeline."""
        fmt = self._fmt.currentText()
        since = self._since_dt()
        tf_label = theme.TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
        self._gauntlet_btn.setEnabled(False)
        self._status.setText("Building gauntlet CSV\u2026")

        def _do():
            from analysis.win_rates import get_meta_standings
            from analysis.deck_analysis import get_average_deck
            standings = get_meta_standings(fmt, top=12, since=since)

            rows = []
            letters = "ABCDEFGHIJKL"
            for i, s in enumerate(standings[:12]):
                arch = s["archetype"]
                deck_id = letters[i] if i < 12 else str(i + 1)

                # Get average decklist
                try:
                    avg = get_average_deck(arch, format_name=fmt, min_inclusion=0.25)
                except Exception:
                    avg = None

                main_parts = []
                side_parts = []
                if avg:
                    for c in avg.get("mainboard", []):
                        qty = max(1, round(c["avg_qty"] * c.get("inclusion_rate", 1.0)))
                        if qty > 0:
                            main_parts.append(f"{qty} {c['name']}")
                    for c in avg.get("sideboard", []):
                        qty = max(1, round(c["avg_qty"] * c.get("inclusion_rate", 1.0)))
                        if qty > 0:
                            side_parts.append(f"{qty} {c['name']}")

                rows.append({
                    "Deck_ID (A-L)": deck_id,
                    "Deck_Name": arch,
                    "Archetype (optional)": "",
                    "Source_Link (Moxfield/Goldfish/URL)": "",
                    "Mainboard (format: '4 Card Name; 3 Card Name; ...')": "; ".join(main_parts),
                    "Sideboard (format: '2 Card Name; 1 Card Name; ...')": "; ".join(side_parts),
                    "Notes (optional)": f"apps={s['appearances']} wr={s.get('est_match_winpct',0)*100:.0f}%",
                })
            return rows

        def _done(rows):
            import csv, os
            from datetime import datetime
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl

            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exports = os.path.join(root, "exports")
            os.makedirs(exports, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(exports, f"gauntlet_{fmt}_{ts}.csv")

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            self._gauntlet_btn.setEnabled(True)
            self._status.setText(f"Gauntlet CSV saved: {os.path.basename(path)} ({len(rows)} decks)")
            QDesktopServices.openUrl(QUrl.fromLocalFile(exports))

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._gauntlet_btn.setEnabled(True),
        ))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _generate_prep_package(self):
        """Generate a full printable prep package HTML."""
        archetype = self._my_arch.currentText().strip()
        field = self._parse_field()
        if not archetype:
            self._status.setText("Enter your archetype first.")
            return
        if not field:
            self._status.setText("Populate the field first (Use Meta Distribution or enter manually).")
            return

        fmt = self._fmt.currentText()
        since = self._since_dt()
        tf_label = theme.TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
        loaded_deck = self._loaded_deck
        self._prep_btn.setEnabled(False)
        self._status.setText("Generating prep package\u2026")

        def _do():
            from analysis.tournament import rcq_equity
            result = rcq_equity(archetype, field, fmt, since=since)

            # Get saved SB plans if a deck is loaded
            sb_plans = []
            if loaded_deck and loaded_deck.get("id"):
                from db.saved_decks import get_sb_plans
                sb_plans = get_sb_plans(loaded_deck["id"])

            # Get personal match stats
            from db.match_log import get_matchup_stats
            personal = get_matchup_stats(archetype, format_name=fmt)

            return {
                "result": result, "sb_plans": sb_plans, "personal": personal,
                "deck": loaded_deck, "fmt": fmt, "tf_label": tf_label,
            }

        def _done(pkg):
            self._prep_btn.setEnabled(True)
            if "error" in pkg["result"]:
                self._status.setText(f"Error: {pkg['result']['error']}")
                return
            html = _build_prep_html(pkg)
            # Save and open
            import os
            from datetime import datetime
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exports = os.path.join(root, "exports")
            os.makedirs(exports, exist_ok=True)
            safe = archetype.replace("/", "_").replace(":", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(exports, f"prep_{safe}_{ts}.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self._status.setText(f"Prep package saved to exports/")

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._prep_btn.setEnabled(True),
        ))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _run(self):
        archetype = self._my_arch.currentText().strip()
        field = self._parse_field()
        if not archetype:
            self._status.setText("Enter your archetype.")
            return
        if not field:
            self._auto_populate_field()
            return

        fmt   = self._fmt.currentText()
        since = self._since_dt()
        self._analyze_btn.setEnabled(False)
        self._status.setText("Analyzing…")

        def _do():
            from analysis.tournament import rcq_equity
            return rcq_equity(archetype, field, fmt, since=since)

        def _done(result):
            self._analyze_btn.setEnabled(True)
            if "error" in result:
                self._status.setText(f"Error: {result['error']}")
                return
            self._status.setText("")
            self._show_results(result)

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._analyze_btn.setEnabled(True),
        ))
        w.start()
        self._workers.append(w)

    def _show_results(self, r):
        grade  = r["grade"]
        wwr    = r["weighted_wr"]
        top    = r["top_prob"]
        struct = r["struct"]

        grade_colors = {
            "A+": "#3cb44b", "A": "#3cb44b", "B": "#5eb5cf",
            "C": "#f0c020", "D": "#f58231", "F": "#e6194b",
        }
        gc = grade_colors.get(grade, theme.TEXT)

        self._grade_lbl.setText(grade)
        self._grade_lbl.setStyleSheet(
            f"color: {gc}; font-size: 36px; font-weight: bold;"
        )
        self._equity_lbl.setText(f"{r['grade_label']}  —  {r['my_archetype']}")
        self._wwr_lbl.setText(
            f"Weighted win rate vs field: {wwr*100:.1f}%   "
            f"(deck strength: {r['my_wr']*100:.1f}% est. MWP)"
        )
        from analysis.tournament import x_loss_cutoff, day2_conversion_probability
        rounds = struct["rounds"]
        top8_text = (
            f"Estimated top-{struct['top_cut']} probability: {top*100:.1f}%   "
            f"({rounds}-round Swiss, {r['players']} players)"
        )
        max_losses = x_loss_cutoff(r["players"], rounds, struct["top_cut"])
        min_wins   = rounds - max_losses
        top8_text += f"\nMinimum record: {min_wins}-{max_losses}"
        # For large events (likely 2-day), show day-2 conversion info
        if rounds >= 9 and r["players"] >= 200:
            day1_rds   = min(8, rounds)
            day2_cut   = day1_rds - 2  # typically 6-2 or better for day 2
            d2_prob    = day2_conversion_probability(wwr, day1_rds, day2_cut)
            top8_text += (
                f"  |  Day-2 conversion ({day2_cut}-{day1_rds - day2_cut} or better "
                f"after {day1_rds} rounds): {d2_prob*100:.1f}%"
            )
        self._top8_lbl.setText(top8_text)

        def _item(txt, color=None, align=Qt.AlignmentFlag.AlignCenter):
            it = QTableWidgetItem(str(txt))
            it.setTextAlignment(align)
            if color:
                it.setForeground(QColor(color))
            return it

        # Matchup table — 7 columns: Archetype|Count|Exp.Rds|G1 WR%|G2/G3 WR%|Guides|Verdict
        self._table.setRowCount(0)
        self._table.setRowCount(len(r["matchups"]))
        for row, m in enumerate(r["matchups"]):

            flip      = m.get("flip", {})
            has_data  = flip.get("has_data", False)
            g1_wr     = m.get("g1_wr", m["matchup_wr"])
            g23_wr    = m.get("g23_wr", g1_wr)
            delta     = flip.get("delta", 0.0)
            flipped   = flip.get("flipped", False)

            g1_color  = "#3cb44b" if g1_wr >= 0.52 else ("#e6194b" if g1_wr <= 0.48 else None)

            if not has_data:
                g23_txt   = "—"
                g23_color = "#8a9aaa"
            else:
                g23_txt   = f"{g23_wr*100:.0f}%"
                if flipped and delta < 0:
                    g23_color = "#e6194b"
                elif flipped and delta > 0:
                    g23_color = "#3cb44b"
                elif delta <= -0.05:
                    g23_color = "#f58231"
                elif delta >= 0.05:
                    g23_color = "#3cb44b"
                else:
                    g23_color = g1_color

            gd = m.get("guide_data", {})
            my_cnt  = gd.get("my_count",  0)
            opp_cnt = gd.get("opp_count", 0)
            if my_cnt + opp_cnt == 0:
                guide_txt   = "none"
                guide_color = "#8a9aaa"
            else:
                guide_txt   = f"↑{my_cnt} ↓{opp_cnt}"
                guide_color = "#5eb5cf"

            if flipped and delta < 0:
                verdict, vc = "⚠ FLIP", "#e6194b"
            elif flipped and delta > 0:
                verdict, vc = "↑ Flip+", "#3cb44b"
            elif m["favored"]:
                verdict, vc = "Favored", "#3cb44b"
            elif m["unfavored"]:
                verdict, vc = "Unfavored", "#e6194b"
            else:
                verdict, vc = "Even", None

            # Encounter probability
            enc = m.get("encounter", {})
            p1_plus = enc.get("p_at_least_1", 0)
            enc_text = f"{p1_plus*100:.0f}%"
            # Build tooltip with full distribution
            enc_probs = enc.get("probs", [])
            tip_lines = [f"P(face {m['archetype']} exactly k times):"]
            for k, p in enumerate(enc_probs):
                if p >= 0.005:
                    bar = "\u2588" * int(p * 20)
                    tip_lines.append(f"  {k}x: {p*100:5.1f}%  {bar}")
            tip_lines.append(f"\nExpected: {enc.get('expected', 0):.1f} rounds")
            tip_lines.append(f"P(never face): {enc.get('p_zero', 0)*100:.0f}%")
            tip_lines.append(f"P(face 2+): {enc.get('p_at_least_2', 0)*100:.0f}%")
            enc_tooltip = "\n".join(tip_lines)

            # Color: red if high encounter + unfavored, green if high + favored
            enc_color = None
            if p1_plus >= 0.6 and m["unfavored"]:
                enc_color = "#e6194b"
            elif p1_plus >= 0.6 and m["favored"]:
                enc_color = "#3cb44b"

            self._table.setItem(row, 0, _item(m["archetype"], align=Qt.AlignmentFlag.AlignLeft))
            self._table.setItem(row, 1, _item(m["count"]))

            enc_item = _item(enc_text, enc_color)
            enc_item.setToolTip(enc_tooltip)
            self._table.setItem(row, 2, enc_item)

            self._table.setItem(row, 3, _item(f"{g1_wr*100:.0f}%", g1_color))
            self._table.setItem(row, 4, _item(g23_txt, g23_color))
            self._table.setItem(row, 5, _item(f"{m['exp_rounds']:.1f}"))
            self._table.setItem(row, 6, _item(guide_txt, guide_color))
            self._table.setItem(row, 7, _item(verdict, vc))

        # Store result and render the full recommendations panel
        self._last_result = r
        self._guide_arch_lbl.setText("(click a matchup row for detailed guide analysis)")
        self._render_recs_html(r, selected_matchup=None)

    def _on_matchup_selected(self):
        if not self._last_result:
            return
        rows = self._table.selectedItems()
        if not rows:
            self._render_recs_html(self._last_result, selected_matchup=None)
            return
        row_idx = self._table.currentRow()
        matchups = self._last_result.get("matchups", [])
        if 0 <= row_idx < len(matchups):
            m = matchups[row_idx]
            self._guide_arch_lbl.setText(
                f"— {m['archetype']} detail"
            )
            self._render_recs_html(self._last_result, selected_matchup=m)
        else:
            self._render_recs_html(self._last_result, selected_matchup=None)

    def _render_recs_html(self, r, selected_matchup):
        from analysis.sideboard_guides import render_guide_html

        my_arch = r["my_archetype"]
        parts   = []

        BASE = f"font-family: Consolas, monospace; font-size: 11px; color: {theme.TEXT}; line-height: 1.45;"

        if selected_matchup:
            # ── Per-matchup detail view ─────────────────────────────────
            m    = selected_matchup
            flip = m.get("flip", {})
            gd   = m.get("guide_data", {})
            g1   = m.get("g1_wr", m["matchup_wr"])
            g23  = m.get("g23_wr", g1)
            has_data = flip.get("has_data", False)

            # Flip verdict block
            fc = flip.get("color", "#8a9aaa")
            verdict_txt = flip.get("verdict", "")
            parts.append(
                f'<div style="background:#1e2d40; border-left:4px solid {fc}; '
                f'padding:8px 12px; border-radius:3px; margin-bottom:8px;">'
                f'<b style="color:{fc};">{verdict_txt}</b>'
                f'</div>'
            )

            # G1 vs G2/G3 breakdown
            parts.append(
                f'<table style="border-collapse:collapse; margin-bottom:8px;">'
                f'<tr style="color:#8a9aaa;">'
                f'<th style="text-align:left; padding-right:20px;">Game</th>'
                f'<th style="padding-right:20px;">Win Rate</th>'
                f'<th>Assessment</th></tr>'
            )
            g1_ass = ("Favored" if g1 >= 0.52 else ("Unfavored" if g1 <= 0.48 else "Even"))
            g1_c   = "#3cb44b" if g1 >= 0.52 else ("#e6194b" if g1 <= 0.48 else "#f0c020")
            parts.append(
                f'<tr>'
                f'<td style="padding-right:20px; color:#c0c8d0;">Game 1</td>'
                f'<td style="color:{g1_c}; padding-right:20px; font-weight:bold;">{g1*100:.0f}%</td>'
                f'<td style="color:{g1_c};">{g1_ass}</td>'
                f'</tr>'
            )
            if has_data:
                g23_ass = ("Favored" if g23 >= 0.52 else ("Unfavored" if g23 <= 0.48 else "Even"))
                g23_c   = "#3cb44b" if g23 >= 0.52 else ("#e6194b" if g23 <= 0.48 else "#f0c020")
                delta_s = f"({flip['delta']*100:+.0f}%)"
                opp_in  = gd.get("opp_sb_plan", {}).get("total_in", 0)
                my_in   = gd.get("my_sb_plan",  {}).get("total_in", 0)
                parts.append(
                    f'<tr>'
                    f'<td style="padding-right:20px; color:#c0c8d0;">Games 2–3</td>'
                    f'<td style="color:{g23_c}; padding-right:20px; font-weight:bold;">'
                    f'{g23*100:.0f}% <span style="color:#8a9aaa; font-size:10px;">{delta_s}</span>'
                    f'</td>'
                    f'<td style="color:{g23_c};">{g23_ass}</td>'
                    f'</tr>'
                )
                parts.append(
                    f'<tr style="color:#8a9aaa; font-size:10px;">'
                    f'<td colspan="3" style="padding-top:4px;">'
                    f'Based on: your guides bring in {my_in} cards / '
                    f'opponent brings in {opp_in} cards vs you'
                    f'</td></tr>'
                )
            else:
                parts.append(
                    f'<tr><td colspan="3" style="color:#8a9aaa; font-style:italic; padding-top:4px;">'
                    f'Games 2–3: no guide data — add sideboard guides to the Knowledge Base '
                    f'to unlock post-board win rate estimates.'
                    f'</td></tr>'
                )
            parts.append('</table>')

            # Guide detail
            parts.append(
                f'<div style="border-top:1px solid #2d2e3f; margin:8px 0; padding-top:8px;">'
            )
            parts.append(render_guide_html(gd, my_arch, m["archetype"]))
            parts.append('</div>')

            # Source links if any guides have URLs
            all_guides = gd.get("my_guides", []) + gd.get("opp_guides", [])
            urls = [(g.get("source") or g.get("url", ""), g.get("archetype", ""))
                    for g in all_guides if g.get("url")]
            if urls:
                parts.append('<p style="color:#8a9aaa; margin-top:6px;"><b>Sources:</b></p>')
                for url, arch in urls[:4]:
                    parts.append(
                        f'<p style="margin:1px 0; font-size:10px; color:#4a7a9b;">'
                        f'{arch} — {url}</p>'
                    )

        else:
            # ── Overview / summary view ─────────────────────────────────
            # Flip warnings first
            flipped_matchups = [
                m for m in r.get("matchups", [])
                if m.get("flip", {}).get("flipped") and m.get("flip", {}).get("delta", 0) < 0
            ]
            if flipped_matchups:
                parts.append(
                    f'<div style="background:#2a1010; border-left:4px solid #e6194b; '
                    f'padding:8px 12px; border-radius:3px; margin-bottom:10px;">'
                    f'<b style="color:#e6194b;">⚠ MATCHUP FLIP WARNINGS</b><br>'
                )
                for m in flipped_matchups:
                    flip = m["flip"]
                    gd   = m.get("guide_data", {})
                    opp_in = gd.get("opp_sb_plan", {}).get("total_in", 0)
                    parts.append(
                        f'<span style="color:#f0c020;"><b>{m["archetype"]}</b></span>: '
                        f'Favored G1 ({m["g1_wr"]*100:.0f}%) but this matchup flips '
                        f'games 2 and 3 ({m["g23_wr"]*100:.0f}%) — opponent has '
                        f'<b>{opp_in}</b> dedicated sideboard cards against you.<br>'
                    )
                parts.append('</div>')

            # Significantly worse post-board (not full flip)
            sig_worse = [
                m for m in r.get("matchups", [])
                if m.get("flip", {}).get("significantly_worse")
                and not m.get("flip", {}).get("flipped")
                and m.get("guide_data", {}).get("opp_count", 0) > 0
            ]
            if sig_worse:
                parts.append(
                    f'<div style="background:#241a0a; border-left:4px solid #f58231; '
                    f'padding:8px 12px; border-radius:3px; margin-bottom:10px;">'
                    f'<b style="color:#f58231;">Post-Board Danger Matchups</b><br>'
                )
                for m in sig_worse:
                    gd     = m.get("guide_data", {})
                    opp_in = gd.get("opp_sb_plan", {}).get("total_in", 0)
                    parts.append(
                        f'<span style="color:#f0c020;"><b>{m["archetype"]}</b></span>: '
                        f'{m["g1_wr"]*100:.0f}% G1 → {m["g23_wr"]*100:.0f}% G2/G3 '
                        f'({m["flip"]["delta"]*100:+.0f}%). Opponent brings {opp_in} cards vs you.<br>'
                    )
                parts.append('</div>')

            # Standard rec bullets
            recs_html = "".join(
                f'<p style="margin: 3px 0;">{rec_}</p>' for rec_ in r.get("recs", [])
            )
            parts.append(recs_html)

            # Guide coverage summary
            guide_matchups = [
                m for m in r.get("matchups", [])
                if m.get("guide_data", {}).get("my_count", 0) > 0
                or m.get("guide_data", {}).get("opp_count", 0) > 0
            ]
            if guide_matchups:
                parts.append(
                    f'<p style="margin-top:10px; color:#8a9aaa; font-size:10px;">'
                    f'Guide data available for {len(guide_matchups)} of '
                    f'{len(r["matchups"])} matchups. '
                    f'Click a matchup row for detailed G2/G3 analysis.</p>'
                )
            else:
                parts.append(
                    f'<p style="margin-top:10px; color:#8a9aaa; font-size:10px; font-style:italic;">'
                    f'No sideboard guides found for these archetypes. Add guides via the '
                    f'Knowledge Base tab to enable G2/G3 win rate analysis.</p>'
                )

        self._recs.setHtml(
            f'<div style="{BASE}">' + "".join(parts) + '</div>'
        )


# ---------------------------------------------------------------------------
# Prep package HTML generator
# ---------------------------------------------------------------------------

def _build_prep_html(pkg: dict) -> str:
    r = pkg["result"]
    sb_plans = pkg["sb_plans"]
    personal = pkg["personal"]
    deck = pkg["deck"]
    fmt = pkg["fmt"]
    tf = pkg["tf_label"]
    my_arch = r["my_archetype"]
    struct = r["struct"]

    # Build SB plan lookup
    sb_lookup = {p["opponent_archetype"]: p for p in sb_plans}

    parts = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{my_arch} — Event Prep</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 900px; margin: 16px auto; color: #222; font-size: 12px; }}
  h1 {{ font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 4px; margin-bottom: 8px; }}
  h2 {{ font-size: 14px; margin: 14px 0 6px 0; color: #333; }}
  .meta {{ color: #666; font-size: 11px; margin-bottom: 12px; }}
  .grade {{ font-size: 28px; font-weight: bold; display: inline-block; margin-right: 12px; }}
  .summary {{ margin-bottom: 12px; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 12px; }}
  th {{ background: #eee; text-align: left; padding: 4px 8px; font-size: 11px; border: 1px solid #ccc; }}
  td {{ padding: 4px 8px; border: 1px solid #ddd; font-size: 11px; }}
  .win {{ color: #2a7a2a; font-weight: bold; }}
  .loss {{ color: #c22; font-weight: bold; }}
  .even {{ color: #666; }}
  .flip {{ background: #fee; }}
  .gap {{ background: #fff3cd; }}
  .sb {{ font-size: 10px; }}
  .in {{ color: #2a7a2a; }} .out {{ color: #c22; }}
  .notes {{ color: #666; font-style: italic; }}
  .decklist {{ background: #f5f5f5; padding: 8px; border-radius: 4px; font-family: Consolas, monospace; font-size: 11px; white-space: pre-wrap; column-count: 2; }}
  @media print {{ body {{ margin: 0; font-size: 11px; }} .decklist {{ column-count: 2; }} }}
</style>
</head><body>
<h1>{my_arch} — Event Prep Package</h1>
<div class="meta">{fmt.capitalize()} &bull; {tf} data &bull; {struct['rounds']} rounds &bull; {r['players']} players &bull; Top {struct['top_cut']}</div>
"""]

    # Grade + summary
    parts.append(f'<div class="summary">')
    parts.append(f'<span class="grade">{r["grade"]}</span> {r["grade_label"]}<br>')
    parts.append(f'Weighted WR vs field: <b>{r["weighted_wr"]*100:.1f}%</b> &bull; '
                 f'Top-{struct["top_cut"]} probability: <b>{r["top_prob"]*100:.1f}%</b>')
    parts.append(f'</div>')

    # Decklist (if loaded)
    if deck and deck.get("mainboard"):
        main = deck["mainboard"]
        side = deck.get("sideboard", {})
        parts.append('<h2>Decklist</h2>')
        parts.append('<div class="decklist">')
        for card, qty in sorted(main.items()):
            parts.append(f'{qty} {card}\n')
        if side:
            parts.append('\nSideboard\n')
            for card, qty in sorted(side.items()):
                parts.append(f'{qty} {card}\n')
        parts.append('</div>')

    # Matchup table
    parts.append('<h2>Expected Field Matchups</h2>')
    parts.append('<table><tr><th>Opponent</th><th>Count</th><th>Exp Rds</th>'
                 '<th>G1 WR</th><th>G2/G3</th><th>Your Record</th><th>SB Plan</th></tr>')

    gaps = []
    for m in r["matchups"]:
        opp = m["archetype"]
        g1 = m["g1_wr"]
        g23 = m.get("g23_wr", g1)
        flip = m.get("flip", {})
        has_sb = opp in sb_lookup
        pers = personal.get(opp)

        # Color
        cls = "win" if g1 >= 0.52 else ("loss" if g1 <= 0.48 else "even")
        row_cls = ' class="flip"' if flip.get("flipped") and flip.get("delta", 0) < 0 else ""
        row_cls = ' class="gap"' if not has_sb else row_cls

        # Personal record
        if pers:
            rec_text = f'{pers["wins"]}-{pers["losses"]}-{pers["draws"]} ({pers["wr"]*100:.0f}%)'
        else:
            rec_text = '<span class="notes">no data</span>'

        # SB plan summary
        if has_sb:
            sp = sb_lookup[opp]
            play_in = sp.get("play_in", [])
            play_out = sp.get("play_out", [])
            sb_text = ""
            if play_in:
                sb_text += f'<span class="in">+{", +".join(play_in[:3])}</span> '
            if play_out:
                sb_text += f'<span class="out">-{", -".join(play_out[:3])}</span>'
            if not sb_text:
                sb_text = '<span class="notes">plan saved (no cards)</span>'
        else:
            sb_text = '<b style="color:#c22;">NO PLAN</b>'
            gaps.append(opp)

        parts.append(
            f'<tr{row_cls}><td>{opp}</td><td>{m["count"]}</td>'
            f'<td>{m["exp_rounds"]:.1f}</td>'
            f'<td class="{cls}">{g1*100:.0f}%</td>'
            f'<td>{g23*100:.0f}%</td>'
            f'<td>{rec_text}</td>'
            f'<td class="sb">{sb_text}</td></tr>')

    parts.append('</table>')

    # Gap warnings
    if gaps:
        parts.append('<h2 style="color:#c22;">Missing SB Plans</h2>')
        parts.append('<p>You have no sideboard plan saved for these matchups:</p><ul>')
        for opp in gaps:
            m = next((x for x in r["matchups"] if x["archetype"] == opp), None)
            pct = f" ({m['frac']*100:.0f}% of field)" if m else ""
            parts.append(f'<li><b>{opp}</b>{pct}</li>')
        parts.append('</ul>')

    # Recommendations
    parts.append('<h2>Sideboard Recommendations</h2>')
    for rec in r.get("recs", []):
        parts.append(f'<p>{rec}</p>')

    parts.append('</body></html>')
    return "".join(parts)

