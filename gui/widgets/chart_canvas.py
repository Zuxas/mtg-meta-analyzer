"""
Reusable interactive matplotlib chart canvas for PyQt6.

All data loading runs in background QThread workers so the UI never blocks.
Drawing always happens on the main thread after the worker completes.

IMPORTANT: This module must be imported AFTER matplotlib.use("QtAgg") is
set in run_gui.py. Do NOT import analysis.charts here — it sets Agg backend
at module level and would conflict.
"""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
import matplotlib.ticker as mticker
import matplotlib.colors as mcolors
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#fffac8", "#800000", "#aaffc3",
]
_BG   = "#1a1a2e"
_MID  = "#16213e"
_GRID = "#2a2a4e"


def _shorten(name, max_len=22):
    return name if len(name) <= max_len else name[:max_len - 1] + "\u2026"


def _style_ax(ax, fig):
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_MID)
    ax.tick_params(colors="white", labelsize=8)
    ax.grid(color=_GRID, linewidth=0.5, zorder=0)
    for spine in ax.spines.values():
        spine.set_edgecolor(_GRID)


# ---------------------------------------------------------------------------
# Background data-loading workers
# ---------------------------------------------------------------------------

class _MetaShareLoader(QThread):
    done  = pyqtSignal(object)   # dict with data, or None
    error = pyqtSignal(str)

    def __init__(self, format_name, top, weeks, since, until, standings=None):
        super().__init__()
        self.format_name = format_name
        self.top         = top
        self.weeks       = weeks
        self.since       = since
        self.until       = until
        self._standings  = standings   # pre-loaded standings to avoid a duplicate DB call

    def run(self):
        try:
            from analysis.win_rates import get_meta_standings, get_archetype_trend
            standings = self._standings
            if standings is None:
                standings = get_meta_standings(
                    format_name=self.format_name, min_appearances=2, top=self.top,
                    since=self.since, until=self.until,
                )
            if not standings:
                self.done.emit(None)
                return
            archetypes = [s["archetype"] for s in standings]
            all_weeks  = set()
            arch_data  = {}
            for arch in archetypes:
                weekly = get_archetype_trend(
                    arch, format_name=self.format_name, weeks=self.weeks,
                    since=self.since, until=self.until,
                )
                arch_data[arch] = {w["week_start"]: w["meta_share"] for w in weekly}
                all_weeks.update(arch_data[arch].keys())
            if not all_weeks:
                self.done.emit(None)
                return
            self.done.emit({"archetypes": archetypes,
                            "arch_data":  arch_data,
                            "all_weeks":  all_weeks,
                            "format_name": self.format_name})
        except Exception as e:
            self.error.emit(str(e))


class _TrendLoader(QThread):
    done  = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, archetype, format_name, weeks, since, until):
        super().__init__()
        self.archetype   = archetype
        self.format_name = format_name
        self.weeks       = weeks
        self.since       = since
        self.until       = until

    def run(self):
        try:
            from analysis.win_rates import get_archetype_trend
            weekly = get_archetype_trend(
                self.archetype, format_name=self.format_name, weeks=self.weeks,
                since=self.since, until=self.until,
            )
            self.done.emit(weekly if weekly else None)
        except Exception as e:
            self.error.emit(str(e))


class _HeatmapLoader(QThread):
    done  = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, format_name, top, min_appearances, since, until):
        super().__init__()
        self.format_name     = format_name
        self.top             = top
        self.min_appearances = min_appearances
        self.since           = since
        self.until           = until

    def run(self):
        try:
            from analysis.win_rates import get_matchup_matrix
            data = get_matchup_matrix(
                format_name=self.format_name,
                min_appearances=self.min_appearances,
                since=self.since, until=self.until, top=self.top,
            )
            self.done.emit(data if data else None)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Chart canvas widget
# ---------------------------------------------------------------------------

