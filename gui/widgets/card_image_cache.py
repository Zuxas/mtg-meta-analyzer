"""Disk-cached Scryfall card image fetcher.

cache_path() returns the on-disk JPEG path for a given (name, grpid).
load_pixmap() returns a QPixmap, fetching from Scryfall on cache miss.

Phase 1 keeps this simple and blocking. Phase 2/3 may wrap in a worker.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "card_images"
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"


def _slugify(name: str) -> str:
    """Normalize a card name to a filesystem-safe slug. Split cards keep only
    the front half so 'Roaring Furnace // Steaming Sauna' -> 'roaring_furnace'."""
    front, _, _ = name.partition("//")
    s = front.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "unknown"


def cache_path(*, card_name: str, grpid: Optional[int]) -> Path:
    """Where this card's JPEG would live on disk."""
    if grpid:
        return CACHE_DIR / f"{grpid}.jpg"
    return CACHE_DIR / f"{_slugify(card_name)}.jpg"


def _fetch_url_bytes(url: str) -> Optional[bytes]:
    """Return raw bytes from a URL, or None on any failure."""
    if requests is None:
        return None
    try:
        resp = requests.get(url, timeout=8, allow_redirects=True)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        return None
    return None


def fetch_to_cache(*, card_name: str, grpid: Optional[int]) -> Optional[Path]:
    """Download the small Scryfall image for card_name; write to cache.

    Returns the cache path on success, None on failure (no Scryfall match,
    network error, etc.)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(card_name=card_name, grpid=grpid)
    if path.exists() and path.stat().st_size > 0:
        return path
    front, _, _ = card_name.partition("//")
    params = urllib.parse.urlencode({
        "exact": front.strip(),
        "format": "image",
        "version": "small",
    })
    blob = _fetch_url_bytes(f"{SCRYFALL_NAMED_URL}?{params}")
    if blob is None:
        return None
    try:
        path.write_bytes(blob)
    except OSError:
        return None
    return path


def load_pixmap(*, card_name: str, grpid: Optional[int]):
    """Return a QPixmap for this card, or None if unavailable.

    Imports QPixmap lazily so this module is safe to import in headless tests.
    """
    path = fetch_to_cache(card_name=card_name, grpid=grpid)
    if path is None:
        return None
    try:
        from PyQt6.QtGui import QPixmap
    except ImportError:
        return None
    px = QPixmap(str(path))
    return px if not px.isNull() else None
