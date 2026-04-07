"""
Nash Equilibrium, Replicator Dynamics, and RPS Cycle Detection.

Takes an NxN matchup matrix and computes:
    - Nash equilibrium (theoretically optimal field distribution)
    - Replicator dynamics (evolutionary stable metagame)
    - Rock-Paper-Scissors cycle detection
    - Monte Carlo tournament simulation

All algorithms operate on numpy arrays built from the existing matchup
data in win_rates.py.  No UI coupling.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from collections import defaultdict

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EquilibriumResult:
    """Result of a Nash / replicator dynamics computation."""
    archetypes: list[str]
    optimal_shares: dict[str, float]     # archetype → optimal fraction
    current_shares: dict[str, float]     # archetype → current fraction
    deltas: dict[str, float]             # archetype → (optimal - current)
    statuses: dict[str, str]             # archetype → Overplayed/Underplayed/Balanced
    converged: bool = True
    iterations: int = 0


@dataclass
class RPSCycle:
    """A detected Rock-Paper-Scissors cycle."""
    archetypes: tuple[str, str, str]     # (A beats B, B beats C, C beats A)
    win_rates: tuple[float, float, float]  # WR of each winning side
    strength: float                       # average win rate of the cycle


@dataclass
class SimulationResult:
    """Result of a Monte Carlo tournament simulation."""
    top8_rates: dict[str, float]         # archetype → fraction of top 8s
    win_rates: dict[str, float]          # archetype → simulated match WR
    simulations: int


# ---------------------------------------------------------------------------
# Matrix builder — converts win_rates.py output to numpy
# ---------------------------------------------------------------------------

def build_payoff_matrix(
    matchup_data: dict,
    archetypes: list[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Convert matchup dict to a square payoff matrix.

    Parameters
    ----------
    matchup_data : dict from get_real_matchup_winrates()
        {arch_a: {arch_b: {"win_rate": float, ...}}} where a < b
    archetypes : optional list to restrict/order the matrix

    Returns
    -------
    (matrix, arch_list) where matrix[i][j] = win rate of arch_list[i] vs arch_list[j]
    Diagonal is 0.5 (mirror match).
    """
    # Collect all archetypes that appear in the data
    all_archs: set[str] = set()
    for a, opponents in matchup_data.items():
        all_archs.add(a)
        for b in opponents:
            all_archs.add(b)

    if archetypes:
        arch_list = [a for a in archetypes if a in all_archs]
    else:
        arch_list = sorted(all_archs)

    n = len(arch_list)
    idx = {a: i for i, a in enumerate(arch_list)}
    matrix = np.full((n, n), 0.5)  # default: even matchup

    for a, opponents in matchup_data.items():
        if a not in idx:
            continue
        for b, stats in opponents.items():
            if b not in idx:
                continue
            wr = stats["win_rate"]
            matrix[idx[a]][idx[b]] = wr
            matrix[idx[b]][idx[a]] = 1.0 - wr

    return matrix, arch_list


# ---------------------------------------------------------------------------
# Replicator dynamics
# ---------------------------------------------------------------------------

