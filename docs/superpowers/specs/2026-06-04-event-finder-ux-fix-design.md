# Event Finder UX Fix — Design

Date: 2026-06-04
Owner: pilot
Scope: Surgical UX fix to `gui/tabs/event_finder_tab.py` + `scrapers/event_finder.py`.
Status: Draft (awaiting user review)

## Summary

Fix the four UX problems with the Event Finder tab:

1. **Sorting is broken** — Distance and Entry columns sort as strings.
2. **Already-queried data is thrown away** — `eventFormat.id` and the time-of-day portion of `scheduledStartTime` are fetched then discarded.
3. **Filters are too coarse** — no date window, so a 200 mi search can return events 4+ months out.
4. **Layout/polish** — RCQ highlight is just a foreground tint, easy to miss; filters do not persist across sessions.

Plus two user-requested additions:

5. **Extend max radius from 200 mi to 300 mi.**
6. **Add per-row "Open in Google Maps" right-click action** so a single event can be inspected visually.

Out of scope (would belong to Approach B+): bookmarking / save column, CSV/.ics export, background polling, Tournament Prep integration, embedded map view, multi-event map page, geocode caching for stores.

## Motivation

The current tab is functional but rough. Concrete issues observed in the code:

- `gui/tabs/event_finder_tab.py:282` — Distance cell is `f"{e['dist_mi']:.0f} mi"`, a string, so `QTableWidget` lex-sorts `"100 mi"` before `"25 mi"`.
- `gui/tabs/event_finder_tab.py:285` — Entry cell is `e["fee"] or "—"`, a string like `"$25"`, also lex-sorted.
- `scrapers/event_finder.py:130` — GraphQL query asks for `eventFormat { id }` but `_format_event` never reads it; the Format column is reconstructed by tag scanning at `gui/tabs/event_finder_tab.py:275-278`.
- `scrapers/event_finder.py:175` — `scheduledStartTime` is sliced to `[:10]`, throwing away the wall-clock time.
- No "next N weeks" filter exists at all — the only filter that bounds time is the API's own upcoming-events scope, which can be wide.
- RCQ rows are highlighted only by tinting the foreground via `theme.ACCENT_LT` (`gui/tabs/event_finder_tab.py:292-295`). On the dark theme this is subtle.
- Filters reset every time the tab is reopened; no `UIState` integration.

## Design

### Column structure

New column set (left to right):

```
Date | Time | Distance | Store | Event | Entry | Format
```

- **Date** — `DateItem(display="Sat Jun 7", sort_key="20260607")`. Display is short and human; sort key is ISO-derived, so column-header sort is correct.
- **Time** — new column. Parsed from the full `scheduledStartTime` (UTC) and rendered in the user's local timezone as `"6:00 PM"`. Uses `SortItem` with `SORT_ROLE` set to a 24-hour `"HH:MM"` string so `"11:00 PM"` (sort key `"23:00"`) sorts after `"9:00 AM"` (sort key `"09:00"`).
- **Distance** — `NumItem` whose `text()` is `"25 mi"` but whose sort role is the raw float `dist_mi`. (`NumItem` already strips trailing non-digit characters; storing the float directly via `SORT_ROLE` is cleaner here.)
- **Store, Event** — unchanged `QTableWidgetItem`.
- **Entry** — `NumItem` storing the numeric fee in dollars (0 for missing). Display "—" for missing.
- **Format** — pulled from `eventFormat.id` first (single normalized value like `"modern"`), falling back to the existing tag-scan if `eventFormat.id` is null. Displayed Title-Cased.

### Sorting fix

Use the existing helpers in `gui/widgets/table_helpers.py` (`NumItem`, `DateItem`, `SORT_ROLE`). The fix is purely in `_populate_table`; no schema or scraper changes required for sorting alone.

Default sort: ascending by Date.

### Date-window filter

A new "When" `QComboBox` in the controls row, matching `theme.TIMEFRAME_OPTIONS` style:

| Label         | Behavior                                  |
| ------------- | ----------------------------------------- |
| Next 2 wk     | `start <= today + 14d`                    |
| Next 4 wk     | `start <= today + 28d` (default)          |
| Next 8 wk     | `start <= today + 56d`                    |
| Next 6 mo     | `start <= today + 183d`                   |
| All upcoming  | no upper bound (current behavior)         |

Applied client-side in `_fetch_events` after the GraphQL call (the API does not expose a date-range parameter on this endpoint). Past events are already filtered out by `searchEvents` upstream — no change needed there.

### Radius bump

`_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200, 300]`. Default remains 100 mi.

Bump the API result cap from `limit=200` to `limit=500` in `_fetch_events` so a 300 mi search has headroom. The date-window filter and the on-screen distance sort make 500 raw results manageable.

### RCQ highlight

Replace the foreground tint with a subtle full-row background. After populating each row, if `"regional_championship_qualifier" in e["raw_tags"]`, set every cell's `setBackground(...)` to a color derived from `theme.ACCENT_DK` with low alpha (e.g. `QColor(theme.ACCENT_DK).darker(110)` or a hand-picked `#1A2434`-ish navy that reads as "tinted"). The accent foreground on the Type cell is removed since the row background now carries the signal.

Store Championships are not highlighted (they are already filtered in by user choice, and double-highlighting muddles the signal).

