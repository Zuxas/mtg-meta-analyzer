"""MCP server package for the MTG Meta Analyzer.

Exposes the analyzer's read-only metagame analytics as agent-callable tools.
`tools` holds the pure, testable logic; `server` registers them on a FastMCP
instance for stdio transport.
"""
