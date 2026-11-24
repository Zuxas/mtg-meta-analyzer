"""#13: page GetRoundMatches past 500 rows, and store nothing for an event
whose round failed (so it is re-fetched next run).

Fixtures are synthetic (the repo is public) but mirror the real DataTables
GetRoundMatches response shape: {"data": [...rows...], "recordsTotal": N}.
"""
import pytest

import scrapers.mtgmelee_scraper as ms


def _pairing_row(d1="Boros Energy", d2="Amulet Titan", p1w=2, p2w=1, fmt="Modern"):
    comp = lambda name, deck, wins: {
        "Team": {"Players": [{"DisplayName": name}]},
        "Decklists": [{"DecklistName": deck, "Format": fmt}],
        "GameWins": wins,
    }
    return {"HasResult": True, "ByeReason": None, "GameDraws": 0, "Format": fmt,
            "Competitors": [comp("Alice", d1, p1w), comp("Bob", d2, p2w)]}


class _PagedSession:
    """Serves `total` identical rows in 500-row pages, recording each `start`."""

    def __init__(self, total, fail=False):
        self.total = total
        self.fail = fail
        self.starts = []

    def post(self, url, data=None, headers=None, timeout=None):
        start = int(data["start"])
        length = int(data["length"])
        self.starts.append(start)
        if self.fail:
            raise RuntimeError("503 Service Unavailable")
        page = [_pairing_row() for _ in range(max(0, min(length, self.total - start)))]
        return _Resp({"data": page, "recordsTotal": self.total})


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


def test_fetch_round_rows_pages_until_records_total():
    sess = _PagedSession(1200)
    rows = ms.fetch_round_rows(sess, "99999", "r1")
    assert len(rows) == 1200          # 500 + 500 + 200, not truncated at 500
    assert sess.starts == [0, 500, 1000]


def test_fetch_tournament_pairings_passes_all_paged_rows_through(monkeypatch):
    sess = _PagedSession(1200)
    monkeypatch.setattr(ms, "_session", lambda: sess)
    monkeypatch.setattr(ms, "_get_round_ids", lambda s, tid: [("r1", "Round 1")])
    monkeypatch.setattr(ms, "_map_archetype", lambda deck, fmt: deck or None)
    matches = ms.fetch_tournament_pairings("99999")
    assert len(matches) == 1200


def test_failed_round_raises_incomplete(monkeypatch):
    monkeypatch.setattr(ms, "_session", lambda: _PagedSession(1200, fail=True))
    monkeypatch.setattr(ms, "_get_round_ids", lambda s, tid: [("r1", "Round 1")])
    with pytest.raises(ms.IncompleteTournament) as exc:
        ms.fetch_tournament_pairings("99999")
    assert exc.value.failed_rounds == ["Round 1"]


def test_scrape_and_store_skips_incomplete_event(monkeypatch):
    # An incomplete event stores nothing and lands in LAST_INCOMPLETE, so the
    # already-stored skip won't hide it next run.
    monkeypatch.setattr(ms, "fetch_tournament_list",
                        lambda fmt, mn, pages: [{"id": "77", "name": "RC", "date": "2026-11-01",
                                                 "player_count": 1200}])
    monkeypatch.setattr(ms, "fetch_tournament_pairings",
                        lambda tid: (_ for _ in ()).throw(ms.IncompleteTournament(tid, ["Round 7"])))
    saved_calls = []
    monkeypatch.setattr("db.matches_queries.save_matches", lambda rows: saved_calls.append(rows) or len(rows))
    monkeypatch.setattr("db.matches_queries.get_stored_event_ids", lambda fmt, source: set())

    total = ms.scrape_and_store("modern", pages=1)
    assert total == 0
    assert saved_calls == []
    assert ms.LAST_INCOMPLETE == ["77"]
