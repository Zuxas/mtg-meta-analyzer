"""
Tab 1 — Dashboard
  Top half:   meta standings QTableWidget (click a row to select an archetype)
  Bottom half: embedded interactive matplotlib chart (meta share or trend)
Controls: Format, Weeks, Top N, Refresh, chart type toggle
"""
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QSplitter,
)
from PyQt6.QtCore import Qt, QTimer

from gui.widgets.meta_table import MetaTable
from gui.widgets.chart_canvas import ChartCanvas
from gui.worker_threads import DataLoadWorker
import gui.theme as theme


class DashboardTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_archetype = None
        self._load_worker = None
        self._standings = None    # cached from last load
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Controls bar ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(120)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Timeframe:"))
        self._weeks = QComboBox()
        self._weeks.addItems(["2 weeks", "4 weeks", "8 weeks", "12 weeks", "6 months"])
        self._weeks.setCurrentText("2 weeks")
        self._weeks.setFixedWidth(100)
        ctrl.addWidget(self._weeks)

        ctrl.addWidget(QLabel("Top N:"))
        self._top_n = QSpinBox()
        self._top_n.setRange(3, 30)
        self._top_n.setValue(12)
        self._top_n.setFixedWidth(60)
        ctrl.addWidget(self._top_n)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_primary())
        self._refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(self._refresh_btn)

        ctrl.addWidget(QLabel("Chart:"))
        self._chart_type = QComboBox()
        self._chart_type.addItems(["Meta Share", "Archetype Trend"])
        self._chart_type.setFixedWidth(160)
        self._chart_type.currentTextChanged.connect(self._redraw_chart)
        ctrl.addWidget(self._chart_type)

        ctrl.addStretch()

        self._status = QLabel("")
        ctrl.addWidget(self._status)

        layout.addLayout(ctrl)

        # ── Splitter: table (top) / chart (bottom) ────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._table = MetaTable()
        self._table.archetype_selected.connect(self._on_arch_selected)
        self._table.itemDoubleClicked.connect(self._on_arch_double_clicked)
        splitter.addWidget(self._table)

        self._canvas = ChartCanvas()
        splitter.addWidget(self._canvas)

        splitter.setSizes([280, 400])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _WEEKS_MAP = {
        "2 weeks":  2,
        "4 weeks":  4,
        "8 weeks":  8,
        "12 weeks": 12,
        "6 months": 26,
    }

    def _selected_weeks(self) -> int:
        return self._WEEKS_MAP.get(self._weeks.currentText(), 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload meta standings from DB, then redraw the chart."""
        fmt   = self._fmt.currentText()
        top   = self._top_n.value()
        weeks = self._selected_weeks()
        since = datetime.now() - timedelta(weeks=weeks)
        self._status.setText("Loading\u2026")
        self._refresh_btn.setEnabled(False)

        from analysis.win_rates import get_meta_standings
        self._load_worker = DataLoadWorker(
            get_meta_standings,
            {"format_name": fmt, "top": top, "min_appearances": 2, "since": since},
        )
        self._load_worker.result.connect(self._on_standings)
        self._load_worker.error.connect(self._on_error)
        self._load_worker.finished.connect(
            lambda: self._refresh_btn.setEnabled(True)
        )
        self._load_worker.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_standings(self, standings):
        self._standings = standings   # cache so chart worker can skip second DB call
        self._table.populate(standings)
        n = len(standings)
        self._status.setText(f"{n} archetype{'s' if n != 1 else ''} loaded")
        self._redraw_chart()

    def _on_error(self, msg):
        self._status.setText(f"Error: {msg}")
        self._canvas.show_message(f"Error loading data:\n{msg}", "#e6194b")

    def _on_arch_selected(self, archetype):
        self._current_archetype = archetype
        self._chart_type.setCurrentText("Archetype Trend")
        # currentTextChanged fires _redraw_chart, but guard in case it was already Trend
        self._redraw_chart()

    def _on_arch_double_clicked(self, item):
        arch_item = self._table.item(self._table.currentRow(), 0)
        if not arch_item:
            return
        archetype = arch_item.text()
        from gui.widgets.archetype_detail import ArchetypeDetailDialog
        dlg = ArchetypeDetailDialog(
            archetype=archetype,
            format_name=self._fmt.currentText(),
            initial_weeks=self._selected_weeks(),
            parent=self,
        )
        dlg.exec()

    def _redraw_chart(self):
        fmt   = self._fmt.currentText()
        weeks = self._selected_weeks()
        top   = self._top_n.value()
        chart = self._chart_type.currentText()

        if chart == "Archetype Trend":
            if self._current_archetype:
                self._canvas.plot_trend(self._current_archetype, fmt, weeks)
            else:
                self._canvas.show_message(
                    "Click a row in the table to view that archetype's trend."
                )
        else:
            # Pass cached standings so the chart worker skips the 6-second DB query
            self._canvas.plot_meta_share(fmt, top, weeks, standings=self._standings)
