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
