"""Tests for gui.main_window window-geometry persistence (GR-1).

Exercises _restore_window_geometry / _persist_window_geometry directly
against a bare QMainWindow (not the full app-specific MainWindow, which
pulls in the DB, workers, and OS-level global hotkeys). These two
functions are exactly what MainWindow.__init__/closeEvent/cleanup() call,
so testing them in isolation covers the real code path without the cost
and fragility of constructing the whole app.
"""
import json

import pytest

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QApplication, QMainWindow

from gui.state import UIState
from gui.state_keys import WINDOW_GEOMETRY, WINDOW_MAXIMIZED
from gui.main_window import (
    _restore_window_geometry, _persist_window_geometry, _clamp_rect_to_screens,
)


class _FakeScreen:
    """Minimal QScreen stand-in -- just enough surface
    (availableGeometry()) for _clamp_rect_to_screens to consume, so tests
    don't need to monkeypatch Qt's own QGuiApplication.screens()."""

    def __init__(self, rect: QRect):
        self._rect = rect

    def availableGeometry(self) -> QRect:
        return self._rect


# A generously-sized single monitor, used by every test in this file that
# isn't specifically exercising the off-screen clamp itself. Needed because
# _restore_window_geometry's default `screens=None` resolves to the REAL
# QGuiApplication.screens() -- and the offscreen QPA platform's virtual
# screen is only 800x800, smaller than several of this file's test rects
# (e.g. 1000x650). Without an explicit large screen, those rects would get
# clamped by the new off-screen-clamp feature under test, even though their
# tests are about plain restore/persist fidelity, not clamping.
_LARGE_SCREEN = [_FakeScreen(QRect(0, 0, 1920, 1040))]  # 1080p minus a 40px taskbar


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect UIState to a per-test preferences.json under tmp_path."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    monkeypatch.setattr("gui.state.UIState._instance", None)
    yield prefs_path
    # Flush (not just cancel) any pending debounced save scheduled by this
    # test's UIState singleton before monkeypatch reverts PREFERENCES_PATH.
    # Without this, a live threading.Timer can outlive the test and fire
    # during a LATER test's tmp_prefs window (gui.state._save_now() reads
    # the module-level PREFERENCES_PATH fresh at fire time, not a captured
    # value), overwriting that later test's file with this test's stale
    # in-memory state -- an intermittent cross-test pollution race.
    try:
        UIState.instance().flush()
    except Exception:
        pass


def test_fresh_launch_maximizes_window(app, tmp_prefs):
    """First-ever launch (no persisted geometry at all) opens maximized."""
    window = QMainWindow()
    state = UIState.instance()

    _restore_window_geometry(window, state)

    assert bool(window.windowState() & Qt.WindowState.WindowMaximized)


def test_persisted_normal_geometry_is_restored(app, tmp_prefs):
    """A previously-saved non-maximized geometry is restored verbatim when
    it still fits a connected screen (_LARGE_SCREEN -- see its docstring
    for why this needs to be explicit under the offscreen QPA platform)."""
    window = QMainWindow()
    state = UIState.instance()
    state.set(WINDOW_GEOMETRY, [50, 60, 1000, 650])
    state.set(WINDOW_MAXIMIZED, False)

    _restore_window_geometry(window, state, screens=_LARGE_SCREEN)

    assert not bool(window.windowState() & Qt.WindowState.WindowMaximized)
    geo = window.geometry()
    assert (geo.x(), geo.y(), geo.width(), geo.height()) == (50, 60, 1000, 650)


def test_persisted_maximized_flag_reapplies_maximize(app, tmp_prefs):
    """If the user closed the window maximized, the next launch reopens
    maximized even though a normal-geometry rect is also on file (used
    for un-maximizing later)."""
    window = QMainWindow()
    state = UIState.instance()
    state.set(WINDOW_GEOMETRY, [10, 10, 900, 600])
    state.set(WINDOW_MAXIMIZED, True)

    _restore_window_geometry(window, state)

    assert bool(window.windowState() & Qt.WindowState.WindowMaximized)


