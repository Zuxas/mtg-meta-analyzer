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
    QComboBox, QSpinBox, QGroupBox, QLineEdit, QCheckBox,
    QSizePolicy,
)
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDateEdit

from gui.widgets.chart_canvas import ChartCanvas

_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class ChartsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

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
        self._type.addItems(["Meta Share", "Archetype Trend", "Matchup Heatmap"])
        self._type.currentTextChanged.connect(self._on_type_changed)
        cv.addWidget(self._type)

        # Format
        cv.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        cv.addWidget(self._fmt)

        # Archetype (Trend only)
        self._arch_label = QLabel("Archetype:")
        cv.addWidget(self._arch_label)
        self._arch = QLineEdit()
        self._arch.setPlaceholderText("e.g. Izzet Prowess")
        cv.addWidget(self._arch)

        # Weeks
        cv.addWidget(QLabel("Weeks back:"))
        self._weeks = QSpinBox()
        self._weeks.setRange(1, 52)
        self._weeks.setValue(12)
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
        self._gen_btn.setStyleSheet(
            "QPushButton { background: #00bcd4; color: #0a0e1a; border: none; "
            "padding: 8px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #00ddf0; }"
            "QPushButton:disabled { background: #2a2a4e; color: #555; }"
        )
        self._gen_btn.clicked.connect(self.generate)
        cv.addWidget(self._gen_btn)

        self._save_btn = QPushButton("Save PNG")
        self._save_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #3a8a9a; "
            "border: 1px solid #1e3a4a; padding: 6px; border-radius: 3px; }"
            "QPushButton:hover { border-color: #00bcd4; color: #00bcd4; }"
        )
        self._save_btn.clicked.connect(self._save_png)
        cv.addWidget(self._save_btn)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888888; font-size: 10px;")
        self._status.setWordWrap(True)
        cv.addWidget(self._status)

        outer.addWidget(ctrl)

        # ── Right: chart canvas ───────────────────────────────────────
        self._canvas = ChartCanvas()
        outer.addWidget(self._canvas, 1)

        # Initial visibility
        self._on_type_changed("Meta Share")

    def _on_type_changed(self, chart_type):
        is_trend = chart_type == "Archetype Trend"
        self._arch_label.setVisible(is_trend)
        self._arch.setVisible(is_trend)
        self._top_label.setVisible(not is_trend)
        self._top_n.setVisible(not is_trend)

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
        weeks = self._weeks.value()
        top   = self._top_n.value()
        since, until = self._get_date_range()

        self._gen_btn.setEnabled(False)
        self._status.setText("Generating\u2026")

        try:
            if chart_type == "Meta Share":
                self._canvas.plot_meta_share(fmt, top, weeks, since, until)
            elif chart_type == "Archetype Trend":
                arch = self._arch.text().strip()
                if not arch:
                    self._status.setText("Enter an archetype name.")
                    return
                self._canvas.plot_trend(arch, fmt, weeks, since, until)
            elif chart_type == "Matchup Heatmap":
                self._canvas.plot_heatmap(fmt, top, 3, since, until)
            self._status.setText("Done.")
        except Exception as e:
            self._status.setText(f"Error: {e}")
        finally:
            self._gen_btn.setEnabled(True)

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
                path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e"
            )
            self._status.setText(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            self._status.setText(f"Save failed: {e}")

    # ------------------------------------------------------------------
    # External API — called from other tabs (e.g. clicking a row in Dashboard)
    # ------------------------------------------------------------------

    def show_archetype_trend(self, archetype, format_name="standard"):
        """Programmatically load this tab and render a trend chart."""
        self._type.setCurrentText("Archetype Trend")
        self._arch.setText(archetype)
        self._fmt.setCurrentText(format_name)
        self._canvas.plot_trend(archetype, format_name, self._weeks.value())
