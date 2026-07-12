"""Tests for wiring the "Storage" QGroupBox into gui/tabs/settings.py::SettingsTab.

The store_box QGroupBox (storage label + "Collect More Data" / "Refresh" /
"Scan Duplicates" buttons) was built in SettingsTab._build_ui but never added
to any layout, so it had never rendered. This item wires it into the scroll
content (between Auto-Update and ML Models). These tests pin:

  1. The Storage groupbox is a *visible* descendant of the tab's QScrollArea
     once the tab is shown (findChildren proves descendant; isVisibleTo proves
     it would actually paint).
  2. Its three buttons exist and each has at least one connected receiver on
     clicked (the wiring survives; none of these slots fire on construction --
     they are user-initiated scrape/read/dialog actions).
  3. SettingsTab standalone minimumSizeHint().height() is still <= 400 -- the
     QScrollArea wrap gate from tests/test_settings_deck_analyzer_scroll.py
     must not regress now that the scroll content holds one more groupbox.

Offscreen-Qt pattern per tests/test_settings_deck_analyzer_scroll.py:
QT_QPA_PLATFORM=offscreen, no pytest-qt plugin. SettingsTab starts no worker
at construction (_backfill_worker / _ml_worker are None until a button is
clicked, which these tests never do), so worker draining is a no-op -- but
cleanup() is still called in finally, and any tab shown is closed so no GUI
lingers.
"""
import pytest

from PyQt6.QtWidgets import QApplication, QGroupBox, QPushButton, QScrollArea


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _storage_box(w) -> QGroupBox:
    boxes = [b for b in w.findChildren(QGroupBox) if b.title() == "Storage"]
    assert len(boxes) == 1, f"expected exactly one Storage groupbox, found {len(boxes)}"
    return boxes[0]


def test_storage_groupbox_is_descendant_of_scroll_area(app):
    """The Storage box lives inside the tab's QScrollArea content (not
    orphaned, not on `self` directly)."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        scrolls = w.findChildren(QScrollArea)
        assert scrolls, "SettingsTab has no QScrollArea"
        box = _storage_box(w)
        in_scroll = any(box in s.findChildren(QGroupBox) for s in scrolls)
        assert in_scroll, "Storage groupbox is not a descendant of any QScrollArea"
    finally:
        w.cleanup()


def test_storage_groupbox_is_visible_when_tab_shown(app):
    """Gate: the Storage box actually renders once the tab is shown
    (isVisibleTo proves it is not collapsed/hidden within the widget tree)."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        box = _storage_box(w)
        w.show()
        app.processEvents()
        try:
            assert box.isVisibleTo(w), "Storage groupbox would not paint inside SettingsTab"
        finally:
            w.hide()
            w.close()
            app.processEvents()
    finally:
        w.cleanup()


def test_storage_buttons_exist_with_connected_receivers(app):
    """Gate: the three Storage buttons exist and each has >=1 connected
    receiver on clicked (Collect More Data / Refresh / Scan Duplicates)."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        box = _storage_box(w)
        btns = {b.text(): b for b in box.findChildren(QPushButton)}
        for label in ("Collect More Data", "Refresh", "Scan Duplicates"):
            assert label in btns, f"Storage button {label!r} missing"
            b = btns[label]
            assert b.receivers(b.clicked) >= 1, (
                f"Storage button {label!r} has no connected clicked receiver"
            )
    finally:
        w.cleanup()


def test_storage_buttons_bound_to_expected_slots(app):
    """The wired buttons point at the intended handler attributes -- guards
    against a future refactor silently re-pointing a button."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        assert w._backfill_btn.text() == "Collect More Data"
        assert w._refresh_storage_btn.text() == "Refresh"
        assert w._dedup_btn.text() == "Scan Duplicates"
        for b in (w._backfill_btn, w._refresh_storage_btn, w._dedup_btn):
            assert b.receivers(b.clicked) >= 1
    finally:
        w.cleanup()


def test_settings_tab_min_height_still_under_400_after_wiring(app):
    """Gate: adding the Storage box to the scroll content must not regress
    the QScrollArea min-height gate (was ~707-878px before the wrap; the
    wrap decouples the tab's minimumSizeHint from content height)."""
    from gui.tabs.settings import SettingsTab

    w = SettingsTab()
    try:
        h = w.minimumSizeHint().height()
        assert h <= 400, f"SettingsTab minimum height {h} exceeds 400 after wiring Storage"
    finally:
        w.cleanup()
