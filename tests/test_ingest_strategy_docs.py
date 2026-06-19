"""Tests for scripts.ingest_strategy_docs.collect_records (pure, no network)."""
from pathlib import Path

from scripts.ingest_strategy_docs import collect_records


def test_collect_records_from_corpus(tmp_path):
    (tmp_path / "izzet_prowess_audit.md").write_text("# H\nbody alpha\n", encoding="utf-8")
    (tmp_path / "boros_energy_oracle.txt").write_text("card one\n\ncard two\n", encoding="utf-8")
    recs = collect_records(Path(tmp_path))
    assert len(recs) >= 2
    r = next(r for r in recs if r["archetype"] == "izzet_prowess")
    assert r["_id"].startswith("izzet_prowess_audit.md#")
    assert "text" in r and r["doc_type"] == "audit"
    assert "id" not in r  # Pinecone records use _id, not id