class ChartCanvas(QWidget):
    """
    Embeds a matplotlib Figure with an interactive navigation toolbar.
    Data loading always runs in a background thread; drawing on the main thread.

    Public methods:
        plot_meta_share(format_name, top, weeks, since, until)
        plot_trend(archetype, format_name, weeks, since, until)
        plot_heatmap(format_name, top, min_appearances, since, until)
        show_message(text, color)
        clear()
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fig    = Figure(figsize=(10, 5), facecolor=_BG, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._toolbar.setStyleSheet(
            "QToolBar { background: #0d0d1e; border: none; spacing: 4px; }"
            "QToolButton { background: #2a2a4e; color: white; border-radius: 3px;"
            "              padding: 3px; }"
            "QToolButton:hover { background: #4363d8; }"
        )

        # Overlay label shown while loading or when no data available
        self._overlay = QLabel("Select a chart type and click Generate", self._canvas)
        self._overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay.setFont(QFont("Arial", 13))
        self._overlay.setStyleSheet("color: #555555; background: transparent;")
        self._overlay.setVisible(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas, 1)

        # Keep worker references alive until they finish
        self._worker = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_overlay(self, msg, color="#555555"):
        self._overlay.setText(msg)
        self._overlay.setStyleSheet(f"color: {color}; background: transparent;")
        self._overlay.setVisible(True)
        self._overlay.resize(self._canvas.size())

    def show_message(self, msg, color="#555555"):
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        ax.set_facecolor(_BG)
        self._fig.patch.set_facecolor(_BG)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        self._set_overlay(msg, color)
        self._canvas.draw()

    def clear(self):
        self.show_message("No data loaded")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self._canvas.size())

    # ------------------------------------------------------------------
    # Meta share — line chart, top N archetypes over time
    # ------------------------------------------------------------------

    def plot_meta_share(self, format_name="standard", top=10, weeks=12,
                        since=None, until=None, standings=None):
        """standings: pass pre-loaded list from get_meta_standings() to skip that DB call."""
        self.show_message("Loading meta data\u2026", "#4363d8")
        self._worker = _MetaShareLoader(format_name, top, weeks, since, until, standings)
        self._worker.done.connect(self._draw_meta_share)
        self._worker.error.connect(
            lambda e: self.show_message(f"Error: {e}", "#e6194b")
        )
        self._worker.start()

    def _draw_meta_share(self, data):
        if data is None:
            self.show_message("No meta data available for this selection.")
            return

        archetypes   = data["archetypes"]
        arch_data    = data["arch_data"]
        sorted_weeks = sorted(data["all_weeks"])
        x_labels     = [w[5:] for w in sorted_weeks]

        self._fig.clear()
        self._overlay.setVisible(False)
        ax = self._fig.add_subplot(111)
        _style_ax(ax, self._fig)

        for i, arch in enumerate(archetypes):
            color = _PALETTE[i % len(_PALETTE)]
            y = [arch_data[arch].get(w, 0) * 100 for w in sorted_weeks]
            ax.plot(x_labels, y, marker="o", markersize=4, linewidth=2,
                    color=color, label=_shorten(arch), alpha=0.9)

        ax.set_title(f"Meta Share Over Time \u2014 {data.get('format_name', 'standard').upper()}",
                     color="white", fontsize=13, pad=10)
        ax.set_xlabel("Week", color="white", fontsize=9)
        ax.set_ylabel("Meta Share %", color="white", fontsize=9)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=12))
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45); lbl.set_ha("right")
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
        )
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3,
                  labelcolor="white", facecolor=_BG, edgecolor=_GRID, ncol=2)
        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    # Archetype trend — dual-axis bars + lines
    # ------------------------------------------------------------------

    def plot_trend(self, archetype, format_name="standard", weeks=12,
                   since=None, until=None):
        self.show_message(f"Loading trend for {_shorten(archetype)}\u2026", "#4363d8")
        self._worker = _TrendLoader(archetype, format_name, weeks, since, until)
        self._worker.done.connect(
            lambda data: self._draw_trend(data, archetype, format_name)
        )
        self._worker.error.connect(
            lambda e: self.show_message(f"Error: {e}", "#e6194b")
        )
        self._worker.start()

    def _draw_trend(self, weekly, archetype, format_name):
        if not weekly:
            self.show_message(f"No trend data for \u2018{archetype}\u2019.")
            return

        weekly      = list(reversed(weekly))
        x_labels    = [w["week_start"][5:] for w in weekly]
        appearances = [w["appearances"] for w in weekly]
        meta_share  = [w["meta_share"] * 100 for w in weekly]
        est_winpct  = [
            w["est_winpct"] * 100 if w["est_winpct"] is not None else None
            for w in weekly
        ]
        top8_rate = [
            w["top8_rate"] * 100 if w["top8_rate"] is not None else None
            for w in weekly
        ]

        self._fig.clear()
        self._overlay.setVisible(False)
        ax1 = self._fig.add_subplot(111)
        _style_ax(ax1, self._fig)
        ax2 = ax1.twinx()

        bar_color = "#4363d8"
        ax1.bar(x_labels, appearances, color=bar_color, alpha=0.4,
                label="Appearances", zorder=2)
        ax1.set_ylabel("Appearances", color=bar_color, fontsize=9)
        ax1.tick_params(axis="y", colors=bar_color, labelsize=8)
        ax1.tick_params(axis="x", colors="white", labelsize=8)
        for lbl in ax1.get_xticklabels():
            lbl.set_rotation(45); lbl.set_ha("right")

        line_handles, line_labels = [], []

        if any(v is not None for v in meta_share):
            xs = [x for x, v in zip(x_labels, meta_share) if v is not None]
            ys = [v for v in meta_share if v is not None]
            h, = ax2.plot(xs, ys, color="#e6194b", marker="o",
                          markersize=4, linewidth=2, label="Meta %")
            line_handles.append(h); line_labels.append("Meta %")

        if any(v is not None for v in est_winpct):
            xs = [x for x, v in zip(x_labels, est_winpct) if v is not None]
            ys = [v for v in est_winpct if v is not None]
            h, = ax2.plot(xs, ys, color="#3cb44b", marker="s",
                          markersize=3, linewidth=1.5, linestyle="--", label="Est Win %")
            line_handles.append(h); line_labels.append("Est Win %")

        if any(v is not None for v in top8_rate):
            xs = [x for x, v in zip(x_labels, top8_rate) if v is not None]
            ys = [v for v in top8_rate if v is not None]
            h, = ax2.plot(xs, ys, color="#f58231", marker="^",
                          markersize=3, linewidth=1.5, linestyle=":", label="Top8 %")
            line_handles.append(h); line_labels.append("Top8 %")

        ax2.set_ylabel("Rate %", color="#e6194b", fontsize=9)
        ax2.tick_params(axis="y", colors="#e6194b", labelsize=8)
        ax2.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
        )
        ax2.set_facecolor(_MID)

        ax1.set_title(
            f"{_shorten(archetype, 40)} \u2014 {format_name.upper()} Trend",
            color="white", fontsize=12, pad=10,
        )
        bar_proxy = ax1.bar([], [], color=bar_color, alpha=0.4, label="Appearances")
        ax1.legend(
            [bar_proxy] + line_handles,
            ["Appearances"] + line_labels,
            loc="upper left", fontsize=7, framealpha=0.3,
            labelcolor="white", facecolor=_BG, edgecolor=_GRID,
        )
        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    # Matchup heatmap — NxN grid
    # ------------------------------------------------------------------

    def plot_heatmap(self, format_name="standard", top=10, min_appearances=3,
                     since=None, until=None):
        self.show_message("Loading matchup data\u2026", "#4363d8")
        self._worker = _HeatmapLoader(format_name, top, min_appearances, since, until)
        self._worker.done.connect(
            lambda data: self._draw_heatmap(data, format_name)
        )
        self._worker.error.connect(
            lambda e: self.show_message(f"Error: {e}", "#e6194b")
        )
        self._worker.start()

    def _draw_heatmap(self, matrix_data, format_name):
        if not matrix_data:
            self.show_message(
                "Not enough matchup data.\n"
                "Try lowering min appearances or expanding the date range."
            )
            return

        archetypes = list(matrix_data.keys())
        n = len(archetypes)
        if n < 2:
            self.show_message("Need at least 2 archetypes with matchup data.")
            return

        grid = np.full((n, n), float("nan"))
        for i, arch_a in enumerate(archetypes):
            for j, arch_b in enumerate(archetypes):
                val = matrix_data[arch_a].get(arch_b)
                if val is not None:
                    grid[i][j] = val * 100

        self._fig.clear()
        self._overlay.setVisible(False)
        self._fig.set_size_inches(max(8, n * 0.85), max(5, n * 0.80))

        ax = self._fig.add_subplot(111)
        _style_ax(ax, self._fig)

        cmap   = mcolors.LinearSegmentedColormap.from_list(
            "rdylgn", ["#e6194b", "#fffac8", "#3cb44b"]
        )
        masked = np.ma.masked_invalid(grid)
        im     = ax.imshow(masked, cmap=cmap, vmin=30, vmax=70, aspect="auto")

        short_names = [_shorten(a, 18) for a in archetypes]
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(short_names, rotation=45, ha="right",
                           fontsize=7, color="white")
        ax.set_yticklabels(short_names, fontsize=7, color="white")
        ax.set_xlabel("Opponent (column)", color="#aaa", fontsize=8)
        ax.set_ylabel("Deck (row)", color="#aaa", fontsize=8)

        fs = max(5, 8 - n // 4)
        for i in range(n):
            for j in range(n):
                if not np.isnan(grid[i][j]):
                    v  = grid[i][j]
                    tc = "black" if 38 < v < 62 else "white"
                    ax.text(j, i, f"{v:.0f}%",
                            ha="center", va="center",
                            fontsize=fs, color=tc, fontweight="bold")

        cbar = self._fig.colorbar(im, ax=ax, shrink=0.75)
        cbar.ax.tick_params(colors="white", labelsize=7)
        cbar.set_label("Win % (row vs col)", color="white", fontsize=8)

        ax.set_title(
            f"Matchup Heatmap \u2014 {format_name.upper()}",
            color="white", fontsize=12, pad=10,
        )
        self._fig.tight_layout()
        self._canvas.draw()