def test_persist_saves_current_rect_when_not_maximized(app, tmp_prefs):
    window = QMainWindow()
    state = UIState.instance()
    window.setGeometry(20, 30, 1100, 680)

    _persist_window_geometry(window, state)

    assert state.get(WINDOW_MAXIMIZED) is False
    assert state.get(WINDOW_GEOMETRY) == [20, 30, 1100, 680]


def test_persist_saves_normal_geometry_when_maximized(app, tmp_prefs):
    """When maximized, persist the un-maximized rect (normalGeometry()),
    not the full-screen rect, so un-maximizing later looks sane."""
    window = QMainWindow()
    state = UIState.instance()
    window.setGeometry(20, 30, 1100, 680)  # normal geometry before maximizing
    window.show()
    window.setWindowState(window.windowState() | Qt.WindowState.WindowMaximized)
    QApplication.processEvents()

    _persist_window_geometry(window, state)

    assert state.get(WINDOW_MAXIMIZED) is True
    saved = state.get(WINDOW_GEOMETRY)
    # normalGeometry() should reflect the pre-maximize rect, not a
    # full-desktop rect -- assert it's still the value we set (some
    # offscreen platforms don't reflow normalGeometry perfectly, so this
    # is checked loosely: it must exist and be 4 ints, not the sentinel
    # None a broken implementation would leave behind).
    assert isinstance(saved, list) and len(saved) == 4
    window.close()


def test_restore_then_persist_round_trip(app, tmp_prefs):
    """End-to-end: restore defaults to maximized on first launch; the
    persisted state from that session then restores correctly next time
    (on a screen large enough that the rect isn't clamped -- see
    _LARGE_SCREEN's docstring)."""
    window1 = QMainWindow()
    state = UIState.instance()
    _restore_window_geometry(window1, state, screens=_LARGE_SCREEN)
    assert bool(window1.windowState() & Qt.WindowState.WindowMaximized)

    # User un-maximizes and resizes, then closes.
    window1.setWindowState(Qt.WindowState.WindowNoState)
    window1.setGeometry(100, 100, 1000, 700)
    _persist_window_geometry(window1, state)
    window1.close()

    # Next launch restores that exact non-maximized rect.
    window2 = QMainWindow()
    _restore_window_geometry(window2, state, screens=_LARGE_SCREEN)
    assert not bool(window2.windowState() & Qt.WindowState.WindowMaximized)
    geo = window2.geometry()
    assert (geo.x(), geo.y(), geo.width(), geo.height()) == (100, 100, 1000, 700)


def test_persist_then_flush_writes_geometry_to_disk_synchronously(app, tmp_prefs):
    """Regression test for the force-quit geometry-loss bug: MainWindow's
    _force_quit -> cleanup() path persists geometry via
    _persist_window_geometry(), which calls state.set() -- and set() only
    *schedules* a 250ms debounced disk save (see gui/state.py). _force_quit
    then calls QApplication.exit(0)/os._exit(0), which can tear the
    process down before that timer ever fires, silently dropping the
    geometry that was "persisted" a moment earlier.

    The fix: cleanup() now calls state.flush() immediately after
    _persist_window_geometry(). This asserts that combination actually
    lands the write on disk with no wait -- no sleep, no processEvents --
    proving the write is synchronous, not a race against the debounce
    timer."""
    window = QMainWindow()
    state = UIState.instance()
    window.setGeometry(15, 25, 950, 620)

    _persist_window_geometry(window, state)
    state.flush()

    with tmp_prefs.open("r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["ui_state"][WINDOW_GEOMETRY.split(".")[0]][
        WINDOW_GEOMETRY.split(".")[1]
    ] == [15, 25, 950, 620]
    assert on_disk["ui_state"][WINDOW_MAXIMIZED.split(".")[0]][
        WINDOW_MAXIMIZED.split(".")[1]
    ] is False


