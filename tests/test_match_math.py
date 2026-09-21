"""Bo3 match math (CHAPIN_METRICS.md Task 3, rule MG-12, NLMF p.90).

A sideboard plan acts on POST-BOARD games, and a Bo3 match is not linear in
game win rate:

    P(match) = p1 * (2q - q^2) + (1 - p1) * q^2

p1 = game-1 win rate, q = post-board game win rate. The flat +/-5pp bump that
compute_deck_ev added to the MATCH win rate is off by up to ~16% relative,
in a direction that depends on p1.
"""
import pytest

from analysis.match_math import implied_q, match_winrate, required_q


# ---------------------------------------------------------------------------
# Chapin's worked cases -- must reproduce exactly (3 dp)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p1, q, expected", [
    (0.40, 0.60, 0.552),
    (0.30, 0.60, 0.504),
    (0.40, 0.70, 0.658),
])
def test_match_winrate_reproduces_chapin_worked_cases(p1, q, expected):
    assert round(match_winrate(p1, q), 3) == expected


def test_match_winrate_boundaries():
    assert match_winrate(0.0, 0.0) == 0.0
    assert match_winrate(1.0, 1.0) == 1.0
    assert match_winrate(0.4, 0.0) == 0.0          # can't win a match without a post-board game
    assert match_winrate(0.4, 1.0) == 1.0          # always win post-board -> always win the match
    assert match_winrate(0.0, 0.6) == pytest.approx(0.36)     # q^2
    assert match_winrate(1.0, 0.6) == pytest.approx(0.84)     # 2q - q^2
    assert match_winrate(0.5, 0.6) == pytest.approx(0.6)      # p1 = 0.5 -> P = q exactly


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_match_winrate_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        match_winrate(bad, 0.5)
    with pytest.raises(ValueError):
        match_winrate(0.5, bad)


# ---------------------------------------------------------------------------
# implied_q: invert P for q given p1; round-trips through match_winrate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p1, q", [
    (0.40, 0.60), (0.30, 0.60), (0.40, 0.70),
    (0.50, 0.45), (0.70, 0.60), (0.10, 0.90), (0.90, 0.10),
    (0.0, 0.3), (1.0, 0.3),
])
def test_implied_q_round_trips(p1, q):
    p = match_winrate(p1, q)
    assert implied_q(p1, p) == pytest.approx(q, abs=1e-9)


def test_implied_q_at_p1_half_equals_match_wr():
    assert implied_q(0.5, 0.43) == pytest.approx(0.43)


def test_implied_q_boundaries():
    assert implied_q(0.4, 0.0) == 0.0
    assert implied_q(0.4, 1.0) == pytest.approx(1.0)
    assert implied_q(0.4, 1.05) is None            # no q in [0, 1] produces P > 1
    assert implied_q(0.4, -0.05) is None


# ---------------------------------------------------------------------------
# required_q: "to reach X%, post-board games must be at ..."
# ---------------------------------------------------------------------------

def test_required_q_is_the_inverse_at_the_target():
    q = required_q(0.40, 0.50)
    assert match_winrate(0.40, q) == pytest.approx(0.50)
    assert q > 0.5                                  # losing G1 -> need better than even post-board


def test_required_q_lower_when_game_one_is_favourable():
    assert required_q(0.60, 0.50) < required_q(0.40, 0.50)


def test_required_q_returns_none_when_unreachable():
    assert required_q(0.40, 1.01) is None           # q would exceed 1
    assert required_q(0.40, 1.0) == pytest.approx(1.0)
    assert required_q(0.40, 0.0) == 0.0


# ---------------------------------------------------------------------------
# compute_deck_ev wiring: bump applies to q, recomposed; flag keeps old path
# ---------------------------------------------------------------------------

