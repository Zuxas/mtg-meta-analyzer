"""#22: the Dashboard freshness chip shows WHICH source is stale, not only
that the format is (source_recency from #8, computed in the panel worker)."""
import sqlite3
from datetime import date, timedelta

import pytest

from analysis.data_health import format_freshness
from analysis.source_recency import source_recency

TODAY = date(2026, 10, 3)
SELECTED = ["modern", "pioneer"]


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _d(days_ago):
    return (TODAY - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def data():
    """Pioneer: MTGTop8 events current, MTGMelee matches months behind.
    Modern: both sources current."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE events (source TEXT, format TEXT, date TEXT)")
    c.execute("CREATE TABLE matches (source TEXT, format TEXT, event_date TEXT)")
    c.executemany("INSERT INTO events VALUES (?,?,?)",
                  [("mtgtop8", f, _d(a)) for f in ("pioneer", "modern") for a in (2, 5)])
    c.executemany("INSERT INTO matches VALUES (?,?,?)",
                  [("mtgmelee", "pioneer", _d(a)) for a in (147, 150)]
                  + [("mtgmelee", "modern", _d(a)) for a in (1, 3, 40)])
    fmts = ["modern", "pioneer"]
    fresh = format_freshness(fmts, con=c, today=TODAY)
    rec = source_recency(fmts, SELECTED, con=c, today=TODAY, state={})
    return fresh, rec


def test_chip_names_the_lagging_source(data):
    from gui.tabs.dashboard import DashboardTab
    fresh, rec = data
    text, _, tip = DashboardTab._freshness_chip("pioneer", fresh["pioneer"], rec)
    assert "matches behind" in text
    assert "By source:" in tip
    assert "MTGTop8" in tip or "mtgtop8" in tip
    assert "mtgmelee: dead -- data to 2026-05-09" in tip
    assert "recover_source.py --format pioneer --source mtgmelee" in tip
    assert "modern" not in tip.lower()          # only the selected format's sources


def test_chip_unchanged_when_every_source_is_fresh(data):
    from gui.tabs.dashboard import DashboardTab
    fresh, rec = data
    with_rec = DashboardTab._freshness_chip("modern", fresh["modern"], rec)
    without = DashboardTab._freshness_chip("modern", fresh["modern"])
    assert with_rec[0] == without[0]            # chip text gets no stale note
    assert "By source:" in with_rec[2] and "mtgmelee: fresh" in with_rec[2]


def test_all_view_names_the_formats(data):
    from gui.tabs.dashboard import DashboardTab
    fresh, rec = data
    text, _, tip = DashboardTab._freshness_chip("all", fresh, rec)
    assert "matches behind: pioneer" in text
    assert "Modern: ok" in tip and "Pioneer: source stale" in tip


def test_no_recency_keeps_the_old_tooltip(data):
    from gui.tabs.dashboard import DashboardTab
    fresh, _ = data
    text, _, tip = DashboardTab._freshness_chip("pioneer", fresh["pioneer"], None)
    assert "By source:" not in tip and "behind" not in text


def test_widget_tooltip_from_worker_payload(app, data):
    from gui.tabs.dashboard import DashboardTab
    fresh, rec = data
    tab = DashboardTab()
    try:
        tab._fmt.blockSignals(True)   # no refresh: a timer-started worker could
        tab._fmt.setCurrentText("pioneer")   # outlive the tab and crash a later test
        tab._fmt.blockSignals(False)
        tab._apply_freshness(fresh, rec)
        assert "matches behind" in tab._fresh_chip.text()
        assert "mtgmelee: dead" in tab._fresh_chip.toolTip()
    finally:
        tab.cleanup()
        tab.deleteLater()
        app.processEvents()


def test_worker_returns_recency(monkeypatch):
    import analysis.source_recency as sr
    from db.database import init_db
    from gui.tabs import dashboard
    init_db()                                   # the guard's empty tmp DB
    monkeypatch.setattr(sr, "source_recency", lambda fmts: {"sentinel": fmts})
    out = dashboard._load_panel_data("pioneer", None, 10)
    assert out["recency"] == {"sentinel": ["pioneer"]}
