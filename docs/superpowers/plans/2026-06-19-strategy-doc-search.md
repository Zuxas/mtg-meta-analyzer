# Strategy-Doc Semantic Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5th MCP tool `search_strategy_docs(query, ...)` that semantically searches the `mtg-sim/docs/` strategy corpus via Pinecone integrated inference, with a real end-to-end run as the acceptance gate.

**Architecture:** Pure chunking + result-shaping logic in `mcp_server/strategy_search.py` (unit-tested, no network); a thin Pinecone adapter in `mcp_server/pinecone_index.py` behind a narrow duck-typed interface so the pure logic is testable with a fake; an ingest CLI; a thin `@mcp.tool` wrapper. Spec: `docs/superpowers/specs/2026-06-19-strategy-doc-search-design.md`.

**Tech Stack:** Python 3.13, pytest, `pinecone>=5` (integrated inference), configparser.

---

## Interfaces (locked — every task conforms to these)

**Chunk dict** (output of `chunk_document`):
```python
{"id": "izzet_prowess_audit.md#0", "text": "...", "archetype": "izzet_prowess",
 "doc_type": "audit", "source_file": "izzet_prowess_audit.md",
 "heading": "Violent Urge DELIRIUM = DOUBLE STRIKE", "chunk_index": 0}
```

**Index adapter** (duck-typed; real impl in `pinecone_index.py`, fake in tests):
- `upsert_records(records: list[dict]) -> None` — each record has `_id`, `text`, and the metadata keys (`archetype`, `doc_type`, `source_file`, `heading`, `chunk_index`).
- `search_records(query: str, top_k: int, flt: dict | None) -> list[dict]` — returns `[{"id": str, "score": float, "fields": {metadata + text}}]`, already sorted best-first.

**Functions:**
- `mcp_server/config.py::pinecone_config() -> dict | None` → `{"api_key","index_name","embed_model"}` or `None` if no key resolvable.
- `mcp_server/strategy_search.py::chunk_document(source_file, text) -> list[dict]`
- `mcp_server/strategy_search.py::search_strategy_docs(query, top_k=5, archetype=None, doc_type=None, *, index) -> dict`
- `mcp_server/pinecone_index.py::get_index() -> adapter` (raises `IndexUnavailable` if no key/index).

---

### Task 0: Pinecone connectivity spike (de-risk; confirm SDK + model)

**Goal:** Prove the real Pinecone integrated-inference path and confirm the model id/dims BEFORE building. Throwaway code.

**Files:** Create (temporary): `scripts/_pinecone_spike.py`

- [ ] **Step 1: User adds key.** Add to `config.ini` (create the section if missing):

```ini
[pinecone]
api_key = <paste your Pinecone key>
index_name = mtg-strategy-docs
embed_model = llama-text-embed-v2
```

- [ ] **Step 2: Install the SDK**

Run: `python -m pip install --user "pinecone>=5"`
Expected: installs `pinecone` (and `pinecone-plugin-*` if any).

- [ ] **Step 3: Write the spike**

```python
# scripts/_pinecone_spike.py  (throwaway)
import configparser, os, time
from pinecone import Pinecone
cfg = configparser.ConfigParser(); cfg.read("config.ini")
key = os.environ.get("PINECONE_API_KEY") or cfg.get("pinecone", "api_key")
model = cfg.get("pinecone", "embed_model", fallback="llama-text-embed-v2")
pc = Pinecone(api_key=key)
name = "spike-test-idx"
if not pc.has_index(name):
    pc.create_index_for_model(
        name=name, cloud="aws", region="us-east-1",
        embed={"model": model, "field_map": {"text": "text"}})
idx = pc.Index(name)
idx.upsert_records("ns1", [
    {"_id": "a", "text": "Slickshot with double strike from delirium is lethal burst."},
    {"_id": "b", "text": "Amulet of Vigor untaps bounce lands for explosive ramp."}])
time.sleep(8)  # indexing latency
res = idx.search(namespace="ns1",
                 query={"inputs": {"text": "double strike delirium"}, "top_k": 2})
print(res)
pc.delete_index(name)  # clean up the spike index
```

