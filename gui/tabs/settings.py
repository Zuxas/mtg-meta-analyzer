"""
Tab 6 — Settings
User preferences: formats to track, data window, timezone, auto-update frequency.
Persists to data/preferences.json.
"""
import json
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QFormLayout, QFrame,
)
from PyQt6.QtCore import Qt

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
        save_preferences(prefs)
        self._status_lbl.setText("Saved.")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._status_lbl.setText(""))

    def _refresh_storage(self):
        try:
            from db.database import DB_PATH, ARCHIVE_DB_PATH
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
