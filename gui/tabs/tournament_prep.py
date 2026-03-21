"""
Tab — Tournament Prep

Two sub-tabs:
  1. RCQ OPTIMIZER — equity analysis for a given expected field
  2. BREAKER MATH  — real-time ID / draw calculator + breaker education
"""
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QSplitter, QTextEdit, QComboBox, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QCheckBox, QToolButton, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from gui.worker_threads import DataLoadWorker
import gui.theme as theme


# ---------------------------------------------------------------------------
# Official RCQ / Competitive REL information
# ---------------------------------------------------------------------------

_COMP_REL_DETAIL = (
    "Competitive Rules Enforcement Level (REL) applies at all RCQ events.\n\n"
    "What this means for players:\n\n"
    "• SLOW PLAY — Judges actively watch for slow play. Taking an unreasonable "
    "amount of time on decisions can result in a warning (and game loss on a "
    "second offense). Play at a reasonable pace at all times.\n\n"
    "• MISSED TRIGGERS — At Competitive REL, beneficial triggers are NOT "
    "automatically given to you if you miss them. Your opponent must acknowledge "
    "the trigger for it to go on the stack. Track your own triggers carefully "
    "(e.g. Sheoldred life loss, Eidolon of the Great Revel damage).\n\n"
    "• DECKLIST ERRORS — Submitting an illegal decklist (wrong card count, "
    "banned card, illegible writing) results in a Deck/Decklist Problem "
    "infraction. Penalty is a Game Loss in the first game of the match where "
    "the problem is discovered. Double-check your decklist before submitting.\n\n"
    "• STRICT JUDGE CALLS — Errors like illegal actions, missed zone changes, "
    "or misrepresenting game state are penalized more strictly than at Regular "
    "REL (FNM). Judges issue formal warnings and game losses, not just fixes.\n\n"
    "• COMMUNICATION — You must answer direct questions about your deck's "
    "contents honestly. You may not bluff about having a card in hand. "
    "Strategic deception (e.g. representing a bluff play) is legal; "
    "misrepresenting the game state is not.\n\n"
    "• TIME LIMITS — Rounds are 50 minutes. After time is called, 5 additional "
    "turns are played (turn of the active player + 5). Matches that end in a "
    "draw after extra turns are reported as draws (1 pt each)."
)

_APPENDIX_E_DETAIL = (
    "MTR Appendix E — Official Round Counts for RCQ Events\n\n"
    "8 players:   3 rounds, single elimination bracket (all 8 play)\n"
    "9–16:        4 rounds of Swiss + cut to top 4\n"
    "17–32:       5 rounds of Swiss + cut to top 8\n"
    "33–64:       6 rounds of Swiss + cut to top 8\n"
    "65–128:      7 rounds of Swiss + cut to top 8\n"
    "129+:        8 rounds of Swiss + cut to top 8\n\n"
    "Minimum 8 players required to run an RCQ.\n"
    "Decklists are required at ALL RCQ events.\n"
    "Source: Wizards Play Network (WPN) / Magic Tournament Rules"
)


def _make_rcq_banner() -> QWidget:
    """A persistent info bar shown at the top of the Tournament Prep tab."""
    banner = QFrame()
    banner.setStyleSheet(
        "QFrame { background: #1a2535; border-bottom: 2px solid #f58231; "
        "border-top: none; border-left: none; border-right: none; }"
    )
    banner.setFixedHeight(32)
    row = QHBoxLayout(banner)
    row.setContentsMargins(12, 0, 12, 0)
    row.setSpacing(8)

    icon = QLabel("⚠")
    icon.setStyleSheet("color: #f58231; font-size: 13px; background: transparent;")
    row.addWidget(icon)

    txt = QLabel(
        "<b style='color:#f58231;'>Decklists required — Competitive REL</b>"
        "  ·  Minimum 8 players  ·  Slow play warnings, missed trigger rules, "
        "and stricter judge calls apply at RCQs."
    )
    txt.setStyleSheet("color: #c0c8d0; font-size: 11px; background: transparent;")
    txt.setWordWrap(False)
    row.addWidget(txt, 1)

    info_btn = QToolButton()
    info_btn.setText("Comp REL ?")
    info_btn.setStyleSheet(
        "QToolButton { color: #65bcd5; font-size: 10px; border: 1px solid #4a5a6e; "
        "border-radius: 3px; padding: 2px 6px; background: transparent; }"
        "QToolButton:hover { border-color: #65bcd5; }"
    )
    info_btn.clicked.connect(lambda: QMessageBox.information(
        None, "Competitive REL — What It Means", _COMP_REL_DETAIL
    ))
    row.addWidget(info_btn)

    appendix_btn = QToolButton()
    appendix_btn.setText("Appendix E ?")
    appendix_btn.setStyleSheet(info_btn.styleSheet())
    appendix_btn.clicked.connect(lambda: QMessageBox.information(
        None, "MTR Appendix E — Official Round Counts", _APPENDIX_E_DETAIL
    ))
    row.addWidget(appendix_btn)

    return banner


