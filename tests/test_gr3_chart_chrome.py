"""Tests for GR-3 (matplotlib chrome clash): gui/widgets/chart_canvas.py.

GR-3 gate (harness/handoffs/mta-gui-polish-2026-07-10.md, amended):
  "programmatic checks -- legend exists with entry-per-series, legend bbox
  vs line bbox intersection empty, toolbar height <= 32px, title fully
  inside figure at 1200x700 and maximized canvas sizes. Write the checks
  as tests using ChartCanvas with synthetic multi-series data."
  Also: "REMOVING a legend is a gate FAIL, not a pass" -- these tests assert
  a legend is PRESENT (not merely that nothing crashed), with one entry per
  plotted series.

No pytest-qt plugin is installed in this environment -- these tests follow
the established offscreen-Qt pattern (QT_QPA_PLATFORM=offscreen env fixture
+ QApplication.instance() or QApplication([])) from
tests/test_heatmap_toolbar_groups.py / tests/test_gr4_empty_on_open.py.

Worker-draining note (see tests/test_gr4_empty_on_open.py's module
docstring for why this matters): every test below feeds synthetic data
directly into ChartCanvas's internal `draw_from_data` / `_draw_meta_share` /
`_draw_compare` / `_draw_trend` methods, NOT the public `plot_*` entry
points (`plot_meta_share`, `plot_trend`, `plot_compare`, ...) -- those
`_draw_*` methods are pure/synchronous (no DB query, no QThread). Only the
public `plot_*` wrappers spawn a background loader via `_start_worker`. So
none of these tests ever start a QThread and there is nothing to drain
before teardown -- a plain `.close()`/`.deleteLater()` is sufficient here.
"""
import pytest

from PyQt6.QtWidgets import QApplication
from matplotlib.transforms import Bbox


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    # Deliberately does NOT call theme.apply_theme() -- no other test file in
    # this suite does (QApplication is a process-wide singleton across every
    # test file in the session, so applying the app-level stylesheet here
    # would leak into unrelated tests run afterward, e.g.
    # tests/test_heatmap_low_n_tint.py explicitly relies on the app's
    # stylesheet being empty because a QTableWidget item's setBackground()
    # is fragile under the global QSS -- confirmed by reproducing that
    # test's failure when this fixture applied the theme first). None of
    # this file's assertions need the real app-wide QSS: the toolbar's
    # <=32px height comes from ChartCanvas's own setFixedHeight() call in
    # code (theme.CHART_TOOLBAR_MAX_H), not from the stylesheet, and the
    # legend/title bbox checks are pure matplotlib rendering.
    import matplotlib
    matplotlib.use("QtAgg")
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Synthetic multi-series data builders
# ---------------------------------------------------------------------------

N_ARCHETYPES = 6
N_WEEKS = 6


def _week_keys():
    return [f"2026-0{i + 1}-01" for i in range(N_WEEKS)]


def _fetch_chart_data_shape(n=N_ARCHETYPES):
    """Matches fetch_chart_data()'s return shape, consumed by draw_from_data."""
    weeks = _week_keys()
    archetypes = [f"Archetype {i}" for i in range(n)]
    return {
        "archetypes": archetypes,
        "meta_data": {a: {w: 0.05 + 0.01 * i for w in weeks}
                      for i, a in enumerate(archetypes)},
        "winpct_data": {a: {w: 0.45 + 0.01 * i for w in weeks}
                        for i, a in enumerate(archetypes)},
        "sample_data": {a: {w: 10 + i for w in weeks}
                        for i, a in enumerate(archetypes)},
        "all_weeks": set(weeks),
        "format_name": "standard",
        "granularity": "weekly",
    }


def _meta_share_shape():
    """Matches _MetaShareLoader/_CompareLoader's emitted dict shape, consumed
    by _draw_meta_share / _draw_compare."""
    weeks = _week_keys()
    archetypes = [f"Archetype {i}" for i in range(N_ARCHETYPES)]
    return {
        "archetypes": archetypes,
        "arch_data": {a: {w: 0.05 + 0.01 * i for w in weeks}
                      for i, a in enumerate(archetypes)},
        "all_weeks": set(weeks),
        "format_name": "standard",
    }


def _trend_rows():
    """Matches get_archetype_trend()'s per-week row shape, consumed by
    _draw_trend -- a dual-axis chart (bars + up to 3 lines)."""
    return [
        {
            "week_start": f"2026-0{i + 1}-01",
            "appearances": 10 + i,
            "meta_share": 0.10 + 0.01 * i,
            "est_winpct": 0.50 + 0.01 * i,
            "top8_rate": 0.20 + 0.01 * i,
        }
        for i in range(N_WEEKS)
    ]


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _make_canvas(app, w=1200, h=700):
    from gui.widgets.chart_canvas import ChartCanvas
    c = ChartCanvas()
    c.resize(w, h)
    c.show()
    app.processEvents()
    return c


