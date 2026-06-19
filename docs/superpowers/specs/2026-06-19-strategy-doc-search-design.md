# Strategy-Doc Semantic Search (MCP tool) — Design Spec

**Date:** 2026-06-19
**Status:** Approved (pending spec review)

## Goal

Add a 5th MCP tool, `search_strategy_docs(query, ...)`, that does semantic search over the mtg-sim strategy-doc corpus, backed by **Pinecone integrated inference** (Pinecone hosts the embedding model; we upsert raw text and query with raw text). This is the deferred stretch from the 2026-06-11 MCP-server work and a portfolio piece for a Pinecone application — so **a real end-to-end run against live Pinecone is the acceptance gate**, not just passing mocked tests.

## Non-negotiable acceptance criteria

1. **Live ingest works:** `python scripts/ingest_strategy_docs.py` creates the index (if absent), chunks all `mtg-sim/docs/` files, and upserts them to a real Pinecone index without error. Re-running is idempotent (no duplicate vectors).
2. **Live query returns sensible results:** through the actual MCP tool path, `search_strategy_docs("double strike delirium prowess")` returns the Izzet Prowess audit chunk that discusses Violent Urge / delirium double strike in its top results; an archetype filter narrows results correctly.
3. **Graceful degradation:** with no key / missing index, the tool returns a structured `index_unavailable` error and the MCP server still starts and serves the other four tools.
4. **CI stays mock-only:** unit tests run with no network and no key; the live smoke is skipped unless `PINECONE_API_KEY` is present.

## Corpus

`../mtg-sim/docs/` — 17 curated files (~165 KB):
- `*_audit.md` — card-by-card APL audits (rich prose, the highest-signal content)
- `*_oracle.txt` — oracle text per archetype
- `*_rules_reference.md` — rules references
- a few cross-cutting (`bible_audit_gaps.md`, `PHASE_RUNNER.md`, etc.)

**Excluded:** `decks/` (decklists — structured data, already in the meta DB), `data/` (dumps), root project-meta. The corpus is small; this is an **integration showcase** whose architecture scales to a larger corpus unchanged. The corpus path is configurable so it can be pointed at a bigger set later.

## Architecture

Mirrors the existing `mcp_server` pattern: thin `@mcp.tool` wrappers over pure logic, `_READ_ONLY` annotations, provenance (`source`) on every result, structured error objects (never raise over stdio).

| File | Responsibility |
|---|---|
| `mcp_server/strategy_search.py` *(new)* | `chunk_document(source_file, text)` → list of chunk dicts (pure, unit-tested, no network). `search_strategy_docs(query, top_k, archetype, doc_type, *, index)` → query Pinecone via an **injected index object** (mockable) and shape results with provenance. |
| `mcp_server/pinecone_index.py` *(new, small)* | `get_index()` — read config, lazily create the Pinecone client + index handle. Isolated so `strategy_search` stays testable without the SDK. |
| `mcp_server/config.py` *(new, small)* | `pinecone_config()` → `{api_key, index_name, embed_model}` from `config.ini [pinecone]`, with `PINECONE_API_KEY` env override. |
| `scripts/ingest_strategy_docs.py` *(new)* | CLI (like `scripts/ingest_set.py`): create index if absent (integrated model), chunk every corpus doc, upsert records with metadata + deterministic IDs. `--counts` / dry-run friendly. |
| `mcp_server/server.py` | Add the thin `@mcp.tool` `search_strategy_docs` wrapper. |
| `requirements.txt` | add `pinecone>=5` (the renamed SDK that supports integrated inference). |
| `config.example.ini` | add a commented `[pinecone]` template. |
| `mcp_server/README.md` | document setup (key, ingest) + the new tool. |

## Embedding model

Pinecone integrated-inference dense model **`llama-text-embed-v2`** (their current flagship; 1024-dim). The exact model id + dimensions are **confirmed in the connectivity spike** (Step 0 of the plan) before any real build — if the name/dims differ, the spec value is updated. `multilingual-e5-large` is the fallback if `llama-text-embed-v2` is unavailable on the free tier.

## Tool contract

```
search_strategy_docs(query: str,
                     top_k: int = 5,
                     archetype: str | None = None,
                     doc_type: str | None = None) -> dict
```

Returns:
```json
{
  "query": "...",
  "source": "strategy_docs",
  "result_count": 5,
  "results": [
    {"text": "...", "score": 0.83, "archetype": "izzet_prowess",
     "doc_type": "audit", "source_file": "izzet_prowess_audit.md",
     "heading": "Violent Urge DELIRIUM = DOUBLE STRIKE"}
  ]
}
```

- `archetype` / `doc_type` → Pinecone **metadata filters** (exact match, lowercased).
- No results → `{..., "result_count": 0, "results": [], "note": "no matching strategy content"}`.
- Missing key / index → `{"error": "index_unavailable", "message": "...", "hint": "set [pinecone] api_key in config.ini and run scripts/ingest_strategy_docs.py"}`.

## Chunking

- **Markdown:** split on headings (`#`/`##`/`###`) into sections; sub-split any section > ~1200 chars into ~1000-char windows with ~150-char overlap. Heading text carried into each chunk's `heading` metadata.
- **Oracle `.txt`:** split on blank-line blocks (each card/entry), grouping to ~1000 chars.
- **Metadata per chunk:** `archetype` (derived from filename stem, e.g. `izzet_prowess_audit.md` → `izzet_prowess`), `doc_type` (`audit` | `oracle` | `rules` | `misc` from filename suffix), `source_file`, `heading`, `chunk_index`.
- **ID:** deterministic `f"{source_file}#{chunk_index}"` → idempotent upserts.

## Data flow

- **Ingest (offline, on demand):** docs → `chunk_document` → upsert `{_id, text, ...metadata}` records to Pinecone; Pinecone embeds the `text` field via integrated inference.
- **Query (per tool call):** `query` string → Pinecone `search` (Pinecone embeds the query, returns top_k by similarity) with optional metadata filter → shape into the result dict.

## Error handling

- Config/key absent or index missing → `index_unavailable` structured error; server still starts (other tools unaffected).
- Any Pinecone/network exception inside the tool → caught, returned as a structured error; never an unhandled exception over stdio.

## Testing

- **Pure unit tests** (`tests/test_strategy_search.py`): chunking (heading split, size/overlap, oracle blocks), metadata derivation from filenames, deterministic IDs, and `search_strategy_docs` result-shaping + filter construction against a **fake index object** (no network, no key).
- **Live smoke** (`tests/test_strategy_search_live.py`): `pytest.mark.skipif(no PINECONE_API_KEY)` — ingest a 2-doc subset into a temp/namespace, query, assert the expected archetype chunk ranks. Excluded from CI (no key there).
- Full suite stays green; CI unaffected (no `pinecone` import at server import time if key absent — lazy import in `pinecone_index`).

## Config

`config.ini`:
```ini
[pinecone]
api_key = pc-...
index_name = mtg-strategy-docs
embed_model = llama-text-embed-v2
```
`PINECONE_API_KEY` env var overrides `api_key`. `config.example.ini` gets a commented template. `config.ini` is already gitignored — the real key never lands in git.

## Out of scope (YAGNI)

- Re-indexing on file change / watching the corpus (manual `ingest` run is fine).
- Hybrid (sparse+dense) search, reranking — dense integrated inference only for v1.
- Indexing `decks/` decklists or the meta DB.
