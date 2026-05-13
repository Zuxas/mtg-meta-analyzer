"""
gui/widgets/mulligan_evaluator.py -- 7-card opening hand evaluator

Shows a random 7-card draw from the selected deck. Classifies cards into
land / cantrip / threat / answer using chapin._classify_cards + a few
Prowess-specific overrides. Outputs a keep/mulligan verdict with
reasoning grounded in primer rules:

  - Land count thresholds (0 / 1 / 2-4 / 5+ / 6-7)
  - Cantrip count (Opt / Sleight / Flow State / Boomerang / Prismari Charm)
  - Threat presence (Slickshot / Eddymurk / Stormchaser's Talent)
  - Matchup adjustments (vs Landfall: removal required on draw;
    Mirror/Spellementals: cantrip-heavy preferred)

Not a probabilistic simulator -- a heuristic evaluator that matches the
primer's keep-or-mulligan decision tree.
"""

import random

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QButtonGroup,
    QRadioButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme


# Card-role overrides for Prowess-style decks. These supplement
# chapin._classify_cards which uses generic oracle-text keywords.
_PROWESS_CANTRIPS = {
    "Opt", "Sleight of Hand", "Flow State", "Boomerang Basics",
    "Prismari Charm", "Stock Up",
}
_PROWESS_THREATS = {
    "Slickshot Show-Off", "Eddymurk Crab", "Stormchaser's Talent",
}
_PROWESS_ANSWERS = {
    "Burst Lightning", "Get Out", "Roaring Furnace // Steaming Sauna",
    "Roaring Furnace / Steaming Sauna",
    "Spell Pierce", "Impractical Joke", "Disdainful Stroke",
    "Slagstorm", "Pyroclasm", "Annul", "Abrade", "Sear",
    "Negate", "Spell Snare", "Bounce Off",
}


def _classify_hand_card(card_name: str, deck_cats: dict) -> str:
    """Return one of: land, cantrip, threat, answer, other.
    deck_cats comes from chapin._classify_cards."""
    if card_name in deck_cats.get("lands", set()):
        return "land"
    if card_name in _PROWESS_CANTRIPS:
        return "cantrip"
    if card_name in _PROWESS_THREATS:
        return "threat"
    if card_name in _PROWESS_ANSWERS:
        return "answer"
    # Fall back to chapin classification
    if (card_name in deck_cats.get("creatures", set()) or
        card_name in deck_cats.get("planeswalkers", set())):
        return "threat"
    if card_name in deck_cats.get("draw_spells", set()):
        return "cantrip"
    if card_name in deck_cats.get("interaction", set()):
        return "answer"
    return "other"


