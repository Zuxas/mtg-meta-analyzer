"""Tests for the EventWidget QScrollArea wrap (GUI polish Wave C side-task,
see harness/handoffs/mta-gui-polish-2026-07-10.md min-height diagnosis at
scratchpad/bob-runs/.../evidence/wave-b/min-height-diagnosis.md).

Root cause: gui/tabs/event_optimizer.py::EventWidget stacked its left-column
inputs (3 QGroupBoxes + 3 buttons + a status row) in a single un-scrolled
QVBoxLayout, measured at 763px minimumSizeHint height alone -- and because
Qt's QTabWidget sizes each tab widget for the LARGEST page among ALL its
children (not just the visible one), buried 3 QTabWidget levels deep
(MainWindow -> outer tabs -> Tournament inner tabs -> TournamentPrepTab's
own inner tabs), that 763px became the app-wide minimum-height floor.

Fix: wrap the left column in a QScrollArea (setWidgetResizable(True),
matching the established pattern used elsewhere in gui/ -- see
gui/tabs/dashboard.py / gui/tabs/event_hub_tab.py), so the panel scrolls
instead of forcing the whole window taller.

Offscreen-Qt pattern per tests/test_heatmap_toolbar_groups.py /
tests/test_gr4_empty_on_open.py: QT_QPA_PLATFORM=offscreen, no pytest-qt
plugin (QApplication.instance() or QApplication([])). Every test that
constructs a widget owning background QThread workers drains them to
completion (see _quiesce) before any cleanup() call -- Qt 6.10 makes it a
fatal process crash (not a catchable exception) to destroy a QThread
wrapper while its thread is still running.

GATE (as assigned):
  1. EventWidget (or its containing page) minimumSizeHint().height() <= 400
     after the wrap.                                                -> MET (measured 321)
  2. The 3 QGroupBoxes still exist inside the scroll area (no content
     dropped).                                                      -> MET
  3. MainWindow-level: constructing the full MainWindow offscreen,
     minimumSizeHint().height() <= 900.                             -> MET (see below)

Gate 3 update (follow-up, Wave C): after this EventWidget fix alone,
MainWindow's minimumSizeHint().height() measured ~1001px, not <=900. The
binding constraint moved OFF Tournament Prep (this item's scope) and onto
gui/tabs/settings.py::SettingsTab (~707-878px standalone, machine-dependent)
and gui/tabs/deck_analyzer.py::DeckAnalyzerTab (~631px standalone). A
follow-up item applied the same QScrollArea wrap to both of those tabs
(gui/tabs/settings.py, gui/tabs/deck_analyzer.py) -- MainWindow's
minimumSizeHint().height() now measures ~746px, comfortably under 900.
Test below encodes:
  - a PASSING regression guard at a loose ceiling well below the pre-fix
    ~1460px floor (would fail again if any of the three wraps were
    reverted), and
  - a PASSING gate on the original <=900 target, now met.
"""
import time

import pytest

from PyQt6.QtWidgets import QApplication, QGroupBox, QScrollArea, QWidget


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect UIState to a per-test preferences.json (same fixture as
    tests/test_ui_state.py / tests/test_gr4_empty_on_open.py) -- these
    tests must not depend on, or write into, the developer's real
    sticky-state file."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


