# Event Finder UX Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix sorting, surface already-queried data, add a date window filter, bump max radius to 300 mi, restyle the RCQ highlight, persist filters across sessions, and add a per-row "Open in Google Maps" right-click action — all within `gui/tabs/event_finder_tab.py` + `scrapers/event_finder.py`.

**Architecture:** Surgical UX fix on an existing tab. New pure helpers live in `gui/tabs/event_finder_tab.py` module scope (sortable, testable without Qt). Scraper changes are additive — extra fields on `_format_event` and one new GraphQL field. UIState integration follows the documented `showEvent`+`blockSignals` pattern. No new modules, no new schema.

**Tech Stack:** Python 3.13, PyQt6, pytest. Existing helpers: `gui/widgets/table_helpers.py` (`NumItem`, `DateItem`, `SortItem`, `SORT_ROLE`), `gui/state.py::UIState`.

**Spec:** `docs/superpowers/specs/2026-06-04-event-finder-ux-fix-design.md`

---

## File Structure

- **Modify** `gui/tabs/event_finder_tab.py` — new helpers, new column layout, new "When" combo, RCQ row tint, UIState hydration, context menu.
- **Modify** `scrapers/event_finder.py` — extend GraphQL query (`venue { city state }`), extend `_format_event` (`start_iso`, `weekday`, `time_str`, `format_id`, `city`, `state`).
- **Modify** `gui/state_keys.py` — add 5 `EVENT_FINDER_*` constants.
- **Create** `tests/test_event_finder_ux.py` — unit tests for pure helpers, `_format_event` extension, UIState roundtrip, Google Maps URL.

---

## Task 1: Pure helpers (date-window filter, time sort key, Google Maps URL)

**Why first:** All three are pure functions used by later tasks. Easy TDD. No Qt, no API.

**Files:**
- Create: `tests/test_event_finder_ux.py`
- Modify: `gui/tabs/event_finder_tab.py` (add module-level helpers near the top)

- [ ] **Step 1: Write failing tests for `filter_by_date_window`**

Add to `tests/test_event_finder_ux.py`:

```python
"""Tests for Event Finder UX fix.

Pure unit tests — no Qt, no network. Helpers live in
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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest tests/test_event_finder_ux.py::TestFilterByDateWindow -v`
Expected: ImportError on `filter_by_date_window`.

- [ ] **Step 3: Implement `filter_by_date_window` in `gui/tabs/event_finder_tab.py`**

Add near the top of the file, **after** the existing imports and **before** `_EVENT_TYPE_OPTIONS`:

```python
from datetime import date as _date, timedelta as _timedelta

# Date-window choices for the "When" filter combo.
# Order matters — used to populate the combobox.
DATE_WINDOW_OPTIONS = [
    ("Next 2 wk",    "2w"),
    ("Next 4 wk",    "4w"),
    ("Next 8 wk",    "8w"),
    ("Next 6 mo",    "6mo"),
    ("All upcoming", "all"),
]

_DATE_WINDOW_DAYS = {"2w": 14, "4w": 28, "8w": 56, "6mo": 183}


def filter_by_date_window(events: list[dict], key: str) -> list[dict]:
    """Drop events whose date falls outside the window.

    `key` is one of "2w", "4w", "8w", "6mo", "all". Unknown keys
    pass everything through (defensive). Events with empty date
    strings are kept (defensive — they sort to the top anyway).
    """
    if key not in _DATE_WINDOW_DAYS:
        return events  # "all" or anything unrecognized
    cutoff = (_date.today() + _timedelta(days=_DATE_WINDOW_DAYS[key])).isoformat()
    return [e for e in events if not e.get("date") or e["date"] <= cutoff]
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `pytest tests/test_event_finder_ux.py::TestFilterByDateWindow -v`
Expected: 7 passed.

- [ ] **Step 5: Write failing tests for `time_sort_key`**

Append to `tests/test_event_finder_ux.py`:

```python
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
```

- [ ] **Step 6: Run tests, confirm they fail**

Run: `pytest tests/test_event_finder_ux.py::TestTimeSortKey -v`
Expected: ImportError on `time_sort_key`.

- [ ] **Step 7: Implement `time_sort_key`**

Append to `gui/tabs/event_finder_tab.py` below `filter_by_date_window`:

```python
def time_sort_key(time_str: str) -> str:
    """Convert "6:00 PM" -> "18:00" for sortable keys.

    Returns "" for empty input. Returns input unchanged for malformed
    strings (defensive — never raises).
    """
    if not time_str:
        return ""
    s = time_str.strip().upper()
    try:
        time_part, ampm = s.rsplit(" ", 1)
        h_str, m_str = time_part.split(":")
        h = int(h_str)
        m = int(m_str)
        if ampm == "AM":
            if h == 12:
                h = 0
        elif ampm == "PM":
            if h != 12:
                h += 12
        else:
            return time_str
        return f"{h:02d}:{m:02d}"
    except (ValueError, IndexError):
        return time_str
