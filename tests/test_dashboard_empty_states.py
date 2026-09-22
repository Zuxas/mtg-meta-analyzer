"""Dashboard panels must explain themselves when they have no rows.

On a database that has never been scraped, the Dashboard's three panels
(Recent Top Finishes / Win Rate / Popular) rendered as 0-row tables with no
per-panel message -- verified empirically against a fresh init_db() database
before this change. There WAS a status line at the top ("No standard data in
the last 2 weeks -- run fill_database.bat or widen the timeframe"), so the tab
was not silent, but the three panels themselves were blank rectangles.

This became a first-run experience worth fixing once the untapped_entries
launch bug was fixed: fresh installs can now actually reach this screen, and
they arrive in Basic mode with nothing scraped.

Fix: each panel frame carries a hidden theme.empty_state_label (the same
helper heatmap_tab.py and my_decks.py already use), swapped in for the table
whenever the panel has no rows.

The Win Rate panel gets separate copy for "standings exist but everything
fell under the 15-appearance floor", because that is a different problem with
a different fix (widen the timeframe) and a blank panel made the two
indistinguishable.

These tests drive the _populate_* methods directly with synthetic rows: no
database, no QThread workers, and therefore no teardown hazard.
"""
import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


@pytest.fixture
def dash(app, tmp_prefs):
    """A constructed DashboardTab with no load kicked off.

    refresh() is what starts the background workers, so simply not calling it
    keeps this file worker-free -- important under Qt 6.10, where a QThread
    alive at teardown kills the whole pytest process.
    """
    from gui.tabs.dashboard import DashboardTab

    w = DashboardTab()
    try:
        yield w
    finally:
        try:
            w.cleanup()
        except Exception:
            pass


def _recent_row(placement=1, archetype="Izzet Prowess"):
    return {
        "placement": placement,
        "archetype": archetype,
        "player": "Tester",
        "event_name": "RCQ",
        "deck_id": 1,
        "date": "2026-09-01",
    }


def _standing(archetype="Izzet Prowess", appearances=50, wr=0.55):
    return {
        "archetype": archetype,
        "appearances": appearances,
        "est_match_winpct": wr,
        "points": 10,
    }


# ---------------------------------------------------------------------------
# The swap helper itself
# ---------------------------------------------------------------------------

def test_apply_empty_state_swaps_both_directions(dash):
    """NOTE: assertions use isHidden(), not isVisible(). Qt reports
    isVisible() False for any widget whose ancestor is hidden, and these tabs
    are never shown here -- isHidden() is the explicit flag the swap sets."""
    from gui.tabs.dashboard import _apply_empty_state

    tbl = dash._recent_tbl
    lbl = tbl._empty_label

    _apply_empty_state(tbl, has_rows=False)
    assert tbl.isHidden(), "table should be hidden when empty"
    assert not lbl.isHidden(), "placeholder should be shown when empty"

    _apply_empty_state(tbl, has_rows=True)
    assert not tbl.isHidden(), "table should come back when rows exist"
    assert lbl.isHidden(), "placeholder should hide when rows exist"


def test_apply_empty_state_is_a_noop_without_a_label(dash):
    """Defensive: a table built elsewhere has no _empty_label, and the helper
    must not raise on it."""
    from PyQt6.QtWidgets import QTableWidget
    from gui.tabs.dashboard import _apply_empty_state

    _apply_empty_state(QTableWidget(), has_rows=False)  # must not raise


def test_every_panel_has_an_empty_label(dash):
    """All three panels participate -- a panel without one silently keeps the
    old blank-rectangle behaviour."""
    for name in ("_recent_tbl", "_winrate_tbl", "_pop_tbl"):
        tbl = getattr(dash, name)
        assert getattr(tbl, "_empty_label", None) is not None, (
            f"{name} has no empty-state placeholder"
        )


# ---------------------------------------------------------------------------
# Wired into the real populate paths
# ---------------------------------------------------------------------------

def test_recent_panel_shows_placeholder_when_empty_and_table_when_not(dash):
    tbl, lbl = dash._recent_tbl, dash._recent_tbl._empty_label

    dash._populate_recent([])
    assert not lbl.isHidden() and tbl.isHidden()

    dash._populate_recent([_recent_row()])
    assert not tbl.isHidden() and lbl.isHidden()
    assert tbl.rowCount() == 1


def test_popularity_panel_shows_placeholder_when_empty_and_table_when_not(dash):
    tbl, lbl = dash._pop_tbl, dash._pop_tbl._empty_label

    dash._populate_popularity([])
    assert not lbl.isHidden() and tbl.isHidden()

    dash._populate_popularity([_standing()])
    assert not tbl.isHidden() and lbl.isHidden()
    assert tbl.rowCount() == 1


def test_winrate_panel_shows_table_when_archetypes_clear_the_floor(dash):
    tbl, lbl = dash._winrate_tbl, dash._winrate_tbl._empty_label

    dash._populate_winrate([_standing(appearances=50)], {}, {}, {})
    assert not tbl.isHidden() and lbl.isHidden()
    assert tbl.rowCount() == 1


def test_winrate_below_threshold_gets_its_own_copy(dash):
    """Standings exist but nothing has 15+ appearances.

    This must NOT read as "no data" -- the user has data, and the fix is to
    widen the timeframe. Pinning the distinct wording is the point of the
    test; a blank panel made the two cases indistinguishable.
    """
    from gui.tabs.dashboard import _BELOW_THRESHOLD_TEXT

    tbl, lbl = dash._winrate_tbl, dash._winrate_tbl._empty_label
    dash._populate_winrate([_standing(appearances=3)], {}, {}, {})

    assert not lbl.isHidden() and tbl.isHidden()
    headline = _BELOW_THRESHOLD_TEXT[0]
    assert headline in lbl.text(), (
        f"expected below-threshold copy {headline!r}, got {lbl.text()!r}"
    )


def test_winrate_with_no_standings_uses_the_generic_copy(dash):
    """Counterpart to the test above: with genuinely nothing loaded, the
    below-threshold wording would be misleading."""
    from gui.tabs.dashboard import _BELOW_THRESHOLD_TEXT

    lbl = dash._winrate_tbl._empty_label
    dash._populate_winrate([], {}, {}, {})

    assert not lbl.isHidden()
    assert _BELOW_THRESHOLD_TEXT[0] not in lbl.text(), (
        "empty standings should not claim archetypes were filtered out"
    )


def test_placeholder_copy_points_at_a_real_affordance(dash):
    """The hint names Settings -> Collect More Data, which only became a
    visible control after the orphaned Storage groupbox was fixed. If that
    button is ever removed the copy becomes a lie, so pin the reference."""
    text = dash._pop_tbl._empty_label.text()
    assert "Collect More Data" in text
