"""
Tab -- Event Finder

Find upcoming sanctioned MTG events (RCQs, Store Championships, etc.)
near a zipcode using the Wizards Event Locator GraphQL API.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

import gui.theme as theme
from gui.worker_threads import DataLoadWorker
from gui.worker_utils import cancel_worker

from datetime import date as _date, timedelta as _timedelta


# ---------------------------------------------------------------------------
# Pure helpers (tested separately, no Qt needed)
# ---------------------------------------------------------------------------

# Date-window choices for the "When" filter combo.
# Order matters -- used to populate the combobox.
DATE_WINDOW_OPTIONS = [
    ("Next 2 wk",    "2w"),
    ("Next 4 wk",    "4w"),
    ("Next 8 wk",    "8w"),
    ("Next 6 mo",    "6mo"),
    ("All upcoming", "all"),
]

_DATE_WINDOW_DAYS = {"2w": 14, "4w": 28, "8w": 56, "6mo": 183}


def filter_by_date_window(events: list[dict], key: str) -> list[dict]:
    """Drop events whose date falls outside the window.

    `key` is one of "2w", "4w", "8w", "6mo", "all". Unknown keys
    pass everything through (defensive). Events with empty date
    strings are kept (defensive -- they sort to the top anyway).
    """
    if key not in _DATE_WINDOW_DAYS:
        return events  # "all" or anything unrecognized
    cutoff = (_date.today() + _timedelta(days=_DATE_WINDOW_DAYS[key])).isoformat()
    return [e for e in events if not e.get("date") or e["date"] <= cutoff]


def time_sort_key(time_str: str) -> str:
    """Convert "6:00 PM" -> "18:00" for sortable keys.

    Returns "" for empty input. Returns input unchanged for malformed
    strings (defensive -- never raises).
    """
    if not time_str:
        return ""
    s = time_str.strip().upper()
    try:
        time_part, ampm = s.rsplit(" ", 1)
        h_str, m_str = time_part.split(":")
        h = int(h_str)
        m = int(m_str)
        if ampm == "AM":
            if h == 12:
                h = 0
        elif ampm == "PM":
            if h != 12:
                h += 12
        else:
            return time_str
        return f"{h:02d}:{m:02d}"
    except (ValueError, IndexError):
        return time_str


import urllib.parse as _urlparse


def google_maps_url(store: str, city: str) -> str:
    """Build a Google Maps search URL for a store + city.

    City may be empty; falls back to store-name-only. The Google
    fuzzy search resolves either form to a useful pin.
    """
    parts = [store.strip()]
    if city.strip():
        parts.append(city.strip())
    query = " ".join(parts)
    encoded = _urlparse.quote_plus(query)
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EVENT_TYPE_OPTIONS = [
    ("RCQ",              "regional_championship_qualifier"),
    ("Store Championship", "store_championship"),
    ("All Types",        None),
]

_FORMAT_OPTIONS = [
    ("All Formats", None),
    ("Modern",      "modern"),
    ("Standard",    "standard"),
    ("Pioneer",     "pioneer"),
    ("Legacy",      "legacy"),
    ("Pauper",      "pauper"),
]

_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200]

_COLUMNS = ["Date", "Distance", "Store", "Event", "Entry", "Format"]


# ---------------------------------------------------------------------------
# Background worker callable
# ---------------------------------------------------------------------------

def _fetch_events(zipcode: str, radius: int, event_type: str | None,
                  format_filter: str | None) -> list[dict]:
    """Called in DataLoadWorker background thread."""
    from scrapers.event_finder import geocode_zipcode, search_events, _format_event

    lat, lng = geocode_zipcode(zipcode)
    tags = [event_type] if event_type else None
    raw = search_events(lat, lng, radius_miles=radius, tags=tags, limit=200)

    # Apply format filter and exclude online
    results = []
    for e in raw:
        fe = _format_event(e)
        if fe["online"]:
            continue
        if format_filter:
            if format_filter.lower() not in [t.lower() for t in fe["raw_tags"]]:
                continue
        results.append(fe)

    results.sort(key=lambda x: (x["date"], x["dist_mi"]))
    return results


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class EventFinderTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._events: list[dict] = []
        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG,
                                theme.SPACE_LG, theme.SPACE_LG)
        root.setSpacing(theme.SPACE_MD)

        # Title row
        title = QLabel("Event Finder")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {theme.TEXT}; background: transparent;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "Find upcoming sanctioned events near you (RCQs, Store Championships) "
            "using the official Wizards Event Locator."
        )
        subtitle.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Search controls
        root.addWidget(self._build_controls())

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;"
        )
        root.addWidget(self._status)

        # Results table
        self._table = self._build_table()
        root.addWidget(self._table, 1)

        # Footer
        footer = QLabel("Data from locator.wizards.com. Click a row to open event page.")
        footer.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px; background: transparent;")
        root.addWidget(footer)

    def _build_controls(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; "
            "border-radius: 4px; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                               theme.SPACE_MD, theme.SPACE_SM)
        row.setSpacing(theme.SPACE_MD)

        # Zipcode
        row.addWidget(self._lbl("Zipcode"))
        self._zip = QLineEdit()
        self._zip.setPlaceholderText("e.g. 20001")
        self._zip.setFixedWidth(90)
        self._zip.setStyleSheet(self._input_style())
        self._zip.returnPressed.connect(self._search)
        row.addWidget(self._zip)

        # Radius
        row.addWidget(self._lbl("Radius"))
        self._radius = QComboBox()
        for mi in _RADIUS_OPTIONS:
            self._radius.addItem(f"{mi} mi", mi)
        self._radius.setCurrentIndex(3)  # default 100mi
        self._radius.setFixedWidth(80)
        self._radius.setStyleSheet(self._combo_style())
        row.addWidget(self._radius)

        # Event type
        row.addWidget(self._lbl("Type"))
        self._etype = QComboBox()
        for label, value in _EVENT_TYPE_OPTIONS:
            self._etype.addItem(label, value)
        self._etype.setFixedWidth(150)
        self._etype.setStyleSheet(self._combo_style())
        row.addWidget(self._etype)

        # Format
        row.addWidget(self._lbl("Format"))
        self._fmt = QComboBox()
        for label, value in _FORMAT_OPTIONS:
            self._fmt.addItem(label, value)
        self._fmt.setCurrentIndex(1)  # default Modern
        self._fmt.setFixedWidth(110)
        self._fmt.setStyleSheet(self._combo_style())
        row.addWidget(self._fmt)

        row.addStretch()

        # Search button
        self._btn = QPushButton("Find Events")
        self._btn.setFixedWidth(110)
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: #111; font-weight: 600; "
            "font-size: 12px; border-radius: 4px; padding: 6px 12px; border: none; }}"
            f"QPushButton:hover {{ background: {theme.ACCENT_LT}; }}"
            f"QPushButton:disabled {{ background: {theme.BORDER}; color: {theme.TEXT_OFF}; }}"
        )
        self._btn.clicked.connect(self._search)
        row.addWidget(self._btn)

        return frame

    def _build_table(self) -> QTableWidget:
        tbl = QTableWidget(0, len(_COLUMNS))
        tbl.setHorizontalHeaderLabels(_COLUMNS)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setAlternatingRowColors(True)
        tbl.verticalHeader().setVisible(False)
        tbl.setSortingEnabled(True)

        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Date
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Distance
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Store
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Event
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Entry
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Format

        tbl.setStyleSheet(
            f"QTableWidget {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"gridline-color: {theme.BORDER_LO}; border: 1px solid {theme.BORDER}; "
            "border-radius: 4px; font-size: 12px; }}"
            f"QTableWidget::item:alternate {{ background: #161822; }}"
            f"QTableWidget::item:selected {{ background: {theme.ACCENT_DK}; color: #fff; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; border-bottom: 1px solid {theme.BORDER}; "
            "padding: 4px 8px; font-size: 11px; font-weight: 600; }}"
        )

        tbl.cellDoubleClicked.connect(self._open_event_url)
        return tbl

    # ── Search logic ──────────────────────────────────────────────────────────

    def _search(self):
        zipcode = self._zip.text().strip()
        if not zipcode:
            self._set_status("Enter a zipcode first.", error=True)
            return

        cancel_worker(self._worker)
        self._btn.setEnabled(False)
        self._btn.setText("Searching...")
        self._table.setRowCount(0)
        self._events = []
        self._set_status(f"Geocoding {zipcode}...")

        radius     = self._radius.currentData()
        event_type = self._etype.currentData()
        fmt        = self._fmt.currentData()

        self._worker = DataLoadWorker(
            _fetch_events,
            kwargs={"zipcode": zipcode, "radius": radius,
                    "event_type": event_type, "format_filter": fmt},
        )
        self._worker.result.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_results(self, events: list[dict]):
        self._events = events
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._populate_table(events)
        type_label = self._etype.currentText()
        fmt_label  = self._fmt.currentText()
        r          = self._radius.currentData()
        self._set_status(
            f"{len(events)} {type_label} event(s) within {r} mi"
            f"{' (' + fmt_label + ')' if fmt_label != 'All Formats' else ''}"
        )

    def _on_error(self, msg: str):
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._set_status(f"Error: {msg}", error=True)

    def _populate_table(self, events: list[dict]):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(events))

        # Collect format tags for each event to show cleanly
        for row, e in enumerate(events):
            fmt_tags = [t for t in e.get("raw_tags", [])
                        if t in ("modern", "standard", "pioneer", "legacy", "pauper",
                                 "booster_draft", "commander", "historic", "explorer")]
            fmt_str = ", ".join(t.replace("_", " ").title() for t in fmt_tags) or "—"

            cells = [
                e["date"],
                f"{e['dist_mi']:.0f} mi",
                e["store"],
                e["title"],
                e["fee"] or "—",
                fmt_str,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                # Highlight RCQs in accent color
                if "regional_championship_qualifier" in e.get("raw_tags", []):
                    item.setForeground(
                        __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(theme.ACCENT_LT)
                    )
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _open_event_url(self, row: int, _col: int):
        if row < len(self._events):
            event_id = self._events[row].get("id", "")
            if event_id:
                url = f"https://locator.wizards.com/event/{event_id}"
                QDesktopServices.openUrl(QUrl(url))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, error: bool = False):
        color = "#e74c3c" if error else theme.TEXT_DIM
        self._status.setStyleSheet(
            f"color: {color}; font-size: 11px; background: transparent;"
        )
        self._status.setText(msg)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )
        return lbl

    @staticmethod
    def _input_style() -> str:
        return (
            f"QLineEdit {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 3px; "
            "padding: 4px 8px; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
        )

    @staticmethod
    def _combo_style() -> str:
        return (
            f"QComboBox {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 3px; "
            "padding: 4px 8px; font-size: 12px; }}"
            f"QComboBox:focus {{ border-color: {theme.ACCENT}; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.SURFACE}; "
            f"color: {theme.TEXT}; selection-background-color: {theme.ACCENT_DK}; }}"
        )
