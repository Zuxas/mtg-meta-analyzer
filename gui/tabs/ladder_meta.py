"""
gui/tabs/ladder_meta.py -- MTGA-ladder meta view

Surfaces Untapped.gg data that the paper-tournament-focused tabs don't:

  1. Mythic Leaderboard     -- top 30 ladder players + their decks + WR
  2. Skill Curve            -- Bo1 ladder archetype WR by rank tier
                               (Bronze/Silver/Gold/Platinum) + climb delta.
                               Positive delta = archetype scales with skill.
  3. Mythic Archetype Roll  -- how the top of ladder splits by color combo

Format selector: standard (Bo1 "Ladder") / pioneer / historic / timeless /
alchemy. Modern / legacy / pauper are not on MTGA -- those formats show an
empty state.

Skill curve uses Bo1 data because Untapped only reports per-tier win
rate in Bo1 ("Ladder", "Explorer_Ladder", etc.).  Bo3 ("Traditional_*")
rows have NULL win_rate at all tiers, only match counts.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QSplitter, QListWidget, QListWidgetItem, QInputDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


class LadderMetaTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM,
                                 theme.SPACE_SM, theme.SPACE_SM)
        outer.setSpacing(6)

        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setStyleSheet(
            f"background: {theme.PANEL}; border-radius: 4px; padding: 2px;"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(theme.SPACE_SM)

        tl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "historic",
                            "timeless", "alchemy"])
        self._fmt.setFixedWidth(110)
        self._fmt.currentIndexChanged.connect(lambda _: self.refresh())
        tl.addWidget(self._fmt)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_btn.setToolTip(
            "Re-query the local Untapped tables. "
            "New data is pulled by the M/W/F nightly scrape "
            "(scripts/run_fill_from_prefs.py)."
        )
        self._refresh_btn.clicked.connect(self.refresh)
        tl.addWidget(self._refresh_btn)

        self._fetch_dl_btn = QPushButton("↻ Fetch decklists")
        self._fetch_dl_btn.setStyleSheet(theme.btn_secondary())
        self._fetch_dl_btn.setToolTip(
            "Extract mainboard + sideboard from every locally-stored "
            "Untapped replay (data/untapped/replays/). No network calls -- "
            "pulls from the corpus the replay fetcher already downloaded. "
            "After fetch, click any Mythic leaderboard row below to see "
            "that player's decklist."
        )
        self._fetch_dl_btn.clicked.connect(self._on_fetch_decklists)
        tl.addWidget(self._fetch_dl_btn)

        tl.addStretch()
        self._as_of = QLabel("")
        self._as_of.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        tl.addWidget(self._as_of)
        outer.addWidget(toolbar)

        # ── Empty/status note ─────────────────────────────────────────
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; padding: 8px;"
        )
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._status)

        # ── Mythic archetype rollup (compact summary) ─────────────────
        rollup_lbl = QLabel("<b>Mythic ladder archetype split</b>")
        rollup_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        outer.addWidget(rollup_lbl)
        self._rollup_tbl = QTableWidget(0, 5)
        self._rollup_tbl.setHorizontalHeaderLabels(
            ["Color combo", "Colors", "Players", "Matches", "Weighted WR"]
        )
        self._rollup_tbl.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._rollup_tbl.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._rollup_tbl.verticalHeader().setVisible(False)
        self._rollup_tbl.setAlternatingRowColors(False)
        self._rollup_tbl.setFixedHeight(190)
        hh = self._rollup_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self._rollup_tbl)

        # ── Splitter: Skill Curve | Mythic Leaderboard ────────────────
        split = QSplitter(Qt.Orientation.Horizontal)

        # Skill curve panel
        sc_wrap = QWidget()
        sc_v = QVBoxLayout(sc_wrap)
        sc_v.setContentsMargins(0, 0, 0, 0)
        sc_v.setSpacing(2)
        sc_lbl = QLabel(
            "<b>Skill curve</b>  "
            "<span style='color:%s;font-size:10px;'>"
            "(Bronze → Mythic; Br-Go hide on narrow windows)</span>" % theme.TEXT_DIM
        )
        sc_lbl.setStyleSheet("font-size: 11px;")
        sc_v.addWidget(sc_lbl)
        self._skill_tbl = QTableWidget(0, 8)
        self._skill_tbl.setHorizontalHeaderLabels(
            ["Archetype", "Bronze", "Silver", "Gold",
             "Platinum", "Diamond", "Mythic", "Δ Br→My"]
        )
        self._skill_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._skill_tbl.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._skill_tbl.verticalHeader().setVisible(False)
        self._skill_tbl.setAlternatingRowColors(False)
        # Sort disabled -- Mythic-having archetypes pinned to top
        self._skill_tbl.setSortingEnabled(False)
        self._skill_tbl.setToolTip(
            "Bronze / Silver / Gold = Bo1 endpoint (only source for those tiers)\n"
            "Platinum / Diamond / Mythic = Bo3 premium endpoint\n"
            "Δ Br→My = WR change from Bronze to Mythic (full skill scaling)\n"
            "         positive = deck scales up with skill\n"
            "         negative = deck weaker at high ranks\n"
            "\n"
            "Mythic only has data for top ~2 archetypes per snapshot.\n"
            "Br/Si/Go columns auto-hide when the panel is narrower than 540px."
        )
        hh2 = self._skill_tbl.horizontalHeader()
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci in range(1, 8):
            hh2.setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)
        sc_v.addWidget(self._skill_tbl, 1)
        split.addWidget(sc_wrap)

        # Mythic leaderboard panel
        lb_wrap = QWidget()
        lb_v = QVBoxLayout(lb_wrap)
        lb_v.setContentsMargins(0, 0, 0, 0)
        lb_v.setSpacing(2)
        lb_lbl = QLabel(
            "<b>Mythic leaderboard</b>  "
            "<span style='color:%s;font-size:10px;'>"
            "(top 30 of ladder snapshot)</span>" % theme.TEXT_DIM
        )
        lb_lbl.setStyleSheet("font-size: 11px;")
        lb_v.addWidget(lb_lbl)
        self._lb_tbl = QTableWidget(0, 5)
        self._lb_tbl.setHorizontalHeaderLabels(
            ["Rank", "Player", "Archetype", "Matches", "WR"]
        )
        self._lb_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._lb_tbl.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._lb_tbl.verticalHeader().setVisible(False)
        self._lb_tbl.setAlternatingRowColors(False)
        self._lb_tbl.setSortingEnabled(True)
        self._lb_tbl.setToolTip(
            "Double-click a row to open that player's deck on Untapped.gg.\n"
            "Right-click for more actions."
        )
        self._lb_tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._lb_tbl.customContextMenuRequested.connect(self._on_lb_context_menu)
        self._lb_tbl.itemDoubleClicked.connect(self._on_lb_double_click)
        self._lb_tbl.itemSelectionChanged.connect(self._on_lb_selection_changed)
        hh3 = self._lb_tbl.horizontalHeader()
        hh3.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh3.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh3.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh3.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh3.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        lb_v.addWidget(self._lb_tbl, 1)

        # ── Decklist panel below the leaderboard table ────────────────
        dl_header = QLabel(
            "<b>Decklist</b>  "
            "<span style='color:%s;font-size:10px;'>"
            "(click a leaderboard row above; ↻ Fetch decklists to populate)"
            "</span>" % theme.TEXT_DIM
        )
        dl_header.setStyleSheet("font-size: 11px;")
        lb_v.addWidget(dl_header)
        dl_row = QHBoxLayout()
        dl_row.setSpacing(4)
        dl_row.setContentsMargins(0, 0, 0, 0)
        self._mb_list = QListWidget()
        self._mb_list.setToolTip("Mainboard (60 cards typical)")
        self._sb_list = QListWidget()
        self._sb_list.setToolTip("Sideboard (15 cards typical)")
        self._mb_list.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; font-size: 11px;"
        )
        self._sb_list.setStyleSheet(self._mb_list.styleSheet())
        dl_row.addWidget(self._mb_list, 3)
        dl_row.addWidget(self._sb_list, 2)
        dl_wrap = QWidget()
        dl_wrap.setLayout(dl_row)
        dl_wrap.setMinimumHeight(160)
        lb_v.addWidget(dl_wrap, 0)
        split.addWidget(lb_wrap)

        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self):
        try:
            from db.untapped_queries import (
                get_skill_curve, get_mythic_leaderboard,
                get_mythic_archetype_rollup, get_bo3_tier_wrs,
            )
        except Exception as exc:
            self._status.setText(f"Untapped tables not available: {exc}")
            return

        fmt = self._fmt.currentText()

        rollup = get_mythic_archetype_rollup(limit=12, format_name=fmt)
        # Br/Si/Go from Bo1 endpoint (only source). Plat/Diamond/Mythic from Bo3 premium.
        bo1_rows = get_skill_curve(fmt, limit=60, min_plat_matches=50)
        if not bo1_rows and fmt != "standard":
            bo1_rows = get_skill_curve(fmt, limit=60, min_plat_matches=20)
        bo3_wrs = get_bo3_tier_wrs(fmt)

        bo1_by_arch = {r.get("archetype_name"): r for r in bo1_rows}
        all_archs = set(bo1_by_arch.keys()) | set(bo3_wrs.keys())

        skill = []
        for arch in all_archs:
            b1 = bo1_by_arch.get(arch) or {}
            b3 = bo3_wrs.get(arch) or {}
            plat_matches = (b3.get("plat_matches") or 0) or (b1.get("plat_matches") or 0)
            if plat_matches < 50:
                continue
            skill.append({
                "archetype_name": arch,
                "bronze_wr":  b1.get("bronze_wr"),
                "silver_wr":  b1.get("silver_wr"),
                "gold_wr":    b1.get("gold_wr"),
                # Plat: prefer Bo3 (premium), fall back to Bo1
                "plat_wr":    b3.get("plat_wr") if b3.get("plat_wr") is not None else b1.get("plat_wr"),
                "diamond_wr": b3.get("diamond_wr"),
                "mythic_wr":  b3.get("mythic_wr"),
            })

        # Sort: Mythic-having archetypes pinned to top, then descending WR
        def _sort_key(r):
            for k in ("mythic_wr", "diamond_wr", "plat_wr"):
                if r.get(k) is not None:
                    return (-1 if k == "mythic_wr" else (0 if k == "diamond_wr" else 1), -r[k])
            return (2, 0)
        skill.sort(key=_sort_key)
        board  = get_mythic_leaderboard(limit=30, format_name=fmt)

        if not (rollup or skill or board):
            self._status.setText(
                "No Untapped data scraped yet.  Run "
                "`python -m scrapers.untapped_mythic_scraper` and "
                "`python -m scrapers.untapped_meta_scraper` first "
                "(or wait for the M/W/F nightly scrape)."
            )
            self._status.setVisible(True)
        else:
            self._status.setVisible(False)

        # As-of timestamp from rollup
        as_of = rollup[0]["as_of_utc"][:10] if rollup else ""
        self._as_of.setText(f"snapshot: {as_of}" if as_of else "")

        self._fill_rollup(rollup)
        self._fill_skill(skill, fmt)
        self._fill_leaderboard(board)

    # ------------------------------------------------------------------
    # Table fill helpers
    # ------------------------------------------------------------------

    def _fill_rollup(self, rows: list):
        self._rollup_tbl.setSortingEnabled(False)
        self._rollup_tbl.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            self._rollup_tbl.setItem(ri, 0,
                QTableWidgetItem(r["archetype"] or "(unknown)"))
            self._rollup_tbl.setItem(ri, 1,
                QTableWidgetItem(r["colors"] or ""))
            n_players = QTableWidgetItem(str(r["n_players"]))
            n_players.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rollup_tbl.setItem(ri, 2, n_players)
            n_matches = QTableWidgetItem(f"{r['total_matches']:,}")
            n_matches.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rollup_tbl.setItem(ri, 3, n_matches)
            wr = r["weighted_wr"]
            wr_item = QTableWidgetItem(f"{wr:.1f}%" if wr is not None else "—")
            wr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if wr is not None:
                wr_item.setForeground(_wr_color(wr / 100.0))
            self._rollup_tbl.setItem(ri, 4, wr_item)

    def _fill_skill(self, rows: list, fmt: str):
        self._skill_tbl.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            self._skill_tbl.setItem(ri, 0,
                QTableWidgetItem(r["archetype_name"]))
            # Tier cols 1-6: Bronze | Silver | Gold | Platinum | Diamond | Mythic
            for ci, key in enumerate(
                ["bronze_wr", "silver_wr", "gold_wr",
                 "plat_wr", "diamond_wr", "mythic_wr"], start=1
            ):
                v = r.get(key)
                cell = QTableWidgetItem(f"{v:.1f}%" if v is not None else "—")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if v is not None:
                    cell.setForeground(_wr_color(v / 100.0))
                self._skill_tbl.setItem(ri, ci, cell)
            # Climb delta col 7: Bronze -> Mythic (full skill scaling)
            b = r.get("bronze_wr")
            m = r.get("mythic_wr")
            if b is not None and m is not None:
                d = m - b
                d_item = QTableWidgetItem(f"{d:+.1f}")
                d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if d >= 5:
                    d_item.setForeground(QColor(80, 200, 100))
                elif d >= 2:
                    d_item.setForeground(QColor(140, 200, 140))
                elif d <= -5:
                    d_item.setForeground(QColor(230, 90, 70))
                elif d <= -2:
                    d_item.setForeground(QColor(220, 140, 120))
                else:
                    d_item.setForeground(QColor(theme.TEXT_DIM))
            else:
                d_item = QTableWidgetItem("—")
                d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._skill_tbl.setItem(ri, 7, d_item)
        self._update_skill_column_visibility()

    def _update_skill_column_visibility(self):
        """Hide Bronze/Silver/Gold columns when the panel is narrow."""
        wide = self._skill_tbl.viewport().width() >= 540
        for ci in (1, 2, 3):
            self._skill_tbl.setColumnHidden(ci, not wide)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_skill_tbl"):
            self._update_skill_column_visibility()

    def _fill_leaderboard(self, rows: list):
        self._lb_tbl.setSortingEnabled(False)
        self._lb_tbl.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            rank_item = QTableWidgetItem(str(r["rank_approx"] or ""))
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Stash the deck identifiers on the rank cell so right-click /
            # double-click handlers can build the Untapped URL without
            # re-querying the DB.
            rank_item.setData(Qt.ItemDataRole.UserRole,
                              {"user_id": r.get("user_id"),
                               "short_id": r.get("short_id"),
                               "player_name": r.get("player_name") or ""})
            self._lb_tbl.setItem(ri, 0, rank_item)
            self._lb_tbl.setItem(ri, 1,
                QTableWidgetItem(r["player_name"] or ""))
            arch = r["archetype_primary"] or ""
            if r["colors_str"]:
                arch_disp = f"{arch} ({r['colors_str']})"
            else:
                arch_disp = arch
            self._lb_tbl.setItem(ri, 2, QTableWidgetItem(arch_disp))
            m_item = QTableWidgetItem(str(r["matches_count"] or 0))
            m_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lb_tbl.setItem(ri, 3, m_item)
            wr = r["win_rate"]
            wr_item = QTableWidgetItem(f"{wr:.1f}%" if wr is not None else "—")
            wr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if wr is not None:
                wr_item.setForeground(_wr_color(wr / 100.0))
            self._lb_tbl.setItem(ri, 4, wr_item)
        self._lb_tbl.setSortingEnabled(True)

    def _open_deck_for_row(self, row_index: int) -> None:
        """Open the Untapped public deck page for the given leaderboard row."""
        item = self._lb_tbl.item(row_index, 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        from db.untapped_queries import untapped_deck_url
        url = untapped_deck_url(data.get("user_id"), data.get("short_id"))
        if not url:
            self._status.setText(
                f"No deck link available for {data.get('player_name','?')} "
                "(missing user_id / short_id in scrape)."
            )
            return
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))
        self._status.setText(f"Opened deck for {data.get('player_name','?')} in browser.")

    def _on_lb_double_click(self, item) -> None:
        self._open_deck_for_row(item.row())

    def _on_lb_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu, QApplication
        item = self._lb_tbl.itemAt(pos)
        if item is None:
            return
        row = item.row()
        data = self._lb_tbl.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
        player_name = data.get("player_name", "?")
        short_id = data.get("short_id")

        menu = QMenu(self)
        open_act = menu.addAction(f"Open {player_name}'s deck on Untapped.gg")
        copy_act = menu.addAction("Copy deck URL")
        save_act = menu.addAction(f"Save {player_name}'s deck to My Decks")
        # Only enable save when we have a stored decklist for this short_id
        from db.untapped_decklists import get_decklist
        save_act.setEnabled(short_id is not None and
                            get_decklist(short_id) is not None)
        action = menu.exec(self._lb_tbl.viewport().mapToGlobal(pos))

        from db.untapped_queries import untapped_deck_url
        url = untapped_deck_url(data.get("user_id"), short_id)

        if action is open_act:
            self._open_deck_for_row(row)
        elif action is copy_act:
            if url:
                QApplication.clipboard().setText(url)
                self._status.setText(f"Copied: {url}")
            else:
                self._status.setText(
                    "No deck link available (missing user_id / short_id)."
                )
        elif action is save_act:
            self._save_deck_for_row(row)

    def _on_lb_selection_changed(self) -> None:
        sel = self._lb_tbl.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        data = self._lb_tbl.item(row, 0).data(Qt.ItemDataRole.UserRole) or {}
        self._populate_decklist_panel(data.get("short_id"),
                                      data.get("player_name") or "?")

    def _populate_decklist_panel(self, short_id, player_name: str) -> None:
        self._mb_list.clear()
        self._sb_list.clear()
        if not short_id:
            self._mb_list.addItem("(no short_id for this row)")
            return
        from db.untapped_decklists import get_decklist
        dl = get_decklist(short_id)
        if dl is None:
            self._mb_list.addItem(
                f"No local decklist for {player_name} yet."
            )
            self._mb_list.addItem(
                "Click '↻ Fetch decklists' to populate from local replays."
            )
            return
        mb = dl.get("mainboard") or {}
        sb = dl.get("sideboard") or {}
        for name, qty in sorted(mb.items(), key=lambda kv: (-kv[1], kv[0])):
            self._mb_list.addItem(f"{qty}  {name}")
        if sb:
            for name, qty in sorted(sb.items(), key=lambda kv: (-kv[1], kv[0])):
                self._sb_list.addItem(f"{qty}  {name}")
        else:
            self._sb_list.addItem("(no sideboard in replay)")

    def _on_fetch_decklists(self) -> None:
        self._fetch_dl_btn.setEnabled(False)
        self._status.setText("Fetching decklists from local replays…")
        self._status.setVisible(True)

        def _do():
            from db.untapped_decklists import populate_for_all_local_replays
            return populate_for_all_local_replays(skip_existing=True)

        def _done(stats: dict):
            self._fetch_dl_btn.setEnabled(True)
            self._status.setText(
                f"Decklists: {stats['written']} written, "
                f"{stats['skipped_existing']} already cached, "
                f"{stats['missing_replay']} missing replay, "
                f"{stats['malformed']} malformed, "
                f"{stats['no_card_resolution']} unresolved."
            )
            self._on_lb_selection_changed()

        def _err(exc):
            self._fetch_dl_btn.setEnabled(True)
            self._status.setText(theme.friendly_error(exc))

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(_err)
        w.start()
        self._fetch_worker = w  # keep ref so it isn't GC'd

    def _save_deck_for_row(self, row_index: int) -> None:
        item = self._lb_tbl.item(row_index, 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        short_id = data.get("short_id")
        player_name = data.get("player_name") or "Mythic Player"
        from db.untapped_decklists import get_decklist
        dl = get_decklist(short_id) if short_id else None
        if dl is None:
            QMessageBox.information(
                self, "No decklist",
                "No local decklist for this player yet. "
                "Click '↻ Fetch decklists' first."
            )
            return

        # Look up the format from the current selector + archetype from row
        fmt = self._fmt.currentText()
        arch_item = self._lb_tbl.item(row_index, 2)
        arch_display = arch_item.text() if arch_item else ""
        # Strip the "(colors)" suffix from displayed archetype
        archetype = arch_display.split(" (")[0].strip() or "Unknown"

        default_name = f"{player_name} -- {archetype}"
        name, ok = QInputDialog.getText(
            self, "Save deck", "Save as:", text=default_name
        )
        if not ok or not name.strip():
            return

        from db.saved_decks import save_deck
        try:
            deck_id = save_deck(
                name=name.strip(),
                format_name=fmt,
                archetype=archetype,
                mainboard=dl["mainboard"],
                sideboard=dl["sideboard"] or {},
                notes=f"Imported from Untapped Mythic ladder. short_id={short_id}",
            )
            self._status.setText(
                f"Saved deck #{deck_id} '{name}' to My Decks."
            )
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))


def _wr_color(wr_frac: float) -> QColor:
    """Foreground color for a win-rate cell (wr_frac in 0..1)."""
    pct = wr_frac * 100
    if pct >= 60:
        return QColor(80, 220, 100)
    if pct >= 55:
        return QColor(120, 190, 130)
    if pct >= 45:
        return QColor(theme.TEXT)
    if pct >= 40:
        return QColor(220, 140, 120)
    return QColor(230, 90, 70)
