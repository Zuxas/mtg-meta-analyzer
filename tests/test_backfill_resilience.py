"""MTGTop8 backfill: a fetch failure must never masquerade as end-of-data.

On 2026-09-21 a DNS blip mid-run made `_scrape_year_page` return
`([], hit_cutoff=True)` for every listing page after it, so every remaining
year and format "reached the cutoff" in seconds and fill_database.py printed
COMPLETE with exit 0 -- four formats at +0 events. Listing-page failures now
retry with backoff and then ABORT the format loudly; fill_database reports
INCOMPLETE and exits non-zero when any format failed.
"""
from datetime import datetime, timedelta

import pytest

import scrapers.backfill as bf


class _Resp:
    def __init__(self, text: str):
        self.text = text


EMPTY_PAGE = _Resp("<html><body></body></html>")


@pytest.fixture
def quiet_backfill(monkeypatch, tmp_path):
    """No DB, no config, no sleeping; 30-day cutoff so only the current year runs."""
    monkeypatch.setattr(bf, "_get_existing_source_ids", lambda: set())
    monkeypatch.setattr(bf, "_load_cutoff", lambda fmt: datetime.now() - timedelta(days=30))
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setattr(bf, "_bad_events_path", lambda: tmp_path / "backfill_bad_events.json")


def test_scrape_year_page_raises_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: None)
    with pytest.raises(bf.BackfillFetchError):
        bf._scrape_year_page("modern", 339, 1, datetime(2023, 9, 22), set())


def test_run_backfill_retries_listing_page_then_aborts_the_format(monkeypatch, quiet_backfill):
    calls = []
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: calls.append(url) or None)
    with pytest.raises(bf.BackfillFetchError):
        bf.run_backfill("modern")
    # retried the SAME listing page, then gave up -- it did not slide to the
    # next year. (The one extra call is the format-page year->meta lookup.)
    listing = [u for u in calls if "&meta=" in u]
    assert len(listing) == bf.PAGE_FETCH_ATTEMPTS
    assert len(set(listing)) == 1


def test_run_backfill_recovers_from_a_transient_failure(monkeypatch, quiet_backfill):
    seq = iter([None, None] + [EMPTY_PAGE] * 20)            # listing pages only
    monkeypatch.setattr(bf, "_get",
                        lambda url, retries=3: EMPTY_PAGE if "&meta=" not in url else next(seq))
    summary = bf.run_backfill("modern")
    assert summary["events"] == 0 and summary["decks"] == 0
    assert summary["transient_failures"] == 2
    assert summary["years"] == [datetime.now().year]


def test_run_backfill_unknown_format_is_reported_not_silent(monkeypatch, quiet_backfill):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: None)    # live page unreachable
    monkeypatch.delitem(bf.YEAR_META, "vintage")                    # and no fallback row
    with pytest.raises(bf.BackfillConfigError):
        bf.run_backfill("vintage")


def test_fill_database_reports_incomplete_when_a_format_fails(monkeypatch, capsys):
    import fill_database
    monkeypatch.setattr(fill_database, "step_init", lambda: None)
    monkeypatch.setattr(fill_database, "step_scryfall_download", lambda: None)
    monkeypatch.setattr(fill_database, "step_mtgtop8_backfill", lambda: ["modern", "pauper"])
    monkeypatch.setattr(fill_database, "step_enrich", lambda: None)
    monkeypatch.setattr(fill_database, "step_normalize", lambda: None)
    monkeypatch.setattr(fill_database, "print_summary", lambda t: None)
    with pytest.raises(SystemExit) as exc:
        fill_database.main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "INCOMPLETE" in out and "modern" in out and "pauper" in out


def test_fill_database_exits_zero_when_all_formats_succeed(monkeypatch):
    import fill_database
    for name in ("step_init", "step_scryfall_download", "step_enrich", "step_normalize"):
        monkeypatch.setattr(fill_database, name, lambda: None)
    monkeypatch.setattr(fill_database, "step_mtgtop8_backfill", lambda: [])
    monkeypatch.setattr(fill_database, "print_summary", lambda t: None)
    fill_database.main()      # returns normally


# ---------------------------------------------------------------------------
# Year -> meta ids come from the live format page, not a hand-typed table
# ---------------------------------------------------------------------------

FORMAT_PAGE = _Resp("""
<a href="?f=MO&meta=339&a="><div style="padding:3px;" class="S14 hover_tr">All 2026 Decks</div></a>
<a href="?f=MO&meta=315&a="><div style="padding:3px;" class="S14 hover_tr">All 2025 Decks</div></a>
<a href="?f=MO&meta=304&a="><div style="padding:3px;" class="S14 hover_tr">Last 5 Days</div></a>
<a href="?f=MO&meta=276&a="><div style="padding:3px;" class="S14 hover_tr">All 2024 Decks</div></a>
<a href="?f=PI&meta=314&a="><div style="padding:3px;" class="S14 hover_tr">All 2025 Decks</div></a>
""")