def replicator_dynamics(
    matrix: np.ndarray,
    arch_list: list[str],
    current_shares: dict[str, float] | None = None,
    generations: int = 2000,
    dt: float = 0.3,
    tolerance: float = 1e-6,
) -> EquilibriumResult:
    """Run replicator dynamics to find evolutionary stable metagame shares.

    The replicator equation: dx_i/dt = x_i * (f_i(x) - avg_f(x))
    where f_i is archetype i's expected win rate vs the current population.

    Parameters
    ----------
    matrix         : NxN payoff matrix (matrix[i][j] = i's WR vs j)
    arch_list      : archetype names corresponding to matrix rows
    current_shares : actual meta shares (for comparison). If None, uses uniform.
    generations    : max iterations
    dt             : step size (larger = faster but less stable)
    tolerance      : convergence threshold (max change in any share)

    Returns
    -------
    EquilibriumResult with optimal shares and over/underplayed status
    """
    n = len(arch_list)
    if n == 0:
        return EquilibriumResult([], {}, {}, {}, {}, True, 0)

    # Initial population: uniform distribution
    x = np.ones(n) / n

    converged = False
    final_iter = 0

    for gen in range(generations):
        # Fitness of each archetype vs current population
        fitness = matrix @ x  # f_i = sum_j(matrix[i][j] * x_j)
        avg_fitness = x @ fitness  # weighted average fitness

        # Replicator update
        dx = x * (fitness - avg_fitness) * dt
        x_new = x + dx

        # Clamp negatives, renormalize
        x_new = np.maximum(x_new, 0.0)
        total = x_new.sum()
        if total > 0:
            x_new /= total
        else:
            x_new = np.ones(n) / n

        # Check convergence
        if np.max(np.abs(x_new - x)) < tolerance:
            converged = True
            final_iter = gen + 1
            x = x_new
            break

        x = x_new
        final_iter = gen + 1

    # Build current shares dict
    if current_shares is None:
        cur = {a: 1.0 / n for a in arch_list}
    else:
        total_cur = sum(current_shares.get(a, 0) for a in arch_list) or 1
        cur = {a: current_shares.get(a, 0) / total_cur for a in arch_list}

    optimal = {a: float(x[i]) for i, a in enumerate(arch_list)}
    deltas = {a: optimal[a] - cur[a] for a in arch_list}

    statuses = {}
    for a in arch_list:
        d = deltas[a]
        if d > 0.02:
            statuses[a] = "Underplayed"
        elif d < -0.02:
            statuses[a] = "Overplayed"
        else:
            statuses[a] = "Balanced"

    return EquilibriumResult(
        archetypes=arch_list,
        optimal_shares=optimal,
        current_shares=cur,
        deltas=deltas,
        statuses=statuses,
        converged=converged,
        iterations=final_iter,
    )


# ---------------------------------------------------------------------------
# Nash equilibrium via linear programming
# ---------------------------------------------------------------------------

def nash_equilibrium(
    matrix: np.ndarray,
    arch_list: list[str],
    current_shares: dict[str, float] | None = None,
) -> EquilibriumResult:
    """Compute Nash equilibrium (mixed strategy) via linear programming.

    Solves the zero-sum game: find x that maximizes min_j(sum_i x_i * M[i][j]).
    Uses scipy.optimize.linprog.

    Falls back to replicator dynamics if scipy fails.
    """
    from scipy.optimize import linprog

    n = len(arch_list)
    if n == 0:
        return EquilibriumResult([], {}, {}, {}, {}, True, 0)

    # Convert win rates to payoff (centered at 0: WR - 0.5)
    P = matrix - 0.5

    # LP: maximize v subject to P^T x >= v*1, sum(x)=1, x>=0
    # Rewrite as minimize -v:
    #   variables: [x_1..x_n, v]
    #   -P^T x + v <= 0  (n constraints)
    #   sum(x) = 1
    #   x >= 0, v unconstrained (but we make it bounded)
    try:
        c = np.zeros(n + 1)
        c[n] = -1  # minimize -v

        # Inequality: v - P^T x <= 0  →  -P^T x + v <= 0
        A_ub = np.zeros((n, n + 1))
        A_ub[:, :n] = -P.T
        A_ub[:, n] = 1
        b_ub = np.zeros(n)

        # Equality: sum(x) = 1
        A_eq = np.zeros((1, n + 1))
        A_eq[0, :n] = 1
        b_eq = np.array([1.0])

        bounds = [(0, 1)] * n + [(None, None)]

        result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                         bounds=bounds, method="highs")

        if result.success:
            x = result.x[:n]
            x = np.maximum(x, 0)
            x /= x.sum()
        else:
            # Fallback to replicator dynamics
            return replicator_dynamics(matrix, arch_list, current_shares)

    except Exception:
        return replicator_dynamics(matrix, arch_list, current_shares)

    # Build result
    if current_shares is None:
        cur = {a: 1.0 / n for a in arch_list}
    else:
        total_cur = sum(current_shares.get(a, 0) for a in arch_list) or 1
        cur = {a: current_shares.get(a, 0) / total_cur for a in arch_list}

    optimal = {a: float(x[i]) for i, a in enumerate(arch_list)}
    deltas = {a: optimal[a] - cur[a] for a in arch_list}

    statuses = {}
    for a in arch_list:
        d = deltas[a]
        if d > 0.02:
            statuses[a] = "Underplayed"
        elif d < -0.02:
            statuses[a] = "Overplayed"
        else:
            statuses[a] = "Balanced"

    return EquilibriumResult(
        archetypes=arch_list,
        optimal_shares=optimal,
        current_shares=cur,
        deltas=deltas,
        statuses=statuses,
        converged=True,
        iterations=0,
    )


