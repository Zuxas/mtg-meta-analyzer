"""scrapers.mtgmelee_scraper.scrape_tournaments: the targeted backfill path is idempotent, reports
exact inserted counts, never guesses metadata, and skips pairings whose deck names are blank
(e.g. the F2FTour Vancouver RCQs, which published no decklists). Synthetic players only."""
import scrapers.mtgmelee_scraper as mm
from db.matches_queries import count_event_matches, get_matches

T = {"id": "900001", "name": "Synthetic Modern Open", "format": "Modern", "date": "2026-09-19", "player_count": 40}
BLANK = {"id": "900002", "name": "Synthetic RCQ (no lists)", "format": "Modern", "date": "2026-09-20",
         "player_count": 36}


def _pair(rnd, a, b, da, db, res):
    w = {"player1": (2, 0), "player2": (0, 2), "draw": (1, 1)}[res]
    return {"round": rnd, "player1": a, "player2": b, "player1_deck": da, "player2_deck": db,
            "player1_wins": w[0], "player2_wins": w[1], "draws": 1 if res == "draw" else 0, "result": res}


PAIRINGS = {
    "900001": [_pair(1, "Player A", "Player B", "Izzet Prowess", "Boros Energy", "player1"),
               _pair(1, "Player C", "Player D", "Eldrazi Tron", "Izzet Prowess", "player2"),
               _pair(2, "Player A", "Player C", "Izzet Prowess", "", "player1"),       # unlabelled: skipped
               _pair(2, "Player B", "Player D", "Boros Energy", "Izzet Prowess", "draw")],
    "900002": [_pair(1, "Player E", "Player F", "", "", "player1")],
}


def _stub(monkeypatch):
    monkeypatch.setattr(mm, "fetch_tournament_list", lambda fmt, mp, pages: [T, BLANK])
    monkeypatch.setattr(mm, "fetch_tournament_pairings", lambda tid: PAIRINGS[tid])


def test_targeted_backfill_counts_exactly_and_is_idempotent(monkeypatch):
    _stub(monkeypatch)
    first = mm.scrape_tournaments(["900001", "900002", "123"], "modern")
    assert first["900001"]["storable"] == 3 and first["900001"]["inserted"] == 3
    assert first["900002"]["storable"] == 0 and "inserted" not in first["900002"]   # nothing to save
    assert first["123"] == {"error": "not-listed"}                                  # never guessed
    second = mm.scrape_tournaments(["900001"], "modern")
    assert second["900001"]["inserted"] == 0                                         # no duplicates
    assert count_event_matches("mtgmelee_900001") == 3
    rows = get_matches("modern", source="mtgmelee")
    assert {r["event_date"] for r in rows} == {"2026-09-19"}
    got = {(r["round"], r["player1"], r["result"], r["winner_arch"]) for r in rows}
    assert got == {(1, "Player A", "player1", "Izzet Prowess"), (1, "Player C", "player2", "Izzet Prowess"),
                   (2, "Player B", "draw", None)}


def test_targeted_dry_run_writes_nothing(monkeypatch):
    _stub(monkeypatch)
    out = mm.scrape_tournaments(["900001"], "modern", dry_run=True)
    assert out["900001"]["storable"] == 3 and "inserted" not in out["900001"]
    assert count_event_matches("mtgmelee_900001") == 0


def test_cli_routes_tournament_ids(monkeypatch):
    seen = {}
    monkeypatch.setattr(mm, "scrape_tournaments", lambda ids, fmt, pages, dry_run: seen.update(
        ids=ids, fmt=fmt, pages=pages, dry_run=dry_run))
    mm.main(["--format", "modern", "--pages", "3", "--tournament-id", "448946", "--tournament-id", "462365",
             "--dry-run"])
    assert seen == {"ids": ["448946", "462365"], "fmt": "modern", "pages": 3, "dry_run": True}
