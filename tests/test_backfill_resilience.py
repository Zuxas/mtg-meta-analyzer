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
def quiet_backfill(monkeypatch):
    """No DB, no config, no sleeping; 30-day cutoff so only the current year runs."""
    monkeypatch.setattr(bf, "_get_existing_source_ids", lambda: set())
    monkeypatch.setattr(bf, "_load_cutoff", lambda fmt: datetime.now() - timedelta(days=30))
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)


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
