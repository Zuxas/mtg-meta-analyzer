"""
Tab — Matchup Data Heatmap

Displays win-rate data as a colour-coded grid. Three data sources merged:

  1. **Real Match Data (DB)** — 221k+ actual match results from MTGMelee.
     Uses get_real_matchup_winrates() with min_matches=20.  Highest priority.
  2. **MTGDecks Live** — scraped from MTGDecks.net /winrates.  Fills gaps.
  3. **Paste Data** — manual CSV / JSON paste (Frank Karsten, etc.)

Combined view:  real data (★) takes priority;  scraped data fills gaps.
Only archetypes in get_meta_standings(top=30) are shown; sorted by meta share.

Color scale:
  ≥ 60 %   deep green
  55–59 %  light green
  45–54 %  grey  (roughly even)
  40–44 %  light red
  ≤ 39 %   deep red
  diagonal — dark neutral (mirror match / no data)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QPlainTextEdit, QDialogButtonBox,
    QFrame, QSizePolicy, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _wr_bg(winrate: float) -> QColor:
    """Background QColor for a given win-rate (0.0–1.0). Subtle tint only."""
    pct = winrate * 100
    if pct >= 60:
        return QColor(12, 50, 22)
    if pct >= 55:
        return QColor(14, 40, 20)
    if pct >= 45:
        return QColor(30, 30, 38)
    if pct >= 40:
        return QColor(55, 18, 16)
    return QColor(65, 14, 14)


def _wr_fg(winrate: float) -> QColor:
    """Foreground (text) QColor for a given win-rate — matches legend colors."""
    pct = winrate * 100
    if pct >= 60:
        return QColor(50, 220, 90)       # bright green
    if pct >= 55:
        return QColor(70, 190, 90)       # green
    if pct >= 45:
        return QColor(140, 145, 160)     # neutral grey
    if pct >= 40:
        return QColor(230, 90, 70)       # orange-red
    return QColor(240, 60, 50)           # bright red


def _wr_label(winrate: float) -> str:
    pct = winrate * 100
    if pct >= 55:
        return "Favored"
    if pct >= 45:
        return "Even"
    return "Unfavored"


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _FetchWorker(QThread):
    done  = pyqtSignal(str, dict)  # (format_name, matrix)
    error = pyqtSignal(str)

    def __init__(self, format_name: str):
        super().__init__()
        self.format_name = format_name

    def run(self):
        try:
            from scrapers.matchup_scraper import scrape_winrates
            from db.matchup_queries import save_matchup_data
            data = scrape_winrates(self.format_name)
            if data:
                save_matchup_data(self.format_name, data)
            self.done.emit(self.format_name, data or {})
        except Exception as exc:
            self.error.emit(str(exc))


class _LoadWorker(QThread):
    done  = pyqtSignal(str, dict)  # (format_name, matrix)
    error = pyqtSignal(str)

    def __init__(self, format_name: str):
        super().__init__()
        self.format_name = format_name

    def run(self):
        try:
            from db.matchup_queries import get_matchup_matrix
            self.done.emit(self.format_name,
                           get_matchup_matrix(self.format_name))
        except Exception as exc:
            self.error.emit(str(exc))


class _CombinedWorker(QThread):
    """Load real match data + cached scraped data and merge them."""
    done  = pyqtSignal(str, dict, dict)  # (format_name, combined_matrix, source_map)
    error = pyqtSignal(str)

    def __init__(self, format_name: str, since=None):
        super().__init__()
        self.format_name = format_name
        self.since = since

    def run(self):
        try:
            from analysis.archetypes import normalize as norm_arch

            # 1) Real match data from matches table
            # Lower threshold for formats with less data
            from analysis.win_rates import get_real_matchup_winrates
            _MIN_MATCHES = {"pioneer": 10, "modern": 5}
            min_m = _MIN_MATCHES.get(self.format_name, 20)
            real_raw = get_real_matchup_winrates(
                self.format_name, since=self.since, min_matches=min_m)

            # Convert canonical (a<b) to full bidirectional matrix
            # Normalize archetype names so they match meta standings
            real_matrix = {}
            for a, opponents in real_raw.items():
                na = norm_arch(a)
                for b, stats in opponents.items():
                    nb = norm_arch(b)
                    wr_a = stats["win_rate"]
                    n    = stats["total"]
                    real_matrix.setdefault(na, {})[nb] = {
                        "winrate": wr_a, "matches": n,
                    }
                    real_matrix.setdefault(nb, {})[na] = {
                        "winrate": round(1.0 - wr_a, 4), "matches": n,
                    }

            # 2) Cached scraped data for this specific format
            from db.matchup_queries import get_matchup_matrix
            scraped_raw = get_matchup_matrix(self.format_name)
            # Normalize scraped keys too
            scraped = {}
            for a, opps in scraped_raw.items():
                na = norm_arch(a)
                scraped[na] = {}
                for b, v in opps.items():
                    scraped[na][norm_arch(b)] = v

            # 3) Merge: real takes priority, scraped fills gaps
            combined = {}
            source   = {}   # {(a,b): "real"|"scraped"}
            all_archs = set(real_matrix) | set(scraped)

            for a in all_archs:
                combined[a] = {}
                real_opps    = real_matrix.get(a, {})
                scraped_opps = scraped.get(a, {})
                for b in all_archs:
                    if a == b:
                        continue
                    if b in real_opps:
                        combined[a][b] = real_opps[b]
                        source[(a, b)] = "real"
                    elif b in scraped_opps:
                        combined[a][b] = scraped_opps[b]
                        source[(a, b)] = "scraped"

            self.done.emit(self.format_name, combined, source)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Paste dialog
# ---------------------------------------------------------------------------

class _PasteDialog(QDialog):
    """
    Let the user paste a CSV or JSON matchup table and parse it into a matrix.

    Accepted CSV format (header row + data rows):
        ,Izzet Prowess,Dimir Midrange,...
        Izzet Prowess,50,48,...
        Dimir Midrange,52,50,...

    Accepted JSON format:
        {"Izzet Prowess": {"Dimir Midrange": 48, ...}, ...}

    Win-rate values may be 0–1 (fractions) or 0–100 (percentages).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste Matchup Data")
        self.setMinimumSize(560, 400)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Paste CSV or JSON matchup data below.\n"
            "CSV: first row = column headers (opponent names), "
            "first column = row labels (your deck). Values = win % (0-100 or 0-1).\n"
            "JSON: {\"Deck A\": {\"Deck B\": 54, ...}, ...}"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        layout.addWidget(hint)

        self._edit = QPlainTextEdit()
        self._edit.setFont(QFont("Consolas", 9))
        self._edit.setPlaceholderText(
            ",Izzet Prowess,Dimir Midrange\n"
            "Izzet Prowess,50,52\n"
            "Dimir Midrange,48,50"
        )
        layout.addWidget(self._edit, 1)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet(f"color: {theme.ERR};")
        self._error_lbl.setWordWrap(True)
        layout.addWidget(self._error_lbl)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.result_matrix: dict = {}

    def _validate(self):
        text = self._edit.toPlainText().strip()
        if not text:
            self._error_lbl.setText("Nothing pasted.")
            return
        try:
            matrix = _parse_pasted(text)
        except Exception as exc:
            self._error_lbl.setText(f"Parse error: {exc}")
            return
        if not matrix:
            self._error_lbl.setText(
                "No matchup data found. Check the format is correct "
                "and the pasted data follows CSV or JSON format."
            )
            return
        self.result_matrix = matrix
        self.accept()


