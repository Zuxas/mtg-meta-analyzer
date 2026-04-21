"""
Tab — Simulate
Runs mtg-sim goldfish simulations for a chosen archetype.

mtg-sim is an optional sibling repo. This tab discovers it via:
  1. $MTG_SIM_PATH environment variable, if set
  2. ../mtg-sim relative to this analyzer's repo root (sibling clone)

If neither is available, the tab still loads but the Run button reports
a helpful install message instead of crashing.
"""
import importlib
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QTextEdit, QProgressBar,
)
from PyQt6.QtCore import Qt

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


# Discover mtg-sim: env var first, then sibling clone
_MTG_SIM_PATH = os.environ.get("MTG_SIM_PATH") or str(
    Path(__file__).resolve().parent.parent.parent.parent / "mtg-sim"
)


# Canonical archetypes shipped in mtg-sim/apl/. Each tuple:
#   (display label,
#    goldfish module,  goldfish class,
#    match module,     match class,
#    deck file relative to mtg-sim root)
_ARCHETYPES = [
    ("Amulet Titan (Modern)",   "apl.amulet_titan",   "AmuletTitanAPL",  "apl.amulet_titan_match",  "AmuletTitanMatchAPL",  "decks/amulet_titan_modern.txt"),
    ("Boros Energy (Modern)",   "apl.boros_energy",   "BorosEnergyAPL",  "apl.boros_energy_match",  "BorosEnergyMatchAPL",  "decks/boros_energy_modern.txt"),
    ("Humans (Modern)",         "apl.humans",         "HumansAPL",       "apl.humans_match",        "HumansMatchAPL",       "decks/humans_modern.txt"),
    ("Dimir Murktide (Modern)", "apl.dimir_murktide", "MurktideAPL",     "apl.murktide_match",      "MurktideMatchAPL",     "decks/dimir_murktide_modern.txt"),
    ("Eldrazi Tron (Modern)",   "apl.eldrazi_tron",   "EldraziTronAPL",  "apl.eldrazi_tron_match",  "EldraziTronMatchAPL",  "decks/eldrazi_tron_modern.txt"),
    ("Domain Zoo (Modern)",     "apl.domain_zoo",     "DomainZooAPL",    "apl.domain_zoo_match",    "DomainZooMatchAPL",    "decks/domain_zoo_modern.txt"),
]


def _check_mtg_sim_available():
    """Return (ok, msg). On ok, ensure mtg-sim is on sys.path."""
    if not os.path.isdir(_MTG_SIM_PATH):
        return False, (
            f"mtg-sim not found at {_MTG_SIM_PATH}\n\n"
            f"Set the MTG_SIM_PATH environment variable to your mtg-sim clone, "
            f"or clone it at {_MTG_SIM_PATH}:\n\n"
            f"    git clone https://github.com/Zuxas/mtg-sim.git {_MTG_SIM_PATH}"
        )
    abs_path = os.path.abspath(_MTG_SIM_PATH)
    if abs_path not in sys.path:
        sys.path.insert(0, abs_path)
    return True, ""


def _run_goldfish(apl_module: str, apl_class: str, deck_file: str,
                  n_games: int, on_play: bool) -> dict:
    """Worker-thread callable. Runs N goldfish sims, returns results dict."""
    ok, msg = _check_mtg_sim_available()
    if not ok:
        raise RuntimeError(msg)

    # Deferred imports — only touch mtg-sim internals once the path check passes.
    from data.deck import load_deck_from_file
    from engine.runner import run_simulation

    mod = importlib.import_module(apl_module)
    apl_cls = getattr(mod, apl_class)
    apl = apl_cls()

    deck_path = os.path.join(_MTG_SIM_PATH, deck_file)
    main_deck, _sb = load_deck_from_file(deck_path)

    results = run_simulation(
        apl=apl, mainboard=main_deck, n=n_games, on_play=on_play,
    )
    data = results.to_dict()
    data["mode"] = "goldfish"
    return data


