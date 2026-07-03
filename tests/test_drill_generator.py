"""Puzzle-trainer v0 Track T1 gates.

- T1-G1 MATH: the hypergeometric solver matches an INDEPENDENT oracle
  (sequential product, not math.comb) and scipy when available, over 100
  random scenarios, zero mismatch.
- grade_number: the exact-number grader rejects the substring false
  positive that fuzzy keyword matching would accept, and accepts the whole
  [exact, shorthand] band the drill teaches.
- T1-G2 SEED: generated drills are well-formed, grounded (real-decklist
  attribution), span difficulty tiers, and grade 'correct' on their own
  canonical answers. Skips gracefully if the DB is unavailable.
"""
from __future__ import annotations

import random
import sqlite3

import pytest

from analysis.puzzles.drill_generator import (
    CATEGORY, generate_drills, p_at_least_one, p_none_sequential, shorthand,
)
from analysis.puzzles.graders import grade, grade_number
from analysis.puzzles.scene_builder import Scene
from db.database import get_connection


# ── T1-G1 MATH ──────────────────────────────────────────────────────────

def test_solver_matches_independent_oracle():
    """p_at_least_one (math.comb) == 1 - sequential-product oracle."""
    rng = random.Random(1234)
    for _ in range(100):
        n = rng.randint(5, 100)
        k = rng.randint(1, n)
        m = rng.randint(1, min(10, n))
        exact = p_at_least_one(n, k, m)
        oracle = 1.0 - p_none_sequential(n, k, m)
        assert abs(exact - oracle) < 1e-9, (n, k, m, exact, oracle)


def test_solver_matches_scipy():
    st = pytest.importorskip("scipy.stats")
    rng = random.Random(99)
    for _ in range(100):
        n = rng.randint(5, 100)
        k = rng.randint(1, n)
        m = rng.randint(1, min(10, n))
        # scipy: hypergeom(M=population, n=successes, N=draws); sf(0)=P(X>=1)
        scipy_val = float(st.hypergeom.sf(0, n, k, m))
        assert abs(p_at_least_one(n, k, m) - scipy_val) < 1e-9, (n, k, m)


def test_solver_edge_conventions():
    assert p_at_least_one(0, 3, 2) == 0.0
    assert p_at_least_one(53, 0, 2) == 0.0
    assert p_at_least_one(53, 4, 0) == 0.0
    assert p_at_least_one(10, 10, 3) == 1.0   # all outs
    assert p_at_least_one(10, 12, 3) == 1.0   # outs clamped to deck size


# ── grade_number ────────────────────────────────────────────────────────

def test_grade_number_rejects_substring_false_positive():
    """The whole reason this grader exists: fuzzy keyword matching would
    score '8.7' against canonical '38.7' as a hit. Exact-number must not."""
    puzzle = {"solution_keywords": ["38.7"], "grading_mode": "number"}
    assert grade_number(puzzle, "8.7")["verdict"] == "incorrect"
    assert grade_number(puzzle, "38.7")["verdict"] == "correct"
    assert grade_number(puzzle, "38.7%")["verdict"] == "correct"
    assert grade_number(puzzle, "0.387")["verdict"] == "correct"  # fraction*100


def test_grade_number_accepts_band_no_dead_zone():
    """Two canonical numbers (exact + shorthand) define a continuous band;
    nothing between them is wrongly rejected."""
    puzzle = {"solution_keywords": ["38.7", "45.0"], "grading_mode": "number"}
    for ans in ("38.7", "41", "45.0"):
        assert grade_number(puzzle, ans)["verdict"] == "correct", ans
    assert grade_number(puzzle, "70")["verdict"] == "incorrect"
    assert grade_number(puzzle, "no idea")["verdict"] == "incorrect"


def test_grade_dispatch_routes_number_mode():
    puzzle = {"solution_keywords": ["38.7", "45.0"], "grading_mode": "number"}
    res = grade(puzzle, "40")
    assert res["verdict"] == "correct"
    assert res["grader_used"] == "number"


# ── T1-G2 SEED (needs the DB) ───────────────────────────────────────────

def _connect_or_skip():
    try:
        conn = get_connection()
    except sqlite3.OperationalError as e:
        pytest.skip(f"meta DB unavailable: {e}")
    return conn


def test_generated_drills_well_formed_and_grounded():
    conn = _connect_or_skip()
    with conn:
        try:
            drills = generate_drills(conn, n=30, seed=42)
        except (sqlite3.OperationalError, RuntimeError) as e:
            pytest.skip(f"cannot sample decklists: {e}")

    assert len(drills) == 30
    for d in drills:
        assert d.category == CATEGORY
        assert d.grading_mode in {"number", "keyword"}
        assert d.solution_keywords, "every drill needs a canonical answer"
        assert "deck #" in d.notes, "house rule 8: real-decklist attribution"
        assert 1 <= d.difficulty <= 5
        # Scene round-trips through the model the Solve tab uses.
        Scene.from_dict(d.scene)
        # The drill grades its OWN canonical answer as correct.
        pd = {"solution_keywords": d.solution_keywords,
              "grading_mode": d.grading_mode}
        if d.grading_mode == "number":
            assert grade(pd, d.solution_keywords[0])["verdict"] == "correct"
        else:
            assert grade(pd, "bottom")["verdict"] == "correct"

    tiers = {d.difficulty for d in drills}
    assert len(tiers) >= 3, f"want tier spread, got {sorted(tiers)}"


def test_generation_is_deterministic():
    conn = _connect_or_skip()
    with conn:
        try:
            a = generate_drills(conn, n=12, seed=7)
            b = generate_drills(conn, n=12, seed=7)
        except (sqlite3.OperationalError, RuntimeError) as e:
            pytest.skip(f"cannot sample decklists: {e}")
    assert [d.question for d in a] == [d.question for d in b]
