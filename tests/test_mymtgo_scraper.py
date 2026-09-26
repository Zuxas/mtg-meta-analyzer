"""Offline tests for scrapers/mymtgo.py (fixtures: tests/fixtures/mymtgo/).

The network is blocked by conftest; fetch paths are exercised with a stubbed
polite_client.get so no request is ever made.
"""
import json
import os
from types import SimpleNamespace

import pytest

from scrapers import mymtgo

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "mymtgo")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def test_extract_page_reads_the_inertia_island_with_escaped_slashes():
    page = mymtgo.extract_page(_read("index_modern_30d_trimmed.html"))
    assert page["component"] == "metagame/Index"      # "\/" unescaped by JSON
    assert page["url"] == "/metagame/modern?days=30"


def test_extract_page_ignores_other_json_scripts_and_fails_loudly_without_island():
    with pytest.raises(mymtgo.MyMtgoParseError, match="no <script"):
        mymtgo.extract_page('<script type="application/ld+json">{"a":1}</script>')
    with pytest.raises(mymtgo.MyMtgoParseError, match="Inertia"):
        mymtgo.extract_page('<script data-page="app" type="application/json">[1,2]</script>')


def test_extract_page_accepts_html_entity_encoded_island():
    blob = json.dumps({"component": "x", "props": {"a": "b"}}).replace('"', "&quot;")
    page = mymtgo.extract_page(f"<script data-page='app'>{blob}</script>")
    assert page["props"] == {"a": "b"}


def test_parse_index():
    idx = mymtgo.parse_index(mymtgo.extract_page(_read("index_modern_30d_trimmed.html")))
    assert (idx["format"], idx["days"], idx["since"], idx["matches"]) == ("modern", 30, "2026-08-28", 11349)
    assert idx["last_page"] == 3 and idx["total_decks"] == 98
    b = idx["decks"][0]
    assert (b["name"], b["share"], b["win_rate"], b["wr_lo"], b["wr_hi"]) == \
           ("Broodscale", 10.3, 53.1, 51.6, 54.6)
    assert idx["decks"][2]["change"] == -4.5


def test_parse_deck_drops_mirror_and_keeps_shrunk_vs_raw():
    d = mymtgo.parse_deck(mymtgo.extract_page(_read("deck_modern_prowess_trimmed.html")))
    assert (d["slug"], d["win_rate"], d["matches"], d["sources"]["challenge"]) == ("prowess", 51.1, 2841, 1718)
    names = [m["opp_name"] for m in d["matchups"]]
    assert names == ["Devoted Combo", "Eldrazi Tron"]          # mirror row removed
    tron = d["matchups"][1]
    assert (tron["win_rate"], tron["shrunk_rate"], tron["wins"], tron["matches"]) == (41.4, 43.0, 55, 133)
    assert [m["kept"] for m in d["mulligan"]] == [7, 6, 5, 4]
    assert d["mulligan"][3]["win_rate"] is None and d["mulligan"][3]["pooled"]
    assert {o["lands"]: o["win_rate"] for o in d["openers"]} == {1: 47.4, 2: 57.1, 3: 58.3, 4: 39.5}
    assert d["cards"][1]["name"] == "Lava Dart" and d["cards"][1]["impact"] == 8.7


def test_wrong_component_is_rejected():
    idx_page = mymtgo.extract_page(_read("index_modern_30d_trimmed.html"))
    with pytest.raises(mymtgo.MyMtgoParseError, match="metagame/Show"):
        mymtgo.parse_deck(idx_page)


def test_snapshot_uses_polite_client_paginates_and_builds_matrix(monkeypatch, tmp_path):
    index_html = _read("index_modern_30d_trimmed.html")
    deck_html = _read("deck_modern_prowess_trimmed.html")
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        assert "/api/" not in url                    # robots.txt disallows /api/
        text = deck_html if "/metagame/modern/" in url else index_html
        return SimpleNamespace(ok=True, status=200, text=text)

    monkeypatch.setattr(mymtgo.polite_client, "get", fake_get)
    snap = mymtgo.snapshot("modern", 30, top=1)
    assert calls[:3] == ["https://mymtgo.com/metagame/modern?days=30",
                         "https://mymtgo.com/metagame/modern?days=30&page=2",
                         "https://mymtgo.com/metagame/modern?days=30&page=3"]
    assert calls[3] == "https://mymtgo.com/metagame/modern/broodscale"   # top-1 by share
    assert len(calls) == 4
    m = mymtgo.matchup_matrix(snap)
    assert m["Prowess"]["Eldrazi Tron"] == 43.0
    assert mymtgo.matchup_matrix(snap, rate="raw")["Prowess"]["Eldrazi Tron"] == 41.4
    path = mymtgo.save_snapshot(snap, str(tmp_path))
    assert os.path.basename(path).startswith("modern_30d_")
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)["format"] == "modern"


def test_bad_inputs_are_refused_before_any_request(monkeypatch):
    monkeypatch.setattr(mymtgo.polite_client, "get",
                        lambda *a, **k: pytest.fail("no request expected"))
    with pytest.raises(ValueError):
        mymtgo.fetch_index("commander")
    with pytest.raises(ValueError):
        mymtgo.fetch_index("modern", days=14)
    with pytest.raises(ValueError):
        mymtgo.fetch_deck("modern", "../api/decks")


def test_polite_client_has_a_host_entry():
    from scrapers import polite_client
    cfg = polite_client.HOST_CONFIG["mymtgo.com"]
    assert cfg["min_interval"] >= 1.5 and not cfg.get("blocked")