```

- [ ] **Step 8: Run tests, confirm they pass**

Run: `pytest tests/test_event_finder_ux.py::TestTimeSortKey -v`
Expected: 5 passed.

- [ ] **Step 9: Write failing tests for `google_maps_url`**

Append to `tests/test_event_finder_ux.py`:

```python
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
```

- [ ] **Step 10: Run tests, confirm they fail**

Run: `pytest tests/test_event_finder_ux.py::TestGoogleMapsUrl -v`
Expected: ImportError on `google_maps_url`.

- [ ] **Step 11: Implement `google_maps_url`**

Append to `gui/tabs/event_finder_tab.py` below `time_sort_key`:

```python
import urllib.parse as _urlparse


def google_maps_url(store: str, city: str) -> str:
    """Build a Google Maps search URL for a store + city.

    City may be empty; falls back to store-name-only. The Google
    fuzzy search resolves either form to a useful pin.
    """
    parts = [store.strip()]
    if city.strip():
        parts.append(city.strip())
    query = " ".join(parts)
    encoded = _urlparse.quote_plus(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"
```

- [ ] **Step 12: Run tests, confirm they pass**

Run: `pytest tests/test_event_finder_ux.py::TestGoogleMapsUrl -v`
Expected: 3 passed.

- [ ] **Step 13: Run the full file to confirm nothing else broke**

Run: `pytest tests/test_event_finder_ux.py -v`
Expected: 15 passed.

- [ ] **Step 14: Commit**

```bash
git add tests/test_event_finder_ux.py gui/tabs/event_finder_tab.py
git commit -m "feat(event-finder): add pure helpers (date window, time sort, gmaps URL)"
```

---

## Task 2: Extend `_format_event` + GraphQL query for venue/format

**Why next:** The new fields on `_format_event` feed the new column layout in Task 5. The GraphQL change is additive — old code paths keep working.

**Files:**
- Modify: `scrapers/event_finder.py` (`search_events` query, `_format_event` return shape)
- Modify: `tests/test_event_finder_ux.py` (new test class)

- [ ] **Step 1: Write failing tests for the extended `_format_event`**

Append to `tests/test_event_finder_ux.py`:

```python
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
```

- [ ] **Step 2: Write failing test for the GraphQL query string**

Append to `tests/test_event_finder_ux.py`:

```python
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
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `pytest tests/test_event_finder_ux.py::TestFormatEventExtended tests/test_event_finder_ux.py::TestSearchEventsQuery -v`
Expected: `start_iso`/`weekday`/`time_str`/`format_id`/`city`/`state` missing from `_format_event`; `venue` missing from query.

- [ ] **Step 4: Extend the GraphQL query in `search_events`**

In `scrapers/event_finder.py`, locate the `query` string inside `search_events` and add `venue { city state }` to the `events` selection set. The final selection set becomes:

```python
    query = f"""
    query searchEvents({vars_decl}) {{
      searchEvents(query: {{
        latitude: $latitude
        longitude: $longitude
        maxMeters: $maxMeters
        {tag_filter}
        pageSize: $pageSize
      }}) {{
        events {{
          id
          title
          scheduledStartTime
          tags
          distance
          organization {{ name }}
          eventFormat {{ id }}
          entryFee {{ amount currency }}
          isOnline
          venue {{ city state }}
        }}
        pageInfo {{ totalResults }}
      }}
    }}
    """
```

- [ ] **Step 5: Extend `_format_event` to surface the new fields**

Replace the existing `_format_event` function in `scrapers/event_finder.py` with:

```python
def _format_event(e: dict) -> dict:
    """Convert raw event dict to a clean display record."""
    from datetime import datetime as _dt

    tags = e.get("tags", [])
    display_tags = [TAG_LABELS.get(t, t) for t in tags if TAG_LABELS.get(t) is not None]

    dist_m = e.get("distance", 0) or 0
    dist_mi = dist_m / 1609.34

    fee = e.get("entryFee") or {}
    fee_str = ""
    if fee.get("amount"):
        # API returns amount in cents (e.g. 2000 = $20.00)
        fee_str = f"${fee['amount'] / 100:.0f}"

    start_iso = e.get("scheduledStartTime") or ""
    date_str = start_iso[:10]
    weekday = ""
    time_str = ""
    if start_iso:
        try:
            # Wizards returns "...Z" — fromisoformat (3.11+) handles "Z" directly,
            # but to be safe across 3.10/3.11 we normalize to +00:00.
            iso_norm = start_iso.replace("Z", "+00:00")
            dt_utc = _dt.fromisoformat(iso_norm)
            local = dt_utc.astimezone()  # convert to local tz
            weekday = local.strftime("%a")          # "Sat"
            # %I is 01-12; lstrip("0") yields "6:00 PM", "12:00 AM" etc.
            # Cross-platform — Windows doesn't support %-I.
            time_str = local.strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            pass

    ef = e.get("eventFormat") or {}
    format_id = ef.get("id", "") if isinstance(ef, dict) else ""

    venue = e.get("venue") or {}
    if not isinstance(venue, dict):
        venue = {}
    city = venue.get("city", "") or ""
    state = venue.get("state", "") or ""

    return {
        "date":      date_str,
        "start_iso": start_iso,
        "weekday":   weekday,
        "time_str":  time_str,
        "title":     e.get("title", "?"),
        "store":     (e.get("organization") or {}).get("name", "?"),
        "tags":      display_tags,
        "dist_mi":   round(dist_mi, 1),
        "fee":       fee_str,
        "format_id": format_id,
        "city":      city,
        "state":     state,
        "online":    e.get("isOnline", False),
        "id":        e.get("id", ""),
        "raw_tags":  tags,
    }
```

- [ ] **Step 6: Run tests, confirm they pass**

Run: `pytest tests/test_event_finder_ux.py::TestFormatEventExtended tests/test_event_finder_ux.py::TestSearchEventsQuery -v`
Expected: 7 passed.

- [ ] **Step 7: Run the full event-finder test file**

Run: `pytest tests/test_event_finder_ux.py -v`
Expected: 22 passed (15 + 7).

- [ ] **Step 8: Commit**

```bash
git add scrapers/event_finder.py tests/test_event_finder_ux.py
git commit -m "feat(event-finder): expose venue + start_iso + format_id from API"
```

---

## Task 3: Bump radius options to include 300 mi + raise API limit

**Why now:** Trivial change, but worth its own commit so the radius bump shows up cleanly in `git log`.

**Files:**
- Modify: `gui/tabs/event_finder_tab.py` (`_RADIUS_OPTIONS`, `_fetch_events`)
- Modify: `tests/test_event_finder_ux.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_event_finder_ux.py`:

```python
class TestRadiusAndLimit:
    def test_300_mi_is_an_option(self):
        from gui.tabs.event_finder_tab import _RADIUS_OPTIONS
        assert 300 in _RADIUS_OPTIONS

    def test_default_radius_index_still_100mi(self):
        # The combobox setCurrentIndex(3) assumes 100mi is at index 3.
        # If we add a value BEFORE 100, this test catches it.
        from gui.tabs.event_finder_tab import _RADIUS_OPTIONS
        assert _RADIUS_OPTIONS[3] == 100
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `pytest tests/test_event_finder_ux.py::TestRadiusAndLimit -v`
Expected: 1 fail (300 not in list), 1 pass.

- [ ] **Step 3: Update `_RADIUS_OPTIONS`**

In `gui/tabs/event_finder_tab.py`, change:

```python
_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200]
```

to:

```python
_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200, 300]
```

- [ ] **Step 4: Raise the API limit in `_fetch_events`**

In `gui/tabs/event_finder_tab.py`, in `_fetch_events`, change:

```python
    raw = search_events(lat, lng, radius_miles=radius, tags=tags, limit=200)
