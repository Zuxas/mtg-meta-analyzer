"""
Sub-tab — Pre-Event Prep Checklist

Picks up one of your saved decks and shows an at-a-glance readiness
grid: for each top-N meta archetype, do I have an SB plan, what's my
real-match WR, what's my personal WR, am I ready for the matchup?

Green = ready (SB plan exists + positive WR); amber = plan exists but
bad matchup; red = no plan + relevant matchup (high meta share).
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QTextBrowser,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


class PrepChecklistTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._decks = []
        self._current_deck = None
        self._workers = []
        self._build_ui()
        self._load_decks()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                theme.SPACE_MD, theme.SPACE_MD)
        lay.setSpacing(theme.SPACE_SM)

        header = QLabel("Pre-Event Prep Checklist")
        header.setStyleSheet(theme.h1_style())
        lay.addWidget(header)

        desc = QLabel(
            "Pick a saved deck — the table shows the top meta archetypes "
            "for its format and whether you have a sideboard plan for "
            "each. Rows are colored by readiness: green = SB plan + "
            "favorable matchup, amber = plan but tough matchup, red = "
            "no plan for a meta-relevant archetype."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(desc)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(theme.SPACE_SM)
        ctrl.addWidget(QLabel("Saved deck:"))
        self._deck_combo = QComboBox()
        self._deck_combo.setMinimumWidth(260)
        self._deck_combo.currentIndexChanged.connect(self._on_deck_changed)
        ctrl.addWidget(self._deck_combo)

        from gui.icons_util import btn_icon
        self._refresh_btn = QPushButton(btn_icon("refresh"), "Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_btn.clicked.connect(self._load_decks)
        ctrl.addWidget(self._refresh_btn)
        ctrl.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(
            f"color: {theme.ACCENT}; font-weight: bold;"
        )
        ctrl.addWidget(self._summary_lbl)
        lay.addLayout(ctrl)

        # Splitter: matchup table on left, SB plan detail on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Archetype", "Meta %", "Real WR", "Your WR", "SB Plan", "Ready"
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(self._on_row_changed)
        splitter.addWidget(self._table)

        self._plan_view = QTextBrowser()
        self._plan_view.setFont(QFont("Consolas", 10))
        self._plan_view.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER};"
        )
        self._plan_view.setPlainText("Pick a row to see its sideboard plan.")
        splitter.addWidget(self._plan_view)
        splitter.setSizes([600, 320])
        lay.addWidget(splitter, 1)

    def cleanup(self):
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_decks(self):
        """Populate the saved-deck combo."""
        try:
            from db.saved_decks import get_decks
            self._decks = get_decks()
        except Exception:
            self._decks = []
        self._deck_combo.blockSignals(True)
        self._deck_combo.clear()
        self._deck_combo.addItem("-- pick a saved deck --")
        for d in self._decks:
            label = f"{d.get('name', '(unnamed)')}  [{d.get('format', '?')}]"
            self._deck_combo.addItem(label)
        self._deck_combo.blockSignals(False)

    def _on_deck_changed(self, idx: int):
        if idx <= 0 or idx - 1 >= len(self._decks):
            self._current_deck = None
            self._table.setRowCount(0)
            self._plan_view.setPlainText("Pick a saved deck above.")
            self._summary_lbl.setText("")
            return
        self._current_deck = self._decks[idx - 1]
        self._refresh_checklist()

    def _refresh_checklist(self):
        deck = self._current_deck
        if not deck:
            return
        fmt = deck.get("format") or "modern"
        archetype = deck.get("archetype") or ""
        deck_id = deck.get("id")

        def _do():
            from analysis.win_rates import get_meta_standings, get_real_matchup_winrates
            from analysis.archetypes import normalize as norm_arch
            from db.match_log import get_matchup_stats
            from db.saved_decks import get_sb_plans

            standings = get_meta_standings(fmt, top=12, min_appearances=2)
            real = get_real_matchup_winrates(fmt, min_matches=5)
            personal = get_matchup_stats(archetype, format_name=fmt) if archetype else {}
            plans = get_sb_plans(deck_id) if deck_id else []
            plans_by_opp = {norm_arch((p.get("opponent_archetype") or "")).lower(): p
                             for p in plans}

            a_norm = norm_arch(archetype).lower()
            rows = []
            for s in standings:
                opp = s.get("archetype", "")
                opp_norm = norm_arch(opp).lower()
                if opp_norm == a_norm:
                    continue

                real_wr = None
                sample = 0
                if a_norm in real and opp_norm in real[a_norm]:
                    entry = real[a_norm][opp_norm]
                    real_wr, sample = entry["win_rate"], entry["total"]
                elif opp_norm in real and a_norm in real[opp_norm]:
                    entry = real[opp_norm][a_norm]
                    real_wr, sample = 1.0 - entry["win_rate"], entry["total"]

                p = personal.get(opp_norm) or personal.get(opp) or {}
                p_wr = p.get("wr")
                p_n = p.get("total", 0)

                has_plan = opp_norm in plans_by_opp
                plan = plans_by_opp.get(opp_norm) if has_plan else None

                rows.append({
                    "opp": opp, "meta_share": s.get("meta_share", 0),
                    "real_wr": real_wr, "real_sample": sample,
                    "p_wr": p_wr, "p_n": p_n,
                    "has_plan": has_plan, "plan": plan,
                })
            return rows

        w = DataLoadWorker(_do)
        w.result.connect(self._on_data)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_data(self, rows: list):
        self._table.setRowCount(len(rows))
        ready_count = 0
        gap_count = 0
        for ri, r in enumerate(rows):
            self._table.setItem(ri, 0, QTableWidgetItem(r["opp"]))

            meta_pct = r["meta_share"] * 100
            meta_item = QTableWidgetItem(f"{meta_pct:.1f}%")
            meta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 1, meta_item)

            self._table.setItem(ri, 2, _wr_item(r["real_wr"], r["real_sample"]))
            self._table.setItem(ri, 3, _wr_item(r["p_wr"], r["p_n"]))

            plan_item = QTableWidgetItem("✓" if r["has_plan"] else "—")
            plan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            plan_item.setForeground(QColor(theme.OK if r["has_plan"]
                                            else theme.TEXT_OFF))
            self._table.setItem(ri, 4, plan_item)

            # Readiness: green if plan + positive WR; amber if plan but bad;
            # red if meta-relevant (>5%) + no plan.
            ready, reason = _readiness(r)
            ready_item = QTableWidgetItem(ready)
            ready_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color_map = {
                "READY": theme.OK, "PLAN": theme.WARN,
                "GAP": theme.ERR, "LOW PRIO": theme.TEXT_OFF,
            }
            ready_item.setForeground(QColor(color_map.get(ready, theme.TEXT)))
            ready_item.setToolTip(reason)
            self._table.setItem(ri, 5, ready_item)

            if ready == "READY":
                ready_count += 1
            elif ready == "GAP":
                gap_count += 1

        self._summary_lbl.setText(
            f"{ready_count} ready · {gap_count} gaps · {len(rows)} archetypes"
        )

    def _on_row_changed(self, row: int, *_):
        if row < 0:
            return
        opp_item = self._table.item(row, 0)
        if opp_item is None:
            return
        opp = opp_item.text()
        # Find the matching stored data by iterating the plans we loaded
        deck = self._current_deck
        if not deck:
            return
        from db.saved_decks import get_sb_plans
        plans = get_sb_plans(deck.get("id")) if deck.get("id") else []
        from analysis.archetypes import normalize as norm_arch
        opp_norm = norm_arch(opp).lower()
        match = next(
            (p for p in plans
             if norm_arch(p.get("opponent_archetype") or "").lower() == opp_norm),
            None,
        )
        if not match:
            self._plan_view.setHtml(
                f"<h3 style='color:{theme.WARN}'>No sideboard plan for {opp}</h3>"
                f"<p style='color:{theme.TEXT_DIM}'>Add one in the My Decks tab "
                f"(select this deck → SB plans section).</p>"
            )
            return
        html = _format_plan_html(match, opp)
        self._plan_view.setHtml(html)


def _wr_item(wr, sample) -> QTableWidgetItem:
    """Return a QTableWidgetItem showing WR + sample, colored by favorability."""
    if wr is None or sample <= 0:
        item = QTableWidgetItem("—")
        item.setForeground(QColor(theme.TEXT_OFF))
    else:
        pct = round(wr * 100, 1)
        item = QTableWidgetItem(f"{pct:.0f}%  ({sample})")
        item.setForeground(theme.winrate_fg(wr))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def _readiness(r: dict) -> tuple:
    """Return (label, tooltip) — READY / PLAN / GAP / LOW PRIO."""
    has_plan = r["has_plan"]
    meta_share = r["meta_share"]
    real_wr = r["real_wr"]

    # Use real WR if available, else personal WR
    wr = real_wr if real_wr is not None else r["p_wr"]

    if has_plan:
        if wr is None or wr >= 0.45:
            return "READY", "SB plan exists; matchup is winnable."
        return "PLAN", (f"SB plan exists but the matchup is tough "
                         f"({round(wr * 100)}% WR). Review the plan.")
    # No plan
    if meta_share >= 0.05:
        return "GAP", (f"No SB plan — {round(meta_share * 100, 1)}% of the "
                       f"field. High priority to build one.")
    return "LOW PRIO", (f"No SB plan, but only {round(meta_share * 100, 1)}% "
                        f"of the field. Low priority.")


def _format_plan_html(plan: dict, opponent: str) -> str:
    """Render an SB plan as HTML with IN/OUT lists for play + draw."""
    difficulty = plan.get("difficulty", "")
    notes = plan.get("notes", "")
    play_in = plan.get("play_in", []) or []
    play_out = plan.get("play_out", []) or []
    draw_in = plan.get("draw_in", []) or []
    draw_out = plan.get("draw_out", []) or []

    def _list(cards, color):
        if not cards:
            return f"<i style='color:{theme.TEXT_DIM};'>(none)</i>"
        return "".join(
            f"<div style='color:{color};'>{qty}× {name}</div>"
            for name, qty in [_parse_card(c) for c in cards]
        )

    lines = [
        f"<h3 style='color:{theme.ACCENT};margin:0 0 6px 0;'>vs {opponent}</h3>",
    ]
    if difficulty:
        lines.append(f"<p><b>Difficulty:</b> {difficulty}</p>")
    if notes:
        lines.append(f"<p style='color:{theme.TEXT_DIM};'>{notes}</p>")
    lines.extend([
        f"<h4 style='color:{theme.TEXT};margin:10px 0 4px 0;'>On the Play</h4>",
        f"<p style='color:{theme.OK};font-weight:bold;margin:2px 0;'>IN:</p>",
        _list(play_in, theme.OK),
        f"<p style='color:{theme.ERR};font-weight:bold;margin:6px 0 2px 0;'>OUT:</p>",
        _list(play_out, theme.ERR),
        f"<h4 style='color:{theme.TEXT};margin:10px 0 4px 0;'>On the Draw</h4>",
        f"<p style='color:{theme.OK};font-weight:bold;margin:2px 0;'>IN:</p>",
        _list(draw_in, theme.OK),
        f"<p style='color:{theme.ERR};font-weight:bold;margin:6px 0 2px 0;'>OUT:</p>",
        _list(draw_out, theme.ERR),
    ])
    return "".join(lines)


def _parse_card(entry):
    """SB plan card entries can be 'Card Name' or {'name', 'qty'} dicts."""
    if isinstance(entry, dict):
        return entry.get("name", "?"), entry.get("qty", 1)
    return str(entry), 1
