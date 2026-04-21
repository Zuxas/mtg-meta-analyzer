"""
Breaker Math sub-tab — real-time ID/draw calculator + breaker education.

Split from tournament_prep.py for maintainability.
"""
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QGroupBox, QTextEdit, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import gui.theme as theme


# ---------------------------------------------------------------------------
# Breaker education text (static HTML, shown at bottom of results)
# ---------------------------------------------------------------------------

_WORKED_EXAMPLE_HTML = f"""
<hr style="border: 1px solid {theme.BORDER}; margin: 14px 0;">
<h3 style="color: {theme.ACCENT}; margin: 0 0 8px 0;">Worked Example — 5-Round RCQ</h3>
<table style="border-collapse: collapse; width: 100%;">
<tr style="color: {theme.TEXT_DIM};">
  <th style="text-align:left; padding-right:12px;">Round</th>
  <th style="text-align:left; padding-right:12px;">Opponent</th>
  <th style="text-align:left; padding-right:12px;">Result</th>
  <th style="text-align:left;">Record</th></tr>
<tr>
  <td style="padding-right:12px;">R1</td>
  <td style="padding-right:12px;">Mono Red Aggro</td>
  <td style="color:{theme.OK}; padding-right:12px;">Win</td>
  <td>1-0-0 (3 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R2</td>
  <td style="padding-right:12px;">Esper Oculus</td>
  <td style="color:{theme.OK}; padding-right:12px;">Win</td>
  <td>2-0-0 (6 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R3</td>
  <td style="padding-right:12px;">Big Dimir Midrange</td>
  <td style="color:{theme.ERR}; padding-right:12px;">Loss</td>
  <td>2-1-0 (6 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R4</td>
  <td style="padding-right:12px;">Rakdos Goblins</td>
  <td style="color:{theme.OK}; padding-right:12px;">Win</td>
  <td>3-1-0 (9 pts) ✓ Locked top 4</td></tr>
<tr>
  <td style="padding-right:12px; color:{theme.WARN};">R5 (pair-down)</td>
  <td style="padding-right:12px; color:{theme.WARN};">Unknown (2-2 player)</td>
  <td style="color:{theme.ERR}; padding-right:12px;">Loss</td>
  <td style="color:{theme.WARN};">3-2-0 (9 pts) → seeded 3rd</td></tr>
</table>

<p style="margin: 8px 0; color: {theme.HILITE};"><b>What happened:</b></p>
<ul style="margin: 4px 0; padding-left: 20px;">
<li>At 9 pts in a 5-round event (top 4 cut at 9 pts), you were <b>locked for top 4</b> before R5.</li>
<li>You were seeded <b>2nd</b> at 3-1 on tiebreakers — your opponents (including the 3-1 Dimir player)
  had strong records, giving you a high OMW%.</li>
<li>The R5 loss didn't eliminate you — still 9 pts — but dropped you to <b>3rd seed</b>
  because your GW% fell and you lost the seeding tiebreak to other 9-pt players.</li>
<li>Seeding 3rd vs 2nd means you face the <b>1st seed</b> in top 4 instead of the 4th seed.
  In top 4, higher seed plays lower seed: 1st vs 4th, 2nd vs 3rd.</li>
</ul>

<p style="margin: 8px 0; color: {theme.HILITE};"><b>Why your R5 opponent (now 3-2) didn't make top 4:</b></p>
<ul style="margin: 4px 0; padding-left: 20px;">
<li>Their 2 prior losses meant their R1-R4 opponents had weaker average records.</li>
<li>OMW% is the average win rate of your opponents. A 2-2 player's opponents
  tend to have records like 2-2, 1-3 — dragging OMW% down.</li>
<li>Despite beating a 3-1 player (you), their other opponents weren't strong enough
  to raise their OMW% above the 3-1 players who also finished at 9 pts.</li>
<li>This is the classic "upset win can't overcome bad early-round opponents" scenario.</li>
</ul>
"""