# ---------------------------------------------------------------------------
# RPS cycle detection
# ---------------------------------------------------------------------------

def detect_rps_cycles(
    matrix: np.ndarray,
    arch_list: list[str],
    min_wr: float = 0.53,
    max_cycles: int = 20,
) -> list[RPSCycle]:
    """Find Rock-Paper-Scissors cycles in the matchup matrix.

    A cycle is A→B→C→A where each arrow means the source has WR ≥ min_wr
    against the target.

    Parameters
    ----------
    matrix    : NxN payoff matrix
    arch_list : archetype names
    min_wr    : minimum win rate to count as "beats" (default 53%)
    max_cycles: cap on returned cycles

    Returns
    -------
    list[RPSCycle] sorted by cycle strength (strongest first)
    """
    n = len(arch_list)
    cycles: list[RPSCycle] = []

    for i in range(n):
        for j in range(n):
            if i == j or matrix[i][j] < min_wr:
                continue
            for k in range(n):
                if k == i or k == j:
                    continue
                if matrix[j][k] >= min_wr and matrix[k][i] >= min_wr:
                    # Found cycle: i beats j, j beats k, k beats i
                    # Canonicalize: smallest index first
                    triple = (i, j, k)
                    canon = min((i, j, k), (j, k, i), (k, i, j))
                    if canon != triple:
                        continue  # skip non-canonical rotations

                    wr_ij = matrix[i][j]
                    wr_jk = matrix[j][k]
                    wr_ki = matrix[k][i]
                    strength = (wr_ij + wr_jk + wr_ki) / 3

                    cycles.append(RPSCycle(
                        archetypes=(arch_list[i], arch_list[j], arch_list[k]),
                        win_rates=(round(wr_ij, 3), round(wr_jk, 3), round(wr_ki, 3)),
                        strength=round(strength, 3),
                    ))

    cycles.sort(key=lambda c: -c.strength)
    return cycles[:max_cycles]


# ---------------------------------------------------------------------------
# Monte Carlo tournament simulation
# ---------------------------------------------------------------------------