- [ ] **Step 4: Run it**

Run: `PYTHONIOENCODING=utf-8 python scripts/_pinecone_spike.py`
Expected: prints a result where record `a` ranks first. Note the exact response shape (`res["result"]["hits"]` → each `{"_id","_score","fields"}`) and confirm `create_index_for_model` / `upsert_records` / `search` signatures. **If the model id or any signature differs, update the spec + this plan's interfaces before continuing.**

- [ ] **Step 5: Delete the spike + commit nothing**

```bash
rm scripts/_pinecone_spike.py
```
(No commit — this task only produces confirmed knowledge.)

---

### Task 1: Config loader

**Files:** Create `mcp_server/config.py`; Test `tests/test_mcp_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_config.py
import configparser
from mcp_server import config as mc

def _write_cfg(tmp_path, body):
    p = tmp_path / "config.ini"; p.write_text(body, encoding="utf-8"); return str(p)

def test_reads_pinecone_section(tmp_path, monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    path = _write_cfg(tmp_path, "[pinecone]\napi_key = pc-abc\nindex_name = my-idx\nembed_model = m1\n")
    cfg = mc.pinecone_config(config_path=path)
    assert cfg == {"api_key": "pc-abc", "index_name": "my-idx", "embed_model": "m1"}

def test_env_overrides_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "pc-env")
    path = _write_cfg(tmp_path, "[pinecone]\napi_key = pc-file\nindex_name = my-idx\n")
    cfg = mc.pinecone_config(config_path=path)
    assert cfg["api_key"] == "pc-env"
    assert cfg["embed_model"] == "llama-text-embed-v2"  # default

def test_returns_none_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    path = _write_cfg(tmp_path, "[other]\nx = 1\n")
    assert mc.pinecone_config(config_path=path) is None
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_mcp_config.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# mcp_server/config.py
"""Read Pinecone settings from config.ini (env override for the key)."""
from __future__ import annotations
import configparser, os
from pathlib import Path

_DEFAULT_MODEL = "llama-text-embed-v2"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pinecone_config(config_path: str | None = None) -> dict | None:
    """Return {api_key, index_name, embed_model} or None if no key is set.

    The key resolves from PINECONE_API_KEY first, then [pinecone] api_key.
    """
    cfg = configparser.ConfigParser()
    cfg.read(config_path or str(_PROJECT_ROOT / "config.ini"))
    env_key = os.environ.get("PINECONE_API_KEY")
    file_key = cfg.get("pinecone", "api_key", fallback=None)
    api_key = env_key or file_key
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "index_name": cfg.get("pinecone", "index_name", fallback="mtg-strategy-docs"),
        "embed_model": cfg.get("pinecone", "embed_model", fallback=_DEFAULT_MODEL),
    }
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_mcp_config.py -q` → PASS (3).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/config.py tests/test_mcp_config.py
git commit -m "feat(mcp): pinecone config loader (config.ini + env override)"
```

---

### Task 2: Document chunking

**Files:** Create `mcp_server/strategy_search.py`; Test `tests/test_strategy_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_search.py
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
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_strategy_search.py -q` → FAIL (no module).

- [ ] **Step 3: Implement chunking**

```python
# mcp_server/strategy_search.py
"""Strategy-doc semantic search: pure chunking + result shaping.

Network lives behind an injected `index` adapter (see mcp_server.pinecone_index),
so everything here is unit-testable with a fake.
"""
from __future__ import annotations
import re

_MAX_CHARS = 1200
_WINDOW = 1000
_OVERLAP = 150
_SUFFIXES = (("_rules_reference", "rules"), ("_audit", "audit"),
             ("_oracle", "oracle"))


