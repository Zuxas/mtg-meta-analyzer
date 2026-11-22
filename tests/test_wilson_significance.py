"""Tests for analysis.wilson — Wilson score interval + tweak classification."""
import pytest

from analysis.wilson import wilson_bounds, classify_tweak


def test_wilson_bounds_n_zero_returns_zero_to_one():
    lo, hi = wilson_bounds(wins=0, total=0)
    assert lo == 0.0
    assert hi == 1.0


def test_wilson_bounds_perfect_record_has_high_lower():
    lo, hi = wilson_bounds(wins=10, total=10)
    assert lo > 0.65  # known: Wilson lower for 10/10 at 95% is ~0.722
    assert hi == pytest.approx(1.0, abs=0.01)


def test_wilson_bounds_no_wins_has_low_upper():
    lo, hi = wilson_bounds(wins=0, total=10)
    assert lo == pytest.approx(0.0, abs=0.01)
    assert hi < 0.35  # known: Wilson upper for 0/10 at 95% is ~0.278


def test_wilson_bounds_50_percent_is_centered_for_large_n():
    lo, hi = wilson_bounds(wins=50, total=100)
    assert 0.40 < lo < 0.50
    assert 0.50 < hi < 0.60


def test_classify_tweak_validated_when_bands_dont_overlap():
    # 0/10 vs 10/10 — clearly non-overlapping
    result = classify_tweak(prev_wins=0, prev_total=10,
                            curr_wins=10, curr_total=10)
    assert result == "validated"


def test_classify_tweak_promising_when_delta_large_but_bands_overlap():
    # 1/3 (33%) vs 4/5 (80%) — delta is +47pp, but small N => bands wide
    result = classify_tweak(prev_wins=1, prev_total=3,
                            curr_wins=4, curr_total=5)
    assert result == "promising"


def test_classify_tweak_noisy_when_delta_small():
    # 5/10 vs 14/30 (46.7%) — 3.3pp, bands overlap heavily
    assert classify_tweak(5, 10, 14, 30) == "noisy"


def test_classify_tweak_exact_10pp_boundary_is_promising():
    # #33: 0.7 - 0.6 == 0.0999... in floats, which read as below 10pp
    assert classify_tweak(5, 10, 6, 10) == "promising"
    assert classify_tweak(6, 10, 7, 10) == "promising"
    assert classify_tweak(6, 10, 5, 10) == "promising"     # symmetric
    assert classify_tweak(50, 100, 59, 100) == "noisy"     # 9pp, just under


def test_classify_tweak_overlapping_bands_never_validated():
    # #33: 4/10 -> 6/10 has bands [0.17, 0.69] / [0.31, 0.83]; N>=10 used to call it validated
    assert classify_tweak(4, 10, 6, 10) == "promising"
