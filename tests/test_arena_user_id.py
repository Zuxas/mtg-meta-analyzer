"""#11 -- arena_user_id() precedence: env > preferences.json > historical default."""
import json
import os

from db.helpers import arena_user_id, DEFAULT_ARENA_USER_ID


def _prefs(tmp_path, obj):
    p = tmp_path / "preferences.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_default_when_no_env_and_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MTGA_USER_ID", raising=False)
    assert arena_user_id(str(tmp_path / "missing.json")) == DEFAULT_ARENA_USER_ID


def test_pref_overrides_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MTGA_USER_ID", raising=False)
    assert arena_user_id(_prefs(tmp_path, {"arena_user_id": "PREFID"})) == "PREFID"


def test_env_overrides_pref_and_is_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGA_USER_ID", "  ENVID  ")
    assert arena_user_id(_prefs(tmp_path, {"arena_user_id": "PREFID"})) == "ENVID"


def test_blank_env_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv("MTGA_USER_ID", "   ")
    assert arena_user_id(_prefs(tmp_path, {"arena_user_id": "PREFID"})) == "PREFID"


def test_missing_key_and_malformed_fall_back_to_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MTGA_USER_ID", raising=False)
    assert arena_user_id(_prefs(tmp_path, {"formats": ["modern"]})) == DEFAULT_ARENA_USER_ID
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert arena_user_id(str(bad)) == DEFAULT_ARENA_USER_ID


def test_mtga_parser_uses_default_id(monkeypatch):
    monkeypatch.delenv("MTGA_USER_ID", raising=False)
    import scrapers.mtga_log_parser as m
    assert m.MY_USER_ID == DEFAULT_ARENA_USER_ID