```

to:

```python
    raw = search_events(lat, lng, radius_miles=radius, tags=tags, limit=500)
```

- [ ] **Step 5: Run tests, confirm they pass**

Run: `pytest tests/test_event_finder_ux.py::TestRadiusAndLimit -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add gui/tabs/event_finder_tab.py tests/test_event_finder_ux.py
git commit -m "feat(event-finder): allow 300mi radius and raise API limit to 500"
```

---

## Task 4: Add UIState keys + roundtrip test

**Why now:** Wiring tasks (6, 7, 8) need these constants. Roundtrip test confirms `UIState` works for our new namespace before the GUI layers touch it.

**Files:**
- Modify: `gui/state_keys.py`
- Modify: `tests/test_event_finder_ux.py`

- [ ] **Step 1: Write failing test for the UIState roundtrip**

Append to `tests/test_event_finder_ux.py`:

```python
class TestEventFinderStateKeys:
    def test_constants_exist(self):
        from gui import state_keys as k
        assert k.EVENT_FINDER_ZIPCODE == "tabs.event_finder.zipcode"
        assert k.EVENT_FINDER_RADIUS == "tabs.event_finder.radius"
        assert k.EVENT_FINDER_EVENT_TYPE == "tabs.event_finder.event_type"
        assert k.EVENT_FINDER_FORMAT == "tabs.event_finder.format"
        assert k.EVENT_FINDER_DATE_WINDOW == "tabs.event_finder.date_window"

    def test_roundtrip(self, tmp_path, monkeypatch):
        from gui.state import UIState
        from gui import state_keys as k

        prefs_path = tmp_path / "preferences.json"
        monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
        monkeypatch.setattr("gui.state.UIState._instance", None)

        state = UIState.instance()
        state.set(k.EVENT_FINDER_ZIPCODE, "98101")
        state.set(k.EVENT_FINDER_RADIUS, 300)
        state.set(k.EVENT_FINDER_EVENT_TYPE, "regional_championship_qualifier")
        state.set(k.EVENT_FINDER_FORMAT, "modern")
        state.set(k.EVENT_FINDER_DATE_WINDOW, "4w")

        assert state.get(k.EVENT_FINDER_ZIPCODE) == "98101"
        assert state.get(k.EVENT_FINDER_RADIUS) == 300
        assert state.get(k.EVENT_FINDER_EVENT_TYPE) == "regional_championship_qualifier"
        assert state.get(k.EVENT_FINDER_FORMAT) == "modern"
        assert state.get(k.EVENT_FINDER_DATE_WINDOW) == "4w"
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `pytest tests/test_event_finder_ux.py::TestEventFinderStateKeys -v`
Expected: AttributeError on `EVENT_FINDER_ZIPCODE`.

