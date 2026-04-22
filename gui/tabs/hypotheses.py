"""
Sub-tab — Matchup Hypotheses

Log a prediction ('I think Amulet Titan vs Boros Energy is 58% for my side')
then see it lined up against three signals:

    Your pred | Sim WR | Real WR | Personal WR

Delta columns show how far off your intuition was from each source.
"""
from datetime import date as _date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialog,
    QFormLayout, QComboBox, QSpinBox, QTextEdit, QLineEdit,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


_FORMATS = ["modern", "standard", "pioneer", "legacy"]
_CONFIDENCE = ["low", "medium", "high"]


class _HypothesisDialog(QDialog):
    """Add / edit one matchup prediction."""
    def __init__(self, parent=None, row=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Hypothesis" if row else "New Hypothesis")
        self.setMinimumSize(*theme.DIALOG_SM)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._a = QLineEdit()
        self._a.setPlaceholderText("Your side  e.g. Amulet Titan")
        form.addRow("Your deck:", self._a)

        self._b = QLineEdit()
        self._b.setPlaceholderText("Opponent  e.g. Boros Energy")
        form.addRow("Opponent:", self._b)

        self._fmt = QComboBox()
        self._fmt.addItems(_FORMATS)
        form.addRow("Format:", self._fmt)

        self._pred = QSpinBox()
        self._pred.setRange(0, 100)
        self._pred.setSuffix("%  (my side wins)")
        self._pred.setValue(50)
        form.addRow("Prediction:", self._pred)

        self._conf = QComboBox()
        self._conf.addItems(_CONFIDENCE)
        self._conf.setCurrentText("medium")
        form.addRow("Confidence:", self._conf)

        self._notes = QTextEdit()
        self._notes.setMaximumHeight(80)
        self._notes.setPlaceholderText(
            "Why do you think this? 'Amulet is faster than their clock', "
            "'I side in 2 Dismember G2', etc."
        )
        form.addRow("Rationale:", self._notes)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        if row:
            self._a.setText(row.get("a_deck", ""))
            self._b.setText(row.get("b_deck", ""))
            fmt = row.get("format", "modern")
            if fmt in _FORMATS:
                self._fmt.setCurrentText(fmt)
            self._pred.setValue(int(row.get("prediction", 50)))
            self._conf.setCurrentText(row.get("confidence", "medium") or "medium")
            self._notes.setPlainText(row.get("notes", ""))

    def data(self) -> dict:
        return {
            "a_deck": self._a.text().strip(),
            "b_deck": self._b.text().strip(),
            "format_name": self._fmt.currentText(),
            "prediction": self._pred.value(),
            "confidence": self._conf.currentText(),
            "notes": self._notes.toPlainText().strip(),
        }


def _lookup_signals(a: str, b: str, format_name: str) -> dict:
    """Return {'real_wr': float|None, 'sample': int, 'personal_wr': float|None,
    'personal_n': int}. Silent on errors."""
    result = {"real_wr": None, "sample": 0,
              "personal_wr": None, "personal_n": 0}
    try:
        from analysis.win_rates import get_real_matchup_winrates
        from analysis.archetypes import normalize as norm_arch
        an, bn = norm_arch(a), norm_arch(b)
        real = get_real_matchup_winrates(format_name, min_matches=5)
        if an in real and bn in real[an]:
            entry = real[an][bn]
            result["real_wr"] = entry["win_rate"]
            result["sample"] = entry["total"]
        elif bn in real and an in real[bn]:
            entry = real[bn][an]
            result["real_wr"] = 1.0 - entry["win_rate"]
            result["sample"] = entry["total"]
    except Exception:
        pass
    try:
        from db.match_log import get_matchup_stats
        from analysis.archetypes import normalize as norm_arch
        stats = get_matchup_stats(norm_arch(a), format_name=format_name)
        bn = norm_arch(b)
        if bn in stats:
            entry = stats[bn]
            result["personal_wr"] = entry.get("wr")
            result["personal_n"] = entry.get("total", 0)
    except Exception:
        pass
    return result


class HypothesesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._workers = []
        self._build_ui()
        self._reload()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                theme.SPACE_MD, theme.SPACE_MD)
        lay.setSpacing(theme.SPACE_SM)

        header = QLabel("Matchup Hypotheses")
        header.setStyleSheet(theme.h1_style())
        lay.addWidget(header)

        desc = QLabel(
            "Log your gut-feel for a matchup before testing. Later, "
            "the table shows your prediction next to the scraped real-match "
            "WR and your personal log WR so you can see which intuitions "
            "panned out."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        lay.addWidget(desc)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(theme.SPACE_SM)

        ctrl.addWidget(QLabel("Format:"))
        self._filter_fmt = QComboBox()
        self._filter_fmt.addItem("All")
        self._filter_fmt.addItems(_FORMATS)
        self._filter_fmt.currentTextChanged.connect(lambda _: self._reload())
        ctrl.addWidget(self._filter_fmt)
        ctrl.addStretch()

        from gui.icons_util import btn_icon
        self._add_btn = QPushButton(btn_icon("add", color=theme.BTN_FG), "New")
        self._add_btn.setStyleSheet(
            f"background: {theme.ACCENT}; color: {theme.BTN_FG}; "
            f"font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        self._add_btn.clicked.connect(self._on_add)
        ctrl.addWidget(self._add_btn)

        self._edit_btn = QPushButton(btn_icon("edit"), "Edit")
        self._edit_btn.setStyleSheet(theme.btn_secondary())
        self._edit_btn.clicked.connect(self._on_edit)
        ctrl.addWidget(self._edit_btn)

        self._del_btn = QPushButton(btn_icon("delete", color=theme.ERR), "Delete")
        self._del_btn.setStyleSheet(f"color: {theme.ERR};")
        self._del_btn.clicked.connect(self._on_delete)
        ctrl.addWidget(self._del_btn)

        lay.addLayout(ctrl)

        # Table
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            "Date", "Your Deck", "Opponent", "Format",
            "Your pred", "Real WR (n)", "Your log (n)", "Notes"
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for c in (0, 3, 4, 5, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table, 1)

    def cleanup(self):
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()

    # ------------------------------------------------------------------
    # Data plumbing
    # ------------------------------------------------------------------

    def _reload(self):
        fmt = self._filter_fmt.currentText()
        fmt_arg = None if fmt == "All" else fmt

        def _do():
            from db.hypotheses import get_hypotheses
            rows = get_hypotheses(fmt_arg)
            # Compute signals per row (blocking DB work) — fine at this scale
            out = []
            for r in rows:
                sigs = _lookup_signals(r["a_deck"], r["b_deck"], r["format"])
                r = dict(r)
                r.update(sigs)
                out.append(r)
            return out

        w = DataLoadWorker(_do)
        w.result.connect(self._on_loaded)
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_loaded(self, rows: list):
        self._rows = rows
        self._table.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            date_str = (r.get("created_at") or "")[:10]
            self._table.setItem(ri, 0, QTableWidgetItem(date_str))
            self._table.setItem(ri, 1, QTableWidgetItem(r.get("a_deck", "")))
            self._table.setItem(ri, 2, QTableWidgetItem(r.get("b_deck", "")))
            fmt = (r.get("format") or "").capitalize()
            self._table.setItem(ri, 3, QTableWidgetItem(fmt))

            pred = int(r.get("prediction", 50))
            pred_item = QTableWidgetItem(f"{pred}%")
            pred_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            conf = r.get("confidence", "medium")
            pred_item.setToolTip(f"Confidence: {conf}")
            self._table.setItem(ri, 4, pred_item)

            real_wr = r.get("real_wr")
            if real_wr is not None:
                real_pct = round(real_wr * 100, 1)
                delta = round(pred - real_pct, 1)
                text = f"{real_pct}%  ({r.get('sample', 0)})"
                item = QTableWidgetItem(text)
                item.setToolTip(
                    f"You said {pred}%. Scraped real-match data says "
                    f"{real_pct}% across {r.get('sample', 0)} matches. "
                    f"Delta: {delta:+.1f} pts"
                )
                item.setForeground(_delta_color(delta))
            else:
                item = QTableWidgetItem("—")
                item.setToolTip("No scraped matchup data for this pairing "
                                 "(min 5 matches).")
                item.setForeground(QColor(theme.TEXT_OFF))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 5, item)

            p_wr = r.get("personal_wr")
            p_n = r.get("personal_n", 0)
            if p_wr is not None and p_n > 0:
                p_pct = round(p_wr * 100, 1)
                delta = round(pred - p_pct, 1)
                text = f"{p_pct}%  ({p_n})"
                item = QTableWidgetItem(text)
                item.setToolTip(
                    f"You said {pred}%. Your match log says {p_pct}% "
                    f"across {p_n} logged matches. Delta: {delta:+.1f} pts"
                )
                item.setForeground(_delta_color(delta))
            else:
                item = QTableWidgetItem("—")
                item.setToolTip("No matches logged for this pairing.")
                item.setForeground(QColor(theme.TEXT_OFF))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ri, 6, item)

            notes = (r.get("notes") or "").replace("\n", " / ")
            self._table.setItem(ri, 7, QTableWidgetItem(notes[:120]))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _on_add(self):
        dlg = _HypothesisDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = dlg.data()
        if not d["a_deck"] or not d["b_deck"]:
            QMessageBox.warning(self, "Missing", "Enter both decks.")
            return
        from db.hypotheses import save_hypothesis
        save_hypothesis(**d)
        self._reload()

    def _on_edit(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            return
        r = self._rows[row]
        dlg = _HypothesisDialog(self, row=r)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = dlg.data()
        from db.hypotheses import save_hypothesis
        save_hypothesis(hypothesis_id=r["id"], **d)
        self._reload()

    def _on_delete(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            return
        r = self._rows[row]
        ok = QMessageBox.question(
            self, "Delete hypothesis",
            f"Delete '{r['a_deck']} vs {r['b_deck']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        from db.hypotheses import delete_hypothesis
        delete_hypothesis(r["id"])
        self._reload()


def _delta_color(delta: float) -> QColor:
    """Green when prediction matches reality, red when way off."""
    abs_d = abs(delta)
    if abs_d < 3:
        return QColor(theme.OK)
    if abs_d < 7:
        return QColor(theme.WARN)
    return QColor(theme.ERR)
