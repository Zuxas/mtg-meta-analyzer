"""Tests for gui/tabs/heatmap_tab.py toolbar grouping (GR-5).

GR-5 gate (harness/handoffs/mta-gui-polish-2026-07-10.md):
  "widget tree contains the three named groups; screenshot shows visual
  separation; at most ONE visible control whose label CONTAINS the word
  'Refresh' per screen -- if two remain (any spelling), each must carry a
  tooltip naming its distinct scope, and the pair must be justified in the
  wave notes."

No pytest-qt plugin is installed in this environment -- these tests follow
the established offscreen-Qt pattern (QT_QPA_PLATFORM=offscreen env fixture
+ QApplication.instance() or QApplication([])) from tests/test_puzzles_tab.py
and tests/test_dashboard_filter_row.py.
"""
import pytest

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame, QMainWindow,
)


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _make_tab(app):
    from gui.tabs.heatmap_tab import HeatmapTab
    return HeatmapTab()


# ---------------------------------------------------------------------------
# Widget-tree asserts for the three named groups
# ---------------------------------------------------------------------------

def test_toolbar_has_three_named_clusters(app):
    """The toolbar must contain three distinctly-named group containers:
    Sources, Analysis, Export."""
    tab = _make_tab(app)

    sources  = tab.findChild(QWidget, "heatmap_group_sources")
    analysis = tab.findChild(QWidget, "heatmap_group_analysis")
    export   = tab.findChild(QWidget, "heatmap_group_export")

    assert sources is not None, "Sources cluster not found in widget tree"
    assert analysis is not None, "Analysis cluster not found in widget tree"
    assert export is not None, "Export cluster not found in widget tree"

    # Each cluster carries a visible header label naming the group.
    assert tab.findChild(QLabel, "heatmap_group_sources_label").text() == "Sources"
    assert tab.findChild(QLabel, "heatmap_group_analysis_label").text() == "Analysis"
    assert tab.findChild(QLabel, "heatmap_group_export_label").text() == "Export"


def test_clusters_actually_contain_the_right_buttons(app):
    """Guard against a 'hollow group' false pass: the named containers must
    actually parent the buttons the gripe called out, split exactly as the
    handoff describes (sources / analysis / I/O), not just exist as empty
    labeled boxes."""
    tab = _make_tab(app)

    sources  = tab.findChild(QWidget, "heatmap_group_sources")
    analysis = tab.findChild(QWidget, "heatmap_group_analysis")
    export   = tab.findChild(QWidget, "heatmap_group_export")

    def _texts(container):
        return {b.text() for b in container.findChildren(QPushButton)}

    assert _texts(sources) == {
        "Real Match Data (DB)", "MTGDecks Live", "Use Cached",
    }
    assert _texts(analysis) == {"Gauntlet", "Equilibrium"}
    assert _texts(export) == {"Export Decks", "Paste Data", "Export"}

    # And the actual button objects the tab wires up elsewhere are the same
    # instances living inside these groups (not lookalike duplicates).
    assert tab._combined_btn.parent() is sources
    assert tab._fetch_btn.parent() is sources
    assert tab._cache_btn.parent() is sources
    assert tab._gauntlet_btn.parent() is analysis
    assert tab._eq_btn.parent() is analysis
    assert tab._build_gauntlet_btn.parent() is export
    assert tab._paste_btn.parent() is export
    assert tab._export_btn.parent() is export


def test_clusters_are_visually_separated(app):
    """Proxy for the gate's 'screenshot shows visual separation': exactly
    three theme-consistent VLine separators sit in the toolbar, one before
    each cluster (Format/Timeframe | Sources | Analysis | Export)."""
    tab = _make_tab(app)

    vlines = [
        f for f in tab.findChildren(QFrame)
        if f.frameShape() == QFrame.Shape.VLine
    ]
    assert len(vlines) == 3, (
        f"expected 3 cluster separators, found {len(vlines)}"
    )


# ---------------------------------------------------------------------------
# "at most ONE visible Refresh-labeled control per screen"
# ---------------------------------------------------------------------------

def test_heatmap_tab_itself_has_no_refresh_labeled_control(app):
    """The Heatmap tab's own toolbar must not introduce a control whose
    label contains 'Refresh' -- the only 'Refresh'-ish control anywhere near
    this screen is the header's global reload button (main_window.py),
    which is covered separately (see test_header_reload_label_avoids_refresh
    below) and is exactly ONE per screen."""
    tab = _make_tab(app)

    hits = [
        w.text() for w in tab.findChildren((QPushButton, QLabel))
        if "refresh" in w.text().lower()
    ]
    assert hits == [], f"unexpected 'Refresh'-labeled control(s) on Heatmap tab: {hits}"


def test_header_reload_label_avoids_refresh():
    """GR-5 disambiguation: the main-window header's global reload button
    (always visible above every tab, including Heatmap and Dashboard) must
    not say 'Refresh', so it never collides with a tab's own Refresh button
    (e.g. Dashboard's filter-row Refresh, which re-runs the query using that
    tab's selected filters -- a different action from a bare DB reload).

    Checked via the module-level HEADER_RELOAD_LABEL constant rather than
    constructing a real MainWindow: MainWindow.__init__ wires up the DB,
    background workers, Win32 global hotkeys, and the MTGA log watcher,
    which is too heavy/fragile for a unit test (same reasoning documented
    in tests/test_main_window_geometry.py for the GR-1 window-geometry
    functions)."""
    from gui.main_window import HEADER_RELOAD_LABEL
    assert "refresh" not in HEADER_RELOAD_LABEL.lower()


