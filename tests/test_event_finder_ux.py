"""Tests for Event Finder UX fix.

Pure unit tests -- no Qt, no network. Helpers live in
gui.tabs.event_finder_tab as module-level functions.
"""
from datetime import date, timedelta

import pytest


def _mk_event(days_out: int, **extra) -> dict:
    """Build a stub formatted event dated `days_out` days from today."""
    d = date.today() + timedelta(days=days_out)
    base = {
        "date": d.isoformat(),
        "dist_mi": 10.0,
        "store": "Test Store",
        "title": "Test Event",
        "fee": "",
        "online": False,
        "raw_tags": [],
        "id": "abc",
    }
    base.update(extra)
    return base


class TestFilterByDateWindow:
    def test_next_2_weeks_includes_today_and_14d(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(14), _mk_event(15)]
        out = filter_by_date_window(events, "2w")
        assert len(out) == 2
        assert all(e["date"] <= (date.today() + timedelta(days=14)).isoformat() for e in out)

    def test_next_4_weeks_default(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(28), _mk_event(29)]
        out = filter_by_date_window(events, "4w")
        assert len(out) == 2

    def test_next_8_weeks(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(56), _mk_event(57)]
        out = filter_by_date_window(events, "8w")
        assert len(out) == 2

    def test_next_6_months(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(183), _mk_event(184)]
        out = filter_by_date_window(events, "6mo")
        assert len(out) == 2

    def test_all_upcoming_no_filter(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(500)]
        out = filter_by_date_window(events, "all")
        assert len(out) == 2

    def test_unknown_key_returns_input(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), _mk_event(500)]
        out = filter_by_date_window(events, "garbage")
        assert out == events

    def test_empty_date_string_is_kept(self):
        from gui.tabs.event_finder_tab import filter_by_date_window
        events = [_mk_event(0), {**_mk_event(0), "date": ""}]
        out = filter_by_date_window(events, "4w")
        assert len(out) == 2


class TestTimeSortKey:
    def test_morning_lex_orders_before_evening(self):
        from gui.tabs.event_finder_tab import time_sort_key
        assert time_sort_key("9:00 AM") < time_sort_key("11:00 PM")

    def test_noon_and_midnight(self):
        from gui.tabs.event_finder_tab import time_sort_key
        assert time_sort_key("12:00 AM") == "00:00"
        assert time_sort_key("12:00 PM") == "12:00"

    def test_pm_offset(self):
        from gui.tabs.event_finder_tab import time_sort_key
        assert time_sort_key("1:00 PM") == "13:00"
        assert time_sort_key("11:30 PM") == "23:30"

    def test_empty_returns_empty(self):
        from gui.tabs.event_finder_tab import time_sort_key
        assert time_sort_key("") == ""

    def test_malformed_returns_input(self):
        from gui.tabs.event_finder_tab import time_sort_key
        # Defensive: don't crash on unexpected formats; sort key just
        # falls back to the raw string.
        assert time_sort_key("not a time") == "not a time"


class TestGoogleMapsUrl:
    def test_store_and_city(self):
        from gui.tabs.event_finder_tab import google_maps_url
        url = google_maps_url("Mox Boarding House", "Seattle")
        assert url.startswith("https://www.google.com/maps/search/?api=1&query=")
        assert "Mox+Boarding+House" in url or "Mox%20Boarding%20House" in url
        assert "Seattle" in url

    def test_store_only_no_city(self):
        from gui.tabs.event_finder_tab import google_maps_url
        url = google_maps_url("Cool Stuff Games", "")
        assert "Cool+Stuff+Games" in url or "Cool%20Stuff%20Games" in url
        # Should not have a trailing space-encoded artifact
        assert not url.endswith("+") and not url.endswith("%20")

    def test_special_characters_encoded(self):
        from gui.tabs.event_finder_tab import google_maps_url
        url = google_maps_url("Joe's Cards & Games", "St. Paul")
        # Apostrophe and ampersand must be URL-encoded
        assert "&" not in url.split("query=", 1)[1]  # only the query separator
        assert "%27" in url or "%26" in url