# ---------------------------------------------------------------------------
# Breaker education text (static HTML, shown at bottom of results)
# ---------------------------------------------------------------------------

_WORKED_EXAMPLE_HTML = """
<hr style="border: 1px solid #4a5a6e; margin: 14px 0;">
<h3 style="color: #65bcd5; margin: 0 0 8px 0;">Worked Example — 5-Round RCQ</h3>
<table style="border-collapse: collapse; width: 100%;">
<tr style="color: #8a9aaa;">
  <th style="text-align:left; padding-right:12px;">Round</th>
  <th style="text-align:left; padding-right:12px;">Opponent</th>
  <th style="text-align:left; padding-right:12px;">Result</th>
  <th style="text-align:left;">Record</th></tr>
<tr>
  <td style="padding-right:12px;">R1</td>
  <td style="padding-right:12px;">Mono Red Aggro</td>
  <td style="color:#3cb44b; padding-right:12px;">Win</td>
  <td>1-0-0 (3 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R2</td>
  <td style="padding-right:12px;">Esper Oculus</td>
  <td style="color:#3cb44b; padding-right:12px;">Win</td>
  <td>2-0-0 (6 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R3</td>
  <td style="padding-right:12px;">Big Dimir Midrange</td>
  <td style="color:#e6194b; padding-right:12px;">Loss</td>
  <td>2-1-0 (6 pts)</td></tr>
<tr>
  <td style="padding-right:12px;">R4</td>
  <td style="padding-right:12px;">Rakdos Goblins</td>
  <td style="color:#3cb44b; padding-right:12px;">Win</td>
  <td>3-1-0 (9 pts) ✓ Locked top 4</td></tr>
<tr>
  <td style="padding-right:12px; color:#f58231;">R5 (pair-down)</td>
  <td style="padding-right:12px; color:#f58231;">Unknown (2-2 player)</td>
  <td style="color:#e6194b; padding-right:12px;">Loss</td>
  <td style="color:#f58231;">3-2-0 (9 pts) → seeded 3rd</td></tr>
</table>

<p style="margin: 8px 0; color: #f0c020;"><b>What happened:</b></p>
<ul style="margin: 4px 0; padding-left: 20px;">
<li>At 9 pts in a 5-round event (top 4 cut at 9 pts), you were <b>locked for top 4</b> before R5.</li>
<li>You were seeded <b>2nd</b> at 3-1 on tiebreakers — your opponents (including the 3-1 Dimir player)
  had strong records, giving you a high OMW%.</li>
<li>The R5 loss didn't eliminate you — still 9 pts — but dropped you to <b>3rd seed</b>
  because your GW% fell and you lost the seeding tiebreak to other 9-pt players.</li>
<li>Seeding 3rd vs 2nd means you face the <b>1st seed</b> in top 4 instead of the 4th seed.
  In top 4, higher seed plays lower seed: 1st vs 4th, 2nd vs 3rd.</li>
</ul>

<p style="margin: 8px 0; color: #f0c020;"><b>Why your R5 opponent (now 3-2) didn't make top 4:</b></p>
<ul style="margin: 4px 0; padding-left: 20px;">
<li>Their 2 prior losses meant their R1-R4 opponents had weaker average records.</li>
<li>OMW% is the average win rate of your opponents. A 2-2 player's opponents
  tend to have records like 2-2, 1-3 — dragging OMW% down.</li>
<li>Despite beating a 3-1 player (you), their other opponents weren't strong enough
  to raise their OMW% above the 3-1 players who also finished at 9 pts.</li>
<li>This is the classic "upset win can't overcome bad early-round opponents" scenario.</li>
</ul>
"""

