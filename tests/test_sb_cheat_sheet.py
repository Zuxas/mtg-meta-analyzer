"""Tests for analysis/sb_cheat_sheet.py — SB plan grid renderer."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "sb.db"
    monkeypatch.setattr("db.database.DB_PATH", db_path)
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "sb_arc.db")
    yield db_path


def _seed_deck_with_plans(plan_specs: list[dict]) -> int:
    """Insert a saved deck + N SB plans. Returns deck_id."""
    from db import saved_decks
    saved_decks._ensure_tables()
    deck_id = saved_decks.save_deck(
        name="Test Deck", format_name="standard", archetype="Test",
        mainboard={"Mountain": 60}, sideboard={}, notes="",
    )
    for spec in plan_specs:
        saved_decks.save_sb_plan(
            deck_id=deck_id,
            opponent_archetype=spec["opp"],
            play_in=spec.get("play_in", []),
            play_out=spec.get("play_out", []),
            draw_in=spec.get("draw_in", []),
            draw_out=spec.get("draw_out", []),
            notes="",
            difficulty=spec.get("difficulty", "Medium"),
        )
    return deck_id


def test_build_figure_returns_matplotlib_figure(tmp_db):
    from matplotlib.figure import Figure
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([
        {"opp": "Azorius Control", "play_in": ["Brotherhood's End"] * 2,
         "play_out": ["Slickshot Show-Off"] * 2, "difficulty": "Easy"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    assert isinstance(fig, Figure)
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_build_figure_raises_for_deck_with_no_plans(tmp_db):
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([])
    with pytest.raises(ValueError, match="no sideboard plans"):
        build_cheat_sheet_figure(deck_id)


def test_build_figure_includes_all_plans_on_one_page_when_under_18(tmp_db):
    """3 plans → 3 subplot axes (excluding the header axis)."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    deck_id = _seed_deck_with_plans([
        {"opp": "Az Control", "difficulty": "Easy"},
        {"opp": "Boros Energy", "difficulty": "Medium"},
        {"opp": "Mono Green", "difficulty": "Hard"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    # Plan tile axes are tagged with gid="plan_tile" so we can count them
    plan_axes = [ax for ax in fig.axes if ax.get_gid() == "plan_tile"]
    assert len(plan_axes) == 3
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_difficulty_color_applied_per_tile(tmp_db):
    """Easy tile must have green-family facecolor, Hard must have
    red-family. Verifies the difficulty palette dispatch."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure, _DIFFICULTY_COLORS
    deck_id = _seed_deck_with_plans([
        {"opp": "Easy Matchup", "difficulty": "Easy"},
        {"opp": "Hard Matchup", "difficulty": "Hard"},
    ])
    fig = build_cheat_sheet_figure(deck_id)
    plan_axes = [ax for ax in fig.axes if ax.get_gid() == "plan_tile"]
    # Order matches alphabetical opponent_archetype: Easy Matchup, Hard Matchup
    easy_bg = plan_axes[0].get_facecolor()
    hard_bg = plan_axes[1].get_facecolor()
    expected_easy = _DIFFICULTY_COLORS["Easy"]["bg"]
    expected_hard = _DIFFICULTY_COLORS["Hard"]["bg"]
    # Compare RGB tuples; matplotlib returns 4-tuples with alpha
    from matplotlib.colors import to_rgb
    assert easy_bg[:3] == pytest.approx(to_rgb(expected_easy), abs=0.01)
    assert hard_bg[:3] == pytest.approx(to_rgb(expected_hard), abs=0.01)
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_pagination_via_page_num_kwarg(tmp_db):
    """Deck with 20 plans + page_num=2 → page 2 has plans 19-20 (2 tiles)."""
    from analysis.sb_cheat_sheet import build_cheat_sheet_figure
    specs = [{"opp": f"Archetype {i:02d}"} for i in range(20)]
    deck_id = _seed_deck_with_plans(specs)
    fig_p2 = build_cheat_sheet_figure(deck_id, page_num=2)
    plan_axes = [ax for ax in fig_p2.axes if ax.get_gid() == "plan_tile"]
    assert len(plan_axes) == 2  # 20 total, 18/page → 2 on page 2
    import matplotlib.pyplot as plt
    plt.close(fig_p2)
