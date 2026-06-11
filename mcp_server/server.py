"""FastMCP server exposing the MTG Meta Analyzer's metagame analytics.

Runs locally over stdio for Claude Desktop / Claude Code. All tools are
read-only -- they query the analyzer's database and never modify it.

Run directly:
    python -m mcp_server.server

Register with Claude Code (from the project root):
    claude mcp add mtg-meta -- python -m mcp_server.server

Inspect interactively:
    mcp dev mcp_server/server.py
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server import tools
from mcp_server.tools import DeckNotFoundError

mcp = FastMCP("mtg-meta-analyzer")

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False,
              "idempotentHint": True, "openWorldHint": False}


def _deck_error(e: DeckNotFoundError) -> dict:
    """Turn an unresolved-deck error into structured, agent-actionable data."""
    return {
        "error": "deck_not_found",
        "message": str(e),
        "deck": e.deck,
        "format": e.format_name,
        "suggestions": e.suggestions,
        "appears_in_formats": e.other_formats,
    }


@mcp.tool(annotations=_READ_ONLY)
def list_decks(format: str = tools.DEFAULT_FORMAT, limit: int = 20) -> dict:
    """List the most-played decks (archetypes) in a Magic format, ranked.

    Call this FIRST to discover valid deck names before using the other
    tools, and to get a metagame overview. Each deck includes its meta share
    and a win rate labelled by source: 'real_matches' (recorded melee.gg
    results) or 'placement_estimate' (inferred from tournament finish, not an
    actual W/L record).

    Args:
        format: Magic format, e.g. 'standard' (default), 'modern', 'pioneer',
            'legacy', 'pauper'.
        limit: How many top decks to return (default 20).
    """
    return tools.list_decks(format_name=format, limit=limit)


@mcp.tool(annotations=_READ_ONLY)
def get_matchup(deck: str, opponent: str,
                format: str = tools.DEFAULT_FORMAT) -> dict:
    """How one deck performs against another in a given format.

    Prefers REAL recorded match results (melee.gg) when available, otherwise
    falls back to a placement-based proxy (best finish when both decks were in
    the same event). The returned `source` field says which -- a placement
    proxy is NOT a true head-to-head win rate. If a deck name can't be
    resolved, returns a 'deck_not_found' object with suggestions.

    Args:
        deck: The deck whose win rate you want (e.g. 'Boros Energy').
        opponent: The opposing deck.
        format: Magic format (default 'standard'). Tip: 'Boros Energy' is a
            Modern deck -- pass format='modern'.
    """
    try:
        return tools.get_matchup(deck, opponent, format_name=format)
    except DeckNotFoundError as e:
        return _deck_error(e)


@mcp.tool(annotations=_READ_ONLY)
def get_field_position(deck: str, format: str = tools.DEFAULT_FORMAT) -> dict:
    """Where a deck sits in the metagame: meta rank plus best/worst matchups.

    Returns the deck's performance rank in the field, its best and worst
    matchups (placement-proxy), and -- when available -- its real recorded
    overall win rate. If the deck name can't be resolved, returns a
    'deck_not_found' object with suggestions.

    Args:
        deck: The deck to analyse.
        format: Magic format (default 'standard').
    """
    try:
        return tools.get_field_position(deck, format_name=format)
    except DeckNotFoundError as e:
        return _deck_error(e)


@mcp.tool(annotations=_READ_ONLY)
def search_matchups(min_win_rate: float = 0.0, max_win_rate: float = 1.0,
                    format: str = tools.DEFAULT_FORMAT, limit: int = 50) -> dict:
    """Find matchups whose win rate falls within a band (e.g. lopsided ones).

    Built from the placement-based matchup matrix of the top archetypes, so
    `source` is 'placement_proxy'. Results are sorted high to low.

    Args:
        min_win_rate: Lower bound, 0..1 (default 0.0).
        max_win_rate: Upper bound, 0..1 (default 1.0).
        format: Magic format (default 'standard').
        limit: Max pairings to return (default 50).
    """
    return tools.search_matchups(min_win_rate, max_win_rate,
                                 format_name=format, limit=limit)


if __name__ == "__main__":
    mcp.run()
