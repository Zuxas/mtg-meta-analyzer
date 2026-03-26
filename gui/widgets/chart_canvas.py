"""
Reusable interactive matplotlib chart canvas for PyQt6.

All data loading runs in background QThread workers so the UI never blocks.
Drawing always happens on the main thread after the worker completes.

IMPORTANT: This module must be imported AFTER matplotlib.use("QtAgg") is
set in run_gui.py. Do NOT import analysis.charts here — it sets Agg backend
at module level and would conflict.
"""
import os, json
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
import matplotlib.ticker as mticker
import matplotlib.colors as mcolors
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from gui.theme import CHART_PALETTE as _PALETTE, CHART_BG as _BG, CHART_PANEL as _MID, CHART_GRID as _GRID

# ---------------------------------------------------------------------------
# Format event markers (set releases, B&R, rotations)
# ---------------------------------------------------------------------------

_EVENT_COLORS = {
    "set_release": "#42a5f5",   # blue
    "rotation":    "#f58231",   # orange
    "banlist":     "#e6194b",   # red
}

_FORMAT_EVENTS: dict = {}  # lazy-loaded


def _load_format_events() -> dict:
    global _FORMAT_EVENTS
    if _FORMAT_EVENTS:
        return _FORMAT_EVENTS
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "format_events.json",
    )
    try:
        with open(path, encoding="utf-8") as f:
            _FORMAT_EVENTS = json.load(f)
    except Exception:
        _FORMAT_EVENTS = {}
    return _FORMAT_EVENTS


def _draw_event_markers(ax, x_labels: list[str], sorted_keys: list[str],
                        format_name: str):
    """Overlay vertical dashed lines for format events that fall within the chart range."""
    events = _load_format_events().get(format_name.lower(), [])
    if not events or not sorted_keys:
        return

    # sorted_keys are bucket start dates like "2025-01-06"
    # x_labels are the shortened display versions like "01-06"
    first_date = sorted_keys[0]
    last_date  = sorted_keys[-1]

    for ev in events:
        d = ev["date"]
        if d < first_date or d > last_date:
            continue
        # Find the closest x position
        best_idx = 0
        best_dist = abs(ord(d[5]) - ord(first_date[5]))  # rough
        for i, k in enumerate(sorted_keys):
            if k <= d:
                best_idx = i
        color = _EVENT_COLORS.get(ev.get("type"), "#888888")
        ax.axvline(x=best_idx, color=color, linestyle="--",
                   linewidth=1, alpha=0.6, zorder=1)
        ax.annotate(ev.get("short", ""),
                    xy=(best_idx, 1.0),
                    xycoords=("data", "axes fraction"),
                    rotation=45, fontsize=6, color=color,
                    ha="left", va="bottom", clip_on=False, alpha=0.85)


def fetch_chart_data(format_name, top, weeks, since, until, standings=None,
                     dedup_cross_source=True, unique_player_decks=False,
                     granularity="weekly"):
    """
    Load time-bucketed meta_share AND est_winpct for all archetypes in one pass.
    Designed to run in a DataLoadWorker; returns a dict or None.
    Result is cache-friendly — pass to ChartCanvas.draw_from_data() to draw.

    granularity: "weekly" (default) or "daily".
    """
    from analysis.win_rates import get_meta_standings, get_archetype_trend
    if standings is None:
        standings = get_meta_standings(
            format_name=format_name, min_appearances=2,
            top=top, since=since, until=until,
            dedup_cross_source=dedup_cross_source,
            unique_player_decks=unique_player_decks,
        )
    if not standings:
        return None

    archetypes = [s["archetype"] for s in standings]
    all_weeks  = set()
    meta_data  = {}
    winpct_data = {}
    sample_data = {}  # {arch: {bucket_key: appearances}}

    for arch in archetypes:
        weekly = get_archetype_trend(
            arch, format_name=format_name, weeks=weeks,
            since=since, until=until,
            dedup_cross_source=dedup_cross_source,
            unique_player_decks=unique_player_decks,
            granularity=granularity,
        )
        meta_data[arch]   = {w["week_start"]: w["meta_share"] for w in weekly}
        winpct_data[arch] = {w["week_start"]: w.get("est_winpct") for w in weekly}
        sample_data[arch] = {w["week_start"]: w["appearances"] for w in weekly}
        all_weeks.update(meta_data[arch].keys())

    if not all_weeks:
        return None

    return {
        "archetypes":   archetypes,
        "meta_data":    meta_data,
        "winpct_data":  winpct_data,
        "sample_data":  sample_data,
        "all_weeks":    all_weeks,
        "format_name":  format_name,
        "granularity":  granularity,
    }


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