def _resize_and_redraw(canvas, app, w, h):
    """Resize the canvas widget (simulating e.g. a maximized window) and
    force matplotlib to recompute the Figure/layout at the new pixel size."""
    canvas.resize(w, h)
    app.processEvents()
    canvas._canvas.draw()
    app.processEvents()


def _renderer(canvas):
    fig = canvas._canvas.figure
    fig.canvas.draw()
    return fig, fig.canvas.get_renderer()


def _line_bboxes(ax, renderer):
    return [line.get_path().get_extents(line.get_transform())
            for line in ax.get_lines()]


def _legend_overlaps_any_line(fig, ax, renderer):
    """True if the figure's legend bbox intersects ANY plotted line's bbox
    -- the exact GR-3 gate check."""
    legends = list(fig.legends) or ([ax.get_legend()] if ax.get_legend() else [])
    assert legends, "no legend present on the figure (GR-3: removing a legend is a FAIL)"
    leg_bbox = legends[0].get_window_extent(renderer)
    for ext in _line_bboxes(ax, renderer):
        if Bbox.intersection(leg_bbox, ext) is not None:
            return True
    return False


def _title_fully_inside_figure(ax, fig, renderer, tol=0.5):
    title_bbox = ax.title.get_window_extent(renderer)
    fw, fh = fig.bbox.width, fig.bbox.height
    return (title_bbox.x0 >= -tol and title_bbox.x1 <= fw + tol
            and title_bbox.y0 >= -tol and title_bbox.y1 <= fh + tol)


def _get_the_legend(fig, ax):
    if fig.legends:
        return fig.legends[0]
    return ax.get_legend()


# ---------------------------------------------------------------------------
# Toolbar: compact, icon-only, <=32px tall (part a)
# ---------------------------------------------------------------------------

def test_toolbar_is_compact_icon_only_and_under_32px(app):
    from PyQt6.QtCore import Qt
    c = _make_canvas(app)
    try:
        tb = c._toolbar
        assert tb.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        assert tb.height() <= 32, f"toolbar height {tb.height()} exceeds 32px"
        # A handful of real matplotlib nav actions should still be present --
        # this isn't a stub toolbar, just a visually compact one.
        assert len(tb.actions()) >= 5
    finally:
        c.close()


def test_toolbar_stays_under_32px_at_maximized_size(app):
    c = _make_canvas(app)
    try:
        _resize_and_redraw(c, app, 1900, 1080)
        assert c._toolbar.height() <= 32
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Legend presence + non-overlap + title bounds -- draw_from_data (meta_share)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["meta_share", "win_pct"])
def test_draw_from_data_legend_entry_per_series_no_overlap(app, mode):
    c = _make_canvas(app)
    try:
        data = _fetch_chart_data_shape()
        c.draw_from_data(data, mode=mode, show_events=False)
        fig, renderer = _renderer(c)
        ax = fig.axes[0]

        legend = _get_the_legend(fig, ax)
        assert legend is not None, "no legend present (GR-3 gate FAIL)"
        assert len(legend.get_texts()) == N_ARCHETYPES, (
            f"expected one legend entry per series ({N_ARCHETYPES}), "
            f"got {len(legend.get_texts())}"
        )
        assert len(ax.get_lines()) == N_ARCHETYPES

        assert not _legend_overlaps_any_line(fig, ax, renderer)
        assert _title_fully_inside_figure(ax, fig, renderer)
    finally:
        c.close()


def test_draw_from_data_legend_no_overlap_at_maximized_size(app):
    c = _make_canvas(app)
    try:
        data = _fetch_chart_data_shape()
        c.draw_from_data(data, mode="meta_share", show_events=False)
        _resize_and_redraw(c, app, 1900, 1080)
        fig, renderer = _renderer(c)
        ax = fig.axes[0]

        assert not _legend_overlaps_any_line(fig, ax, renderer)
        assert _title_fully_inside_figure(ax, fig, renderer)
    finally:
        c.close()


def test_draw_from_data_legend_does_not_collapse_axes_at_top_n_ceiling(app):
    """gui/tabs/charts.py's "Top N" spinbox goes up to 20 (setRange(3, 20)),
    so 20 is a real, user-reachable series count -- not just a synthetic
    stress case. A single-column outside-figure legend at that many entries
    forces constrained_layout to squeeze the axes down to a sliver to make
    vertical room (empirically ~38% of figure height at N=20 with ncol=1,
    measured while building this fix), which is itself the "chrome clash"
    GR-3 exists to kill even though it doesn't trip the plain bbox-overlap
    check. _place_legend's rows-per-column ncol default should keep the
    axes at a reasonable share of the figure instead."""
    c = _make_canvas(app)
    try:
        data = _fetch_chart_data_shape(n=20)
        c.draw_from_data(data, mode="meta_share", show_events=False)
        fig, renderer = _renderer(c)
        ax = fig.axes[0]

        legend = _get_the_legend(fig, ax)
        assert legend is not None
        assert len(legend.get_texts()) == 20
        assert not _legend_overlaps_any_line(fig, ax, renderer)
        assert _title_fully_inside_figure(ax, fig, renderer)

        ax_bbox = ax.get_window_extent(renderer)
        ax_height_frac = (ax_bbox.y1 - ax_bbox.y0) / fig.bbox.height
        assert ax_height_frac >= 0.5, (
            f"axes collapsed to {ax_height_frac:.1%} of figure height at "
            f"N=20 series -- legend needs to wrap columns instead of "
            f"growing as one tall column"
        )
    finally:
        c.close()


