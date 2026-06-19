"""Read Pinecone settings from config.ini (env override for the key)."""
from __future__ import annotations

import configparser
import os
from pathlib import Path

_DEFAULT_MODEL = "llama-text-embed-v2"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def pinecone_config(config_path: str | None = None) -> dict | None:
    """Return {api_key, index_name, embed_model} or None if no key is set.

    The key resolves from PINECONE_API_KEY first, then [pinecone] api_key in
    config.ini. Returning None lets callers degrade gracefully (the MCP server
    keeps serving its other tools).
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
