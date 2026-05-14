"""Tests for db.deck_variants.variant_diff."""
from db.deck_variants import variant_diff


def _empty():
    return {"mainboard": {"added": [], "removed": []},
            "sideboard": {"added": [], "removed": []}}


def test_identical_variants_produce_no_diff():
    mb = {"Lightning Bolt": 4}
    sb = {"Pithing Needle": 2}
    d = variant_diff(mb, sb, mb, sb)
    assert d == _empty()


def test_single_card_add_to_mainboard():
    d = variant_diff({}, {}, {"Lightning Bolt": 4}, {})
    assert d["mainboard"]["added"] == [("Lightning Bolt", 4)]
    assert d["mainboard"]["removed"] == []
    assert d["sideboard"]["added"] == []
    assert d["sideboard"]["removed"] == []


def test_single_card_remove_from_mainboard():
    d = variant_diff({"Lightning Bolt": 4}, {}, {}, {})
    assert d["mainboard"]["removed"] == [("Lightning Bolt", 4)]
    assert d["mainboard"]["added"] == []


def test_swap_renders_as_paired_add_remove():
    d = variant_diff({"Dismember": 2}, {},
                     {"Lightning Helix": 2}, {})
    assert d["mainboard"]["added"] == [("Lightning Helix", 2)]
    assert d["mainboard"]["removed"] == [("Dismember", 2)]


def test_quantity_change_renders_as_paired_change():
    d = variant_diff({"Lightning Bolt": 3}, {},
                     {"Lightning Bolt": 4}, {})
    assert d["mainboard"]["removed"] == [("Lightning Bolt", 3)]
    assert d["mainboard"]["added"] == [("Lightning Bolt", 4)]


def test_sideboard_diff_independent_of_mainboard():
    d = variant_diff({"Llanowar Elves": 4}, {"Rest in Peace": 2},
                     {"Llanowar Elves": 4}, {"Pithing Needle": 2})
    assert d["mainboard"] == {"added": [], "removed": []}
    assert d["sideboard"]["added"] == [("Pithing Needle", 2)]
    assert d["sideboard"]["removed"] == [("Rest in Peace", 2)]


def test_diff_lists_are_sorted_for_stable_rendering():
    d = variant_diff({}, {},
                     {"Zealous Conscripts": 1, "Aether Vial": 4, "Mana Leak": 2}, {})
    names = [n for n, _ in d["mainboard"]["added"]]
    assert names == sorted(names)
