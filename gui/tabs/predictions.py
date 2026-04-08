"""
Tab 5 — Predictions
  Table of recent predictions with status (pending / correct / wrong)
  Generate Predictions button, Validate button, accuracy summary
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QFrame, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from gui.worker_threads import DataLoadWorker
import gui.theme as theme


class PredictionsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Controls ──────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(120)
        ctrl.addWidget(self._fmt)

        self._pending_only = QCheckBox("Pending only")
        ctrl.addWidget(self._pending_only)

        self._gen_btn = QPushButton("Generate Predictions")
        self._gen_btn.setStyleSheet(theme.btn_primary())
        self._gen_btn.clicked.connect(self._generate)
        ctrl.addWidget(self._gen_btn)

        self._val_btn = QPushButton("Validate")
        self._val_btn.setStyleSheet(theme.btn_success())
        self._val_btn.clicked.connect(self._validate)
        ctrl.addWidget(self._val_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_btn.clicked.connect(self._load)
        ctrl.addWidget(self._refresh_btn)

        self._status = QLabel("")
        ctrl.addWidget(self._status)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── How this works ────────────────────────────────────────────
        info = QFrame()
        info.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
            " border-radius: 4px; padding: 4px;"
        )
        info_lbl = QLabel(
            "<b>How predictions work:</b> Each week the system auto-generates forecasts "
            "from recent meta trends. <b>top_meta</b> = expected to rank in the top archetypes; "
            "<b>trending_up</b> = expected to gain meta share; "
            "<b>trending_down</b> = expected to decline. "
            "After the target week passes, click <i>Validate</i> to score them against "
            "actual results. Accuracy is tracked per prediction type so you can see "
            "which signals are most reliable."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; border: none; background: transparent;"
        )
        QVBoxLayout(info).addWidget(info_lbl)
        layout.addWidget(info)

        # ── Prediction table ──────────────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Archetype", "Type", "Predicted", "Target Week", "Actual", "Correct"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        # ── Accuracy summary bar ──────────────────────────────────────
        summary = QFrame()
        summary.setFixedHeight(60)
        summary.setStyleSheet(
            "border: 1px solid #2d2e3f; border-radius: 4px; padding: 6px;"
        )
        sv = QHBoxLayout(summary)
        self._accuracy_lbl = QLabel("Accuracy: \u2014 (no validated predictions yet)")
        self._accuracy_lbl.setFont(QFont("Arial", 11))
        self._accuracy_lbl.setStyleSheet("border: none;")
        sv.addWidget(self._accuracy_lbl)
        sv.addStretch()
        layout.addWidget(summary)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _generate(self):
        fmt = self._fmt.currentText()
        self._status.setText("Generating predictions\u2026")
        self._gen_btn.setEnabled(False)

        def _do():
            from analysis.predictions import generate_predictions
            return generate_predictions(fmt, commit=True)

        def _done(preds):
            n = len(preds) if preds else 0
            self._status.setText(f"Generated {n} prediction{'s' if n != 1 else ''}.")
            self._gen_btn.setEnabled(True)
            self._load()

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._gen_btn.setEnabled(True),
        ))
        w.start()
        self._workers.append(w)

    def _validate(self):
        fmt = self._fmt.currentText()
        self._status.setText("Validating\u2026")
        self._val_btn.setEnabled(False)

        def _do():
            from analysis.predictions import validate_predictions
            return validate_predictions(fmt)

        def _done(results):
            n = len(results) if results else 0
            self._status.setText(f"Validated {n} prediction{'s' if n != 1 else ''}.")
            self._val_btn.setEnabled(True)
            self._load()

        w = DataLoadWorker(_do)
        w.result.connect(_done)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._val_btn.setEnabled(True),
        ))
        w.start()
        self._workers.append(w)

    def _load(self):
        fmt     = self._fmt.currentText()
        pending = self._pending_only.isChecked()

        def _do():
            from analysis.predictions import recent_predictions, accuracy_report
            preds  = recent_predictions(fmt, limit=200, pending_only=pending)
            report = accuracy_report(fmt)
            return {"predictions": preds, "report": report}

        def _show(data):
            self._populate(data.get("predictions", []))
            self._show_accuracy(data.get("report", {}))

        w = DataLoadWorker(_do)
        w.result.connect(_show)
        w.error.connect(lambda e: self._status.setText(f"Load error: {e}"))
        w.start()
        self._workers.append(w)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _populate(self, predictions):
        self._table.setRowCount(0)
        if not predictions:
            return
        self._table.setRowCount(len(predictions))
        for row, p in enumerate(predictions):
            arch       = p.get("archetype", "")
            ptype      = p.get("prediction_type", "")
            pred_rank  = p.get("predicted_rank")
            pred_share = p.get("predicted_share")
            predicted  = (
                f"rank {pred_rank}" if pred_rank is not None
                else f"{pred_share:.1%}" if pred_share is not None
                else "\u2014"
            )
            target     = (p.get("target_week") or "")[:10] or "\u2014"
            act_rank   = p.get("actual_rank")
            act_share  = p.get("actual_share")
            actual     = (
                f"rank {act_rank}" if act_rank is not None
                else f"{act_share:.1%}" if act_share is not None
                else "pending"
            )
            correct = p.get("correct")

            self._table.setItem(row, 0, QTableWidgetItem(arch))
            self._table.setItem(row, 1, QTableWidgetItem(ptype))
            self._table.setItem(row, 2, QTableWidgetItem(predicted))
            self._table.setItem(row, 3, QTableWidgetItem(target))
            self._table.setItem(row, 4, QTableWidgetItem(actual))

            if correct is None:
                ci = QTableWidgetItem("pending")
                ci.setForeground(QColor("#888888"))
            elif correct:
                ci = QTableWidgetItem("\u2713 correct")
                ci.setForeground(QColor("#3cb44b"))
            else:
                ci = QTableWidgetItem("\u2717 wrong")
                ci.setForeground(QColor("#e6194b"))
            self._table.setItem(row, 5, ci)

    def _show_accuracy(self, report):
        if not report:
            self._accuracy_lbl.setText("Accuracy: \u2014 (no validated predictions yet)")
            return
        overall = report.get("overall", {})
        acc     = overall.get("accuracy")
        total   = overall.get("total", 0)
        correct = overall.get("correct", 0)

        if acc is not None and total > 0:
            parts = [f"Overall: {acc:.1%}  ({correct}/{total})"]
            for k, v in report.items():
                if k != "overall" and isinstance(v, dict) and v.get("total", 0) > 0:
                    parts.append(
                        f"{k}: {v.get('accuracy', 0):.1%} ({v.get('correct',0)}/{v.get('total',0)})"
                    )
            self._accuracy_lbl.setText("  |  ".join(parts))
        else:
            self._accuracy_lbl.setText("Accuracy: \u2014 (no validated predictions yet)")
