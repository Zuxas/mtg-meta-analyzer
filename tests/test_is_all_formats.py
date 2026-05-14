"""Unit + regression tests for the cross-format sentinel helper."""
from analysis.win_rates import is_all_formats


def test_is_all_formats_none():
    assert is_all_formats(None) is True


def test_is_all_formats_empty_string():
    assert is_all_formats("") is True


def test_is_all_formats_whitespace():
    assert is_all_formats("   ") is True


def test_is_all_formats_all_lowercase():
    assert is_all_formats("all") is True


def test_is_all_formats_all_uppercase():
    assert is_all_formats("ALL") is True


def test_is_all_formats_all_formats_label():
    assert is_all_formats("All Formats") is True


def test_is_all_formats_any_paren_sentinel():
    assert is_all_formats("(any)") is True


def test_is_all_formats_any_bare():
    assert is_all_formats("any") is True


def test_is_all_formats_concrete_format():
    assert is_all_formats("standard") is False
    assert is_all_formats("modern") is False
    assert is_all_formats("Pioneer") is False


def test_regression_archetype_trend_all_returns_data():
    """Before the fix, fmt='all' produced WHERE format='all' which matched zero
    rows. Confirm cross-format trend now returns something."""
    from analysis.win_rates import get_archetype_trend
    rows_all = get_archetype_trend("Izzet Prowess", format_name="all", weeks=4)
    rows_std = get_archetype_trend("Izzet Prowess", format_name="standard", weeks=4)
    if rows_std:
        assert rows_all, (
            "fmt='all' should return at least as much data as fmt='standard' "
            "(since 'all' is a superset). Got 0 rows for 'all'."
        )