@pytest.fixture
def ev_env(monkeypatch):
    """Stub every DB-touching collaborator of compute_deck_ev with one
    saved deck, one Hard matchup at a 40% paper WR, and a 50/50 field."""
    import db.saved_decks as sd
    import analysis.win_rates as wr
    import db.untapped_queries as uq
    import analysis.deck_ev as dev

    monkeypatch.setattr(sd, "get_deck", lambda _id: {"name": "My Prowess", "archetype": "Izzet Prowess"})
    monkeypatch.setattr(sd, "get_sb_plans",
                        lambda _id: [{"opponent_archetype": "Boros Energy", "difficulty": "Hard"}])
    monkeypatch.setattr(wr, "get_real_matchup_winrates",
                        lambda fmt, min_matches=10: {"Izzet Prowess": {"Boros Energy": {"win_rate": 0.40, "total": 120}}})
    monkeypatch.setattr(uq, "get_untapped_matchup_matrix", lambda fmt: {})
    monkeypatch.setattr(dev, "_game_one_prior", lambda: {"p1": 0.569, "n": 109})
    return {"Boros Energy": 0.5, "Amulet Titan": 0.5}


def test_compute_deck_ev_default_path_is_the_old_flat_bump(ev_env):
    from analysis.deck_ev import compute_deck_ev
    r = compute_deck_ev(1, field_shares=ev_env, format_name="modern")
    boros = next(x for x in r["rows"] if x["opponent"] == "Boros Energy")
    assert boros["pre_board_wr"] == pytest.approx(0.40)
    assert boros["post_board_wr"] == pytest.approx(0.35)       # 0.40 - 0.05, unchanged behaviour
    assert boros["math"] == "flat-bump"
    # required_q_for_even is computed on every row regardless of the path
    assert boros["required_q_for_even"] == pytest.approx(required_q(0.40, 0.50))
    assert r["g1_prior"] == {"p1": 0.569, "n": 109}


def test_compute_deck_ev_match_math_applies_bump_to_post_board_games(ev_env):
    from analysis.deck_ev import compute_deck_ev
    r = compute_deck_ev(1, field_shares=ev_env, format_name="modern", use_match_math=True)
    boros = next(x for x in r["rows"] if x["opponent"] == "Boros Energy")
    p1 = 0.40                                   # held at the observed match WR (no game-level data)
    q = implied_q(p1, 0.40)
    expected_post = match_winrate(p1, max(0.10, min(0.90, q - 0.05)))
    assert boros["post_board_wr"] == pytest.approx(expected_post)
    assert boros["post_board_wr"] != pytest.approx(0.35)       # differs from the flat bump
    assert boros["math"] == "implied-q"
    assert boros["implied_q"] == pytest.approx(q)
    assert boros["required_q_for_even"] == pytest.approx(required_q(p1, 0.50))


def test_compute_deck_ev_match_math_no_bump_is_a_no_op(ev_env):
    """With no sideboard plan the recomposition must return the observed WR."""
    from analysis.deck_ev import compute_deck_ev
    r = compute_deck_ev(1, field_shares=ev_env, format_name="modern", use_match_math=True)
    amulet = next(x for x in r["rows"] if x["opponent"] == "Amulet Titan")   # source "guess", 0.50
    assert amulet["post_board_wr"] == pytest.approx(amulet["pre_board_wr"])


# ---------------------------------------------------------------------------
# EV widget: unfavourable rows show the post-board game WR needed for 50%
# ---------------------------------------------------------------------------

def _fake_result():
    row_bad = {"opponent": "Boros Energy", "share": 0.5, "pre_board_wr": 0.40,
               "post_board_wr": 0.35, "difficulty": "Hard", "source": "paper",
               "sample_n": 120, "contribution": 0.175, "math": "flat-bump",
               "p1": 0.40, "implied_q": 0.449, "required_q_for_even": 0.5528}
    row_ok = {"opponent": "Amulet Titan", "share": 0.5, "pre_board_wr": 0.58,
              "post_board_wr": 0.58, "difficulty": "", "source": "paper",
              "sample_n": 60, "contribution": 0.29, "math": "flat-bump",
              "p1": 0.58, "implied_q": 0.58, "required_q_for_even": 0.45}
    return {"deck_name": "My Prowess", "deck_archetype": "Izzet Prowess",
            "field_total_share": 1.0, "field_weighted_wr": 0.465,
            "rows": [row_ok, row_bad], "best": [row_ok], "worst": [row_bad],
            "low_confidence_share": 0.0, "use_match_math": False,
            "g1_prior": {"p1": 0.569, "n": 109}}