def _parse_pasted(text: str) -> dict:
    """Try JSON first, fall back to CSV."""
    import json, csv, io

    text = text.strip()

    # JSON
    if text.startswith("{"):
        raw = json.loads(text)
        matrix = {}
        for arch_a, opponents in raw.items():
            matrix[arch_a] = {}
            for arch_b, wr in opponents.items():
                val = float(wr)
                matrix[arch_a][arch_b] = {
                    "winrate": val / 100.0 if val > 1 else val,
                    "matches": 0,
                }
        return matrix

    # CSV
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError("Need at least a header row and one data row.")
    opponents = [c.strip() for c in rows[0][1:]]
    matrix = {}
    for row in rows[1:]:
        if not row:
            continue
        arch = row[0].strip()
        matrix[arch] = {}
        for i, val in enumerate(row[1:]):
            if i >= len(opponents) or not val.strip():
                continue
            wr = float(val.strip().rstrip("%"))
            matrix[arch][opponents[i]] = {
                "winrate": wr / 100.0 if wr > 1 else wr,
                "matches": 0,
            }
    return matrix


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class HeatmapTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._load_gen: int = 0          # monotonic counter — stale callbacks ignored
        self._current_matrix: dict = {}
        self._source_map: dict = {}      # {(a,b): "real"|"scraped"}
        self._loaded_format: str = ""    # format that _current_matrix belongs to
        self._load_source: str = ""      # "combined"|"fetch"|"cache"|"paste"
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setStyleSheet(
            f"background: {theme.PANEL}; border-radius: 4px; padding: 2px;"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 4, 8, 4)
        tl.setSpacing(8)

        tl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy", "pauper"])
        self._fmt.setFixedWidth(100)
        self._fmt.currentIndexChanged.connect(lambda _: self._load_combined())
        tl.addWidget(self._fmt)

        tl.addWidget(QLabel("Timeframe:"))
        self._tf = QComboBox()
        self._TIMEFRAME_OPTIONS = theme.TIMEFRAME_OPTIONS
        for label, _ in self._TIMEFRAME_OPTIONS:
            self._tf.addItem(label)
        # Default to "8 weeks"
        for i, (label, _) in enumerate(self._TIMEFRAME_OPTIONS):
            if label == "8 weeks":
                self._tf.setCurrentIndex(i)
                break
        self._tf.setFixedWidth(100)
        self._tf.currentIndexChanged.connect(lambda _: self._load_combined())
        tl.addWidget(self._tf)

        self._combined_btn = QPushButton("Real Match Data (DB)")
        self._combined_btn.setStyleSheet(theme.btn_primary())
        self._combined_btn.setToolTip(
            "Build heatmap from 221k+ real match results.\n"
            "Scraped MTGDecks data fills gaps where real data is thin."
        )
        self._combined_btn.clicked.connect(self._load_combined)
        tl.addWidget(self._combined_btn)

        self._fetch_btn = QPushButton("MTGDecks Live")
        self._fetch_btn.setStyleSheet(theme.btn_secondary())
        self._fetch_btn.setToolTip("Scrape current win-rates from MTGDecks.net and save to DB")
        self._fetch_btn.clicked.connect(self._fetch_live)
        tl.addWidget(self._fetch_btn)

        self._cache_btn = QPushButton("Use Cached")
        self._cache_btn.setStyleSheet(theme.btn_secondary())
        self._cache_btn.setToolTip("Load the last saved MTGDecks snapshot from the local DB")
        self._cache_btn.clicked.connect(self._load_cached)
        tl.addWidget(self._cache_btn)

        self._gauntlet_btn = QPushButton("Gauntlet")
        self._gauntlet_btn.setStyleSheet(theme.btn_secondary())
        self._gauntlet_btn.setToolTip(
            "Build a live gauntlet from the top 12 meta decks\n"
            "Uses real match data to populate the matchup grid"
        )
        self._gauntlet_btn.clicked.connect(self._load_gauntlet)
        tl.addWidget(self._gauntlet_btn)

        self._paste_btn = QPushButton("Paste Data")
        self._paste_btn.setStyleSheet(theme.btn_secondary())
        self._paste_btn.setToolTip(
            "Manually paste CSV or JSON matchup data "
            "(e.g. from Frank Karsten or I Love Azorius tweets)"
        )
        self._paste_btn.clicked.connect(self._open_paste_dialog)
        tl.addWidget(self._paste_btn)

        self._eq_btn = QPushButton("Equilibrium")
        self._eq_btn.setStyleSheet(theme.btn_secondary())
        self._eq_btn.setToolTip(
            "Nash Equilibrium + RPS Cycles\n"
            "Shows optimal meta shares vs actual, and detects\n"
            "Rock-Paper-Scissors cycles in the matchup data."
        )
        self._eq_btn.clicked.connect(self._show_equilibrium)
        tl.addWidget(self._eq_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setToolTip("Export current matchup data as JSON for team sharing")
        self._export_btn.clicked.connect(self._export_gauntlet)
        tl.addWidget(self._export_btn)

        tl.addStretch()

        self._updated_lbl = QLabel("")
        self._updated_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        tl.addWidget(self._updated_lbl)

        outer.addWidget(toolbar)

        from gui.widgets.summary_bar import SummaryBar
        self._summary_bar = SummaryBar()
        outer.addWidget(self._summary_bar)

        # ── Status label ──────────────────────────────────────────────
        self._status = QLabel(
            "Click \u2018Real Match Data (DB)\u2019 for heatmap from actual match results, "
            "or \u2018MTGDecks Live\u2019 to scrape."
        )
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; padding: 8px;"
        )
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # Indeterminate progress bar (visible during loading)
        from PyQt6.QtWidgets import QProgressBar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        # ── Grid container (QTableWidget has its own scrolling with sticky headers)
        self._grid_container = QWidget()
        self._grid_container.setVisible(False)
        self._grid_layout = QVBoxLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(2)
        outer.addWidget(self._grid_container, 1)

        # ── Legend ────────────────────────────────────────────────────
        legend = self._build_legend()
        outer.addWidget(legend)

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def _build_legend(self) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(12)
        hl.addWidget(QLabel("Legend:"))
        for label, color in [
            ("\u226560% (Strong Fav)", QColor(50, 220, 90)),
            ("55\u201359% (Favored)",  QColor(70, 190, 90)),
            ("45\u201354% (Even)",     QColor(140, 145, 160)),
            ("40\u201344% (Unfav)",    QColor(230, 90, 70)),
            ("\u226439% (Bad)",        QColor(240, 60, 50)),
        ]:
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background: rgb({color.red()},{color.green()},{color.blue()});"
                " border-radius: 2px;"
            )
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
            hl.addWidget(swatch)
            hl.addWidget(lbl)

        # Source legend
        star_lbl = QLabel("\u2605 = real match data   (no star) = scraped")
        star_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 10px;")
        hl.addWidget(star_lbl)

        hl.addStretch()
        return row

    # ------------------------------------------------------------------
    # Worker lifecycle — safe start / cancel
    # ------------------------------------------------------------------

    def _since_dt(self):
        """Return a datetime for the selected timeframe, or None for All Time."""
        from datetime import datetime, timedelta
        weeks = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][1]
        return (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None

    def _set_busy(self, busy: bool):
        self._progress.setVisible(busy)
        self._combined_btn.setEnabled(not busy)
        self._fetch_btn.setEnabled(not busy)
        self._cache_btn.setEnabled(not busy)
        self._gauntlet_btn.setEnabled(not busy)
        self._paste_btn.setEnabled(not busy)
        self._eq_btn.setEnabled(not busy)
        self._export_btn.setEnabled(not busy)
        self._fmt.setEnabled(not busy)
        self._tf.setEnabled(not busy)

    def cleanup(self):
        """Stop running worker. Called by MainWindow on app exit."""
        self._cancel_worker()

    def _cancel_worker(self):
        """Block signals on any running worker so its callbacks are ignored."""
        from gui.worker_utils import cancel_worker
        cancel_worker(self._worker)
        self._worker = None

    def _prepare_load(self, source: str):
        """Common pre-load steps: cancel old worker, reset state, show loading UI."""
        self._cancel_worker()
        self._load_gen += 1          # new generation — stale callbacks will be ignored
        self._load_source = source
        self._current_matrix = {}
        self._source_map = {}
        self._status.setVisible(True)
        self._grid_container.setVisible(False)
        self._updated_lbl.setText("")
        self._set_busy(True)

    def _wire_worker(self, worker):
        """Store worker reference and wire finished → deleteLater safely."""
        self._worker = worker
        gen = self._load_gen  # snapshot — callbacks check this to detect staleness
        worker.error.connect(lambda msg: self._on_error(msg, gen))
        worker.finished.connect(lambda: self._on_worker_finished(worker, gen))
        worker.start()

    def _on_worker_finished(self, w, gen: int):
        """Clean up after a worker finishes. Re-enable UI only if still current."""
        if self._worker is w:
            self._worker = None
            # Only re-enable buttons if this is still the active generation
            if gen == self._load_gen:
                self._set_busy(False)
        try:
            w.deleteLater()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Load actions
    # ------------------------------------------------------------------

    def _load_combined(self):
        """Default action: real match data + scraped fills gaps."""
        fmt = self._fmt.currentText()
        since = self._since_dt()
        self._prepare_load("combined")
        gen = self._load_gen
        tf_label = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]
        self._status.setText(f"Loading {fmt} match data ({tf_label})\u2026")

        worker = _CombinedWorker(fmt, since=since)
        worker.done.connect(
            lambda f, m, s: self._on_combined_data(f, m, s, gen))
        self._wire_worker(worker)

    def _on_combined_data(self, fmt: str, matrix: dict, source_map: dict,
                          gen: int):
        if gen != self._load_gen:
            return  # stale result from a cancelled load
        self._source_map = source_map
        self._on_data(fmt, matrix, gen)

    def _fetch_live(self):
        fmt = self._fmt.currentText()
        self._prepare_load("fetch")
        gen = self._load_gen
        self._status.setText(f"Fetching {fmt} win-rates from MTGDecks\u2026")

        worker = _FetchWorker(fmt)
        worker.done.connect(lambda f, m: self._on_data(f, m, gen))
        self._wire_worker(worker)

    def _load_cached(self):
        fmt = self._fmt.currentText()
        self._prepare_load("cache")
        gen = self._load_gen
        self._status.setText(f"Loading cached {fmt} data\u2026")

        worker = _LoadWorker(fmt)
        worker.done.connect(lambda f, m: self._on_data(f, m, gen))
        self._wire_worker(worker)

    def _load_gauntlet(self):
        """Build a live gauntlet: top 12 meta decks with real matchup data."""
        fmt = self._fmt.currentText()
        since = self._since_dt()
        self._prepare_load("gauntlet")
        gen = self._load_gen
        self._status.setText(f"Building {fmt} gauntlet from top 12 meta decks\u2026")

        def _do():
            from analysis.win_rates import get_meta_standings, get_real_matchup_winrates
            from analysis.archetypes import normalize as norm_arch

            # Get top 12 by appearances
            standings = get_meta_standings(fmt, top=12, since=since)
            if not standings:
                return None, {}

            top_names = [s["archetype"] for s in standings]

            # Get real matchup data
            _MIN = {"pioneer": 10, "modern": 5}.get(fmt, 20)
            real_raw = get_real_matchup_winrates(fmt, since=since, min_matches=_MIN)

            # Build bidirectional matrix for just these 12 decks
            matrix = {}
            source = {}
            for a in top_names:
                matrix[a] = {}
                na = norm_arch(a).lower()
                for b in top_names:
                    if a == b:
                        continue
                    nb = norm_arch(b).lower()
                    # Search real data (canonical ordering: a<b)
                    found = False
                    for ra, opps in real_raw.items():
                        if norm_arch(ra).lower() == na:
                            for rb, stats in opps.items():
                                if norm_arch(rb).lower() == nb:
                                    matrix[a][b] = {
                                        "winrate": stats["win_rate"],
                                        "matches": stats["total"],
                                    }
                                    source[(a, b)] = "real"
                                    found = True
                                    break
                        if found:
                            break
                    if not found:
                        # Try reverse lookup
                        for ra, opps in real_raw.items():
                            if norm_arch(ra).lower() == nb:
                                for rb, stats in opps.items():
                                    if norm_arch(rb).lower() == na:
                                        matrix[a][b] = {
                                            "winrate": round(1.0 - stats["win_rate"], 4),
                                            "matches": stats["total"],
                                        }
                                        source[(a, b)] = "real"
                                        found = True
                                        break
                            if found:
                                break

            return matrix, source

        def _done(result):
            if result is None:
                self._on_error("No meta data available for gauntlet", gen)
                return
            matrix, src = result
            self._source_map = src
            filled = sum(1 for a in matrix for b in matrix[a] if matrix[a].get(b))
            total_possible = len(matrix) * (len(matrix) - 1)
            self._updated_lbl.setText(
                f"{fmt.upper()}  \u2022  Gauntlet: top {len(matrix)} decks, "
                f"{filled}/{total_possible} matchup cells filled from real data")
            self._on_data(fmt, matrix, gen)

        from gui.worker_threads import DataLoadWorker
        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: self._on_error(e, gen))
        self._wire_worker(w)

    def _open_paste_dialog(self):
        dlg = _PasteDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_matrix:
            fmt = self._fmt.currentText()
            self._load_source = "paste"
            self._source_map = {}
            self._on_data(fmt, dlg.result_matrix, self._load_gen)

    # ------------------------------------------------------------------
    # Data callbacks
    # ------------------------------------------------------------------

    def _on_error(self, msg: str, gen: int = -1):
        if gen != -1 and gen != self._load_gen:
            return  # stale error from a cancelled load
        self._grid_container.setVisible(False)
        self._status.setVisible(True)
        self._status.setText(theme.friendly_error(msg))

    def _on_data(self, fmt: str, matrix: dict, gen: int = -1):
        if gen != -1 and gen != self._load_gen:
            return  # stale result from a cancelled load
        self._loaded_format = fmt

        if not matrix:
            self._grid_container.setVisible(False)
            self._status.setVisible(True)
            if self._load_source == "cache":
                self._status.setText(
                    f"No cached data for {fmt} \u2014 click \u2018Real Match Data (DB)\u2019 "
                    f"or \u2018MTGDecks Live\u2019 first."
                )
            elif self._load_source == "combined":
                self._status.setText(
                    f"No match data found for {fmt}. "
                    f"Run the MTGMelee scraper or fetch from MTGDecks."
                )
            else:
                self._status.setText(
                    f"No data found for {fmt}. "
                    f"Try \u2018Real Match Data (DB)\u2019 or \u2018MTGDecks Live\u2019."
                )
            return

        self._current_matrix = matrix
        # Use the format the data was loaded for, NOT the current combo value
        filtered, ordered = self._filter_to_meta(matrix, fmt)
        self._draw_grid(filtered, ordered, total_archetypes=len(matrix), fmt=fmt)

        # Summary bar
        n_archetypes = len(ordered)
        total_cells = sum(len(v) for v in filtered.values())
        stats = [f"{n_archetypes} archetypes", f"{total_cells} matchup cells"]
        real_ct = sum(1 for v in getattr(self, '_source_map', {}).values() if v == "real")
        if real_ct:
            stats.append(f"{real_ct} from real matches")
        self._summary_bar.update(fmt.upper() + " MATCHUPS", stats)

        # Update last-updated label
        if self._load_source == "combined":
            real_ct = sum(1 for v in self._source_map.values() if v == "real")
            scr_ct  = sum(1 for v in self._source_map.values() if v == "scraped")
            parts = [f"{fmt.upper()}  \u2022  \u2605 {real_ct} real cells"]
            if scr_ct:
                parts.append(f"{scr_ct} scraped cells")
            else:
                parts.append("no cached scrapes \u2014 click MTGDecks Live to fill gaps")
            self._updated_lbl.setText("  |  ".join(parts))
        else:
            try:
                from db.matchup_queries import get_last_updated
                ts = get_last_updated(fmt)
                self._updated_lbl.setText(
                    f"{fmt.upper()}  \u2022  "
                    f"Last updated: {ts[:10] if ts else 'just now'}"
                )
            except Exception:
                self._updated_lbl.setText(f"{fmt.upper()}")

    # ------------------------------------------------------------------
    # Meta filtering
    # ------------------------------------------------------------------

    def _filter_to_meta(self, matrix: dict, format_name: str, top: int = 30):
        """
        Return (filtered_matrix, ordered_archetypes) keeping only the top-N
        archetypes, sorted by relevance.

        Strategy:
          1. Try matching meta standings names to matrix keys (normalized).
          2. If overlap is good (≥40% of meta names found), use meta order.
          3. Otherwise fall back to sorting by data density (most matchup
             cells first) — this handles real match data where melee.gg
             names don't match the local archetype naming.
        """
        # -- Sort by data density (always available) --
        by_density = sorted(matrix.keys(),
                            key=lambda a: -len(matrix.get(a, {})))[:top]

        try:
            from analysis.win_rates import get_meta_standings
            standings = get_meta_standings(format_name, top=top, min_appearances=2)
        except Exception:
            standings = []

        if not standings:
            return self._build_filtered(matrix, by_density)

        # -- Try name matching --
        from analysis.archetypes import normalize as norm_arch

        # Normalize matrix keys: norm_lower → original_key
        norm_to_orig = {}
        for k in matrix:
            nk = norm_arch(k).lower()
            norm_to_orig.setdefault(nk, k)

        ordered = []
        used    = set()

        for s in standings:
            meta_low = norm_arch(s["archetype"]).lower()

            # Exact normalized match
            if meta_low in norm_to_orig and meta_low not in used:
                used.add(meta_low)
                ordered.append(norm_to_orig[meta_low])
                continue

            # Substring match
            for nk, orig in norm_to_orig.items():
                if nk not in used and (meta_low in nk or nk in meta_low):
                    used.add(nk)
                    ordered.append(orig)
                    break

        overlap_pct = len(ordered) / len(standings) if standings else 0
        # Debug removed — was: [HEATMAP] _filter_to_meta overlap info

        if overlap_pct >= 0.4:
            # Good overlap — use meta-share ordering
            return self._build_filtered(matrix, ordered)
        else:
            # Poor overlap (real match data vs different naming) — use data density
            pass  # poor name overlap — using data-density sort
            return self._build_filtered(matrix, by_density)

    @staticmethod
    def _build_filtered(matrix: dict, ordered: list):
        """Build a filtered matrix containing only the ordered archetypes."""
        ordered_set = set(ordered)
        filtered = {
            a: {b: v for b, v in matrix.get(a, {}).items() if b in ordered_set}
            for a in ordered if a in matrix
        }
        return filtered, [a for a in ordered if a in matrix]

    # ------------------------------------------------------------------
    # Grid drawing
    # ------------------------------------------------------------------

    def _draw_grid(self, matrix: dict, ordered_archetypes: list = None,
                   total_archetypes: int = None, fmt: str = ""):
        archetypes = ordered_archetypes if ordered_archetypes is not None \
                     else sorted(matrix.keys())
        n = len(archetypes)
        source_map = self._source_map
        ncols = n + 1  # +1 for Overall column at index 0

        # Load team notes for this format
        try:
            from db.matchup_queries import get_matchup_notes
            notes = get_matchup_notes(fmt) if fmt else {}
        except Exception:
            notes = {}
        self._grid_archetypes = archetypes
        self._grid_format = fmt
        self._grid_notes = notes

        tbl = QTableWidget(n, ncols)
        # CRITICAL: The global stylesheet sets QTableWidget::item { padding }
        # which prevents setBackground() from working. Override with a
        # stylesheet that does NOT touch background at all — only padding/border.
        # The "color: white" on ::item is needed so Qt enters "styled" mode
        # but still respects BackgroundRole from setBackground().
        tbl.setStyleSheet("")  # clear inherited styles
        tbl.setAlternatingRowColors(False)
        # Apply via palette instead of stylesheet for cell backgrounds
        from PyQt6.QtGui import QPalette
        pal = tbl.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(theme.BG))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.BG))
        tbl.setPalette(pal)
        tbl.setHorizontalHeaderLabels(["Overall"] + archetypes)
        tbl.setVerticalHeaderLabels(archetypes)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        hh = tbl.horizontalHeader()
        vh = tbl.verticalHeader()
        hh.setDefaultSectionSize(72)
        vh.setDefaultSectionSize(26)
        vh.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_font = QFont()
        header_font.setPointSize(8)
        tbl.horizontalHeader().setFont(header_font)
        tbl.verticalHeader().setFont(header_font)

        # Populate Overall column (index 0) — weighted avg WR across all matchups
        for ri, arch_a in enumerate(archetypes):
            opps = matrix.get(arch_a, {})
            total_w = 0.0
            total_n = 0
            for arch_b, mu in opps.items():
                m = mu.get("matches", 0) or 1
                total_w += mu["winrate"] * m
                total_n += m
            if total_n > 0:
                overall_wr = total_w / total_n
                pct = round(overall_wr * 100)
                item = QTableWidgetItem(f"{pct}%")
                item.setBackground(_wr_bg(overall_wr))
                item.setForeground(_wr_fg(overall_wr))
                bold = QFont(); bold.setBold(True); item.setFont(bold)
                item.setToolTip(
                    f"{arch_a}\nOverall WR: {pct}% (weighted by sample size)\n"
                    f"Total matches: n={total_n:,}"
                )
            else:
                item = QTableWidgetItem("\u2014")
                item.setBackground(QColor(40, 40, 50))
                item.setForeground(QColor(theme.TEXT_DIM))
                total_n = 0
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 0, item)

        # Populate matchup cells (columns 1..n)
        for ri, arch_a in enumerate(archetypes):
            for ci, arch_b in enumerate(archetypes):
                col = ci + 1  # offset by 1 for Overall column
                if arch_a == arch_b:
                    item = QTableWidgetItem("\u2014")
                    item.setBackground(QColor(40, 40, 50))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor(theme.TEXT_DIM))
                else:
                    matchup = matrix.get(arch_a, {}).get(arch_b)
                    if matchup is None:
                        item = QTableWidgetItem("")
                        item.setBackground(QColor(35, 35, 45))
                    else:
                        wr = matchup["winrate"]
                        matches = matchup.get("matches", 0)
                        pct = round(wr * 100)
                        is_real = source_map.get((arch_a, arch_b)) == "real"
                        star = "\u2605" if is_real else ""
                        item = QTableWidgetItem(f"{pct}%{star}")
                        item.setBackground(_wr_bg(wr))
                        item.setForeground(_wr_fg(wr))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        verdict = _wr_label(wr)
                        src_tag = "Real match data" if is_real else "Scraped (MTGDecks)"
                        tooltip = (
                            f"{arch_a}  vs  {arch_b}\n"
                            f"Win rate: {pct}%  ({verdict})\n"
                            f"Source: {src_tag}"
                        )
                        if matches:
                            tooltip += f"\nMatches logged: {matches:,}"
                        cell_note = notes.get((arch_a, arch_b), "")
                        if cell_note:
                            tooltip += f"\n\nTeam Note:\n{cell_note}"
                        tooltip += "\n\nRight-click to add/edit note"
                        item.setToolTip(tooltip)
                        if pct < 43 or pct > 57:
                            f = QFont()
                            f.setBold(True)
                            item.setFont(f)

                tbl.setItem(ri, col, item)

        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(0, 64)
        for ci in range(1, ncols):
            hh.setSectionResizeMode(ci, QHeaderView.ResizeMode.Fixed)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # Clear existing grid content
        while self._grid_layout.count():
            child = self._grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        vl = self._grid_layout

        # Info label
        if total_archetypes and total_archetypes > n:
            filter_note = (f"showing top {n} by meta share "
                           f"(filtered from {total_archetypes})  \u00b7  ")
        else:
            filter_note = ""
        info = QLabel(
            f"{n} archetypes  \u00b7  {filter_note}"
            f"Row = your deck  \u00b7  Column = opponent  \u00b7  Cell = your win %"
        )
        info.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px; padding: 4px;")
        vl.addWidget(info)

        # Low-coverage warning for sparse formats
        if n < 8 and fmt and fmt.lower() != "standard":
            warn = QLabel(
                f"Limited data \u2014 only {n} archetypes with 20+ matches for "
                f"{fmt.capitalize()}. Run more {fmt.capitalize()} scrapes "
                f"(MTGMelee or MTGDecks) to improve coverage."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color: {theme.WARN}; font-size: 10px; padding: 4px; "
                f"background: #1a1510; border-radius: 3px;"
            )
            vl.addWidget(warn)

        # Right-click context menu for team notes
        tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tbl.customContextMenuRequested.connect(
            lambda pos, t=tbl: self._show_note_menu(t, pos))

        vl.addWidget(tbl, 1)

        self._status.setVisible(False)
        self._grid_container.setVisible(True)

    # ------------------------------------------------------------------
    # Team notes (right-click on matchup cell)
    # ------------------------------------------------------------------

    def _show_note_menu(self, tbl: QTableWidget, pos):
        item = tbl.itemAt(pos)
        if not item:
            return
        row = tbl.row(item)
        col = tbl.column(item)
        archetypes = getattr(self, "_grid_archetypes", [])
        fmt = getattr(self, "_grid_format", "")
        if not archetypes or col < 1:
            return  # skip Overall column
        arch_a = archetypes[row] if row < len(archetypes) else None
        arch_b = archetypes[col - 1] if (col - 1) < len(archetypes) else None
        if not arch_a or not arch_b or arch_a == arch_b:
            return

        notes = getattr(self, "_grid_notes", {})
        existing = notes.get((arch_a, arch_b), "")

        menu = QMenu(self)
        edit_action = menu.addAction("Add/Edit Note\u2026" if not existing else "Edit Note\u2026")
        clear_action = None
        if existing:
            menu.addSeparator()
            clear_action = menu.addAction("Clear Note")

        action = menu.exec(tbl.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == clear_action:
            from db.matchup_queries import save_matchup_note
            save_matchup_note(fmt, arch_a, arch_b, "")
            self._grid_notes.pop((arch_a, arch_b), None)
            # Update tooltip — strip note section
            tip = item.toolTip()
            if "\n\nTeam Note:" in tip:
                tip = tip.split("\n\nTeam Note:")[0] + "\n\nRight-click to add/edit note"
            item.setToolTip(tip)
            return

        if action == edit_action:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Note: {arch_a} vs {arch_b}")
            dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
            layout = QVBoxLayout(dlg)

            text_edit = QPlainTextEdit()
            text_edit.setPlainText(existing)
            text_edit.setMinimumSize(400, 180)
            text_edit.setStyleSheet(
                f"background: {theme.PANEL}; color: {theme.TEXT}; "
                f"border: 1px solid {theme.ACCENT}; padding: 6px;"
            )
            layout.addWidget(text_edit)

            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)

            if dlg.exec() == QDialog.DialogCode.Accepted:
                note = text_edit.toPlainText().strip()
                from db.matchup_queries import save_matchup_note
                save_matchup_note(fmt, arch_a, arch_b, note)
                if note:
                    self._grid_notes[(arch_a, arch_b)] = note
                else:
                    self._grid_notes.pop((arch_a, arch_b), None)
                # Update tooltip
                tip = item.toolTip()
                if "\n\nTeam Note:" in tip:
                    tip = tip.split("\n\nTeam Note:")[0]
                else:
                    tip = tip.replace("\n\nRight-click to add/edit note", "")
                if note:
                    tip += f"\n\nTeam Note:\n{note}"
                tip = tip.rstrip() + "\n\nRight-click to add/edit note"
                item.setToolTip(tip)

    # ------------------------------------------------------------------
    # Meta Equilibrium dialog
    # ------------------------------------------------------------------

    def _show_equilibrium(self):
        """Open a dialog showing Nash equilibrium and RPS cycles."""
        fmt = self._fmt.currentText()
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Meta Equilibrium \u2014 {fmt.capitalize()}")
        dlg.setMinimumSize(750, 550)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        layout = QVBoxLayout(dlg)

        status = QLabel("Computing equilibrium\u2026")
        status.setStyleSheet(f"color: {theme.TEXT_DIM};")
        layout.addWidget(status)

        # Run analysis in this thread (it's fast — cached data, numpy math)
        try:
            from analysis.equilibrium import analyze_metagame
            result = analyze_metagame(fmt, since=self._since_dt(), top=15, method="nash")
        except Exception as e:
            status.setText(theme.friendly_error(e))
            dlg.exec()
            return

        eq = result.get("equilibrium")
        cycles = result.get("cycles", [])

        if not eq or not eq.archetypes:
            status.setText(
                f"Not enough matchup data for {fmt}. "
                f"Load the heatmap first with \u2018Real Match Data (DB)\u2019."
            )
            dlg.exec()
            return

        status.setText(
            f"Nash equilibrium for {fmt.upper()} \u2014 "
            f"{len(eq.archetypes)} archetypes analyzed"
            + ("" if eq.converged else " (did not fully converge)")
        )

        # ── Equilibrium table ────────────────────────────────────────
        layout.addWidget(QLabel("Optimal vs Actual Meta Shares:"))

        tbl = QTableWidget()
        tbl.setColumnCount(5)
        tbl.setHorizontalHeaderLabels(
            ["Archetype", "Current", "Optimal", "Delta", "Status"])
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Sort by absolute delta (biggest mismatch first)
        sorted_archs = sorted(
            eq.archetypes,
            key=lambda a: -abs(eq.deltas[a])
        )
        tbl.setRowCount(len(sorted_archs))

        for ri, a in enumerate(sorted_archs):
            cur = eq.current_shares[a] * 100
            opt = eq.optimal_shares[a] * 100
            d = eq.deltas[a] * 100
            st = eq.statuses[a]

            tbl.setItem(ri, 0, QTableWidgetItem(a))

            cur_item = QTableWidgetItem(f"{cur:.1f}%")
            cur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 1, cur_item)

            opt_item = QTableWidgetItem(f"{opt:.1f}%")
            opt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if opt > 0.5:
                opt_item.setForeground(QColor(theme.OK))
            tbl.setItem(ri, 2, opt_item)

            sign = "+" if d > 0 else ""
            d_item = QTableWidgetItem(f"{sign}{d:.1f}%")
            d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            d_clr = (QColor(theme.OK) if d > 2 else
                     QColor(theme.ERR) if d < -2 else
                     QColor(theme.TEXT_DIM))
            d_item.setForeground(d_clr)
            tbl.setItem(ri, 3, d_item)

            st_item = QTableWidgetItem(st)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            st_clr = {"Underplayed": QColor("#f0c040"),
                       "Overplayed": QColor(theme.ERR),
                       "Balanced": QColor(theme.TEXT_DIM)}.get(st, QColor(theme.TEXT))
            st_item.setForeground(st_clr)
            f = st_item.font(); f.setBold(True); st_item.setFont(f)
            tbl.setItem(ri, 4, st_item)

        layout.addWidget(tbl, 1)

        # ── RPS Cycles ───────────────────────────────────────────────
        if cycles:
            layout.addWidget(QLabel(
                f"Rock-Paper-Scissors Cycles ({len(cycles)} found):"
            ))

            cycle_tbl = QTableWidget()
            cycle_tbl.setColumnCount(4)
            cycle_tbl.setHorizontalHeaderLabels(
                ["A beats B", "B beats C", "C beats A", "Strength"])
            ch = cycle_tbl.horizontalHeader()
            for c in range(4):
                ch.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
            cycle_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            cycle_tbl.setRowCount(min(len(cycles), 10))

            for ri, cyc in enumerate(cycles[:10]):
                a, b, cc = cyc.archetypes
                w1, w2, w3 = cyc.win_rates

                tbl_items = [
                    f"{a} > {b} ({w1*100:.0f}%)",
                    f"{b} > {cc} ({w2*100:.0f}%)",
                    f"{cc} > {a} ({w3*100:.0f}%)",
                    f"{cyc.strength*100:.1f}%",
                ]
                for ci, text in enumerate(tbl_items):
                    item = QTableWidgetItem(text)
                    if ci == 3:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        strength_clr = (QColor(theme.ERR) if cyc.strength > 0.58 else
                                        QColor(theme.WARN) if cyc.strength > 0.55 else
                                        QColor(theme.TEXT_DIM))
                        item.setForeground(strength_clr)
                    cycle_tbl.setItem(ri, ci, item)

            layout.addWidget(cycle_tbl)
        else:
            layout.addWidget(QLabel(
                "No Rock-Paper-Scissors cycles detected (need WR \u226553% on all edges)."
            ))

        # ── Interpretation ───────────────────────────────────────────
        underplayed = [a for a in eq.archetypes if eq.statuses[a] == "Underplayed"
                       and eq.optimal_shares[a] > 0.01]
        overplayed = [a for a in eq.archetypes if eq.statuses[a] == "Overplayed"
                      and eq.current_shares[a] > 0.03]
        if underplayed or overplayed:
            tip_parts = []
            if underplayed:
                names = ", ".join(underplayed[:3])
                tip_parts.append(f"Underplayed (exploit opportunity): {names}")
            if overplayed:
                names = ", ".join(overplayed[:3])
                tip_parts.append(f"Overplayed (bring a counter): {names}")
            tip = QLabel("\n".join(tip_parts))
            tip.setWordWrap(True)
            tip.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: 11px; padding: 6px; "
                f"background: {theme.PANEL}; border-radius: 4px;"
            )
            layout.addWidget(tip)

        # ── Monte Carlo Simulation ───────────────────────────────────
        mc_bar = QWidget()
        mc_bar.setStyleSheet(f"background: {theme.PANEL}; border-radius: 4px;")
        mc_layout = QVBoxLayout(mc_bar)
        mc_layout.setContentsMargins(8, 8, 8, 8)
        mc_layout.setSpacing(6)

        mc_header = QLabel("Monte Carlo Tournament Simulation")
        mc_header.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
        mc_layout.addWidget(mc_header)

        mc_controls = QHBoxLayout()

        from PyQt6.QtWidgets import QSpinBox
        players_lbl = QLabel("Players:")
        players_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        mc_controls.addWidget(players_lbl)
        players_spin = QSpinBox()
        players_spin.setRange(32, 2000)
        players_spin.setValue(128)
        players_spin.setSingleStep(32)
        mc_controls.addWidget(players_spin)

        rounds_lbl = QLabel("Rounds:")
        rounds_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        mc_controls.addWidget(rounds_lbl)
        rounds_spin = QSpinBox()
        rounds_spin.setRange(4, 15)
        rounds_spin.setValue(7)
        mc_controls.addWidget(rounds_spin)

        sims_lbl = QLabel("Simulations:")
        sims_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        mc_controls.addWidget(sims_lbl)
        sims_spin = QSpinBox()
        sims_spin.setRange(1000, 100000)
        sims_spin.setValue(10000)
        sims_spin.setSingleStep(1000)
        mc_controls.addWidget(sims_spin)

        run_mc_btn = QPushButton("Run Simulation")
        run_mc_btn.setStyleSheet(theme.btn_primary())
        mc_controls.addWidget(run_mc_btn)
        mc_controls.addStretch()
        mc_layout.addLayout(mc_controls)

        mc_status = QLabel("Configure parameters and click Run Simulation.")
        mc_status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        mc_layout.addWidget(mc_status)

        mc_result_tbl = QTableWidget()
        mc_result_tbl.setColumnCount(3)
        mc_result_tbl.setHorizontalHeaderLabels(["Archetype", "Top-8 Rate", "Sim Win Rate"])
        mc_result_tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            mc_result_tbl.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        mc_result_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        mc_result_tbl.setVisible(False)
        mc_layout.addWidget(mc_result_tbl)
        layout.addWidget(mc_bar)

        # Wire Run button
        _mc_worker_ref = [None]

        def _run_monte_carlo():
            run_mc_btn.setEnabled(False)
            mc_status.setText("Running simulation…")
            mc_result_tbl.setVisible(False)

            worker = _MonteCarloWorker(
                result=result,
                players=players_spin.value(),
                rounds=rounds_spin.value(),
                simulations=sims_spin.value(),
            )
            _mc_worker_ref[0] = worker

            def _on_done(sim_result):
                mc_result_tbl.setRowCount(len(sim_result.top8_rates))
                for ri, (arch, rate) in enumerate(sim_result.top8_rates.items()):
                    mc_result_tbl.setItem(ri, 0, QTableWidgetItem(arch))

                    rate_item = QTableWidgetItem(f"{rate*100:.2f}%")
                    rate_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    clr = (QColor(theme.OK) if rate > 0.10 else
                           QColor(theme.WARN) if rate > 0.06 else
                           QColor(theme.TEXT))
                    rate_item.setForeground(clr)
                    mc_result_tbl.setItem(ri, 1, rate_item)

                    wr = sim_result.win_rates.get(arch, 0)
                    wr_item = QTableWidgetItem(f"{wr*100:.1f}%")
                    wr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    mc_result_tbl.setItem(ri, 2, wr_item)

                mc_result_tbl.setVisible(True)
                mc_status.setText(
                    f"Done — {sim_result.simulations:,} tournaments simulated. "
                    f"Top-8 rate = appearances / (simulations × top_cut)."
                )
                run_mc_btn.setEnabled(True)
                worker.deleteLater()

            def _on_error(msg):
                mc_status.setText(theme.friendly_error(msg))
                run_mc_btn.setEnabled(True)
                worker.deleteLater()

            worker.finished_ok.connect(_on_done)
            worker.error.connect(_on_error)
            worker.start()

        run_mc_btn.clicked.connect(_run_monte_carlo)

        dlg.exec()

    # ------------------------------------------------------------------
    # Gauntlet export / import
    # ------------------------------------------------------------------

    def _export_gauntlet(self):
        """Export current matchup matrix as a shareable JSON file."""
        import json, os
        from datetime import datetime
        from PyQt6.QtWidgets import QFileDialog

        if not self._current_matrix:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Export", "No matchup data loaded. Load data first.")
            return

        fmt = self._loaded_format or self._fmt.currentText()
        tf_label = self._TIMEFRAME_OPTIONS[self._tf.currentIndex()][0]

        export_data = {
            "type": "mtg_meta_gauntlet",
            "format": fmt,
            "timeframe": tf_label,
            "exported_at": datetime.now().isoformat(),
            "archetypes": sorted(self._current_matrix.keys()),
            "matchups": {},
            "sources": {},
        }

        for a, opps in self._current_matrix.items():
            export_data["matchups"][a] = {}
            for b, stats in opps.items():
                export_data["matchups"][a][b] = {
                    "winrate": stats.get("winrate", 0.5),
                    "matches": stats.get("matches", 0),
                }
                src = self._source_map.get((a, b), "unknown")
                export_data["sources"][f"{a} vs {b}"] = src

        exports_dir = os.path.join(os.path.dirname(__file__), "..", "..", "exports")
        os.makedirs(exports_dir, exist_ok=True)
        default_name = f"gauntlet_{fmt}_{datetime.now().strftime('%Y%m%d')}.json"
        default_path = os.path.join(exports_dir, default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Gauntlet", default_path,
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        self._updated_lbl.setText(f"Exported to {os.path.basename(path)}")


# ======================================================================
# Monte Carlo simulation worker
# ======================================================================

class _MonteCarloWorker(QThread):
    finished_ok = pyqtSignal(object)   # SimulationResult
    error       = pyqtSignal(str)

    def __init__(self, result: dict, players: int, rounds: int, simulations: int):
        super().__init__()
        self._result      = result
        self._players     = players
        self._rounds      = rounds
        self._simulations = simulations

    def run(self):
        try:
            from analysis.equilibrium import simulate_tournament
            import numpy as np

            eq = self._result.get("equilibrium")
            raw_matrix = self._result.get("matrix")  # may be None

            if not eq or not eq.archetypes:
                self.error.emit("No equilibrium data — load the heatmap first.")
                return

            # Build payoff matrix from equilibrium data if raw matrix not stored
            archs = eq.archetypes
            n = len(archs)
            idx = {a: i for i, a in enumerate(archs)}

            if raw_matrix is not None and hasattr(raw_matrix, "shape"):
                matrix = raw_matrix
            else:
                # Reconstruct from win_rates stored on eq object (if available)
                matrix = np.full((n, n), 0.5)
                if hasattr(eq, "win_rates"):
                    for a in archs:
                        for b in archs:
                            if a != b and (a, b) in eq.win_rates:
                                matrix[idx[a]][idx[b]] = eq.win_rates[(a, b)]

            sim_result = simulate_tournament(
                matrix=matrix,
                arch_list=archs,
                field_shares=eq.current_shares,
                players=self._players,
                rounds=self._rounds,
                top_cut=min(8, self._players // 8),
                simulations=self._simulations,
            )
            self.finished_ok.emit(sim_result)

        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()[-300:]}")