def evaluate_hand(hand: list, deck_cats: dict, on_play: bool,
                  matchup: str = "") -> dict:
    """
    Returns:
      {"verdict": "KEEP"|"MARGINAL"|"MULL",
       "reasons": [str, ...],          # bullet points
       "counts": {land, cantrip, threat, answer, other},
       "land_2_pct": float|None}      # estimated probability of hitting land 2
    """
    counts = {"land": 0, "cantrip": 0, "threat": 0, "answer": 0, "other": 0}
    for c in hand:
        counts[_classify_hand_card(c, deck_cats)] += 1

    lands    = counts["land"]
    cantrips = counts["cantrip"]
    threats  = counts["threat"]
    answers  = counts["answer"]

    reasons = []
    verdict = "KEEP"
    matchup_lo = (matchup or "").lower()
    is_landfall = "landfall" in matchup_lo or "cub" in matchup_lo
    is_mirror   = "prowess" in matchup_lo or "spellement" in matchup_lo or "stallion" in matchup_lo or "cosmos" in matchup_lo
    is_control  = "control" in matchup_lo or "lessons" in matchup_lo or "momo" in matchup_lo or "high noon" in matchup_lo

    # --- Hard thresholds ---
    if lands == 0:
        reasons.append("0 lands — auto-mulligan.")
        return {"verdict": "MULL", "reasons": reasons,
                "counts": counts, "land_2_pct": None}
    if lands >= 6:
        reasons.append(f"{lands} lands — flood. Auto-mulligan.")
        return {"verdict": "MULL", "reasons": reasons,
                "counts": counts, "land_2_pct": None}
    if lands == 5 and threats == 0:
        reasons.append("5 lands, 0 threats — flood with no clock.")
        return {"verdict": "MULL", "reasons": reasons,
                "counts": counts, "land_2_pct": None}

    # --- One-lander analysis (primer math) ---
    land_2_pct = None
    if lands == 1:
        # Primer: double cantrip on draw = 95%; single = 86%
        if not on_play and cantrips >= 2:
            land_2_pct = 95.0
            reasons.append(f"1-lander, {cantrips} cantrips, on the draw — 95% to find land 2.")
        elif not on_play and cantrips == 1:
            land_2_pct = 86.0
            reasons.append(f"1-lander, 1 cantrip, on the draw — 86% to find land 2.")
            verdict = "MARGINAL"
        elif on_play and cantrips >= 2:
            land_2_pct = 84.0  # primer says "84%" on the play with cantrip eating turn 1
            reasons.append(f"1-lander, {cantrips} cantrips, on the play — ~84% to hit land 2 (T1 cantrip).")
            verdict = "MARGINAL"
        else:
            reasons.append(f"1-lander, {cantrips} cantrips on the play — too risky. Mulligan.")
            return {"verdict": "MULL", "reasons": reasons,
                    "counts": counts, "land_2_pct": None}

        # vs Landfall, harder to keep 1-landers
        if is_landfall:
            reasons.append("vs Landfall: 1-landers worse — you need to impact the board, not dig.")
            if verdict == "KEEP":
                verdict = "MARGINAL"

    # --- Threat-less hand check ---
    if threats == 0:
        if is_control:
            # Control matchup: Crab Control plan is OK with 0 threats if velocity is there
            if cantrips >= 2 and answers >= 2:
                reasons.append("No threat, but Crab Control plan needs velocity + answers — keepable vs control.")
            else:
                reasons.append("0 threats, vs control — Mulligan (you can't survive without a threat).")
                if verdict == "KEEP":
                    verdict = "MARGINAL"
        elif is_landfall and answers == 0:
            reasons.append("vs Landfall, no threats, no removal — auto-mulligan (must kill T1 Llanowar Elf on draw).")
            return {"verdict": "MULL", "reasons": reasons,
                    "counts": counts, "land_2_pct": land_2_pct}
        else:
            # Generic: threat-less needs a way to dig (Flow State or Sauna)
            has_flow_or_sauna = any(
                c in ("Flow State", "Roaring Furnace // Steaming Sauna",
                      "Roaring Furnace / Steaming Sauna")
                for c in hand
            )
            if has_flow_or_sauna and cantrips >= 2:
                reasons.append("0 threats but Flow State/Sauna + cantrips give you time to find one.")
                if verdict == "KEEP":
                    verdict = "MARGINAL"
            else:
                reasons.append("0 threats, no Flow State/Sauna fallback — Mulligan.")
                if verdict != "MULL":
                    verdict = "MULL"

    # --- Matchup-specific bonuses ---
    if is_mirror and cantrips >= 3 and verdict != "MULL":
        reasons.append("Mirror/Spellementals: cantrip-heavy hand — strong keep.")
    elif is_mirror and cantrips == 0 and verdict == "KEEP":
        reasons.append("Mirror/Spellementals: no cantrips — bottom of your range. Consider mulligan.")
        verdict = "MARGINAL"

    if is_landfall and not on_play and answers == 0 and threats >= 1:
        reasons.append("vs Landfall on the draw: no removal — you can't answer T1 Llanowar Elf. Lean mulligan.")
        if verdict == "KEEP":
            verdict = "MARGINAL"

    # --- Final summary line ---
    if not reasons:
        reasons.append(f"{lands} lands, {cantrips} cantrips, {threats} threats, {answers} answers — standard keep.")
    elif verdict == "KEEP":
        reasons.append(f"Profile: {lands}L / {cantrips}C / {threats}T / {answers}A.")

    return {"verdict": verdict, "reasons": reasons,
            "counts": counts, "land_2_pct": land_2_pct}


