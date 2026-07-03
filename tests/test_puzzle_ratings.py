"""Tests for the T3 puzzle-rating loop (Glicko-2).

Two layers:
  * db/puzzles.py rating store  -- get_rating / upsert_rating round-trip.
  * analysis/puzzles/rating_loop.py -- cold-start, two-sided apply_attempt,
    the T3-G1 (wiring == analysis.ratings._update_rating) and T3-G2
    (survives restart) gates.
"""
import sqlite3

import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Patch db.database to a temp SQLite file so tests don't touch prod."""
    db_path = tmp_path / "test_mtg_meta.db"
    monkeypatch.setattr("db.database.DB_PATH", str(db_path))
    monkeypatch.setattr("db.database.ARCHIVE_PATH", str(tmp_path / "archive.db"))
    yield db_path


# ── DB store ───────────────────────────────────────────────────────────────

def test_ensure_tables_creates_puzzle_ratings(tmp_db):
    from db import puzzles
    puzzles._ensure_tables()
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='puzzle_ratings'"
        ).fetchone()
    assert row is not None


def test_get_rating_absent_returns_none(tmp_db):
    from db import puzzles
    assert puzzles.get_rating("user", "default") is None


def test_upsert_and_get_rating_round_trip(tmp_db):
    from db import puzzles
    puzzles.upsert_rating("user", "default",
                          mu=1523.75, phi=310.5, sigma=0.0601, matches=3)
    got = puzzles.get_rating("user", "default")
    assert got["mu"] == 1523.75   # REAL is IEEE-754 double -> bit-exact
    assert got["phi"] == 310.5
    assert got["sigma"] == 0.0601
    assert got["matches"] == 3


def test_upsert_replaces_existing_row(tmp_db):
    from db import puzzles
    puzzles.upsert_rating("puzzle", "49",
                          mu=1500.0, phi=350.0, sigma=0.06, matches=0)
    puzzles.upsert_rating("puzzle", "49",
                          mu=1488.2, phi=300.1, sigma=0.0599, matches=1)
    got = puzzles.get_rating("puzzle", "49")
    assert got["mu"] == 1488.2
    assert got["matches"] == 1
    # exactly one row -- upsert, not append
    with sqlite3.connect(tmp_db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM puzzle_ratings WHERE entity_id='49'"
        ).fetchone()[0]
    assert n == 1


# ── rating_loop: cold-start ─────────────────────────────────────────────────

def test_cold_start_mu_is_monotonic_in_difficulty():
    from analysis.puzzles import rating_loop as rl
    mus = [rl.cold_start_mu(d) for d in range(1, 6)]
    assert mus == sorted(mus)          # harder puzzle -> higher rating
    assert mus[2] == 1500.0            # difficulty 3 == default mu


# ── rating_loop: tracer bullet (score direction) ────────────────────────────

def test_correct_attempt_raises_user_lowers_puzzle(tmp_db):
    """A brand-new user solving a puzzle: user mu up, puzzle mu down."""
    from analysis.puzzles import rating_loop as rl
    res = rl.apply_attempt(puzzle_id=49, difficulty=3, verdict="correct")
    assert res is not None
    assert res.user_after > res.user_before      # solver gains
    assert res.user_delta > 0
    assert res.puzzle_after < res.puzzle_before   # puzzle loses


def test_incorrect_attempt_lowers_user_raises_puzzle(tmp_db):
    from analysis.puzzles import rating_loop as rl
    res = rl.apply_attempt(puzzle_id=49, difficulty=3, verdict="incorrect")
    assert res.user_after < res.user_before
    assert res.puzzle_after > res.puzzle_before


def test_non_scoring_verdict_is_a_noop(tmp_db):
    from analysis.puzzles import rating_loop as rl
    from db import puzzles
    assert rl.apply_attempt(puzzle_id=49, difficulty=3,
                            verdict="user_marked") is None
    # nothing persisted
    assert puzzles.get_rating("user", "default") is None
    assert puzzles.get_rating("puzzle", "49") is None


# ── T3-G1: wiring == analysis.ratings._update_rating ────────────────────────