class _CompareLoader(QThread):
    """Load trend data for multiple archetypes to overlay on one chart."""
    done  = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, archetypes, format_name, weeks, since, until):
        super().__init__()
        self.archetypes  = archetypes
        self.format_name = format_name
        self.weeks       = weeks
        self.since       = since
        self.until       = until

    def run(self):
        try:
            from analysis.win_rates import get_archetype_trend
            all_weeks = set()
            arch_data = {}
            for arch in self.archetypes:
                weekly = get_archetype_trend(
                    arch, format_name=self.format_name, weeks=self.weeks,
                    since=self.since, until=self.until,
                )
                arch_data[arch] = {w["week_start"]: w["meta_share"] for w in weekly}
                all_weeks.update(arch_data[arch].keys())
            if not all_weeks:
                self.done.emit(None)
                return
            self.done.emit({
                "archetypes":  self.archetypes,
                "arch_data":   arch_data,
                "all_weeks":   all_weeks,
                "format_name": self.format_name,
            })
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
        # Toolbar inherits the global QToolBar stylesheet from main_window.py
        self._toolbar.setStyleSheet("")

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

    def _start_worker(self, worker):
        """Block signals on any running worker, then start the new one."""
        if self._worker is not None:
            self._worker.blockSignals(True)
        self._worker = worker
        worker.finished.connect(worker.deleteLater)
        worker.start()

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

    def draw_from_data(self, data, visible_archetypes=None, mode="meta_share",
                       show_events=True):
        """
        Draw the meta-share or win-pct chart from a pre-loaded data dict
        (returned by fetch_chart_data). No DB query — instant redraw.
        visible_archetypes: set/list of archetype names to include (None = all).
        mode: 'meta_share' or 'win_pct'
        show_events: overlay format event markers (set releases, B&R, rotations)
        """
        if data is None:
            self.show_message("No data to display.")
            return

        archetypes = data["archetypes"]
        if visible_archetypes is not None:
            archetypes = [a for a in archetypes if a in visible_archetypes]
        if not archetypes:
            self.show_message("No archetypes selected.")
            return

        sorted_weeks = sorted(data["all_weeks"])
        x_labels     = [w[5:] for w in sorted_weeks]

        if mode == "win_pct":
            series    = data["winpct_data"]
            y_label   = "Est Win %"
            title_sfx = "Win Rate Over Time"
        else:
            series    = data["meta_data"]
            y_label   = "Meta Share %"
            title_sfx = "Popularity Over Time"

        self._fig.clear()
        self._overlay.setVisible(False)
        ax = self._fig.add_subplot(111)
        _style_ax(ax, self._fig)

        sample = data.get("sample_data", {})

        for i, arch in enumerate(archetypes):
            color = _PALETTE[i % len(_PALETTE)]
            row = series.get(arch, {})
            arch_samples = sample.get(arch, {})

            if mode == "win_pct":
                # For win rate: suppress weeks with <3 appearances, apply 3-point rolling avg
                raw = []
                for w in sorted_weeks:
                    val = row.get(w)
                    n   = arch_samples.get(w, 0)
                    raw.append((val or 0) * 100 if val is not None and n >= 3 else None)
                # 3-point rolling average (skip Nones)
                y = []
                for j in range(len(raw)):
                    window = [raw[k] for k in range(max(0, j - 1), min(len(raw), j + 2))
                              if raw[k] is not None]
                    y.append(sum(window) / len(window) if window else None)
                # Plot only non-None segments
                xs = [x_labels[j] for j in range(len(y)) if y[j] is not None]
                ys = [y[j] for j in range(len(y)) if y[j] is not None]
                if ys:
                    ax.plot(xs, ys, marker="o", markersize=3, linewidth=2,
                            color=color, label=_shorten(arch), alpha=0.9)
            else:
                y = [(row.get(w) or 0) * 100 for w in sorted_weeks]
                ax.plot(x_labels, y, marker="o", markersize=4, linewidth=2,
                        color=color, label=_shorten(arch), alpha=0.9)

        fmt = data.get("format_name", "standard").upper()
        ax.set_title(f"{title_sfx} \u2014 {fmt}",
                     color="white", fontsize=13, pad=10)
        ax.set_xlabel("Week", color="white", fontsize=9)
        ax.set_ylabel(y_label, color="white", fontsize=9)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=12))
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_ha("right")
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
        )
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3,
                  labelcolor="white", facecolor=_BG, edgecolor=_GRID, ncol=2)
        if show_events:
            _draw_event_markers(ax, x_labels, sorted_weeks,
                                data.get("format_name", "standard"))
        self._fig.tight_layout()
        self._canvas.draw()

    def plot_meta_share(self, format_name="standard", top=10, weeks=12,
                        since=None, until=None, standings=None):
        """standings: pass pre-loaded list from get_meta_standings() to skip that DB call."""
        self.show_message("Loading meta data\u2026", "#65bcd5")
        w = _MetaShareLoader(format_name, top, weeks, since, until, standings)
        w.done.connect(self._draw_meta_share)
        w.error.connect(lambda e: self.show_message(f"Error: {e}", "#e6194b"))
        self._start_worker(w)

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
        _draw_event_markers(ax, x_labels, sorted_weeks,
                            data.get("format_name", "standard"))
        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    # Archetype trend — dual-axis bars + lines
    # ------------------------------------------------------------------

    def plot_trend(self, archetype, format_name="standard", weeks=12,
                   since=None, until=None):
        self.show_message(f"Loading trend for {_shorten(archetype)}\u2026", "#65bcd5")
        w = _TrendLoader(archetype, format_name, weeks, since, until)
        w.done.connect(lambda data: self._draw_trend(data, archetype, format_name))
        w.error.connect(lambda e: self.show_message(f"Error: {e}", "#e6194b"))
        self._start_worker(w)

    def _draw_trend(self, weekly, archetype, format_name):
        if not weekly:
            self.show_message(f"No trend data for \u2018{archetype}\u2019.")
            return

        weekly      = list(reversed(weekly))
        x_labels    = [w["week_start"][5:] for w in weekly]
        _trend_keys = [w["week_start"] for w in weekly]
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

        bar_color = "#65bcd5"
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
        _draw_event_markers(ax1, x_labels, _trend_keys, format_name)
        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    # Compare trends — overlay multiple archetypes
    # ------------------------------------------------------------------

    def plot_compare(self, archetypes, format_name="standard", weeks=12,
                     since=None, until=None):
        names = ", ".join(_shorten(a) for a in archetypes[:3])
        if len(archetypes) > 3:
            names += f" +{len(archetypes) - 3}"
        self.show_message(f"Loading {names}\u2026", "#65bcd5")
        w = _CompareLoader(archetypes, format_name, weeks, since, until)
        w.done.connect(self._draw_compare)
        w.error.connect(lambda e: self.show_message(f"Error: {e}", "#e6194b"))
        self._start_worker(w)

    def _draw_compare(self, data):
        if data is None:
            self.show_message("No trend data available for these archetypes.")
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
            y = [arch_data.get(arch, {}).get(w, 0) * 100 for w in sorted_weeks]
            ax.plot(x_labels, y, marker="o", markersize=4, linewidth=2,
                    color=color, label=_shorten(arch), alpha=0.9)

        fmt = data.get("format_name", "standard").upper()
        ax.set_title(f"Compare Trends \u2014 {fmt}",
                     color="white", fontsize=13, pad=10)
        ax.set_xlabel("Week", color="white", fontsize=9)
        ax.set_ylabel("Meta Share %", color="white", fontsize=9)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=12))
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_ha("right")
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{v:.0f}%")
        )
        ax.legend(loc="upper left", fontsize=7, framealpha=0.3,
                  labelcolor="white", facecolor=_BG, edgecolor=_GRID, ncol=2)
        _draw_event_markers(ax, x_labels, sorted_weeks,
                            data.get("format_name", "standard"))
        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    # Matchup heatmap — NxN grid
    # ------------------------------------------------------------------

    def plot_heatmap(self, format_name="standard", top=10, min_appearances=3,
                     since=None, until=None):
        self.show_message("Loading matchup data\u2026", "#65bcd5")
        w = _HeatmapLoader(format_name, top, min_appearances, since, until)
        w.done.connect(lambda data: self._draw_heatmap(data, format_name))
        w.error.connect(lambda e: self.show_message(f"Error: {e}", "#e6194b"))
        self._start_worker(w)

    def _draw_heatmap(self, matrix_data, format_name):
        if not matrix_data:
            self.show_message(
                "Not enough matchup data.\n"
                "Try lowering min appearances or expanding the date range."
            )
            return

        archetypes = matrix_data.get("archetypes", [])
        raw_matrix = matrix_data.get("matrix", {})
        n = len(archetypes)
        if n < 2:
            self.show_message("Need at least 2 archetypes with matchup data.")
            return

        grid = np.full((n, n), float("nan"))
        for i, arch_a in enumerate(archetypes):
            for j, arch_b in enumerate(archetypes):
                val = raw_matrix.get(arch_a, {}).get(arch_b)
                if val is not None:
                    wr = val.get("win_rate")
                    if wr is not None:
                        grid[i][j] = wr * 100

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
