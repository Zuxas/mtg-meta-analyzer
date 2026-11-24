"""#34: keep mtgtop8 tied ranks ('3-4', '5-8') instead of numbering decks by
page order, so two decks that both finished 5-8 read as a tie.

The fixture mirrors the real page nesting verified against a live Challenge 32
event (synthetic here -- the repo is public):
  <div> RANK <div> <div class="S14"><a href="?d=N">ARCH</a></div> PLAYER </div></div>
"""
import scrapers.mtgtop8 as m
from analysis.win_rates import _matchup_stats


def _page(rows):
    """rows: list of (rank_text, deck_id, archetype, player)."""
    body = "".join(
        f'<div>{rank} <div><div class="S14">'
        f'<a href="?d={did}&f=ST">{arch}</a></div> {player}</div></div>'
        for rank, did, arch, player in rows
    )
    return f"<html><body>{body}</body></html>"


def _scrape(monkeypatch, html):
    monkeypatch.setattr(m, "_get", lambda url: type("R", (), {"text": html})())
    return m.scrape_event_decks("1", "https://mtgtop8.com/event?e=1")


def test_parse_rank_range_start():
    assert m._parse_rank("1 Foo") == 1
    assert m._parse_rank("3-4 Foo") == 3
    assert m._parse_rank("5-8 Foo") == 5
    assert m._parse_rank("no rank here") is None


def test_tied_ranks_flatten_to_range_start(monkeypatch):
    decks = _scrape(monkeypatch, _page([
        ("1", 10, "Boros Energy", "alice"),
        ("2", 11, "Amulet Titan", "bob"),
        ("3-4", 12, "Izzet Prowess", "carol"),
        ("3-4", 13, "Dimir Murktide", "dave"),
        ("5-8", 14, "Mono Red", "erin"),
        ("5-8", 15, "Living End", "finn"),
    ]))
    assert [d["placement"] for d in decks] == [1, 2, 3, 3, 5, 5]


def test_no_rank_falls_back_to_page_order(monkeypatch):
    # A page with no rank tokens keeps the old 1..N behaviour.
    decks = _scrape(monkeypatch, _page([
        ("", 20, "Boros Energy", "alice"),
        ("", 21, "Amulet Titan", "bob"),
    ]))
    assert [d["placement"] for d in decks] == [1, 2]


def test_matchup_stats_counts_equal_placement_as_tie():
    # done-when: two decks that both finished 5-8 in the same event tie, not W/L.
    stats = _matchup_stats({"e1": 5}, {"e1": 5})
    assert stats["wins"] == 0 and stats["losses"] == 0 and stats["ties"] == 1
