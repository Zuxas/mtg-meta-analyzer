"""#32 (read side): raw match pairs that normalize to the same matchup are
pooled in the heatmap, not overwritten by whichever came last."""
import pytest

from analysis.archetypes import normalize
from gui.tabs.heatmap_tab import pool_real_matchups


def _st(wins, losses, draws=0):
    return {"win_rate": round(wins / (wins + losses), 4) if wins + losses else 0.5,
            "wins": wins, "losses": losses, "draws": draws,
            "total": wins + losses + draws}


def test_issue_example_pools_to_one_cell():
    # 'UR Prowess' and 'Izzet Prowess' both normalize to Izzet Prowess
    raw = {"Dimir Midrange": {"UR Prowess": _st(10, 15)},          # Dimir's view, 25
           "Izzet Prowess": {"Dimir Midrange": _st(24, 16)}}       # Prowess' view, 40
    m = pool_real_matchups(raw, normalize)
    cell = m["Izzet Prowess"]["Dimir Midrange"]
    assert cell["matches"] == 65
    assert cell["winrate"] == pytest.approx((15 + 24) / 65, abs=1e-4)
    back = m["Dimir Midrange"]["Izzet Prowess"]
    assert back["matches"] == 65
    assert back["winrate"] == pytest.approx(1 - cell["winrate"], abs=1e-4)


def test_draws_count_in_matches_not_in_the_rate():
    m = pool_real_matchups({"A Deck": {"B Deck": _st(3, 1, draws=2)}}, lambda x: x)
    assert m["A Deck"]["B Deck"] == {"winrate": 0.75, "matches": 6}


def test_pair_that_normalizes_to_a_mirror_is_dropped():
    m = pool_real_matchups({"UR Prowess": {"Izzet Prowess": _st(5, 5)}}, normalize)
    assert m == {}


def test_no_decisive_games_is_even():
    m = pool_real_matchups({"A Deck": {"B Deck": _st(0, 0, draws=3)}}, lambda x: x)
    assert m["A Deck"]["B Deck"] == {"winrate": 0.5, "matches": 3}
    assert m["B Deck"]["A Deck"] == {"winrate": 0.5, "matches": 3}
