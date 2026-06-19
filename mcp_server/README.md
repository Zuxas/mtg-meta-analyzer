# MTG Meta Analyzer — MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
the analyzer's metagame analytics as **agent-callable tools**. Point Claude
Desktop or Claude Code at it and ask natural-language questions like *"What's
Boros Energy's worst matchup in Modern, and what does the win-rate data say?"* —
Claude calls these tools to answer.

All tools are **read-only**. The server wraps the project's existing, tested
analysis layer (`analysis/win_rates.py`) rather than re-querying raw SQL.

## Tools

| Tool | Purpose |
|---|---|
| `list_decks(format, limit)` | Discovery: ranked decks in a format with meta share + win rate. **Call first** to learn valid deck names. |
| `get_matchup(deck, opponent, format)` | One pairing's win rate. |
| `get_field_position(deck, format)` | A deck's meta rank + best/worst matchups + overall win rate. |
| `search_matchups(min_win_rate, max_win_rate, format)` | Pairings whose win rate falls in a band (e.g. lopsided matchups). |
| `search_strategy_docs(query, top_k, archetype, doc_type)` | Semantic search over the strategy-doc corpus (primers, card audits, oracle/rules refs). Backed by Pinecone. |

## Design decisions (the part that matters)

These are the choices that make the server *correct* and *easy for an agent to
use correctly* — the things an MCP is actually judged on:

1. **Explicit provenance on every win rate.** The data has two very different
   signals: *real recorded match results* (melee.gg round data) and a
   *placement-based proxy* (best finish when two decks shared an event). They
   are not the same thing, and conflating them gives subtly wrong answers.
   Every result carries a `source` field (`real_matches` / `placement_proxy` /
   `placement_estimate`), prefers real data when available, and preserves the
   analysis layer's data-quality notes instead of stripping them.

2. **Self-correcting deck-name resolution.** Agents can't call what they can't
   name. An unknown deck doesn't return an empty result or a stack trace — it
   returns a structured `deck_not_found` object with fuzzy suggestions and the
   formats the deck *does* appear in (e.g. *"Borós Enrgy → did you mean Boros
   Energy?"*). Resolution reuses the app's own normalization layer
   (`analysis/archetypes.normalize`, 250+ aliases + fuzzy), so the server
   speaks the same names as the app.

3. **Read-only, typed, annotated.** Every tool sets `readOnlyHint=True`; there
   are no destructive tools. Tool descriptions read like docs because agents
   pick tools off the description.

4. **Discovery-first.** `list_decks` exists so an agent can orient before
   asking targeted questions — a server without a discovery tool is a tell that
   the agent's point of view wasn't considered.

## Strategy-doc semantic search (Pinecone)

`search_strategy_docs` is the one tool that doesn't query the meta DB — it does
semantic search over the curated strategy corpus in `../mtg-sim/docs/`
(archetype audits, oracle text, rules references) using **Pinecone integrated
inference** (Pinecone hosts the embedding model; we upsert raw text and query
with raw text — no separate embedding key).

Setup (one-time):

```bash
pip install pinecone                      # >=5, integrated inference
# add your free Pinecone key to config.ini (gitignored):
#   [pinecone]
#   api_key = pc-...
python scripts/ingest_strategy_docs.py    # chunk + upsert the corpus (re-run anytime; idempotent)
```

It **degrades gracefully**: with no key or before the first ingest, the tool
returns a structured `{"error": "index_unavailable", "hint": ...}` and the
other four tools keep working. Every result carries `source: "strategy_docs"`
plus its `source_file` + `heading`, consistent with the provenance philosophy
below. `archetype` / `doc_type` are Pinecone metadata filters.

## Run it

```bash
pip install -r requirements.txt          # installs mcp>=1.27
python -m mcp_server.server               # stdio server (blocks, waiting for a client)
```

## Register with Claude Code

From the project root (already done if `.mcp.json` exists):

```bash
claude mcp add mtg-meta --scope project -- python -m mcp_server.server
```

This writes `.mcp.json`. The first time you open `claude` in this project it
will ask you to **approve** the project-scoped server (a one-time security
prompt). After that:

```
> What's Boros Energy's worst matchup in Modern?
```

## Inspect / debug

```bash
mcp dev mcp_server/server.py              # MCP Inspector UI
pytest tests/test_mcp_server.py           # tool-layer tests (run against the live DB)
```

## Layout

```
mcp_server/
  tools.py            Pure, testable tool logic (no MCP imports) — wraps analysis/win_rates.py
  server.py           FastMCP instance + thin @mcp.tool registrations + stdio entry point
  strategy_search.py  Pure chunking + result shaping for search_strategy_docs (no network)
  pinecone_index.py   Thin Pinecone integrated-inference adapter (lazy import; behind get_index)
  config.py           Reads [pinecone] from config.ini (PINECONE_API_KEY override)
scripts/
  ingest_strategy_docs.py   Chunk ../mtg-sim/docs/ and upsert to Pinecone
```
