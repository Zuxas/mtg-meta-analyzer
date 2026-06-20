"""Tests for mcp_server.pinecone_index (no network: normalization + unavailability)."""
import pytest

from mcp_server import pinecone_index as pi


def test_get_index_raises_without_config(monkeypatch):
    monkeypatch.setattr(pi, "pinecone_config", lambda: None)
    with pytest.raises(pi.IndexUnavailable):
        pi.get_index()


def test_normalize_search_response():
    raw = {"result": {"hits": [
        {"_id": "izzet_prowess_audit.md#3", "_score": 0.81,
         "fields": {"text": "t", "archetype": "izzet_prowess", "doc_type": "audit",
                    "source_file": "izzet_prowess_audit.md", "heading": "H"}}]}}
    out = pi._normalize(raw)
    assert out == [{"id": "izzet_prowess_audit.md#3", "score": 0.81,
                    "fields": {"text": "t", "archetype": "izzet_prowess",
                               "doc_type": "audit",
                               "source_file": "izzet_prowess_audit.md", "heading": "H"}}]


def test_normalize_empty():
    assert pi._normalize({"result": {"hits": []}}) == []
    assert pi._normalize({}) == []


class _SpyIndex:
    """Mirrors the real pinecone Index kwargs: upsert_records(records, namespace),
    search(namespace, query). Catches positional-arg-order mistakes."""
    def __init__(self):
        self.upsert_call = None
        self.search_call = None

    def upsert_records(self, records=None, namespace=None, **kw):
        self.upsert_call = {"records": records, "namespace": namespace}

    def search(self, namespace=None, query=None, **kw):
        self.search_call = {"namespace": namespace, "query": query}
        return {"result": {"hits": []}}


def test_adapter_upsert_routes_records_and_namespace():
    spy = _SpyIndex()
    pi._PineconeAdapter(spy, namespace="docs").upsert_records([{"_id": "x", "text": "t"}])
    assert spy.upsert_call["namespace"] == "docs"
    assert spy.upsert_call["records"] == [{"_id": "x", "text": "t"}]


def test_adapter_search_builds_query_and_namespace():
    spy = _SpyIndex()
    pi._PineconeAdapter(spy, namespace="docs").search_records(
        "q", 5, {"archetype": {"$eq": "x"}})
    assert spy.search_call["namespace"] == "docs"
    assert spy.search_call["query"]["inputs"] == {"text": "q"}
    assert spy.search_call["query"]["top_k"] == 5
    assert spy.search_call["query"]["filter"] == {"archetype": {"$eq": "x"}}


def test_adapter_search_omits_filter_when_none():
    spy = _SpyIndex()
    pi._PineconeAdapter(spy, namespace="docs").search_records("q", 5, None)
    assert "filter" not in spy.search_call["query"]
