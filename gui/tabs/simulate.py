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
    QComboBox, QSpinBox, QCheckBox, QTextEdit, QPlainTextEdit,
    QProgressBar, QSplitter,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


# Discover mtg-sim: env var first, then sibling clone
_MTG_SIM_PATH = os.environ.get("MTG_SIM_PATH") or str(
    Path(__file__).resolve().parent.parent.parent.parent / "mtg-sim"
)


# Manual overrides for archetypes whose match file doesn't follow the
# <name>_match.py convention (e.g., Dimir Murktide -> murktide_match.py).
# Key is the goldfish module name (without 'apl.' prefix).
_OVERRIDES = {
    "dimir_murktide": {
        "match_module": "apl.murktide_match",
        "match_class":  "MurktideMatchAPL",
    },
}

# Module names to skip during discovery — base classes and utilities.
_DISCOVERY_SKIP = {
    "__init__", "base_apl", "match_apl", "sb_mixin", "sb_plans",
    "mulligan", "auto_apl", "generic_apl", "playbook_parser",
}


_ACRONYMS = {"uw", "ub", "ur", "ug", "wb", "wr", "wg", "br", "bg", "rg",
             "wub", "wug", "wbg", "wbr", "wrg", "ubg", "ubr", "urg",
             "brg", "bug", "bant", "naya", "jund", "grixis", "esper"}


def _label_from_base(base: str, format_name: str) -> str:
    """Title-case the module name, preserving MTG color acronyms as upper."""
    def _fmt(w):
        if w.lower() in _ACRONYMS and len(w) <= 3:
            return w.upper()
        return w.capitalize()
    label = " ".join(_fmt(w) for w in base.split("_"))
    return f"{label} ({format_name.capitalize()})"