class MulliganEvaluator(QWidget):
    """Tab widget: random 7-card draw + keep/mulligan evaluator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck = None       # full deck dict (name, mainboard, sideboard, archetype)
        self._deck_cats = {}    # chapin classification
        self._hand = []         # current 7-card hand
        self._build_ui()

    def set_deck(self, deck: dict):
        """Load a deck. Pre-classify cards once via chapin helpers."""
        self._deck = deck
        if not deck:
            self._deck_cats = {}
            self._render_empty()
            return

        from analysis.chapin import _classify_cards, _to_dict
        from scrapers.scryfall import get_cards_data
        main = _to_dict(deck.get("mainboard", {}) or {})
        try:
            card_data = get_cards_data(list(main.keys()))
            self._deck_cats = _classify_cards(main, card_data)
        except Exception:
            self._deck_cats = {}

        # Populate matchup combo from saved SB plans
        self._matchup_combo.blockSignals(True)
        self._matchup_combo.clear()
        self._matchup_combo.addItem("(no matchup -- general rules)", "")
        deck_id = deck.get("id")
        if deck_id is not None:
            try:
                from db.saved_decks import get_sb_plans
                for p in get_sb_plans(deck_id):
                    opp = p.get("opponent_archetype", "")
                    if opp:
                        self._matchup_combo.addItem(opp, opp)
            except Exception:
                pass
        self._matchup_combo.blockSignals(False)

        self._draw_random_hand()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM,
                                theme.SPACE_SM, theme.SPACE_SM)
        root.setSpacing(8)

        # Top controls
        controls = QHBoxLayout()
        self._draw_btn = QPushButton("Draw 7")
        self._draw_btn.setStyleSheet(theme.btn_primary())
        self._draw_btn.setToolTip("Random 7-card opening hand from the deck (re-shuffles each click)")
        self._draw_btn.clicked.connect(self._draw_random_hand)
        controls.addWidget(self._draw_btn)

        controls.addWidget(QLabel("  Going:"))
        self._play_group = QButtonGroup(self)
        self._play_rb = QRadioButton("On the play")
        self._draw_rb = QRadioButton("On the draw")
        self._play_rb.setChecked(True)
        self._play_group.addButton(self._play_rb)
        self._play_group.addButton(self._draw_rb)
        self._play_rb.toggled.connect(self._reevaluate)
        controls.addWidget(self._play_rb)
        controls.addWidget(self._draw_rb)

        controls.addWidget(QLabel("  vs:"))
        self._matchup_combo = QComboBox()
        self._matchup_combo.addItem("(no matchup -- general rules)", "")
        self._matchup_combo.setMinimumWidth(220)
        self._matchup_combo.currentIndexChanged.connect(self._reevaluate)
        controls.addWidget(self._matchup_combo)

        controls.addStretch()
        root.addLayout(controls)

        # Hand display
        self._hand_tbl = QTableWidget(0, 2)
        self._hand_tbl.setHorizontalHeaderLabels(["Card", "Role"])
        self._hand_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._hand_tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._hand_tbl.verticalHeader().setVisible(False)
        self._hand_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._hand_tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._hand_tbl.setFixedHeight(225)
        self._hand_tbl.setStyleSheet(
            f"QTableWidget {{ background: {theme.PANEL}; font-size: 12px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        try:
            from gui.widgets.card_tooltip import install_card_tooltip
            install_card_tooltip(self._hand_tbl, card_name_column=0)
        except Exception:
            pass
        root.addWidget(self._hand_tbl)

        # Verdict panel
        self._verdict_frame = QFrame()
        self._verdict_frame.setStyleSheet(
            f"background: {theme.PANEL}; border-radius: 6px; padding: 8px;"
        )
        vf_layout = QVBoxLayout(self._verdict_frame)
        vf_layout.setContentsMargins(12, 8, 12, 8)
        vf_layout.setSpacing(6)
        self._verdict_label = QLabel("—")
        vf = QFont()
        vf.setPointSize(18)
        vf.setBold(True)
        self._verdict_label.setFont(vf)
        self._verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vf_layout.addWidget(self._verdict_label)

        self._verdict_counts = QLabel("")
        self._verdict_counts.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._verdict_counts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vf_layout.addWidget(self._verdict_counts)

        self._verdict_reasons = QLabel("")
        self._verdict_reasons.setWordWrap(True)
        self._verdict_reasons.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; padding: 4px 8px;")
        vf_layout.addWidget(self._verdict_reasons)

        root.addWidget(self._verdict_frame)
        root.addStretch()

    def _draw_random_hand(self):
        if not self._deck:
            return
        main = self._deck.get("mainboard", {}) or {}
        # Build flat card pool
        pool = []
        for name, qty in main.items():
            pool.extend([name] * int(qty))
        if len(pool) < 7:
            self._hand = list(pool)
        else:
            self._hand = random.sample(pool, 7)
        self._reevaluate()

    def _reevaluate(self):
        if not self._deck:
            self._render_empty()
            return
        on_play = self._play_rb.isChecked()
        matchup = self._matchup_combo.currentData() or ""

        # Render hand list
        self._hand_tbl.setRowCount(len(self._hand))
        role_colors = {
            "land":    QColor(120, 100, 60),
            "cantrip": QColor(80, 140, 200),
            "threat":  QColor(180, 80, 80),
            "answer":  QColor(80, 160, 80),
            "other":   QColor(140, 140, 140),
        }
        for ri, card in enumerate(sorted(self._hand)):
            role = _classify_hand_card(card, self._deck_cats)
            name_item = QTableWidgetItem(card)
            self._hand_tbl.setItem(ri, 0, name_item)
            role_item = QTableWidgetItem(role.upper())
            role_item.setForeground(role_colors.get(role, QColor(theme.TEXT)))
            role_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            f = QFont(); f.setBold(True)
            role_item.setFont(f)
            self._hand_tbl.setItem(ri, 1, role_item)

        result = evaluate_hand(self._hand, self._deck_cats, on_play, matchup)
        v = result["verdict"]
        verdict_color = {"KEEP": theme.OK, "MARGINAL": theme.WARN, "MULL": theme.ERR}.get(v, theme.TEXT)
        self._verdict_label.setText(v)
        self._verdict_label.setStyleSheet(f"color: {verdict_color};")

        c = result["counts"]
        self._verdict_counts.setText(
            f"{c['land']} land  ·  {c['cantrip']} cantrip  ·  "
            f"{c['threat']} threat  ·  {c['answer']} answer  ·  {c['other']} other"
        )

        bullets = "\n".join(f"  • {r}" for r in result["reasons"])
        self._verdict_reasons.setText(bullets)

    def _render_empty(self):
        self._hand_tbl.setRowCount(0)
        self._verdict_label.setText("—")
        self._verdict_counts.setText("Select a deck on the left.")
        self._verdict_reasons.setText("")
