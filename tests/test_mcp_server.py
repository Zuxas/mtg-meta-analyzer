"""Tests for the MCP server tool layer (mcp_server/tools.py).

These run against the live read-only mtg_meta.db (same pattern as the
analysis tests). They assert structure, ordering, provenance labelling, and
error behaviour -- NOT specific win-rate values, which shift as data updates.
"""
from __future__ import annotations

import pytest

from mcp_server import tools


# A real archetype discovered from the data, so tests don't hardcode a name
# that might age out of the metagame.
@pytest.fixture(scope="module")
def real_deck():
    result = tools.list_decks(format_name="standard", limit=10)
    assert result["decks"], "no standard decks in DB -- can't run MCP tool tests"
    return result["decks"][0]["deck"]


# ── list_decks ────────────────────────────────────────────────────────

def test_list_decks_returns_ranked_decks_with_meta_share():
    out = tools.list_decks(format_name="standard", limit=15)
    assert out["format"] == "standard"
    assert out["deck_count"] == len(out["decks"]) <= 15
    first = out["decks"][0]
    for key in ("deck", "appearances", "meta_share", "win_rate", "win_rate_source"):
        assert key in first, f"missing {key} in deck entry"
    # meta_share is a share in [0,1]; appearances descending
    assert 0.0 <= first["meta_share"] <= 1.0
    apps = [d["appearances"] for d in out["decks"]]
    assert apps == sorted(apps, reverse=True)
    # provenance is always one of the two labelled sources
    assert first["win_rate_source"] in ("real_matches", "placement_estimate")


# ── _resolve_deck / error behaviour ───────────────────────────────────

def test_resolve_deck_exact_and_case_insensitive(real_deck):
    assert tools._resolve_deck(real_deck, "standard") == real_deck
    assert tools._resolve_deck(real_deck.lower(), "standard") == real_deck


def test_resolve_deck_unknown_raises_with_suggestions():
    with pytest.raises(tools.DeckNotFoundError) as exc:
        tools._resolve_deck("Zzzz Totally Nonexistent Brew", "standard")
    err = exc.value
    assert err.deck == "Zzzz Totally Nonexistent Brew"
    assert isinstance(err.suggestions, list)
    # the message must name real alternatives so an agent can self-correct
    assert "available" in str(err).lower() or "did you mean" in str(err).lower()


def test_get_matchup_unknown_deck_raises():
    with pytest.raises(tools.DeckNotFoundError):
        tools.get_matchup("Definitely Not A Real Deck 9000", "Izzet Prowess",
                          format_name="standard")


# ── get_matchup (provenance is the key contract) ──────────────────────

def test_get_matchup_always_labels_a_source(real_deck):
    out = tools.list_decks(format_name="standard", limit=6)
    a = out["decks"][0]["deck"]
    b = out["decks"][1]["deck"]
    mu = tools.get_matchup(a, b, format_name="standard")
    assert mu["deck"] == a and mu["opponent"] == b
    assert mu["source"] in ("real_matches", "placement_proxy", "none")
    if mu["source"] != "none":
        assert 0.0 <= mu["win_rate"] <= 1.0
        assert mu["note"], "data-quality note must be preserved, not stripped"


# ── get_field_position ────────────────────────────────────────────────

def test_get_field_position_has_rank_and_best_worst(real_deck):
    fp = tools.get_field_position(real_deck, format_name="standard")
    assert fp["deck"] == real_deck
    assert "meta_rank" in fp
    assert isinstance(fp["best_matchups"], list)
    assert isinstance(fp["worst_matchups"], list)
    # best are >= worst by win_rate when both populated
    if fp["best_matchups"] and fp["worst_matchups"]:
        assert fp["best_matchups"][0]["win_rate"] >= fp["worst_matchups"][0]["win_rate"]
    assert fp["note"]


def test_get_field_position_prefers_real_matchups_when_available():
    # The Modern #1 deck has thousands of recorded matches, so best/worst
    # should come from real match data (with sample sizes), not 1-event
    # placement-proxy noise.
    top = tools.list_decks(format_name="modern", limit=1)["decks"][0]["deck"]
    fp = tools.get_field_position(top, format_name="modern")
    assert fp["matchup_source"] == "real_matches"
    assert fp["best_matchups"], "expected real best matchups"
    for m in fp["best_matchups"] + fp["worst_matchups"]:
        assert m["sample_size"] >= 20, "real matchups must clear the sample floor"
    assert fp["best_matchups"][0]["win_rate"] >= fp["worst_matchups"][0]["win_rate"]


# ── search_matchups ───────────────────────────────────────────────────

def test_search_matchups_respects_winrate_band():
    out = tools.search_matchups(min_win_rate=0.6, max_win_rate=1.0,
                                format_name="standard", limit=50)
    assert out["source"] == "placement_proxy"
    for m in out["matchups"]:
        assert 0.6 <= m["win_rate"] <= 1.0
        assert {"deck", "opponent", "win_rate", "shared_events"} <= set(m)


def test_search_matchups_empty_band_is_clean():
    # An impossible band returns an empty list, not an error.
    out = tools.search_matchups(min_win_rate=0.99, max_win_rate=1.0,
                                format_name="standard", limit=50)
    assert isinstance(out["matchups"], list)


def test_search_strategy_docs_registered():
    import asyncio
    from mcp_server import server
    registered = asyncio.run(server.mcp.list_tools())
    assert any(t.name == "search_strategy_docs" for t in registered)


def test_search_strategy_docs_index_unavailable(monkeypatch):
    from mcp_server import server
    from mcp_server.pinecone_index import IndexUnavailable

    def boom():
        raise IndexUnavailable("no key")

    monkeypatch.setattr(server, "get_index", boom)
    out = server.search_strategy_docs("anything")
    assert out["error"] == "index_unavailable"
    assert "hint" in out
