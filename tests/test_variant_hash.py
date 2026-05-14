"""Tests for db.deck_variants.compute_variant_hash.

Pure-Python; no DB, no Qt.
"""
from db.deck_variants import compute_variant_hash


def test_hash_is_16_hex_chars():
    h = compute_variant_hash({"Llanowar Elves": 4}, {})
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_deterministic():
    mb = {"Llanowar Elves": 4, "Forest": 20}
    sb = {"Rest in Peace": 2}
    assert compute_variant_hash(mb, sb) == compute_variant_hash(mb, sb)


def test_hash_is_order_invariant_in_mainboard():
    a = compute_variant_hash({"Forest": 20, "Llanowar Elves": 4}, {})
    b = compute_variant_hash({"Llanowar Elves": 4, "Forest": 20}, {})
    assert a == b


def test_hash_is_order_invariant_in_sideboard():
    mb = {"Forest": 20}
    a = compute_variant_hash(mb, {"Rest in Peace": 2, "Pithing Needle": 1})
    b = compute_variant_hash(mb, {"Pithing Needle": 1, "Rest in Peace": 2})
    assert a == b


def test_hash_changes_on_mainboard_swap():
    mb1 = {"Llanowar Elves": 4, "Forest": 20}
    mb2 = {"Elvish Mystic": 4, "Forest": 20}
    assert compute_variant_hash(mb1, {}) != compute_variant_hash(mb2, {})


def test_hash_changes_on_sideboard_swap():
    mb = {"Forest": 20}
    assert (compute_variant_hash(mb, {"Rest in Peace": 2})
            != compute_variant_hash(mb, {"Pithing Needle": 2}))


def test_hash_changes_on_quantity_change():
    assert (compute_variant_hash({"Lightning Bolt": 3}, {})
            != compute_variant_hash({"Lightning Bolt": 4}, {}))


def test_empty_boards_produce_stable_hash():
    h = compute_variant_hash({}, {})
    assert len(h) == 16
