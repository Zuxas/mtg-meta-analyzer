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


class TestFormatEventExtended:
    def _raw_event(self, **overrides):
        base = {
            "id": "evt-123",
            "title": "Modern RCQ",
            "scheduledStartTime": "2026-06-07T18:00:00Z",
            "tags": ["regional_championship_qualifier", "modern"],
            "distance": 16093,
            "organization": {"name": "Mox Boarding House"},
            "eventFormat": {"id": "modern"},
            "entryFee": {"amount": 2500, "currency": "USD"},
            "isOnline": False,
            "venue": {"city": "Seattle", "state": "WA"},
        }
        base.update(overrides)
        return base

    def test_all_new_fields_present(self):
        from scrapers.event_finder import _format_event
        out = _format_event(self._raw_event())
        assert out["start_iso"] == "2026-06-07T18:00:00Z"
        assert out["weekday"]  # non-empty
        assert out["time_str"]  # non-empty
        assert out["format_id"] == "modern"
        assert out["city"] == "Seattle"
        assert out["state"] == "WA"

    def test_missing_eventFormat_falls_back(self):
        from scrapers.event_finder import _format_event
        raw = self._raw_event()
        del raw["eventFormat"]
        out = _format_event(raw)
        assert out["format_id"] == ""

    def test_null_eventFormat(self):
        from scrapers.event_finder import _format_event
        out = _format_event(self._raw_event(eventFormat=None))
        assert out["format_id"] == ""

    def test_missing_venue_returns_empty_strings(self):
        from scrapers.event_finder import _format_event
        raw = self._raw_event()
        del raw["venue"]
        out = _format_event(raw)
        assert out["city"] == ""
        assert out["state"] == ""

    def test_null_venue(self):
        from scrapers.event_finder import _format_event
        out = _format_event(self._raw_event(venue=None))
        assert out["city"] == ""
        assert out["state"] == ""

    def test_existing_fields_unchanged(self):
        # Regression: make sure we didn't break the original shape.
        from scrapers.event_finder import _format_event
        out = _format_event(self._raw_event())
        assert out["date"] == "2026-06-07"
        assert out["title"] == "Modern RCQ"
        assert out["store"] == "Mox Boarding House"
        assert out["fee"] == "$25"
        assert out["online"] is False
        assert out["id"] == "evt-123"
        assert "regional_championship_qualifier" in out["raw_tags"]


class TestSearchEventsQuery:
    def test_query_requests_venue_and_format(self, monkeypatch):
        """The query string sent to the API must include the new fields."""
        from scrapers import event_finder

        captured = {}

        class _FakeResp:
            def __init__(self, body):
                self._body = body
            def read(self):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["payload"] = req.data
            import json as _j
            return _FakeResp(_j.dumps({"data": {"searchEvents": {"events": []}}}).encode())

        monkeypatch.setattr(event_finder.urllib.request, "urlopen", fake_urlopen)
        event_finder.search_events(47.6, -122.3, radius_miles=100)

        payload = captured["payload"].decode()
        assert "venue" in payload
        assert "city" in payload
        assert "state" in payload
        assert "eventFormat" in payload  # already there, but verify regression
