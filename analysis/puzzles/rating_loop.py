"""Glicko-2 rating loop for the puzzle trainer (T3, puzzle trainer v0).

Each puzzle attempt is a one-game Glicko-2 "match" between the user and the
puzzle: a correct answer is a user win, incorrect a user loss. We reuse the
already-validated ``analysis.ratings._update_rating`` (do NOT reimplement the
math) and persist through ``db.puzzles`` rating store.

Design notes
------------
* Single-user app -> one user row (entity_id ``"default"``). Puzzles are keyed
  by ``str(puzzle_id)``.
* A puzzle's rating cold-starts from its difficulty stars (harder == higher mu),
  keeping the default deviation/volatility so a fresh puzzle is appropriately
  uncertain.
* Per-attempt single-game update (each attempt is its own rating period) is the
  spec directive and how live Glicko-2 sites approximate real-time ratings.
* Both sides update simultaneously: we snapshot each opponent's Glicko-2 internal
  coordinates BEFORE updating either, matching ``compute_archetype_ratings``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.ratings import (
    GlickoRating,
    _INIT_MU,
    _INIT_PHI,
    _INIT_SIG,
    _to_glicko2,
    _update_rating,
)
from db import puzzles as _db

# verdict -> Glicko score for the USER (1.0 win / 0.5 draw / 0.0 loss).
# Verdicts absent here (e.g. "user_marked") are not a rating signal -> no-op.
_VERDICT_SCORES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

USER_ENTITY_ID = "default"

# Each difficulty star above/below the median (3) shifts cold-start mu by this.
_DIFFICULTY_STEP = 150.0


@dataclass
class AttemptRating:
    """User + puzzle rating movement from one attempt (display scale)."""
    user_before: float
    user_after: float
    user_delta: float
    puzzle_before: float
    puzzle_after: float


def cold_start_mu(difficulty: int) -> float:
    """Map a puzzle's difficulty (1-5 stars) to a starting Glicko mu.

    Difficulty 3 == the default 1500; each star shifts by _DIFFICULTY_STEP so
    a 5-star puzzle starts higher-rated than a 1-star one.
    """
    return _INIT_MU + (float(difficulty) - 3.0) * _DIFFICULTY_STEP


def _load(entity_type: str, entity_id: str, default: GlickoRating) -> GlickoRating:
    row = _db.get_rating(entity_type, entity_id)
    if row is None:
        return default
    return GlickoRating(
        mu=row["mu"], phi=row["phi"], sigma=row["sigma"], matches=row["matches"]
    )


def _store(entity_type: str, entity_id: str, r: GlickoRating) -> None:
    _db.upsert_rating(
        entity_type, entity_id,
        mu=r.mu, phi=r.phi, sigma=r.sigma, matches=r.matches,
    )


def get_user_rating() -> GlickoRating:
    """The user's current rating, defaulting to a fresh 1500 if unrated."""
    return _load("user", USER_ENTITY_ID,
                 GlickoRating(_INIT_MU, _INIT_PHI, _INIT_SIG, 0))


def get_puzzle_rating(puzzle_id: int, difficulty: int) -> GlickoRating:
    """A puzzle's current rating, cold-started from difficulty if unrated."""
    return _load("puzzle", str(puzzle_id),
                 GlickoRating(cold_start_mu(difficulty), _INIT_PHI, _INIT_SIG, 0))


def apply_attempt(
    puzzle_id: int, difficulty: int, verdict: str
) -> Optional[AttemptRating]:
    """Update user + puzzle ratings for one attempt; persist write-through.

    Returns the rating movement, or None when ``verdict`` carries no rating
    signal (e.g. ``user_marked``) so the caller can skip the display update.
    """
    score = _VERDICT_SCORES.get(verdict)
    if score is None:
        return None

    user = get_user_rating()
    puzzle = get_puzzle_rating(puzzle_id, difficulty)

    # Snapshot both opponents' Glicko-2 internal coords BEFORE updating either,
    # so the update is simultaneous (not sequential).
    user_mu2, user_phi2 = _to_glicko2(user.mu, user.phi)
    puz_mu2, puz_phi2 = _to_glicko2(puzzle.mu, puzzle.phi)

    new_user = _update_rating(user, [(puz_mu2, puz_phi2, score)])
    new_puzzle = _update_rating(puzzle, [(user_mu2, user_phi2, 1.0 - score)])

    _store("user", USER_ENTITY_ID, new_user)
    _store("puzzle", str(puzzle_id), new_puzzle)

    return AttemptRating(
        user_before=user.mu,
        user_after=new_user.mu,
        user_delta=new_user.mu - user.mu,
        puzzle_before=puzzle.mu,
        puzzle_after=new_puzzle.mu,
    )
