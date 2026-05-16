"""Tests for gui/widgets/card_image_cache.py — path logic + cache hits."""
from pathlib import Path
import pytest


def test_cache_path_uses_grpid_when_available(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Eddymurk Crab", grpid=12345)
    assert p == tmp_path / "12345.jpg"


def test_cache_path_falls_back_to_slug_when_no_grpid(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Eddymurk Crab", grpid=None)
    assert p == tmp_path / "eddymurk_crab.jpg"


def test_cache_path_handles_split_names(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    p = cic.cache_path(card_name="Roaring Furnace // Steaming Sauna", grpid=None)
    assert p == tmp_path / "roaring_furnace.jpg"  # first half only


def test_load_pixmap_returns_none_for_missing_card_when_no_network(tmp_path, monkeypatch):
    from gui.widgets import card_image_cache as cic
    monkeypatch.setattr(cic, "CACHE_DIR", tmp_path)
    # Don't allow real network. fetch_url returns None.
    monkeypatch.setattr(cic, "_fetch_url_bytes", lambda url: None)
    px = cic.load_pixmap(card_name="No-Such-Card-1234", grpid=None)
    assert px is None