def _pump_until(app, predicate, timeout_s=20.0, interval_s=0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _all_workers_idle(root: QWidget) -> bool:
    """True once every background worker any descendant widget of `root`
    is holding a reference to (the `_workers` list / `_worker` singleton
    pattern used across gui/tabs and gui/widgets) has actually finished.
    Workers here are typically parent-less QThread wrappers (see
    DataLoadWorker usage in event_optimizer.py), so they can't be found
    via QObject.findChildren -- walk the widget tree's own attributes
    instead, same approach as tests/test_gr4_empty_on_open.py's
    _tab_workers/_all_workers_idle but generalized across every widget in
    the tree (MainWindow owns ~16 tabs, each with its own worker refs)."""
    for wdg in root.findChildren(QWidget):
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


# ---------------------------------------------------------------------------
# EventWidget-level gates
# ---------------------------------------------------------------------------

def test_event_widget_min_height_under_400(app, tmp_prefs):
    """Gate 1: EventWidget's minimumSizeHint().height() <= 400 after the
    QScrollArea wrap (was 763 before; measured 321 after)."""
    from gui.tabs.event_optimizer import EventWidget

    w = EventWidget()
    try:
        h = w.minimumSizeHint().height()
        assert h <= 400, f"EventWidget minimum height {h} still exceeds 400"
    finally:
        w.cleanup()


def test_event_widget_has_scroll_area_wrapping_left_column(app, tmp_prefs):
    """The left input column must actually be wrapped in a QScrollArea
    (not just coincidentally short) -- resizable, no horizontal scrollbar
    by policy (matches the established pattern: no dead right-edge gutter
    at wide viewports, per gui/tabs/dashboard.py / event_hub_tab.py)."""
    from gui.tabs.event_optimizer import EventWidget
    from PyQt6.QtCore import Qt

    w = EventWidget()
    try:
        scroll_areas = w.findChildren(QScrollArea)
        assert len(scroll_areas) >= 1, "no QScrollArea found in EventWidget"
        scroll = scroll_areas[0]
        assert scroll.widgetResizable() is True
        assert (
            scroll.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        ), "left panel must not grow a horizontal scrollbar at wide widths"
    finally:
        w.cleanup()


def test_event_widget_groupboxes_survive_inside_scroll_area(app, tmp_prefs):
    """Gate 2: all 3 QGroupBoxes (Event / Your Deck / Expected Field) still
    exist, and specifically as descendants of the QScrollArea -- proves no
    content was dropped by the wrap, and that it's the intended panel
    (not some unrelated scroll area) that holds them."""
    from gui.tabs.event_optimizer import EventWidget

    w = EventWidget()
    try:
        scroll_areas = w.findChildren(QScrollArea)
        assert len(scroll_areas) >= 1
        scroll = scroll_areas[0]
        boxes = scroll.findChildren(QGroupBox)
        titles = {b.title() for b in boxes}
        assert len(boxes) == 3, f"expected 3 group boxes inside the scroll area, found {len(boxes)}"
        assert titles == {"Event", "Your Deck", "Expected Field"}
    finally:
        w.cleanup()


# ---------------------------------------------------------------------------
# MainWindow-level gate
# ---------------------------------------------------------------------------

@pytest.fixture
def _patched_mainwindow_integrations(monkeypatch):
    """Neutralize MainWindow integrations that are orthogonal to layout but
    have real side effects if allowed to run inside a test process:

      - MtgaLogWatcher.start() fires synchronously in MainWindow.__init__
        (independent of the event loop) and its run() parses the real
        MTGA Player.log and calls scrapers.mtga_log_parser.save_matches_to_db
        -- a live DB write path. Not-pumping the event loop does NOT
        protect against this since .start() doesn't need it.
      - MainWindow._startup_check (QTimer 150ms) can pop a modal
        SetupWizard.exec() (hangs a test) or, once past setup, schedule a
        4s background network scrape.
      - MainWindow._auto_sync_mtga_on_launch (QTimer 500ms) is another
        log-parse -> DB-write path.
      - register_global_hotkeys registers real OS-level hotkeys
        (Ctrl+Shift+M/L/Q) that could collide with a live app instance
        running on the same machine.

    None of these affect widget construction or minimumSizeHint -- they're
    purely startup side-effects gated behind timers/threads that fire
    independently of layout.
    """
    import gui.mtga_log_watcher as watcher_mod
    import gui.main_window as mw_mod
    import gui.global_hotkey as hotkey_mod

    monkeypatch.setattr(watcher_mod.MtgaLogWatcher, "start", lambda self: None)
    monkeypatch.setattr(mw_mod.MainWindow, "_startup_check", lambda self: None)
    monkeypatch.setattr(
        mw_mod.MainWindow, "_auto_sync_mtga_on_launch", lambda self: None
    )
    # register_global_hotkeys is imported with a LOCAL `from gui.global_hotkey
    # import register_global_hotkeys` inside MainWindow.__init__, so it must be
    # patched at its defining module, not on gui.main_window (which never
    # binds it at module scope).
    monkeypatch.setattr(hotkey_mod, "register_global_hotkeys", lambda hotkeys: None)


@pytest.fixture
def _restore_app_theme(app):
    """MainWindow.__init__ unconditionally calls
    `theme.apply_theme(QApplication.instance())`, which mutates the
    app-WIDE QPalette and QSS stylesheet on the shared QApplication
    singleton -- the same object for the entire pytest session, since
    QApplication can't be recreated per test. Left applied, this leaks
    into later, unrelated test modules that implicitly assume an unstyled
    QApplication (observed empirically: tests/test_heatmap_low_n_tint.py's
    palette-based per-item background rendering technique passes in
    isolation but fails when run after this file in the same session,
    because the global stylesheet/palette this fixture would otherwise
    leave behind changes how QTableWidgetItem backgrounds paint). Save the
    palette/stylesheet before constructing MainWindow and restore them
    after, so THIS test still exercises the real theme (an honest
    measurement -- a live launch always has it applied) without leaking
    global app state to sibling test files. Neither gui/theme.py nor
    gui/tabs/heatmap_tab.py is touched -- this is pure test isolation
    local to this file."""
    orig_palette = app.palette()
    orig_stylesheet = app.styleSheet()
    yield
    app.setPalette(orig_palette)
    app.setStyleSheet(orig_stylesheet)


def _build_mainwindow_offscreen():
    from gui.main_window import MainWindow

    return MainWindow()


def _quiesce_mainwindow(app, win) -> None:
    _pump_until(app, lambda: _all_workers_idle(win))
    win.cleanup()


def test_mainwindow_min_height_regression_guard(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme
):
    """Regression guard (passing): before any of these fixes, EventWidget
    alone measured 763px and was the app-wide floor, plausibly explaining
    the ~1460px real-window minimum observed in the live review. After the
    EventWidget QScrollArea wrap plus the follow-up wraps on
    gui/tabs/settings.py::SettingsTab and
    gui/tabs/deck_analyzer.py::DeckAnalyzerTab, MainWindow's
    minimumSizeHint().height() measures ~746px on this machine (verified
    empirically).

    The precise "did the EventWidget wrap get reverted" catch already
    lives in test_event_widget_min_height_under_400 (a direct, robust
    321-vs-763 check on the one widget this item owns). This test's job
    is narrower: prove the app-wide number is nowhere near its old
    ~1460px floor, without being so tight that ordinary cross-machine
    variance (font fallback, DPI, offscreen-platform defaults -- the
    diagnosis doc's own SettingsTab measurement of 731 vs this session's
    707 is a 24px example of that variance on ONE tab alone) turns this
    into a flaky, everyone-blocking failure for near-zero marginal
    protection. 1300 is comfortably below the old ~1460 baseline and
    comfortably above the ~746 measured here."""
    win = _build_mainwindow_offscreen()
    try:
        h = win.minimumSizeHint().height()
        assert h < 1300, (
            f"MainWindow minimum height {h} is back near the pre-fix "
            "~1460px floor -- one of the three QScrollArea wraps may have "
            "regressed"
        )
    finally:
        _quiesce_mainwindow(app, win)


def test_mainwindow_min_height_meets_original_900_target(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme
):
    """The original GATE-AS-ASSIGNED target: MainWindow
    minimumSizeHint().height() <= 900. Previously xfail(strict=True) --
    the EventWidget wrap alone got MainWindow to ~1001px, still short of
    900 because gui/tabs/settings.py::SettingsTab and
    gui/tabs/deck_analyzer.py::DeckAnalyzerTab were the next-tallest
    standalone tabs (~707-878px and ~631px respectively). A follow-up item
    applied the same QScrollArea wrap to both of those tabs, closing the
    gap (MainWindow now measures ~746px) -- flipped to a normal passing
    assertion."""
    win = _build_mainwindow_offscreen()
    try:
        h = win.minimumSizeHint().height()
        assert h <= 900, f"MainWindow minimum height {h} exceeds 900"
    finally:
        _quiesce_mainwindow(app, win)