_EDU_HTML = """
<hr style="border: 1px solid #4a5a6e; margin: 14px 0;">
<h3 style="color: #65bcd5; margin: 0 0 8px 0;">How Tiebreakers Work in Magic Tournaments</h3>
<p style="margin: 4px 0;">When players tie on points after Swiss, three tiebreakers decide who makes top cut:</p>

<p style="margin: 8px 0;">
<b style="color: #f0c020;">1. Opponent Match Win % (OMW%) — most important</b><br>
The average match win percentage of every opponent you played against.
Playing against strong opponents who go 4-1 is better for your OMW% than
opponents who go 1-4. <i>Each opponent has a 33% minimum floor to protect players who receive byes.</i>
</p>

<p style="margin: 8px 0;">
<b style="color: #f0c020;">2. Game Win % (GW%)</b><br>
Your own win % across all individual games (not matches).
Going 2-0 in every match builds GW% faster than 2-1 wins.
<i>Minimum floor: 33%.</i>
</p>

<p style="margin: 8px 0;">
<b style="color: #f0c020;">3. Opponent Game Win % (OGW%)</b><br>
The average GW% of all your opponents. The last tiebreaker — only relevant
when OMW% and GW% are both perfectly tied.
</p>

<p style="margin: 8px 0; color: #3cb44b;">
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
        '<div style="background: #2a2a1a; border-left: 4px solid #f58231; '
        'padding: 8px 12px; border-radius: 3px; margin: 10px 0;">'
        '<b style="color: #f58231;">Pair-Down Warning</b><br>'
        f'You are locked at {cur} pts with 1 round remaining. '
        'You may be paired DOWN against a player with one fewer win.<br>'
        '<span style="color: #f0f0f0;">• Winning improves your seeding and GW%</span><br>'
        '<span style="color: #8a9aaa;">• Losing still qualifies you for top cut, but drops your '
        'seeding and hurts GW% — important if multiple players are at the same points total</span><br>'
        '<span style="color: #8a9aaa;">• Your opponent (if 2-2) will need a win to reach '
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
        f'<tr><td style="padding-right:16px; color:#65bcd5;">{p}</td>'
        f'<td style="color:#8a9aaa;">{note}</td></tr>'
        for p, note in pairings
    )
    return (
        f'<h3 style="color: #65bcd5; margin: 12px 0 6px 0;">Seeding Impact</h3>'
        f'<p style="margin: 4px 0;">Top-{top_cut} bracket pairings (higher seed = better):</p>'
        f'<table style="border-collapse: collapse; margin: 6px 0 0 8px;">{rows}</table>'
        f'<p style="margin: 6px 0; color: #8a9aaa; font-size: 10px;">'
        f'Seeding is determined by: 1. Points, 2. OMW%, 3. GW%, 4. OGW%</p>'
    )


def _build_results_html(standing: dict, id_data: dict | None, show_examples: bool = False) -> str:
    """Generate the full HTML for the Breaker Math results panel."""
    s  = standing
    sc = s["status_color"]

    lines = [
        f'<div style="background: #1e2d40; border-left: 4px solid {sc}; '
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
            f'<p style="color: #f58231; margin: 6px 0;">'
            f'⚠ You have {d_count} draw(s) on your record — '
            f'each draw cost you 2 points vs a win ({pts_lost} pts total lost). '
            f'Your OMW% is also slightly reduced since opponents get 1 pt from you instead of 0 or 3.'
            f'</p>'
        )

    if s["eliminated"]:
        lines.append(
            '<p style="color: #e6194b; margin: 6px 0;">'
            f'Mathematically eliminated — maximum {s["max_pts"]} pts cannot reach '
            f'the {s["threshold"]}-pt threshold with {s["remaining"]} rounds remaining.</p>'
        )
        lines.append(_EDU_HTML)
        return "\n".join(lines)

    # --- ID Calculator ---
    lines.append(
        '<h3 style="color: #65bcd5; margin: 12px 0 6px 0;">ID Calculator</h3>'
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
                    f'<span style="color:#3cb44b;">✓ You are already at or above threshold. '
                    f'Safe to draw.</span>'
                )
            else:
                draw_desc = (
                    f'Still need <b>{d["wins_needed"]}</b> more win(s) from '
                    f'{d["remaining"]} remaining round(s) to lock up top cut.'
                )
        else:
            draw_desc = (
                f'<span style="color:#e6194b;">⚠ Cannot reach {s["threshold"]} pts after a draw. '
                f'Max would be {d["pts"] + d["remaining"]*3} pts. You MUST WIN this round.</span>'
            )

        lines.append(
            f'<p style="margin: 4px 0;"><b>Draw this round:</b> '
            f'{s["cur_pts"]} → <b>{d["pts"]}</b> pts &nbsp; {draw_desc}</p>'
        )

        # Win scenario
        if w["wins_needed"] == 0:
            win_desc = '<span style="color:#3cb44b;">✓ At or above threshold!</span>'
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
        '<h3 style="color: #65bcd5; margin: 12px 0 6px 0;">Points Tracker</h3>'
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
            clr = "#3cb44b" if rec["over"] else "#f0c020"
            tag = "safely in" if rec["over"] else "at threshold"
            lines.append(
                f'<tr>'
                f'<td style="color:{clr}; padding: 1px 12px 1px 0;"><b>{rec["record"]}</b></td>'
                f'<td style="color:{clr};">{rec["points"]} pts</td>'
                f'<td style="color: #8a9aaa; padding-left: 12px;">{tag}</td>'
                f'</tr>'
            )
        lines.append('</table>')

    # --- Draw Equity Calculator ---
    if id_data:
        lines.append(
            '<h3 style="color: #65bcd5; margin: 12px 0 6px 0;">Draw Equity Calculator</h3>'
        )
        rc  = id_data["rec_color"]
        opp = id_data["opponent"]
        lines.append(
            f'<div style="background: #1e2d40; border-left: 4px solid {rc}; '
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
            '<tr style="color: #8a9aaa;">'
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
            '<div style="background: #1e3a22; border-left: 4px solid #3cb44b; '
            'padding: 8px 12px; border-radius: 3px; margin: 10px 0;">'
            '<b style="color: #3cb44b;">Teammate / Locked Concession</b><br>'
            'Both players are locked for top cut. '
            'If this is a teammate pairing, either player can concede instantly — '
            'the result does not affect whether either player makes top cut.<br>'
            '<span style="color: #8a9aaa;">Note: conceding to a teammate helps '
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

class _BreakerWidget(QWidget):
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
        self._players.setRange(4, 512)
        self._players.setValue(32)
        self._players.setFixedWidth(80)
        sb_row.addWidget(self._players)

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

        from analysis.tournament import RCQ_MIN_PLAYERS
        struct = tournament_structure(players)
        if players < RCQ_MIN_PLAYERS:
            self._struct_lbl.setText(
                f"⚠  {players} players — below minimum ({RCQ_MIN_PLAYERS} required for RCQ)"
            )
            self._struct_lbl.setStyleSheet("color: #e6194b; font-size: 11px;")
        elif struct["single_elim"]:
            self._struct_lbl.setText(
                "3 rounds, single elimination  •  All 8 players in bracket  •  No points threshold"
            )
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        else:
            self._struct_lbl.setText(
                f"{struct['rounds']} rounds  •  Top {struct['top_cut']}  "
                f"•  Threshold: {struct['threshold']} pts"
            )
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


# ---------------------------------------------------------------------------
# RCQ Optimizer sub-tab
# ---------------------------------------------------------------------------

class _RCQWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()

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
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)

        lv.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        lv.addWidget(self._fmt)
        self._fmt.currentTextChanged.connect(self._on_fmt_changed)

        lv.addWidget(QLabel("Player count:"))
        self._players = QSpinBox()
        self._players.setRange(4, 512)
        self._players.setValue(32)
        self._players.setSuffix(" players")
        lv.addWidget(self._players)

        self._struct_lbl = QLabel("")
        self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        lv.addWidget(self._struct_lbl)
        self._players.valueChanged.connect(self._update_struct_lbl)
        self._update_struct_lbl(32)

        lv.addWidget(QLabel("Timeframe:"))
        self._tf = QComboBox()
        for label, _ in theme.TIMEFRAME_OPTIONS:
            self._tf.addItem(label)
        self._tf.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._tf.currentIndexChanged.connect(
            lambda _: self._populate_arch_combo(self._fmt.currentText())
        )
        lv.addWidget(self._tf)

        lv.addWidget(QLabel("My archetype:"))
        self._my_arch = QComboBox()
        self._my_arch.setEditable(True)
        self._my_arch.lineEdit().setPlaceholderText("e.g. Boros Energy")
        lv.addWidget(self._my_arch)

        help_lbl = QLabel("Expected field (one per line):\n'Deck Name x4' or 'Deck Name 4'")
        help_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lv.addWidget(help_lbl)

        self._field_input = QTextEdit()
        self._field_input.setPlaceholderText(
            "Boros Energy x8\nAzorius Blink x5\nDimir Midrange x4\nMono Red Aggro x3"
        )
        self._field_input.setMinimumHeight(130)
        self._field_input.setMaximumHeight(220)
        lv.addWidget(self._field_input)

        self._analyze_btn = QPushButton("Analyze Field")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.clicked.connect(self._run)
        lv.addWidget(self._analyze_btn)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._status.setWordWrap(True)
        lv.addWidget(self._status)
        lv.addStretch()

        splitter.addWidget(left)

        # ── Right: results ─────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 12)
        rv.setSpacing(8)

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
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Archetype", "Count", "Exp. Rds", "G1 WR%", "G2/G3 WR%", "Guides", "Verdict"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 7):
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
        from analysis.tournament import tournament_structure, RCQ_MIN_PLAYERS
        s = tournament_structure(n)
        if n < RCQ_MIN_PLAYERS:
            self._struct_lbl.setText(
                f"⚠  {n} players — below minimum ({RCQ_MIN_PLAYERS} required to run an RCQ)"
            )
            self._struct_lbl.setStyleSheet(f"color: #e6194b; font-size: 11px;")
        elif s["single_elim"]:
            self._struct_lbl.setText(
                f"3 rounds, single elimination bracket  •  All {n} players in the bracket"
            )
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        else:
            self._struct_lbl.setText(
                f"{s['rounds']} rounds  •  Top {s['top_cut']}  •  Threshold: {s['threshold']} pts"
            )
            self._struct_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")

    def _on_fmt_changed(self, fmt):
        self._populate_arch_combo(fmt)

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

    def _run(self):
        archetype = self._my_arch.currentText().strip()
        field = self._parse_field()
        if not archetype:
            self._status.setText("Enter your archetype.")
            return
        if not field:
            self._status.setText("Enter the expected field (e.g. 'Boros Energy x8').")
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
            self._status.setText(f"Error: {e}"),
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
            "A+": "#3cb44b", "A": "#3cb44b", "B": "#65bcd5",
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
        self._top8_lbl.setText(
            f"Estimated top-{struct['top_cut']} probability: {top*100:.1f}%   "
            f"({struct['rounds']}-round Swiss, {r['players']} players)"
        )

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
                guide_color = "#65bcd5"

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

            self._table.setItem(row, 0, _item(m["archetype"], align=Qt.AlignmentFlag.AlignLeft))
            self._table.setItem(row, 1, _item(m["count"]))
            self._table.setItem(row, 2, _item(f"{m['exp_rounds']:.1f}"))
            self._table.setItem(row, 3, _item(f"{g1_wr*100:.0f}%", g1_color))
            self._table.setItem(row, 4, _item(g23_txt, g23_color))
            self._table.setItem(row, 5, _item(guide_txt, guide_color))
            self._table.setItem(row, 6, _item(verdict, vc))

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
                f'<div style="border-top:1px solid #4a5a6e; margin:8px 0; padding-top:8px;">'
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
# Combined Tournament Prep tab
# ---------------------------------------------------------------------------

class TournamentPrepTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(_make_rcq_banner())

        inner = QTabWidget()
        inner.setTabPosition(QTabWidget.TabPosition.North)
        inner.addTab(_RCQWidget(),    "RCQ OPTIMIZER")
        inner.addTab(_BreakerWidget(), "BREAKER MATH")
        layout.addWidget(inner)