def test_g1_user_update_matches_update_rating_reference(tmp_db):
    """T3-G1 MATH: apply_attempt's user rating equals a hand-built single-game
    _update_rating call. Inputs (cold-start coords, score) are written
    literally here so the test pins scale conversion + score DIRECTION +
    opponent identity, not just determinism."""
    from analysis.puzzles import rating_loop as rl
    from analysis.ratings import (
        GlickoRating, _INIT_MU, _INIT_PHI, _INIT_SIG, _to_glicko2, _update_rating,
    )
    from db import puzzles

    # Fresh user vs a fresh difficulty-4 puzzle (cold-start mu 1650), solved.
    fresh_user = GlickoRating(_INIT_MU, _INIT_PHI, _INIT_SIG, 0)
    puzzle_mu = 1650.0  # == cold_start_mu(4), asserted literally
    assert rl.cold_start_mu(4) == puzzle_mu
    opp_mu2, opp_phi2 = _to_glicko2(puzzle_mu, _INIT_PHI)
    expected_user = _update_rating(fresh_user, [(opp_mu2, opp_phi2, 1.0)])

    rl.apply_attempt(puzzle_id=7, difficulty=4, verdict="correct")

    stored = puzzles.get_rating("user", "default")
    assert stored["mu"] == pytest.approx(expected_user.mu, abs=1e-9)
    assert stored["phi"] == pytest.approx(expected_user.phi, abs=1e-9)
    assert stored["sigma"] == pytest.approx(expected_user.sigma, abs=1e-9)
    assert stored["matches"] == expected_user.matches == 1


def test_g1_puzzle_update_matches_update_rating_reference(tmp_db):
    """T3-G1: the puzzle side takes score = 1 - user_score with the user's
    pre-update coords as its opponent."""
    from analysis.puzzles import rating_loop as rl
    from analysis.ratings import (
        GlickoRating, _INIT_MU, _INIT_PHI, _INIT_SIG, _to_glicko2, _update_rating,
    )
    from db import puzzles

    fresh_puzzle = GlickoRating(1650.0, _INIT_PHI, _INIT_SIG, 0)
    opp_mu2, opp_phi2 = _to_glicko2(_INIT_MU, _INIT_PHI)  # user's coords
    expected_puzzle = _update_rating(fresh_puzzle, [(opp_mu2, opp_phi2, 0.0)])

    rl.apply_attempt(puzzle_id=7, difficulty=4, verdict="correct")

    stored = puzzles.get_rating("puzzle", "7")
    assert stored["mu"] == pytest.approx(expected_puzzle.mu, abs=1e-9)
    assert stored["phi"] == pytest.approx(expected_puzzle.phi, abs=1e-9)
    assert stored["sigma"] == pytest.approx(expected_puzzle.sigma, abs=1e-9)


# ── T3-G2: ratings survive restart ──────────────────────────────────────────

def test_g2_ratings_survive_restart(tmp_db):
    """T3-G2 PERSISTENCE: after an attempt, a fresh read (simulating an app
    relaunch) returns identical values, and the next attempt builds on the
    persisted rating rather than the default."""
    from analysis.puzzles import rating_loop as rl
    from db import puzzles

    first = rl.apply_attempt(puzzle_id=7, difficulty=4, verdict="correct")

    # Simulate restart: re-read straight from the store.
    stored = puzzles.get_rating("user", "default")
    assert stored["mu"] == first.user_after       # bit-exact round-trip

    # A subsequent attempt starts from the persisted rating, not 1500.
    loaded = rl.get_user_rating()
    assert loaded.mu == first.user_after
    assert loaded.matches == 1

    second = rl.apply_attempt(puzzle_id=7, difficulty=4, verdict="correct")
    assert second.user_before == first.user_after  # continuity across "restart"

# NOTE: the end-to-end Solve-tab GUI smoke lives in tests/test_puzzles_tab.py
# (test_solve_tab_records_rating_and_displays_it) -- co-located with the other
# Qt tests so this file stays pure-Python and free of the offscreen-Qt
# process-teardown crash on Windows.
