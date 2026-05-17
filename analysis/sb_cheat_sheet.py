"""SB cheat-sheet renderer — produces a 1-page printable matplotlib
Figure of all sideboard plans for a saved deck. Caller (or the
export_cheat_sheet wrapper) handles file I/O.

Pure-function design lets the test suite verify rendering without
touching the file system or GUI.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from db.saved_decks import get_sb_plans
from db.database import get_connection


_PER_PAGE_COLS = 3
_PER_PAGE_ROWS = 6
_PER_PAGE = _PER_PAGE_COLS * _PER_PAGE_ROWS  # 18

# US Letter portrait in inches
_PAGE_W_IN = 8.5
_PAGE_H_IN = 11.0

# Difficulty palette — dark backgrounds suitable for color print or screen.
# Each entry has 'bg' (tile face) and 'border' (axis spine color).
_DIFFICULTY_COLORS = {
    "Easy":   {"bg": "#1a3320", "border": "#80c890"},
    "Medium": {"bg": "#1a1f33", "border": "#6080c8"},
    "Hard":   {"bg": "#33201a", "border": "#d88060"},
    None:     {"bg": "#1a1a1a", "border": "#666666"},
}

_TEXT_FG = "#e6e6e6"
_TEXT_DIM = "#9aa0b4"
_MAX_INOUT_LINES = 7


def _fetch_deck_name(deck_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name, format FROM saved_decks WHERE id = ?", (deck_id,),
        ).fetchone()
    if row is None:
        return f"Deck #{deck_id}"
    return f"{row['name']} ({row['format'] or 'no format'})"


def _format_inout(card_names: list[str], sign: str) -> list[str]:
    """Collapse duplicates into '+N CardName' / '-N CardName' lines.
    Truncates to _MAX_INOUT_LINES with a '+N more...' tail."""
    counter = Counter(card_names or [])
    lines = [f"{sign}{n} {name}" for name, n in counter.most_common()]
    if len(lines) > _MAX_INOUT_LINES:
        extra = len(lines) - (_MAX_INOUT_LINES - 1)
        lines = lines[: _MAX_INOUT_LINES - 1] + [f"{sign}{extra} more..."]
    return lines


def _render_tile(ax, plan: dict) -> None:
    """Render one plan into an existing axis. Axis is configured with
    no ticks/labels; we paint a colored background + text."""
    difficulty = plan.get("difficulty") or None
    palette = _DIFFICULTY_COLORS.get(difficulty, _DIFFICULTY_COLORS[None])

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor(palette["bg"])
    for spine in ax.spines.values():
        spine.set_edgecolor(palette["border"])
        spine.set_linewidth(1.5)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_gid("plan_tile")  # so tests can find these axes

    # Header: opponent archetype
    opp = plan.get("opponent_archetype") or "(unknown)"
    ax.text(
        0.04, 0.92, opp,
        fontsize=11, fontweight="bold", color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
    )
    # Difficulty chip top-right
    ax.text(
        0.96, 0.92, (difficulty or "—"),
        fontsize=8, color=palette["border"],
        transform=ax.transAxes, verticalalignment="top",
        horizontalalignment="right",
    )

    # IN / OUT columns — use play_in/play_out (primary) since most
    # matchups have same swaps for play and draw; the user can lean on
    # notes / GUI for play vs draw distinctions.
    in_lines = _format_inout(plan.get("play_in") or [], "+")
    out_lines = _format_inout(plan.get("play_out") or [], "-")

    ax.text(
        0.04, 0.78, "IN",
        fontsize=8, color=_TEXT_DIM,
        transform=ax.transAxes, verticalalignment="top",
    )
    ax.text(
        0.04, 0.72, "\n".join(in_lines) or "(none)",
        fontsize=8, color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
        family="monospace",
    )

    ax.text(
        0.54, 0.78, "OUT",
        fontsize=8, color=_TEXT_DIM,
        transform=ax.transAxes, verticalalignment="top",
    )
    ax.text(
        0.54, 0.72, "\n".join(out_lines) or "(none)",
        fontsize=8, color=_TEXT_FG,
        transform=ax.transAxes, verticalalignment="top",
        family="monospace",
    )


def build_cheat_sheet_figure(
    deck_id: int,
    *,
    page_num: int = 1,
) -> Figure:
    """Build the cheat-sheet figure for one page of plans.

    Returns the matplotlib Figure (caller owns lifecycle / must close).
    Raises ValueError if deck_id doesn't exist or has no SB plans."""
    plans = get_sb_plans(deck_id)
    if not plans:
        raise ValueError(f"Deck #{deck_id} has no sideboard plans to render")

    start_idx = (page_num - 1) * _PER_PAGE
    page_plans = plans[start_idx : start_idx + _PER_PAGE]
    if not page_plans:
        raise ValueError(
            f"page_num={page_num} is out of range for deck #{deck_id} "
            f"({len(plans)} plans, {_PER_PAGE} per page)"
        )

    fig = Figure(figsize=(_PAGE_W_IN, _PAGE_H_IN), facecolor="#0c0d14")

    # Header axis (top ~10% of page)
    header_ax = fig.add_axes((0.04, 0.92, 0.92, 0.06))
    header_ax.set_xticks([])
    header_ax.set_yticks([])
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    header_ax.set_facecolor("#0c0d14")
    total_pages = (len(plans) + _PER_PAGE - 1) // _PER_PAGE
    header_ax.text(
        0.0, 0.7, _fetch_deck_name(deck_id),
        fontsize=14, fontweight="bold", color=_TEXT_FG,
        transform=header_ax.transAxes,
    )
    header_ax.text(
        0.0, 0.1,
        f"{len(plans)} sideboard plans  ·  page {page_num} of {total_pages}  ·  "
        f"generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        fontsize=9, color=_TEXT_DIM,
        transform=header_ax.transAxes,
    )

    # Tile grid (remaining ~85% of page)
    grid_top = 0.90
    grid_bottom = 0.03
    grid_left = 0.04
    grid_right = 0.96
    cell_w = (grid_right - grid_left) / _PER_PAGE_COLS
    cell_h = (grid_top - grid_bottom) / _PER_PAGE_ROWS
    inner_pad_x = 0.005
    inner_pad_y = 0.008

    for i, plan in enumerate(page_plans):
        row = i // _PER_PAGE_COLS
        col = i % _PER_PAGE_COLS
        x = grid_left + col * cell_w + inner_pad_x
        y = grid_top - (row + 1) * cell_h + inner_pad_y
        w = cell_w - 2 * inner_pad_x
        h = cell_h - 2 * inner_pad_y
        ax = fig.add_axes((x, y, w, h))
        _render_tile(ax, plan)

    return fig
