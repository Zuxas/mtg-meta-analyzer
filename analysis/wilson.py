"""Wilson score interval + tweak classification.

Used by the Match Log Variant Timeline to surface 'did this tweak help?'
honestly. Naive WR delta is misleading at small N; Wilson bounds + a
classification rule give a 3-state verdict (validated / promising / noisy)
without making predictive claims.
"""
from __future__ import annotations

import math
from fractions import Fraction

# Two-sided z at 95% confidence
_Z_95 = 1.959963984540054


def wilson_bounds(wins: int, total: int, z: float = _Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (lower, upper) on [0.0, 1.0]. For total=0 returns (0.0, 1.0)
    -- maximally uninformative band, the right answer when we have no data."""
    if total <= 0:
        return (0.0, 1.0)
    n = float(total)
    p = wins / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) / n) + (z * z) / (4.0 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def classify_tweak(prev_wins: int, prev_total: int,
                   curr_wins: int, curr_total: int) -> str:
    """Three-state verdict on whether a variant change moved win rate.

    Returns one of:
      - 'validated' : the 95% Wilson bands do not overlap. A conservative
                      heuristic for real separation, not a formal two-proportion test.
      - 'promising' : |delta| >= 10pp but the bands overlap.
      - 'noisy'     : everything else.

    An N>=10 / 10pp rule used to return 'validated' too, which called
    4/10 -> 6/10 (bands [0.17, 0.69] and [0.31, 0.83]) a proven improvement.
    The delta is compared exactly (Fraction), so 6/10 -> 7/10 is 10pp, not
    0.0999... < 0.10.
    """
    if prev_total == 0 or curr_total == 0:
        return "noisy"

    delta = Fraction(curr_wins, curr_total) - Fraction(prev_wins, prev_total)

    prev_lo, prev_hi = wilson_bounds(prev_wins, prev_total)
    curr_lo, curr_hi = wilson_bounds(curr_wins, curr_total)

    bands_overlap = not (curr_lo > prev_hi or prev_lo > curr_hi)

    if not bands_overlap:
        return "validated"
    if abs(delta) >= Fraction(1, 10):
        return "promising"
    return "noisy"
