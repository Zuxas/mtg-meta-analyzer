"""
Tab — Match Log

Personal tournament match tracker. Log each round with opponent archetype,
result, play/draw, game-by-game results, and notes. View aggregated stats
per matchup including play/draw win rate splits.
"""
from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame, QGroupBox, QDialog,
    QFormLayout, QDialogButtonBox, QMessageBox, QSplitter,
    QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker

_FORMATS = ["standard", "pioneer", "modern", "legacy", "pauper"]
_RESULTS = ["win", "loss", "draw"]
_PLAY_DRAW = ["", "play", "draw"]
_GAME_RESULTS = ["", "win", "loss"]


class _MatchDialog(QDialog):
    """Dialog to add/edit a single match log entry."""

    def __init__(self, parent=None, match=None, default_event="",
                 default_deck="", default_format="modern",
                 default_round=1):
        super().__init__(parent)
        self.setWindowTitle("Edit Match" if match else "Log Match")
        self.setMinimumSize(*theme.DIALOG_SM)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._event = QLineEdit()
        self._event.setText(match.get("event_name", default_event) if match else default_event)
        self._event.setPlaceholderText("e.g. RCQ @ Card Kingdom")
        form.addRow("Event:", self._event)

        self._date = QLineEdit()
        self._date.setText(match.get("event_date", date.today().isoformat()) if match else date.today().isoformat())
        self._date.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Date:", self._date)

        self._fmt = QComboBox()
        self._fmt.addItems(_FORMATS)
        self._fmt.setCurrentText(match.get("format", default_format) if match else default_format)
        form.addRow("Format:", self._fmt)

        self._round = QSpinBox()
        self._round.setRange(1, 20)
        self._round.setValue(match.get("round", default_round) if match else default_round)
        form.addRow("Round:", self._round)

        self._my_deck = QComboBox()
        self._my_deck.setEditable(True)
        self._my_deck.lineEdit().setPlaceholderText("Your deck")
        if match:
            self._my_deck.setCurrentText(match.get("my_deck", default_deck))
        elif default_deck:
            self._my_deck.setCurrentText(default_deck)
        # Populate from saved decks
        try:
            from db.saved_decks import get_decks
            decks = get_decks()
            self._my_deck.addItems(list({d["archetype"] for d in decks if d.get("archetype")}))
        except Exception:
            pass
        form.addRow("My Deck:", self._my_deck)

        self._opp_deck = QComboBox()
        self._opp_deck.setEditable(True)
        self._opp_deck.lineEdit().setPlaceholderText("Opponent's deck")
        if match:
            self._opp_deck.setCurrentText(match.get("opp_deck", ""))
        # Populate with meta archetypes
        try:
            from analysis.win_rates import get_meta_standings
            fmt = self._fmt.currentText()
            top = get_meta_standings(fmt, top=20)
            self._opp_deck.addItems([s["archetype"] for s in top])
        except Exception:
            pass
        form.addRow("Opponent Deck:", self._opp_deck)

        self._opp_name = QLineEdit()
        self._opp_name.setText(match.get("opp_name", "") if match else "")
        self._opp_name.setPlaceholderText("Optional")
        form.addRow("Opponent Name:", self._opp_name)

        self._result = QComboBox()
        self._result.addItems(_RESULTS)
        if match and match.get("result"):
            self._result.setCurrentText(match["result"])
        form.addRow("Match Result:", self._result)

        self._play_draw = QComboBox()
        self._play_draw.addItems(["Unknown", "On the Play", "On the Draw"])
        if match:
            pd = match.get("play_draw", "")
            if pd == "play":
                self._play_draw.setCurrentText("On the Play")
            elif pd == "draw":
                self._play_draw.setCurrentText("On the Draw")
        form.addRow("Play/Draw:", self._play_draw)

        # Game-by-game
        game_row = QHBoxLayout()
        game_row.addWidget(QLabel("G1:"))
        self._g1 = QComboBox()
        self._g1.addItems(_GAME_RESULTS)
        if match:
            self._g1.setCurrentText(match.get("g1_result", ""))
        game_row.addWidget(self._g1)
        game_row.addWidget(QLabel("G2:"))
        self._g2 = QComboBox()
        self._g2.addItems(_GAME_RESULTS)
        if match:
            self._g2.setCurrentText(match.get("g2_result", ""))
        game_row.addWidget(self._g2)
        game_row.addWidget(QLabel("G3:"))
        self._g3 = QComboBox()
        self._g3.addItems(_GAME_RESULTS)
        if match:
            self._g3.setCurrentText(match.get("g3_result", ""))
        game_row.addWidget(self._g3)
        form.addRow("Games:", game_row)

        self._notes = QTextEdit()
        self._notes.setMaximumHeight(60)
        self._notes.setPlaceholderText("Notes about the match...")
        if match:
            self._notes.setPlainText(match.get("notes", ""))
        form.addRow("Notes:", self._notes)

        self._swap_notes = QLineEdit()
        self._swap_notes.setPlaceholderText(
            "e.g. in: 2 Dismember, out: 2 Lightning Helix"
        )
        if match:
            self._swap_notes.setText(match.get("swap_notes", ""))
        form.addRow("Swap:", self._swap_notes)

        self._swap_verdict = QComboBox()
        self._swap_verdict.addItems(["", "kept", "reverted"])
        self._swap_verdict.setToolTip(
            "Post-match hindsight: did the swap pay off?\n"
            "  kept — works, keeping this change\n"
            "  reverted — didn't work, going back\n"
            "  (blank) — haven't decided yet"
        )
        if match:
            self._swap_verdict.setCurrentText(match.get("swap_verdict", ""))
        form.addRow("Swap Verdict:", self._swap_verdict)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self) -> dict:
        pd_map = {"On the Play": "play", "On the Draw": "draw", "Unknown": ""}
        return {
            "event_name": self._event.text().strip(),
            "event_date": self._date.text().strip(),
            "format":     self._fmt.currentText(),
            "round":      self._round.value(),
            "my_deck":    self._my_deck.currentText().strip(),
            "opp_deck":   self._opp_deck.currentText().strip(),
            "opp_name":   self._opp_name.text().strip(),
            "result":     self._result.currentText(),
            "play_draw":  pd_map.get(self._play_draw.currentText(), ""),
            "g1_result":  self._g1.currentText(),
            "g2_result":  self._g2.currentText(),
            "g3_result":  self._g3.currentText(),
            "notes":      self._notes.toPlainText().strip(),
            "swap_notes": self._swap_notes.text().strip(),
            "swap_verdict": self._swap_verdict.currentText(),
        }


