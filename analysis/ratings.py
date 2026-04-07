"""
Glicko-2 archetype power ratings.

Treats each archetype as a "player" and computes ratings from real match
results in the matches table.  Matches are grouped into weekly rating
periods — each week's results update all archetypes that played.

The Glicko-2 algorithm (Mark Glickman, 2012) produces:
    - rating (µ)      : skill estimate (higher = stronger)
    - deviation (φ)    : uncertainty (lower = more confident)
    - volatility (σ)   : consistency (lower = more stable results)

No external dependencies — pure Python + math stdlib.

Reference: http://www.glicko.net/glicko/glicko2.pdf
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from db.database import get_connection

# ---------------------------------------------------------------------------
# Glicko-2 constants
# ---------------------------------------------------------------------------

_TAU      = 0.5      # system volatility constant (controls σ change speed)
_EPSILON  = 0.000001 # convergence threshold for σ iteration
_INIT_MU  = 1500.0   # initial rating
_INIT_PHI = 350.0    # initial deviation
_INIT_SIG = 0.06     # initial volatility
_SCALE    = 173.7178 # Glicko-2 scaling factor (400 / ln(10))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GlickoRating:
    mu: float = _INIT_MU
    phi: float = _INIT_PHI
    sigma: float = _INIT_SIG
    matches: int = 0


@dataclass
class RatingResult:
    """Public-facing result for one archetype."""
    archetype: str
    rating: float
    deviation: float
    volatility: float
    matches: int
    rank: int = 0

    @property
    def confidence_interval(self) -> tuple[float, float]:
        return (self.rating - 2 * self.deviation,
                self.rating + 2 * self.deviation)

    @property
    def display(self) -> str:
        return f"{self.rating:.0f} ±{self.deviation:.0f}"


# ---------------------------------------------------------------------------
# Glicko-2 math (internal scale: µ' = (µ-1500)/173.7, φ' = φ/173.7)
# ---------------------------------------------------------------------------

def _to_glicko2(mu: float, phi: float) -> tuple[float, float]:
    return (mu - _INIT_MU) / _SCALE, phi / _SCALE


def _from_glicko2(mu2: float, phi2: float) -> tuple[float, float]:
    return mu2 * _SCALE + _INIT_MU, phi2 * _SCALE


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _update_rating(r: GlickoRating,
                   opponents: list[tuple[float, float, float]]) -> GlickoRating:
    """Update a single archetype's rating given a list of (opp_mu2, opp_phi2, score).

    score: 1.0 = win, 0.0 = loss, 0.5 = draw
    """
    mu2, phi2 = _to_glicko2(r.mu, r.phi)
    sigma = r.sigma

    if not opponents:
        # No games: increase uncertainty
        phi_star = math.sqrt(phi2 * phi2 + sigma * sigma)
        new_mu, new_phi = _from_glicko2(mu2, phi_star)
        return GlickoRating(new_mu, new_phi, sigma, r.matches)

    # Step 3: compute v (estimated variance)
    v_inv = 0.0
    delta_sum = 0.0
    for opp_mu2, opp_phi2, s in opponents:
        g_j = _g(opp_phi2)
        e_j = _E(mu2, opp_mu2, opp_phi2)
        v_inv += g_j * g_j * e_j * (1.0 - e_j)
        delta_sum += g_j * (s - e_j)

    v = 1.0 / v_inv if v_inv > 0 else 1e6
    delta = v * delta_sum

    # Step 4: compute new volatility σ' (Illinois algorithm)
    a = math.log(sigma * sigma)
    f = lambda x: (
        (math.exp(x) * (delta * delta - phi2 * phi2 - v - math.exp(x)))
        / (2.0 * (phi2 * phi2 + v + math.exp(x)) ** 2)
        - (x - a) / (_TAU * _TAU)
    )

    A = a
    if delta * delta > phi2 * phi2 + v:
        B = math.log(delta * delta - phi2 * phi2 - v)
    else:
        k = 1
        while f(a - k * _TAU) < 0:
            k += 1
        B = a - k * _TAU

    fA, fB = f(A), f(B)
    for _ in range(100):  # max iterations
        if abs(B - A) < _EPSILON:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2.0
        B, fB = C, fC

    new_sigma = math.exp(A / 2.0)

    # Step 5-6: update rating and deviation
    phi_star = math.sqrt(phi2 * phi2 + new_sigma * new_sigma)
    new_phi2 = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu2 = mu2 + new_phi2 * new_phi2 * delta_sum

    new_mu, new_phi = _from_glicko2(new_mu2, new_phi2)
    return GlickoRating(new_mu, new_phi, new_sigma, r.matches + len(opponents))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Simple TTL cache
_ratings_cache: dict = {}
_CACHE_TTL = 120  # seconds


def compute_archetype_ratings(
    format_name: str,
    since: datetime | None = None,
    min_matches: int = 10,
) -> list[RatingResult]:
    """Compute Glicko-2 ratings for all archetypes in a format.

    Matches are grouped into weekly rating periods.  Each period's results
    are processed as a batch update for every archetype that played.

    Parameters
    ----------
    format_name : str       e.g. "standard", "modern"
    since       : datetime  only consider matches after this date (None = all)
    min_matches : int       minimum matches for an archetype to be rated

    Returns
    -------
    list[RatingResult] sorted by rating descending
    """
    cache_key = (format_name, str(since), min_matches)
    now = time.time()
    if cache_key in _ratings_cache:
        ts, result = _ratings_cache[cache_key]
        if now - ts < _CACHE_TTL:
            return result

    # Exclude placeholder archetype names
    from analysis.win_rates import EXCLUDE_ARCHETYPES

    conn = get_connection()
    try:
        q = """
            SELECT player1_arch, player2_arch, winner_arch, result, event_date
            FROM matches
            WHERE lower(format) = lower(?)
        """
        params: list = [format_name]
        if since:
            q += " AND event_date >= ?"
            params.append(since.strftime("%Y-%m-%d"))
        q += " ORDER BY event_date ASC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    # Group matches into weekly periods
    periods: dict[str, list] = defaultdict(list)
    for r in rows:
        a1, a2 = r["player1_arch"], r["player2_arch"]
        if a1 in EXCLUDE_ARCHETYPES or a2 in EXCLUDE_ARCHETYPES:
            continue
        if not a1 or not a2:
            continue
        # Normalize archetype names
        try:
            from analysis.archetypes import normalize
            a1 = normalize(a1)
            a2 = normalize(a2)
        except Exception:
            pass

        # Determine score
        winner = r["winner_arch"]
        result = r["result"]
        if result == "draw" or not winner:
            s1, s2 = 0.5, 0.5
        elif winner == a1 or result == "player1":
            s1, s2 = 1.0, 0.0
        else:
            s1, s2 = 0.0, 1.0

        # Week key for rating period
        date_str = r["event_date"] or "1970-01-01"
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            week_key = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        except ValueError:
            week_key = "1970-01-01"

        periods[week_key].append((a1, a2, s1, s2))

    # Process each rating period in chronological order
    ratings: dict[str, GlickoRating] = defaultdict(GlickoRating)

    for week in sorted(periods.keys()):
        # Collect all match results per archetype for this period
        arch_games: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
        played_this_week: set[str] = set()

        for a1, a2, s1, s2 in periods[week]:
            r1 = ratings[a1]
            r2 = ratings[a2]
            mu2_1, phi2_1 = _to_glicko2(r1.mu, r1.phi)
            mu2_2, phi2_2 = _to_glicko2(r2.mu, r2.phi)
            arch_games[a1].append((mu2_2, phi2_2, s1))
            arch_games[a2].append((mu2_1, phi2_1, s2))
            played_this_week.add(a1)
            played_this_week.add(a2)

        # Update ratings for archetypes that played
        for arch in played_this_week:
            ratings[arch] = _update_rating(ratings[arch], arch_games[arch])

    # Filter and sort
    results = []
    for arch, r in ratings.items():
        if r.matches < min_matches:
            continue
        results.append(RatingResult(
            archetype=arch,
            rating=round(r.mu, 1),
            deviation=round(r.phi, 1),
            volatility=round(r.sigma, 4),
            matches=r.matches,
        ))

    results.sort(key=lambda x: -x.rating)
    for i, r in enumerate(results):
        r.rank = i + 1

    _ratings_cache[cache_key] = (now, results)
    return results


def get_ratings_map(format_name: str,
                    since: datetime | None = None,
                    min_matches: int = 10) -> dict[str, RatingResult]:
    """Return ratings as a dict keyed by archetype name."""
    return {r.archetype: r for r in compute_archetype_ratings(
        format_name, since, min_matches)}