def test_dashboard_refresh_button_is_unaffected(app):
    """Regression guard: the header rename must NOT be paired with also
    renaming the Dashboard filter-row's own Refresh button -- GR-1's gate
    explicitly requires the literal string 'Refresh' to render on that row
    at 1200x700 (tests/test_dashboard_filter_row.py). Renaming it too would
    silently break GR-1's screenshot gate without failing any existing test
    (that test checks tab._refresh_btn by attribute/width, never by text)."""
    from gui.tabs.dashboard import DashboardTab
    tab = DashboardTab()
    assert tab._refresh_btn.text() == "Refresh"


# ---------------------------------------------------------------------------
# Toolbar wrap fix (council-seat-46.md refutation of GR-5): at 1200x700 the
# old QHBoxLayout kept all three clusters on one row and pushed 5 of 8
# buttons past the right edge, unreachable, with no wrap and no scrollbar.
# The toolbar is now a FlowLayout (gui/widgets/flow_layout.py, same fix as
# the Dashboard filter row for GR-1) so clusters wrap onto additional lines
# instead -- each cluster is a single atomic QWidget, so FlowLayout only
# ever wraps BETWEEN clusters, never splitting one open mid-row.
# ---------------------------------------------------------------------------

def _make_windowed_heatmap(app, width, height):
    """Build a HeatmapTab inside a real QMainWindow sized to (width, height)
    and pump the event loop so layouts settle -- mirrors
    tests/test_dashboard_filter_row.py::_make_windowed_dashboard."""
    win = QMainWindow()
    tab = _make_tab(app)
    win.setCentralWidget(tab)
    win.resize(width, height)
    win.show()
    for _ in range(3):
        app.processEvents()
    return win, tab


def test_toolbar_buttons_reachable_at_1200x700(app):
    """At 1200x700, every one of the 8 clustered toolbar buttons must be
    visible, rendered at its full sizeHint (never compressed/elided), and
    positioned with its right edge inside the window -- i.e. reachable, not
    clipped off-window. Bound against the window's *actual* rendered width
    (as tests/test_dashboard_filter_row.py does with win.width(), not a
    hardcoded literal): HeatmapTab's legend row has its own wide minimum
    width unrelated to this toolbar, which keeps Qt from ever honoring a
    literal 1200px window for this tab -- Qt clamps resize() up to the
    widget tree's minimum instead of clipping it. That pre-existing legend
    behavior is out of scope for the toolbar-wrap fix under test here; what
    matters is that no button is pushed beyond whatever the real viewport
    turns out to be.
    """
    win, tab = _make_windowed_heatmap(app, 1200, 700)

    sources  = tab.findChild(QWidget, "heatmap_group_sources")
    analysis = tab.findChild(QWidget, "heatmap_group_analysis")
    export   = tab.findChild(QWidget, "heatmap_group_export")
    assert sources is not None, "Sources cluster not found"
    assert analysis is not None, "Analysis cluster not found"
    assert export is not None, "Export cluster not found"

    all_buttons = []
    for cluster in (sources, analysis, export):
        all_buttons.extend(cluster.findChildren(QPushButton))
    assert len(all_buttons) == 8, (
        f"expected all 8 clustered buttons, found {len(all_buttons)}"
    )

    for btn in all_buttons:
        assert btn.isVisible(), f"{btn.text()!r} is not visible"
        hint = btn.sizeHint()
        assert btn.width() >= hint.width(), (
            f"{btn.text()!r}: width {btn.width()} < sizeHint {hint.width()} "
            "(compressed below natural size -- text would clip)"
        )
        top_left = btn.mapTo(win, QPoint(0, 0))
        right_edge = top_left.x() + btn.width()
        assert right_edge <= win.width(), (
            f"{btn.text()!r}: right edge {right_edge} exceeds window width "
            f"{win.width()} -- button is off-window/unreachable"
        )

    # The right-edge check above is NOT enough on its own: Qt clamps this
    # bare QMainWindow's resize() up to whatever the widget tree's
    # minimumSizeHint requires (see this test's docstring), so "every
    # button's right edge <= win.width()" would hold trivially even under
    # the OLD unwrapped QHBoxLayout, which never clips in this harness --
    # it just makes the window wider. The thing that actually distinguishes
    # the fix is that the toolbar genuinely WRAPS at this width: with the
    # old single-row QHBoxLayout all three clusters share one y; with
    # FlowLayout the Analysis/Export clusters land on a second line.
    cluster_rows = {
        cluster.objectName(): cluster.mapTo(win, QPoint(0, 0)).y()
        for cluster in (sources, analysis, export)
    }
    assert len(set(cluster_rows.values())) >= 2, (
        f"toolbar never wrapped onto a second line -- all clusters landed "
        f"on the same row {cluster_rows} (a plain QHBoxLayout would also "
        "pass the right-edge check above, since Qt enlarges this bare "
        "QMainWindow to fit an unwrapped row rather than clipping it)"
    )

    # A cluster must not split internally mid-wrap: every button inside one
    # cluster box stays on the same visual row as its siblings.
    for cluster in (sources, analysis, export):
        rows = {
            btn.mapTo(win, QPoint(0, 0)).y()
            for btn in cluster.findChildren(QPushButton)
        }
        assert len(rows) == 1, (
            f"{cluster.objectName()}: buttons land on different rows "
            f"{sorted(rows)} -- cluster split internally mid-wrap"
        )

    win.close()