_EDU_HTML = f"""
<hr style="border: 1px solid {theme.BORDER}; margin: 14px 0;">
<h3 style="color: {theme.ACCENT}; margin: 0 0 8px 0;">How Tiebreakers Work in Magic Tournaments</h3>
<p style="margin: 4px 0;">When players tie on points after Swiss, three tiebreakers decide who makes top cut:</p>

<p style="margin: 8px 0;">
<b style="color: {theme.HILITE};">1. Opponent Match Win % (OMW%) — most important</b><br>
The average match win percentage of every opponent you played against.
Playing against strong opponents who go 4-1 is better for your OMW% than
opponents who go 1-4. <i>Each opponent has a 33% minimum floor to protect players who receive byes.</i>
</p>

<p style="margin: 8px 0;">
<b style="color: {theme.HILITE};">2. Game Win % (GW%)</b><br>
Your own win % across all individual games (not matches).
Going 2-0 in every match builds GW% faster than 2-1 wins.
<i>Minimum floor: 33%.</i>
</p>

<p style="margin: 8px 0;">
<b style="color: {theme.HILITE};">3. Opponent Game Win % (OGW%)</b><br>
The average GW% of all your opponents. The last tiebreaker — only relevant
when OMW% and GW% are both perfectly tied.
</p>

<p style="margin: 8px 0; color: {theme.OK};">
<b>Practical tips:</b><br>
&nbsp;• Playing fast matters — a 2-0 win is worth more GW% than a 2-1 grind<br>
&nbsp;• If you're already eliminated and your opponent is fighting for top 8, conceding
  quickly is a common sportsmanship gesture — it doesn't affect your standing<br>
&nbsp;• An unintentional draw (ID) costs you 2 points vs a win, and reduces your OMW%
  since your opponent gets 1 point instead of 0 or 3 — plan carefully in later rounds<br>
&nbsp;• A 3-1-1 finish at 10 pts can sometimes miss if opponent records are weak;
  a 3-2 with strong opponents can sometimes squeak through on OMW%
</p>
"""


def _pair_down_note(s: dict) -> str:
    """If player might be getting paired down (safe to draw = locked 3-1 in final round), show note."""
    if not (s["safe_to_draw"] and s["remaining"] == 1):
        return ""
    thr = s["threshold"]
    cur = s["cur_pts"]
    if cur < thr:
        return ""
    return (
        f'<div style="background: {theme.WARN_BG}; border-left: 4px solid {theme.WARN}; '
        'padding: 8px 12px; border-radius: 3px; margin: 10px 0;">'
        f'<b style="color: {theme.WARN};">Pair-Down Warning</b><br>'
        f'You are locked at {cur} pts with 1 round remaining. '
        'You may be paired DOWN against a player with one fewer win.<br>'
        f'<span style="color: {theme.TEXT};">• Winning improves your seeding and GW%</span><br>'
        f'<span style="color: {theme.TEXT_DIM};">• Losing still qualifies you for top cut, but drops your '
        'seeding and hurts GW% — important if multiple players are at the same points total</span><br>'
        f'<span style="color: {theme.TEXT_DIM};">• Your opponent (if 2-2) will need a win to reach '
        f'{thr} pts — they cannot ID into top cut</span>'
        '</div>'
    )


def _seeding_html(top_cut: int) -> str:
    """Show what top-cut seeding positions mean for matchup pairings."""
    if top_cut == 8:
        pairings = [("1st vs 8th", "Best record plays worst"), ("2nd vs 7th", ""), ("3rd vs 6th", ""), ("4th vs 5th", "")]
    elif top_cut == 4:
        pairings = [("1st vs 4th", "Best record plays worst"), ("2nd vs 3rd", "")]
    else:
        pairings = [("1st vs 2nd", "Finals only")]

    rows = "".join(
        f'<tr><td style="padding-right:16px; color:{theme.ACCENT};">{p}</td>'
        f'<td style="color:{theme.TEXT_DIM};">{note}</td></tr>'
        for p, note in pairings
    )
    return (
        f'<h3 style="color: {theme.ACCENT}; margin: 12px 0 6px 0;">Seeding Impact</h3>'
        f'<p style="margin: 4px 0;">Top-{top_cut} bracket pairings (higher seed = better):</p>'
        f'<table style="border-collapse: collapse; margin: 6px 0 0 8px;">{rows}</table>'
        f'<p style="margin: 6px 0; color: {theme.TEXT_DIM}; font-size: 10px;">'
        f'Seeding is determined by: 1. Points, 2. OMW%, 3. GW%, 4. OGW%</p>'
    )


