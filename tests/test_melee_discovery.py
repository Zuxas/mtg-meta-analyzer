"""Melee.gg tournament discovery + round parsing (2026-10-01 match-gap fix).

Live evidence (captured 2026-10-01, read-only probes):
  * TournamentSearch is deterministic, returns rows ascending by id and ignores `ordering`,
    BUT it serves offset (start // length) * length -- it snaps `start` DOWN to a multiple of
    `length` (and caps `length` at 500).  The scraper asked for start = total - 100*(page+1)
    (1051 for 1,151 rows), was served rows 1000-1099, and never saw the newest
    `total % 100` rows -- where every event since 2026-09-14 sat (448946, 467590, 467594),
    plus the China RC (451148) and both Dallas RCQ flights (462365 / 462366).
  * SCG's "$1K Modern RCQ - SCG CON Dallas" (442749) is a registration shell: its public page
    has no pairings section at all; the event was split into "FLIGHT A/B" tournaments
    (462365 / 462366) that use the normal round-selector markup.
Fixtures are sanitized (tournament metadata and round markup only; no player data).
"""
import json
import os

import pytest

import scrapers.mtgmelee_scraper as mm

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "melee")


def _search_fixture():
    d = json.load(open(os.path.join(FIX, "tournament_search_modern_2026-10-01.json"), encoding="utf-8"))
    first = d["first_position"]
    # positions before the captured tail: synthetic old (2023) rows with small ids
    old = [{"id": 1000 + i, "name": f"Old event {i}", "startDate": "2023-01-01T00:00:00Z",
            "enrolledPlayerCount": 40, "formatString": "Modern", "gameDescription": "Magic: The Gathering",
            "status": "Ended"} for i in range(first)]
    return old + d["rows"], d["recordsTotal"]


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class SnappingServer:
    """Fake TournamentSearch with the live server's paging rule: offset = start // length * length,
    length capped at 500, rows ascending by id."""

    def __init__(self, rows, total=None, transform=None):
        self.rows = rows
        self.total = len(rows) if total is None else total
        self.transform = transform
        self.calls = []

    def post(self, url, data=None, timeout=None, **kw):
        start, length = int(data["variables[start]"]), min(500, int(data["variables[length]"]))
        self.calls.append((start, length))
        off = (start // length) * length
        page = self.rows[off:off + length]
        if self.transform:
            page = self.transform(off, page)
        return _Resp({"recordsTotal": self.total, "recordsFiltered": self.total, "data": page})

    def get(self, *a, **k):
        raise AssertionError("no GET expected")


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(mm.time, "sleep", lambda s: None)


def _discover(monkeypatch, server, pages=3, min_players=32):
    monkeypatch.setattr(mm, "_session", lambda: server)
    return mm.fetch_tournament_list("modern", min_players, pages)


# ------------------------------------------------------------------ discovery
def test_captured_search_discovers_the_september_19_20_events(monkeypatch, no_sleep):
    rows, total = _search_fixture()
    assert total == len(rows) == 1151
    found = _discover(monkeypatch, SnappingServer(rows))
    ids = [t["id"] for t in found]
    for tid in ("448946", "467590", "467594", "451148", "462365", "462366"):
        assert tid in ids, tid
    assert len(ids) == len(set(ids))                                     # deduplicated
    dates = [t["date"] for t in found]
    assert dates == sorted(dates, reverse=True) and dates[0] == "2026-09-20"   # newest first


def test_requests_are_page_aligned_and_bounded(monkeypatch, no_sleep):
    rows, _total = _search_fixture()
    server = SnappingServer(rows)
    _discover(monkeypatch, server, pages=3)
    page_calls = [c for c in server.calls if c[1] > 1]
    assert all(start % length == 0 for start, length in page_calls)     # the server would snap anything else
    assert len(server.calls) <= 3 + 2                                    # pages + probe + one re-check


def test_the_old_unaligned_window_really_misses_them():
    """Documents the root cause against the fake server: start=1051 is served from 1000."""
    rows, total = _search_fixture()
    page = SnappingServer(rows).post(None, data={"variables[start]": "1051", "variables[length]": "100"}).json()
    ids = {r["id"] for r in page["data"]}
    assert not ids & {448946, 467590, 467594}


def test_discovery_tolerates_reordered_overlapping_and_inconsistent_pages(monkeypatch, no_sleep):
    rows, total = _search_fixture()

    def chaos(off, page):
        page = list(reversed(page))                                      # reordered
        if off >= 100:
            page = page + rows[off - 3:off]                              # overlaps the previous page
        return page + page[:2]                                           # duplicates within a page
    server = SnappingServer(rows, total=total + 7, transform=chaos)      # recordsTotal disagrees with rows
    found = _discover(monkeypatch, server, pages=4)
    ids = [t["id"] for t in found]
    assert len(ids) == len(set(ids))
    assert {"448946", "467590", "467594"} <= set(ids)
    dates = [t["date"] for t in found]
    assert dates == sorted(dates, reverse=True)
    assert len(server.calls) <= 4 + 2


def test_pages_argument_and_cli_are_unchanged(monkeypatch, no_sleep):
    rows, _total = _search_fixture()
    server = SnappingServer(rows)
    monkeypatch.setattr(mm, "_session", lambda: server)
    one = mm.fetch_tournament_list("modern", 32, 1)                      # positional (format, min_players, pages)
    assert {"467590", "467594"} <= {t["id"] for t in one}
    seen = {}
    monkeypatch.setattr(mm, "scrape_and_store", lambda **kw: seen.update(kw))
    mm.main(["--format", "modern", "--pages", "3", "--dry-run"])
    assert seen == {"format_name": "modern", "pages": 3, "min_players": 32, "dry_run": True}


def test_min_players_filter_still_applies(monkeypatch, no_sleep):
    rows, _total = _search_fixture()
    found = _discover(monkeypatch, SnappingServer(rows), pages=1, min_players=40)
    assert found and all(t["player_count"] >= 40 for t in found)
    assert "448946" not in {t["id"] for t in found}                      # 34 players


# ------------------------------------------------------------------ round parsing
def _html(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


def test_existing_markup_yields_started_pairing_rounds_only():
    rounds, reason = mm._parse_round_ids(_html("view_447684_standard_markup.html"))
    assert reason == "ok"
    assert [n for _r, n in rounds] == ["Round 1", "Round 2", "Round 3", "Round 4", "Round 5",
                                       "Quarterfinals", "Semifinals", "Finals"]
    assert len({r for r, _n in rounds}) == 8                             # standings duplicates excluded


def test_scg_flight_markup_yields_started_rounds_and_rejects_unstarted_ones():
    html = _html("view_462365_scg_flight_a.html")
    anchor = '<div class="round-selector-container" id="pairings-round-selector-container">'
    if anchor not in html:
        anchor = '<div id="pairings-round-selector-container" class="round-selector-container">'
    assert anchor in html
    unstarted = ('<button class="btn btn-gray round-selector" data-id="9999999" data-is-started="False" '
                 'data-name="Round 8">Round 8</button>')
    html = html.replace(anchor, anchor + unstarted, 1)                   # an unstarted round in the pairings
    rounds, reason = mm._parse_round_ids(html)
    assert reason == "ok" and len(rounds) == 10
    assert 9999999 not in {r for r, _n in rounds}
    assert rounds[-1][1] == "Finals" and all(isinstance(r, int) for r, _n in rounds)


def test_scg_registration_shell_reports_no_public_pairings():
    rounds, reason = mm._parse_round_ids(_html("view_442749_scg_registration_shell.html"))
    assert rounds == [] and reason == "no-pairings-section"
