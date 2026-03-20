"""
Chart generation for MTG Meta Analyzer.
Produces PNG files saved to data/charts/ and auto-opened on Windows.

Functions:
    meta_share_chart(format_name, top, weeks, since, until)  -> path
    archetype_trend_chart(archetype, format_name, weeks, since, until) -> path
    matchup_heatmap(format_name, top, min_appearances, since, until)   -> path

All functions return the path to the saved PNG.
"""

import os
import sys
import math
from datetime import datetime

import matplotlib
matplotlib.use("Agg")   # non-interactive backend — works without a display
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.colors as mcolors
import numpy as np

from analysis.win_rates import (
    get_archetype_trend,
    get_meta_standings,
    get_matchup_matrix,
    parse_date_range,
)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARTS_DIR = os.path.join(_project_root, "data", "charts")

# Palette — distinct colours for up to 15 archetypes
_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
]


def _ensure_charts_dir():
    os.makedirs(CHARTS_DIR, exist_ok=True)


def _save_and_open(fig, filename):
    """Save figure, close it, optionally open it. Returns path."""
    _ensure_charts_dir()
    path = os.path.join(CHARTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {path}")
    # Auto-open on Windows
    try:
        os.startfile(path)
    except Exception:
        pass
    return path


def _date_label(since, until):
    if since and until:
        return f"{since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}"
    if since:
        return f"since {since.strftime('%Y-%m-%d')}"
    return "all time"


def _shorten(name, max_len=22):
    return name if len(name) <= max_len else name[:max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Meta share over time — multiple archetypes
# ---------------------------------------------------------------------------

def meta_share_chart(format_name="standard", top=10, weeks=12,
                     since=None, until=None, include_archive=False,
                     event_type=None):
    """
    Line chart: meta share % per week for the top N archetypes.
    Returns path to saved PNG.
    """
    # Get top archetypes by avg_points over the window
    standings = get_meta_standings(
        format_name=format_name, min_appearances=2, top=top,
        include_archive=include_archive, since=since, until=until,
        event_type=event_type,
    )
    if not standings:
        print("  No meta standings data available.")
        return None

    archetypes = [s["archetype"] for s in standings]

    # Collect weekly data for each archetype
    # Build a unified week-start list
    all_weeks = set()
    arch_data = {}
    for arch in archetypes:
        weekly = get_archetype_trend(
            arch, format_name=format_name, weeks=weeks,
            include_archive=include_archive, since=since, until=until,
            event_type=event_type,
        )
        arch_data[arch] = {w["week_start"]: w["meta_share"] for w in weekly}
        all_weeks.update(arch_data[arch].keys())

    if not all_weeks:
        print("  No weekly trend data available.")
        return None

    sorted_weeks = sorted(all_weeks)
    x_labels = [w[5:]  for w in sorted_weeks]   # "MM-DD" from "YYYY-MM-DD"

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    for i, arch in enumerate(archetypes):
        color = _PALETTE[i % len(_PALETTE)]
        y = [arch_data[arch].get(w, 0) * 100 for w in sorted_weeks]
        ax.plot(x_labels, y, marker="o", markersize=4, linewidth=2,
                color=color, label=_shorten(arch), alpha=0.9)

    ax.set_title(f"Meta Share Over Time — {format_name.upper()}",
                 color="white", fontsize=14, pad=12)
    ax.set_xlabel("Week", color="white", fontsize=10)
    ax.set_ylabel("Meta Share %", color="white", fontsize=10)
    ax.tick_params(colors="white", labelsize=8)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=12))
    plt.xticks(rotation=45, ha="right")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(color="#2a2a4e", linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_edgecolor("#2a2a4e")

    legend = ax.legend(
        loc="upper left", fontsize=7, framealpha=0.3,
        labelcolor="white", facecolor="#1a1a2e", edgecolor="#2a2a4e",
        ncol=2,
    )

    date_str = _date_label(since, until)
    ax.annotate(f"Source: MTGTop8 | {date_str}",
                xy=(0.99, 0.01), xycoords="axes fraction",
                ha="right", va="bottom", color="#888888", fontsize=7)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_and_open(fig, f"meta_share_{format_name}_{ts}.png")


# ---------------------------------------------------------------------------
# Single archetype trend
# ---------------------------------------------------------------------------

def archetype_trend_chart(archetype, format_name="standard", weeks=12,
                           since=None, until=None, include_archive=False,
                           event_type=None):
    """
    Dual-axis chart for one archetype:
      - Bars: appearances per week
      - Left line: meta share %
      - Right line: estimated win %
    Returns path to saved PNG.
    """
    weekly = get_archetype_trend(
        archetype, format_name=format_name, weeks=weeks,
        include_archive=include_archive, since=since, until=until,
        event_type=event_type,
    )
    if not weekly:
        print(f"  No trend data for '{archetype}'.")
        return None

    weekly = list(reversed(weekly))    # oldest first for left-to-right
    x_labels = [w["week_start"][5:] for w in weekly]  # MM-DD
    appearances = [w["appearances"] for w in weekly]
    meta_share  = [w["meta_share"] * 100 for w in weekly]
    est_winpct  = [w["est_winpct"] * 100 if w["est_winpct"] is not None else None
                   for w in weekly]
    top8_rate   = [w["top8_rate"] * 100  if w["top8_rate"]  is not None else None
                   for w in weekly]

    fig, ax1 = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax1.set_facecolor("#16213e")
    ax2 = ax1.twinx()

    # Bars — appearances
    bar_color = "#4363d8"
    ax1.bar(x_labels, appearances, color=bar_color, alpha=0.4, label="Appearances", zorder=2)
    ax1.set_ylabel("Appearances", color=bar_color, fontsize=10)
    ax1.tick_params(axis="y", colors=bar_color, labelsize=8)
    ax1.tick_params(axis="x", colors="white", labelsize=8)
    plt.xticks(rotation=45, ha="right")

    # Lines — right axis
    def _plot_line(ax, values, color, label, linestyle="-"):
        xs = [x_labels[i] for i, v in enumerate(values) if v is not None]
        ys = [v for v in values if v is not None]
        if xs:
            ax.plot(xs, ys, color=color, linewidth=2.5, linestyle=linestyle,
                    marker="o", markersize=5, label=label, zorder=3)

    _plot_line(ax2, meta_share,  "#3cb44b", "Meta Share %")
    _plot_line(ax2, est_winpct,  "#e6194b", "Est. Win %", linestyle="--")
    _plot_line(ax2, top8_rate,   "#f58231", "Top 8 Rate %", linestyle=":")

    ax2.set_ylabel("Rate %", color="white", fontsize=10)
    ax2.tick_params(axis="y", colors="white", labelsize=8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax2.set_ylim(bottom=0)

    # Draw 50% reference line on right axis
    ax2.axhline(50, color="#555577", linewidth=0.8, linestyle="--", zorder=1)

    ax1.set_title(f"{archetype} — {format_name.upper()} Trend",
                  color="white", fontsize=14, pad=12)
    ax1.set_xlabel("Week (start)", color="white", fontsize=10)
    ax1.grid(color="#2a2a4e", linewidth=0.5, zorder=0)
    for spine in ax1.spines.values():
        spine.set_edgecolor("#2a2a4e")
    for spine in ax2.spines.values():
        spine.set_edgecolor("#2a2a4e")

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper left", fontsize=8, framealpha=0.3,
               labelcolor="white", facecolor="#1a1a2e", edgecolor="#2a2a4e")

    date_str = _date_label(since, until)
    ax1.annotate(f"Source: MTGTop8 | {date_str} | Est. Win% based on placement",
                 xy=(0.99, 0.01), xycoords="axes fraction",
                 ha="right", va="bottom", color="#888888", fontsize=7)

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = archetype.replace(" ", "_").replace("/", "-")[:30]
    return _save_and_open(fig, f"trend_{safe}_{format_name}_{ts}.png")


# ---------------------------------------------------------------------------
# Matchup heatmap
# ---------------------------------------------------------------------------

def matchup_heatmap(format_name="standard", top=12, min_appearances=3,
                    since=None, until=None, include_archive=False):
    """
    NxN heatmap of placement-based win rates between top archetypes.
    Green = favored (>50%), Red = unfavored (<50%), Grey = no data.
    Returns path to saved PNG.
    """
    data = get_matchup_matrix(
        format_name=format_name, min_appearances=min_appearances,
        include_archive=include_archive, since=since, until=until, top=top,
    )
    archetypes = data["archetypes"]
    matrix     = data["matrix"]

    if not archetypes:
        print("  No matchup matrix data available.")
        return None

    n = len(archetypes)
    # Build numpy matrix (NaN = no data / self)
    mat = np.full((n, n), np.nan)
    for i, a in enumerate(archetypes):
        for j, b in enumerate(archetypes):
            if i == j:
                continue
            if b in matrix.get(a, {}):
                mat[i, j] = matrix[a][b]["win_rate"]

    # Short labels
    short = [_shorten(a, 18) for a in archetypes]

    fig, ax = plt.subplots(figsize=(max(8, n * 0.8), max(6, n * 0.7)))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Custom colormap: red → white (50%) → green, grey for NaN
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color="#2a2a3e")

    im = ax.imshow(mat, cmap=cmap, vmin=0.0, vmax=1.0, aspect="auto")

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Win Rate", color="white", fontsize=9)
    cbar.ax.yaxis.set_tick_params(color="white", labelsize=8)
    cbar.ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v*100:.0f}%")
    )
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white")

    # Annotate cells
    for i in range(n):
        for j in range(n):
            if i == j:
                ax.text(j, i, "—", ha="center", va="center",
                        color="#555577", fontsize=8)
            elif not np.isnan(mat[i, j]):
                val   = mat[i, j]
                color = "black" if 0.3 < val < 0.7 else "white"
                ev    = matrix.get(archetypes[i], {}).get(archetypes[j], {})
                shared = ev.get("shared_events", 0)
                ax.text(j, i, f"{val*100:.0f}%\n({shared})",
                        ha="center", va="center", color=color, fontsize=7,
                        fontweight="bold" if abs(val - 0.5) > 0.1 else "normal")
            else:
                ax.text(j, i, "n/a", ha="center", va="center",
                        color="#444466", fontsize=7)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(short, rotation=45, ha="right", color="white", fontsize=8)
    ax.set_yticklabels(short, color="white", fontsize=8)
    ax.set_xlabel("Opponent →", color="#aaaacc", fontsize=9)
    ax.set_ylabel("↑ This deck", color="#aaaacc", fontsize=9)

    ax.set_title(f"Matchup Matrix — {format_name.upper()}",
                 color="white", fontsize=13, pad=12)
    ax.tick_params(length=0)

    date_str = _date_label(since, until)
    ax.annotate(
        f"Number in cell = shared events | {date_str} | Based on placement, not actual match results",
        xy=(0.5, -0.18 - n * 0.005), xycoords="axes fraction",
        ha="center", va="bottom", color="#888888", fontsize=7
    )

    fig.tight_layout()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_and_open(fig, f"heatmap_{format_name}_{ts}.png")
