"""
Bo3 match math -- Chapin, Next Level Magic Forever p.90 (rule MG-12).

A best-of-three is not linear in game win rate, and a sideboard plan acts on
post-board games only. With p1 = game-1 win rate and q = post-board game win
rate:

    P(match) = p1 * (2q - q^2) + (1 - p1) * q^2

Win G1 (p1) then need one of two post-board games (2q - q^2); lose G1 then
need both (q^2). Sensitivity dP/dq = 2*p1 + 2q*(1 - 2*p1) runs about
0.84-1.16 over realistic inputs, so a flat +/-5pp bump applied to the MATCH
win rate is off by up to ~16% relative -- it overstates sideboard help where
you already win game 1 and understates it where you are losing game 1. A
refinement, not a five-alarm bug; do not oversell it in the UI.

Data constraint: scraped rows are match-level only, so p1 and q are not
separately observable per matchup. `implied_q` recovers the q that a
matchup's observed match WR implies for a given p1; `required_q` answers
the question RC prep actually asks: "to reach X%, this sideboard plan has to
get post-board games to ...%".

Pure functions, no I/O. Not to be confused with analysis/chapin.py (the
six-pillar deck-construction scorer), which this module does not import.
"""
import math

_EPS = 1e-9


def _check(name: str, x: float) -> None:
    if not (-_EPS <= x <= 1.0 + _EPS):
        raise ValueError(f"{name} must be in [0, 1], got {x!r}")


def match_winrate(p1: float, q: float) -> float:
    """P(win Bo3) given game-1 win rate p1 and post-board game win rate q."""
    _check("p1", p1)
    _check("q", q)
    return p1 * (2.0 * q - q * q) + (1.0 - p1) * q * q


def implied_q(p1: float, observed_match_wr: float) -> float | None:
    """
    The post-board game win rate q that makes match_winrate(p1, q) equal
    `observed_match_wr`. None when no q in [0, 1] can produce it.

    P = (1 - 2*p1) * q^2 + 2*p1 * q, so
        q = (-p1 + sqrt(p1^2 + (1 - 2*p1) * P)) / (1 - 2*p1)      (p1 != 0.5)
        q = P                                                   (p1 == 0.5)
    The '+' root is the one on [0, 1] for every p1 in [0, 1]; the
    discriminant is >= (1 - p1)^2 >= 0 whenever 0 <= P <= 1.
    """
    _check("p1", p1)
    P = observed_match_wr
    if P < -_EPS or P > 1.0 + _EPS:
        return None
    P = min(1.0, max(0.0, P))
    a = 1.0 - 2.0 * p1
    if abs(a) < _EPS:
        q = P
    else:
        disc = p1 * p1 + a * P
        if disc < 0:
            return None
        q = (-p1 + math.sqrt(disc)) / a
    if q < -_EPS or q > 1.0 + _EPS:
        return None
    return min(1.0, max(0.0, q))


def required_q(p1: float, target_match_wr: float) -> float | None:
    """
    Post-board game win rate needed to reach `target_match_wr` from game-1
    win rate p1. None when the target is unreachable (q would exceed 1).

    This is the number RC prep wants: for an unfavourable matchup, "to reach
    50%, the sideboard plan has to get post-board games to X%".
    """
    return implied_q(p1, target_match_wr)
