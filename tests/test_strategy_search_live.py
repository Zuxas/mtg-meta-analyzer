"""LIVE end-to-end acceptance test for search_strategy_docs.

Skipped unless a Pinecone key is configured (config.ini [pinecone] or
PINECONE_API_KEY). It assumes the corpus has already been ingested:
    python scripts/ingest_strategy_docs.py

CI has no key, so this is always skipped there. This is the acceptance gate
the feature is judged on -- it must pass against real Pinecone before the
work is considered live.
"""
import os

import pytest


def _has_cfg_key() -> bool:
    from mcp_server.config import pinecone_config
    return pinecone_config() is not None


pytestmark = pytest.mark.skipif(
    not (os.environ.get("PINECONE_API_KEY") or _has_cfg_key()),
    reason="no Pinecone key configured",
)


def test_live_query_finds_prowess_double_strike():
    from mcp_server.server import search_strategy_docs
    out = search_strategy_docs("double strike delirium prowess", top_k=5)
    assert "error" not in out, out
    files = [r["source_file"] for r in out["results"]]
    assert any("izzet_prowess" in f for f in files), files


def test_live_archetype_filter():
    from mcp_server.server import search_strategy_docs
    out = search_strategy_docs("removal", top_k=5, archetype="izzet_prowess")
    assert "error" not in out, out
    assert all(r["archetype"] == "izzet_prowess" for r in out["results"]), out
