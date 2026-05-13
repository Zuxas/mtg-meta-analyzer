"""Tests for gui.state.UIState.

UIState is a pure-Python singleton wrapping data/preferences.json.
It supports dotted-path get/set, debounced disk save, and corrupt-JSON
recovery. These tests never touch Qt — UIState must work standalone.
"""
import json
from pathlib import Path

import pytest

from gui.state import UIState


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect UIState to a per-test preferences.json under tmp_path."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    # Reset singleton between tests. This requires UIState to declare
    # `_instance` as a class attribute (Task 2's implementation does
    # this — `_instance: "UIState | None" = None` at class level).
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


def test_get_returns_default_when_key_missing(tmp_prefs):
    state = UIState.instance()
    assert state.get("tabs.dashboard.selected_archetype", default="Foo") == "Foo"


def test_set_then_get_round_trip(tmp_prefs):
    state = UIState.instance()
    state.set("tabs.dashboard.selected_archetype", "Izzet Prowess")
    assert state.get("tabs.dashboard.selected_archetype") == "Izzet Prowess"


def test_set_creates_intermediate_dicts(tmp_prefs):
    state = UIState.instance()
    state.set("tabs.scout.days", 14)
    state.set("tabs.scout.target_archetypes", ["Izzet Prowess"])
    assert state.get("tabs.scout.days") == 14
    assert state.get("tabs.scout.target_archetypes") == ["Izzet Prowess"]


def test_save_writes_to_disk(tmp_prefs):
    state = UIState.instance()
    state.set("global.format", "Standard")
    state.flush()  # synchronous save for tests
    data = json.loads(tmp_prefs.read_text())
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_load_preserves_unrelated_prefs(tmp_prefs):
    # Existing preferences (formats, api_key) must not be clobbered
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "anthropic_api_key": "sk-test",
    }))
    state = UIState.instance()
    state.set("global.format", "Standard")
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data["anthropic_api_key"] == "sk-test"
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_corrupt_json_falls_back_to_empty_state(tmp_prefs):
    tmp_prefs.write_text("{not valid json}")
    state = UIState.instance()
    # Load failure is silent; get returns defaults
    assert state.get("anything", default="fallback") == "fallback"


def test_corrupt_ui_state_key_does_not_kill_other_prefs(tmp_prefs):
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "ui_state": "not-a-dict",  # corrupt
    }))
    state = UIState.instance()
    # ui_state slot recovers, formats unaffected on save
    state.set("global.format", "Standard")
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data["ui_state"]["global"]["format"] == "Standard"


def test_reset_clears_ui_state_only(tmp_prefs):
    tmp_prefs.write_text(json.dumps({
        "formats": ["standard"],
        "ui_state": {"global": {"format": "Standard"}},
    }))
    state = UIState.instance()
    state.reset()
    state.flush()
    data = json.loads(tmp_prefs.read_text())
    assert data["formats"] == ["standard"]
    assert data.get("ui_state", {}) == {}


def test_instance_returns_same_object(tmp_prefs):
    """Singleton contract: repeated .instance() calls return the same object."""
    a = UIState.instance()
    b = UIState.instance()
    assert a is b
