"""
Tab 4 — Charts
Interactive chart controls on the left, live embedded matplotlib canvas on the right.

Supports: Meta Share | Archetype Trend | Matchup Heatmap
All charts are rendered live inside the GUI. Save PNG writes the current
canvas figure to data/charts/ without re-generating.
"""
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QCheckBox, QListWidget, QListWidgetItem,
    QSizePolicy, QDateEdit, QSpinBox,
)
from PyQt6.QtCore import QDate, Qt

from gui.widgets.chart_canvas import ChartCanvas
from gui.worker_threads import DataLoadWorker
import gui.theme as theme

_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class ChartsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()
        self._refresh_archetypes()

    def cleanup(self):
        """Block signals on any running workers. Called by MainWindow on app exit."""
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()
        # Also clean up the chart canvas's internal loader worker
        if hasattr(self, "_canvas") and hasattr(self._canvas, "_worker"):
            try:
                if self._canvas._worker is not None:
                    self._canvas._worker.blockSignals(True)
            except RuntimeError:
                pass

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── Left: controls panel ──────────────────────────────────────
        ctrl = QGroupBox("Chart Controls")
        ctrl.setFixedWidth(230)
        ctrl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        cv = QVBoxLayout(ctrl)
        cv.setSpacing(8)

        # Chart type
        cv.addWidget(QLabel("Chart Type:"))
        self._type = QComboBox()
        self._type.addItems(["Meta Share", "Archetype Trend", "Compare Trends", "Meta Positioning", "Matchup Heatmap"])
        self._type.currentTextChanged.connect(self._on_type_changed)
        cv.addWidget(self._type)

        # Format
        cv.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.currentIndexChanged.connect(self._refresh_archetypes)
        cv.addWidget(self._fmt)

        # Archetype (Trend only) — editable combo populated from DB
        self._arch_label = QLabel("Archetype:")
        cv.addWidget(self._arch_label)
        self._arch = QComboBox()
        self._arch.setEditable(True)
        self._arch.setMinimumWidth(160)
        self._arch.lineEdit().setPlaceholderText("e.g. Izzet Prowess")
        self._arch.lineEdit().returnPressed.connect(self._on_arch_enter)
        cv.addWidget(self._arch)

        # Compare list (shown for Compare Trends mode)
        self._compare_label = QLabel("Selected archetypes:")
        self._compare_label.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
        cv.addWidget(self._compare_label)
        self._compare_list = QListWidget()
        self._compare_list.setMaximumHeight(120)
        self._compare_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._compare_list.setStyleSheet(
            f"background: {theme.INPUT}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; font-size: 10px;"
        )
        cv.addWidget(self._compare_list)

        cmp_row = QHBoxLayout()
        self._add_arch_btn = QPushButton("+ Add")
        self._add_arch_btn.setStyleSheet(theme.btn_secondary())
        self._add_arch_btn.clicked.connect(self._add_compare_arch)
        cmp_row.addWidget(self._add_arch_btn)
        self._rm_arch_btn = QPushButton("Remove")
        self._rm_arch_btn.setStyleSheet(theme.btn_secondary())
        self._rm_arch_btn.clicked.connect(self._remove_compare_arch)
        cmp_row.addWidget(self._rm_arch_btn)
        self._compare_btn_row = QWidget()
        self._compare_btn_row.setLayout(cmp_row)
        cv.addWidget(self._compare_btn_row)

        # Timeframe
        cv.addWidget(QLabel("Timeframe:"))
        self._weeks = QComboBox()
        for label, _ in theme.TIMEFRAME_OPTIONS:
            self._weeks.addItem(label)
        self._weeks.setCurrentText(theme.TIMEFRAME_DEFAULT)
        cv.addWidget(self._weeks)

        # Top N (not shown for Trend)
        self._top_label = QLabel("Top N archetypes:")
        cv.addWidget(self._top_label)
        self._top_n = QSpinBox()
        self._top_n.setRange(3, 20)
        self._top_n.setValue(10)
        cv.addWidget(self._top_n)

        # Date range
        cv.addWidget(QLabel("From:"))
        self._date_from = QDateEdit()
        self._date_from.setDate(QDate.currentDate().addDays(-84))
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        cv.addWidget(self._date_from)

        cv.addWidget(QLabel("To:"))
        self._date_to = QDateEdit()
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        cv.addWidget(self._date_to)

        self._use_dates = QCheckBox("Use date range")
        cv.addWidget(self._use_dates)

        cv.addStretch()

        # Buttons
        self._gen_btn = QPushButton("Generate Chart")
        self._gen_btn.setStyleSheet(theme.btn_primary())
        self._gen_btn.clicked.connect(self.generate)
        cv.addWidget(self._gen_btn)

        self._save_btn = QPushButton("Save PNG")
        self._save_btn.setStyleSheet(theme.btn_secondary())
        self._save_btn.clicked.connect(self._save_png)
        cv.addWidget(self._save_btn)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        cv.addWidget(self._status)

        outer.addWidget(ctrl)

        # ── Right: chart canvas ───────────────────────────────────────
        self._canvas = ChartCanvas()
        outer.addWidget(self._canvas, 1)

        # Initial visibility — must run after all controls are created
        self._on_type_changed("Meta Share")

    def _on_type_changed(self, chart_type):
        is_trend   = chart_type == "Archetype Trend"
        is_compare = chart_type == "Compare Trends"
        need_arch  = is_trend or is_compare
        self._arch_label.setVisible(need_arch)
        self._arch.setVisible(need_arch)
        self._compare_label.setVisible(is_compare)
        self._compare_list.setVisible(is_compare)
        self._compare_btn_row.setVisible(is_compare)
        self._top_label.setVisible(not need_arch)
        self._top_n.setVisible(not need_arch)

    def _get_date_range(self):
        if not self._use_dates.isChecked():
            return None, None
        since = datetime.fromisoformat(
            self._date_from.date().toString("yyyy-MM-dd")
        )
        until = datetime.fromisoformat(
            self._date_to.date().toString("yyyy-MM-dd")
        )
        return since, until

    def generate(self):
        chart_type = self._type.currentText()
        fmt   = self._fmt.currentText()
        weeks = theme.TIMEFRAME_OPTIONS[self._weeks.currentIndex()][1]
        top   = self._top_n.value()
        since, until = self._get_date_range()

        self._gen_btn.setEnabled(False)
        self._status.setText("Generating\u2026")

        try:
            if chart_type == "Meta Share":
                self._canvas.plot_meta_share(fmt, top, weeks, since, until)
            elif chart_type == "Archetype Trend":
                arch = self._arch.currentText().strip()
                if not arch:
                    self._status.setText("Enter an archetype name.")
                    return
                self._canvas.plot_trend(arch, fmt, weeks, since, until)
            elif chart_type == "Compare Trends":
                archetypes = [
                    self._compare_list.item(i).text()
                    for i in range(self._compare_list.count())
                ]
                if len(archetypes) < 2:
                    self._status.setText("Add at least 2 archetypes to compare.")
                    return
                self._canvas.plot_compare(archetypes, fmt, weeks, since, until)
            elif chart_type == "Meta Positioning":
                self._canvas.plot_scatter(fmt, top, weeks, since, until)
            elif chart_type == "Matchup Heatmap":
                self._canvas.plot_heatmap(fmt, top, 3, since, until)
            self._status.setText("Done.")
        except Exception as e:
            self._status.setText(theme.friendly_error(e))
        finally:
            self._gen_btn.setEnabled(True)

    def _on_arch_enter(self):
        """Enter key in archetype field: add to compare list in Compare mode, generate otherwise."""
        if self._type.currentText() == "Compare Trends":
            self._add_compare_arch()
        else:
            self.generate()

    def _add_compare_arch(self):
        arch = self._arch.currentText().strip()
        if not arch:
            return
        # Don't add duplicates
        existing = [
            self._compare_list.item(i).text()
            for i in range(self._compare_list.count())
        ]
        if arch not in existing:
            self._compare_list.addItem(arch)
        self._arch.lineEdit().clear()

    def _remove_compare_arch(self):
        for item in self._compare_list.selectedItems():
            self._compare_list.takeItem(self._compare_list.row(item))

    def _save_png(self):
        """Save the currently displayed chart figure to data/charts/."""
        charts_dir = os.path.join(_project_root, "data", "charts")
        os.makedirs(charts_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = self._type.currentText().replace(" ", "_").lower()
        fmt  = self._fmt.currentText()
        path = os.path.join(charts_dir, f"{name}_{fmt}_{ts}.png")
        try:
            self._canvas._fig.savefig(
                path, dpi=150, bbox_inches="tight", facecolor=theme.CHART_BG
            )
            self._status.setText(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            self._status.setText(f"Save failed: {e}")

    # ------------------------------------------------------------------
    # External API — called from other tabs (e.g. clicking a row in Dashboard)
    # ------------------------------------------------------------------

    def _refresh_archetypes(self):
        """Populate the archetype combo with top archetypes for the current format."""
        fmt = self._fmt.currentText()

        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT d.archetype, COUNT(*) AS cnt
                    FROM decks d
                    JOIN events e ON e.id = d.event_id
                    WHERE lower(e.format) = lower(?)
                    GROUP BY d.archetype
                    ORDER BY cnt DESC
                    LIMIT 100
                """, [fmt]).fetchall()
            finally:
                conn.close()
            return [r[0] for r in rows]

        w = DataLoadWorker(_do)
        w.result.connect(self._on_archetypes_loaded)
        w.start()
        self._workers.append(w)

    def _on_archetypes_loaded(self, archetypes: list):
        current = self._arch.currentText()
        self._arch.blockSignals(True)
        self._arch.clear()
        self._arch.addItems(archetypes)
        idx = self._arch.findText(current)
        self._arch.setCurrentIndex(idx if idx >= 0 else -1)
        if idx < 0:
            self._arch.lineEdit().setText(current)
        self._arch.blockSignals(False)

    def show_archetype_trend(self, archetype, format_name="standard"):
        """Programmatically load this tab and render a trend chart."""
        self._type.setCurrentText("Archetype Trend")
        self._arch.setCurrentText(archetype)
        self._fmt.setCurrentText(format_name)
        self._canvas.plot_trend(
            archetype, format_name,
            theme.TIMEFRAME_OPTIONS[self._weeks.currentIndex()][1],
        )