def _classify_filename(source_file: str) -> tuple[str, str]:
    """(archetype, doc_type) from a corpus filename."""
    stem = re.sub(r"\.(md|txt)$", "", source_file)
    for suffix, dtype in _SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)], dtype
    return stem, "misc"


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) on #/##/### lines.

    Lines before the first heading go under heading ''. .txt with no headings
    yields a single ('', whole-text) section.
    """
    sections: list[tuple[str, str]] = []
    heading, buf = "", []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)$", line)
        if m:
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))
    return [(h, b) for h, b in sections if b]


def _windows(body: str) -> list[str]:
    if len(body) <= _MAX_CHARS:
        return [body]
    out, start = [], 0
    while start < len(body):
        out.append(body[start:start + _WINDOW])
        if start + _WINDOW >= len(body):
            break
        start += _WINDOW - _OVERLAP
    return out


def chunk_document(source_file: str, text: str) -> list[dict]:
    archetype, doc_type = _classify_filename(source_file)
    chunks: list[dict] = []
    for heading, body in _split_sections(text):
        for piece in _windows(body):
            i = len(chunks)
            chunks.append({
                "id": f"{source_file}#{i}", "text": piece,
                "archetype": archetype, "doc_type": doc_type,
                "source_file": source_file, "heading": heading,
                "chunk_index": i,
            })
    return chunks
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_strategy_search.py -q` → PASS (4).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/strategy_search.py tests/test_strategy_search.py
git commit -m "feat(mcp): strategy-doc chunking with archetype/doc_type metadata"
```

---

### Task 3: Search + result shaping (against a fake index)

**Files:** Modify `mcp_server/strategy_search.py`; Modify `tests/test_strategy_search.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_strategy_search.py
from mcp_server.strategy_search import search_strategy_docs

class FakeIndex:
    def __init__(self, hits): self.hits = hits; self.last = None
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
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_strategy_search.py -q` → FAIL (no `search_strategy_docs`).

- [ ] **Step 3: Implement search**

```python
# append to mcp_server/strategy_search.py
_RESULT_FIELDS = ("text", "archetype", "doc_type", "source_file", "heading")


def _build_filter(archetype, doc_type) -> dict | None:
    flt = {}
    if archetype:
        flt["archetype"] = {"$eq": archetype.strip().lower().replace(" ", "_")}
    if doc_type:
        flt["doc_type"] = {"$eq": doc_type.strip().lower()}
    return flt or None


def search_strategy_docs(query, top_k=5, archetype=None, doc_type=None, *, index) -> dict:
    """Semantic search over the strategy corpus. `index` is an injected adapter
    exposing search_records(query, top_k, flt)."""
    flt = _build_filter(archetype, doc_type)
    hits = index.search_records(query, top_k, flt)
    results = []
    for h in hits:
        f = h.get("fields", {})
        results.append({"text": f.get("text"), "score": h.get("score"),
                        **{k: f.get(k) for k in _RESULT_FIELDS if k != "text"}})
    out = {"query": query, "source": "strategy_docs",
           "result_count": len(results), "results": results}
    if not results:
        out["note"] = "no matching strategy content"
    return out
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_strategy_search.py -q` → PASS (8 total).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/strategy_search.py tests/test_strategy_search.py
git commit -m "feat(mcp): search_strategy_docs result shaping + metadata filters"
```

---

### Task 4: Pinecone index adapter (real network impl)

**Files:** Create `mcp_server/pinecone_index.py`; Test `tests/test_pinecone_index.py`

- [ ] **Step 1: Write the failing test** (no network — assert normalization + unavailability)

```python
# tests/test_pinecone_index.py
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
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_pinecone_index.py -q` → FAIL (no module).

- [ ] **Step 3: Implement** (adjust `search`/`upsert_records`/`create_index_for_model` calls to whatever the Task 0 spike confirmed)

```python
# mcp_server/pinecone_index.py
"""Thin Pinecone integrated-inference adapter. Lazy import so the MCP server
imports fine without the SDK / a key."""
from __future__ import annotations
from mcp_server.config import pinecone_config

_NAMESPACE = "docs"


class IndexUnavailable(RuntimeError):
    pass


def _normalize(raw) -> list[dict]:
    hits = (raw.get("result") or {}).get("hits") or []
    return [{"id": h.get("_id"), "score": h.get("_score"),
             "fields": h.get("fields", {})} for h in hits]


class _PineconeAdapter:
    def __init__(self, index, namespace=_NAMESPACE):
        self._index = index
        self._ns = namespace

    def upsert_records(self, records: list[dict]) -> None:
        self._index.upsert_records(self._ns, records)

    def search_records(self, query: str, top_k: int, flt: dict | None) -> list[dict]:
        q = {"inputs": {"text": query}, "top_k": top_k}
        if flt:
            q["filter"] = flt
        raw = self._index.search(namespace=self._ns, query=q)
        return _normalize(raw)


def get_index(create: bool = False):
    cfg = pinecone_config()
    if not cfg:
        raise IndexUnavailable("no Pinecone api_key (config.ini [pinecone] or PINECONE_API_KEY)")
    from pinecone import Pinecone  # lazy
    pc = Pinecone(api_key=cfg["api_key"])
    name = cfg["index_name"]
    if not pc.has_index(name):
        if not create:
            raise IndexUnavailable(f"index '{name}' missing; run scripts/ingest_strategy_docs.py")
        pc.create_index_for_model(
            name=name, cloud="aws", region="us-east-1",
            embed={"model": cfg["embed_model"], "field_map": {"text": "text"}})
    return _PineconeAdapter(pc.Index(name))
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_pinecone_index.py -q` → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/pinecone_index.py tests/test_pinecone_index.py
git commit -m "feat(mcp): pinecone integrated-inference adapter (lazy, normalized)"
```

---

### Task 5: Ingest script

**Files:** Create `scripts/ingest_strategy_docs.py`; Test `tests/test_ingest_strategy_docs.py`

- [ ] **Step 1: Write the failing test** (pure: collecting records from a temp corpus, no network)

```python
# tests/test_ingest_strategy_docs.py
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
    assert "id" not in r  # uses _id for Pinecone
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_ingest_strategy_docs.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# scripts/ingest_strategy_docs.py
"""Chunk the mtg-sim strategy docs and upsert them to Pinecone.

