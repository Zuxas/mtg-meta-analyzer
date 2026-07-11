"""
Tab — Settings
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
from PyQt6.QtCore import Qt, pyqtSignal, QThread
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
        self._backfill_worker = None
        self._ml_worker = None
        self._build_ui()
        self._load()

    def cleanup(self):
        from gui.worker_utils import stop_worker
        stop_worker(self._backfill_worker)
        stop_worker(self._ml_worker)
        self._backfill_worker = None
        self._ml_worker = None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Content is built in a plain QWidget, then wrapped in a QScrollArea
        # so the tab scrolls instead of forcing the whole window taller --
        # this tab's standalone minimumSizeHint() was ~878px unscrolled,
        # one of the two tabs (with deck_analyzer.py::DeckAnalyzerTab)
        # binding MainWindow's minimum height above 900px. Same pattern as
        # gui/tabs/event_optimizer.py::EventWidget / dashboard.py / event_hub_tab.py.
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(18)

        # ── Formats ───────────────────────────────────────────────────
        fmt_box = QGroupBox("Formats to Track")
        fmt_layout = QVBoxLayout(fmt_box)
        fmt_layout.setSpacing(theme.SPACE_SM)

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
        self._storage_lbl.setWordWrap(True)
        sv.addWidget(self._storage_lbl)

        store_btns = QHBoxLayout()
        self._backfill_btn = QPushButton("Collect More Data")
        self._backfill_btn.setStyleSheet(theme.btn_primary())
        self._backfill_btn.setToolTip(
            "Run a backfill scrape for selected formats and sources"
        )
        self._backfill_btn.clicked.connect(self._show_backfill_dialog)
        store_btns.addWidget(self._backfill_btn)

        self._refresh_storage_btn = QPushButton("Refresh")
        self._refresh_storage_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_storage_btn.clicked.connect(self._refresh_storage)
        store_btns.addWidget(self._refresh_storage_btn)

        self._dedup_btn = QPushButton("Scan Duplicates")
        self._dedup_btn.setStyleSheet(theme.btn_secondary())
        self._dedup_btn.setToolTip(
            "Find duplicate events across MTGTop8, MTGDecks, and MTGMelee"
        )
        self._dedup_btn.clicked.connect(self._show_dedup_report)
        store_btns.addWidget(self._dedup_btn)

        store_btns.addStretch()
        self._backfill_status = QLabel("")
        self._backfill_status.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        self._backfill_status.setWordWrap(True)
        store_btns.addWidget(self._backfill_status)
        sv.addLayout(store_btns)

        # ── ML Models ─────────────────────────────────────────────
        ml_box = QGroupBox("ML Models (Advanced Analytics)")
        ml_layout = QVBoxLayout(ml_box)
        ml_layout.setSpacing(6)

        ml_info = QLabel(
            "Card embeddings power Similar Cards, Functional Substitutes, and "
            "auto-archetype classification. Download once; models train in minutes."
        )
        ml_info.setWordWrap(True)
        ml_info.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        ml_layout.addWidget(ml_info)

        ml_btns = QHBoxLayout()

        self._dl_embeddings_btn = QPushButton("Download Card Embeddings")
        self._dl_embeddings_btn.setStyleSheet(theme.btn_primary())
        self._dl_embeddings_btn.setToolTip(
            "Download ModernBERT 768-dim card embeddings from HuggingFace (~150 MB)\n"
            "Required for: Similar Cards, deck similarity, KNN classifier"
        )
        self._dl_embeddings_btn.clicked.connect(self._download_embeddings)
        ml_btns.addWidget(self._dl_embeddings_btn)

        self._train_card2vec_btn = QPushButton("Train Card2Vec")
        self._train_card2vec_btn.setStyleSheet(theme.btn_secondary())
        self._train_card2vec_btn.setToolTip(
            "Train Word2Vec on your local decklists (~2-5 min)\n"
            "Required for: Functional Substitutes panel"
        )
        self._train_card2vec_btn.clicked.connect(self._train_card2vec)
        ml_btns.addWidget(self._train_card2vec_btn)

        self._train_knn_btn = QPushButton("Train KNN Classifier")
        self._train_knn_btn.setStyleSheet(theme.btn_secondary())
        self._train_knn_btn.setToolTip(
            "Train KNN archetype classifier on your decklists\n"
            "Required for: auto-classify unrecognized archetypes during scraping"
        )
        self._train_knn_btn.clicked.connect(self._train_knn)
        ml_btns.addWidget(self._train_knn_btn)

        ml_btns.addStretch()
        ml_layout.addLayout(ml_btns)

        self._ml_status_lbl = QLabel("")
        self._ml_status_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        self._ml_status_lbl.setWordWrap(True)
        ml_layout.addWidget(self._ml_status_lbl)

        self._refresh_ml_status()
        outer.addWidget(ml_box)

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
        av.setSpacing(theme.SPACE_SM)

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

        # ── Save / Reset bar ──────────────────────────────────────────
        bar = QHBoxLayout()
        bar.addStretch()
        reset_state_btn = QPushButton("Reset UI state")
        reset_state_btn.setStyleSheet(theme.btn_secondary())
        reset_state_btn.setToolTip(
            "Clear persisted selections, filters, palette recents.\n"
            "Does not affect format / API key / scrape preferences."
        )
        reset_state_btn.clicked.connect(self._on_reset_ui_state)
        bar.addWidget(reset_state_btn)
        self._save_btn = QPushButton("Save Settings")
        self._save_btn.setStyleSheet(theme.btn_primary())
        self._save_btn.clicked.connect(self._save)
        bar.addWidget(self._save_btn)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        bar.addWidget(self._status_lbl)
        outer.addLayout(bar)

        outer.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

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

    def _on_reset_ui_state(self):
        from gui.state import UIState
        ok = QMessageBox.question(
            self, "Reset UI state",
            "Clear persisted selections, filters, and palette recents?\n"
            "(Format / API key / scrape preferences are NOT affected.)"
        )
        if ok == QMessageBox.StandardButton.Yes:
            UIState.instance().reset()
            UIState.instance().flush()
            QMessageBox.information(self, "Reset", "UI state cleared. Restart for full effect.")

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
            self._arch_status_lbl.setText(theme.friendly_error(e))

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

    # ------------------------------------------------------------------
    # Cross-source duplicate detection
    # ------------------------------------------------------------------

    def _show_dedup_report(self):
        """Show a dialog with cross-source duplicate event analysis."""
        from analysis.cross_source_dedup import get_dedup_report
        fmt = "standard"
        # Use the first selected format from preferences
        prefs = load_preferences()
        fmts = prefs.get("formats", ["standard"])
        if fmts:
            fmt = fmts[0]

        try:
            report = get_dedup_report(fmt)
        except Exception as e:
            QMessageBox.warning(self, "Duplicate Scan", theme.friendly_error(e))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Cross-Source Duplicates \u2014 {fmt.capitalize()}")
        dlg.setMinimumSize(600, 400)
        dlg.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")
        layout = QVBoxLayout(dlg)

        # Summary
        summary = QLabel(
            f"<b>{report['total_events']:,}</b> total events  \u00b7  "
            f"<b>{report['duplicate_groups']}</b> duplicate groups found  \u00b7  "
            f"<b>{report['removable_events']}</b> removable copies  "
            f"({report['savings_pct']}% of total)"
        )
        summary.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; padding: 6px;")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Source pair breakdown
        if report["by_source_pair"]:
            pairs_text = " \u00b7 ".join(
                f"{k}: {v}" for k, v in sorted(report["by_source_pair"].items())
            )
            pairs_lbl = QLabel(f"By source pair: {pairs_text}")
            pairs_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; padding: 2px 6px;")
            layout.addWidget(pairs_lbl)

        # Duplicate groups table
        dupes = report["duplicates"]
        if dupes:
            tbl = QTableWidget(len(dupes), 4)
            tbl.setHorizontalHeaderLabels(["Confidence", "Events", "Sources", "Reason"])
            hh = tbl.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            tbl.verticalHeader().setVisible(False)
            tbl.setAlternatingRowColors(True)

            for ri, d in enumerate(dupes):
                # Confidence
                conf = d["confidence"]
                ci = QTableWidgetItem(f"{conf*100:.0f}%")
                ci.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if conf >= 0.9:
                    ci.setForeground(QColor(theme.OK))
                elif conf >= 0.7:
                    ci.setForeground(QColor(theme.WARN))
                else:
                    ci.setForeground(QColor(theme.TEXT_DIM))
                tbl.setItem(ri, 0, ci)

                # Event names
                names = set(e["name"] for e in d["events"] if e.get("name"))
                tbl.setItem(ri, 1, QTableWidgetItem(" / ".join(sorted(names)[:2])))

                # Sources
                sources = sorted(set(e["source"] for e in d["events"]))
                tbl.setItem(ri, 2, QTableWidgetItem(", ".join(sources)))

                # Reason
                tbl.setItem(ri, 3, QTableWidgetItem(d["reason"]))

            layout.addWidget(tbl, 1)
        else:
            no_dupes = QLabel("No cross-source duplicates detected.")
            no_dupes.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_dupes.setStyleSheet(f"color: {theme.OK}; font-size: 13px; padding: 20px;")
            layout.addWidget(no_dupes)

        dlg.exec()

    # Backfill / Collect More Data
    # ------------------------------------------------------------------

    def _show_backfill_dialog(self):
        dlg = _BackfillDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        formats = dlg.selected_formats()
        sources = dlg.selected_sources()
        pages = dlg.page_count()

        if not formats:
            QMessageBox.warning(self, "No Formats", "Select at least one format.")
            return
        if not sources:
            QMessageBox.warning(self, "No Sources", "Select at least one data source.")
            return

        self._backfill_btn.setEnabled(False)
        self._backfill_status.setText(
            f"Collecting data: {', '.join(formats)} from {', '.join(sources)}..."
        )

        self._backfill_worker = _BackfillWorker(formats, sources, pages)
        self._backfill_worker.progress.connect(self._on_backfill_progress)
        self._backfill_worker.finished_ok.connect(self._on_backfill_done)
        self._backfill_worker.error.connect(self._on_backfill_error)
        self._backfill_worker.finished.connect(self._backfill_worker.deleteLater)
        self._backfill_worker.finished.connect(
            lambda: setattr(self, "_backfill_worker", None))
        self._backfill_worker.start()

    def _on_backfill_progress(self, msg: str):
        self._backfill_status.setText(msg)

    def _on_backfill_done(self, summary: str):
        self._backfill_btn.setEnabled(True)
        self._backfill_status.setText(summary)
        self._refresh_storage()

    def _on_backfill_error(self, msg: str):
        self._backfill_btn.setEnabled(True)
        self._backfill_status.setText(theme.friendly_error(msg))

    # ------------------------------------------------------------------
    # ML Models
    # ------------------------------------------------------------------

    def _refresh_ml_status(self):
        try:
            from analysis.card_embeddings import is_available
            emb_ok = is_available()
        except Exception:
            emb_ok = False
        try:
            from analysis.cooccurrence_embeddings import is_trained
            c2v_ok = is_trained()
        except Exception:
            c2v_ok = False
        parts = [
            f"Embeddings: {'✓ Ready' if emb_ok else '✗ Not downloaded'}",
            f"Card2Vec: {'✓ Trained' if c2v_ok else '✗ Not trained'}",
        ]
        self._ml_status_lbl.setText("  |  ".join(parts))

    def _download_embeddings(self):
        self._ml_status_lbl.setText("Downloading…")
        self._dl_embeddings_btn.setEnabled(False)
        self._ml_worker = _MLWorker("download", [])
        self._ml_worker.progress.connect(self._ml_status_lbl.setText)
        self._ml_worker.finished_ok.connect(lambda m: [
            self._ml_status_lbl.setText(m),
            self._dl_embeddings_btn.setEnabled(True),
            self._refresh_ml_status(),
        ])
        self._ml_worker.error.connect(lambda e: [
            self._ml_status_lbl.setText(theme.friendly_error(e)),
            self._dl_embeddings_btn.setEnabled(True),
        ])
        self._ml_worker.start()

    def _train_card2vec(self):
        self._ml_status_lbl.setText("Training Card2Vec…")
        self._train_card2vec_btn.setEnabled(False)
        import json, os
        prefs_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "preferences.json")
        try:
            with open(prefs_path) as f:
                formats = json.load(f).get("formats", ["standard", "modern"])
        except Exception:
            formats = ["standard", "modern"]
        self._ml_worker = _MLWorker("card2vec", formats)
        self._ml_worker.progress.connect(self._ml_status_lbl.setText)
        self._ml_worker.finished_ok.connect(lambda m: [
            self._ml_status_lbl.setText(m),
            self._train_card2vec_btn.setEnabled(True),
            self._refresh_ml_status(),
        ])
        self._ml_worker.error.connect(lambda e: [
            self._ml_status_lbl.setText(theme.friendly_error(e)),
            self._train_card2vec_btn.setEnabled(True),
        ])
        self._ml_worker.start()

    def _train_knn(self):
        self._ml_status_lbl.setText("Training KNN classifier…")
        self._train_knn_btn.setEnabled(False)
        import json, os
        prefs_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "preferences.json")
        try:
            with open(prefs_path) as f:
                formats = json.load(f).get("formats", ["standard", "modern"])
        except Exception:
            formats = ["standard", "modern"]
        self._ml_worker = _MLWorker("knn", formats)
        self._ml_worker.progress.connect(self._ml_status_lbl.setText)
        self._ml_worker.finished_ok.connect(lambda m: [
            self._ml_status_lbl.setText(m),
            self._train_knn_btn.setEnabled(True),
            self._refresh_ml_status(),
        ])
        self._ml_worker.error.connect(lambda e: [
            self._ml_status_lbl.setText(theme.friendly_error(e)),
            self._train_knn_btn.setEnabled(True),
        ])
        self._ml_worker.start()


# ======================================================================
# Backfill dialog
# ======================================================================

class _BackfillDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Collect More Data")
        self.setMinimumWidth(380)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        v.addWidget(QLabel("Select which formats and sources to scrape.\n"
                           "This runs in the background — you can keep using the app."))

        # Formats
        fmt_box = QGroupBox("Formats")
        fmt_lay = QVBoxLayout(fmt_box)
        self._fmt_checks = {}
        for fmt in ("standard", "pioneer", "modern", "legacy", "pauper"):
            cb = QCheckBox(fmt.capitalize())
            if fmt in ("modern", "pioneer"):
                cb.setChecked(True)  # these are thin by default
            self._fmt_checks[fmt] = cb
            fmt_lay.addWidget(cb)
        v.addWidget(fmt_box)

        # Sources
        src_box = QGroupBox("Data Sources")
        src_lay = QVBoxLayout(src_box)
        self._src_checks = {}
        sources = [
            ("mtgtop8_backfill", "MTGTop8 Historical Backfill (deep — years of data)"),
            ("mtgtop8_latest", "MTGTop8 Latest Events (recent pages)"),
            ("mtgdecks", "MTGDecks.net (decklists + events)"),
            ("melee", "Melee.gg (real match results)"),
        ]
        for key, label in sources:
            cb = QCheckBox(label)
            if key == "mtgtop8_backfill":
                cb.setChecked(True)
            self._src_checks[key] = cb
            src_lay.addWidget(cb)
        v.addWidget(src_box)

        # Pages
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Pages per source:"))
        self._pages_spin = QComboBox()
        self._pages_spin.addItems(["3 (quick)", "5 (moderate)", "10 (thorough)", "20 (deep)"])
        self._pages_spin.setCurrentIndex(1)
        page_row.addWidget(self._pages_spin)
        page_row.addStretch()
        v.addLayout(page_row)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Start Collection")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def selected_formats(self) -> list[str]:
        return [fmt for fmt, cb in self._fmt_checks.items() if cb.isChecked()]

    def selected_sources(self) -> list[str]:
        return [src for src, cb in self._src_checks.items() if cb.isChecked()]

    def page_count(self) -> int:
        text = self._pages_spin.currentText()
        return int(text.split(" ")[0])


# ======================================================================
# ML model workers + SettingsTab ML methods (injected at class level)
# ======================================================================

class _MLWorker(QThread):
    progress    = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    error       = pyqtSignal(str)

    def __init__(self, task: str, formats: list):
        super().__init__()
        self._task    = task
        self._formats = formats

    def run(self):
        try:
            if self._task == "download":
                from scripts.download_embeddings import download
                download(progress_cb=lambda m: self.progress.emit(m))
                self.finished_ok.emit("Card embeddings downloaded.")

            elif self._task == "card2vec":
                from analysis.cooccurrence_embeddings import train_card2vec
                for fmt in self._formats:
                    self.progress.emit(f"Training Card2Vec for {fmt}…")
                    model = train_card2vec(fmt)
                    self.progress.emit(f"{fmt}: {len(model.wv)} card vectors")
                self.finished_ok.emit("Card2Vec training complete.")

            elif self._task == "knn":
                from analysis.knn_classifier import train_knn
                for fmt in self._formats:
                    self.progress.emit(f"Training KNN for {fmt}…")
                    clf = train_knn(fmt)
                    msg = "trained" if clf else "insufficient data"
                    self.progress.emit(f"{fmt}: {msg}")
                self.finished_ok.emit("KNN training complete.")

            elif self._task == "backfill_classify":
                self._run_backfill_classify()
                self.finished_ok.emit("Backfill classification complete.")

        except Exception as e:
            self.error.emit(str(e))

    def _run_backfill_classify(self):
        """Retroactively classify unrecognized archetypes using KNN."""
        from db.database import get_connection
        from analysis.knn_classifier import classify_deck, load_knn

        _JUNK = {"", "Decklist", "All Other Decklists", "Rogue Decklists",
                 "Others", "Other", "Unclassified"}

        with get_connection() as conn:
            rows = conn.execute("""
                SELECT d.id, d.archetype, e.format,
                       GROUP_CONCAT(c.name || ':' || dc.quantity, '|') AS cards
                FROM decks d
                JOIN events e ON e.id = d.event_id
                LEFT JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
                LEFT JOIN cards c ON c.id = dc.card_id
                WHERE d.archetype IN ({})
                GROUP BY d.id
                LIMIT 10000
            """.format(",".join("?" * len(_JUNK))),
            list(_JUNK)).fetchall()

        classified = 0
        for row in rows:
            if not row["cards"]:
                continue
            fmt = (row["format"] or "").lower()
            if not load_knn(fmt):
                continue
            card_list = {}
            for entry in row["cards"].split("|"):
                parts = entry.rsplit(":", 1)
                if len(parts) == 2:
                    card_list[parts[0]] = int(parts[1])
            if not card_list:
                continue
            result = classify_deck(card_list, fmt)
            if result:
                predicted, confidence = result
                if confidence >= 0.6:
                    with get_connection() as conn:
                        conn.execute("UPDATE decks SET archetype=? WHERE id=?",
                                     (predicted, row["id"]))
                    classified += 1
            if classified % 100 == 0 and classified > 0:
                self.progress.emit(f"Classified {classified} decks so far…")

        self.progress.emit(f"Done — classified {classified} previously unrecognized decks.")



# ======================================================================
# ML worker
# ======================================================================

class _MLWorker(QThread):
    progress    = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    error       = pyqtSignal(str)

    def __init__(self, task: str, formats: list):
        super().__init__()
        self._task    = task
        self._formats = formats

    def run(self):
        try:
            if self._task == "download":
                import subprocess, sys
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.download_embeddings"],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr[-500:])
                self.finished_ok.emit("Card embeddings downloaded successfully.")

            elif self._task == "card2vec":
                from analysis.cooccurrence_embeddings import train_card2vec
                for fmt in self._formats:
                    self.progress.emit(f"Training Card2Vec for {fmt}…")
                    model = train_card2vec(fmt)
                    self.progress.emit(f"{fmt}: {len(model.wv)} card vectors")
                self.finished_ok.emit("Card2Vec training complete.")

            elif self._task == "knn":
                from analysis.knn_classifier import train_knn
                for fmt in self._formats:
                    self.progress.emit(f"Training KNN for {fmt}…")
                    clf = train_knn(fmt)
                    self.progress.emit(f"{fmt}: {'trained' if clf else 'insufficient data'}")
                self.finished_ok.emit("KNN training complete.")

        except Exception as e:
            self.error.emit(str(e))


# ======================================================================
# Backfill worker
# ======================================================================

class _BackfillWorker(QThread):
    progress    = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    error       = pyqtSignal(str)

    def __init__(self, formats: list[str], sources: list[str], pages: int):
        super().__init__()
        self._formats = formats
        self._sources = sources
        self._pages   = pages

    def run(self):
        import sys, io
        if hasattr(sys.stdout, "buffer") and sys.stdout.buffer is not None:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace")

        total_steps = len(self._formats) * len(self._sources)
        step = 0
        errors = []

        for fmt in self._formats:
            for src in self._sources:
                step += 1
                self.progress.emit(
                    f"[{step}/{total_steps}] {fmt.capitalize()} from {src}..."
                )
                try:
                    if src == "mtgtop8_backfill":
                        from scrapers.backfill import run_backfill
                        run_backfill(format_name=fmt)

                    elif src == "mtgtop8_latest":
                        from scrapers.mtgtop8 import run as mtgtop8_run
                        mtgtop8_run(format_name=fmt, pages=self._pages,
                                    max_events=self._pages * 10)

                    elif src == "mtgdecks":
                        from scrapers.mtgdecks import run_scraper as mtgdecks_run
                        mtgdecks_run(format_name=fmt, pages=self._pages)

                    elif src == "melee":
                        from scrapers.mtgmelee_scraper import scrape_and_store
                        scrape_and_store(format_name=fmt, pages=self._pages)

                except Exception as e:
                    errors.append(f"{fmt}/{src}: {e}")

        # Normalize after scrape
        try:
            self.progress.emit("Normalizing archetype names...")
            from analysis.archetypes import apply_normalization
            apply_normalization(dry_run=False, fuzzy=False)
        except Exception:
            pass

        if errors:
            self.finished_ok.emit(
                f"Done with {len(errors)} error(s): {'; '.join(errors[:3])}")
        else:
            self.finished_ok.emit(
                f"Done! Scraped {total_steps} format/source combinations."
            )
