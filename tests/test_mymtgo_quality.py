"""Tests for the MyMTGO accuracy layer: event parsing/reconciliation, epoch-safe
matchup aggregation, snapshot re-derivation. Offline (fixtures/mymtgo/)."""
import copy
import json
import os
from types import SimpleNamespace

import pytest

from analysis import mymtgo_quality as q
from scrapers import mymtgo

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "mymtgo")


def _page(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return mymtgo.extract_page(fh.read())


@pytest.fixture
def event():
    return mymtgo.parse_event(_page("event_synthetic.html"))


def test_event_matches_are_deduped_across_both_seats(event):
    # 5 real pairings; each appears twice in rows (once per seat), plus a bye and a null score
    assert len(event["matches"]) == 5
    fps = [m["fingerprint"] for m in event["matches"]]
    assert len(set(fps)) == 5
    assert all(m["provenance"] == "mymtgo_reconstructed" for m in event["matches"])


def test_both_published_flag(event):
    by = {(m["round"], m["a_player"], m["b_player"]): m["both_published"] for m in event["matches"]}
    assert by[(1, "alice", "bob")] is True
    assert by[(1, "cara", "dan")] is False          # dan has no published deck
    assert by[(2, "bob", "eve")] is True            # eve published but unclassified


def test_reconciliation_against_official_records(event):
    assert event["reconciled"] is True
    page = _page("event_synthetic.html")
    page["props"]["standings"][0]["record"] = "3-0"   # tamper alice's official record
    bad = mymtgo.parse_event(page)
    assert bad["reconciled"] is False
    assert [r["player"] for r in bad["reconciliation"] if not r["ok"]] == ["alice"]


def test_event_matchups_counts_both_directions_and_skips_unknown_labels(event):
    mu = q.event_matchups([event], "2026-09-15", "2026-09-30")
    pt = mu[("Prowess", "Eldrazi Tron")]
    assert (pt["wins"], pt["losses"], pt["matches"]) == (2, 0, 2)         # R1 + playoff
    assert mu[("Eldrazi Tron", "Prowess")]["losses"] == 2
    assert mu[("Prowess", "Affinity (Provisional)")]["losses"] == 1
    assert not any(None in k for k in mu)                                 # eve unclassified -> skipped
    assert pt["provenance"] == "mymtgo_reconstructed" and pt["unit"] == "match"


def test_playoffs_toggle_and_family_merge(event):
    mu = q.event_matchups([event], "2026-09-15", "2026-09-30", include_playoffs=False)
    assert mu[("Prowess", "Eldrazi Tron")]["matches"] == 1
    fam = q.event_matchups([event], "2026-09-15", "2026-09-30", use_family=True)
    assert ("Prowess", "Affinity") in fam and ("Prowess", "Affinity (Provisional)") not in fam


def test_window_refuses_to_cross_an_epoch(event):
    with pytest.raises(q.EpochCrossingError):
        q.event_matchups([event], "2026-08-01", "2026-09-30")          # crosses The Hobbit
    assert q.event_matchups([event], "2026-08-01", "2026-09-30", allow_cross_epoch=True)
    assert q.epoch_of("2026-09-26") == "hob"
    assert q.epoch_range("hob") == ("2026-08-14", "2026-10-01")


def test_wilson_and_pilot_clustered_interval():
    assert q.wilson(540, 1000) == (50.9, 57.1)                 # site methodology example: 51-57
    # one grinder with 40 matches at 75% + 9 pilots at 40%: clustering must widen the band
    pilots = {"grinder": [30, 40]}
    pilots.update({f"p{i}": [2, 5] for i in range(9)})
    lo, hi = q._cluster_ci(pilots)
    w = q.wilson(48, 85)
    assert (hi - lo) > (w[1] - w[0])
    assert q._cluster_ci({"a": [1, 2], "b": [1, 2]}) is None       # too few pilots


def test_family_strips_only_the_provisional_suffix():
    assert q.family("Affinity (Provisional)") == "Affinity"
    assert q.family("Basim Affinity") == "Basim Affinity"
    assert q.family(None) is None


def _snap():
    deck = mymtgo.parse_deck(_page("deck_modern_prowess_trimmed.html"))
    idx = mymtgo.parse_index(_page("index_modern_30d_trimmed.html"))
    return {"format": "modern", "index": idx, "deck_pages": {"prowess": deck}}


def test_validate_snapshot_catches_a_changed_shrinkage_or_count():
    s = _snap()
    s["index"]["decks"] = []            # trimmed index: skip seat accounting here
    assert q.validate_snapshot(s) == []
    t = copy.deepcopy(s)
    t["deck_pages"]["prowess"]["matchups"][0]["shrunk_rate"] = 70.0
    assert any("shrunk" in p for p in q.validate_snapshot(t))
    t = copy.deepcopy(s)
    t["deck_pages"]["prowess"]["matchups"][1]["wins"] += 3
    assert any("raw" in p for p in q.validate_snapshot(t))


def test_validate_snapshot_seat_accounting():
    s = _snap()
    s["deck_pages"] = {}
    s["index"]["matches"] = 10
    s["index"]["decks"] = [{"played": 12, "share": 60.0}, {"played": 6, "share": 30.0}]
    s["index"]["unlisted"] = {"rogue": {"played": 1, "share": 5.0}, "other": {"played": 1, "share": 5.0}}
    assert q.validate_snapshot(s) == []
    s["index"]["decks"][0]["played"] = 13
    assert any("seat accounting" in p for p in q.validate_snapshot(s))


def test_sensitivity_parent_vs_provisional():
    rows = [{"opp_name": "Affinity", "wins": 55, "matches": 149},
            {"opp_name": "Affinity (Provisional)", "wins": 8, "matches": 14},
            {"opp_name": "Basim Affinity", "wins": 5, "matches": 20}]
    r = q.sensitivity(rows, "Affinity")
    assert r["parent_only"]["rate"] == 36.9 and r["with_provisional"]["rate"] == 38.7
    assert r["siblings"] == ["Affinity (Provisional)"]


def test_tracker_lean_uses_parsed_league_runs():
    s = _snap()
    s["deck_pages"]["prowess"]["tracker_league"] = {"runs": 38, "wins": 97, "matches": 190, "win_rate": 51.1}
    assert q.tracker_lean(s)[0]["lean_pp"] == 0.0


def test_fetch_events_windows_skips_no_match_events_and_stops(monkeypatch):
    with open(os.path.join(FIX, "events_index_synthetic.html"), encoding="utf-8") as fh:
        idx_html = fh.read()
    with open(os.path.join(FIX, "event_synthetic.html"), encoding="utf-8") as fh:
        ev_html = fh.read()
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return SimpleNamespace(ok=True, status=200, text=ev_html if url.endswith("/99") else idx_html)

    monkeypatch.setattr(mymtgo.polite_client, "get", fake_get)
    evs = mymtgo.fetch_events("modern", "2026-09-01")
    assert [e["number"] for e in evs] == [99]          # 98 has no matches, 97 predates window
    assert calls == ["https://mymtgo.com/events/modern?page=1", "https://mymtgo.com/events/modern/99"]
    with pytest.raises(ValueError):
        mymtgo.fetch_events("modern", "last week")
