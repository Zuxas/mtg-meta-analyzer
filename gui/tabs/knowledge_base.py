"""
Tab 7 — Knowledge Base

Left panel : Add Resource form — paste any URL and tag it with
             format / archetype / type.
Right panel : All saved resources (guides + bookmarks) in a searchable table.
             Click any row to open the URL in your browser.
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QTextEdit, QFrame,
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QDesktopServices, QColor, QFont

import gui.theme as theme
from gui.worker_threads import DataLoadWorker


_FORMATS = ["any", "standard", "pioneer", "modern", "legacy"]
_TYPES   = ["Guide", "Primer", "Sideboard Guide", "Tweet", "Article",
            "Video", "Deck Tech", "Other"]

_FMT_PRIORITY = {"standard": 1, "modern": 2, "pioneer": 3, "legacy": 4}
_TYPE_COLOR = {
    "guide":          QColor(30,  60, 40),
    "primer":         QColor(25,  40, 65),
    "sideboard guide":QColor(55,  35, 15),
    "tweet":          QColor(20,  45, 60),
    "article":        QColor(40,  35, 55),
    "video":          QColor(55,  28, 28),
    "deck tech":      QColor(40,  50, 20),
}


class KnowledgeBaseTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = []
        self._build_ui()
        self._refresh_archetypes()
        QTimer.singleShot(200, self._load_all)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── Left: Add form ────────────────────────────────────────────
        left = QGroupBox("Add Resource")
        left.setFixedWidth(280)
        lv = QVBoxLayout(left)
        lv.setSpacing(6)

        lv.addWidget(QLabel("URL *"))
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://twitter.com/… or any link")
        lv.addWidget(self._url_input)

        lv.addWidget(QLabel("Title (optional)"))
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Short description")
        lv.addWidget(self._title_input)

        lv.addWidget(QLabel("Format"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(_FORMATS)
        self._fmt_combo.setCurrentText("standard")
        lv.addWidget(self._fmt_combo)

        lv.addWidget(QLabel("Archetype"))
        self._arch_input = QComboBox()
        self._arch_input.setEditable(True)
        self._arch_input.setPlaceholderText("e.g. Izzet Prowess")
        lv.addWidget(self._arch_input)

        lv.addWidget(QLabel("Type"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(_TYPES)
        lv.addWidget(self._type_combo)

        lv.addWidget(QLabel("Note (optional)"))
        self._note_input = QTextEdit()
        self._note_input.setPlaceholderText("Brief note about why you saved this…")
        self._note_input.setMaximumHeight(70)
        lv.addWidget(self._note_input)

        lv.addStretch()

        self._add_btn = QPushButton("Save Bookmark")
        self._add_btn.setStyleSheet(theme.btn_primary())
        self._add_btn.clicked.connect(self._save_bookmark)
        lv.addWidget(self._add_btn)

        self._form_status = QLabel("")
        self._form_status.setWordWrap(True)
        self._form_status.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;")
        lv.addWidget(self._form_status)

        outer.addWidget(left)

        # ── Right: table ──────────────────────────────────────────────
        right = QFrame()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)

        # Header row: title + search + delete
        hdr = QHBoxLayout()
        hdr_lbl = QLabel("ALL RESOURCES")
        hdr_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        hdr_lbl.setStyleSheet(f"color: {theme.ACCENT}; letter-spacing: 1px;")
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()

        self._filter_fmt = QComboBox()
        self._filter_fmt.addItems(["All Formats"] + _FORMATS[1:])  # skip "any"
        self._filter_fmt.setFixedWidth(100)
        self._filter_fmt.currentIndexChanged.connect(lambda _: self._apply_filter(self._search_box.text()))
        hdr.addWidget(self._filter_fmt)

        self._filter_arch = QComboBox()
        self._filter_arch.setEditable(True)
        self._filter_arch.addItem("All Archetypes")
        self._filter_arch.setFixedWidth(150)
        self._filter_arch.lineEdit().setPlaceholderText("Archetype…")
        self._filter_arch.currentTextChanged.connect(lambda _: self._apply_filter(self._search_box.text()))
        hdr.addWidget(self._filter_arch)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search text…")
        self._search_box.setFixedWidth(160)
        self._search_box.textChanged.connect(self._apply_filter)
        hdr.addWidget(self._search_box)

        self._run_scraper_btn = QPushButton("Sync Guides")
        self._run_scraper_btn.setStyleSheet(theme.btn_secondary())
        self._run_scraper_btn.setToolTip("Fetch latest entries from the Skill Issue Magic spreadsheet")
        self._run_scraper_btn.clicked.connect(self._run_guides_scraper)
        hdr.addWidget(self._run_scraper_btn)

        self._del_btn = QPushButton("Delete Selected")
        self._del_btn.setStyleSheet(theme.btn_secondary())
        self._del_btn.clicked.connect(self._delete_selected)
        hdr.addWidget(self._del_btn)

        rv.addLayout(hdr)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Archetype", "Format", "Type", "Title / Author", "Source", "Date"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setCursor(Qt.CursorShape.PointingHandCursor)
        self._table.setToolTip("Click a row to open in browser")
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemClicked.connect(self._open_url)
        rv.addWidget(self._table)

        self._table_status = QLabel("")
        self._table_status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        rv.addWidget(self._table_status)

        outer.addWidget(right, 1)

        # store all loaded rows for filter
        self._all_rows: list[dict] = []

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _refresh_archetypes(self):
        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT d.archetype, COUNT(*) AS cnt
                    FROM decks d JOIN events e ON e.id = d.event_id
                    GROUP BY d.archetype ORDER BY cnt DESC LIMIT 150
                """).fetchall()
            finally:
                conn.close()
            return [r[0] for r in rows if r[0]]

        w = DataLoadWorker(_do)
        w.result.connect(self._on_archetypes)
        w.start()
        self._workers.append(w)

    def _on_archetypes(self, archetypes):
        current = self._arch_input.currentText()
        self._arch_input.blockSignals(True)
        self._arch_input.clear()
        self._arch_input.addItems(archetypes)
        idx = self._arch_input.findText(current)
        self._arch_input.setCurrentIndex(idx if idx >= 0 else -1)
        if idx < 0:
            self._arch_input.lineEdit().setText(current)
        self._arch_input.blockSignals(False)

    def _load_all(self):
        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                guides = conn.execute("""
                    SELECT archetype, format, type, author AS title,
                           source, date AS date_str, url, 'guide' AS origin, comment
                    FROM guides ORDER BY
                        CASE lower(format) WHEN 'standard' THEN 1
                            WHEN 'modern' THEN 2 WHEN 'pioneer' THEN 3
                            WHEN 'legacy' THEN 4 ELSE 5 END,
                        date DESC
                """).fetchall()
                bookmarks = conn.execute("""
                    SELECT archetype, format, type, title,
                           '' AS source, added_at AS date_str, url,
                           'bookmark' AS origin, note AS comment
                    FROM bookmarks ORDER BY added_at DESC
                """).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in bookmarks] + [dict(r) for r in guides]

        w = DataLoadWorker(_do)
        w.result.connect(self._on_rows_loaded)
        w.start()
        self._workers.append(w)

    def _on_rows_loaded(self, rows):
        self._all_rows = rows
        # Populate archetype filter from loaded data
        archs = sorted({r.get("archetype", "") for r in rows if r.get("archetype")})
        self._filter_arch.blockSignals(True)
        self._filter_arch.clear()
        self._filter_arch.addItem("All Archetypes")
        self._filter_arch.addItems(archs)
        self._filter_arch.blockSignals(False)
        self._apply_filter(self._search_box.text())

    def _apply_filter(self, text: str = ""):
        rows = self._all_rows

        # Format dropdown filter
        fmt_filter = self._filter_fmt.currentText()
        if fmt_filter and fmt_filter != "All Formats":
            rows = [r for r in rows
                    if (r.get("format") or "").lower() == fmt_filter.lower()]

        # Archetype dropdown filter
        arch_filter = self._filter_arch.currentText().strip()
        if arch_filter and arch_filter != "All Archetypes":
            al = arch_filter.lower()
            rows = [r for r in rows
                    if al in (r.get("archetype") or "").lower()]

        # Text search across archetype, type, title, comment
        term = (text or self._search_box.text()).strip().lower()
        if term:
            rows = [r for r in rows
                    if term in (r.get("archetype") or "").lower()
                    or term in (r.get("type") or "").lower()
                    or term in (r.get("title") or "").lower()
                    or term in (r.get("comment") or "").lower()
                    or term in (r.get("source") or "").lower()]

        self._populate_table(rows)

    def _populate_table(self, rows: list[dict]):
        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            tint = _TYPE_COLOR.get((r.get("type") or "").lower(), QColor(40, 40, 52))
            origin = r.get("origin", "guide")
            # Slightly different shade for manual bookmarks
            if origin == "bookmark":
                tint = QColor(
                    min(tint.red()   + 15, 255),
                    min(tint.green() + 15, 255),
                    min(tint.blue()  + 15, 255),
                )
            arch    = r.get("archetype") or "—"
            fmt     = (r.get("format") or "—").capitalize()
            rtype   = r.get("type") or "—"
            title   = r.get("title") or r.get("comment") or "—"
            source  = r.get("source") or ("★ Bookmark" if origin == "bookmark" else "—")
            date    = (r.get("date_str") or "")[:10]
            url     = r.get("url") or ""
            tooltip = f"{arch} — {rtype}\n{url}"

            for ci, val in enumerate([arch, fmt, rtype, title, source, date]):
                item = QTableWidgetItem(val)
                item.setBackground(tint)
                item.setToolTip(tooltip)
                item.setData(Qt.ItemDataRole.UserRole, url)
                item.setData(Qt.ItemDataRole.UserRole + 1, origin)
                self._table.setItem(ri, ci, item)

        g = sum(1 for r in rows if r.get("origin") == "guide")
        b = sum(1 for r in rows if r.get("origin") == "bookmark")
        self._table_status.setText(
            f"{len(rows)} resources  ({g} scraped guides, {b} bookmarks)"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_url(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _save_bookmark(self):
        url = self._url_input.text().strip()
        if not url or not url.startswith("http"):
            self._form_status.setText("Please enter a valid URL (must start with http).")
            return

        title    = self._title_input.text().strip()
        fmt      = self._fmt_combo.currentText()
        archetype= self._arch_input.currentText().strip()
        btype    = self._type_combo.currentText()
        note     = self._note_input.toPlainText().strip()
        added_at = datetime.now().isoformat(timespec="seconds")

        def _do():
            from db.database import get_connection, init_db
            init_db()
            conn = get_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO bookmarks
                       (added_at, url, title, format, archetype, type, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (added_at, url, title, fmt, archetype, btype, note),
                )
                conn.commit()
            finally:
                conn.close()
            return True

        self._add_btn.setEnabled(False)
        w = DataLoadWorker(_do)
        w.result.connect(self._on_saved)
        w.error.connect(lambda e: (
            self._form_status.setText(f"Error: {e}"),
            self._add_btn.setEnabled(True),
        ))
        w.start()
        self._workers.append(w)

    def _on_saved(self, _):
        self._form_status.setText("Saved!")
        self._add_btn.setEnabled(True)
        # Clear form
        self._url_input.clear()
        self._title_input.clear()
        self._note_input.clear()
        QTimer.singleShot(2000, lambda: self._form_status.setText(""))
        self._load_all()

    def _delete_selected(self):
        selected = self._table.selectedItems()
        if not selected:
            return
        row = self._table.currentRow()
        url    = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        origin = self._table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1)
        if origin != "bookmark":
            self._table_status.setText("Only manual bookmarks can be deleted (guides re-sync from sheet).")
            return

        def _do():
            from db.database import get_connection
            conn = get_connection()
            try:
                conn.execute("DELETE FROM bookmarks WHERE url = ?", [url])
                conn.commit()
            finally:
                conn.close()
            return True

        w = DataLoadWorker(_do)
        w.result.connect(lambda _: self._load_all())
        w.start()
        self._workers.append(w)

    def _run_guides_scraper(self):
        self._run_scraper_btn.setEnabled(False)
        self._table_status.setText("Syncing guides from Skill Issue Magic…")

        def _do():
            from scrapers.guides import run_scraper
            run_scraper()
            return True

        w = DataLoadWorker(_do)
        w.result.connect(lambda _: (
            self._run_scraper_btn.setEnabled(True),
            self._load_all(),
        ))
        w.error.connect(lambda e: (
            self._table_status.setText(f"Sync failed: {e}"),
            self._run_scraper_btn.setEnabled(True),
        ))
        w.start()
        self._workers.append(w)