class MatchLogTab(QWidget):
    def __init__(self, parent=None, on_simulate_matchup=None):
        """
        on_simulate_matchup: optional callable(a_label, b_label, format_hint).
        When set, rows in both the match table and the stats table show a
        right-click 'Simulate this matchup' action that hands off to
        SIMULATE pre-filled.
        """
        super().__init__(parent)
        self._workers = []
        self._last_event = ""
        self._last_deck = ""
        self._last_format = "modern"
        self._last_round = 1
        self._on_simulate_matchup = on_simulate_matchup
        self._build_ui()
        QTimer.singleShot(200, self._load_matches)

    def cleanup(self):
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)

        from gui.widgets.summary_bar import SummaryBar
        self._summary_bar = SummaryBar()
        outer.addWidget(self._summary_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: match log table ─────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        # Filter row
        filt = QHBoxLayout()
        filt.addWidget(QLabel("Format:"))
        self._filter_fmt = QComboBox()
        self._filter_fmt.addItems(["All"] + _FORMATS)
        self._filter_fmt.currentIndexChanged.connect(lambda _: self._load_matches())
        filt.addWidget(self._filter_fmt)

        filt.addWidget(QLabel("Deck:"))
        self._filter_deck = QComboBox()
        self._filter_deck.setEditable(True)
        self._filter_deck.addItem("All")
        self._filter_deck.setFixedWidth(150)
        self._filter_deck.currentTextChanged.connect(lambda _: self._load_matches())
        filt.addWidget(self._filter_deck)
        filt.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
        filt.addWidget(self._summary_lbl)
        lv.addLayout(filt)

        # Match table
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Event", "Rd", "My Deck", "vs", "Result", "P/D", "Games", "Swap"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_matches_menu)
        lv.addWidget(self._table, 1)

        # Buttons
        from gui.icons_util import btn_icon
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton(btn_icon("add", color=theme.BTN_FG), "Log Match")
        self._add_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self._add_btn.clicked.connect(self._add_match)
        btn_row.addWidget(self._add_btn)

        self._edit_btn = QPushButton(btn_icon("edit"), "Edit")
        self._edit_btn.setStyleSheet(theme.btn_secondary())
        self._edit_btn.clicked.connect(self._edit_match)
        btn_row.addWidget(self._edit_btn)

        self._del_btn = QPushButton(btn_icon("delete", color=theme.ERR), "Delete")
        self._del_btn.setStyleSheet(f"color: {theme.ERR};")
        self._del_btn.clicked.connect(self._delete_match)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # ── Right: matchup stats ──────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        rv.addWidget(QLabel("Matchup Stats — Your Record vs Meta Expected:"))

        self._stats_table = QTableWidget()
        self._stats_table.setColumnCount(8)
        self._stats_table.setHorizontalHeaderLabels(
            ["Opponent", "Record", "Your WR", "Meta WR", "Delta", "On Play", "On Draw", "#"])
        sh = self._stats_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            sh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.setAlternatingRowColors(True)
        self._stats_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._stats_table.customContextMenuRequested.connect(self._on_stats_menu)
        rv.addWidget(self._stats_table, 1)

        # SB Advice button
        advice_row = QHBoxLayout()
        self._advice_btn = QPushButton("SB Advice")
        self._advice_btn.setStyleSheet(theme.btn_secondary())
        self._advice_btn.setToolTip(
            "Analyze your weak matchups and get sideboard recommendations"
        )
        self._advice_btn.clicked.connect(self._show_sb_advice)
        advice_row.addWidget(self._advice_btn)
        advice_row.addStretch()
        rv.addLayout(advice_row)

        # Event type breakdown
        self._event_lbl = QLabel("")
        self._event_lbl.setWordWrap(True)
        self._event_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        rv.addWidget(self._event_lbl)

        # Win rate trend chart
        rv.addWidget(QLabel("Win Rate Trend:"))
        from gui.widgets.chart_canvas import ChartCanvas
        self._trend_canvas = ChartCanvas()
        rv.addWidget(self._trend_canvas)

        splitter.addWidget(right)
        splitter.setSizes([550, 350])
        outer.addWidget(splitter)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_matches(self):
        fmt = self._filter_fmt.currentText()
        fmt_arg = None if fmt == "All" else fmt
        deck = self._filter_deck.currentText().strip()
        deck_arg = None if deck in ("All", "") else deck

        def _do():
            from db.match_log import get_matches, get_matchup_stats, get_overall_stats
            matches = get_matches(format_name=fmt_arg, my_deck=deck_arg)
            stats = {}
            overall = {"wins": 0, "losses": 0, "draws": 0, "total": 0, "wr": 0}
            active_deck = deck_arg
            if deck_arg:
                stats = get_matchup_stats(deck_arg, format_name=fmt_arg)
                overall = get_overall_stats(my_deck=deck_arg, format_name=fmt_arg)
            elif matches:
                from collections import Counter
                decks = Counter(m["my_deck"] for m in matches if m.get("my_deck"))
                if decks:
                    active_deck = decks.most_common(1)[0][0]
                    stats = get_matchup_stats(active_deck, format_name=fmt_arg)
                    overall = get_overall_stats(my_deck=active_deck, format_name=fmt_arg)

            # Fetch meta WR for comparison
            meta_wrs = {}
            try:
                from analysis.win_rates import get_real_matchup_winrates
                from analysis.archetypes import normalize as norm_arch
                if active_deck and fmt_arg:
                    real = get_real_matchup_winrates(fmt_arg or "modern", min_matches=10)
                    my_norm = norm_arch(active_deck).lower()
                    for a, opps in real.items():
                        if norm_arch(a).lower() == my_norm:
                            for b, s in opps.items():
                                meta_wrs[norm_arch(b)] = s["win_rate"]
                            break
            except Exception:
                pass

            # Event type breakdown: tally W/L/D per event category so we can
            # show 'RCQ: 12W-8L (60%)' rather than just '20 matches'.
            def _classify_event(name: str) -> str:
                low = (name or "").lower()
                if "rcq" in low:
                    return "RCQ"
                if "regional" in low or " rc " in low:
                    return "RC"
                if "open" in low or "5k" in low or "$5k" in low:
                    return "Open"
                if "fnm" in low or "friday" in low:
                    return "FNM"
                return "Other"

            event_stats = {}  # type -> {wins, losses, draws, total}
            for m in matches:
                cat = _classify_event(m.get("event_name"))
                bucket = event_stats.setdefault(
                    cat, {"wins": 0, "losses": 0, "draws": 0, "total": 0})
                bucket["total"] += 1
                result = (m.get("result") or "").lower()
                if result == "win":
                    bucket["wins"] += 1
                elif result == "loss":
                    bucket["losses"] += 1
                elif result == "draw":
                    bucket["draws"] += 1
            # Also keep a flat count for backward-compat with any other consumer
            event_types = {k: v["total"] for k, v in event_stats.items()}

            # Win rate trend over time
            from db.match_log import get_trend_data
            trend = get_trend_data(my_deck=active_deck, format_name=fmt_arg)

            return {"matches": matches, "stats": stats, "overall": overall,
                    "meta_wrs": meta_wrs, "event_types": dict(event_types),
                    "event_stats": event_stats,
                    "trend": trend,
                    "active_deck": active_deck, "active_format": fmt_arg}

        w = DataLoadWorker(_do)
        w.result.connect(self._on_data)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_data(self, data):
        self._matches = data["matches"]
        self._active_deck = data.get("active_deck") or ""
        self._active_format = data.get("active_format") or "modern"
        self._populate_table(data["matches"])
        self._populate_stats(data["stats"], data.get("meta_wrs", {}))
        ov = data["overall"]
        if ov["total"] > 0:
            self._summary_lbl.setText(
                f"{ov['wins']}W-{ov['losses']}L-{ov['draws']}D  "
                f"({ov['wr']*100:.0f}% WR, {ov['total']} matches)")
            stats = [
                f"{ov['total']} matches logged",
                f"{ov['wins']}W-{ov['losses']}L-{ov['draws']}D",
                f"{ov['wr']*100:.0f}% win rate",
            ]
            # data["stats"] is {opp_deck: {"wr", "total", ...}} per
            # db.match_log.get_matchup_stats — iterate items, not keys.
            best = data.get("stats", {})
            if best:
                qualified = [(opp, s) for opp, s in best.items()
                             if s.get("total", 0) >= 3]
                if qualified:
                    top_opp, top_stats = max(
                        qualified, key=lambda kv: kv[1].get("wr", 0))
                    stats.append(
                        f"Best: vs {top_opp} {top_stats['wr']*100:.0f}%")
            self._summary_bar.update("MATCH LOG", stats)
        else:
            self._summary_lbl.setText(
                "No matches logged yet \u2014 click 'Log Match' to record your first tournament result"
            )
            self._summary_bar.update("MATCH LOG", [
                "Track your results to see personal win rates vs each archetype",
            ])

        # Event type breakdown — now includes W/L per event category.
        event_stats = data.get("event_stats", {})
        if event_stats:
            parts = []
            # Sort by decisive-match volume descending so the heaviest-used
            # category shows first.
            ranked = sorted(event_stats.items(),
                            key=lambda kv: -(kv[1]["wins"] + kv[1]["losses"]))
            for cat, s in ranked:
                decisive = s["wins"] + s["losses"]
                if decisive == 0:
                    continue
                wr = round(s["wins"] / decisive * 100)
                draws = f"-{s['draws']}D" if s["draws"] else ""
                parts.append(f"{cat}: {s['wins']}W-{s['losses']}L{draws} ({wr}%)")
            self._event_lbl.setText(
                ("Events: " + " \u2022 ".join(parts)) if parts else ""
            )
        else:
            self._event_lbl.setText("")

        # Win rate trend chart
        trend = data.get("trend", [])
        self._draw_trend(trend)

    def _on_matches_menu(self, pos):
        """Right-click on a logged match row → 'Simulate this matchup'."""
        if self._on_simulate_matchup is None:
            return
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(getattr(self, "_matches", [])):
            return
        m = self._matches[row]
        my_deck = (m.get("my_deck") or "").strip()
        opp_deck = (m.get("opp_deck") or "").strip()
        fmt = (m.get("format") or "modern").lower()
        if not my_deck or not opp_deck:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self._table)
        act = menu.addAction(f"Simulate: {my_deck} vs {opp_deck}")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is act:
            try:
                self._on_simulate_matchup(my_deck, opp_deck, fmt)
            except Exception:
                pass

    def _on_stats_menu(self, pos):
        """Right-click on a matchup-stats row → 'Simulate this matchup'."""
        if self._on_simulate_matchup is None:
            return
        row = self._stats_table.rowAt(pos.y())
        if row < 0:
            return
        opp_item = self._stats_table.item(row, 0)
        if opp_item is None:
            return
        opp_deck = opp_item.text().strip()
        my_deck = getattr(self, "_active_deck", "") or ""
        fmt = getattr(self, "_active_format", "modern") or "modern"
        if not my_deck or not opp_deck:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self._stats_table)
        act = menu.addAction(f"Simulate: {my_deck} vs {opp_deck}")
        chosen = menu.exec(self._stats_table.viewport().mapToGlobal(pos))
        if chosen is act:
            try:
                self._on_simulate_matchup(my_deck, opp_deck, fmt)
            except Exception:
                pass

    def _populate_table(self, matches):
        self._table.setRowCount(len(matches))
        for ri, m in enumerate(matches):
            self._table.setItem(ri, 0, QTableWidgetItem(m.get("event_date", "")[:10]))
            self._table.setItem(ri, 1, QTableWidgetItem(m.get("event_name", "")))
            rd_item = QTableWidgetItem(str(m.get("round", "")))
            rd_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 2, rd_item)
            self._table.setItem(ri, 3, QTableWidgetItem(m.get("my_deck", "")))
            self._table.setItem(ri, 4, QTableWidgetItem(m.get("opp_deck", "")))

            result = m.get("result", "")
            r_item = QTableWidgetItem(result.upper() if result else "")
            if result == "win":
                r_item.setForeground(QColor(theme.OK))
            elif result == "loss":
                r_item.setForeground(QColor(theme.ERR))
            r_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 5, r_item)

            pd = m.get("play_draw", "")
            pd_item = QTableWidgetItem("P" if pd == "play" else ("D" if pd == "draw" else ""))
            pd_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 6, pd_item)

            games = []
            for g in ("g1_result", "g2_result", "g3_result"):
                gr = m.get(g, "")
                if gr == "win":
                    games.append("W")
                elif gr == "loss":
                    games.append("L")
            self._table.setItem(ri, 7, QTableWidgetItem("-".join(games) if games else ""))

            # Swap column: icon if the match has swap notes; color by verdict.
            swap_notes = (m.get("swap_notes") or "").strip()
            verdict = (m.get("swap_verdict") or "").strip()
            if swap_notes:
                if verdict == "kept":
                    symbol, color = "\u2713", theme.OK    # check
                elif verdict == "reverted":
                    symbol, color = "\u2717", theme.ERR   # cross
                else:
                    symbol, color = "\u2219", theme.TEXT_DIM  # bullet
                swap_item = QTableWidgetItem(symbol)
                swap_item.setForeground(QColor(color))
                swap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                swap_item.setToolTip(
                    f"{swap_notes}"
                    + (f"\nVerdict: {verdict}" if verdict else "")
                )
            else:
                swap_item = QTableWidgetItem("")
            self._table.setItem(ri, 8, swap_item)

            # Store match id
            self._table.item(ri, 0).setData(Qt.ItemDataRole.UserRole, m.get("id"))

    def _populate_stats(self, stats, meta_wrs=None):
        meta_wrs = meta_wrs or {}
        sorted_stats = sorted(stats.items(), key=lambda x: -x[1]["total"])
        self._stats_table.setRowCount(len(sorted_stats))
        for ri, (opp, s) in enumerate(sorted_stats):
            self._stats_table.setItem(ri, 0, QTableWidgetItem(opp))

            record = f"{s['wins']}-{s['losses']}-{s['draws']}"
            self._stats_table.setItem(ri, 1, QTableWidgetItem(record))

            # Your WR
            wr_item = QTableWidgetItem(f"{s['wr']*100:.0f}%")
            if s["wr"] >= 0.55:
                wr_item.setForeground(QColor(theme.OK))
            elif s["wr"] <= 0.45:
                wr_item.setForeground(QColor(theme.ERR))
            wr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stats_table.setItem(ri, 2, wr_item)

            # Meta WR (from real match data)
            from analysis.archetypes import normalize as norm_arch
            meta_wr = meta_wrs.get(norm_arch(opp))
            if meta_wr is not None:
                meta_item = QTableWidgetItem(f"{meta_wr*100:.0f}%")
                meta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                meta_item.setForeground(QColor(theme.TEXT_DIM))
                self._stats_table.setItem(ri, 3, meta_item)

                # Delta: your WR minus meta WR
                delta = s["wr"] - meta_wr
                delta_item = QTableWidgetItem(f"{delta*100:+.0f}%")
                delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if delta >= 0.05:
                    delta_item.setForeground(QColor(theme.OK))
                elif delta <= -0.05:
                    delta_item.setForeground(QColor(theme.ERR))
                else:
                    delta_item.setForeground(QColor(theme.TEXT_DIM))
                self._stats_table.setItem(ri, 4, delta_item)
            else:
                self._stats_table.setItem(ri, 3, QTableWidgetItem("\u2014"))
                self._stats_table.setItem(ri, 4, QTableWidgetItem("\u2014"))

            play_text = f"{s['play_wr']*100:.0f}%" if s["play_wr"] is not None else "\u2014"
            pi = QTableWidgetItem(play_text)
            pi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stats_table.setItem(ri, 5, pi)

            draw_text = f"{s['draw_wr']*100:.0f}%" if s["draw_wr"] is not None else "\u2014"
            di = QTableWidgetItem(draw_text)
            di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stats_table.setItem(ri, 6, di)

            ct_item = QTableWidgetItem(str(s["total"]))
            ct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stats_table.setItem(ri, 7, ct_item)

    # ------------------------------------------------------------------
    # Trend chart
    # ------------------------------------------------------------------

    def _show_sb_advice(self):
        """Show SB advisor dialog for the user's most-played deck."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
        from PyQt6.QtGui import QColor

        # Determine user's deck from most recent matches
        deck = self._last_deck or ""
        fmt = self._last_format or "standard"
        if not deck:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "SB Advice", "Log some matches first so I know your deck.")
            return

        from analysis.matchup_advisor import get_advice
        try:
            advice = get_advice(deck, fmt)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "SB Advice", theme.friendly_error(e))
            return

        matchups = advice.get("matchups", [])
        if not matchups:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "SB Advice", advice.get("summary", "No data."))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"SB Advisor \u2014 {deck} ({fmt.capitalize()})")
        dlg.setMinimumSize(800, 500)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        from PyQt6.QtWidgets import QLabel
        summary = QLabel(advice.get("summary", ""))
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; padding: 6px;")
        layout.addWidget(summary)

        tbl = QTableWidget(len(matchups), 6)
        tbl.setHorizontalHeaderLabels([
            "Opponent", "Your WR", "Meta WR", "Delta", "Status", "Recommendation",
        ])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)

        _SEV_COLORS = {
            "critical": theme.ERR, "warning": theme.WARN,
            "ok": theme.TEXT_DIM, "strong": theme.OK,
        }
        _SEV_LABELS = {
            "critical": "CRITICAL", "warning": "Warning",
            "ok": "OK", "strong": "Strong",
        }

        for ri, m in enumerate(matchups):
            tbl.setItem(ri, 0, QTableWidgetItem(m["opponent"]))

            wr = QTableWidgetItem(f"{m['personal_wr']*100:.0f}%")
            wr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 1, wr)

            meta = m.get("meta_wr")
            mi = QTableWidgetItem(f"{meta*100:.0f}%" if meta else "\u2014")
            mi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 2, mi)

            d = m.get("delta")
            di = QTableWidgetItem(f"{d*100:+.0f}%" if d is not None else "\u2014")
            di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if d and d <= -0.05:
                di.setForeground(QColor(theme.ERR))
            elif d and d >= 0.05:
                di.setForeground(QColor(theme.OK))
            tbl.setItem(ri, 3, di)

            sev = m["severity"]
            si = QTableWidgetItem(_SEV_LABELS.get(sev, sev))
            si.setForeground(QColor(_SEV_COLORS.get(sev, theme.TEXT_DIM)))
            f = si.font()
            f.setBold(True)
            si.setFont(f)
            si.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 4, si)

            rec = QTableWidgetItem(m.get("suggestion", ""))
            rec.setToolTip(m.get("suggestion", ""))
            tbl.setItem(ri, 5, rec)

        layout.addWidget(tbl, 1)
        dlg.exec()

    # ------------------------------------------------------------------
    # Trend chart
    # ------------------------------------------------------------------

    def _draw_trend(self, trend: list):
        """Draw win rate trend on the embedded chart canvas."""
        fig = self._trend_canvas._fig
        fig.clear()
        if len(trend) < 2:
            ax = fig.add_subplot(111)
            ax.set_facecolor("#111219")
            fig.patch.set_facecolor("#111219")
            ax.text(0.5, 0.5, "Need 2+ events to show trend",
                    ha="center", va="center", color="#888", fontsize=9,
                    transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            self._trend_canvas._canvas.draw()
            return

        dates = [t["date"] for t in trend]
        daily_wr = [t["wr"] * 100 for t in trend]
        cum_wr = [t["cumulative_wr"] * 100 for t in trend]

        ax = fig.add_subplot(111)
        fig.patch.set_facecolor("#111219")
        ax.set_facecolor("#111219")

        x = range(len(dates))
        ax.bar(x, daily_wr, color="#5eb5cf", alpha=0.4, label="Event WR")
        ax.plot(x, cum_wr, color="#3cb44b", linewidth=2, marker="o",
                markersize=3, label="Cumulative WR")
        ax.axhline(y=50, color="#888", linestyle="--", linewidth=0.8, alpha=0.5)

        ax.set_xticks(list(x))
        ax.set_xticklabels([d[5:] for d in dates], rotation=45,
                           fontsize=7, color="#aaa")
        ax.set_ylabel("Win %", fontsize=8, color="#aaa")
        ax.tick_params(axis="y", labelsize=7, colors="#aaa")
        ax.set_ylim(0, 100)
        ax.legend(fontsize=7, loc="upper left",
                  facecolor="#111219", edgecolor="#555", labelcolor="#ccc")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color("#555")
        ax.spines["left"].set_color("#555")

        fig.tight_layout()
        self._trend_canvas._canvas.draw()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _add_match(self):
        dlg = _MatchDialog(self, default_event=self._last_event,
                           default_deck=self._last_deck,
                           default_format=self._last_format,
                           default_round=self._last_round)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["opp_deck"]:
            QMessageBox.warning(self, "Missing", "Enter opponent's deck.")
            return
        # Translate dialog keys to match save_match kwargs
        data["format_name"] = data.pop("format")
        data["round_num"] = data.pop("round")
        from db.match_log import save_match
        save_match(**data)
        # Remember for next entry
        self._last_event = data["event_name"]
        self._last_deck = data["my_deck"]
        self._last_format = data["format_name"]
        self._last_round = data["round_num"] + 1
        self._load_matches()

    def _edit_match(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._matches):
            return
        m = self._matches[row]
        dlg = _MatchDialog(self, match=m)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        data["format_name"] = data.pop("format")
        data["round_num"] = data.pop("round")
        from db.match_log import save_match
        save_match(**data, match_id=m["id"])
        self._load_matches()

    def _delete_match(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._matches):
            return
        m = self._matches[row]
        reply = QMessageBox.question(
            self, "Delete Match",
            f"Delete round {m.get('round', '?')} vs {m.get('opp_deck', '?')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        from db.match_log import delete_match
        delete_match(m["id"])
        self._load_matches()
