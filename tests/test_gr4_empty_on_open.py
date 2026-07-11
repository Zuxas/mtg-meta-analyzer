"""Tests for GR-4 (empty-on-open panes): CHARTS and MATCHUP DATA tabs.

GR-4 gate (harness/handoffs/mta-gui-polish-2026-07-10.md, amended):
  "fresh open -> non-empty content with ZERO extra clicks, asserted
  programmatically (CHARTS: Figure has >=1 Axes with >=1 plotted artist;
  MATCHUP DATA: table rowCount > 0); a placeholder/empty-state render does
  NOT pass. ... Both must also not double-load when re-shown (guard with a
  one-shot flag or data-presence check)."

Real local DB (data/mtg_meta.db) has live standard-format data -- these
tests exercise the actual worker-backed load paths (real QThread + real DB
queries) end to end, same as the live-review screenshot loop, and poll the
Qt event loop until the async result lands. No pytest-qt plugin is
installed -- offscreen-Qt pattern per tests/test_heatmap_toolbar_groups.py
(QT_QPA_PLATFORM=offscreen + QApplication.instance() or QApplication([])).

UIState is isolated to a per-test tmp preferences.json (same fixture as
tests/test_ui_state.py) so these tests don't depend on -- or mutate -- the
developer's real sticky-state file (tabs.charts.chart_type etc. would
otherwise make first-show behavior depend on whatever the app was last
left showing).

IMPORTANT -- every test MUST call the _quiesce() helper (below) before
returning (a `finally` block, run even on assertion failure), never a bare
tab.cleanup(). Both ChartsTab.__init__ (archetype combo refresh) and the
GR-4 auto-load/auto-generate hook spin up a real background QThread. Qt
6.10 made it fatal (hard process crash, not a catchable exception) to
destroy a QThread wrapper while its thread is still running -- see
gui/worker_utils.py's stop_worker() docstring. Once the test function
returns, `tab` (and any worker refs it holds) can be garbage collected at
any moment, so SOME cleanup call is mandatory -- but calling
tab.cleanup() directly while a worker is still mid-flight forces
stop_worker() down its QThread.terminate() force-kill fallback, which can
corrupt shared Qt/interpreter state badly enough to crash a LATER,
unrelated test instead of this one (observed empirically while authoring
this file: the whole suite died with no traceback deep inside an
unrelated module; excluding this file made it green again). _quiesce()
pumps the event loop until every worker has ACTUALLY finished first, so
cleanup()'s fast wait()-only path is what runs, never terminate().
"""
import time

import pytest

from PyQt6.QtWidgets import QApplication, QMainWindow, QTableWidget


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Redirect UIState to a per-test preferences.json (same fixture as
    tests/test_ui_state.py) -- these tests must not depend on, or write
    into, the developer's real sticky-state file."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


def _pump_until(app, predicate, timeout_s=20.0, interval_s=0.02) -> bool:
    """Pump the Qt event loop until predicate() is True or timeout expires.
    Needed because the auto-load/auto-generate work happens on a background
    QThread and pytest runs no Qt event loop of its own."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _figure_has_plotted_artist(fig) -> bool:
    """True if any Axes on the figure actually has drawn content (line,
    scatter/imshow collection, bar patch, ...) -- NOT just an empty axes
    with ticks cleared, which is what the 'Loading...' placeholder state
    looks like (see ChartCanvas.show_message)."""
    return any(
        ax.get_lines() or ax.collections or ax.patches or ax.images
        for ax in fig.axes
    )


def _tab_workers(tab) -> list:
    """Every QThread worker a ChartsTab/HeatmapTab might be holding a
    reference to right now (the archetype-refresh list on ChartsTab, its
    canvas' current chart-loader, and the heatmap's single active loader)."""
    workers = list(getattr(tab, "_workers", []) or [])
    single = getattr(tab, "_worker", None)
    if single is not None:
        workers.append(single)
    canvas = getattr(tab, "_canvas", None)
    if canvas is not None:
        cw = getattr(canvas, "_worker", None)
        if cw is not None:
            workers.append(cw)
    return workers


def _all_workers_idle(tab) -> bool:
    for w in _tab_workers(tab):
        try:
            if w.isRunning():
                return False
        except RuntimeError:
            pass  # underlying C++ object already gone -- definitely not running
    return True


def _quiesce(app, tab, timeout_s=20.0) -> None:
    """Pump the event loop until every worker the tab is holding a reference
    to has actually finished, THEN call tab.cleanup(). Calling cleanup()
    while a worker is still mid-flight forces worker_utils.stop_worker()
    down its QThread.terminate() fallback path -- a hard kill that can
    corrupt Qt/Python interpreter state in a way that doesn't crash this
    test but a LATER, unrelated one instead (observed empirically: the
    process would crash with no traceback deep into a different test file
    entirely; excluding this module made the whole suite green again,
    which is what pointed at improperly-terminated background threads
    rather than anything in the tests that were actually failing). Always
    prefer draining naturally over relying on stop_worker()'s force-kill."""
    _pump_until(app, lambda: _all_workers_idle(tab), timeout_s=timeout_s)
    tab.cleanup()


# ---------------------------------------------------------------------------
# CHARTS (gui/tabs/charts.py)
# ---------------------------------------------------------------------------

