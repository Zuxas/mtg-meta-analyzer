"""Tests for mcp_server.strategy_search (pure: chunking + result shaping)."""
from mcp_server.strategy_search import (
    chunk_document, _classify_filename, search_strategy_docs,
)


class FakeIndex:
    def __init__(self, hits):
        self.hits = hits
        self.last = None

    def search_records(self, query, top_k, flt):
        self.last = {"query": query, "top_k": top_k, "flt": flt}
        return self.hits[:top_k]


def _hit(score, archetype, heading):
    return {"id": f"{archetype}#0", "score": score,
            "fields": {"text": "body", "archetype": archetype, "doc_type": "audit",
                       "source_file": f"{archetype}_audit.md", "heading": heading}}


def test_search_shapes_results_with_provenance():
    idx = FakeIndex([_hit(0.9, "izzet_prowess", "Double Strike"),
                     _hit(0.5, "boros_energy", "Ocelot")])
    out = search_strategy_docs("delirium", top_k=5, index=idx)
    assert out["source"] == "strategy_docs"
    assert out["query"] == "delirium"
    assert out["result_count"] == 2
    assert out["results"][0]["archetype"] == "izzet_prowess"
    assert out["results"][0]["score"] == 0.9
    assert out["results"][0]["heading"] == "Double Strike"
    assert out["results"][0]["text"] == "body"


def test_search_builds_metadata_filter():
    idx = FakeIndex([_hit(0.9, "izzet_prowess", "H")])
    search_strategy_docs("q", archetype="Izzet Prowess", doc_type="Audit", index=idx)
    assert idx.last["flt"] == {"archetype": {"$eq": "izzet_prowess"},
                               "doc_type": {"$eq": "audit"}}


def test_search_no_filter_when_unspecified():
    idx = FakeIndex([_hit(0.9, "a", "H")])
    search_strategy_docs("q", index=idx)
    assert idx.last["flt"] is None


def test_search_empty_results_note():
    out = search_strategy_docs("q", index=FakeIndex([]))
    assert out["result_count"] == 0 and out["results"] == []
    assert "note" in out


def test_classify_filename():
    assert _classify_filename("izzet_prowess_audit.md") == ("izzet_prowess", "audit")
    assert _classify_filename("boros_energy_oracle.txt") == ("boros_energy", "oracle")
    assert _classify_filename("amulet_titan_rules_reference.md") == ("amulet_titan", "rules")
    assert _classify_filename("bible_audit_gaps.md") == ("bible_audit_gaps", "misc")


def test_chunk_splits_on_headings_with_metadata():
    text = "# Title\nintro line\n\n## Section A\nalpha body\n\n## Section B\nbeta body\n"
    chunks = chunk_document("izzet_prowess_audit.md", text)
    headings = [c["heading"] for c in chunks]
    assert "Section A" in headings and "Section B" in headings
    a = next(c for c in chunks if c["heading"] == "Section A")
    assert "alpha body" in a["text"]
    assert a["archetype"] == "izzet_prowess" and a["doc_type"] == "audit"
    assert a["source_file"] == "izzet_prowess_audit.md"
    assert a["id"] == f"izzet_prowess_audit.md#{a['chunk_index']}"


def test_large_section_subsplit_with_overlap():
    big = "# H\n" + ("word " * 600)  # ~3000 chars under one heading
    chunks = chunk_document("x_audit.md", big)
    assert len(chunks) >= 2
    assert all(len(c["text"]) <= 1200 for c in chunks)
    # overlap: end of chunk 0 reappears at start of chunk 1
    assert chunks[0]["text"][-40:] in chunks[1]["text"]


def test_ids_are_unique_and_sequential():
    chunks = chunk_document("a_audit.md", "# H1\nx\n\n## H2\ny\n\n## H3\nz\n")
    idxs = [c["chunk_index"] for c in chunks]
    assert idxs == list(range(len(chunks)))
    assert len({c["id"] for c in chunks}) == len(chunks)
