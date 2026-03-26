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
    QDialog, QPlainTextEdit, QDialogButtonBox, QScrollArea,
    QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

import gui.theme as theme


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _wr_color(winrate: float) -> QColor:
    """Background QColor for a given win-rate (0.0–1.0)."""
    pct = winrate * 100
    if pct >= 60:
        return QColor(20, 80, 35)
    if pct >= 55:
        return QColor(30, 65, 30)
    if pct >= 45:
        return QColor(55, 55, 65)
    if pct >= 40:
        return QColor(80, 35, 30)
    return QColor(100, 20, 20)


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
    done  = pyqtSignal(dict)
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
            self.done.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class _LoadWorker(QThread):
    done  = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, format_name: str):
        super().__init__()
        self.format_name = format_name

    def run(self):
        try:
            from db.matchup_queries import get_matchup_matrix
            self.done.emit(get_matchup_matrix(self.format_name))
        except Exception as exc:
            self.error.emit(str(exc))


class _CombinedWorker(QThread):
    """Load real match data + cached scraped data and merge them."""
    done  = pyqtSignal(dict, dict)  # (combined_matrix, source_map)
    error = pyqtSignal(str)

    def __init__(self, format_name: str):
        super().__init__()
        self.format_name = format_name

    def run(self):
        try:
            # 1) Real match data from matches table
            from analysis.win_rates import get_real_matchup_winrates
            real_raw = get_real_matchup_winrates(self.format_name, min_matches=20)

            # Convert canonical (a<b) to full bidirectional matrix
            real_matrix = {}
            for a, opponents in real_raw.items():
                for b, stats in opponents.items():
                    wr_a = stats["win_rate"]
                    n    = stats["total"]
                    real_matrix.setdefault(a, {})[b] = {
                        "winrate": wr_a, "matches": n,
                    }
                    real_matrix.setdefault(b, {})[a] = {
                        "winrate": round(1.0 - wr_a, 4), "matches": n,
                    }

            # 2) Cached scraped data
            from db.matchup_queries import get_matchup_matrix
            scraped = get_matchup_matrix(self.format_name)

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

            self.done.emit(combined, source)
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
            self._error_lbl.setText("No data found. Check the format.")
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
        self._current_matrix: dict = {}
        self._source_map: dict = {}  # {(a,b): "real"|"scraped"}
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
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(100)
        tl.addWidget(self._fmt)

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

        self._paste_btn = QPushButton("Paste Data")
        self._paste_btn.setStyleSheet(theme.btn_secondary())
        self._paste_btn.setToolTip(
            "Manually paste CSV or JSON matchup data "
            "(e.g. from Frank Karsten or I Love Azorius tweets)"
        )
        self._paste_btn.clicked.connect(self._open_paste_dialog)
        tl.addWidget(self._paste_btn)

        tl.addStretch()

        self._updated_lbl = QLabel("")
        self._updated_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        tl.addWidget(self._updated_lbl)

        outer.addWidget(toolbar)

        # ── Status label ──────────────────────────────────────────────
        self._status = QLabel(
            "Click \u2018Real Match Data (DB)\u2019 for heatmap from actual match results, "
            "or \u2018MTGDecks Live\u2019 to scrape."
        )
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; padding: 8px;"
        )
        outer.addWidget(self._status)

        # ── Grid (inside a scroll area) ───────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVisible(False)
        self._grid_widget = QWidget()
        self._scroll.setWidget(self._grid_widget)
        outer.addWidget(self._scroll, 1)

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
            ("\u226560% (Strong Fav)", QColor(20, 80, 35)),
            ("55\u201359% (Favored)",  QColor(30, 65, 30)),
            ("45\u201354% (Even)",     QColor(55, 55, 65)),
            ("40\u201344% (Unfav)",    QColor(80, 35, 30)),
            ("\u226439% (Bad)",        QColor(100, 20, 20)),
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
    # Workers
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self._combined_btn.setEnabled(not busy)
        self._fetch_btn.setEnabled(not busy)
        self._cache_btn.setEnabled(not busy)
        self._paste_btn.setEnabled(not busy)

    def cleanup(self):
        """Stop running worker. Called by MainWindow on app exit."""
        self._cancel_worker()

    def _cancel_worker(self):
        if self._worker is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None

    def _load_combined(self):
        """Default action: real match data + scraped fills gaps."""
        fmt = self._fmt.currentText()
        self._load_source = "combined"
        self._status.setText(f"Loading real match data + cached scrapes for {fmt}\u2026")
        self._status.setVisible(True)
        self._scroll.setVisible(False)
        self._set_busy(True)

        self._cancel_worker()
        self._worker = _CombinedWorker(fmt)
        self._worker.done.connect(self._on_combined_data)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_combined_data(self, matrix: dict, source_map: dict):
        self._source_map = source_map
        self._on_data(matrix)

    def _fetch_live(self):
        fmt = self._fmt.currentText()
        self._load_source = "fetch"
        self._source_map = {}
        self._status.setText(f"Fetching {fmt} win-rates from MTGDecks\u2026")
        self._status.setVisible(True)
        self._scroll.setVisible(False)
        self._set_busy(True)

        self._cancel_worker()
        self._worker = _FetchWorker(fmt)
        self._worker.done.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _load_cached(self):
        fmt = self._fmt.currentText()
        self._load_source = "cache"
        self._source_map = {}
        self._status.setText(f"Loading cached {fmt} data\u2026")
        self._status.setVisible(True)
        self._scroll.setVisible(False)
        self._set_busy(True)

        self._cancel_worker()
        self._worker = _LoadWorker(fmt)
        self._worker.done.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _open_paste_dialog(self):
        dlg = _PasteDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_matrix:
            self._source_map = {}
            self._on_data(dlg.result_matrix)

    # ------------------------------------------------------------------
    # Data callbacks
    # ------------------------------------------------------------------

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._scroll.setVisible(False)
        self._status.setVisible(True)
        self._status.setText(f"Error: {msg}")

    def _on_data(self, matrix: dict):
        self._set_busy(False)
        if not matrix:
            self._scroll.setVisible(False)
            self._status.setVisible(True)
            if getattr(self, "_load_source", None) == "cache":
                self._status.setText(
                    "No cached data yet \u2014 click \u2018Real Match Data (DB)\u2019 "
                    "or \u2018MTGDecks Live\u2019 first."
                )
            elif getattr(self, "_load_source", None) == "combined":
                self._status.setText(
                    "No match data found. Run the MTGMelee scraper or fetch from MTGDecks."
                )
            else:
                self._status.setText(
                    "No data found. Try \u2018Real Match Data (DB)\u2019 or \u2018MTGDecks Live\u2019."
                )
            return

        self._current_matrix = matrix
        fmt = self._fmt.currentText()
        filtered, ordered = self._filter_to_meta(matrix, fmt)
        self._draw_grid(filtered, ordered, total_archetypes=len(matrix))

        # Update last-updated label
        source = getattr(self, "_load_source", "")
        if source == "combined":
            real_ct = sum(1 for v in self._source_map.values() if v == "real")
            scr_ct  = sum(1 for v in self._source_map.values() if v == "scraped")
            self._updated_lbl.setText(
                f"\u2605 {real_ct} real cells  |  {scr_ct} scraped cells"
            )
        else:
            try:
                from db.matchup_queries import get_last_updated
                ts = get_last_updated(fmt)
                self._updated_lbl.setText(f"Last updated: {ts[:10] if ts else 'just now'}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Meta filtering
    # ------------------------------------------------------------------

    def _filter_to_meta(self, matrix: dict, format_name: str, top: int = 30):
        """
        Return (filtered_matrix, ordered_archetypes) keeping only the top-N
        archetypes by meta share, sorted descending.
        Uses case-insensitive matching to bridge naming differences between
        data sources.
        """
        try:
            from analysis.win_rates import get_meta_standings
            standings = get_meta_standings(format_name, top=top, min_appearances=2)
        except Exception:
            standings = []

        if not standings:
            return matrix, sorted(matrix.keys())

        # Build a case-insensitive lookup from matrix keys
        matrix_lower = {k.lower(): k for k in matrix}

        # Match meta archetype names to matrix keys (case-insensitive + substring)
        ordered = []
        for s in standings:
            arch = s["archetype"]
            low  = arch.lower()
            # Exact match (case-insensitive)
            if low in matrix_lower:
                ordered.append(matrix_lower[low])
            else:
                # Substring match: check if the meta name is a substring of any matrix key or vice versa
                for mk_low, mk_orig in matrix_lower.items():
                    if mk_orig not in ordered and (low in mk_low or mk_low in low):
                        ordered.append(mk_orig)
                        break

        if not ordered:
            # No overlap found — fall back to sorting by number of matchup cells
            by_cells = sorted(matrix.keys(), key=lambda a: -len(matrix.get(a, {})))
            return matrix, by_cells[:top]

        ordered_set = set(ordered)
        filtered = {
            a: {b: v for b, v in matrix[a].items() if b in ordered_set}
            for a in ordered if a in matrix
        }
        return filtered, ordered

    # ------------------------------------------------------------------
    # Grid drawing
    # ------------------------------------------------------------------

    def _draw_grid(self, matrix: dict, ordered_archetypes: list = None,
                   total_archetypes: int = None):
        archetypes = ordered_archetypes if ordered_archetypes is not None \
                     else sorted(matrix.keys())
        n = len(archetypes)
        source_map = self._source_map

        tbl = QTableWidget(n, n)
        tbl.setHorizontalHeaderLabels(archetypes)
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

        for ri, arch_a in enumerate(archetypes):
            for ci, arch_b in enumerate(archetypes):
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
                        item.setBackground(_wr_color(wr))
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        verdict = _wr_label(wr)
                        src_tag = "Real match data" if is_real else "Scraped (MTGDecks)"
                        tooltip = (
                            f"{arch_a}  vs  {arch_b}\n"
                            f"Win rate: {pct}%  ({verdict})\n"
                            f"Source: {src_tag}"
                        )
                        if matches:
                            tooltip += f"\nSample: n={matches:,}"
                        item.setToolTip(tooltip)
                        if pct < 43 or pct > 57:
                            f = QFont()
                            f.setBold(True)
                            item.setFont(f)

                tbl.setItem(ri, ci, item)

        # Rotate column headers
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # Replace grid widget content
        old_layout = self._grid_widget.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            import sip
            try:
                sip.delete(old_layout)
            except Exception:
                pass

        vl = QVBoxLayout(self._grid_widget)
        vl.setContentsMargins(0, 0, 0, 0)

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
        vl.addWidget(tbl, 1)

        self._status.setVisible(False)
        self._scroll.setVisible(True)
