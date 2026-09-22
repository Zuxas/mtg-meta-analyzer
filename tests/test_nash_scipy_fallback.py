"""The Equilibrium button failed on any install that followed requirements.txt.

analysis/equilibrium.py::nash_equilibrium says, in its own docstring:

    "Falls back to replicator dynamics if scipy fails."

and the machinery for that is right there -- a broad `except Exception:
return replicator_dynamics(...)`. But the import sat 14 lines ABOVE the try:

    from scipy.optimize import linprog      # line 220, outside the try
    ...
    try:                                    # line 234
        ...
    except Exception:
        return replicator_dynamics(...)     # never reached on ImportError

So a missing scipy escaped the function instead of falling back. And scipy is
NOT in requirements.txt, so "missing" is the state of every fresh clone.

gui/tabs/heatmap_tab.py:1421 calls
`analyze_metagame(fmt, ..., method="nash")` -- explicitly the nash path -- so
the Matchup Data tab's Equilibrium button reported an error instead of
computing. It is not a crash (the GUI wraps the call and shows
theme.friendly_error), but the feature was unavailable and the failure was
environmental rather than anything the user could act on.

The repo already had the right pattern: gui/tabs/deck_analyzer.py:861 does
`try: from scipy.stats import hypergeom / except ImportError:` with a manual
math.comb fallback. equilibrium.py simply did not follow it.

Fix = move the import inside the existing try. No new fallback logic was
needed; the intended behaviour just became reachable.
"""
import sys

import numpy as np
import pytest

from analysis.equilibrium import nash_equilibrium, replicator_dynamics

# Textbook Rock-Paper-Scissors. The exact Nash answer is 1/3 each, so both
# solvers should agree closely and the fallback stays meaningful.
ARCH = ["Rock", "Paper", "Scissors"]
RPS = np.array([[0.5, 0.0, 1.0],
                [1.0, 0.5, 0.0],
                [0.0, 1.0, 0.5]])


@pytest.fixture
def scipy_unavailable(monkeypatch):
    """Simulate a machine without scipy.

    Setting the entry to None makes `from scipy.optimize import ...` raise
    ImportError, which is what an absent package does -- and it behaves the
    same whether or not the developer running the suite has scipy installed.
    """
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.optimize", None)


def test_nash_falls_back_instead_of_raising(scipy_unavailable):
    """The headline: the documented fallback must actually happen."""
    result = nash_equilibrium(RPS, ARCH)
    assert result is not None
    assert result.archetypes == ARCH


def test_fallback_result_is_a_real_distribution(scipy_unavailable):
    """Falling back must return a usable answer, not an empty shell -- the
    Equilibrium dialog reads optimal_shares straight out of it."""
    result = nash_equilibrium(RPS, ARCH)
    shares = result.optimal_shares
    assert set(shares) == set(ARCH)
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(v >= 0 for v in shares.values())
    # RPS has a known exact equilibrium
    for a in ARCH:
        assert shares[a] == pytest.approx(1 / 3, abs=0.02), (
            f"{a} at {shares[a]:.4f}, expected ~0.3333")


def test_fallback_matches_calling_replicator_directly(scipy_unavailable):
    """Pins WHICH fallback runs, so a future edit cannot silently substitute
    something else while still returning a plausible-looking object."""
    viaNash = nash_equilibrium(RPS, ARCH).optimal_shares
    direct = replicator_dynamics(RPS, ARCH).optimal_shares
    for a in ARCH:
        assert viaNash[a] == pytest.approx(direct[a], abs=1e-6)


def test_the_equilibrium_button_path_survives(scipy_unavailable, monkeypatch):
    """End to end through analyze_metagame with method='nash', which is
    exactly what heatmap_tab.py:1421 calls."""
    import analysis.equilibrium as eq

    monkeypatch.setattr(eq, "_eq_cache", {})

    fake_matchups = {
        "Rock": {"Paper": {"win_rate": 0.0, "matches": 30},
                 "Scissors": {"win_rate": 1.0, "matches": 30}},
        "Paper": {"Scissors": {"win_rate": 0.0, "matches": 30}},
    }
    monkeypatch.setattr(
        "analysis.win_rates.get_real_matchup_winrates",
        lambda *a, **k: fake_matchups)
    monkeypatch.setattr(
        "analysis.win_rates.get_meta_standings",
        lambda *a, **k: [{"archetype": a, "appearances": 10} for a in ARCH])

    out = eq.analyze_metagame("standard", top=15, method="nash")
    assert out["equilibrium"] is not None, (
        "the Equilibrium button's exact call returned no equilibrium")


def test_the_import_is_inside_the_try():
    """Pins the mechanism in source.

    The fallback machinery already existed; only the import's placement made
    it unreachable. A refactor that hoists the import back to module scope or
    above the try would silently restore the bug, and the tests above would
    still pass on any machine that happens to have scipy installed.
    """
    import inspect

    src = inspect.getsource(nash_equilibrium)
    try_at = src.index("    try:")
    import_at = src.index("from scipy.optimize import linprog")
    assert import_at > try_at, (
        "the scipy import is outside the try block again -- an absent scipy "
        "will escape instead of falling back to replicator dynamics")
