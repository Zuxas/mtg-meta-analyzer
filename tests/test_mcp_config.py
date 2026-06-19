"""Tests for mcp_server.config.pinecone_config (no network, no real key)."""
from mcp_server import config as mc


def _write_cfg(tmp_path, body):
    p = tmp_path / "config.ini"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_reads_pinecone_section(tmp_path, monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    path = _write_cfg(tmp_path,
                      "[pinecone]\napi_key = pc-abc\nindex_name = my-idx\nembed_model = m1\n")
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