def _run_matchup(
    a_label: str, a_match_module: str, a_match_class: str, a_deck_file: str,
    b_label: str, b_match_module: str, b_match_class: str, b_deck_file: str,
    n_games: int,
) -> dict:
    """Worker-thread callable. Runs N matches A-vs-B (mixed play/draw), returns results dict."""
    ok, msg = _check_mtg_sim_available()
    if not ok:
        raise RuntimeError(msg)

    import time
    from data.deck import load_deck_from_file
    from engine.match_engine import run_match_set

    a_mod = importlib.import_module(a_match_module)
    b_mod = importlib.import_module(b_match_module)
    apl_a = getattr(a_mod, a_match_class)()
    apl_b = getattr(b_mod, b_match_class)()
    apl_a.name = a_label
    apl_b.name = b_label

    a_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, a_deck_file))
    b_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, b_deck_file))

    t0 = time.perf_counter()
    results = run_match_set(apl_a, a_deck, apl_b, b_deck, n=n_games, mix_play_draw=True, seed=42)
    elapsed = time.perf_counter() - t0

    return {
        "mode": "matchup",
        "a_label": a_label,
        "b_label": b_label,
        "n_games": results.n_games,
        "a_wins": results.a_wins,
        "b_wins": results.b_wins,
        "a_win_pct": results.win_pct_a(),
        "avg_turns": round(results.avg_turns, 2) if results.avg_turns else 0,
        "kill_distribution": results.kill_turn_distribution(),
        "elapsed_sec": round(elapsed, 3),
    }