def test_charts_tab_nonempty_on_first_show(app, tmp_prefs):
    """Fresh open (no sticky state) -> Meta Share auto-generates with zero
    clicks: Figure ends up with >=1 Axes carrying >=1 plotted artist."""
    from gui.tabs.charts import ChartsTab
    tab = ChartsTab()
    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        ok = _pump_until(app, lambda: _figure_has_plotted_artist(tab._canvas._fig))
        assert ok, "chart did not auto-populate within timeout"
        assert len(tab._canvas._fig.axes) >= 1
        assert _figure_has_plotted_artist(tab._canvas._fig)
        # The canvas' own empty/placeholder overlay ("Select a chart type
        # and click Generate") must not still be showing -- a placeholder
        # render does not satisfy the gate.
        assert not tab._canvas._overlay.isVisible()
    finally:
        _quiesce(app, tab)
        win.close()


def test_charts_tab_defaults_to_meta_share_with_no_sticky_state(app, tmp_prefs):
    """With nothing persisted yet, the combo's own default (index 0) is
    Meta Share -- the gate's 'or default Meta Share' half."""
    from gui.tabs.charts import ChartsTab
    tab = ChartsTab()
    try:
        assert tab._type.currentText() == "Meta Share"
    finally:
        _quiesce(app, tab)


def test_charts_tab_falls_back_to_meta_share_when_restored_type_has_no_archetype(
    app, tmp_prefs
):
    """If sticky state restores a Trend-family chart type but no archetype
    is available/selected yet, auto-generate must fall back to Meta Share
    instead of firing into 'Enter an archetype name.' with nothing
    plotted -- the fallback half of the GR-4 gate ('or default Meta
    Share')."""
    from gui.state import UIState
    from gui.state_keys import CHARTS_CHART_TYPE
    UIState.instance().set(CHARTS_CHART_TYPE, "Archetype Trend")

    from gui.tabs.charts import ChartsTab
    tab = ChartsTab()
    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        ok = _pump_until(app, lambda: _figure_has_plotted_artist(tab._canvas._fig))
        assert ok, "chart did not auto-populate within timeout"
        assert tab._type.currentText() == "Meta Share"
    finally:
        _quiesce(app, tab)
        win.close()


def test_charts_tab_no_double_load_on_reshow(app, tmp_prefs):
    """Switching away from CHARTS and back must NOT re-trigger a second
    auto-generate (the gate's 'must not double-load when re-shown')."""
    from gui.tabs.charts import ChartsTab
    tab = ChartsTab()

    calls = {"n": 0}
    orig = tab._auto_generate_on_first_show

    def _wrapped():
        calls["n"] += 1
        orig()

    tab._auto_generate_on_first_show = _wrapped

    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        app.processEvents()
        assert calls["n"] == 1

        win.hide()
        app.processEvents()
        win.show()
        app.processEvents()
        assert calls["n"] == 1, "auto-generate fired again on re-show -- double-load"
        # Let the (real, background) auto-generate worker actually finish
        # before teardown -- see module docstring.
        _pump_until(app, lambda: _figure_has_plotted_artist(tab._canvas._fig))
    finally:
        _quiesce(app, tab)
        win.close()


# ---------------------------------------------------------------------------
# MATCHUP DATA (gui/tabs/heatmap_tab.py)
# ---------------------------------------------------------------------------

def test_heatmap_tab_nonempty_on_first_show(app, tmp_prefs):
    """Fresh open -> non-empty grid with zero clicks: table rowCount > 0."""
    from gui.tabs.heatmap_tab import HeatmapTab
    tab = HeatmapTab()
    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        def _loaded():
            tbl = tab.findChild(QTableWidget)
            return tbl is not None and tbl.rowCount() > 0

        ok = _pump_until(app, _loaded)
        assert ok, "heatmap did not auto-populate within timeout"
        tbl = tab.findChild(QTableWidget)
        assert tbl.rowCount() > 0
        # The status-label empty/placeholder state must not still be
        # showing -- a placeholder render does not satisfy the gate.
        assert tab._grid_container.isVisible()
        assert not tab._status.isVisible()
    finally:
        _quiesce(app, tab)
        win.close()


def test_heatmap_tab_auto_load_prefers_cache_when_available(app, tmp_prefs):
    """If a cached MTGDecks snapshot exists for the current format, the
    first-show auto-load must use 'Use Cached' ('cache'); otherwise it
    falls back to 'Real Match Data (DB)' ('combined')."""
    from gui.tabs.heatmap_tab import HeatmapTab
    from db.matchup_queries import get_last_updated

    tab = HeatmapTab()
    fmt = tab._fmt.currentText()
    has_cache = get_last_updated(fmt) is not None

    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        def _settled():
            return (
                tab._load_source in ("cache", "combined")
                and not tab._progress.isVisible()
            )

        ok = _pump_until(app, _settled)
        assert ok, "heatmap load did not settle within timeout"
        expected = "cache" if has_cache else "combined"
        assert tab._load_source == expected
    finally:
        _quiesce(app, tab)
        win.close()


def test_heatmap_tab_no_double_load_on_reshow(app, tmp_prefs):
    """Switching away from MATCHUP DATA and back must NOT re-trigger a
    second auto-load (the gate's 'must not double-load when re-shown')."""
    from gui.tabs.heatmap_tab import HeatmapTab
    tab = HeatmapTab()

    calls = {"n": 0}
    orig = tab._auto_load_on_first_show

    def _wrapped():
        calls["n"] += 1
        orig()

    tab._auto_load_on_first_show = _wrapped

    win = QMainWindow()
    win.setCentralWidget(tab)
    win.show()
    try:
        app.processEvents()
        assert calls["n"] == 1

        win.hide()
        app.processEvents()
        win.show()
        app.processEvents()
        assert calls["n"] == 1, "auto-load fired again on re-show -- double-load"
        # Let the (real, background) auto-load worker actually finish before
        # teardown -- see module docstring.
        _pump_until(app, lambda: not tab._progress.isVisible())
    finally:
        _quiesce(app, tab)
        win.close()