def test_ev_widget_shows_required_q_for_unfavourable_rows(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.deck_ev_widget import DeckEvWidget
    w = DeckEvWidget()
    w._render(_fake_result())
    headers = [w._tbl.horizontalHeaderItem(i).text() for i in range(w._tbl.columnCount())]
    assert "Q for 50%" in headers
    col = headers.index("Q for 50%")
    by_name = {w._tbl.item(r, 0).text(): w._tbl.item(r, col) for r in range(w._tbl.rowCount())}
    assert by_name["Boros Energy"].text() == "55.3%"
    assert "post-board games" in by_name["Boros Energy"].toolTip()
    assert by_name["Amulet Titan"].text() == "\u2014"        # already >= 50%: nothing to reach
    assert "G1 prior" in w._sub_lbl.text() and "56.9%" in w._sub_lbl.text()
    w.deleteLater(); app.processEvents()


# ---------------------------------------------------------------------------
# Field shares: decks-derived first, matches-derived when the decks window is
# empty (Modern's decks table was empty for 14 days while the backfill was broken)
# ---------------------------------------------------------------------------

def _shares_con(with_decks: bool):
    import sqlite3
    from datetime import date, timedelta
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, format TEXT, date TEXT)")
    con.execute("CREATE TABLE decks (id INTEGER PRIMARY KEY, event_id INTEGER, archetype TEXT)")
    con.execute("""CREATE TABLE matches (id INTEGER PRIMARY KEY, event_id TEXT, round INTEGER,
        player1 TEXT, player2 TEXT, player1_arch TEXT, player2_arch TEXT, winner_arch TEXT,
        result TEXT, format TEXT, event_date TEXT, source TEXT)""")
    today = date.today().isoformat()
    if with_decks:
        con.execute("INSERT INTO events VALUES (1, 'modern', ?)", (today,))
        con.executemany("INSERT INTO decks (event_id, archetype) VALUES (1, ?)",
                        [("Boros Energy",)] * 6 + [("Amulet Titan",)] * 4)
    # a 16-player melee event: 8 Izzet Prowess, 8 Jeskai Blink, round robin
    from itertools import combinations
    arch = lambda i: "Izzet Prowess" if i < 8 else "Jeskai Blink"
    con.executemany("INSERT INTO matches (event_id, round, player1, player2, player1_arch, player2_arch, "
                    "winner_arch, result, format, event_date, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [("ev", r, f"p{a:02d}", f"p{b:02d}", arch(a), arch(b), arch(a), "player1",
                      "modern", (date.today() - timedelta(days=3)).isoformat(), "mtgmelee")
                     for r, (a, b) in enumerate(combinations(range(16), 2), start=1)])
    return con


def test_default_field_shares_prefers_decks():
    from analysis.deck_ev import _default_field_shares
    shares, source = _default_field_shares("modern", con=_shares_con(with_decks=True))
    assert source == "decks-14d"
    assert shares["Boros Energy"] == pytest.approx(0.6) and shares["Amulet Titan"] == pytest.approx(0.4)


def test_default_field_shares_falls_back_to_matches_when_decks_window_is_empty():
    from analysis.deck_ev import _default_field_shares
    shares, source = _default_field_shares("modern", con=_shares_con(with_decks=False))
    assert source == "matches-14d"
    assert shares["Izzet Prowess"] == pytest.approx(0.5) and shares["Jeskai Blink"] == pytest.approx(0.5)


def test_default_field_shares_empty_when_both_sources_empty():
    import sqlite3
    from analysis.deck_ev import _default_field_shares
    con = _shares_con(with_decks=False)
    con.execute("DELETE FROM matches")
    assert _default_field_shares("modern", con=con) == ({}, None)


def test_compute_deck_ev_reports_field_source(ev_env, monkeypatch):
    import analysis.deck_ev as dev
    from analysis.deck_ev import compute_deck_ev
    monkeypatch.setattr(dev, "_default_field_shares",
                        lambda fmt, con=None: ({"Boros Energy": 0.5, "Amulet Titan": 0.5}, "matches-14d"))
    r = compute_deck_ev(1, format_name="modern")          # no explicit field_shares
    assert r["field_source"] == "matches-14d"
    r2 = compute_deck_ev(1, field_shares={"Boros Energy": 1.0}, format_name="modern")
    assert r2["field_source"] == "explicit"