- [ ] **Step 3: Add the constants to `gui/state_keys.py`**

Append the following block at the end of `gui/state_keys.py`:

```python
# Event Finder
EVENT_FINDER_ZIPCODE     = "tabs.event_finder.zipcode"
EVENT_FINDER_RADIUS      = "tabs.event_finder.radius"
EVENT_FINDER_EVENT_TYPE  = "tabs.event_finder.event_type"
EVENT_FINDER_FORMAT      = "tabs.event_finder.format"
EVENT_FINDER_DATE_WINDOW = "tabs.event_finder.date_window"
```

- [ ] **Step 4: Run test, confirm it passes**

Run: `pytest tests/test_event_finder_ux.py::TestEventFinderStateKeys -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add gui/state_keys.py tests/test_event_finder_ux.py
git commit -m "feat(event-finder): add UIState keys for filter persistence"
```

---

## Task 5: New column layout + sort fix + RCQ row tint

**Why now:** Largest GUI change, but isolated to `_populate_table` and `_build_table`. No new behavior is exposed yet — Task 6 wires the "When" combo, Task 8 wires the context menu. After this task the tab still functions exactly as today, except sort/columns/highlight are correct.

**Files:**
- Modify: `gui/tabs/event_finder_tab.py` (`_COLUMNS`, `_build_table`, `_populate_table`)

