"""
PostEventDialog — given a logged tournament event, compare what you
actually faced against what the meta predicted.

Answers questions like:
  - Did I encounter the field I expected? (meta share vs actual share)
  - How did my per-matchup WR compare to scraped real-match data?
  - Which matchups over-represented vs the meta? (lucky / unlucky field)
"""
from collections import Counter

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

import gui.theme as theme


class PostEventDialog(QDialog):
    def __init__(self, parent=None, matches: list = None):
        """matches: full match_log rows from db.match_log.get_matches()."""
        super().__init__(parent)
        self.setWindowTitle("Post-Event Analysis")
        self.setMinimumSize(*theme.DIALOG_LG)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        self._matches = matches or []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                theme.SPACE_MD, theme.SPACE_MD)
        lay.setSpacing(theme.SPACE_SM)

        hdr = QLabel("Post-Event Analysis")
        hdr.setStyleSheet(theme.h1_style())
        lay.addWidget(hdr)

        desc = QLabel(
            "For a completed event, compare the opponents you actually "
            "faced against the meta's expected share at the time, and "
            "your per-matchup record against scraped real-match data."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(desc)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Event:"))
        self._event_combo = QComboBox()
        self._event_combo.setMinimumWidth(360)
        self._populate_events()
        self._event_combo.currentIndexChanged.connect(self._on_event_changed)
        ctrl.addWidget(self._event_combo)
        ctrl.addStretch()

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(
            f"color: {theme.ACCENT}; font-weight: bold;"
        )
        ctrl.addWidget(self._summary_lbl)
        lay.addLayout(ctrl)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "Opponent", "You faced", "Expected %",
            "Your WR", "Scraped WR", "Verdict"
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        lay.addLayout(close_row)

        if self._event_combo.count() > 0:
            self._on_event_changed(0)

    def _populate_events(self):
        """List unique events from the match list, newest first."""
        seen = []
        for m in self._matches:
            event = (m.get("event_name") or "").strip()
            if not event:
                continue
            if event not in seen:
                seen.append(event)
        for event in seen:
            same = [m for m in self._matches
                    if (m.get("event_name") or "").strip() == event]
            date = (same[0].get("event_date") or "")[:10]
            label = f"{event}  ({date}, {len(same)} rounds)"
            self._event_combo.addItem(label, userData=event)

    def _on_event_changed(self, idx: int):
        if idx < 0:
            return
        event_name = self._event_combo.itemData(idx)
        if not event_name:
            return
        same = [m for m in self._matches
                if (m.get("event_name") or "").strip() == event_name]
        if not same:
            return
        fmt = (same[0].get("format") or "modern").lower()
        date = (same[0].get("event_date") or "")[:10]

        # Count actual opponents
        opp_counts = Counter()
        opp_records = {}   # opp -> [wins, losses, draws]
        for m in same:
            opp = (m.get("opp_deck") or "").strip()
            if not opp:
                continue
            opp_counts[opp] += 1
            rec = opp_records.setdefault(opp, [0, 0, 0])
            r = (m.get("result") or "").lower()
            if r == "win":   rec[0] += 1
            elif r == "loss": rec[1] += 1
            elif r == "draw": rec[2] += 1
        total_rounds = sum(opp_counts.values())

        # Meta share at event date
        from analysis.win_rates import get_meta_standings, get_real_matchup_winrates
        from analysis.archetypes import normalize as norm_arch
        from datetime import datetime, timedelta
        try:
            event_dt = datetime.fromisoformat(date) if date else datetime.now()
        except Exception:
            event_dt = datetime.now()
        since = event_dt - timedelta(weeks=4)
        try:
            standings = get_meta_standings(fmt, since=since, top=50,
                                            min_appearances=1)
        except Exception:
            standings = []
        expected_share = {}
        total_apps = sum(s.get("appearances", 0) for s in standings)
        for s in standings:
            key = norm_arch(s.get("archetype", "")).lower()
            if total_apps > 0:
                expected_share[key] = s.get("appearances", 0) / total_apps

        # Scraped real-match WR
        my_deck = (same[0].get("my_deck") or "").strip()
        my_norm = norm_arch(my_deck).lower()
        try:
            real = get_real_matchup_winrates(fmt, min_matches=5)
        except Exception:
            real = {}

        # Render rows
        rows = []
        for opp, count in opp_counts.most_common():
            opp_norm = norm_arch(opp).lower()
            expected = expected_share.get(opp_norm, 0.0)
            actual = count / total_rounds if total_rounds else 0

            w, l, d = opp_records[opp]
            decisive = w + l
            your_wr = (w / decisive) if decisive else None

            scraped_wr = None
            if my_norm in real and opp_norm in real[my_norm]:
                scraped_wr = real[my_norm][opp_norm]["win_rate"]
            elif opp_norm in real and my_norm in real[opp_norm]:
                scraped_wr = 1.0 - real[opp_norm][my_norm]["win_rate"]

            rows.append({
                "opp": opp, "count": count, "expected": expected,
                "actual": actual, "your_wr": your_wr,
                "scraped_wr": scraped_wr, "record": (w, l, d),
            })

        self._table.setRowCount(len(rows))
        field_diff_total = 0
        for ri, r in enumerate(rows):
            self._table.setItem(ri, 0, QTableWidgetItem(r["opp"]))

            w, l, d = r["record"]
            rec = f"{r['count']}×  ({w}-{l}-{d})"
            item = QTableWidgetItem(rec)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 1, item)

            exp_pct = r["expected"] * 100
            exp_item = QTableWidgetItem(f"{exp_pct:.1f}%"
                                         if exp_pct else "—")
            exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if exp_pct == 0:
                exp_item.setForeground(QColor(theme.TEXT_OFF))
            exp_item.setToolTip(
                f"Expected share of the field (meta standings in the 4 "
                f"weeks before {date})."
            )
            self._table.setItem(ri, 2, exp_item)

            if r["your_wr"] is not None:
                you_item = QTableWidgetItem(f"{r['your_wr']*100:.0f}%")
                you_item.setForeground(theme.winrate_fg(r["your_wr"]))
            else:
                you_item = QTableWidgetItem("—")
                you_item.setForeground(QColor(theme.TEXT_OFF))
            you_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 3, you_item)

            if r["scraped_wr"] is not None:
                sc_item = QTableWidgetItem(f"{r['scraped_wr']*100:.0f}%")
                sc_item.setForeground(theme.winrate_fg(r["scraped_wr"]))
            else:
                sc_item = QTableWidgetItem("—")
                sc_item.setForeground(QColor(theme.TEXT_OFF))
            sc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 4, sc_item)

            verdict, tip = _verdict(r)
            v_item = QTableWidgetItem(verdict)
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            v_item.setToolTip(tip)
            color_map = {
                "LUCKY FIELD": theme.OK,
                "UNLUCKY FIELD": theme.ERR,
                "AS EXPECTED": theme.TEXT_DIM,
                "OVER-PERFORMED": theme.OK,
                "UNDER-PERFORMED": theme.ERR,
            }
            v_item.setForeground(QColor(color_map.get(verdict, theme.TEXT)))
            self._table.setItem(ri, 5, v_item)

            field_diff_total += abs(r["actual"] - r["expected"])

        # Summary: how far off was your field from the expected field?
        avg_diff = (field_diff_total / len(rows)) * 100 if rows else 0
        wins = sum(r["record"][0] for r in rows)
        losses = sum(r["record"][1] for r in rows)
        draws = sum(r["record"][2] for r in rows)
        self._summary_lbl.setText(
            f"{wins}-{losses}-{draws}  · "
            f"avg field vs expected: ±{avg_diff:.1f} pts per matchup"
        )


