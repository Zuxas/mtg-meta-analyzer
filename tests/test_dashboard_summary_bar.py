"""Tests for gui.tabs.dashboard summary-bar labeling (GR-9).

The dashboard summary strip used to render an unlabeled
"Top: <archetype> <pct>%" stat, which reads as contradictory next to the
Popular panel's own labeled "Meta%" percentage (same underlying metric,
no shared name). Fix: name the metric ("Top meta share") and the active
timeframe window explicitly, e.g. "Top meta share (2 weeks): Boros Energy
12.3%" -- AND make sure the archetype/percentage named is actually the
meta-share leader (get_meta_standings sorts by avg_points, not
appearances, so the naive `standings[0]` is often a different, lower-share
archetype than the Popular panel's own #1 row -- see
test_build_summary_stats_uses_true_meta_share_leader_not_first_row).
"""
import re

import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# A bare "Top: <name> <pct>%" stat -- no metric name, no window -- must
# never reappear. This mirrors the exact pre-fix format from the gate.
_BARE_TOP_RE = re.compile(r"\bTop:\s")


def test_build_summary_stats_names_metric_and_window():
    """Direct unit test of the extracted pure helper -- no GUI/DB needed."""
    from gui.tabs.dashboard import DashboardTab

    standings = [
        {"archetype": "Boros Energy", "appearances": 30},
        {"archetype": "Izzet Prowess", "appearances": 20},
    ]
    stats = DashboardTab._build_summary_stats(standings, {}, "2 weeks")

    top_stats = [s for s in stats if "Boros Energy" in s]
    assert len(top_stats) == 1, f"expected exactly one Top stat, got: {stats}"
    top_stat = top_stats[0]

    # Names the metric explicitly.
    assert "meta share" in top_stat.lower(), (
        f"Top stat does not name its metric: {top_stat!r}"
    )
    # Names the active window explicitly.
    assert "2 weeks" in top_stat, (
        f"Top stat does not name its window: {top_stat!r}"
    )
    # The percentage is still present (60.0% of 50 total appearances).
    assert "60.0%" in top_stat
    # The old bare, unlabeled format must not reappear.
    assert not _BARE_TOP_RE.search(top_stat), (
        f"bare 'Top: <name> <pct>' format leaked through: {top_stat!r}"
    )


def test_build_summary_stats_window_changes_with_timeframe():
    """A different tf_label produces a different rendered window -- proves
    the window isn't a hardcoded string."""
    from gui.tabs.dashboard import DashboardTab

    standings = [{"archetype": "Mono Green", "appearances": 10}]
    stats_all_time = DashboardTab._build_summary_stats(standings, {}, "All Time")
    stats_4wk = DashboardTab._build_summary_stats(standings, {}, "4 weeks")

    top_all_time = next(s for s in stats_all_time if "Mono Green" in s)
    top_4wk = next(s for s in stats_4wk if "Mono Green" in s)

    assert "All Time" in top_all_time
    assert "4 weeks" in top_4wk
    assert top_all_time != top_4wk


def test_build_summary_stats_uses_true_meta_share_leader_not_first_row():
    """`get_meta_standings` sorts by avg_points descending, NOT by
    appearances -- so `standings[0]` is often the best-*placing*
    archetype, which can have a small meta share. Naively labeling
    `standings[0]`'s share as "Top meta share" would print a low
    percentage next to the Popular panel's genuine (bigger, different)
    meta-share leader -- the exact GR-9 contradiction, just wearing a
    label. The Top stat must report the true highest-appearances
    archetype, matching the Popular panel's own #1 row."""
    from gui.tabs.dashboard import DashboardTab

    standings = [
        # Sorted first (best avg_points) but NOT the meta-share leader.
        {"archetype": "Fringe WR Deck", "appearances": 10},
        # The actual highest-appearances archetype: 40 / 50 = 80.0%.
        {"archetype": "Boros Energy", "appearances": 40},
    ]
    stats = DashboardTab._build_summary_stats(standings, {}, "2 weeks")
    top_stat = next(s for s in stats if "meta share" in s.lower())

    assert "Boros Energy" in top_stat, (
        f"Top stat named the points-leader instead of the true "
        f"meta-share leader: {top_stat!r}"
    )
    assert "Fringe WR Deck" not in top_stat
    assert "80.0%" in top_stat, (
        f"expected the true 40/50 = 80.0% share, not the first row's "
        f"10/50 = 20.0%: {top_stat!r}"
    )


def test_build_summary_stats_empty_standings_has_no_top_stat():
    """No standings -> no Top stat at all (nothing to be ambiguous about)."""
    from gui.tabs.dashboard import DashboardTab

    stats = DashboardTab._build_summary_stats([], {}, "2 weeks")
    assert not any("Top" in s for s in stats)


def test_summary_bar_rendered_text_names_metric_and_window(app):
    """End-to-end through the real slot: construct a DashboardTab, feed it
    a standings payload the way the DataLoadWorker would, and read the
    actual rendered text off the real SummaryBar widget."""
    from gui.tabs.dashboard import DashboardTab

    tab = DashboardTab()
    data = {
        "standings": [
            {"archetype": "Boros Energy", "appearances": 40,
             "est_match_winpct": 0.55},
            {"archetype": "Izzet Prowess", "appearances": 20,
             "est_match_winpct": 0.50},
        ],
        "recent": [],
        "real_wrs": {},
        "ratings": {},
    }

    tab._on_panel_data(data)

    rendered = tab._summary_bar._stats.text()
    assert "meta share" in rendered.lower(), (
        f"rendered summary bar does not name the metric: {rendered!r}"
    )
    tf_label = tab._TIMEFRAME_OPTIONS[tab._tf.currentIndex()][0]
    assert tf_label in rendered, (
        f"rendered summary bar does not name the window {tf_label!r}: {rendered!r}"
    )
    assert not _BARE_TOP_RE.search(rendered), (
        f"bare 'Top: <name> <pct>' format leaked into the rendered bar: {rendered!r}"
    )
