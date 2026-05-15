"""Match History panel for a saved deck.

Shows all match_log rows where my_deck_id matches the selected deck:
- Summary header (overall W-L, WR%, breakdown by ranked/unranked/other)
- Matchup aggregation table (per opp_deck: matches + W-L + WR%)
- Recent-matches table (last 50 chronologically, most recent first)

Used as the "Match History" sub-tab on the My Decks deck-detail panel.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

import gui.theme as theme


# Event-name classification reused from the headless module
# (so CLI scrapers don't have to import the GUI's Qt deps).
from analysis.auto_save_deck import classify_event as _classify_event


def _wr_color(wr_frac: float) -> QColor:
    pct = wr_frac * 100
    if pct >= 60:
        return QColor(80, 200, 100)
    if pct >= 52:
        return QColor(140, 200, 140)
    if pct >= 48:
        return QColor(200, 200, 200)
    if pct >= 40:
        return QColor(220, 140, 120)
    return QColor(230, 90, 70)


class DeckMatchHistory(QWidget):
    """Match history view for a single saved deck."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck_id: Optional[int] = None
        self._matches: list[dict] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM,
                                 theme.SPACE_SM, theme.SPACE_SM)
        outer.setSpacing(6)

        # ── Summary header ────────────────────────────────────────────
        self._summary = QLabel("Pick a deck to see its match history.")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; padding: 4px;"
        )
        outer.addWidget(self._summary)

        # ── Filter row ────────────────────────────────────────────────
        filt = QHBoxLayout()
        filt.setSpacing(8)
        filt.addWidget(QLabel("Filter:"))
        self._filter = QComboBox()
        self._filter.addItem("All matches", "all")
        self._filter.addItem("Ranked Bo3 only", "ranked-bo3")
        self._filter.addItem("Ranked Bo1 only", "ranked-bo1")
        self._filter.addItem("Ranked (any)", "ranked")
        self._filter.addItem("Unranked Bo3 / Direct", "unranked")
        self._filter.addItem("Limited (Sealed/Draft)", "limited")
        self._filter.addItem("Other / Paper / Manual", "other")
        self._filter.setFixedWidth(180)
        self._filter.currentIndexChanged.connect(self._render)
        filt.addWidget(self._filter)
        filt.addStretch()
        outer.addLayout(filt)

        # ── Matchup aggregation table ─────────────────────────────────
        mu_lbl = QLabel("<b>Matchup performance</b>")
        mu_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        outer.addWidget(mu_lbl)
        self._mu_tbl = QTableWidget(0, 5)
        self._mu_tbl.setHorizontalHeaderLabels(
            ["Opponent archetype", "Matches", "W", "L", "WR"]
        )
        self._mu_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._mu_tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._mu_tbl.verticalHeader().setVisible(False)
        self._mu_tbl.setAlternatingRowColors(False)
        self._mu_tbl.setSortingEnabled(True)
        hh = self._mu_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for ci in range(1, 5):
            hh.setSectionResizeMode(ci, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self._mu_tbl, 2)

        # ── Recent matches table ──────────────────────────────────────
        rm_lbl = QLabel("<b>Recent matches</b> "
                        f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
                        "(newest first, capped at 50)</span>")
        outer.addWidget(rm_lbl)
        self._rm_tbl = QTableWidget(0, 6)
        self._rm_tbl.setHorizontalHeaderLabels(
            ["Date", "Event", "vs Opponent", "Archetype", "Result", "P/D"]
        )
        self._rm_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._rm_tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._rm_tbl.verticalHeader().setVisible(False)
        self._rm_tbl.setAlternatingRowColors(False)
        self._rm_tbl.setSortingEnabled(True)
        hh2 = self._rm_tbl.horizontalHeader()
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh2.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self._rm_tbl, 3)
        self._rm_tbl.itemSelectionChanged.connect(self._on_recent_selection)

        # ── Per-match detail (game-by-game stats + SB plan) ───────────
        self._sb_lbl = QLabel(
            "<b>Match detail</b>  "
            f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
            "(click a Recent Matches row above; shows per-game life / "
            "turn count / mulligan + SB plan)</span>"
        )
        outer.addWidget(self._sb_lbl)
        self._sb_detail = QLabel(
            "<i style='color:#9aa3b8;'>No SB plan loaded.</i>"
        )
        self._sb_detail.setTextFormat(Qt.TextFormat.RichText)
        self._sb_detail.setWordWrap(True)
        self._sb_detail.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; padding: 6px; "
            f"font-size: 11px;"
        )
        self._sb_detail.setMinimumHeight(60)
        outer.addWidget(self._sb_detail, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_deck(self, deck_id: Optional[int]) -> None:
        """Switch to a different deck. None clears the panel."""
        self._deck_id = deck_id
        if deck_id is None:
            self._matches = []
            self._summary.setText("Pick a deck to see its match history.")
            self._mu_tbl.setRowCount(0)
            self._rm_tbl.setRowCount(0)
            return
        from db.match_log import get_matches
        try:
            self._matches = get_matches(my_deck_id=deck_id, limit=2000)
        except Exception as e:
            self._matches = []
            self._summary.setText(f"Could not load matches: {e}")
            return
        self._render()

    def refresh(self) -> None:
        """Reload from DB (after a new Sync Untapped or MTGA log import)."""
        self.set_deck(self._deck_id)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render(self) -> None:
        if not self._matches:
            self._summary.setText("No matches yet for this deck.")
            self._mu_tbl.setRowCount(0)
            self._rm_tbl.setRowCount(0)
            return

        cat = self._filter.currentData()
        if cat == "all":
            filtered = list(self._matches)
        elif cat == "ranked":
            filtered = [m for m in self._matches
                        if _classify_event(m.get("event_name") or "")
                        in ("ranked-bo3", "ranked-bo1")]
        else:
            filtered = [m for m in self._matches
                        if _classify_event(m.get("event_name") or "") == cat]

        self._render_summary(filtered)
        self._render_matchups(filtered)
        self._render_recent(filtered)

    def _render_summary(self, matches: list[dict]) -> None:
        total = len(matches)
        if total == 0:
            self._summary.setText("No matches in this filter.")
            return
        wins = sum(1 for m in matches if (m.get("result") or "").lower() == "win")
        losses = sum(1 for m in matches if (m.get("result") or "").lower() == "loss")
        draws = total - wins - losses
        wr = (100.0 * wins / (wins + losses)) if (wins + losses) else 0.0

        # Breakdown by category
        cats: dict[str, list[int]] = {}
        for m in self._matches:  # full set, not filtered
            c = _classify_event(m.get("event_name") or "")
            cats.setdefault(c, [0, 0, 0])
            r = (m.get("result") or "").lower()
            if r == "win":
                cats[c][0] += 1
            elif r == "loss":
                cats[c][1] += 1
            cats[c][2] += 1

        labels = {
            "ranked-bo3": "Ranked Bo3",
            "ranked-bo1": "Ranked Bo1",
            "unranked": "Unranked",
            "limited": "Limited",
            "other": "Other",
        }
        parts = []
        for key in ("ranked-bo3", "ranked-bo1", "unranked", "limited", "other"):
            w, l, n = cats.get(key, [0, 0, 0])
            if n == 0:
                continue
            sub_wr = (100.0 * w / (w + l)) if (w + l) else 0.0
            parts.append(f"{labels[key]} {w}-{l} ({sub_wr:.0f}%)")
        breakdown = " | ".join(parts) if parts else "no category breakdown"

        head = (f"<b style='color:{theme.ACCENT};font-size:14px;'>"
                f"{wins}-{losses}"
                f"{f'-{draws}' if draws else ''}"
                f"</b>  ({total} matches, {wr:.1f}% WR)")
        self._summary.setText(f"{head}<br/>"
                               f"<span style='color:{theme.TEXT_DIM};font-size:11px;'>"
                               f"{breakdown}</span>")
        self._summary.setTextFormat(Qt.TextFormat.RichText)

    def _render_matchups(self, matches: list[dict]) -> None:
        # Aggregate W-L per opp_deck
        agg: dict[str, list[int]] = {}
        for m in matches:
            opp = (m.get("opp_deck") or "").strip() or "(unknown)"
            agg.setdefault(opp, [0, 0])
            r = (m.get("result") or "").lower()
            if r == "win":
                agg[opp][0] += 1
            elif r == "loss":
                agg[opp][1] += 1
        rows = []
        for opp, (w, l) in agg.items():
            n = w + l
            if n == 0:
                continue
            wr = w / n
            rows.append((opp, n, w, l, wr))
        # Sort by matches desc
        rows.sort(key=lambda r: (-r[1], r[0]))

        self._mu_tbl.setSortingEnabled(False)
        self._mu_tbl.setRowCount(len(rows))
        for ri, (opp, n, w, l, wr) in enumerate(rows):
            self._mu_tbl.setItem(ri, 0, QTableWidgetItem(opp))
            for ci, v in ((1, n), (2, w), (3, l)):
                cell = QTableWidgetItem(str(v))
                cell.setData(Qt.ItemDataRole.UserRole, v)  # numeric sort key
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._mu_tbl.setItem(ri, ci, cell)
            wr_cell = QTableWidgetItem(f"{wr*100:.0f}%")
            wr_cell.setData(Qt.ItemDataRole.UserRole, wr)
            wr_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            wr_cell.setForeground(_wr_color(wr))
            self._mu_tbl.setItem(ri, 4, wr_cell)
        self._mu_tbl.setSortingEnabled(True)

    def _render_recent(self, matches: list[dict]) -> None:
        # Already newest-first from get_matches; cap at 50
        view = matches[:50]
        self._rm_tbl.setSortingEnabled(False)
        self._rm_tbl.setRowCount(len(view))
        for ri, m in enumerate(view):
            date_cell = QTableWidgetItem(str(m.get("event_date") or ""))
            # Stash the match_log row id on the date cell so the SB-plan
            # detail handler can look up the right plan.
            date_cell.setData(Qt.ItemDataRole.UserRole, m.get("id"))
            self._rm_tbl.setItem(ri, 0, date_cell)
            self._rm_tbl.setItem(ri, 1, QTableWidgetItem(str(m.get("event_name") or "")))
            self._rm_tbl.setItem(ri, 2, QTableWidgetItem(str(m.get("opp_name") or "")))
            self._rm_tbl.setItem(ri, 3, QTableWidgetItem(str(m.get("opp_deck") or "")))
            res = (m.get("result") or "").lower()
            res_cell = QTableWidgetItem(res.upper() or "-")
            res_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if res == "win":
                res_cell.setForeground(QColor(80, 200, 100))
            elif res == "loss":
                res_cell.setForeground(QColor(230, 90, 70))
            self._rm_tbl.setItem(ri, 4, res_cell)
            pd = (m.get("play_draw") or "").strip()
            self._rm_tbl.setItem(ri, 5, QTableWidgetItem(pd))
        self._rm_tbl.setSortingEnabled(True)

    def _on_recent_selection(self) -> None:
        sel = self._rm_tbl.selectedItems()
        if not sel:
            return
        row = sel[0].row()
        cell = self._rm_tbl.item(row, 0)
        if cell is None:
            return
        match_log_id = cell.data(Qt.ItemDataRole.UserRole)
        if match_log_id is None:
            self._sb_detail.setText("<i style='color:#9aa3b8;'>No match id.</i>")
            return

        # Pull match-level info to know per-game W/L outcomes
        match_row = next((m for m in self._matches if m.get("id") == match_log_id),
                         None)
        g_results = {}
        if match_row:
            for gn, key in ((1, "g1_result"), (2, "g2_result"), (3, "g3_result")):
                r = (match_row.get(key) or "").lower()
                if r:
                    g_results[gn] = r

        parts = []

        # Per-game stats (life, mulligan, turn count, decisive-vs-close)
        try:
            from db.match_games import get_stats_for_match, classify_game
            games = get_stats_for_match(match_log_id)
        except Exception as e:
            games = []
            parts.append(f"<i style='color:#e07060;'>Game stats lookup failed: {e}</i>")
        if games:
            for g in games:
                gn = g["game_num"]
                gres = g_results.get(gn, "")
                my_won = (gres == "win")
                klass = classify_game(g, my_won)
                klass_color = {"blowout": "#80c890", "close": "#e0a060",
                               "normal": "#9aa3b8"}.get(klass, "#9aa3b8")
                gres_label = ("<span style='color:#80c890;'>W</span>" if gres == "win"
                              else "<span style='color:#d88060;'>L</span>"
                              if gres == "loss" else "-")
                my_life = max(0, g.get("my_life_end") or 0)
                opp_life = max(0, g.get("opp_life_end") or 0)
                turns = g.get("n_turns") or 0
                mull = g.get("my_mull_to") or 7
                mull_str = f"keep 7" if mull == 7 else f"mull to {mull}"
                opp_mull = g.get("opp_mull_to") or 7
                opp_mull_str = "" if opp_mull == 7 else f" opp mull-{opp_mull}"
                parts.append(
                    f"<b>Game {gn}</b> {gres_label} "
                    f"<span style='color:{klass_color};font-size:10px;'>"
                    f"&#9679; {klass}</span> "
                    f"&nbsp;<span style='color:#9aa3b8;font-size:11px;'>"
                    f"T{turns} &middot; {mull_str}{opp_mull_str} &middot; "
                    f"my life {my_life} / opp life {opp_life}</span>"
                )

        # Per-game sideboard plans
        try:
            from db.match_sb_plans import get_plans_for_match
            plans = get_plans_for_match(match_log_id)
        except Exception as e:
            plans = []
            parts.append(f"<i style='color:#e07060;'>SB plan lookup failed: {e}</i>")
        for p in plans:
            in_str = ", ".join(
                f"<span style='color:#80c890;'>+{q} {n}</span>"
                for n, q in sorted(p["cards_in"].items(), key=lambda kv: (-kv[1], kv[0]))
            ) or "<i>(no cards in)</i>"
            out_str = ", ".join(
                f"<span style='color:#d88060;'>-{q} {n}</span>"
                for n, q in sorted(p["cards_out"].items(), key=lambda kv: (-kv[1], kv[0]))
            ) or "<i>(no cards out)</i>"
            parts.append(
                f"<b>SB plan G{p['from_game']} &rarr; G{p['to_game']}</b> "
                f"&nbsp;<span style='color:#9aa3b8;'>({p['n_swapped']} swapped)</span>"
                f"<br/>&nbsp;&nbsp;IN: {in_str}"
                f"<br/>&nbsp;&nbsp;OUT: {out_str}"
            )

        if not parts:
            self._sb_detail.setText(
                "<i style='color:#9aa3b8;'>No per-game data yet. "
                "(Match imported pre-feature, or Bo1 with no SB plan.)</i>"
            )
        else:
            self._sb_detail.setText("<br/><br/>".join(parts))