- [ ] **Step 1: Update `_COLUMNS`**

In `gui/tabs/event_finder_tab.py`, change:

```python
_COLUMNS = ["Date", "Distance", "Store", "Event", "Entry", "Format"]
```

to:

```python
_COLUMNS = ["Date", "Time", "Distance", "Store", "Event", "Entry", "Format"]
```

- [ ] **Step 2: Update `_build_table` column resize modes**

In `gui/tabs/event_finder_tab.py`, replace the existing block:

```python
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Date
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Distance
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Store
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Event
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Entry
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Format
```

with:

```python
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Date
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Time
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Distance
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Store
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)           # Event
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Entry
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Format
```

- [ ] **Step 3: Rewrite `_populate_table`**

Replace the entire `_populate_table` method with:

```python
    def _populate_table(self, events: list[dict]):
        from gui.widgets.table_helpers import DateItem, NumItem, SortItem, SORT_ROLE
        from PyQt6.QtGui import QColor

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(events))

        # Soft navy tint for RCQ rows — keeps the dark theme readable.
        rcq_bg = QColor(theme.ACCENT_DK)
        rcq_bg.setAlpha(60)  # subtle wash

        for row, e in enumerate(events):
            # Date column: display "Sat Jun 7", sort by "20260607".
            iso = e.get("date", "")
            display_date = iso
            if iso and len(iso) == 10:
                from datetime import date as _d
                try:
                    parts = iso.split("-")
                    d_obj = _d(int(parts[0]), int(parts[1]), int(parts[2]))
                    # Cross-platform "Mon D" with no leading zero.
                    display_date = f"{d_obj.strftime('%b')} {d_obj.day}"
                except (ValueError, IndexError):
                    display_date = iso
            weekday = e.get("weekday", "")
            if weekday:
                display_date = f"{weekday} {display_date}"
            date_sort = iso.replace("-", "") if iso else ""
            date_item = DateItem(display_date, sort_key=date_sort)

            # Time column: sortable via SortItem + 24h key.
            time_str = e.get("time_str", "")
            time_item = SortItem(time_str)
            time_item.setData(SORT_ROLE, time_sort_key(time_str))

            # Distance column: numeric sort, "25 mi" display.
            dist_mi = e.get("dist_mi", 0.0) or 0.0
            dist_item = SortItem(f"{dist_mi:.0f} mi")
            dist_item.setData(SORT_ROLE, float(dist_mi))

            # Store / Event: plain.
            store_item = QTableWidgetItem(e.get("store", "?"))
            event_item = QTableWidgetItem(e.get("title", "?"))

            # Entry: numeric sort, dollar display, "—" for missing.
            fee_str = e.get("fee", "") or ""
            if fee_str.startswith("$"):
                try:
                    fee_num = float(fee_str[1:])
                except ValueError:
                    fee_num = 0.0
                fee_display = fee_str
            else:
                fee_num = 0.0
                fee_display = "—"
            entry_item = SortItem(fee_display)
            entry_item.setData(SORT_ROLE, fee_num)

            # Format: prefer eventFormat.id, fallback to tag scan.
            fmt_id = e.get("format_id", "") or ""
            if fmt_id:
                fmt_str = fmt_id.replace("_", " ").title()
            else:
                fmt_tags = [t for t in e.get("raw_tags", [])
                            if t in ("modern", "standard", "pioneer", "legacy", "pauper",
                                     "booster_draft", "commander", "historic", "explorer")]
                fmt_str = ", ".join(t.replace("_", " ").title() for t in fmt_tags) or "—"
            fmt_item = QTableWidgetItem(fmt_str)

            cells = [date_item, time_item, dist_item, store_item,
                     event_item, entry_item, fmt_item]
            for col, item in enumerate(cells):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if "regional_championship_qualifier" in e.get("raw_tags", []):
                    item.setBackground(rcq_bg)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
```