def _build_results_html(standing: dict, id_data: dict | None, show_examples: bool = False) -> str:
    """Generate the full HTML for the Breaker Math results panel."""
    s  = standing
    sc = s["status_color"]

    lines = [
        f'<div style="background: {theme.INFO_BG}; border-left: 4px solid {sc}; '
        f'padding: 10px 12px; margin-bottom: 10px; border-radius: 3px;">',
        f'<span style="font-size: 15px; color: {sc}; font-weight: bold;">{s["status"]}</span><br>',
        f'Record: <b>{s["record"]}</b> &nbsp;|&nbsp; '
        f'Points: <b>{s["cur_pts"]}</b> &nbsp;|&nbsp; '
        f'Max possible: <b>{s["max_pts"]}</b> &nbsp;|&nbsp; '
        f'Threshold: <b>{s["threshold"]} pts</b><br>',
        f'Rounds played: {s["played"]} / {s["rounds"]} &nbsp;&nbsp; '
        f'Remaining: <b>{s["remaining"]}</b>',
        '</div>',
    ]

    # --- Unintentional draw impact (show when draws > 0) ---
    if ',' in s["record"]:  # should not trigger
        pass
    parts = s["record"].split("-")
    if len(parts) == 3 and int(parts[2]) > 0:
        d_count = int(parts[2])
        pts_lost = d_count * 2
        lines.append(
            f'<p style="color: {theme.WARN}; margin: 6px 0;">'
            f'⚠ You have {d_count} draw(s) on your record — '
            f'each draw cost you 2 points vs a win ({pts_lost} pts total lost). '
            f'Your OMW% is also slightly reduced since opponents get 1 pt from you instead of 0 or 3.'
            f'</p>'
        )

    if s["eliminated"]:
        lines.append(
            f'<p style="color: {theme.ERR}; margin: 6px 0;">'
            f'Mathematically eliminated — maximum {s["max_pts"]} pts cannot reach '
            f'the {s["threshold"]}-pt threshold with {s["remaining"]} rounds remaining.</p>'
        )
        lines.append(_EDU_HTML)
        return "\n".join(lines)

    # --- ID Calculator ---
    lines.append(
        f'<h3 style="color: {theme.ACCENT}; margin: 12px 0 6px 0;">ID Calculator</h3>'
    )

    if s["remaining"] == 0:
        lines.append(f'<p>Tournament complete. Final: {s["record"]} ({s["cur_pts"]} pts).</p>')
    else:
        d = s["draw"]
        w = s["win"]

        # Draw scenario
        if d["viable"]:
            if d["wins_needed"] == 0:
                draw_desc = (
                    f'<span style="color:{theme.OK};">✓ You are already at or above threshold. '
                    f'Safe to draw.</span>'
                )
            else:
                draw_desc = (
                    f'Still need <b>{d["wins_needed"]}</b> more win(s) from '
                    f'{d["remaining"]} remaining round(s) to lock up top cut.'
                )
        else:
            draw_desc = (
                f'<span style="color:{theme.ERR};">⚠ Cannot reach {s["threshold"]} pts after a draw. '
                f'Max would be {d["pts"] + d["remaining"]*3} pts. You MUST WIN this round.</span>'
            )

        lines.append(
            f'<p style="margin: 4px 0;"><b>Draw this round:</b> '
            f'{s["cur_pts"]} → <b>{d["pts"]}</b> pts &nbsp; {draw_desc}</p>'
        )

        # Win scenario
        if w["wins_needed"] == 0:
            win_desc = '<span style="color:{theme.OK};">✓ At or above threshold!</span>'
        else:
            win_desc = (
                f'Then need <b>{w["wins_needed"]}</b> more win(s) from {w["remaining"]} remaining.'
            )
        lines.append(
            f'<p style="margin: 4px 0;"><b>Win this round:</b> '
            f'{s["cur_pts"]} → <b>{w["pts"]}</b> pts &nbsp; {win_desc}</p>'
        )

    # --- Points Tracker / Alive Records ---
    lines.append(
        f'<h3 style="color: {theme.ACCENT}; margin: 12px 0 6px 0;">Points Tracker</h3>'
    )
    lines.append(
        f'<p style="margin: 4px 0;">'
        f'{s["rounds"]}-round Swiss &nbsp;|&nbsp; '
        f'Top {s["top_cut"]} cut &nbsp;|&nbsp; '
        f'Win = 3 pts, Draw = 1 pt, Loss = 0 pts</p>'
    )

    if s["alive_records"]:
        lines.append('<p style="margin: 6px 0;"><b>Records that reach top cut:</b></p>')
        lines.append('<table style="border-collapse: collapse; margin-left: 8px;">')
        for rec in s["alive_records"][:12]:
            clr = theme.OK if rec["over"] else theme.HILITE
            tag = "safely in" if rec["over"] else "at threshold"
            lines.append(
                f'<tr>'
                f'<td style="color:{clr}; padding: 1px 12px 1px 0;"><b>{rec["record"]}</b></td>'
                f'<td style="color:{clr};">{rec["points"]} pts</td>'
                f'<td style="color: {theme.TEXT_DIM}; padding-left: 12px;">{tag}</td>'
                f'</tr>'
            )
        lines.append('</table>')

    # --- Draw Equity Calculator ---
    if id_data:
        lines.append(
            f'<h3 style="color: {theme.ACCENT}; margin: 12px 0 6px 0;">Draw Equity Calculator</h3>'
        )
        rc  = id_data["rec_color"]
        opp = id_data["opponent"]
        lines.append(
            f'<div style="background: {theme.INFO_BG}; border-left: 4px solid {rc}; '
            f'padding: 8px 12px; border-radius: 3px; margin-bottom: 8px;">'
            f'<b style="color: {rc};">{id_data["recommendation"]}</b>'
            f'</div>'
        )
        lines.append(
            f'<p style="margin: 4px 0;">'
            f'Opponent: {opp["record"]} ({opp["cur_pts"]} pts) — '
            f'<span style="color: {opp["status_color"]};"><b>{opp["status"]}</b></span></p>'
        )
        # Detailed comparison
        me = id_data["me"]
        lines.append(
            '<table style="border-collapse: collapse; margin-top: 6px;">'
            f'<tr style="color: {theme.TEXT_DIM};">'
            '<th style="text-align:left; padding-right: 16px;">Outcome</th>'
            '<th style="padding-right: 12px;">Your pts</th>'
            '<th>Opp pts</th></tr>'
        )
        for outcome, my_p, op_p in [
            ("You draw",  me["draw"]["pts"], opp["draw"]["pts"]),
            ("You win",   me["win"]["pts"],  opp["cur_pts"]),
            ("You lose",  me["cur_pts"],     opp["win"]["pts"]),
        ]:
            lines.append(
                f'<tr>'
                f'<td style="padding-right: 16px;">{outcome}</td>'
                f'<td style="text-align:center; padding-right:12px;">{my_p}</td>'
                f'<td style="text-align:center;">{op_p}</td>'
                f'</tr>'
            )
        lines.append('</table>')

    # Seeding impact
    lines.append(_seeding_html(s["top_cut"]))

    # Teammate / locked concession note
    if s["safe_to_draw"] and id_data and id_data["opponent"]["safe_to_draw"]:
        lines.append(
            f'<div style="background: {theme.SUCCESS_BG}; border-left: 4px solid {theme.OK}; '
            'padding: 8px 12px; border-radius: 3px; margin: 10px 0;">'
            f'<b style="color: {theme.OK};">Teammate / Locked Concession</b><br>'
            'Both players are locked for top cut. '
            'If this is a teammate pairing, either player can concede instantly — '
            'the result does not affect whether either player makes top cut.<br>'
            f'<span style="color: {theme.TEXT_DIM};">Note: conceding to a teammate helps '
            'their GW% and can improve their seeding slightly.</span>'
            '</div>'
        )

    lines.append(_pair_down_note(s))
    lines.append(_EDU_HTML)
    if show_examples:
        lines.append(_WORKED_EXAMPLE_HTML)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Breaker Math sub-tab
