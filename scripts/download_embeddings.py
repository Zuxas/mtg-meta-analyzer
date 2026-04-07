"""
Download pre-computed MTG card embeddings from HuggingFace.

Source: minimaxir/mtg-embeddings (ModernBERT 768-dim, 32k cards)
Saves to: data/mtg_embeddings.parquet (~94 MB)
"""

import os
import sys

_URL = (
    "https://huggingface.co/api/datasets/minimaxir/mtg-embeddings"
    "/parquet/cards/train/0.parquet"
)
_DEST = os.path.join(os.path.dirname(__file__), "..", "data", "mtg_embeddings.parquet")


def download(dest: str = _DEST, force: bool = False) -> str:
    """Download the embeddings parquet file. Returns the file path."""
    dest = os.path.abspath(dest)
    if os.path.exists(dest) and not force:
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"Already exists: {dest} ({size_mb:.1f} MB)")
        return dest

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"Downloading card embeddings (~94 MB)...")

    import requests
    resp = requests.get(_URL, stream=True, timeout=120)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                print(f"\r  {downloaded / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB ({pct:.0f}%)", end="", flush=True)

    print(f"\nSaved to {dest}")
    return dest


if __name__ == "__main__":
    force = "--force" in sys.argv
    download(force=force)