def test_fetch_year_metas_parses_only_this_formats_year_links(monkeypatch):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: FORMAT_PAGE)
    assert bf.fetch_year_metas("modern") == {2026: 339, 2025: 315, 2024: 276}


def test_fetch_year_metas_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: None)
    assert bf.fetch_year_metas("modern") == {}


def test_hardcoded_year_meta_matches_the_live_values_captured_2026_09_21():
    """The old table was extrapolated (Standard minus 1/2/3) and was wrong for
    Pioneer/Modern/Legacy 2022-2025 -- every historical backfill of those years
    re-listed the CURRENT year instead. Pin the corrected fallback table."""
    assert bf.YEAR_META["modern"][2025] == 315 and bf.YEAR_META["modern"][2024] == 276
    assert bf.YEAR_META["pioneer"][2025] == 314 and bf.YEAR_META["legacy"][2025] == 316
    assert bf.YEAR_META["pauper"][2026] == 342 and bf.YEAR_META["vintage"][2026] == 337


def test_run_backfill_prefers_live_metas_and_warns_on_disagreement(monkeypatch, quiet_backfill, capsys):
    seen = []
    def fake_get(url, retries=3):
        seen.append(url)
        if "&meta=" not in url:          # the format page
            return FORMAT_PAGE
        return EMPTY_PAGE
    monkeypatch.setattr(bf, "_get", fake_get)
    monkeypatch.setitem(bf.YEAR_META, "modern", {**bf.YEAR_META["modern"], 2026: 999})   # stale table
    bf.run_backfill("modern")
    assert any("meta=339" in u for u in seen) and not any("meta=999" in u for u in seen)
    assert "YEAR_META" in capsys.readouterr().out      # told us the table is stale


def test_run_backfill_falls_back_to_table_when_format_page_fails(monkeypatch, quiet_backfill, capsys):
    seen = []
    def fake_get(url, retries=3):
        seen.append(url)
        return None if "&meta=" not in url else EMPTY_PAGE
    monkeypatch.setattr(bf, "_get", fake_get)
    bf.run_backfill("modern")
    assert any(f"meta={bf.YEAR_META['modern'][datetime.now().year]}" in u for u in seen)
    assert "fallback" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# An event is stored only if FULLY fetched; partial fetches roll back so the
# next run re-fetches the whole event (existing_ids would otherwise skip it
# forever: 17 zero-deck events + one event with 14 card-less decks on 09-21)
# ---------------------------------------------------------------------------

@pytest.fixture
def real_db(tmp_path, monkeypatch):
    import db.database as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "t.db"))
    dbm.init_db()
    return dbm


EV = {"source_id": "90486", "name": "MTGO Challenge 32", "date": "15/09/26",
      "url": "https://www.mtgtop8.com/event?e=90486&f=MO"}
DECKS = [{"source_id": f"8868{i}", "player": f"p{i}", "archetype": "Boros Energy",
          "placement": i, "url": f"https://www.mtgtop8.com/event?e=90486&d=8868{i}&f=MO"} for i in range(1, 4)]
CARDS = ({"Lightning Bolt": 4}, {"Wear // Tear": 2})


def _counts(dbm):
    with dbm.get_connection() as c:
        return (c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM decks").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0])


def test_process_event_stores_a_fully_fetched_event(real_db, monkeypatch):
    monkeypatch.setattr(bf, "scrape_event_decks", lambda sid, url: DECKS)
    monkeypatch.setattr(bf, "scrape_deck_cards", lambda url: CARDS)
    n, ok = bf._process_event(EV, "modern")
    assert (n, ok) == (3, True)
    assert _counts(real_db) == (1, 3, 6)


def test_process_event_rolls_back_when_the_event_page_fails(real_db, monkeypatch):
    monkeypatch.setattr(bf, "scrape_event_decks", lambda sid, url: [])     # fetch failed / no decks
    monkeypatch.setattr(bf, "scrape_deck_cards", lambda url: CARDS)
    n, ok = bf._process_event(EV, "modern")
    assert (n, ok) == (0, False)
    assert _counts(real_db) == (0, 0, 0), "a zero-deck event must not be left behind"


def test_process_event_rolls_back_when_a_deck_fetch_fails(real_db, monkeypatch):
    monkeypatch.setattr(bf, "scrape_event_decks", lambda sid, url: DECKS)
    calls = iter([CARDS, ({}, {}), CARDS])                                  # 2nd deck fails
    monkeypatch.setattr(bf, "scrape_deck_cards", lambda url: next(calls))
    n, ok = bf._process_event(EV, "modern")
    assert ok is False
    assert _counts(real_db) == (0, 0, 0), "partial events are rolled back whole"


def test_run_backfill_aborts_after_consecutive_event_failures(monkeypatch, quiet_backfill):
    listing = _Resp("".join(
        f'<tr class="hover_tr"><td class="S14"><a href="event?e=9{i:04d}&f=MO">Ev {i}</a></td>'
        f'<td>{(datetime.now() - timedelta(days=1)).strftime("%d/%m/%y")}</td></tr>' for i in range(10)))
    # listing served, but the host probe (format page) is unreachable: a real outage
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: listing if "&meta=" in url else None)
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: (0, False))   # every event fails
    with pytest.raises(bf.BackfillFetchError):
        bf.run_backfill("modern")