- [ ] **Step 4: Manually smoke-test the GUI**

Launch the app: `python run_gui.py`
Navigate to: Tournament tab -> Event Finder sub-tab (or wherever it is in the current build).
Enter zipcode 20001, radius 100, type RCQ, click Find Events.
Verify:
1. Date column shows "Sat Jun 7"-style entries.
2. Time column shows local-time strings.
3. Clicking the Distance column header sorts numerically (25 mi before 100 mi).
4. Clicking the Entry column header sorts numerically.
5. RCQ rows have a subtle navy background.
6. No exceptions in the terminal.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/event_finder_tab.py
git commit -m "feat(event-finder): fix sort, add Time column, tint RCQ rows"
```

---

## Task 6: Add "When" combobox + integrate with filter

**Why now:** Helpers exist (Task 1), `_format_event` carries the right dates (Task 2), state key exists (Task 4). Now wire the new combo into the controls row and the fetch pipeline.

**Files:**
- Modify: `gui/tabs/event_finder_tab.py` (`_build_controls`, `_search`, `_fetch_events`)

- [ ] **Step 1: Add the "When" combobox in `_build_controls`**

In `gui/tabs/event_finder_tab.py`, inside `_build_controls`, insert a new "When" combo **after** the Format combo block and **before** `row.addStretch()`. The new block:

```python
        # Date window
        row.addWidget(self._lbl("When"))
        self._when = QComboBox()
        for label, value in DATE_WINDOW_OPTIONS:
            self._when.addItem(label, value)
        self._when.setCurrentIndex(1)  # default Next 4 wk
        self._when.setFixedWidth(120)
        self._when.setStyleSheet(self._combo_style())
        row.addWidget(self._when)
```

- [ ] **Step 2: Pass the date-window key through `_search`**

In the `_search` method, replace the kwargs construction with:

```python
        radius      = self._radius.currentData()
        event_type  = self._etype.currentData()
        fmt         = self._fmt.currentData()
        date_window = self._when.currentData()

        self._worker = DataLoadWorker(
            _fetch_events,
            kwargs={"zipcode": zipcode, "radius": radius,
                    "event_type": event_type, "format_filter": fmt,
                    "date_window": date_window},
        )
```

- [ ] **Step 3: Apply the filter in `_fetch_events`**

Replace the existing `_fetch_events` with:

```python
def _fetch_events(zipcode: str, radius: int, event_type: str | None,
                  format_filter: str | None, date_window: str = "4w") -> list[dict]:
    """Called in DataLoadWorker background thread."""
    from scrapers.event_finder import geocode_zipcode, search_events, _format_event

    lat, lng = geocode_zipcode(zipcode)
    tags = [event_type] if event_type else None
    raw = search_events(lat, lng, radius_miles=radius, tags=tags, limit=500)

    # Apply format filter and exclude online
    results = []
    for e in raw:
        fe = _format_event(e)
        if fe["online"]:
            continue
        if format_filter:
            if format_filter.lower() not in [t.lower() for t in fe["raw_tags"]]:
                continue
        results.append(fe)

    results = filter_by_date_window(results, date_window)
    results.sort(key=lambda x: (x["date"], x["dist_mi"]))
    return results
