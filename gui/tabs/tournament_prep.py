"""
Tab — Tournament Prep

Two sub-tabs:
  1. EVENT OPTIMIZER — equity analysis for a given expected field
  2. BREAKER MATH  — real-time ID / draw calculator + breaker education

This module composes the two sub-tabs from their respective modules.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QFrame, QToolButton, QMessageBox,
)
from PyQt6.QtCore import Qt

import gui.theme as theme

from gui.tabs.event_optimizer import EventWidget
from gui.tabs.breaker_math import BreakerWidget
from gui.tabs.hypotheses import HypothesesTab
from gui.tabs.prep_checklist import PrepChecklistTab
from gui.tabs.event_hub_tab import EventHubTab
from gui.tabs.scout import ScoutTab


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
    row.setSpacing(theme.SPACE_SM)

    icon = QLabel("\u26a0")
    icon.setStyleSheet("color: #f58231; font-size: 13px; background: transparent;")
    row.addWidget(icon)

    txt = QLabel(
        "<b style='color:#f58231;'>Decklists required \u2014 Competitive REL</b>"
        "  \u00b7  Minimum 8 players  \u00b7  Slow play warnings, missed trigger rules, "
        "and stricter judge calls apply at RCQs."
    )
    txt.setStyleSheet("color: #c0c8d0; font-size: 11px; background: transparent;")
    txt.setWordWrap(False)
    row.addWidget(txt, 1)

    info_btn = QToolButton()
    info_btn.setText("Comp REL ?")
    info_btn.setStyleSheet(
        f"QToolButton {{ color: {theme.ACCENT}; font-size: 10px; border: 1px solid {theme.BORDER}; "
        "border-radius: 3px; padding: 2px 6px; background: transparent; }"
        f"QToolButton:hover {{ border-color: {theme.ACCENT}; }}"
    )
    info_btn.clicked.connect(lambda: QMessageBox.information(
        None, "Competitive REL \u2014 What It Means", _COMP_REL_DETAIL
    ))
    row.addWidget(info_btn)

    appendix_btn = QToolButton()
    appendix_btn.setText("Appendix E ?")
    appendix_btn.setStyleSheet(info_btn.styleSheet())
    appendix_btn.clicked.connect(lambda: QMessageBox.information(
        None, "MTR Appendix E \u2014 Official Round Counts", _APPENDIX_E_DETAIL
    ))
    row.addWidget(appendix_btn)

    return banner


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
        self._prep_checklist = PrepChecklistTab()
        self._rcq            = EventWidget()
        self._event_hub      = EventHubTab()
        self._scout          = ScoutTab()
        self._breaker        = BreakerWidget()
        self._hypotheses     = HypothesesTab()
        inner.addTab(self._prep_checklist, "PREP CHECKLIST")
        inner.addTab(self._rcq,            "EVENT OPTIMIZER")
        inner.addTab(self._event_hub,      "EVENT HUB")
        inner.addTab(self._scout,          "SCOUT")
        inner.addTab(self._breaker,        "BREAKER MATH")
        inner.addTab(self._hypotheses,     "HYPOTHESES")
        layout.addWidget(inner)

    def cleanup(self):
        for sub in (self._prep_checklist, self._rcq, self._event_hub,
                    self._scout, self._breaker, self._hypotheses):
            if hasattr(sub, "cleanup"):
                try:
                    sub.cleanup()
                except Exception:
                    pass

    def load_deck(self, deck: dict):
        """Called by MainWindow when user clicks 'Open in Event Optimizer' from My Decks."""
        self._rcq.load_deck(deck)