# ---------------------------------------------------------------------------
# _draw_meta_share / _draw_compare (single-axis, multi-series line charts)
# ---------------------------------------------------------------------------

def test_draw_meta_share_legend_entry_per_series_no_overlap(app):
    c = _make_canvas(app)
    try:
        c._draw_meta_share(_meta_share_shape())
        fig, renderer = _renderer(c)
        ax = fig.axes[0]

        legend = _get_the_legend(fig, ax)
        assert legend is not None
        assert len(legend.get_texts()) == N_ARCHETYPES
        assert not _legend_overlaps_any_line(fig, ax, renderer)
        assert _title_fully_inside_figure(ax, fig, renderer)
    finally:
        c.close()


def test_draw_compare_legend_entry_per_series_no_overlap(app):
    c = _make_canvas(app)
    try:
        c._draw_compare(_meta_share_shape())
        fig, renderer = _renderer(c)
        ax = fig.axes[0]

        legend = _get_the_legend(fig, ax)
        assert legend is not None
        assert len(legend.get_texts()) == N_ARCHETYPES
        assert not _legend_overlaps_any_line(fig, ax, renderer)
        assert _title_fully_inside_figure(ax, fig, renderer)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# _draw_trend (dual/twin-axis: bars + up to 3 lines) -- the trickiest case,
# since a naive "just outside the axes" legend anchor can still collide with
# the twin axis's own tick labels/ylabel (see chart_canvas.py::_place_legend
# docstring). Assert on the actual gate (line-bbox intersection), which is
# what matters, at both window sizes.
# ---------------------------------------------------------------------------

def test_draw_trend_legend_entry_per_series_no_overlap(app):
    c = _make_canvas(app)
    try:
        c._draw_trend(_trend_rows(), "Izzet Prowess", "standard")
        fig, renderer = _renderer(c)
        ax1 = fig.axes[0]

        legend = _get_the_legend(fig, ax1)
        assert legend is not None
        # Appearances (bar proxy) + Meta % + Est Win % + Top8 % = 4 series
        assert len(legend.get_texts()) == 4

        overlap = False
        for ax in fig.axes:
            for ext in _line_bboxes(ax, renderer):
                if Bbox.intersection(legend.get_window_extent(renderer), ext) is not None:
                    overlap = True
        assert not overlap
        assert _title_fully_inside_figure(ax1, fig, renderer)
    finally:
        c.close()


def test_draw_trend_legend_no_overlap_at_maximized_size(app):
    c = _make_canvas(app)
    try:
        c._draw_trend(_trend_rows(), "Izzet Prowess", "standard")
        _resize_and_redraw(c, app, 1900, 1080)
        fig, renderer = _renderer(c)
        ax1 = fig.axes[0]
        legend = _get_the_legend(fig, ax1)
        assert legend is not None

        overlap = False
        for ax in fig.axes:
            for ext in _line_bboxes(ax, renderer):
                if Bbox.intersection(legend.get_window_extent(renderer), ext) is not None:
                    overlap = True
        assert not overlap
        assert _title_fully_inside_figure(ax1, fig, renderer)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Shared _place_legend() helper -- direct unit coverage
# ---------------------------------------------------------------------------

def test_place_legend_returns_none_when_no_series(app):
    """A plot with nothing labeled shouldn't fabricate an empty legend box."""
    from gui.widgets.chart_canvas import _place_legend
    c = _make_canvas(app)
    try:
        fig = c._fig
        fig.clear()
        ax = fig.add_subplot(111)
        # no ax.plot(..., label=...) calls -- nothing to legend
        result = _place_legend(fig, ax)
        assert result is None
        assert not fig.legends
    finally:
        c.close()


def test_place_legend_one_entry_per_series_outside_axes(app):
    """Direct check that _place_legend's bbox never intersects the axes
    bbox itself (a stronger, simpler invariant than per-line checking --
    since every line is clipped to inside the axes patch, an outside-axes
    legend can never overlap any of them)."""
    from gui.widgets.chart_canvas import _place_legend
    c = _make_canvas(app)
    try:
        fig = c._fig
        fig.clear()
        ax = fig.add_subplot(111)
        for i in range(5):
            ax.plot([0, 1, 2], [i, i + 1, i], label=f"Series {i}")
        legend = _place_legend(fig, ax)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        assert legend is not None
        assert len(legend.get_texts()) == 5
        ax_bbox = ax.get_window_extent(renderer)
        leg_bbox = legend.get_window_extent(renderer)
        assert Bbox.intersection(ax_bbox, leg_bbox) is None
    finally:
        c.close()