class SimulateTab(QWidget):
    """
    Goldfish simulator surface for the analyzer.
    Wraps mtg-sim's engine.runner.run_simulation in a worker thread and
    renders the aggregated SimulationResults in a monospaced pane.
    """

    def __init__(self):
        super().__init__()
        self._workers = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        hdr = QLabel("<b>Goldfish Simulator</b>")
        hdr.setStyleSheet(f"color: {theme.TEXT}; font-size: 18px;")
        layout.addWidget(hdr)

        desc = QLabel(
            "Runs mtg-sim goldfish simulations for a chosen archetype. "
            "Results show kill-turn distribution, win-by-turn milestones, and mulligan rate."
        )
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Deck:"))
        self._archetype = QComboBox()
        for label, *_ in _ARCHETYPES:
            self._archetype.addItem(label)
        self._archetype.setMinimumWidth(220)
        ctrl.addWidget(self._archetype)

        ctrl.addSpacing(8)

        ctrl.addWidget(QLabel("vs:"))
        self._opponent = QComboBox()
        self._opponent.addItem("Goldfish (no opponent)")
        for label, *_ in _ARCHETYPES:
            self._opponent.addItem(label)
        self._opponent.setMinimumWidth(220)
        self._opponent.currentIndexChanged.connect(self._on_mode_change)
        ctrl.addWidget(self._opponent)

        ctrl.addSpacing(12)

        ctrl.addWidget(QLabel("Games:"))
        self._n_games = QSpinBox()
        self._n_games.setRange(100, 50000)
        self._n_games.setSingleStep(100)
        self._n_games.setValue(1000)
        ctrl.addWidget(self._n_games)

        ctrl.addSpacing(12)

        self._on_play = QCheckBox("On the play (goldfish only)")
        self._on_play.setChecked(True)
        ctrl.addWidget(self._on_play)

        ctrl.addStretch(1)

        self._run_btn = QPushButton("Run")
        self._run_btn.setMinimumWidth(80)
        self._run_btn.clicked.connect(self._on_run)
        ctrl.addWidget(self._run_btn)

        layout.addLayout(ctrl)

        # Status line + indeterminate progress
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setMaximumHeight(4)
        layout.addWidget(self._progress)

        # Results pane
        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; "
            f"font-family: 'Cascadia Mono', 'Consolas', 'Courier New', monospace; "
            f"font-size: 12px; padding: 8px;"
        )
        # Pre-populate with the availability message if applicable
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self._results.setPlainText(msg)
            self._status.setText("mtg-sim not configured")
        layout.addWidget(self._results, 1)

    def _on_mode_change(self, idx: int):
        """Gray out the on-play checkbox when a real opponent is selected."""
        goldfish = (idx == 0)
        self._on_play.setEnabled(goldfish)

    def _on_run(self):
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self._results.setPlainText(msg)
            return

        a_idx = self._archetype.currentIndex()
        o_idx = self._opponent.currentIndex()
        a = _ARCHETYPES[a_idx]
        n = self._n_games.value()

        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._results.clear()

        if o_idx == 0:
            # Goldfish mode: just the chosen deck
            a_label, apl_mod, apl_cls, _m_mod, _m_cls, deck_file = a
            on_play = self._on_play.isChecked()
            self._status.setText(f"Running {n:,} goldfish games of {a_label} ...")
            w = DataLoadWorker(_run_goldfish, kwargs=dict(
                apl_module=apl_mod, apl_class=apl_cls,
                deck_file=deck_file, n_games=n, on_play=on_play,
            ))
        else:
            # Matchup mode: A vs B with mixed play/draw
            b = _ARCHETYPES[o_idx - 1]  # opponent dropdown has 'Goldfish' at index 0
            self._status.setText(f"Running {n:,} matches of {a[0]} vs {b[0]} ...")
            w = DataLoadWorker(_run_matchup, kwargs=dict(
                a_label=a[0], a_match_module=a[3], a_match_class=a[4], a_deck_file=a[5],
                b_label=b[0], b_match_module=b[3], b_match_class=b[4], b_deck_file=b[5],
                n_games=n,
            ))

        w.result.connect(self._on_result)
        w.error.connect(self._on_error)
        w.finished.connect(self._on_finished)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_result(self, data: dict):
        elapsed = data.get("elapsed_sec") or 0.001
        gps = data["n_games"] / elapsed
        self._status.setText(f"Complete: {elapsed:.2f}s, {gps:.0f} games/sec")

        if data.get("mode") == "matchup":
            self._results.setPlainText(self._format_matchup(data))
        else:
            self._results.setPlainText(self._format_goldfish(data))

    @staticmethod
    def _format_goldfish(data: dict) -> str:
        lines = [
            f"== {data['archetype']} | {data['n_games']:,} games (goldfish) ==",
            "",
            f"Win rate       : {data['win_rate']*100:.1f}%",
        ]
        if data.get("avg_kill_turn") is not None:
            lines.append(f"Avg kill turn  : {data['avg_kill_turn']:.2f}")
        if data.get("median_kill_turn") is not None:
            lines.append(f"Median kill    : {data['median_kill_turn']:.0f}")
        lines.extend([
            f"Win by T3      : {data['win_by_t3']}%",
            f"Win by T4      : {data['win_by_t4']}%",
            f"Win by T5      : {data['win_by_t5']}%",
            f"Avg mulligans  : {data['avg_mulligans']:.2f}  ({data['mull_rate']}% mulled)",
            "",
            "Kill turn distribution:",
        ])
        for turn, pct in data.get("kill_distribution", {}).items():
            bar = "\u2588" * int(pct / 2)
            lines.append(f"  T{turn:2d}  {pct:5.1f}%  {bar}")
        return "\n".join(lines)

    @staticmethod
    def _format_matchup(data: dict) -> str:
        a, b = data["a_label"], data["b_label"]
        n = data["n_games"]
        a_wins = data["a_wins"]
        b_wins = data["b_wins"]
        a_pct = data["a_win_pct"]
        b_pct = round(100 - a_pct, 1)
        lines = [
            f"== {a} vs {b} | {n:,} matches (mixed play/draw) ==",
            "",
            f"  {a:35s} {a_wins:5d} wins  ({a_pct}%)",
            f"  {b:35s} {b_wins:5d} wins  ({b_pct}%)",
            "",
            f"Avg match length: {data['avg_turns']} turns",
            "",
            "Kill turn distribution (winner):",
        ]
        for turn, pct in data.get("kill_distribution", {}).items():
            bar = "\u2588" * int(pct / 2)
            lines.append(f"  T{turn:2d}  {pct:5.1f}%  {bar}")
        return "\n".join(lines)

    def _on_error(self, msg: str):
        self._status.setText("Error")
        self._results.setPlainText(f"Simulation failed:\n\n{msg}")

    def _on_finished(self):
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)

    def cleanup(self):
        """Called by main_window on close — stops any running workers."""
        for w in self._workers:
            try:
                if w.isRunning():
                    w.quit()
                    w.wait(1000)
            except RuntimeError:
                # Worker may have already been deleted; ignore.
                pass
