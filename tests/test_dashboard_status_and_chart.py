"""Dashboard review fixes (2026-10-01).

1. The status-bar event count was hard-coded to Standard ("Standard: 4,242 events") while the
   Dashboard showed Modern -- it now follows the Dashboard's format.
2. The win-rate chart: low-sample buckets swung 0% <-> 100% (n>=1 + an unweighted 3-point mean),
   and the chart legend duplicated the archetype selector, whose colour dots did not even match
   the lines (selector coloured by position in the full list, chart by position among the
   CHECKED archetypes). Now: one colour per archetype everywhere, sample-weighted smoothing,
   points backed by < 3 appearances omitted, thin points faded, and the Dashboard relies on its
   (now colour-matched) selector instead of a second legend. ChartCanvas keeps its legend by
   default -- the GR-3 gate (tests/test_gr3_chart_chrome.py) is unchanged.
"""
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


WEEKS = [f"2026-08-{d:02d}" for d in (3, 10, 17, 24, 31)]


def _data(samples, winpct):
    archetypes = list(samples)
    return {"archetypes": archetypes,
            "meta_data": {a: {w: 0.1 for w in WEEKS} for a in archetypes},
            "winpct_data": winpct, "sample_data": samples,
            "all_weeks": set(WEEKS), "format_name": "modern", "granularity": "weekly"}


# ------------------------------------------------------------------ status bar
def test_event_count_label_follows_the_format(monkeypatch):
    import gui.main_window as mw
    counts = {"modern": 1284, "standard": 4242, "pioneer": 7, "legacy": 3, "pauper": 2}
    monkeypatch.setattr(mw, "_count_events", lambda f="standard": counts.get(f, 0))
    assert mw._event_count_text("modern") == "Modern: 1,284 events"
    assert mw._event_count_text("standard") == "Standard: 4,242 events"
    assert mw._event_count_text("all") == f"All formats: {sum(counts.values()):,} events"


def test_dashboard_announces_its_format(app):
    from gui.tabs.dashboard import DashboardTab
    tab = DashboardTab()
    seen = []
    tab.format_changed.connect(seen.append)
    tab._fmt.setCurrentText("modern")
    tab._fmt.setCurrentText("legacy")
    assert seen[-2:] == ["modern", "legacy"]
    assert tab.current_format() == "legacy"
    tab.cleanup()
    tab.deleteLater()


# ------------------------------------------------------------------ chart
def _lines(canvas):
    ax = canvas._fig.axes[0]
    return {l.get_label(): l for l in ax.get_lines() if not l.get_label().startswith("_")}


def test_line_colours_are_stable_per_archetype(app):
    from gui.widgets.chart_canvas import ChartCanvas, archetype_color
    s = {a: {w: 10 for w in WEEKS} for a in ("Alpha", "Bravo", "Charlie", "Delta")}
    wp = {a: {w: 0.5 for w in WEEKS} for a in s}
    c = ChartCanvas()
    c.draw_from_data(_data(s, wp), {"Bravo", "Delta"}, mode="win_pct", show_events=False)
    got = {k: l.get_color() for k, l in _lines(c).items()}
    assert got == {"Bravo": archetype_color(1), "Delta": archetype_color(3)}   # index in the FULL list
    c.close()


def test_dashboard_can_hide_the_duplicate_legend(app):
    from gui.widgets.chart_canvas import ChartCanvas
    s = {a: {w: 10 for w in WEEKS} for a in ("Alpha", "Bravo")}
    wp = {a: {w: 0.5 for w in WEEKS} for a in s}
    c = ChartCanvas()
    c.draw_from_data(_data(s, wp), None, mode="win_pct", show_events=False, legend=False)
    assert not c._fig.legends and c._fig.axes[0].get_legend() is None
    c.draw_from_data(_data(s, wp), None, mode="win_pct", show_events=False)            # default: legend
    assert c._fig.legends
    c.close()


def test_smoothing_is_sample_weighted_and_drops_thin_windows():
    from gui.widgets.chart_canvas import smooth_win_rate
    # one 0% singleton beside two solid buckets no longer drags the line to ~33%
    ys, ns = smooth_win_rate([60.0, 0.0, 60.0], [20, 1, 20])
    assert ys[1] == pytest.approx((60 * 20 + 0 * 1 + 60 * 20) / 41)
    # a window backed by fewer than 3 appearances is not drawn at all
    ys, ns = smooth_win_rate([100.0, None, None, 0.0, None], [1, 0, 0, 1, 0])
    assert ys == [None, None, None, None, None]
    ys, ns = smooth_win_rate([50.0, 70.0, None], [2, 2, 0])
    assert ys[0] == pytest.approx(60.0) and ns[0] == 4
    assert ys[2] is None and ns[2] == 2                   # only the 2-game bucket in reach: not drawn