def test_broken_event_pages_with_the_host_up_do_not_abort(monkeypatch, quiet_backfill, capsys):
    """Standard died twice (09-21, 09-27) on the SAME four adjacent events 73498-73501:
    broken pages, not an outage. With the host answering, keep going."""
    listing = _listing([f"7{i:04d}" for i in range(8)])
    pages = iter([listing, EMPTY_PAGE])
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: next(pages) if "&meta=" in url else EMPTY_PAGE)
    outcomes = iter([(0, False)] * 6 + [(3, True)] * 2)
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: next(outcomes))
    summary = bf.run_backfill("modern")
    assert summary["events"] == 2 and summary["event_failures"] == 6
    assert "host reachable" in capsys.readouterr().out


def test_repeatedly_failing_events_are_skipped_after_three_runs(monkeypatch, quiet_backfill):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: _listing(["111", "222"]) if "&meta=" in url else EMPTY_PAGE)
    calls = []

    def process(ev, fmt):
        calls.append(ev["source_id"])
        return (0, False) if ev["source_id"] == "111" else (2, True)
    monkeypatch.setattr(bf, "_process_event", process)
    for _ in range(3):
        bf.run_backfill("modern")
    assert bf._load_bad_events()["111"]["fails"] == 3 and "222" not in bf._load_bad_events()
    calls.clear()
    summary = bf.run_backfill("modern")
    assert calls == ["222"]                      # 111 skipped without a fetch
    assert summary["skipped_bad_events"] == 1


def test_bad_event_that_later_succeeds_leaves_the_ledger(monkeypatch, quiet_backfill):
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: _listing(["333"]) if "&meta=" in url else EMPTY_PAGE)
    results = iter([(0, False), (4, True)])
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: next(results))
    bf.run_backfill("modern")
    assert bf._load_bad_events()["333"]["fails"] == 1
    bf.run_backfill("modern")
    assert "333" not in bf._load_bad_events()


def test_run_backfill_tolerates_isolated_event_failures(monkeypatch, quiet_backfill):
    listing = _Resp("".join(
        f'<tr class="hover_tr"><td class="S14"><a href="event?e=9{i:04d}&f=MO">Ev {i}</a></td>'
        f'<td>{(datetime.now() - timedelta(days=1)).strftime("%d/%m/%y")}</td></tr>' for i in range(6)))
    pages = iter([listing, EMPTY_PAGE])
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: next(pages) if "&meta=" in url else EMPTY_PAGE)
    outcomes = iter([(5, True), (0, False), (5, True), (0, False), (5, True), (5, True)])
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: next(outcomes))
    summary = bf.run_backfill("modern")
    assert summary["events"] == 4 and summary["decks"] == 20
    assert summary["event_failures"] == 2


# ---------------------------------------------------------------------------
# Pagination: a page full of already-known events is NOT the end of the year
# ---------------------------------------------------------------------------

def _listing(ids):
    day = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%y")
    return _Resp("".join(
        f'<tr class="hover_tr"><td class="S14"><a href="event?e={i}&f=MO">Ev {i}</a></td>'
        f'<td>{day}</td></tr>' for i in ids))


def test_run_backfill_continues_past_pages_of_known_events(monkeypatch, quiet_backfill):
    """Modern 2026 pages 1-2 were fully known (daily scrapes), page 3+ were not,
    and the year stopped after page 2 -- Jan-Aug 2026 was never fetched."""
    pages = {1: _listing(["1", "2"]), 2: _listing(["3", "4"]), 3: _listing(["5", "6"]), 4: _listing([])}
    monkeypatch.setattr(bf, "_get_existing_source_ids", lambda: {"1", "2", "3", "4"})
    monkeypatch.setattr(bf, "_get", lambda url, retries=3:
                        pages[int(url.split("cp=")[1])] if "&meta=" in url else EMPTY_PAGE)
    processed = []
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: processed.append(ev["source_id"]) or (1, True))
    summary = bf.run_backfill("modern")
    assert processed == ["5", "6"]
    assert summary["events"] == 2


def test_run_backfill_stops_when_the_site_repeats_the_last_page(monkeypatch, quiet_backfill):
    """Past the end MTGTop8 keeps serving the last page; a repeat must end the year."""
    monkeypatch.setattr(bf, "_get", lambda url, retries=3: _listing(["7", "8"]) if "&meta=" in url else EMPTY_PAGE)
    processed = []
    monkeypatch.setattr(bf, "_process_event", lambda ev, fmt: processed.append(ev["source_id"]) or (1, True))
    summary = bf.run_backfill("modern")
    assert processed == ["7", "8"]           # once, not forever
    assert summary["events"] == 2