### Per-row "Open in Google Maps"

Add a right-click context menu to `self._table` with a single action: **Open in Google Maps**.

URL pattern: `https://www.google.com/maps/search/?api=1&query=<URL-encoded>` where the query is `f"{store_name} {city}"` if a city is available, otherwise just the store name. Google's fuzzy search handles ambiguous queries fine.

City source: the GraphQL query is extended to fetch `venue { city state }` (or whichever field the API actually exposes — to be confirmed during implementation; if no address field exists, we fall back to store name alone, which Google still resolves correctly for any registered WPN store).

The context menu is wired via `self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)` + `customContextMenuRequested.connect(...)`.

### Persisted filter state

New constants in `gui/state_keys.py`:

```python
EVENT_FINDER_ZIPCODE     = "tabs.event_finder.zipcode"
EVENT_FINDER_RADIUS      = "tabs.event_finder.radius"
EVENT_FINDER_EVENT_TYPE  = "tabs.event_finder.event_type"
EVENT_FINDER_FORMAT      = "tabs.event_finder.format"
EVENT_FINDER_DATE_WINDOW = "tabs.event_finder.date_window"
```

Hydration follows the same pattern documented in `CLAUDE.md` Section 6 ("Persisted UI state"):

- `showEvent` reads all five via `UIState.get(path, default)`.
- Each widget is wrapped in `blockSignals(True)` while the saved value is applied, then signals are re-enabled.
- On any widget change (`textEdited`, `currentIndexChanged`), the new value is written back via `UIState.set(path, value)`.

`UIState` is schema-tolerant: missing paths return the default, so first-launch users see the documented defaults (radius 100 mi, type RCQ, format Modern, window Next 4 wk, empty zipcode).

## API changes (`scrapers/event_finder.py`)

1. **GraphQL query** gains `venue { city state }` (field name confirmed during implementation; if not available, omit and accept the store-name-only fallback). Also keeps the existing `eventFormat { id }` field which is already there.
2. **`_format_event`** returns the additional keys:
   - `start_iso` — the full `scheduledStartTime` (so the tab can parse Date + Time without re-fetching).
   - `weekday` — three-letter abbreviation in user local tz (e.g. `"Sat"`).
   - `time_str` — local wall-clock time (e.g. `"6:00 PM"`).
   - `format_id` — `eventFormat.id` or `""`.
   - `city`, `state` — from `venue` if present, else `""`.
3. **`search_events`** signature unchanged. Internal `limit` default stays 50 for CLI; the GUI explicitly passes `limit=500`.

The CLI (`python -m scrapers.event_finder ...`) continues to work; the print path uses the new fields if present and falls back gracefully if not (the new fields are additive).

## Data flow

```
User edits any filter
  -> on-change handler writes the new value via UIState.set(...)
  -> user clicks "Find Events" (or presses Enter in zipcode)
  -> _search() snapshots all filter values, cancels any in-flight worker,
     spawns DataLoadWorker(_fetch_events, kwargs=...)
  -> _fetch_events runs on background thread:
       geocode_zipcode -> search_events -> [_format_event for each]
       -> client-side filters: not online, format match, date window
       -> sort by (date, dist_mi)
  -> result signal -> _on_results -> _populate_table
       -> rows built with DateItem / NumItem / QTableWidgetItem
       -> RCQ rows get row-background tint
  -> right-click row -> context menu -> "Open in Google Maps" -> QDesktopServices.openUrl(...)
```

## Testing

Unit tests (new file `tests/test_event_finder_ux.py`):

1. **Date-window filter** — given a synthetic events list spanning today + 0/10/30/60/200 days, assert that each window setting includes the right subset.
2. **Distance sort key** — assert `NumItem` for `25 mi` sorts before `100 mi`.
3. **`_format_event` shape** — given a stub GraphQL response, assert that `start_iso`, `weekday`, `time_str`, `format_id`, `city`, `state` are present, and that missing-input cases (no `eventFormat`, no `venue`, no `entryFee`) degrade to empty strings rather than raising.
4. **UIState roundtrip** — set all five `EVENT_FINDER_*` keys via `UIState.set`, re-read via `UIState.get`, assert echoed values.
5. **Google Maps URL builder** — assert the URL is correctly formed for `(store, city)`, `(store, "")`, and that special characters are URL-encoded.

No Qt-level snapshot tests. Manual smoke after merge: open the tab, run a 300 mi RCQ search, sort by Distance, confirm a 4 wk window keeps the list short, right-click a row and confirm Google Maps opens to a sane result.

## Risk

- **Venue address field name unknown.** The GraphQL schema for `silverbeak-griffin-service` is undocumented. If `venue { city state }` is not the right field, the implementation falls back to store-name-only Google Maps queries — still useful, just less precise. Probe in the first implementation step before relying on it.
- **API limit of 500.** If WPN caps `pageSize` lower than 500, the request will fail or be silently truncated. Detect via `pageInfo.totalResults` (already in the query) and surface a status line like `"showing 500 of 642 — narrow your filters"`.
- **Timezone parsing.** `scheduledStartTime` is ISO 8601 with timezone info; converting to local is straightforward (`datetime.fromisoformat` + `astimezone()`). Test on a non-UTC machine.