def test_thin_points_are_faded_on_the_chart(app):
    from gui.widgets.chart_canvas import ChartCanvas
    s = {"Alpha": dict(zip(WEEKS, [40, 40, 2, 40, 40])), "Bravo": dict(zip(WEEKS, [1, 1, 1, 1, 1]))}
    wp = {"Alpha": dict(zip(WEEKS, [0.55, 0.55, 1.0, 0.55, 0.55])), "Bravo": dict(zip(WEEKS, [1.0, 0, 1.0, 0, 1.0]))}
    c = ChartCanvas()
    c.draw_from_data(_data(s, wp), None, mode="win_pct", show_events=False)
    ax = c._fig.axes[0]
    ys = [y for l in ax.get_lines() if l.get_label() == "Alpha" for y in l.get_ydata()]
    assert max(ys) < 60                                   # the 2-game 100% spike is diluted, not plotted raw
    bravo = [l for l in ax.get_lines() if l.get_label() == "Bravo"]
    assert all(len(l.get_ydata()) == 3 for l in bravo)    # n=3 per window: drawn ...
    alphas = [a for col in ax.collections for a in col.get_facecolors()[:, 3]]
    assert alphas and min(alphas) < max(alphas)           # ... but thin points faded
    c.close()


# ------------------------------------------------------------------ hover
def _move(c, ax, x, y):
    from matplotlib.backend_bases import MouseEvent
    px, py = ax.transData.transform((x, y))
    ev = MouseEvent("motion_notify_event", c._canvas, px, py)
    c._on_hover_move(ev)


def test_hover_box_lists_every_series_and_highlights_the_nearest(app):
    import matplotlib.dates as md
    from datetime import datetime
    from gui.widgets.chart_canvas import ChartCanvas
    s = {a: {w: 20 for w in WEEKS} for a in ("Alpha", "Bravo")}
    wp = {"Alpha": {w: 0.60 for w in WEEKS}, "Bravo": {w: 0.40 for w in WEEKS}}
    c = ChartCanvas()
    c.resize(1000, 600)
    c.draw_from_data(_data(s, wp), None, mode="win_pct", show_events=False, legend=False)
    c._canvas.draw()
    ax = c._fig.axes[0]
    x = md.date2num(datetime(2026, 8, 17))
    _move(c, ax, x, 60.0)                                  # right on Alpha's point
    text = c._hover_box.text()
    assert c._hover_box.isVisibleTo(c) and "2026-08-17" in text
    assert "Alpha: 60.0%" in text and "Bravo: 40.0%" in text and "(n=60)" in text
    assert c._highlighted == "Alpha"
    lines = {l.get_label(): l for l in ax.get_lines()}
    assert lines["Bravo"].get_alpha() < lines["Alpha"].get_alpha()
    _move(c, ax, x, 50.0)                                  # between the lines: box stays, no highlight
    assert c._highlighted is None and c._hover_box.isVisibleTo(c)
    c._end_hover()
    assert not c._hover_box.isVisibleTo(c) and c._highlighted is None
    c.close()


def test_selector_row_hover_highlights_its_line(app):
    from PyQt6.QtCore import QEvent
    from gui.tabs.dashboard import DashboardTab
    tab = DashboardTab()
    s = {a: {w: 20 for w in WEEKS} for a in ("Alpha", "Bravo", "Charlie")}
    wp = {a: {w: 0.5 for w in WEEKS} for a in s}
    data = _data(s, wp)
    tab._on_chart_data(data)
    rows = [tab._check_layout.itemAt(i).widget() for i in range(tab._check_layout.count())
            if tab._check_layout.itemAt(i).widget() is not None]
    bravo = next(r for r in rows if r.property("chart_arch") == "Bravo")
    tab.eventFilter(bravo, QEvent(QEvent.Type.Enter))
    assert tab._canvas._highlighted == "Bravo"
    tab.eventFilter(bravo, QEvent(QEvent.Type.Leave))
    assert tab._canvas._highlighted is None
    # the selector dot and the line share one colour, toggling or not
    from gui.widgets.chart_canvas import archetype_color
    for arch, cb in tab._chart_checks.items():
        cb.setChecked(arch != "Alpha")                     # deselect the first deck
    lines = {l.get_label(): l.get_color() for l in tab._canvas._fig.axes[0].get_lines()}
    assert lines["Bravo"] == archetype_color(1) and lines["Charlie"] == archetype_color(2)
    tab.cleanup()
    tab.deleteLater()
