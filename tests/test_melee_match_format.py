"""#14: tag each Melee match with its OWN format.

A multi-format event (Pro Tour, trios) mixes Draft/Limited and several
constructed formats in one tournament. The scraper used to stamp every pairing
with the single requested `format_name`, so a Pro Tour's Draft rounds landed in
Modern/Standard win rates. Now `_parse_pairing_row` reads the per-match `Format`
(row-level, else the decklist `Format`), and `_match_rows` keeps only matches
played in the requested format, dropping Limited and other-format rows.

Fixtures are synthetic (the repo is public) but mirror the real GetRoundMatches
shape that `scripts/quarantine_matches.py` reads from live data.
"""
import pytest

import scrapers.mtgmelee_scraper as ms


def _row(fmt, d1, d2, p1w, p2w, *, decklist_fmt=None):
    """One GetRoundMatches pairing row. `fmt` is the row-level Format; pass
    decklist_fmt to also set the per-decklist Format (and fmt=None to test the
    decklist fallback)."""
    dfmt = decklist_fmt if decklist_fmt is not None else fmt
    comp = lambda name, deck, wins: {
        "Team": {"Players": [{"DisplayName": name}]},
        "Decklists": [{"DecklistName": deck, "Format": dfmt}] if deck else [],
        "GameWins": wins,
    }
    r = {"HasResult": True, "ByeReason": None, "GameDraws": 0,
         "Competitors": [comp("Alice", d1, p1w), comp("Bob", d2, p2w)]}
    if fmt is not None:
        r["Format"] = fmt
    return r


@pytest.fixture(autouse=True)
def _identity_archetypes(monkeypatch):
    # Isolate the format gate from the archetype table: every deck name maps to
    # itself, so a row is kept iff the format logic keeps it.
    monkeypatch.setattr(ms, "_map_archetype", lambda deck, fmt: deck or None)


T = {"id": "99999", "date": "2026-11-01"}


def _rows(pairing_rows, format_name):
    parsed = [ms._parse_pairing_row(r, 1) for r in pairing_rows]
    return ms._match_rows(T, [p for p in parsed if p], format_name)


def test_mixed_modern_draft_round_keeps_only_modern():
    out = _rows([
        _row("Modern", "Boros Energy", "Amulet Titan", 2, 1),
        _row("Draft", "WU", "BR", 2, 0),
    ], "modern")
    assert len(out) == 1
    assert out[0]["format"] == "modern"
    assert out[0]["player1_arch"] == "Boros Energy"


def test_sealed_is_dropped():
    out = _rows([_row("Sealed Deck", "WU", "BR", 2, 0)], "modern")
    assert out == []


def test_other_constructed_format_is_dropped_for_this_scrape():
    # During a Modern scrape, a Standard match of a multi-format event is left
    # for the Standard scrape rather than mis-tagged Modern.
    out = _rows([
        _row("Modern", "Boros Energy", "Amulet Titan", 2, 1),
        _row("Standard", "Mono Red", "Azorius Control", 2, 0),
    ], "modern")
    assert [r["player1_arch"] for r in out] == ["Boros Energy"]


def test_missing_match_format_falls_back_to_requested():
    # Ordinary single-format event: no per-match Format at all -> kept as before.
    out = _rows([_row(None, "Boros Energy", "Amulet Titan", 2, 1, decklist_fmt=None)], "modern")
    assert len(out) == 1
    assert out[0]["format"] == "modern"


def test_decklist_format_used_when_row_format_is_the_event_bundle():
    # Row Format carries the comma-joined event bundle; the per-match format
    # comes from the decklist instead.
    r = _row("Modern, Standard, Pauper", "Grixis Affinity", "WR", 2, 0,
             decklist_fmt="Pauper")
    parsed = ms._parse_pairing_row(r, 1)
    assert parsed["match_format"] == "Pauper"
    assert ms._match_rows(T, [parsed], "modern") == []        # dropped on a Modern scrape
    assert len(ms._match_rows(T, [parsed], "pauper")) == 1    # kept on a Pauper scrape


def test_is_limited_predicate():
    assert ms._is_limited("Draft") and ms._is_limited("Booster Draft")
    assert ms._is_limited("Sealed Deck")
    assert not ms._is_limited("Modern")
    assert not ms._is_limited(None)
