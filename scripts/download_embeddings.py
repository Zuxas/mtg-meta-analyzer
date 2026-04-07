"""
scripts/download_embeddings.py

Downloads pre-computed ModernBERT card embeddings from HuggingFace.
Source: minimaxir/mtg-embeddings (parquet file, ~150MB)

Usage:
    python -m scripts.download_embeddings
"""

import os
import sys
import urllib.request

PARQUET_URL = (
    "https://huggingface.co/datasets/minimaxir/mtg-embeddings"
    "/resolve/main/mtg_embeddings.parquet"
)
OUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "mtg_embeddings.parquet"
)


def download(progress_cb=None):
    out = os.path.abspath(OUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    if progress_cb:
        progress_cb("Connecting to HuggingFace…")

    def _reporthook(block_num, block_size, total_size):
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, downloaded * 100 // total_size)
        mb_done = downloaded / 1_048_576
        mb_total = total_size / 1_048_576
        msg = f"Downloading embeddings: {pct}% ({mb_done:.1f} / {mb_total:.1f} MB)"
        if progress_cb:
            progress_cb(msg)
        else:
            print(f"\r{msg}", end="", flush=True)

    urllib.request.urlretrieve(PARQUET_URL, out, reporthook=_reporthook)

    if not progress_cb:
        print()
    size_mb = os.path.getsize(out) / 1_048_576
    msg = f"Saved to {out} ({size_mb:.1f} MB)"
    if progress_cb:
        progress_cb(msg)
    else:
        print(msg)


if __name__ == "__main__":
    download()
