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


def test_search_cards_gated_behind_prefix_for_short_queries():
    reg = PaletteRegistry()
    reg.register(_entry("tab:dashboard", "TAB", "Dashboard"))
    reg.register(_entry("card:sheoldred", "CARD", "Sheoldred, the Apocalypse"))
    # Without prefix, query "s" should NOT surface the card
    results = reg.search("s")
    assert not any(r.category == "CARD" for r in results)
    # With c: prefix, card surfaces
    results = reg.search("c:sheo")
    assert results[0].category == "CARD"


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
    pruned = reg.prune_recents([
        "tab:dashboard",
        "arch:deleted-archetype",
        "tab:nonexistent",
    ])
    assert pruned == ["tab:dashboard"]
