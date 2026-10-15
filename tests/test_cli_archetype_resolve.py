"""#29: CLI partial names resolve to one archetype instead of a LIKE merge."""
import pytest

from analysis.query import resolve_archetype_name as r

KNOWN = ["Izzet Prowess", "Mono Red Prowess", "Domain Ramp", "Dimir Midrange"]


def test_exact_case_insensitive():
    assert r("izzet prowess", KNOWN) == "Izzet Prowess"


def test_unique_partial():
    assert r("domain", KNOWN) == "Domain Ramp"


def test_ambiguous_partial_exits_with_candidates():
    with pytest.raises(SystemExit, match="Izzet Prowess, Mono Red Prowess"):
        r("prowess", KNOWN)


def test_unknown_passes_through():
    assert r("Boros Energy", KNOWN) == "Boros Energy"
