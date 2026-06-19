"""Tests for mcp_server.strategy_search (pure: chunking + result shaping)."""
from mcp_server.strategy_search import chunk_document, _classify_filename


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