```

- [ ] **Step 4: Update `_on_results` status line to mention the window**

In `_on_results`, replace the existing status block with:

```python
    def _on_results(self, events: list[dict]):
        self._events = events
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._populate_table(events)
        type_label = self._etype.currentText()
        fmt_label  = self._fmt.currentText()
        when_label = self._when.currentText()
        r          = self._radius.currentData()
        fmt_part   = f" ({fmt_label})" if fmt_label != "All Formats" else ""
        self._set_status(
            f"{len(events)} {type_label} event(s) within {r} mi, {when_label}{fmt_part}"
        )
```

- [ ] **Step 5: Manually smoke-test**

Launch app, open Event Finder, run a 300 mi RCQ search. Switch the When combo between "Next 2 wk" / "Next 4 wk" / "All upcoming" and click Find Events each time. Verify:
1. Result count drops as the window narrows.
2. Status line includes the When label.

- [ ] **Step 6: Commit**

```bash
git add gui/tabs/event_finder_tab.py
git commit -m "feat(event-finder): add When date-window filter"
```

---

## Task 7: UIState hydration + persistence for all filters

**Why now:** All filter widgets exist. Wire them to UIState last so the wiring covers every control in one pass.

**Files:**
- Modify: `gui/tabs/event_finder_tab.py` (`__init__`, `showEvent` (new), per-widget change handlers)

- [ ] **Step 1: Import state keys**

At the top of `gui/tabs/event_finder_tab.py`, alongside the other imports, add:

```python
from gui.state import UIState
from gui import state_keys as k
```

- [ ] **Step 2: Add a `showEvent` hydration method**

Add this method to `EventFinderTab`, right above `_build_ui`:

```python
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_state_hydrated", False):
            return
        s = UIState.instance()

        # Zipcode
        zipcode = s.get(k.EVENT_FINDER_ZIPCODE, "")
        self._zip.blockSignals(True)
        self._zip.setText(zipcode)
        self._zip.blockSignals(False)

        # Radius (find by data value)
        radius = s.get(k.EVENT_FINDER_RADIUS, 100)
        idx = self._radius.findData(radius)
        if idx >= 0:
            self._radius.blockSignals(True)
            self._radius.setCurrentIndex(idx)
            self._radius.blockSignals(False)

        # Event type
        etype = s.get(k.EVENT_FINDER_EVENT_TYPE, "regional_championship_qualifier")
        idx = self._etype.findData(etype)
        if idx >= 0:
            self._etype.blockSignals(True)
            self._etype.setCurrentIndex(idx)
            self._etype.blockSignals(False)

        # Format
        fmt = s.get(k.EVENT_FINDER_FORMAT, "modern")
        idx = self._fmt.findData(fmt)
        if idx >= 0:
            self._fmt.blockSignals(True)
            self._fmt.setCurrentIndex(idx)
            self._fmt.blockSignals(False)

        # When
        when = s.get(k.EVENT_FINDER_DATE_WINDOW, "4w")
        idx = self._when.findData(when)
        if idx >= 0:
            self._when.blockSignals(True)
            self._when.setCurrentIndex(idx)
            self._when.blockSignals(False)

        self._state_hydrated = True
```

- [ ] **Step 3: Wire write-back on every change**

At the bottom of `_build_controls` (just before `return frame`), wire signals for each widget:

```python
        # Persist filter changes to UIState
        s = UIState.instance()
        self._zip.textEdited.connect(
            lambda txt: s.set(k.EVENT_FINDER_ZIPCODE, txt))
        self._radius.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_RADIUS, self._radius.currentData()))
        self._etype.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_EVENT_TYPE, self._etype.currentData()))
        self._fmt.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_FORMAT, self._fmt.currentData()))
        self._when.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_DATE_WINDOW, self._when.currentData()))
```

- [ ] **Step 4: Manually smoke-test persistence**

Launch app. Open Event Finder. Set zipcode 98101, radius 300 mi, type Store Championship, format Standard, when "Next 8 wk". Close the app. Relaunch. Open Event Finder. Verify every filter is restored.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/event_finder_tab.py
git commit -m "feat(event-finder): persist filters across sessions via UIState"
```

---

## Task 8: Right-click context menu — Open in Google Maps

