"""Active-format resolution for the scrape pipeline (Bug 1, 2026-09-20).

`data/preferences.json` had no top-level `formats` key for ~10 weeks. Both
readers silently fell back to ["standard"] while the log printed
"[prefs] Active formats: standard" -- a fallback that read like a setting.
Modern and Pioneer were never scraped. A default must be LOUD, and there must
be exactly one implementation of the decision.
"""
import io
import json
import sys

import pytest

from db.helpers import DEFAULT_FORMATS, load_active_formats


@pytest.fixture
def prefs(tmp_path):
    return tmp_path / "preferences.json"


def _defaulted(result, log):
    assert result == DEFAULT_FORMATS == ["standard"]
    text = "\n".join(log)
    assert "DEFAULTING to standard only" in text
    assert "Modern/Pioneer will not be scraped" in text


def test_valid_list_is_returned_verbatim_without_warning(prefs):
    prefs.write_text(json.dumps({"formats": ["modern", "standard", "pioneer"]}), encoding="utf-8")
    log = []
    assert load_active_formats(prefs, log=log.append) == ["modern", "standard", "pioneer"]
    assert log == []


def test_missing_formats_key_defaults_loudly(prefs):
    prefs.write_text(json.dumps({"ui_state": {"global": {"format": "modern"}}}), encoding="utf-8")
    log = []
    _defaulted(load_active_formats(prefs, log=log.append), log)
    assert "No 'formats' key" in "\n".join(log)


def test_empty_formats_list_defaults_loudly(prefs):
    prefs.write_text(json.dumps({"formats": []}), encoding="utf-8")
    log = []
    _defaulted(load_active_formats(prefs, log=log.append), log)


def test_malformed_json_defaults_loudly(prefs):
    prefs.write_text("{ this is not json", encoding="utf-8")
    log = []
    _defaulted(load_active_formats(prefs, log=log.append), log)


def test_missing_file_defaults_loudly(prefs):
    log = []
    _defaulted(load_active_formats(prefs, log=log.append), log)


def test_non_list_formats_value_defaults_loudly(prefs):
    prefs.write_text(json.dumps({"formats": "modern"}), encoding="utf-8")
    log = []
    _defaulted(load_active_formats(prefs, log=log.append), log)


def test_default_list_is_a_fresh_copy(prefs):
    # A caller mutating the fallback must not poison the next call.
    load_active_formats(prefs, log=lambda _m: None).append("legacy")
    assert load_active_formats(prefs, log=lambda _m: None) == ["standard"]


# ---------------------------------------------------------------------------
# Both pipeline drivers delegate to the one implementation
# ---------------------------------------------------------------------------

def test_fill_database_delegates_to_shared_loader(prefs, monkeypatch, capsys):
    import fill_database
    prefs.write_text(json.dumps({"ui_state": {}}), encoding="utf-8")
    monkeypatch.setattr(fill_database, "PREFS_PATH", str(prefs))
    assert fill_database._load_formats() == ["standard"]
    assert "DEFAULTING to standard only" in capsys.readouterr().out


def test_run_fill_from_prefs_delegates_to_shared_loader(prefs, monkeypatch, capsys):
    # Importing the scheduled driver must be safe under pytest (it used to
    # replace sys.stdout at import, closing pytest's capture buffer).
    import scripts.run_fill_from_prefs as rf
    prefs.write_text(json.dumps({"formats": ["modern", "legacy"]}), encoding="utf-8")
    monkeypatch.setattr(rf, "_PREFS", str(prefs))
    assert rf.load_formats() == ["modern", "legacy"]
    assert "DEFAULTING" not in capsys.readouterr().out
    sys.stdout.write("still writable\n")  # would raise if the buffer were closed


# ---------------------------------------------------------------------------
# The scheduled driver records a per-format outcome in scrape_state.json
# ---------------------------------------------------------------------------

def test_driver_records_per_format_scrape_state(tmp_path):
    import scripts.run_fill_from_prefs as rf
    from db.scrape_state import format_scrape_state
    path = tmp_path / "scrape_state.json"
    outcomes = {
        "modern":  [("MTGTop8 -- modern", 0), ("MTGMelee -- modern", 0)],
        "pioneer": [("MTGTop8 -- pioneer", 0), ("MTGMelee -- pioneer", 1)],
        "legacy":  [("MTGMelee -- legacy", 0)],
    }
    rf.record_format_outcomes(outcomes, path=path)

    assert format_scrape_state("modern", path=path)["last_status"] == "ok"
    p = format_scrape_state("pioneer", path=path)
    assert p["last_status"] == "error" and "MTGMelee -- pioneer" in p["last_error"]
    assert format_scrape_state("legacy", path=path)["scope"] == "format"
