"""Scryfall bulk-data download -- API shape change (2026-09-20).

Scryfall's /bulk-data index dropped `download_uri` + `size` and now serves
`jsonl_download_uri` (gzipped JSONL) + `compressed_size`. The on-disk format
stays a JSON array so nothing downstream (`_build_bulk_cache`, enrich) changes.
"""
import gc
import gzip
import io
import json
import sys

import pytest

from scrapers import scryfall
import fill_database


# ---------------------------------------------------------------------------
# Index entry -> (url, size, fmt)
# ---------------------------------------------------------------------------

def test_pick_bulk_download_prefers_jsonl_uri():
    entry = {
        "type": "oracle_cards",
        "jsonl_download_uri": "https://data.scryfall.io/oracle-cards/oc.jsonl.gz",
        "compressed_size": 24_706_130,
    }
    url, size, fmt = scryfall._pick_bulk_download(entry)
    assert url == "https://data.scryfall.io/oracle-cards/oc.jsonl.gz"
    assert size == 24_706_130
    assert fmt == "jsonl.gz"


def test_pick_bulk_download_falls_back_to_legacy_download_uri():
    entry = {
        "type": "oracle_cards",
        "download_uri": "https://data.scryfall.io/oracle-cards/oc.json",
        "size": 201_000_000,
    }
    url, size, fmt = scryfall._pick_bulk_download(entry)
    assert url == "https://data.scryfall.io/oracle-cards/oc.json"
    assert size == 201_000_000
    assert fmt == "json"


def test_pick_bulk_download_raises_naming_available_keys_when_neither():
    entry = {"type": "oracle_cards", "uri": "https://api.scryfall.com/bulk-data/x",
             "updated_at": "2026-09-20T09:01:59Z"}
    with pytest.raises(RuntimeError) as exc:
        scryfall._pick_bulk_download(entry)
    msg = str(exc.value)
    assert "jsonl_download_uri" in msg and "download_uri" in msg
    # names the keys that WERE present so the next API change is diagnosable
    assert "updated_at" in msg and "uri" in msg


# ---------------------------------------------------------------------------
# gz-JSONL stream -> JSON array on disk
# ---------------------------------------------------------------------------

CARDS = [
    {"name": "Opt", "mana_cost": "{U}", "oracle_text": "Scry 1.\nDraw a card."},
    {"name": "Lightning Bolt", "mana_cost": "{R}", "cmc": 1.0},
    {"name": "Æther Vial", "unicode": "ok"},
]


def _gz_jsonl(cards) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for c in cards:
            gz.write(json.dumps(c, ensure_ascii=False).encode("utf-8") + b"\n")
    return buf.getvalue()


def test_stream_to_json_array_roundtrips_gz_jsonl(tmp_path):
    dest = tmp_path / "oracle.json"
    n = scryfall._stream_to_json_array(io.BytesIO(_gz_jsonl(CARDS)), str(dest), "jsonl.gz")
    assert n == 3
    assert json.loads(dest.read_text(encoding="utf-8")) == CARDS
    assert not (tmp_path / "oracle.json.tmp").exists()


def test_stream_to_json_array_copies_legacy_json_array(tmp_path):
    dest = tmp_path / "oracle.json"
    raw = json.dumps(CARDS).encode("utf-8")
    scryfall._stream_to_json_array(io.BytesIO(raw), str(dest), "json")
    assert json.loads(dest.read_text(encoding="utf-8")) == CARDS


def test_stream_to_json_array_leaves_existing_file_intact_on_failure(tmp_path):
    dest = tmp_path / "oracle.json"
    dest.write_text(json.dumps(CARDS), encoding="utf-8")
    corrupt = _gz_jsonl(CARDS)[:40]  # truncated gzip stream
    with pytest.raises((EOFError, gzip.BadGzipFile)):
        scryfall._stream_to_json_array(io.BytesIO(corrupt), str(dest), "jsonl.gz")
    assert json.loads(dest.read_text(encoding="utf-8")) == CARDS
    assert not (tmp_path / "oracle.json.tmp").exists()


# ---------------------------------------------------------------------------
# fill_database: Scryfall is enrichment, not a prerequisite
# ---------------------------------------------------------------------------

def test_fill_database_main_continues_past_scryfall_failure(monkeypatch, capsys):
    ran = []

    def _boom():
        raise KeyError("download_uri")

    monkeypatch.setattr(fill_database, "step_init", lambda: ran.append("init"))
    monkeypatch.setattr(fill_database, "step_scryfall_download", _boom)
    monkeypatch.setattr(fill_database, "step_mtgtop8_backfill", lambda: ran.append("backfill"))
    monkeypatch.setattr(fill_database, "step_enrich", lambda: ran.append("enrich"))
    monkeypatch.setattr(fill_database, "step_normalize", lambda: ran.append("normalize"))
    monkeypatch.setattr(fill_database, "print_summary", lambda t: ran.append("summary"))

    fill_database.main()  # must not sys.exit(1)

    assert ran == ["init", "backfill", "enrich", "normalize", "summary"]
    assert "[warn]" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# UTF-8 stdio forcing must not close the underlying buffer
# (root cause of the 2026-09-20 backfill crash: "I/O operation on closed file")
# ---------------------------------------------------------------------------

def test_force_utf8_stdio_does_not_close_underlying_buffer(monkeypatch):
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", wrapper)

    fill_database._force_utf8_stdio()

    # _run_backfill.py wrapped stdout once itself, then importing fill_database
    # wrapped it again; the orphaned first wrapper's __del__ closed the shared
    # buffer. Reproduce by dropping our only extra reference.
    del wrapper
    gc.collect()

    sys.stdout.write("Æther Vial\n")  # raises ValueError on a closed buffer
    sys.stdout.flush()
    assert not buf.closed
    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
