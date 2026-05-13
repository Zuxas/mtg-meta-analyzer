"""Tests for gui.widgets.palette_registry.

The registry is pure Python — no Qt. It owns: entry storage, prefix parsing,
fuzzy search, context predicates, and stale-recent pruning.
"""
import pytest

from gui.widgets.palette_registry import (
    PaletteEntry,
    PaletteRegistry,
    parse_prefix,
)


def _entry(id_, category, name, secondary="", context_predicate=None):
    """Factory for PaletteEntry with a no-op handler; intent is to make
    test setup terse without hiding any of the inspectable fields."""
    return PaletteEntry(
        id=id_, category=category, name=name,
        secondary=secondary, handler=lambda: None,
        context_predicate=context_predicate,
    )


def test_parse_prefix_no_prefix():
    assert parse_prefix("izzet") == (None, "izzet")


def test_parse_prefix_actions():
    assert parse_prefix(">refresh") == ("ACT", "refresh")


def test_parse_prefix_tabs():
    assert parse_prefix("#dashboard") == ("TAB", "dashboard")


def test_parse_prefix_archetypes():
    assert parse_prefix("@izzet") == ("ARCH", "izzet")


def test_parse_prefix_decks():
    assert parse_prefix(":tokyo") == ("DECK", "tokyo")


def test_parse_prefix_cards():
    assert parse_prefix("c:sheoldred") == ("CARD", "sheoldred")


@pytest.mark.parametrize("query,expected", [
    (">",  ("ACT",  "")),
    ("#",  ("TAB",  "")),
    ("@",  ("ARCH", "")),
    (":",  ("DECK", "")),
    ("c:", ("CARD", "")),
])
def test_parse_prefix_bare_prefix_returns_empty_query(query, expected):
    assert parse_prefix(query) == expected


def test_register_and_get():
    reg = PaletteRegistry()
    e = _entry("tab:dashboard", "TAB", "Dashboard")
    reg.register(e)
    assert reg.get("tab:dashboard") is e


def test_register_replaces_existing_id():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard", "old"))
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard", "new"))
    assert reg.get("tab:dashboard").secondary == "new"
    assert len(reg.search("dashboard")) == 1  # not duplicated


def test_unregister_removes_entry():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.unregister("tab:dashboard")
    assert reg.get("tab:dashboard") is None
    assert reg.search("dashboard") == []


def test_search_fuzzy_match():
    reg = PaletteRegistry()
    reg.register(_entry("arch:izzet-prowess", "ARCH", "Izzet Prowess"))
    reg.register(_entry("arch:mono-green", "ARCH", "Mono-Green Landfall"))
    results = reg.search("izet")  # typo
    assert results[0].id == "arch:izzet-prowess"


def test_search_prefix_filters_category():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("arch:dashboard-archetype", "ARCH", "Dashboard Archetype"))
    results = reg.search("#dashboard")
    assert all(r.category == "TAB" for r in results)
    assert results[0].id == "tab:dashboard"


def test_search_cards_always_gated_behind_c_prefix():
    """Cards are gated by c: prefix regardless of query length.
    A buggy implementation that gates only short queries could pass
    the old test, so we verify both short and long no-prefix queries."""
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("card:sheoldred", "CARD", "Sheoldred, the Apocalypse"))
    # Without prefix, short query "s" must NOT surface CARD entries
    results = reg.search("s")
    assert not any(r.category == "CARD" for r in results)
    # Without prefix, long query "sheoldred" ALSO must not surface CARD entries
    # (cards are gated by prefix, not by query length — spec v2)
    results = reg.search("sheoldred")
    assert not any(r.category == "CARD" for r in results)
    # With c: prefix, card surfaces
    results = reg.search("c:sheo")
    assert results[0].category == "CARD"


def test_search_empty_query_returns_priority_sorted_non_cards():
    """Empty query: returns up to `limit` entries sorted by category
    priority (TAB=0, ACT=1, ARCH=2, DECK=3), with CARDs excluded
    (cards only surface via c: prefix)."""
    reg = PaletteRegistry()
    reg.register(_entry("card:sheoldred", "CARD", "Sheoldred"))
    reg.register(_entry("deck:42", "DECK", "My Deck"))
    reg.register(_entry("arch:izzet", "ARCH", "Izzet Prowess"))
    reg.register(_entry("act:refresh", "ACT", "Refresh"))
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    results = reg.search("", limit=8)
    # CARD entries excluded
    assert not any(r.category == "CARD" for r in results)
    # Sorted by category priority: TAB first, then ACT, then ARCH, then DECK
    categories = [r.category for r in results]
    assert categories == ["TAB", "ACT", "ARCH", "DECK"]


def test_search_context_predicate_filters_entry():
    reg = PaletteRegistry()
    available = {"value": False}
    reg.register(_entry(
        "act:print-sb", "ACT", "Print SB Guide",
        context_predicate=lambda: available["value"],
    ))
    assert reg.search("print") == []
    available["value"] = True
    assert len(reg.search("print")) == 1


def test_prune_recents_drops_unknown_ids():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("tab:meta", "TAB", "Meta"))
    pruned = reg.prune_recents([
        "tab:dashboard",
        "arch:deleted-archetype",
        "tab:meta",
        "tab:nonexistent",
    ])
    # Order from input list is preserved; only known IDs survive
    assert pruned == ["tab:dashboard", "tab:meta"]
