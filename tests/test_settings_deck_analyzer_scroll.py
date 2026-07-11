"""Tests for the QScrollArea wrap applied to gui/tabs/settings.py::SettingsTab
and gui/tabs/deck_analyzer.py::DeckAnalyzerTab (GUI polish Wave C follow-up
to tests/test_event_optimizer_scroll.py).

Same root cause as EventWidget (see that file's module docstring): each tab
stacked all of its content in a single un-scrolled top-level QVBoxLayout
directly on `self`, so its full unscrolled height became a floor on
MainWindow's minimumSizeHint() (Qt sizes a QTabWidget page for the largest
tab among ALL its children, not just the visible one). Measured standalone
before the fix: SettingsTab ~707-878px (machine-dependent), DeckAnalyzerTab
~631px.

Fix: identical pattern to EventWidget -- build all existing content into a
plain QWidget (`content`), then wrap it in a QScrollArea
(setWidgetResizable(True), horizontal scrollbar policy AlwaysOff) sized to
`self` via a thin outer QVBoxLayout. Every existing addWidget/addLayout call
is unchanged -- only the parent layout instance changed from `self` to
`content`.

GATES (as assigned):
  1. Each tab's standalone minimumSizeHint().height() <= 400.
  2. All existing child widgets/groupboxes still present inside the scroll
     area (nothing dropped by the wrap).
  3. No horizontal scrollbar needed at >=1200px width.
  4. SettingsTab's api_key_changed signal and DeckAnalyzerTab's on_simulate
     callback wiring are untouched by the wrap.
  5. MainWindow (full offscreen construction) minimumSizeHint().height()
     <= 900 -- covered by
     tests/test_event_optimizer_scroll.py::test_mainwindow_min_height_meets_original_900_target
     (flipped from xfail to a normal passing assertion in this same change).

Offscreen-Qt pattern per tests/test_event_optimizer_scroll.py /
tests/test_gr4_empty_on_open.py: QT_QPA_PLATFORM=offscreen, no pytest-qt
plugin. DeckAnalyzerTab starts a DataLoadWorker at construction time
(_refresh_archetypes in __init__) -- it must be drained to completion
before cleanup()/teardown, since Qt 6.10 hard-crashes the process (not a
catchable exception) if a QThread wrapper is destroyed while still running.
SettingsTab does not start any worker at construction (_refresh_storage /
_refresh_ml_status / _refresh_arch_status are synchronous DB reads), so its
tests need no draining.
"""
import time

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QGroupBox, QScrollArea, QWidget


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _pump_until(app, predicate, timeout_s=20.0, interval_s=0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _workers_idle(widget: QWidget) -> bool:
    for wdg in widget.findChildren(QWidget) + [widget]:
        candidates = list(getattr(wdg, "_workers", []) or [])
        single = getattr(wdg, "_worker", None)
        if single is not None:
            candidates.append(single)
        for w in candidates:
            try:
                if w.isRunning():
                    return False
            except RuntimeError:
                pass  # underlying C++ object already gone -- not running
    return True


def _first_scroll_area(widget: QWidget) -> QScrollArea:
    scroll_areas = widget.findChildren(QScrollArea)
    assert len(scroll_areas) >= 1, f"no QScrollArea found in {type(widget).__name__}"
    return scroll_areas[0]


# ---------------------------------------------------------------------------
# SettingsTab
# ---------------------------------------------------------------------------

_SETTINGS_GROUPBOX_TITLES = {
    "Formats to Track",
    "Data Window",
    "Auto-Update Frequency",
    # NOTE: a "Storage" QGroupBox is instantiated in _build_ui (store_box)
    # but never added to any layout -- a pre-existing orphaned-widget bug
    # (confirmed present before this QScrollArea wrap, via `git diff` on
    # this file: the wrap touches none of the store_box lines). It and its
    # children (storage label + backfill/refresh/dedup buttons) are
    # garbage-collected once _build_ui returns and never appear in the
    # widget tree at all. Unrelated to and out of scope for this item
    # (files: settings.py/deck_analyzer.py QScrollArea wrap only) -- not
    # fixed here, just accurately reflected in this test's expectations.
    "ML Models (Advanced Analytics)",
    "Archetype Manager",
    "AI Assistant (optional)",
}


def test_settings_tab_min_height_under_400(app):
    """Gate 1: SettingsTab minimumSizeHint().height() <= 400 after the wrap
    (was ~707-878px standalone before)."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        h = w.minimumSizeHint().height()
        assert h <= 400, f"SettingsTab minimum height {h} still exceeds 400"
    finally:
        w.cleanup()


def test_settings_tab_has_scroll_area_wrapping_content(app):
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        scroll = _first_scroll_area(w)
        assert scroll.widgetResizable() is True
        assert (
            scroll.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        ), "content must not grow a horizontal scrollbar at wide widths"
    finally:
        w.cleanup()


def test_settings_tab_groupboxes_survive_inside_scroll_area(app):
    """Gate 2: all pre-existing QGroupBoxes still exist, specifically as
    descendants of the QScrollArea -- proves no content was dropped."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        scroll = _first_scroll_area(w)
        boxes = scroll.findChildren(QGroupBox)
        titles = {b.title() for b in boxes}
        assert titles == _SETTINGS_GROUPBOX_TITLES, (
            f"expected {_SETTINGS_GROUPBOX_TITLES}, found {titles}"
        )
    finally:
        w.cleanup()


def test_settings_tab_no_horizontal_scrollbar_needed_at_1200_width(app):
    """Gate 3: content is narrower than 1200px, so the (AlwaysOff) horizontal
    scrollbar is never forced to clip anything at a normal-monitor width."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        scroll = _first_scroll_area(w)
        content_w = scroll.widget().minimumSizeHint().width()
        assert content_w <= 1200, (
            f"SettingsTab content minimum width {content_w} would need "
            "horizontal scrolling at 1200px"
        )
    finally:
        w.cleanup()


def test_settings_tab_api_key_changed_signal_still_wired(app, tmp_path, monkeypatch):
    """Gate 4: api_key_changed still fires from _save() after the wrap
    (pure re-parenting of the layout must not touch signal wiring)."""
    from gui.tabs import settings as settings_mod

    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr(settings_mod, "_PREFS_PATH", str(prefs_path))

    w = settings_mod.SettingsTab()
    try:
        received = []
        w.api_key_changed.connect(received.append)
        w._api_key_input.setText("sk-ant-test-key")
        w._save()
        assert received == ["sk-ant-test-key"]
    finally:
        w.cleanup()


# ---------------------------------------------------------------------------
# DeckAnalyzerTab
# ---------------------------------------------------------------------------

def test_deck_analyzer_tab_min_height_under_400(app):
    """Gate 1: DeckAnalyzerTab minimumSizeHint().height() <= 400 after the
    wrap (was ~631px standalone before)."""
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    w = DeckAnalyzerTab()
    try:
        h = w.minimumSizeHint().height()
        assert h <= 400, f"DeckAnalyzerTab minimum height {h} still exceeds 400"
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()


def test_deck_analyzer_tab_has_scroll_area_wrapping_content(app):
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    w = DeckAnalyzerTab()
    try:
        scroll = _first_scroll_area(w)
        assert scroll.widgetResizable() is True
        assert (
            scroll.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        ), "content must not grow a horizontal scrollbar at wide widths"
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()


def test_deck_analyzer_tab_groupbox_survives_inside_scroll_area(app):
    """Gate 2: the pre-existing 'Flex / Tech Recommendations' QGroupBox
    still exists, specifically as a descendant of the QScrollArea."""
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    w = DeckAnalyzerTab()
    try:
        scroll = _first_scroll_area(w)
        boxes = scroll.findChildren(QGroupBox)
        titles = {b.title() for b in boxes}
        assert titles == {"Flex / Tech Recommendations"}
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()


def test_deck_analyzer_tab_no_horizontal_scrollbar_needed_at_1200_width(app):
    """Gate 3: content is narrower than 1200px."""
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    w = DeckAnalyzerTab()
    try:
        scroll = _first_scroll_area(w)
        content_w = scroll.widget().minimumSizeHint().width()
        assert content_w <= 1200, (
            f"DeckAnalyzerTab content minimum width {content_w} would need "
            "horizontal scrolling at 1200px"
        )
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()


def test_deck_analyzer_tab_on_simulate_wiring_still_works(app):
    """Gate 4: the on_simulate callback wiring (Simulate button -> callback
    with the pasted decklist) must be untouched by the wrap."""
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    calls = []

    def _on_simulate(text, source, format_hint=None):
        calls.append((text, source, format_hint))

    w = DeckAnalyzerTab(on_simulate=_on_simulate)
    try:
        assert hasattr(w, "_simulate_btn"), "Simulate button not created when on_simulate is set"
        w._deck_input.setPlainText("Deck\n4 Lightning Bolt")
        w._on_send_to_simulate()
        assert len(calls) == 1
        text, source, format_hint = calls[0]
        assert "Lightning Bolt" in text
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()


def test_deck_analyzer_tab_no_simulate_button_without_callback(app):
    """Sanity check that the conditional simulate-button wiring (guarded by
    `if self._on_simulate is not None`) still behaves as before the wrap."""
    from gui.tabs.deck_analyzer import DeckAnalyzerTab

    w = DeckAnalyzerTab()
    try:
        assert not hasattr(w, "_simulate_btn")
    finally:
        _pump_until(app, lambda: _workers_idle(w))
        w.cleanup()
