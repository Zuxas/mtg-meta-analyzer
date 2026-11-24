"""#18: a failed or empty TournamentSearch discovery must raise DiscoveryFailed
(so the run exits nonzero) instead of looking like 'no new events', and each
run logs how many events were filtered out by min_players.

Fixtures are synthetic (the repo is public) but mirror the TournamentSearch
response shape {recordsTotal, data:[rows]} the live endpoint returns.
"""
import logging

import pytest

import scrapers.mtgmelee_scraper as ms


def _row(tid, players, date="2026-11-01", name="RC Modern"):
    return {"id": tid, "name": name, "startDate": date,
            "enrolledPlayerCount": players, "formatString": "Modern"}


class _SearchSession:
    """Stubs TournamentSearch. `total` drives the recordsTotal probe (length=1);
    `page_rows` is served for data pages. Set probe_fail / page_fail to raise."""

    def __init__(self, total=0, page_rows=None, probe_fail=False, page_fail=False):
        self.total = total
        self.page_rows = page_rows or []
        self.probe_fail = probe_fail
        self.page_fail = page_fail

    def post(self, url, data=None, headers=None, timeout=None):
        is_probe = data.get("variables[length]") == "1"
        if is_probe:
            if self.probe_fail:
                raise RuntimeError("403 Cloudflare")
            return _Resp({"recordsTotal": self.total, "data": []})
        if self.page_fail:
            raise RuntimeError("503 Service Unavailable")
        return _Resp({"recordsTotal": self.total, "data": self.page_rows})


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ms.time, "sleep", lambda *_: None)


def _use(monkeypatch, sess):
    monkeypatch.setattr(ms, "_session", lambda: sess)


def test_probe_failure_raises(monkeypatch):
    _use(monkeypatch, _SearchSession(probe_fail=True))
    with pytest.raises(ms.DiscoveryFailed):
        ms.fetch_tournament_list("modern", pages=1)


def test_records_total_zero_raises(monkeypatch):
    _use(monkeypatch, _SearchSession(total=0))
    with pytest.raises(ms.DiscoveryFailed):
        ms.fetch_tournament_list("modern", pages=1)


def test_page_failure_raises(monkeypatch):
    _use(monkeypatch, _SearchSession(total=150, page_fail=True))
    with pytest.raises(ms.DiscoveryFailed):
        ms.fetch_tournament_list("modern", pages=2)


def test_success_returns_qualifying_and_logs_filtered(monkeypatch, caplog):
    sess = _SearchSession(total=3, page_rows=[
        _row("1", 40), _row("2", 64), _row("3", 6),   # 6-player one is below min
    ])
    _use(monkeypatch, sess)
    with caplog.at_level(logging.INFO):
        out = ms.fetch_tournament_list("modern", min_players=32, pages=1)
    assert {t["id"] for t in out} == {"1", "2"}       # the 6-player event filtered
    assert any("below min_players=32" in r.message or "1 below min_players" in r.message
               for r in caplog.records)


def test_main_exits_nonzero_on_discovery_failure(monkeypatch):
    _use(monkeypatch, _SearchSession(probe_fail=True))
    with pytest.raises(SystemExit) as exc:
        ms.main(["--format", "modern", "--pages", "1"])
    assert exc.value.code == 2