**Why last:** Smallest, most isolated change. No upstream dependencies once `_format_event` carries `city`/`state` (Task 2) and the helper exists (Task 1).

**Files:**
- Modify: `gui/tabs/event_finder_tab.py` (`_build_table`, new handler `_show_context_menu`)

- [ ] **Step 1: Enable custom context menu in `_build_table`**

In `gui/tabs/event_finder_tab.py`, locate `_build_table`. **Before** `tbl.cellDoubleClicked.connect(...)`, insert:

```python
        tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tbl.customContextMenuRequested.connect(self._show_context_menu)
```

- [ ] **Step 2: Add the menu handler**

Add this method to `EventFinderTab` (near `_open_event_url`):

```python
    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._events):
            return
        e = self._events[row]

        menu = QMenu(self._table)

        a_event = QAction("Open event page", menu)
        a_event.triggered.connect(lambda: self._open_event_url(row, 0))
        menu.addAction(a_event)

        a_maps = QAction("Open in Google Maps", menu)
        a_maps.triggered.connect(lambda: self._open_in_maps(row))
        menu.addAction(a_maps)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _open_in_maps(self, row: int):
        if row < 0 or row >= len(self._events):
            return
        e = self._events[row]
        store = e.get("store", "")
        city = e.get("city", "")
        if not store:
            return
        url = google_maps_url(store, city)
        QDesktopServices.openUrl(QUrl(url))
```

- [ ] **Step 3: Manually smoke-test**

Launch app. Open Event Finder. Run a search. Right-click a row. Verify:
1. Context menu appears with "Open event page" and "Open in Google Maps".
2. Clicking "Open in Google Maps" opens a browser to the store's location.
3. Clicking "Open event page" still works (same as the old double-click behavior).
4. Right-click outside any row does nothing.

- [ ] **Step 4: Commit**

```bash
git add gui/tabs/event_finder_tab.py
git commit -m "feat(event-finder): right-click row -> Open in Google Maps"
```

---

## Final verification

- [ ] **Run full test suite**

Run: `pytest tests/test_event_finder_ux.py -v`
Expected: 26 passed (all helper + format_event + GraphQL + radius + UIState tests).

Run: `pytest -q`
Expected: every previously-passing test still passes (no regressions).

- [ ] **Update CLAUDE.md**

Per project convention (`E:\vscode ai project\mtg-meta-analyzer\CLAUDE.md` -> "NON-NEGOTIABLE RULES"): update the top-of-file "Last updated" line to mention the Event Finder UX fix. Mention: sort fix, Time column, RCQ row tint, "When" filter, 300 mi radius, Google Maps right-click, persisted filters.

- [ ] **Update NEXT_STEPS.md and ROADMAP.md**

Per the same NON-NEGOTIABLE RULES, reflect the completion of this work.

- [ ] **Final commit + push**

```bash
git add CLAUDE.md NEXT_STEPS.md ROADMAP.md
git commit -m "docs: event-finder UX fix shipped"
git push
```

---

## Self-review notes

**Spec coverage check:** Every numbered item in the spec maps to at least one task:
1. Sort fix -> Task 5.
2. Already-queried data surfaced -> Task 2 (`start_iso`, `time_str`, `weekday`, `format_id`).
3. Date-window filter -> Tasks 1 (helper) + 6 (UI).
4. RCQ highlight -> Task 5.
5. Persisted filters -> Tasks 4 + 7.
6. 300 mi radius + limit bump -> Task 3.
7. Per-row Google Maps -> Tasks 1 (helper) + 2 (city/state from API) + 8 (UI).

**Type consistency:** `filter_by_date_window`, `time_sort_key`, `google_maps_url` keep the same signatures from Task 1 through every downstream task. `DATE_WINDOW_OPTIONS` keys (`"2w"`, `"4w"`, `"8w"`, `"6mo"`, `"all"`) match `_DATE_WINDOW_DAYS` and the UIState default. `EVENT_FINDER_*` constant names match between `state_keys.py` and Task 7's `showEvent`.

**Placeholders:** None remain. Every code step contains the actual code to paste; every test step contains the actual test body.
