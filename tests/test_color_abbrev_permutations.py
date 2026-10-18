"""#30: every letter order of a 2- or 3-colour abbreviation names the same
guild / shard / wedge, so one deck doesn't split across sources."""
from itertools import permutations

import pytest

from analysis.archetypes import normalize, pre_normalize

NAMES = {
    "wu": "Azorius", "ub": "Dimir", "br": "Rakdos", "rg": "Gruul",
    "gw": "Selesnya", "wb": "Orzhov", "ur": "Izzet", "bg": "Golgari",
    "rw": "Boros", "gu": "Simic",
    "wub": "Esper", "ubr": "Grixis", "brg": "Jund", "rgw": "Naya",
    "gwu": "Bant", "wbg": "Abzan", "urw": "Jeskai", "bgu": "Sultai",
    "rwb": "Mardu", "gur": "Temur",
}
CASES = [("".join(p), name) for colors, name in NAMES.items()
         for p in permutations(colors)]


@pytest.mark.parametrize("abbrev,name", CASES)
def test_every_letter_order(abbrev, name):
    assert pre_normalize(f"{abbrev.upper()} Testdeck") == f"{name} Testdeck"
    assert pre_normalize(f"Testdeck {abbrev}") == f"Testdeck {name}"


def test_issue_examples():
    assert normalize("WUB Control") == "Esper Control"
    assert normalize("BRG Midrange") == "Jund Midrange"
    assert normalize("WBG Midrange") == "Abzan Midrange"
    assert normalize("GUR Energy") == "Temur Energy"
    assert normalize("URW Control") == "Jeskai Control"
    assert normalize("BWR Midrange") == "Mardu Midrange"


@pytest.mark.parametrize("raw", ["UUR Tempo", "Madness Bur...", "Madness Bur…",
                                 "Elves", "Affinity"])
def test_non_colour_tokens_untouched(raw):
    assert pre_normalize(raw) == raw.title()