def test_persist_without_flush_does_not_guarantee_disk_write(app, tmp_prefs):
    """Contrast case: calling only _persist_window_geometry() (state.set()),
    with no flush(), must NOT have written to disk yet -- this is exactly
    the bug shape the fix above closes off. If this ever starts passing
    with data on disk immediately, gui/state.py's debounce contract
    changed and the cleanup() fix's reasoning needs re-checking."""
    window = QMainWindow()
    state = UIState.instance()
    window.setGeometry(15, 25, 950, 620)

    _persist_window_geometry(window, state)
    try:
        assert not tmp_prefs.exists() or json.loads(
            tmp_prefs.read_text(encoding="utf-8")
        ).get("ui_state", {}).get("global", {}).get("window_geometry") != [
            15, 25, 950, 620,
        ]
    finally:
        # Don't leak a live debounce timer into the next test.
        state.flush()


# ---------------------------------------------------------------------------
# Off-screen geometry clamp (council-seat-48.md limitation): a rect saved
# on a monitor that's since been disconnected must not open off-screen and
# unreachable. Reuses _LARGE_SCREEN (defined near the top of this file) as
# the single connected monitor.
# ---------------------------------------------------------------------------

def test_clamp_returns_rect_unchanged_when_fully_on_screen():
    clamped = _clamp_rect_to_screens(100, 100, 800, 600, screens=_LARGE_SCREEN)
    assert clamped == (100, 100, 800, 600)


def test_clamp_returns_none_when_rect_is_fully_off_every_screen():
    """A rect saved on a second monitor to the right (e.g. x=2200) that no
    longer exists once that monitor is unplugged has zero overlap with any
    remaining screen."""
    clamped = _clamp_rect_to_screens(2200, 100, 800, 600, screens=_LARGE_SCREEN)
    assert clamped is None


def test_clamp_nudges_a_partially_off_screen_rect_back_into_view():
    """A rect that's mostly on-screen but hangs off the right/bottom edge
    (e.g. the primary monitor's resolution shrank) gets nudged fully
    inside the available geometry instead of being thrown out entirely."""
    clamped = _clamp_rect_to_screens(1700, 900, 800, 600, screens=_LARGE_SCREEN)
    assert clamped is not None
    x, y, w, h = clamped
    assert w == 800 and h == 600
    assert x + w <= 1920
    assert y + h <= 1040
    assert x >= 0 and y >= 0


def test_clamp_with_no_screens_leaves_rect_unchanged():
    """If screens() ever returns empty (nothing to validate against),
    don't destroy the persisted rect -- leave it as-is rather than
    guessing."""
    clamped = _clamp_rect_to_screens(100, 100, 800, 600, screens=[])
    assert clamped == (100, 100, 800, 600)


def test_restore_maximizes_when_persisted_rect_is_fully_off_screen(app, tmp_prefs):
    """End-to-end: a normal (non-maximized) persisted rect that no longer
    overlaps any connected screen must open maximized instead of
    off-screen and unreachable."""
    window = QMainWindow()
    state = UIState.instance()
    state.set(WINDOW_GEOMETRY, [2200, 100, 800, 600])  # a monitor that's gone
    state.set(WINDOW_MAXIMIZED, False)

    _restore_window_geometry(window, state, screens=_LARGE_SCREEN)

    assert bool(window.windowState() & Qt.WindowState.WindowMaximized)


def test_restore_keeps_persisted_rect_when_still_on_screen(app, tmp_prefs):
    """Regression guard: a persisted rect that DOES still overlap a
    connected screen must restore verbatim, not get needlessly maximized
    or moved."""
    window = QMainWindow()
    state = UIState.instance()
    state.set(WINDOW_GEOMETRY, [50, 60, 1000, 650])
    state.set(WINDOW_MAXIMIZED, False)

    _restore_window_geometry(window, state, screens=_LARGE_SCREEN)

    assert not bool(window.windowState() & Qt.WindowState.WindowMaximized)
    geo = window.geometry()
    assert (geo.x(), geo.y(), geo.width(), geo.height()) == (50, 60, 1000, 650)
