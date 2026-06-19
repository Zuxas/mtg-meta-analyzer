"""Chunk the mtg-sim strategy docs and upsert them to Pinecone.

Usage:
    python scripts/ingest_strategy_docs.py            # ingest (needs a key)
    python scripts/ingest_strategy_docs.py --counts   # chunk count only (no network)
    python scripts/ingest_strategy_docs.py --corpus /path/to/docs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.strategy_search import chunk_document

_CORPUS = Path(__file__).resolve().parent.parent.parent / "mtg-sim" / "docs"


def collect_records(corpus_dir: Path) -> list[dict]:
    """Chunk every .md/.txt in the corpus into Pinecone integrated-inference
    records (keyed by `_id`, with a `text` field Pinecone embeds + metadata)."""
    records: list[dict] = []
    paths = sorted(corpus_dir.glob("*.md")) + sorted(corpus_dir.glob("*.txt"))
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for c in chunk_document(path.name, text):
            records.append({
                "_id": c["id"], "text": c["text"],
                "archetype": c["archetype"], "doc_type": c["doc_type"],
                "source_file": c["source_file"], "heading": c["heading"],
                "chunk_index": c["chunk_index"],
            })
    return records


def _upsert(records: list[dict], batch: int = 90) -> None:
    from mcp_server.pinecone_index import get_index
    index = get_index(create=True)
    for i in range(0, len(records), batch):
        index.upsert_records(records[i:i + batch])
        print(f"  upserted {min(i + batch, len(records))}/{len(records)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", action="store_true",
                    help="chunk count only, no network")
    ap.add_argument("--corpus", default=str(_CORPUS))
    args = ap.parse_args()
    records = collect_records(Path(args.corpus))
    print(f"{len(records)} chunks from {args.corpus}")
    if args.counts:
        return
    _upsert(records)
    print("ingest complete")


if __name__ == "__main__":
    main()
