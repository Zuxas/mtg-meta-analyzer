"""Dashboard data-freshness chip + dead-format banners (CHAPIN Task 1, item 3).

A silently stale number is worse than no number: when the selected format's
match data is `dead`, every panel on the dashboard must say so.
"""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


FRESH = {"last_match_date": "2026-09-17", "last_event_date": "2026-09-18",
         "matches_30d": 11218, "matches_prev_30d": 2910, "days_stale": 3, "status": "fresh"}
STALE = {"last_match_date": "2026-09-05", "last_event_date": "2026-09-05",
         "matches_30d": 40, "matches_prev_30d": 300, "days_stale": 15, "status": "stale"}
DEAD = {"last_match_date": "2026-05-22", "last_event_date": "2026-05-22",
        "matches_30d": 0, "matches_prev_30d": 0, "days_stale": 121, "status": "dead"}
NONE = {"last_match_date": None, "last_event_date": None,
        "matches_30d": 0, "matches_prev_30d": 0, "days_stale": None, "status": "dead"}


# ---------------------------------------------------------------------------
# Pure helpers (no GUI, no DB)
# ---------------------------------------------------------------------------

def test_freshness_chip_maps_status_to_text_and_color():
    from gui.tabs.dashboard import DashboardTab
    from gui import theme

    text, color, tip = DashboardTab._freshness_chip("modern", FRESH)
    assert "fresh" in text.lower() and "3d" in text
    assert color == theme.OK
    assert "2026-09-17" in tip and "11,218" in tip

    text, color, _ = DashboardTab._freshness_chip("standard", STALE)
    assert "stale" in text.lower() and color == theme.WARN

    text, color, _ = DashboardTab._freshness_chip("pioneer", DEAD)
    assert "dead" in text.lower() and "121d" in text and color == theme.ERR

    text, color, tip = DashboardTab._freshness_chip("pioneer", NONE)
    assert "no data" in text.lower() and color == theme.ERR

    text, color, _ = DashboardTab._freshness_chip("modern", None)   # freshness unavailable
    assert color == theme.TEXT_DIM


def test_freshness_chip_for_all_formats_reports_the_worst():
    from gui.tabs.dashboard import DashboardTab
    from gui import theme
    text, color, tip = DashboardTab._freshness_chip(
        "all", {"modern": FRESH, "standard": STALE, "pioneer": DEAD})
    assert color == theme.ERR
    assert "pioneer" in tip.lower() and "modern" in tip.lower()


def test_stale_banner_text_only_for_dead():
    from gui.tabs.dashboard import DashboardTab
    assert DashboardTab._stale_banner_text("modern", FRESH) is None
    assert DashboardTab._stale_banner_text("standard", STALE) is None
    dead = DashboardTab._stale_banner_text("pioneer", DEAD)
    assert "121 days old" in dead and "2026-05-22" in dead and "pioneer" in dead.lower()
    none = DashboardTab._stale_banner_text("pioneer", NONE)
    assert "no pioneer match data" in none.lower()


# ---------------------------------------------------------------------------
# Widget level: banners on every panel + chart, driven by _apply_freshness
# ---------------------------------------------------------------------------

def test_apply_freshness_shows_banner_on_every_panel_when_dead(app):
    from gui.tabs.dashboard import DashboardTab
    tab = DashboardTab()
    try:
        banners = tab._panel_banners
        assert len(banners) >= 4, "recent / win rate / popular panels + chart area"
        assert all(not b.isVisibleTo(tab) for b in banners)

        tab._fmt.setCurrentText("pioneer")
        tab._apply_freshness({"pioneer": DEAD})
        assert all(b.isVisibleTo(tab) for b in banners)
        assert all("121 days old" in b.text() for b in banners)
        assert "dead" in tab._fresh_chip.text().lower()

        tab._fmt.setCurrentText("modern")
        tab._apply_freshness({"modern": FRESH})
        assert all(not b.isVisibleTo(tab) for b in banners)
        assert "fresh" in tab._fresh_chip.text().lower()
    finally:
        tab.cleanup()
        tab.deleteLater()
        app.processEvents()