# ---------------------------------------------------------------------------

class BreakerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Tournament structure ───────────────────────────────────────
        struct_box = QGroupBox("Tournament Structure")
        sb_row = QHBoxLayout(struct_box)

        sb_row.addWidget(QLabel("Players:"))
        self._players = QSpinBox()
        self._players.setRange(4, 5000)
        self._players.setValue(32)
        self._players.setFixedWidth(80)
        sb_row.addWidget(self._players)

        sb_row.addWidget(QLabel("Top cut:"))
        self._top_cut = QComboBox()
        self._top_cut.addItems(["8", "16", "32", "64"])
        self._top_cut.setCurrentText("8")
        self._top_cut.setFixedWidth(60)
        sb_row.addWidget(self._top_cut)

        self._struct_lbl = QLabel("")
        self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        sb_row.addWidget(self._struct_lbl)
        sb_row.addStretch()
        layout.addWidget(struct_box)

        # ── Records ───────────────────────────────────────────────────
        rec_row = QHBoxLayout()
        rec_row.setSpacing(16)

        my_box = QGroupBox("My Current Record")
        my_h = QHBoxLayout(my_box)
        my_h.addWidget(QLabel("W:"))
        self._my_w = QSpinBox(); self._my_w.setRange(0, 20); self._my_w.setFixedWidth(55)
        my_h.addWidget(self._my_w)
        my_h.addWidget(QLabel("L:"))
        self._my_l = QSpinBox(); self._my_l.setRange(0, 20); self._my_l.setFixedWidth(55)
        my_h.addWidget(self._my_l)
        my_h.addWidget(QLabel("D:"))
        self._my_d = QSpinBox(); self._my_d.setRange(0, 20); self._my_d.setFixedWidth(55)
        my_h.addWidget(self._my_d)
        rec_row.addWidget(my_box)

        op_box = QGroupBox("Opponent Record  (for Draw Equity Calculator)")
        op_h = QHBoxLayout(op_box)
        op_h.addWidget(QLabel("W:"))
        self._op_w = QSpinBox(); self._op_w.setRange(0, 20); self._op_w.setFixedWidth(55)
        op_h.addWidget(self._op_w)
        op_h.addWidget(QLabel("L:"))
        self._op_l = QSpinBox(); self._op_l.setRange(0, 20); self._op_l.setFixedWidth(55)
        op_h.addWidget(self._op_l)
        op_h.addWidget(QLabel("D:"))
        self._op_d = QSpinBox(); self._op_d.setRange(0, 20); self._op_d.setFixedWidth(55)
        op_h.addWidget(self._op_d)
        rec_row.addWidget(op_box)

        layout.addLayout(rec_row)

        # ── Options ───────────────────────────────────────────────────
        opt_row = QHBoxLayout()
        self._show_examples = QCheckBox("Show worked example (5-round RCQ)")
        self._show_examples.setChecked(False)
        self._show_examples.stateChanged.connect(lambda _: self._update())
        opt_row.addWidget(self._show_examples)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # ── Results panel (real-time HTML) ────────────────────────────
        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setFont(QFont("Consolas", 10))
        self._results.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 6px;"
        )
        layout.addWidget(self._results, 1)

        # Wire all spinboxes to update (lambda discards the emitted int)
        for sb in (self._players, self._my_w, self._my_l, self._my_d,
                   self._op_w, self._op_l, self._op_d):
            sb.valueChanged.connect(lambda _: self._update())
        self._top_cut.currentIndexChanged.connect(lambda _: self._update())

        self._update()

    def _update(self):
        from analysis.tournament import tournament_structure, standing_analysis, id_recommendation

        players = self._players.value()
        my_w = self._my_w.value()
        my_l = self._my_l.value()
        my_d = self._my_d.value()
        op_w = self._op_w.value()
        op_l = self._op_l.value()
        op_d = self._op_d.value()

        from analysis.tournament import RCQ_MIN_PLAYERS, cut_threshold, x_loss_cutoff
        struct = tournament_structure(players)
        # Override top cut from dropdown
        custom_cut = int(self._top_cut.currentText())
        struct["top_cut"] = custom_cut
        struct["threshold"] = cut_threshold(struct["rounds"]) if not struct["single_elim"] else 0

        if players < RCQ_MIN_PLAYERS:
            self._struct_lbl.setText(
                f"\u26a0  {players} players \u2014 below minimum ({RCQ_MIN_PLAYERS} required for RCQ)")
            self._struct_lbl.setStyleSheet(f"color: {theme.ERR}; font-size: 11px;")
        elif struct["single_elim"]:
            self._struct_lbl.setText(
                "3 rounds, single elimination  \u2022  All 8 in bracket  \u2022  No threshold")
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        else:
            max_l = x_loss_cutoff(players, struct["rounds"], custom_cut)
            min_w = struct["rounds"] - max_l
            self._struct_lbl.setText(
                f"{struct['rounds']} rounds  \u2022  Top {custom_cut}  \u2022  "
                f"{struct['threshold']} pts  \u2022  Need {min_w}-{max_l} or better")
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")

        standing = standing_analysis(my_w, my_l, my_d, players)
        id_data  = None
        if op_w + op_l + op_d > 0:
            id_data = id_recommendation(my_w, my_l, my_d, op_w, op_l, op_d, players)

        show_ex = self._show_examples.isChecked()
        body = _build_results_html(standing, id_data, show_examples=show_ex)
        self._results.setHtml(
            f'<div style="background:{theme.PANEL}; color:{theme.TEXT}; '
            f'font-family: Consolas, monospace; font-size: 11px; line-height: 1.4;">'
            f'{body}</div>'
        )