def _discover_archetypes_modern() -> list:
    """Scan mtg-sim/apl/ for Modern archetypes with goldfish + match APL + deck."""
    import re

    if not os.path.isdir(_MTG_SIM_PATH):
        return []
    apl_dir = os.path.join(_MTG_SIM_PATH, "apl")
    if not os.path.isdir(apl_dir):
        return []

    cls_re = re.compile(r"^class\s+([A-Z][A-Za-z0-9]*APL)\s*\(", re.MULTILINE)
    rows = []

    for fname in sorted(os.listdir(apl_dir)):
        if not fname.endswith(".py"):
            continue
        base = fname[:-3]
        if base in _DISCOVERY_SKIP:
            continue
        if base.endswith("_match") or "_grind_" in base or base.endswith("_standard_match"):
            continue

        with open(os.path.join(apl_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        gcls_match = cls_re.search(src)
        if not gcls_match:
            continue
        goldfish_class = gcls_match.group(1)

        override = _OVERRIDES.get(base, {})
        match_module = override.get("match_module") or f"apl.{base}_match"
        match_class = override.get("match_class")
        if not match_class:
            match_path = os.path.join(apl_dir, f"{base}_match.py")
            if not os.path.isfile(match_path):
                continue
            with open(match_path, "r", encoding="utf-8", errors="ignore") as f:
                msrc = f.read()
            mcls_match = re.search(r"^class\s+([A-Z][A-Za-z0-9]*MatchAPL)\s*\(",
                                   msrc, re.MULTILINE)
            if not mcls_match:
                continue
            match_class = mcls_match.group(1)
        else:
            override_path = os.path.join(_MTG_SIM_PATH,
                                         match_module.replace(".", os.sep) + ".py")
            if not os.path.isfile(override_path):
                continue

        deck_rel = f"decks/{base}_modern.txt"
        if not os.path.isfile(os.path.join(_MTG_SIM_PATH, deck_rel)):
            continue

        rows.append((
            _label_from_base(base, "modern"),
            f"apl.{base}", goldfish_class,
            match_module, match_class, deck_rel,
        ))

    return rows


def _discover_archetypes_standard() -> list:
    """Scan mtg-sim/apl/ for Standard archetypes (match APL + deck, no goldfish).

    Standard archetypes ship as *_standard_match.py with a matching
    *_standard.txt deck. Goldfish variants generally don't exist for
    these — so the tuple's goldfish slots are None.
    """
    import re

    if not os.path.isdir(_MTG_SIM_PATH):
        return []
    apl_dir = os.path.join(_MTG_SIM_PATH, "apl")
    if not os.path.isdir(apl_dir):
        return []

    mcls_re = re.compile(r"^class\s+([A-Z][A-Za-z0-9]*StandardMatchAPL)\s*\(",
                          re.MULTILINE)
    rows = []

    for fname in sorted(os.listdir(apl_dir)):
        if not fname.endswith("_standard_match.py"):
            continue
        base = fname[:-len("_standard_match.py")]
        if base in _DISCOVERY_SKIP:
            continue

        with open(os.path.join(apl_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        m = mcls_re.search(src)
        if not m:
            continue
        match_class = m.group(1)

        deck_rel = f"decks/{base}_standard.txt"
        if not os.path.isfile(os.path.join(_MTG_SIM_PATH, deck_rel)):
            continue

        rows.append((
            _label_from_base(base, "standard"),
            None, None,   # no goldfish APL for Standard archetypes
            f"apl.{base}_standard_match", match_class, deck_rel,
        ))

    return rows


def _discover_archetypes(format_name: str = "modern") -> list:
    """Combined discovery. Kept for backwards-compat with earlier callers."""
    if format_name == "modern":
        rows = _discover_archetypes_modern()
    elif format_name == "standard":
        rows = _discover_archetypes_standard()
    else:
        rows = []
    return sorted(rows, key=lambda r: r[0])


# Fallback registry if discovery fails or finds nothing — ensures the tab
# works out of the box on a fresh mtg-sim clone matching the original 6.
_FALLBACK_ARCHETYPES = [
    ("Amulet Titan (Modern)",   "apl.amulet_titan",   "AmuletTitanAPL",  "apl.amulet_titan_match",  "AmuletTitanMatchAPL",  "decks/amulet_titan_modern.txt"),
    ("Boros Energy (Modern)",   "apl.boros_energy",   "BorosEnergyAPL",  "apl.boros_energy_match",  "BorosEnergyMatchAPL",  "decks/boros_energy_modern.txt"),
    ("Humans (Modern)",         "apl.humans",         "HumansAPL",       "apl.humans_match",        "HumansMatchAPL",       "decks/humans_modern.txt"),
    ("Dimir Murktide (Modern)", "apl.dimir_murktide", "MurktideAPL",     "apl.murktide_match",      "MurktideMatchAPL",     "decks/dimir_murktide_modern.txt"),
    ("Eldrazi Tron (Modern)",   "apl.eldrazi_tron",   "EldraziTronAPL",  "apl.eldrazi_tron_match",  "EldraziTronMatchAPL",  "decks/eldrazi_tron_modern.txt"),
    ("Domain Zoo (Modern)",     "apl.domain_zoo",     "DomainZooAPL",    "apl.domain_zoo_match",    "DomainZooMatchAPL",    "decks/domain_zoo_modern.txt"),
]

# Build the registry at module load. Combine Modern + Standard discovery
# results. Modern archetypes have goldfish + match APLs; Standard
# archetypes are match-only (goldfish slots are None in the tuple).
# Fall back to hardcoded Modern set if discovery fails entirely.
_discovered_modern = _discover_archetypes_modern()
_discovered_standard = _discover_archetypes_standard()
_discovered_combined = sorted(
    _discovered_modern + _discovered_standard, key=lambda r: r[0]
)
_ARCHETYPES = (_discovered_combined
               if len(_discovered_combined) >= 3
               else _FALLBACK_ARCHETYPES)


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
                  n_games: int, on_play: bool, deck_text: str = "") -> dict:
    """Worker-thread callable. Runs N goldfish sims, returns results dict.

    If deck_text is non-empty, loads from the pasted text instead of deck_file.
    """
    ok, msg = _check_mtg_sim_available()
    if not ok:
        raise RuntimeError(msg)

    # Deferred imports — only touch mtg-sim internals once the path check passes.
    from data.deck import load_deck_from_file, load_deck_from_text
    from engine.runner import run_simulation

    mod = importlib.import_module(apl_module)
    apl_cls = getattr(mod, apl_class)
    apl = apl_cls()

    if deck_text.strip():
        main_deck, _sb = load_deck_from_text(deck_text)
    else:
        deck_path = os.path.join(_MTG_SIM_PATH, deck_file)
        main_deck, _sb = load_deck_from_file(deck_path)

    results = run_simulation(
        apl=apl, mainboard=main_deck, n=n_games, on_play=on_play,
    )
    data = results.to_dict()
    data["mode"] = "goldfish"
    return data


def _strip_format_suffix(s: str) -> str:
    """Drop '(Modern)'/(Standard)/etc. trailing format tag from a sim label."""
    for suf in (" (Modern)", " (Standard)", " (Pioneer)", " (Legacy)", " (Pauper)"):
        if s.endswith(suf):
            return s[:-len(suf)].strip()
    return s.strip()


def _format_of(label: str) -> str:
    """Return 'modern'/'standard'/etc. based on the label's trailing tag."""
    for fmt in ("Modern", "Standard", "Pioneer", "Legacy", "Pauper"):
        if label.endswith(f" ({fmt})"):
            return fmt.lower()
    return "modern"


def _lookup_real_matchup(a_label: str, b_label: str, format_name: str = None,
                         min_matches: int = 10) -> dict:
    """Look up real-match win rate for A vs B from the analyzer's scraped DB.

    Returns {'real_a_wr': float|None, 'sample_size': int}. If no data exists
    for the pairing (or the normalizer can't match the archetype name),
    real_a_wr is None and sample_size is 0. Silently returns empty on any
    exception — the overlay is opt-in, not load-bearing.
    """
    try:
        from analysis.win_rates import get_real_matchup_winrates
        from analysis.archetypes import normalize as norm_arch

        fmt = format_name or _format_of(a_label)
        a_arch = norm_arch(_strip_format_suffix(a_label))
        b_arch = norm_arch(_strip_format_suffix(b_label))
        real = get_real_matchup_winrates(fmt, min_matches=min_matches)

        # Canonical ordering is alphabetical; query both directions
        if a_arch in real and b_arch in real[a_arch]:
            entry = real[a_arch][b_arch]
            return {"real_a_wr": entry["win_rate"], "sample_size": entry["total"]}
        if b_arch in real and a_arch in real[b_arch]:
            entry = real[b_arch][a_arch]
            return {"real_a_wr": 1.0 - entry["win_rate"], "sample_size": entry["total"]}
    except Exception:
        pass
    return {"real_a_wr": None, "sample_size": 0}


def _lookup_personal_matchup(a_label: str, b_label: str,
                             format_name: str = None) -> dict:
    """Look up the user's personal W/L record for A vs B from the match_log table.

    Returns {'personal_wr': float|None, 'total': int, 'wins': int, 'losses': int}.
    Matches by archetype name (normalized) on my_deck + opp_deck.
    """
    try:
        from db.match_log import get_matchup_stats
        from analysis.archetypes import normalize as norm_arch

        fmt = format_name or _format_of(a_label)
        a_arch = norm_arch(_strip_format_suffix(a_label))
        b_arch = norm_arch(_strip_format_suffix(b_label))

        stats = get_matchup_stats(a_arch, format_name=fmt)
        # stats shape: {opp_deck: {'wr', 'total', 'wins', 'losses', ...}}
        if b_arch in stats:
            entry = stats[b_arch]
            return {"personal_wr": entry.get("wr"),
                    "total": entry.get("total", 0),
                    "wins": entry.get("wins", 0),
                    "losses": entry.get("losses", 0)}
    except Exception:
        pass
    return {"personal_wr": None, "total": 0, "wins": 0, "losses": 0}


def _run_field_gauntlet(
    a_label: str, a_match_module: str, a_match_class: str, a_deck_file: str,
    field_entries: list,   # list of _ARCHETYPES tuples (the opponents)
    n_per_matchup: int,
) -> dict:
    """Run A vs every archetype in field_entries, weighted by meta share.

    Returns a results dict with:
      - per_matchup: [{opp_label, sim_wr, meta_share, appearances}, ...]
      - expected_field_wr: weighted WR (float 0-1) over sim-covered archetypes
      - coverage_meta_share: total meta share covered by the sim (0-1)
      - weighted_covered_share: sum of weights actually applied (same as coverage)
      - total_matches: n_per_matchup * len(field_entries)
      - elapsed_sec
    """
    ok, msg = _check_mtg_sim_available()
    if not ok:
        raise RuntimeError(msg)

    import time
    from data.deck import load_deck_from_file
    from engine.match_engine import run_match_set
    from analysis.win_rates import get_meta_standings
    from analysis.archetypes import normalize as norm_arch

    fmt = _format_of(a_label)
    # Only match opponents in the same format as A — mixing Modern and
    # Standard in a field gauntlet is incoherent.
    field_entries = [e for e in field_entries if _format_of(e[0]) == fmt]

    # Build a name -> meta_share lookup from the current DB
    meta_share_by_arch = {}
    appearances_by_arch = {}
    try:
        standings = get_meta_standings(format_name=fmt, top=100)
        for row in standings:
            key = norm_arch(row.get("archetype", "") or "").lower()
            if key:
                meta_share_by_arch[key] = row.get("meta_share", 0.0)
                appearances_by_arch[key] = row.get("appearances", 0)
    except Exception:
        pass

    # Our side
    a_mod = importlib.import_module(a_match_module)
    apl_a_factory = getattr(a_mod, a_match_class)
    a_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, a_deck_file))

    t0 = time.perf_counter()
    per_matchup = []

    for entry in field_entries:
        opp_label, _g_mod, _g_cls, m_mod, m_cls, opp_deck_file = entry
        if opp_label == a_label:
            continue  # skip self-matchup

        opp_mod = importlib.import_module(m_mod)
        apl_b = getattr(opp_mod, m_cls)()
        apl_a = apl_a_factory()  # fresh instance per matchup
        apl_a.name = a_label
        apl_b.name = opp_label

        opp_deck, _ = load_deck_from_file(os.path.join(_MTG_SIM_PATH, opp_deck_file))
        results = run_match_set(apl_a, a_deck, apl_b, opp_deck,
                                n=n_per_matchup, mix_play_draw=True, seed=42)
        sim_wr = results.win_rate_a()

        # Strip '(Modern)' from opp_label for the meta-share lookup
        opp_bare = opp_label
        for suf in (" (Modern)", " (Standard)", " (Pioneer)", " (Legacy)"):
            if opp_bare.endswith(suf):
                opp_bare = opp_bare[:-len(suf)].strip()
                break
        opp_key = norm_arch(opp_bare).lower()
        meta_share = meta_share_by_arch.get(opp_key, 0.0)
        appearances = appearances_by_arch.get(opp_key, 0)

        per_matchup.append({
            "opp_label": opp_label,
            "sim_wr": sim_wr,
            "meta_share": meta_share,
            "appearances": appearances,
        })

    # Weighted expected field WR (weights re-normalized over covered opponents)
    total_weight = sum(m["meta_share"] for m in per_matchup)
    if total_weight > 0:
        expected_wr = sum(m["sim_wr"] * m["meta_share"]
                          for m in per_matchup) / total_weight
    else:
        # No meta-share data available — fall back to uniform average
        expected_wr = (sum(m["sim_wr"] for m in per_matchup) / len(per_matchup)
                       if per_matchup else 0.0)

    elapsed = time.perf_counter() - t0

    return {
        "mode": "field_gauntlet",
        "a_label": a_label,
        "n_per_matchup": n_per_matchup,
        "per_matchup": per_matchup,
        "expected_field_wr": expected_wr,
        "coverage_meta_share": total_weight,
        "total_matches": n_per_matchup * len(per_matchup),
        "elapsed_sec": round(elapsed, 3),
    }


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

    # Aggregate per-game winner stats: hand sizes + which cards appeared.
    # Per-game MatchResult objects are in results.results.
    from collections import Counter
    winner_hand_sizes = []
    a_inclusion = Counter()   # card name -> # of winning A-hands it was in
    b_inclusion = Counter()   # same for B
    a_wins_with_hand = 0
    b_wins_with_hand = 0
    for r in getattr(results, "results", []) or []:
        if r.winner == "a":
            winner_hand_sizes.append(7 - r.mulligans_a)
            hand = getattr(r, "hand_a", []) or []
            if hand:
                a_wins_with_hand += 1
                for name in set(hand):
                    a_inclusion[name] += 1
        elif r.winner == "b":
            winner_hand_sizes.append(7 - r.mulligans_b)
            hand = getattr(r, "hand_b", []) or []
            if hand:
                b_wins_with_hand += 1
                for name in set(hand):
                    b_inclusion[name] += 1

    avg_winner_hand = (round(sum(winner_hand_sizes) / len(winner_hand_sizes), 2)
                       if winner_hand_sizes else 7.0)
    pct_winner_kept_7 = (round(sum(1 for h in winner_hand_sizes if h == 7)
                               / len(winner_hand_sizes) * 100, 1)
                         if winner_hand_sizes else 100.0)

    def _top_cards(counter: Counter, denom: int, n: int = 12):
        if not denom:
            return []
        return [{"name": name, "pct": round(c / denom * 100, 1)}
                for name, c in counter.most_common(n)]

    a_winner_hand_top = _top_cards(a_inclusion, a_wins_with_hand)
    b_winner_hand_top = _top_cards(b_inclusion, b_wins_with_hand)

    # Calibration overlay: community real-match WR + user's personal record
    fmt = _format_of(a_label)
    real = _lookup_real_matchup(a_label, b_label, format_name=fmt)
    personal = _lookup_personal_matchup(a_label, b_label, format_name=fmt)

    return {
        "mode": "matchup",
        "a_label": a_label,
        "b_label": b_label,
        "n_games": results.n_games,
        "a_wins": results.a_wins,
        "b_wins": results.b_wins,
        "a_win_pct": results.win_pct_a(),
        "avg_turns": round(results.avg_turns, 2) if results.avg_turns else 0,
        "avg_winner_hand": avg_winner_hand,
        "pct_winner_kept_7": pct_winner_kept_7,
        "a_winner_hand_top": a_winner_hand_top,
        "b_winner_hand_top": b_winner_hand_top,
        "a_wins_with_hand": a_wins_with_hand,
        "b_wins_with_hand": b_wins_with_hand,
        "kill_distribution": results.kill_turn_distribution(),
        "elapsed_sec": round(elapsed, 3),
        "real_a_wr": real["real_a_wr"],
        "real_sample_size": real["sample_size"],
        "personal_wr": personal["personal_wr"],
        "personal_total": personal["total"],
        "personal_wins": personal["wins"],
        "personal_losses": personal["losses"],
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

        self._archetype.currentIndexChanged.connect(self._on_archetype_change)

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

        self._field_btn = QPushButton("Field")
        self._field_btn.setMinimumWidth(80)
        self._field_btn.setToolTip(
            "Run this deck against every archetype in the sim registry, "
            "weighted by current Modern meta share. Produces an expected "
            "field win rate."
        )
        self._field_btn.clicked.connect(self._on_run_field)
        ctrl.addWidget(self._field_btn)

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

        # Optional: load a saved deck from the analyzer's My Decks tab
        my_decks_row = QHBoxLayout()
        my_decks_row.addWidget(QLabel("Load from My Decks:"))
        self._my_decks_combo = QComboBox()
        self._my_decks_combo.setMinimumWidth(280)
        self._my_decks_combo.currentIndexChanged.connect(self._on_load_my_deck)
        my_decks_row.addWidget(self._my_decks_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.setMaximumWidth(80)
        refresh.clicked.connect(self._refresh_my_decks)
        my_decks_row.addWidget(refresh)
        layout.addLayout(my_decks_row)
        self._refresh_my_decks()

        # Optional paste-your-own-deck textarea (overrides the archetype's shipped deck)
        paste_hdr = QLabel(
            "Paste your decklist (optional — overrides the archetype's shipped deck, "
            "but keeps the APL you picked above):"
        )
        paste_hdr.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        paste_hdr.setWordWrap(True)
        layout.addWidget(paste_hdr)

        self._paste = QPlainTextEdit()
        self._paste.setPlaceholderText(
            "4 Monastery Swiftspear\n4 Ragavan, Nimble Pilferer\n...\n\n"
            "Sideboard\n2 Dismember\n..."
        )
        self._paste.setStyleSheet(
            f"background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; "
            f"font-family: 'Cascadia Mono', 'Consolas', 'Courier New', monospace; "
            f"font-size: 11px; padding: 6px;"
        )
        self._paste.setMaximumHeight(120)
        layout.addWidget(self._paste)

        # Debounced auto-detect: when paste changes, wait 500ms and try to
        # auto-select the best-matching archetype via the KNN classifier.
        self._autodetect_timer = QTimer(self)
        self._autodetect_timer.setSingleShot(True)
        self._autodetect_timer.setInterval(500)
        self._autodetect_timer.timeout.connect(self._auto_detect_archetype)
        self._paste.textChanged.connect(self._autodetect_timer.start)

        # Results header with copy button
        results_hdr = QHBoxLayout()
        results_hdr.addWidget(QLabel("<b>Results</b>"))
        results_hdr.addStretch(1)
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setMaximumWidth(80)
        self._copy_btn.setToolTip("Copy the full results text to the clipboard.")
        self._copy_btn.clicked.connect(self._on_copy_results)
        results_hdr.addWidget(self._copy_btn)
        layout.addLayout(results_hdr)

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

        # Sync the Goldfish-option enabled state with the default archetype.
        self._on_archetype_change(self._archetype.currentIndex())

    def _on_mode_change(self, idx: int):
        """Gray out the on-play checkbox when a real opponent is selected."""
        goldfish = (idx == 0)
        self._on_play.setEnabled(goldfish)

    def _on_archetype_change(self, a_idx: int):
        """Disable the 'Goldfish (no opponent)' option when the selected
        archetype has no goldfish APL (currently all Standard archetypes).
        Also drop the opponent selection to index 1 if Goldfish was active."""
        if a_idx < 0 or a_idx >= len(_ARCHETYPES):
            return
        has_goldfish = _ARCHETYPES[a_idx][2] is not None
        model = self._opponent.model()
        item = model.item(0) if model else None
        if item is not None:
            flags = item.flags()
            if has_goldfish:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            else:
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                if self._opponent.currentIndex() == 0 and self._opponent.count() > 1:
                    self._opponent.setCurrentIndex(1)

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
            if apl_cls is None:
                self._run_btn.setEnabled(True)
                self._progress.setVisible(False)
                self._status.setText(
                    f"{a_label} has no goldfish APL — pick an opponent instead."
                )
                self._results.setPlainText(
                    f"{a_label} is a matchup-only archetype (no solo goldfish "
                    f"variant available). Select an opponent in the 'vs' "
                    f"dropdown and try again."
                )
                return
            on_play = self._on_play.isChecked()
            deck_text = self._paste.toPlainText()
            source = "pasted deck" if deck_text.strip() else a_label
            self._status.setText(f"Running {n:,} goldfish games ({source}, {apl_cls}) ...")
            w = DataLoadWorker(_run_goldfish, kwargs=dict(
                apl_module=apl_mod, apl_class=apl_cls,
                deck_file=deck_file, n_games=n, on_play=on_play,
                deck_text=deck_text,
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

    def _on_run_field(self):
        ok, msg = _check_mtg_sim_available()
        if not ok:
            self._results.setPlainText(msg)
            return

        a_idx = self._archetype.currentIndex()
        a = _ARCHETYPES[a_idx]
        n_per = max(50, min(500, self._n_games.value() // 10 or 100))

        self._run_btn.setEnabled(False)
        self._field_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._results.clear()
        fmt = _format_of(a[0])
        field_entries = [e for e in _ARCHETYPES
                         if _format_of(e[0]) == fmt and e[0] != a[0]]
        self._status.setText(
            f"Running {a[0]} vs {len(field_entries)} field archetypes "
            f"({fmt.capitalize()}, {n_per} games each) ..."
        )

        w = DataLoadWorker(_run_field_gauntlet, kwargs=dict(
            a_label=a[0], a_match_module=a[3], a_match_class=a[4], a_deck_file=a[5],
            field_entries=field_entries,
            n_per_matchup=n_per,
        ))
        w.result.connect(self._on_result)
        w.error.connect(self._on_error)
        w.finished.connect(self._on_finished)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_result(self, data: dict):
        elapsed = data.get("elapsed_sec") or 0.001
        mode = data.get("mode")

        if mode == "matchup":
            gps = data["n_games"] / elapsed
            self._status.setText(f"Complete: {elapsed:.2f}s, {gps:.0f} games/sec")
            self._results.setPlainText(self._format_matchup(data))
        elif mode == "field_gauntlet":
            self._status.setText(
                f"Field gauntlet complete: {data['total_matches']:,} games in "
                f"{elapsed:.1f}s ({data['total_matches']/elapsed:.0f} games/sec)"
            )
            self._results.setPlainText(self._format_field(data))
        else:
            gps = data["n_games"] / elapsed
            self._status.setText(f"Complete: {elapsed:.2f}s, {gps:.0f} games/sec")
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
            f"Avg winner hand : {data.get('avg_winner_hand', 7.0):.2f} cards  "
            f"({data.get('pct_winner_kept_7', 100.0)}% kept 7)",
        ]

        # Calibration overlay: sim prediction vs real-match data + personal record
        lines.extend(["", "-- Sim vs real-match data --"])
        real_wr = data.get("real_a_wr")
        personal_wr = data.get("personal_wr")

        # Sim row always present
        lines.append(f"  Sim predicts  {a:24s}  {a_pct:5.1f}%  (n={n})")

        # Community real data
        if real_wr is not None:
            real_pct = round(real_wr * 100, 1)
            sample = data.get("real_sample_size", 0)
            delta = round(a_pct - real_pct, 1)
            sign = "+" if delta >= 0 else ""
            lines.append(f"  Real (meta)   {a:24s}  {real_pct:5.1f}%  (n={sample})")
            if abs(delta) >= 5:
                verdict = f"{sign}{delta} pts - sim {'over' if delta > 0 else 'under'}-predicts {a}"
            elif abs(delta) >= 2:
                verdict = f"{sign}{delta} pts - close match"
            else:
                verdict = f"{sign}{delta} pts - sim aligns with real data"
            lines.append(f"  Sim vs meta   {'':24s}  {verdict}")
        else:
            lines.append(f"  Real (meta)   (no scraped data for {a} vs {b} at min_matches>=10)")

        # User's personal match log
        if personal_wr is not None and data.get("personal_total", 0) > 0:
            personal_pct = round(personal_wr * 100, 1)
            total = data["personal_total"]
            wins = data["personal_wins"]
            losses = data["personal_losses"]
            delta_p = round(a_pct - personal_pct, 1)
            sign_p = "+" if delta_p >= 0 else ""
            lines.append(f"  Your log      {a:24s}  {personal_pct:5.1f}%  "
                         f"({wins}W-{losses}L, n={total})")
            lines.append(f"  Sim vs you    {'':24s}  {sign_p}{delta_p} pts")
        else:
            lines.append(f"  Your log      (no personal matches logged for {a} vs {b})")

        # Most-common cards in winning opening hands (per side)
        a_top = data.get("a_winner_hand_top") or []
        b_top = data.get("b_winner_hand_top") or []
        if a_top or b_top:
            lines.extend(["", "-- Cards in winning opening hands --"])
            if a_top:
                lines.append(f"  [{a} winners, n={data.get('a_wins_with_hand', 0)}]")
                for item in a_top:
                    lines.append(f"    {item['name']:32s} {item['pct']:5.1f}%")
            if b_top:
                lines.append(f"  [{b} winners, n={data.get('b_wins_with_hand', 0)}]")
                for item in b_top:
                    lines.append(f"    {item['name']:32s} {item['pct']:5.1f}%")

        lines.extend(["", "Kill turn distribution (winner):"])
        for turn, pct in data.get("kill_distribution", {}).items():
            bar = "\u2588" * int(pct / 2)
            lines.append(f"  T{turn:2d}  {pct:5.1f}%  {bar}")
        return "\n".join(lines)

    def _on_error(self, msg: str):
        self._status.setText("Error")
        self._results.setPlainText(f"Simulation failed:\n\n{msg}")

    def _on_copy_results(self):
        text = self._results.toPlainText()
        if not text.strip():
            self._status.setText("Nothing to copy — run a sim first.")
            return
        QApplication.clipboard().setText(text)
        prev = self._status.text()
        self._status.setText("Copied to clipboard.")
        # Restore previous status after 2 seconds
        QTimer.singleShot(2000, lambda: self._status.setText(prev))

    @staticmethod
    def _format_field(data: dict) -> str:
        a = data["a_label"]
        n = data["n_per_matchup"]
        expected = round(data["expected_field_wr"] * 100, 1)
        coverage = round(data["coverage_meta_share"] * 100, 1)
        fmt = _format_of(a).capitalize()

        lines = [
            f"== {a} vs field ({fmt}) | {n} games per matchup ==",
            "",
            f"Expected field WR: {expected}%  "
            f"(weighted over {len(data['per_matchup'])} covered archetypes, "
            f"{coverage}% of meta)",
            "",
            "Per matchup (sorted by meta share):",
            "",
            f"  {'Opponent':32s} {'Meta%':>7s} {'Sim WR':>8s}",
            f"  {'-'*32} {'-'*7} {'-'*8}",
        ]
        sorted_matchups = sorted(data["per_matchup"],
                                 key=lambda m: m["meta_share"], reverse=True)
        for m in sorted_matchups:
            share_pct = m["meta_share"] * 100
            sim_pct = m["sim_wr"] * 100
            star = " *" if share_pct == 0 else ""
            lines.append(
                f"  {m['opp_label']:32s} {share_pct:>6.1f}% {sim_pct:>7.1f}%{star}"
            )
        lines.extend([
            "",
            "* = archetype has no meta-share data in the scraped DB; "
            "uniform-weighted into the expected WR.",
        ])
        return "\n".join(lines)

    def _on_finished(self):
        self._run_btn.setEnabled(True)
        self._field_btn.setEnabled(True)
        self._progress.setVisible(False)

    def _auto_detect_archetype(self):
        """Parse the paste text, ask KNN for the best matching archetype,
        select it in the dropdown if we ship an APL for it.
        Silent no-op when:
          - paste is empty or too small to classify
          - classifier can't confidently identify
          - returned archetype isn't in our registry
        """
        text = self._paste.toPlainText().strip()
        if len(text) < 20:
            return  # too short to be a deck

        try:
            # Reuse the analyzer's existing parser
            from gui.tabs.deck_analyzer import parse_arena_decklist
            main, _side = parse_arena_decklist(text)
            if not main or sum(main.values()) < 40:
                return  # not a plausible 60-card deck

            from analysis.knn_classifier import hybrid_classify
            from analysis.archetypes import normalize as norm_arch
            # Respect the currently-selected archetype's format so paste
            # classification matches the registry the user is browsing.
            cur_idx = self._archetype.currentIndex()
            cur_label = (_ARCHETYPES[cur_idx][0]
                         if 0 <= cur_idx < len(_ARCHETYPES) else "")
            fmt = _format_of(cur_label) if cur_label else "modern"
            arch = hybrid_classify(main, format_name=fmt)
            if not arch:
                return

            # Find the matching archetype in _ARCHETYPES by normalized name
            target_norm = norm_arch(arch).lower()
            for i, entry in enumerate(_ARCHETYPES):
                entry_label_bare = entry[0]
                for suf in (" (Modern)", " (Standard)", " (Pioneer)", " (Legacy)"):
                    if entry_label_bare.endswith(suf):
                        entry_label_bare = entry_label_bare[:-len(suf)].strip()
                        break
                if norm_arch(entry_label_bare).lower() == target_norm:
                    if self._archetype.currentIndex() != i:
                        self._archetype.setCurrentIndex(i)
                        self._status.setText(
                            f"Auto-detected: {arch} -> {entry[0]} APL selected."
                        )
                    return
            # Classified but not in our registry — note it in the status line
            self._status.setText(
                f"Auto-detected: {arch} (no APL in registry for this archetype)."
            )
        except Exception:
            # Silent — classifier may be missing its model file, etc.
            pass

    def _refresh_my_decks(self):
        """Populate the My Decks dropdown from the saved_decks table."""
        self._my_decks_combo.blockSignals(True)
        self._my_decks_combo.clear()
        self._my_decks_combo.addItem("-- choose a saved deck --")
        self._my_decks_cache = []
        try:
            from db.saved_decks import get_decks
            decks = get_decks()
            for d in decks:
                fmt = d.get("format", "") or "?"
                label = f"{d.get('name', '(unnamed)')}  [{fmt}]"
                self._my_decks_combo.addItem(label)
                self._my_decks_cache.append(d)
        except Exception:
            # DB missing / not bootstrapped yet — silently skip.
            pass
        self._my_decks_combo.blockSignals(False)

    def _on_load_my_deck(self, idx: int):
        if idx <= 0:
            return
        if idx - 1 >= len(self._my_decks_cache):
            return
        deck = self._my_decks_cache[idx - 1]
        text = self._deck_to_text(deck)
        self._paste.setPlainText(text)
        # Nudge: show a tip via the status line
        self._status.setText(
            f"Loaded '{deck.get('name', '(unnamed)')}' into the paste area. "
            f"Pick an archetype whose APL matches this deck, then Run."
        )

    @staticmethod
    def _deck_to_text(deck: dict) -> str:
        """Format a saved-deck dict ({name, mainboard: {card: qty}, sideboard: {...}}) as plain text."""
        lines = []
        mb = deck.get("mainboard") or {}
        for card, qty in sorted(mb.items()):
            lines.append(f"{qty} {card}")
        sb = deck.get("sideboard") or {}
        if sb:
            lines.append("")
            lines.append("Sideboard")
            for card, qty in sorted(sb.items()):
                lines.append(f"{qty} {card}")
        return "\n".join(lines)

    def set_deck_paste(self, deck_text: str, source_label: str = "",
                       format_hint: str = None):
        """External entry: load a decklist into the paste area.
        Used by cross-tab 'Simulate this deck' actions (from Deck Analyzer,
        Deck Search, Dashboard avg-deck, etc.). Does NOT auto-run.

        format_hint: 'modern' / 'standard' / etc. When provided, pre-selects
        the first archetype of that format so KNN auto-detect classifies in
        the right format.
        """
        if format_hint:
            target = format_hint.lower()
            for i, entry in enumerate(_ARCHETYPES):
                if _format_of(entry[0]) == target:
                    if self._archetype.currentIndex() != i:
                        self._archetype.setCurrentIndex(i)
                    break
        self._paste.setPlainText(deck_text)
        if source_label:
            self._status.setText(
                f"Loaded '{source_label}' into the paste area. "
                f"Pick an archetype whose APL matches, then Run."
            )

    def set_matchup(self, a_label: str, b_label: str):
        """External entry for 'jump to this matchup from another tab'.
        Sets the archetype + opponent dropdowns to the requested labels
        (silently no-ops if either label isn't in the registry)."""
        # Find the archetype dropdown index for a_label
        for i in range(self._archetype.count()):
            if self._archetype.itemText(i) == a_label:
                self._archetype.setCurrentIndex(i)
                break
        # Opponent dropdown: index 0 is 'Goldfish', archetypes start at 1
        for j in range(1, self._opponent.count()):
            if self._opponent.itemText(j) == b_label:
                self._opponent.setCurrentIndex(j)
                break

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
