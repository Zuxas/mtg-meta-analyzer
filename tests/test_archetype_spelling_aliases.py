"""Spelling variants of one deck read as one deck (2026-09-28 merge)."""
import pytest

from analysis.archetypes import ALIASES, normalize


@pytest.mark.parametrize("raw,canon", [
    ("Merfolks", "Merfolk"), ("Death & Taxes", "Death And Taxes"), ("Urza Tron", "Urzatron"),
    ("Mono U Delver", "Mono Blue Delver"), ("Esper Goryos", "Esper Goryo"),
    ("Weenie White", "White Weenie"), ("4C Control", "Four-Color Control"),
])
def test_spelling_variants_merge(raw, canon):
    assert normalize(raw) == canon


def test_alias_targets_are_canonical():
    for target in set(ALIASES.values()):
        assert normalize(target) == target, target


@pytest.mark.parametrize("name", ["Izzet Lesson", "Izzet Lessons", "Boros Energy", "Boros Aggro",
                                  "Mono Black Aggro", "Mono Black Midrange"])
def test_borderline_and_distinct_decks_stay_apart(name):
    assert normalize(name) == name