Usage:
    python scripts/ingest_strategy_docs.py            # ingest
    python scripts/ingest_strategy_docs.py --counts   # chunk count only (no network)
"""
from __future__ import annotations
import argparse
from pathlib import Path

from mcp_server.strategy_search import chunk_document

_CORPUS = Path(__file__).resolve().parent.parent.parent / "mtg-sim" / "docs"


def collect_records(corpus_dir: Path) -> list[dict]:
    """Chunk every .md/.txt into Pinecone integrated-inference records."""
    records: list[dict] = []
    for path in sorted(corpus_dir.glob("*.md")) + sorted(corpus_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for c in chunk_document(path.name, text):
            records.append({"_id": c["id"], "text": c["text"],
                            "archetype": c["archetype"], "doc_type": c["doc_type"],
                            "source_file": c["source_file"], "heading": c["heading"],
                            "chunk_index": c["chunk_index"]})
    return records


def _upsert(records: list[dict], batch: int = 90) -> None:
    from mcp_server.pinecone_index import get_index
    index = get_index(create=True)
    for i in range(0, len(records), batch):
        index.upsert_records(records[i:i + batch])
        print(f"  upserted {min(i + batch, len(records))}/{len(records)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", action="store_true", help="chunk count only, no network")
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
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_ingest_strategy_docs.py -q` → PASS (1).
  Also run `python scripts/ingest_strategy_docs.py --counts` → prints a chunk count (no network); expect > 17.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_strategy_docs.py tests/test_ingest_strategy_docs.py
git commit -m "feat(mcp): strategy-doc ingest script (chunk + upsert)"
```

---

### Task 6: MCP tool registration + deps + docs

**Files:** Modify `mcp_server/server.py`; Modify `requirements.txt`, `config.example.ini`, `mcp_server/README.md`; Test `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mcp_server.py
def test_search_strategy_docs_registered():
    from mcp_server import server
    # tool is registered on the FastMCP instance
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    assert any(t.name == "search_strategy_docs" for t in tools)

def test_search_strategy_docs_index_unavailable(monkeypatch):
    from mcp_server import server
    from mcp_server.pinecone_index import IndexUnavailable
    def boom(): raise IndexUnavailable("no key")
    monkeypatch.setattr(server, "get_index", boom)
    out = server.search_strategy_docs("anything")
    assert out["error"] == "index_unavailable"
    assert "hint" in out
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_mcp_server.py -q -k strategy` → FAIL.

- [ ] **Step 3: Implement the wrapper** — add to `mcp_server/server.py` (imports at top: `from mcp_server.strategy_search import search_strategy_docs as _search`, `from mcp_server.pinecone_index import get_index, IndexUnavailable`):

```python
@mcp.tool(annotations=_READ_ONLY)
def search_strategy_docs(query: str, top_k: int = 5,
                         archetype: str | None = None,
                         doc_type: str | None = None) -> dict:
    """Semantic search over Team Resolve's MTG strategy documents.

    Searches archetype primers, card-by-card audits, and oracle/rules references
    (e.g. 'how does Izzet Prowess use delirium for lethal?'). Results carry
    `source: "strategy_docs"` and cite their source_file + heading.

    Args:
        query: Natural-language question or topic.
        top_k: Max results (default 5).
        archetype: Optional filter, e.g. 'izzet_prowess' (spaces ok).
        doc_type: Optional filter: 'audit', 'oracle', 'rules', or 'misc'.
    """
    try:
        index = get_index()
    except IndexUnavailable as e:
        return {"error": "index_unavailable", "message": str(e),
                "hint": "set [pinecone] api_key in config.ini and run "
                        "scripts/ingest_strategy_docs.py"}
    try:
        return _search(query, top_k=top_k, archetype=archetype,
                       doc_type=doc_type, index=index)
    except Exception as e:  # never raise over stdio
        return {"error": "search_failed", "message": str(e)}
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_mcp_server.py -q` → PASS.

- [ ] **Step 5: Update deps + docs**
  - `requirements.txt`: add `pinecone>=5` under a `# Strategy-doc semantic search (MCP)` comment.
  - `config.example.ini`: append:
    ```ini

    # Pinecone (strategy-doc semantic search MCP tool). Free account key.
    [pinecone]
    api_key =
    index_name = mtg-strategy-docs
    embed_model = llama-text-embed-v2
    ```
  - `mcp_server/README.md`: add a "5th tool: search_strategy_docs" section — setup (key in config.ini, `pip install pinecone`, run `scripts/ingest_strategy_docs.py`), the tool signature, and that it degrades gracefully without a key.

- [ ] **Step 6: Run the whole suite** — `python -m pytest -q` → all green (no network needed; live test is skipped).

- [ ] **Step 7: Commit**

```bash
git add mcp_server/server.py requirements.txt config.example.ini mcp_server/README.md tests/test_mcp_server.py
git commit -m "feat(mcp): register search_strategy_docs tool + deps + docs"
```

---

### Task 7: LIVE end-to-end verification (the acceptance gate)

**Files:** Create `tests/test_strategy_search_live.py`

- [ ] **Step 1: Ensure the key is in `config.ini`** (from Task 0). Confirm: `python -c "from mcp_server.config import pinecone_config; print(bool(pinecone_config()))"` → `True`.

- [ ] **Step 2: Run the real ingest**

Run: `PYTHONIOENCODING=utf-8 python scripts/ingest_strategy_docs.py`
Expected: prints chunk count then `upserted N/N` batches then `ingest complete`, no errors.

- [ ] **Step 3: Run it AGAIN (idempotency check)** — same command; expect the same chunk count and no error (deterministic `_id`s overwrite, no duplicates).

- [ ] **Step 4: Write the live smoke test**

```python
# tests/test_strategy_search_live.py
import os, pytest
pytestmark = pytest.mark.skipif(
    not (os.environ.get("PINECONE_API_KEY") or _has_cfg_key()),
    reason="no Pinecone key")

def _has_cfg_key():
    from mcp_server.config import pinecone_config
    return pinecone_config() is not None

def test_live_query_finds_prowess_double_strike():
    from mcp_server.server import search_strategy_docs
    out = search_strategy_docs("double strike delirium prowess", top_k=5)
    assert "error" not in out, out
    files = [r["source_file"] for r in out["results"]]
    assert any("izzet_prowess" in f for f in files), files

def test_live_archetype_filter():
    from mcp_server.server import search_strategy_docs
    out = search_strategy_docs("removal", top_k=5, archetype="izzet_prowess")
    assert all(r["archetype"] == "izzet_prowess" for r in out["results"]), out
```
(Note: `_has_cfg_key` must be defined before `pytestmark` uses it — define it above the marker, or inline the call. Put the function def at module top.)

- [ ] **Step 5: Run the live test**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_strategy_search_live.py -q`
Expected: PASS — the Izzet Prowess audit surfaces for the double-strike query, and the archetype filter is respected. **This is the acceptance gate; if it fails, debug before proceeding (check indexing latency — Pinecone may need a few seconds after upsert; re-run).**

- [ ] **Step 6: Confirm CI safety** — `git grep -n "PINECONE_API_KEY" tests/` shows the live test is skip-guarded. Run `python -m pytest -q` once more; the live test should report as skipped only if no key, else pass.

- [ ] **Step 7: Commit**

```bash
git add tests/test_strategy_search_live.py
git commit -m "test(mcp): live end-to-end strategy-doc search smoke (skip without key)"
```

---

### Task 8: Docs + finish

- [ ] **Step 1: Update `CLAUDE.md`** — dated note: 5th MCP tool `search_strategy_docs` shipped; Pinecone integrated inference over `mtg-sim/docs/`; config in `[pinecone]`; ingest via `scripts/ingest_strategy_docs.py`; graceful degradation; live-verified.
- [ ] **Step 2: Update `NEXT_STEPS.md`** — mark the "deferred Pinecone doc search" stretch as DONE; note re-ingest is manual on doc change.
- [ ] **Step 3: Update `ROADMAP.md`** — check off the Pinecone semantic-search item.
- [ ] **Step 4: Commit docs** (scrub local paths / the user's first name per the pre-push hook):
```bash
git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
git commit -m "docs: strategy-doc semantic search (Pinecone MCP tool) shipped"
```
- [ ] **Step 5: Finish the branch** — use superpowers:finishing-a-development-branch (merge to main, push, confirm CI green).

---

## Self-Review Notes

- **Spec coverage:** integrated inference → Task 0/4; config.ini key + env override → Task 1; corpus `docs/` → Task 5 `_CORPUS`; chunking + metadata → Task 2; tool contract + filters + provenance → Task 3/6; graceful degradation → Task 4 `IndexUnavailable` + Task 6 wrapper; CI mock-only + live skip-guard → Tasks 1-6 (no network) + Task 7 (skipif); **live acceptance gate** → Task 7; idempotent ingest → Task 5 deterministic `_id` + Task 7 Step 3.
- **Risk — Pinecone SDK surface:** Task 0 spike confirms the exact `create_index_for_model` / `upsert_records` / `search` signatures + model id BEFORE Tasks 4-5 lock them in. If the spike shows a different surface, update Task 4's adapter and the interfaces block.
- **Risk — indexing latency:** integrated-inference upsert isn't instantly queryable; Task 7 notes a retry. The live test may need a short wait after ingest.
- **Deferred (YAGNI):** auto re-index on file change, hybrid/rerank, indexing `decks/`.
