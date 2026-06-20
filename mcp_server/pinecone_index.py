"""Thin Pinecone integrated-inference adapter.

The Pinecone SDK is imported lazily inside get_index() so the MCP server (and
the test suite) import fine without the package or an API key. The exact SDK
call surface (create_index_for_model / upsert_records / search) is confirmed by
the connectivity spike in the implementation plan.
"""
from __future__ import annotations

from mcp_server.config import pinecone_config

_NAMESPACE = "docs"


class IndexUnavailable(RuntimeError):
    """No Pinecone key, or the index hasn't been built yet."""


def _normalize(raw) -> list[dict]:
    """Flatten a Pinecone search response to [{id, score, fields}]."""
    hits = (raw.get("result") or {}).get("hits") or []
    return [{"id": h.get("_id"), "score": h.get("_score"),
             "fields": h.get("fields", {})} for h in hits]


class _PineconeAdapter:
    def __init__(self, index, namespace=_NAMESPACE):
        self._index = index
        self._ns = namespace

    def upsert_records(self, records: list[dict]) -> None:
        # Keyword args: the pinecone SDK signature is upsert_records(records,
        # namespace) -- pass by name so arg order can't silently swap them.
        self._index.upsert_records(records=records, namespace=self._ns)

    def search_records(self, query: str, top_k: int, flt: dict | None) -> list[dict]:
        q = {"inputs": {"text": query}, "top_k": top_k}
        if flt:
            q["filter"] = flt
        raw = self._index.search(namespace=self._ns, query=q)
        return _normalize(raw)


def get_index(create: bool = False):
    """Return a _PineconeAdapter, or raise IndexUnavailable.

    create=True will create the integrated-inference index if it's missing
    (used by the ingest script); the query path leaves create=False so a missing
    index surfaces a clear, actionable error instead of silently creating one.
    """
    cfg = pinecone_config()
    if not cfg:
        raise IndexUnavailable(
            "no Pinecone api_key (config.ini [pinecone] or PINECONE_API_KEY)")
    from pinecone import Pinecone  # lazy import
    pc = Pinecone(api_key=cfg["api_key"])
    name = cfg["index_name"]
    if not pc.has_index(name):
        if not create:
            raise IndexUnavailable(
                f"index '{name}' missing; run scripts/ingest_strategy_docs.py")
        pc.create_index_for_model(
            name=name, cloud="aws", region="us-east-1",
            embed={"model": cfg["embed_model"], "field_map": {"text": "text"}})
    return _PineconeAdapter(pc.Index(name))
