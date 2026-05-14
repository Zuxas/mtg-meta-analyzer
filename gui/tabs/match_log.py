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
        self._my_deck.setEditable(False)
        # Populate from saved decks; item data = deck id, display = "Name (archetype)"
        self._my_deck.addItem("— select saved deck —", None)
        try:
            from db.saved_decks import get_decks
            for d in get_decks():
                label = f"{d['name']} ({d.get('archetype','?')})"
                self._my_deck.addItem(label, d["id"])
        except Exception:
            pass
        # Preselect from match.my_deck_id if editing
        if match and match.get("my_deck_id") is not None:
            target_id = match["my_deck_id"]
            for i in range(self._my_deck.count()):
                if self._my_deck.itemData(i) == target_id:
                    self._my_deck.setCurrentIndex(i)
                    break
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
            "my_deck_id": self._my_deck.currentData(),  # int or None
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
        from gui.worker_utils import stop_worker
        for w in self._workers:
            stop_worker(w)
        self._workers.clear()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)

        from gui.widgets.summary_bar import SummaryBar
        self._summary_bar = SummaryBar()
        outer.addWidget(self._summary_bar)

        # Live event banner — shows current standing, points, threshold,
        # and a 'Quick-log next round' button when an event is active.
        self._event_banner = QLabel("")
        self._event_banner.setWordWrap(True)
        self._event_banner.setStyleSheet(
            f"background: {theme.INFO_BG}; border-left: 4px solid {theme.ACCENT}; "
            f"padding: 8px 12px; border-radius: 3px; color: {theme.TEXT}; "
            f"font-size: 12px;"
        )
        self._event_banner.setTextFormat(Qt.TextFormat.RichText)
        self._event_banner.setOpenExternalLinks(False)
        self._event_banner.linkActivated.connect(self._on_banner_link)
        self._event_banner.setVisible(False)
        outer.addWidget(self._event_banner)

        # Orphan-resolution banner — visible when match_log has orphan rows
        self._orphan_banner = QLabel("")
        self._orphan_banner.setStyleSheet(
            f"background: #3a2a1a; border-left: 4px solid #e2a55c; "
            f"padding: 6px 10px; border-radius: 3px; color: {theme.TEXT}; "
            f"font-size: 11px;"
        )
        self._orphan_banner.setVisible(False)
        self._resolve_btn = QPushButton("Resolve…")
        self._resolve_btn.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"padding: 4px 10px; border-radius: 3px;"
        )
        self._resolve_btn.setVisible(False)
        self._resolve_btn.clicked.connect(self._on_resolve_clicked)
        banner_row = QHBoxLayout()
        banner_row.addWidget(self._orphan_banner, 1)
        banner_row.addWidget(self._resolve_btn)
        outer.addLayout(banner_row)

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
        self._filter_deck.setEditable(False)
        self._filter_deck.addItem("All decks", None)
        try:
            from db.saved_decks import get_decks
            for d in get_decks():
                self._filter_deck.addItem(f"{d['name']} ({d.get('archetype','?')})", d["id"])
        except Exception:
            pass
        self._filter_deck.setMinimumWidth(220)
        self._filter_deck.currentIndexChanged.connect(self._on_deck_filter_changed)
        filt.addWidget(self._filter_deck)
        filt.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
        filt.addWidget(self._summary_lbl)
        lv.addLayout(filt)

        # Match table
        self._table = QTableWidget()
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Event", "Rd", "My Deck", "vs", "Result", "P/D", "Games", "Var", "Swap"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
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

        self._post_event_btn = QPushButton(btn_icon("analyze"), "Post-Event")
        self._post_event_btn.setStyleSheet(theme.btn_secondary())
        self._post_event_btn.setToolTip(
            "Compare a completed event's actual matchups against the "
            "expected meta share and scraped real-match WR."
        )
        self._post_event_btn.clicked.connect(self._show_post_event)
        btn_row.addWidget(self._post_event_btn)

        self._sync_btn = QPushButton("Sync Untapped")
        self._sync_btn.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"padding: 6px 14px; border-radius: 4px;")
        self._sync_btn.setToolTip(
            "Pull new match_log rows from data/untapped/replays/. "
            "Same writer the M/W/F pipeline runs."
        )
        self._sync_btn.clicked.connect(self._on_sync_untapped)
        btn_row.addWidget(self._sync_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        btn_row.addWidget(self._status_lbl)
        btn_row.addStretch()
        lv.addLayout(btn_row)

        splitter.addWidget(left)

        # Right side: variant timeline panel (replaces previous matchup-stats
        # table + SB Advice + trend chart per design 2026-05-13 Option C)
        from gui.widgets.variant_timeline import VariantTimelinePanel
        self._timeline = VariantTimelinePanel()
        splitter.addWidget(self._timeline)
        splitter.setSizes([700, 300])
        splitter.setCollapsible(1, True)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_matches(self):
        fmt = self._filter_fmt.currentText()
        fmt_arg = None if fmt == "All" else fmt
        deck_id = self._filter_deck.currentData()

        def _do():
            from db.match_log import get_matches, get_overall_stats
            matches = get_matches(format_name=fmt_arg, my_deck_id=deck_id)
            overall = {"wins": 0, "losses": 0, "draws": 0, "total": 0, "wr": 0}

            # Determine active_deck name for summary bar
            active_deck = None
            if deck_id is not None:
                try:
                    from db.saved_decks import get_decks
                    d = next((x for x in get_decks() if x["id"] == deck_id), None)
                    if d:
                        active_deck = d.get("archetype") or d.get("name")
                except Exception:
                    pass
            if active_deck is None and matches:
                from collections import Counter
                decks = Counter(m["my_deck"] for m in matches if m.get("my_deck"))
                if decks:
                    active_deck = decks.most_common(1)[0][0]

            if active_deck:
                overall = get_overall_stats(my_deck=active_deck, format_name=fmt_arg)

            return {"matches": matches, "overall": overall,
                    "active_deck": active_deck, "active_format": fmt_arg}

        w = DataLoadWorker(_do)
        w.result.connect(self._on_data)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)
        self._refresh_orphan_banner()

    def _on_data(self, data):
        self._matches = data["matches"]
        self._active_deck = data.get("active_deck") or ""
        self._active_format = data.get("active_format") or "modern"
        self._populate_table(data["matches"])
        self._refresh_event_banner()
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
            self._summary_bar.update("MATCH LOG", stats)
        else:
            self._summary_lbl.setText(
                "No matches logged yet — click 'Log Match' to record your first tournament result"
            )
            self._summary_bar.update("MATCH LOG", [
                "Track your results to see personal win rates vs each archetype",
            ])

    # ------------------------------------------------------------------
    # Deck filter + timeline sync
    # ------------------------------------------------------------------

    def _on_deck_filter_changed(self, _index: int) -> None:
        """Re-filter table AND update the variant timeline."""
        deck_id = self._filter_deck.currentData()
        self._timeline.set_deck(deck_id)
        self._load_matches()

    # ------------------------------------------------------------------
    # Untapped sync
    # ------------------------------------------------------------------

    def _on_sync_untapped(self) -> None:
        """Trigger the Untapped match_log writer ad-hoc."""
        self._status_lbl.setText("Syncing Untapped replays...")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            from scrapers.untapped_match_log_writer import run as _utw_run
            n = _utw_run()
            self._status_lbl.setText(f"Sync complete: {n} new rows.")
        except Exception as e:
            self._status_lbl.setText(f"Sync error: {e}")
        self._load_matches()
        deck_id = self._filter_deck.currentData()
        if deck_id is not None:
            self._timeline.set_deck(deck_id)

    def _refresh_orphan_banner(self) -> None:
        from db.database import get_connection
        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM match_log "
                "WHERE backfill_status='orphan' AND my_deck_id IS NULL"
            ).fetchone()[0]
        if n > 0:
            self._orphan_banner.setText(
                f"⚠ {n} historical match{'es' if n != 1 else ''} need a deck"
            )
            self._orphan_banner.setVisible(True)
            self._resolve_btn.setVisible(True)
        else:
            self._orphan_banner.setVisible(False)
            self._resolve_btn.setVisible(False)

    def _on_resolve_clicked(self) -> None:
        from gui.widgets.orphan_resolver import OrphanResolverDialog
        dlg = OrphanResolverDialog(parent=self)
        dlg.exec()
        self._load_matches()
        self._refresh_orphan_banner()
        deck_id = self._filter_deck.currentData()
        if deck_id is not None:
            self._timeline.set_deck(deck_id)

    def _show_post_event(self):
        """Open the PostEventDialog with the currently-loaded matches."""
        if not getattr(self, "_matches", []):
            QMessageBox.information(self, "No matches",
                                     "Log some matches first.")
            return
        from gui.widgets.post_event_dialog import PostEventDialog
        dlg = PostEventDialog(self, matches=self._matches)
        dlg.exec()

    # ------------------------------------------------------------------
    # Live event banner (round tracking)
    # ------------------------------------------------------------------

    def _refresh_event_banner(self):
        """Group the most recently-logged matches by event name and show the
        current event's live standing: W-L-D, points, cut threshold, next
        round number."""
        matches = getattr(self, "_matches", []) or []
        if not matches:
            self._event_banner.setVisible(False)
            return
        # Most recent event = event_name of the newest match (they're sorted
        # DESC by date/id by get_matches).
        newest = matches[0]
        event_name = (newest.get("event_name") or "").strip()
        if not event_name:
            self._event_banner.setVisible(False)
            return

        same_event = [m for m in matches
                      if (m.get("event_name") or "").strip() == event_name]
        rounds_played = len(same_event)
        wins = sum(1 for m in same_event if (m.get("result") or "").lower() == "win")
        losses = sum(1 for m in same_event if (m.get("result") or "").lower() == "loss")
        draws = sum(1 for m in same_event if (m.get("result") or "").lower() == "draw")
        points = wins * 3 + draws

        # Next-round lookup: the max round in same_event + 1
        next_round = max(((m.get("round") or 0) for m in same_event), default=0) + 1
        fmt = (newest.get("format") or "modern")
        my_deck = (newest.get("my_deck") or "").strip()

        # Threshold heuristic based on rounds played:
        #   — up to 4 rounds ⇒ assume 5-round RCQ (cut at 9 pts / top 4)
        #   — 5–7 rounds     ⇒ assume 7-round event (cut at 15 pts / top 8)
        #   — 8+ rounds      ⇒ assume 9-round RC / Pro Tour (cut at 18 pts)
        if rounds_played <= 4:
            threshold, top_cut = 9, 4
        elif rounds_played <= 7:
            threshold, top_cut = 15, 8
        else:
            threshold, top_cut = 18, 8

        status_color = theme.OK if points >= threshold else (
            theme.WARN if points >= threshold - 3 else theme.TEXT_DIM
        )
        status = ("✓ at / above cut threshold"
                  if points >= threshold
                  else f"need {threshold - points} more pts for top {top_cut}")

        lines = [
            f"<b style='color:{theme.ACCENT};'>Active event: {event_name}</b>"
            f"  <span style='color:{theme.TEXT_DIM};'>({fmt}"
            + (f" · {my_deck}" if my_deck else "") + ")</span>",
            f"Record: <b>{wins}-{losses}-{draws}</b> · Points: <b>{points}</b> · "
            f"<span style='color:{status_color};'>{status}</span> · "
            f"<a href='next' style='color:{theme.ACCENT};'>Log round {next_round} →</a>",
        ]
        self._event_banner.setText("<br>".join(lines))
        self._event_banner.setVisible(True)

    def _on_banner_link(self, href: str):
        """Banner link clicks — 'next' opens _MatchDialog pre-filled for the
        next round of the active event."""
        if href != "next":
            return
        matches = getattr(self, "_matches", []) or []
        if not matches:
            return
        newest = matches[0]
        event_name = (newest.get("event_name") or "").strip()
        same_event = [m for m in matches
                      if (m.get("event_name") or "").strip() == event_name]
        next_round = max(((m.get("round") or 0) for m in same_event), default=0) + 1
        # Reuse _add_match's dialog path but seed the defaults
        self._last_event = event_name
        self._last_deck = (newest.get("my_deck") or "").strip()
        self._last_format = newest.get("format") or "modern"
        self._last_round = next_round
        self._add_match()

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
            var_short = (m.get("my_variant_hash") or "")[:4]
            var_item = QTableWidgetItem(var_short)
            var_item.setForeground(QColor("#5fa8d3"))
            self._table.setItem(ri, 8, var_item)

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
            self._table.setItem(ri, 9, swap_item)

            # Store match id
            self._table.item(ri, 0).setData(Qt.ItemDataRole.UserRole, m.get("id"))

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
        # Translate dialog keys to match resolve_and_save kwargs
        format_name = data.pop("format")
        round_num = data.pop("round")
        from db.match_log import resolve_and_save
        resolve_and_save(
            event_name=data["event_name"],
            event_date=data["event_date"],
            format_name=format_name,
            round_num=round_num,
            my_deck_id=data["my_deck_id"],
            opp_deck=data["opp_deck"],
            opp_name=data["opp_name"],
            result=data["result"],
            play_draw=data["play_draw"],
            g1_result=data["g1_result"],
            g2_result=data["g2_result"],
            g3_result=data["g3_result"],
            notes=data["notes"],
            source="manual",
        )
        # Remember for next entry
        self._last_event = data["event_name"]
        self._last_format = format_name
        self._last_round = round_num + 1
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
        format_name = data.pop("format")
        round_num = data.pop("round")
        # my_deck_id is in data but save_match uses the legacy my_deck string;
        # preserve the existing my_deck value from the stored row for the edit path.
        data.pop("my_deck_id", None)
        from db.match_log import save_match
        save_match(
            event_name=data["event_name"],
            event_date=data["event_date"],
            format_name=format_name,
            round_num=round_num,
            my_deck=m.get("my_deck", ""),
            opp_deck=data["opp_deck"],
            opp_name=data["opp_name"],
            result=data["result"],
            play_draw=data["play_draw"],
            g1_result=data["g1_result"],
            g2_result=data["g2_result"],
            g3_result=data["g3_result"],
            notes=data["notes"],
            swap_notes=data["swap_notes"],
            swap_verdict=data["swap_verdict"],
            match_id=m["id"],
        )
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
