"""Recent Top Finishes must list a day's results best-first.

Found by driving the Dashboard against a populated database (48 events, 768
decks) rather than the empty one everything else had been checked against.
The panel showed:

    4th | Selesnya Landfall | Challenge 0 | Sep 22
    3rd | Mono Red Aggro    | Challenge 0 | Sep 22
    2nd | Golgari Midrange  | Challenge 0 | Sep 22
    1st | Azorius Control   | Challenge 0 | Sep 22

Dates descended correctly, but within a day the placements ran backwards --
in a panel called "Top Finishes".

The SQL was never wrong: it ends "ORDER BY (date) DESC, d.placement ASC".
The display was. _populate_recent inserts rows in that order and then calls
setSortingEnabled(True) plus sortByColumn(5, Descending) on the Date column.
Qt's sort is not stable, and enabling sorting re-sorts immediately, so every
row sharing a date was free to move -- in practice reversing the group.

Fix: fold placement into the Date column's sort key. date_sort_key returns a
"YYYYMMDD" STRING, so the tiebreak stays string-sortable as a zero-padded
999-placement suffix; a descending sort then puts the lowest placement first
within a date.
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
    """DashboardTab with no load started — refresh() is what spawns workers."""
    from gui.tabs.dashboard import DashboardTab

    w = DashboardTab()
    try:
        yield w
    finally:
        try:
            w.cleanup()
        except Exception:
            pass


def _row(placement, date="2026-09-22", event="Ev"):
    return {
        "placement": placement,
        "archetype": f"Arch{placement}",
        "player": f"P{placement}",
        "event_name": event,
        "deck_id": placement,
        "date": date,
    }


def _placements(tbl):
    return [tbl.item(r, 0).text() for r in range(tbl.rowCount())]


def _dates(tbl):
    return [tbl.item(r, 5).text() for r in range(tbl.rowCount())]


def test_same_day_results_read_best_first(dash):
    """The regression itself: one day's rows must not invert."""
    dash._populate_recent([_row(p) for p in (1, 2, 3, 4)])
    assert _placements(dash._recent_tbl) == ["1st", "2nd", "3rd", "4th"]


def test_insertion_order_does_not_rescue_it(dash):
    """Feeding the rows in the WRONG order must still display correctly.

    Guards against a fix that only works because the query happens to insert
    them sorted — the sort key has to do the work.
    """
    dash._populate_recent([_row(p) for p in (4, 2, 1, 3)])
    assert _placements(dash._recent_tbl) == ["1st", "2nd", "3rd", "4th"]


def test_dates_still_descend_across_days(dash):
    """The primary sort must survive the tiebreak: newest day first."""
    rows = [_row(p, date="2026-09-21", event="Old") for p in (1, 2)]
    rows += [_row(p, date="2026-09-22", event="New") for p in (1, 2)]
    dash._populate_recent(rows)

    dates = _dates(dash._recent_tbl)
    assert dates == sorted(dates, reverse=True), f"dates not descending: {dates}"
    assert _placements(dash._recent_tbl) == ["1st", "2nd", "1st", "2nd"]


def test_missing_placement_sorts_last_within_its_day(dash):
    """A None placement must not crash the key builder, and shouldn't
    outrank a real finish."""
    rows = [_row(1), {**_row(2), "placement": None}]
    dash._populate_recent(rows)

    placements = _placements(dash._recent_tbl)
    assert placements[0] == "1st", f"a real 1st should lead, got {placements}"
    assert len(placements) == 2


def test_the_panel_still_empties_correctly(dash):
    """The empty-state swap added earlier must be unaffected."""
    dash._populate_recent([])
    tbl = dash._recent_tbl
    assert tbl.isHidden() and not tbl._empty_label.isHidden()
