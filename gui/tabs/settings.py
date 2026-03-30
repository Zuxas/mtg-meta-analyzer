"""
Tab 6 — Settings
User preferences: formats to track, data window, timezone, auto-update frequency.
Persists to data/preferences.json.
"""
import json
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QFormLayout, QFrame, QLineEdit,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QDialogButtonBox, QMessageBox, QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

import gui.theme as theme

_PREFS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "preferences.json",
)

_DEFAULTS = {
    "formats":     ["standard"],
    "date_window": "3years",
    "timezone":    "UTC",
    "auto_update": "daily",
}


def load_preferences() -> dict:
    if os.path.exists(_PREFS_PATH):
        try:
            with open(_PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Fill any missing keys with defaults
            for k, v in _DEFAULTS.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_preferences(prefs: dict):
    from datetime import datetime
    os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
    prefs["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(_PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


class SettingsTab(QWidget):
    # Emitted when the Anthropic API key is saved — main window shows/hides Ask Claude tab
    api_key_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(18)

        # ── Formats ───────────────────────────────────────────────────
        fmt_box = QGroupBox("Formats to Track")
        fmt_layout = QVBoxLayout(fmt_box)
        fmt_layout.setSpacing(8)

        self._fmt_checks = {}
        for fmt in ["standard", "pioneer", "modern", "legacy"]:
            cb = QCheckBox(fmt.capitalize())
            cb.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
            fmt_layout.addWidget(cb)
            self._fmt_checks[fmt] = cb

        note = QLabel(
            "Unchecking a format stops new data collection — existing data is kept."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        fmt_layout.addWidget(note)
        outer.addWidget(fmt_box)

        # ── Data window ───────────────────────────────────────────────
        window_box = QGroupBox("Data Window")
        wf = QFormLayout(window_box)
        wf.setSpacing(10)

        self._window_combo = QComboBox()
        self._window_combo.addItems([
            "2 weeks", "1 month", "3 months", "1 year", "3 years",
        ])
        self._window_combo.setFixedWidth(160)
        wf.addRow(QLabel("Show data from the last:"), self._window_combo)
        outer.addWidget(window_box)

        # ── Auto-update ───────────────────────────────────────────────
        update_box = QGroupBox("Auto-Update Frequency")
        uf = QFormLayout(update_box)
        uf.setSpacing(10)

        self._update_combo = QComboBox()
        self._update_combo.addItems(["Daily", "Twice daily", "Weekly"])
        self._update_combo.setFixedWidth(160)
        uf.addRow(QLabel("Background scrape:"), self._update_combo)
        outer.addWidget(update_box)

        # ── Storage info ──────────────────────────────────────────────
        store_box = QGroupBox("Storage")
        sv = QVBoxLayout(store_box)
        sv.setSpacing(6)
        self._storage_lbl = QLabel("Loading…")
        self._storage_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        sv.addWidget(self._storage_lbl)
        outer.addWidget(store_box)

        # ── Archetype Manager ─────────────────────────────────────
        arch_box = QGroupBox("Archetype Manager")
        arch_layout = QVBoxLayout(arch_box)
        arch_layout.setSpacing(6)

        self._arch_status_lbl = QLabel("Loading archetype status\u2026")
        self._arch_status_lbl.setWordWrap(True)
        self._arch_status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        arch_layout.addWidget(self._arch_status_lbl)

        arch_btns = QHBoxLayout()
        self._view_unclass_btn = QPushButton("View Unclassified")
        self._view_unclass_btn.setStyleSheet(theme.btn_secondary())
        self._view_unclass_btn.clicked.connect(self._view_unclassified)
        arch_btns.addWidget(self._view_unclass_btn)

        self._add_arch_btn = QPushButton("Add Definition")
        self._add_arch_btn.setStyleSheet(theme.btn_secondary())
        self._add_arch_btn.clicked.connect(self._add_archetype_def)
        arch_btns.addWidget(self._add_arch_btn)

        self._sync_btn = QPushButton("Run Sync Now")
        self._sync_btn.setStyleSheet(theme.btn_secondary())
        self._sync_btn.clicked.connect(self._run_sync)
        arch_btns.addWidget(self._sync_btn)
        arch_btns.addStretch()
        arch_layout.addLayout(arch_btns)

        outer.addWidget(arch_box)
        self._refresh_arch_status()

        # ── AI Assistant ──────────────────────────────────────────────
        ai_box = QGroupBox("AI Assistant (optional)")
        av = QVBoxLayout(ai_box)
        av.setSpacing(8)

        ai_note = QLabel(
            "Enter your Anthropic API key to unlock the Ask Claude tab — "
            "an in-app chat that answers questions about your local meta data. "
            "Leave blank to disable. Key is stored only in preferences.json on your machine."
        )
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        av.addWidget(ai_note)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Anthropic API key:"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("sk-ant-…  (leave blank to disable AI Assistant)")
        key_row.addWidget(self._api_key_input, 1)
        av.addLayout(key_row)

        outer.addWidget(ai_box)

        # ── Save button ───────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.addStretch()
        self._save_btn = QPushButton("Save Settings")
        self._save_btn.setStyleSheet(theme.btn_primary())
        self._save_btn.clicked.connect(self._save)
        bar.addWidget(self._save_btn)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        bar.addWidget(self._status_lbl)
        outer.addLayout(bar)

        outer.addStretch()

        # Load storage info
        self._refresh_storage()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    _WINDOW_MAP = {
        "2weeks":  "2 weeks",
        "1month":  "1 month",
        "3months": "3 months",
        "1year":   "1 year",
        "3years":  "3 years",
    }
    _WINDOW_MAP_INV = {v: k for k, v in _WINDOW_MAP.items()}

    _UPDATE_MAP = {
        "daily":       "Daily",
        "twice_daily": "Twice daily",
        "weekly":      "Weekly",
    }
    _UPDATE_MAP_INV = {v: k for k, v in _UPDATE_MAP.items()}

    def _load(self):
        prefs = load_preferences()

        self._api_key_input.setText(prefs.get("anthropic_api_key", ""))

        for fmt, cb in self._fmt_checks.items():
            cb.setChecked(fmt in prefs.get("formats", ["standard"]))

        window_label = self._WINDOW_MAP.get(prefs.get("date_window", "3years"), "3 years")
        idx = self._window_combo.findText(window_label)
        if idx >= 0:
            self._window_combo.setCurrentIndex(idx)

        update_label = self._UPDATE_MAP.get(prefs.get("auto_update", "daily"), "Daily")
        idx = self._update_combo.findText(update_label)
        if idx >= 0:
            self._update_combo.setCurrentIndex(idx)

    def _save(self):
        prefs = load_preferences()
        prefs["formats"] = [f for f, cb in self._fmt_checks.items() if cb.isChecked()]
        prefs["date_window"] = self._WINDOW_MAP_INV.get(
            self._window_combo.currentText(), "3years"
        )
        prefs["auto_update"] = self._UPDATE_MAP_INV.get(
            self._update_combo.currentText(), "daily"
        )
        prefs["anthropic_api_key"] = self._api_key_input.text().strip()
        save_preferences(prefs)
        self.api_key_changed.emit(prefs["anthropic_api_key"])
        self._status_lbl.setText("Saved.")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._status_lbl.setText(""))

    def _refresh_storage(self):
        try:
            from db.database import DB_PATH, ARCHIVE_PATH as ARCHIVE_DB_PATH
            import sqlite3

            lines = []
            for label, path in [("Active DB", DB_PATH), ("Archive DB", ARCHIVE_DB_PATH)]:
                if not os.path.exists(path):
                    continue
                size_mb = os.path.getsize(path) / 1_048_576
                with sqlite3.connect(path) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(
                        "SELECT lower(format) AS fmt, COUNT(*) AS n FROM events GROUP BY fmt"
                    ).fetchall()
                fmt_str = "  ".join(f"{r['fmt']}: {r['n']:,} events" for r in rows)
                lines.append(f"{label} ({size_mb:.1f} MB) — {fmt_str or 'empty'}")

            self._storage_lbl.setText("\n".join(lines) if lines else "No database found.")
        except Exception as e:
            self._storage_lbl.setText(f"Could not read storage info: {e}")

    # ------------------------------------------------------------------
    # Archetype Manager
    # ------------------------------------------------------------------

    def _refresh_arch_status(self):
        try:
            from analysis.archetype_classifier import load_archetype_configs
            from db.database import get_connection
            from analysis.win_rates import EXCLUDE_ARCHETYPES

            load_archetype_configs.cache_clear()
            conn = get_connection()
            lines = []
            total_unclass = 0
            for fmt in ("standard", "modern", "pioneer", "legacy", "pauper"):
                configs = load_archetype_configs(fmt)
                defined = {c["name"].lower() for c in configs}
                excl = list(EXCLUDE_ARCHETYPES)
                rows = conn.execute(
                    "SELECT COUNT(DISTINCT player1_arch) FROM matches "
                    "WHERE format=? AND player1_arch != '' "
                    "AND player1_arch NOT IN ({})".format(",".join("?" * len(excl))),
                    [fmt] + excl).fetchone()[0]
                unclass = max(0, rows - len(defined))
                total_unclass += unclass
                flag = " \u26a0" if unclass > 50 else ""
                lines.append(f"{fmt.capitalize()}: {len(defined)} defined, ~{unclass} unclassified{flag}")
            conn.close()
            self._arch_status_lbl.setText("  |  ".join(lines))
            if total_unclass > 200:
                self._arch_status_lbl.setStyleSheet(f"color: {theme.WARN}; font-size: 11px;")
            else:
                self._arch_status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        except Exception as e:
            self._arch_status_lbl.setText(f"Error: {e}")

    def _view_unclassified(self):
        try:
            from scripts.sync_archetypes import sync
            rows = sync()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        if not rows:
            QMessageBox.information(self, "All Classified", "No unclassified archetypes with 20+ matches.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Unclassified Archetypes ({len(rows)})")
        dlg.setMinimumSize(500, 400)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        tbl = QTableWidget(len(rows), 3)
        tbl.setHorizontalHeaderLabels(["Archetype", "Matches", "Format"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.verticalHeader().setVisible(False)
        for ri, r in enumerate(rows):
            tbl.setItem(ri, 0, QTableWidgetItem(r["archetype_name"]))
            ci = QTableWidgetItem(str(r["match_count"]))
            ci.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(ri, 1, ci)
            tbl.setItem(ri, 2, QTableWidgetItem(r["format"]))
        layout.addWidget(tbl)
        dlg.exec()

    def _add_archetype_def(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Archetype Definition")
        dlg.setMinimumWidth(450)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        form = QFormLayout()
        fmt_combo = QComboBox()
        fmt_combo.addItems(["standard", "modern", "pioneer", "legacy", "pauper"])
        form.addRow("Format:", fmt_combo)

        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g. Gruul Energy")
        form.addRow("Archetype Name:", name_input)

        cards_input = QTextEdit()
        cards_input.setMaximumHeight(120)
        cards_input.setPlaceholderText(
            "One signature card per line:\n"
            "Card Name, minCopies\n"
            "e.g.:\n"
            "Ocelot Pride, 3\n"
            "Ragavan Nimble Pilferer, 3"
        )
        form.addRow("Signature Cards:", cards_input)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        fmt = fmt_combo.currentText()
        name = name_input.text().strip()
        if not name:
            return

        # Parse signature cards
        lines = []
        lines.append(f"\n  - name: {name}")
        lines.append("    signatureCards:")
        for line in cards_input.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            card_name = parts[0]
            min_copies = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
            lines.append(f'      - name: "{card_name}"')
            lines.append(f"        minCopies: {min_copies}")

        # Append to config file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "archetypes", f"{fmt}.txt")
        with open(config_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        from analysis.archetype_classifier import load_archetype_configs
        load_archetype_configs.cache_clear()
        self._refresh_arch_status()
        QMessageBox.information(self, "Added",
                                f"Added {name} to {fmt} config. Run classifier to apply.")

    def _run_sync(self):
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("Syncing\u2026")
        try:
            from scripts.sync_archetypes import sync
            sync()
            self._refresh_arch_status()
            self._sync_btn.setText("Run Sync Now")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
        finally:
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText("Run Sync Now")
