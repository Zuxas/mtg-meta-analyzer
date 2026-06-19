"""Strategy-doc semantic search: pure chunking + result shaping.

Network lives behind an injected `index` adapter (see mcp_server.pinecone_index),
so everything here is unit-testable with a fake.
"""
from __future__ import annotations

import re

_MAX_CHARS = 1200
_WINDOW = 1000
_OVERLAP = 150
# Order matters: check the most specific suffix first.
_SUFFIXES = (("_rules_reference", "rules"), ("_audit", "audit"),
             ("_oracle", "oracle"))


def _classify_filename(source_file: str) -> tuple[str, str]:
    """(archetype, doc_type) derived from a corpus filename."""
    stem = re.sub(r"\.(md|txt)$", "", source_file)
    for suffix, dtype in _SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)], dtype
    return stem, "misc"


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) on #/##/### lines.

    Lines before the first heading go under heading ''. A .txt with no headings
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
    """Chunk one corpus document into metadata-tagged pieces."""
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
