"""Tests for per-archetype mulligan rules in gui.tabs.my_decks.

Pure unit tests -- no Qt instance needed (the helpers are module-level).
Guards the bug these rules fixed: the hardcoded Izzet Prowess mulligan
block used to render on EVERY deck's printed SB guide.
"""
from gui.tabs.my_decks import (
    _GENERIC_MULL_RULES,
    _ESPER_BLINK_MULL_RULES,
    _IZZET_PROWESS_MULL_RULES,
    _generate_sb_print_html,
    _mull_rules_for,
)

# Distinctive substrings unique to each rules block.
PROWESS_MARK = "Stormchaser's Talent"
ESPER_MARK = "Phelia"
GENERIC_MARK = "keep 2-5 lands"


# --- _mull_rules_for dispatch ----------------------------------------------

def test_none_and_empty_fall_back_to_generic():
    assert _mull_rules_for(None) == _GENERIC_MULL_RULES
    assert _mull_rules_for("") == _GENERIC_MULL_RULES


def test_exact_archetype_match():
    assert _mull_rules_for("Izzet Prowess") == _IZZET_PROWESS_MULL_RULES
    assert _mull_rules_for("Esper Blink") == _ESPER_BLINK_MULL_RULES


def test_match_is_case_insensitive_and_whitespace_tolerant():
    assert _mull_rules_for("IZZET PROWESS") == _IZZET_PROWESS_MULL_RULES
    assert _mull_rules_for("  esper blink  ") == _ESPER_BLINK_MULL_RULES


def test_substring_match_on_decorated_archetype_name():
    # Real deck archetypes carry qualifiers; the key must still match.
    assert _mull_rules_for("Izzet Prowess (Tokyo)") == _IZZET_PROWESS_MULL_RULES


def test_esper_flicker_alias_maps_to_blink_rules():
    assert _mull_rules_for("Esper Flicker") == _ESPER_BLINK_MULL_RULES


def test_unknown_archetype_gets_generic_not_prowess():
    # The regression guard: an unrelated deck must NOT inherit Prowess rules.
    rules = _mull_rules_for("Boros Energy")
    assert rules == _GENERIC_MULL_RULES
    assert PROWESS_MARK not in rules


# --- print-HTML integration (the actual leak site) -------------------------

def _deck(archetype):
    return {"name": "Test Deck", "format": "standard", "archetype": archetype}


def test_print_html_uses_archetype_rules_not_hardcoded_prowess():
    boros = _generate_sb_print_html(_deck("Boros Energy"), [])
    assert GENERIC_MARK in boros
    assert PROWESS_MARK not in boros  # <-- the bug that was leaking

    prowess = _generate_sb_print_html(_deck("Izzet Prowess"), [])
    assert PROWESS_MARK in prowess

    esper = _generate_sb_print_html(_deck("Esper Blink"), [])
    assert ESPER_MARK in esper