def simulate_tournament(
    matrix: np.ndarray,
    arch_list: list[str],
    field_shares: dict[str, float],
    players: int = 128,
    rounds: int = 7,
    top_cut: int = 8,
    simulations: int = 10000,
) -> SimulationResult:
    """Monte Carlo tournament simulation.

    Randomly assigns archetypes to players based on field shares, pairs
    them Swiss-style (simplified: random pairing per round), resolves
    matches via the payoff matrix, and counts top-cut appearances.

    Parameters
    ----------
    matrix       : NxN payoff matrix
    arch_list    : archetype names
    field_shares : {archetype: fraction} for population
    players      : number of players per simulated tournament
    rounds       : number of Swiss rounds
    top_cut      : how many make the cut
    simulations  : number of tournaments to simulate
    """
    n = len(arch_list)
    idx = {a: i for i, a in enumerate(arch_list)}

    # Build cumulative probability for archetype assignment
    probs = np.array([field_shares.get(a, 0) for a in arch_list])
    if probs.sum() == 0:
        probs = np.ones(n) / n
    else:
        probs /= probs.sum()

    top8_counts = np.zeros(n)
    total_wins = np.zeros(n)
    total_matches = np.zeros(n)

    rng = np.random.default_rng()

    for _ in range(simulations):
        # Assign archetypes to players
        player_archs = rng.choice(n, size=players, p=probs)
        wins = np.zeros(players)

        for _round in range(rounds):
            # Simplified Swiss: shuffle and pair adjacent
            order = rng.permutation(players)
            for p in range(0, players - 1, 2):
                a = player_archs[order[p]]
                b = player_archs[order[p + 1]]
                wr = matrix[a][b]
                if rng.random() < wr:
                    wins[order[p]] += 1
                else:
                    wins[order[p + 1]] += 1
                total_matches[a] += 1
                total_matches[b] += 1
                total_wins[a] += wr  # expected wins accumulation
                total_wins[b] += (1 - wr)

        # Top cut: players with most wins
        top_indices = np.argsort(-wins)[:top_cut]
        for idx_p in top_indices:
            top8_counts[player_archs[idx_p]] += 1

    total_top8 = top_cut * simulations
    total_match_sum = total_matches.sum() or 1

    top8_rates = {arch_list[i]: round(top8_counts[i] / total_top8, 4)
                  for i in range(n) if top8_counts[i] > 0}
    sim_wrs = {arch_list[i]: round(total_wins[i] / total_matches[i], 4)
               for i in range(n) if total_matches[i] > 0}

    return SimulationResult(
        top8_rates=dict(sorted(top8_rates.items(), key=lambda x: -x[1])),
        win_rates=sim_wrs,
        simulations=simulations,
    )


# ---------------------------------------------------------------------------
# Convenience: full analysis from format name
# ---------------------------------------------------------------------------

# Cache
_eq_cache: dict = {}
_CACHE_TTL = 120


def analyze_metagame(
    format_name: str,
    since=None,
    top: int = 15,
    method: str = "replicator",
) -> dict:
    """Run full equilibrium analysis for a format.

    Returns dict with:
        equilibrium : EquilibriumResult
        cycles      : list[RPSCycle]
        matrix      : np.ndarray
        archetypes  : list[str]
    """
    cache_key = f"eq:{format_name}:{since}:{top}:{method}"
    now = time.time()
    if cache_key in _eq_cache:
        ts, result = _eq_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return result

    from analysis.win_rates import (
        get_real_matchup_winrates, get_meta_standings,
    )
    from datetime import datetime

    # Get matchup matrix
    matchup_data = get_real_matchup_winrates(
        format_name, since=since, min_matches=10, min_arch_appearances=10
    )
    if not matchup_data:
        return {"equilibrium": None, "cycles": [], "matrix": None, "archetypes": []}

    # Get current meta shares for comparison
    standings = get_meta_standings(format_name, since=since, top=top * 2,
                                   min_appearances=2)
    total_apps = sum(s["appearances"] for s in standings) or 1
    current_shares = {s["archetype"]: s["appearances"] / total_apps
                      for s in standings}

    # Restrict matrix to top archetypes that have matchup data
    arch_with_data = set()
    for a, opps in matchup_data.items():
        arch_with_data.add(a)
        for b in opps:
            arch_with_data.add(b)

    # Prioritize by meta share, but only include those with matchup data
    ranked = sorted(
        [(a, current_shares.get(a, 0)) for a in arch_with_data],
        key=lambda x: -x[1]
    )[:top]
    top_archs = [a for a, _ in ranked]

    matrix, arch_list = build_payoff_matrix(matchup_data, top_archs)

    if len(arch_list) < 3:
        return {"equilibrium": None, "cycles": [], "matrix": matrix,
                "archetypes": arch_list}

    # Run equilibrium solver
    if method == "nash":
        eq = nash_equilibrium(matrix, arch_list, current_shares)
    else:
        eq = replicator_dynamics(matrix, arch_list, current_shares)

    # Detect RPS cycles
    cycles = detect_rps_cycles(matrix, arch_list)

    result = {
        "equilibrium": eq,
        "cycles": cycles,
        "matrix": matrix,
        "archetypes": arch_list,
    }

    _eq_cache[cache_key] = (now, result)
    return result