def _verdict(r: dict) -> tuple:
    """Short 2-word label + tooltip for each row."""
    opp = r["opp"]
    actual = r["actual"]
    expected = r["expected"]
    your_wr = r["your_wr"]
    scraped_wr = r["scraped_wr"]
    count = r["count"]

    # Field-share verdict
    diff = actual - expected
    if expected > 0 and abs(diff) >= 0.10 and count >= 2:
        if diff > 0:
            field = "LUCKY FIELD"
            field_tip = (f"Faced {opp} {count}× ({actual*100:.0f}% of "
                         f"rounds) — field had {expected*100:.1f}% "
                         f"expected. Over-represented.")
        else:
            field = "UNLUCKY FIELD"
            field_tip = (f"Faced {opp} {count}× ({actual*100:.0f}% of "
                         f"rounds) — field had {expected*100:.1f}% "
                         f"expected. Under-represented.")
    else:
        field, field_tip = None, None

    # Performance verdict (only if we have a record and a scraped baseline)
    perf, perf_tip = None, None
    if your_wr is not None and scraped_wr is not None and count >= 2:
        delta = your_wr - scraped_wr
        if delta >= 0.10:
            perf = "OVER-PERFORMED"
            perf_tip = (f"Your {your_wr*100:.0f}% WR vs {opp} beat the "
                        f"scraped baseline of {scraped_wr*100:.0f}%.")
        elif delta <= -0.10:
            perf = "UNDER-PERFORMED"
            perf_tip = (f"Your {your_wr*100:.0f}% WR vs {opp} is below "
                        f"the scraped baseline of {scraped_wr*100:.0f}%.")

    # Prefer performance verdict over field verdict when both apply
    if perf:
        return perf, perf_tip or ""
    if field:
        return field, field_tip or ""
    return "AS EXPECTED", (f"Faced {opp} {count}×; no strong delta vs "
                            f"the expected field or scraped WR.")
