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
from gui.state import UIState
from gui import state_keys as k

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

_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200, 300]

_COLUMNS = ["Date", "Time", "Distance", "Store", "Event", "Entry", "Format"]


# ---------------------------------------------------------------------------
# Background worker callable
# ---------------------------------------------------------------------------

def _fetch_events(zipcode: str, radius: int, event_type: str | None,
                  format_filter: str | None, date_window: str = "4w") -> list[dict]:
    """Called in DataLoadWorker background thread."""
    from scrapers.event_finder import geocode_zipcode, search_events, _format_event

    lat, lng = geocode_zipcode(zipcode)
    tags = [event_type] if event_type else None
    raw = search_events(lat, lng, radius_miles=radius, tags=tags, limit=500)

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

    results = filter_by_date_window(results, date_window)
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
        self._state_hydrated = False
        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._state_hydrated:
            return
        s = UIState.instance()

        # Zipcode
        zipcode = s.get(k.EVENT_FINDER_ZIPCODE, "")
        self._zip.blockSignals(True)
        self._zip.setText(zipcode)
        self._zip.blockSignals(False)

        # Radius (find by data value)
        radius = s.get(k.EVENT_FINDER_RADIUS, 100)
        idx = self._radius.findData(radius)
        if idx >= 0:
            self._radius.blockSignals(True)
            self._radius.setCurrentIndex(idx)
            self._radius.blockSignals(False)

        # Event type
        etype = s.get(k.EVENT_FINDER_EVENT_TYPE, "regional_championship_qualifier")
        idx = self._etype.findData(etype)
        if idx >= 0:
            self._etype.blockSignals(True)
            self._etype.setCurrentIndex(idx)
            self._etype.blockSignals(False)

        # Format
        fmt = s.get(k.EVENT_FINDER_FORMAT, "modern")
        idx = self._fmt.findData(fmt)
        if idx >= 0:
            self._fmt.blockSignals(True)
            self._fmt.setCurrentIndex(idx)
            self._fmt.blockSignals(False)

        # When
        when = s.get(k.EVENT_FINDER_DATE_WINDOW, "4w")
        idx = self._when.findData(when)
        if idx >= 0:
            self._when.blockSignals(True)
            self._when.setCurrentIndex(idx)
            self._when.blockSignals(False)

        self._state_hydrated = True

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

        # Date window
        row.addWidget(self._lbl("When"))
        self._when = QComboBox()
        for label, value in DATE_WINDOW_OPTIONS:
            self._when.addItem(label, value)
        self._when.setCurrentIndex(1)  # default Next 4 wk
        self._when.setFixedWidth(120)
        self._when.setStyleSheet(self._combo_style())
        row.addWidget(self._when)

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

        # Persist filter changes to UIState
        s = UIState.instance()
        self._zip.textEdited.connect(
            lambda txt: s.set(k.EVENT_FINDER_ZIPCODE, txt))
        self._radius.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_RADIUS, self._radius.currentData()))
        self._etype.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_EVENT_TYPE, self._etype.currentData()))
        self._fmt.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_FORMAT, self._fmt.currentData()))
        self._when.currentIndexChanged.connect(
            lambda _i: s.set(k.EVENT_FINDER_DATE_WINDOW, self._when.currentData()))

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
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Time
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Distance
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Store
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)           # Event
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Entry
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Format

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

        radius      = self._radius.currentData()
        event_type  = self._etype.currentData()
        fmt         = self._fmt.currentData()
        date_window = self._when.currentData()

        self._worker = DataLoadWorker(
            _fetch_events,
            kwargs={"zipcode": zipcode, "radius": radius,
                    "event_type": event_type, "format_filter": fmt,
                    "date_window": date_window},
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
        when_label = self._when.currentText()
        r          = self._radius.currentData()
        fmt_part   = f" ({fmt_label})" if fmt_label != "All Formats" else ""
        self._set_status(
            f"{len(events)} {type_label} event(s) within {r} mi, {when_label}{fmt_part}"
        )

    def _on_error(self, msg: str):
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._set_status(f"Error: {msg}", error=True)

    def _populate_table(self, events: list[dict]):
        from gui.widgets.table_helpers import DateItem, SortItem, SORT_ROLE
        from PyQt6.QtGui import QColor

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(events))

        # Soft navy tint for RCQ rows -- keeps the dark theme readable.
        rcq_bg = QColor(theme.ACCENT_DK)
        rcq_bg.setAlpha(60)  # subtle wash

        for row, e in enumerate(events):
            # Date column: display "Sat Jun 7", sort by "20260607".
            iso = e.get("date", "")
            display_date = iso
            if iso and len(iso) == 10:
                from datetime import date as _d
                try:
                    parts = iso.split("-")
                    d_obj = _d(int(parts[0]), int(parts[1]), int(parts[2]))
                    # Cross-platform "Mon D" with no leading zero.
                    display_date = f"{d_obj.strftime('%b')} {d_obj.day}"
                except (ValueError, IndexError):
                    display_date = iso
            weekday = e.get("weekday", "")
            if weekday:
                display_date = f"{weekday} {display_date}"
            date_sort = iso.replace("-", "") if iso else ""
            date_item = DateItem(display_date, sort_key=date_sort)

            # Time column: sortable via SortItem + 24h key.
            time_str = e.get("time_str", "")
            time_item = SortItem(time_str)
            time_item.setData(SORT_ROLE, time_sort_key(time_str))

            # Distance column: numeric sort, "25 mi" display.
            dist_mi = e.get("dist_mi", 0.0) or 0.0
            dist_item = SortItem(f"{dist_mi:.0f} mi")
            dist_item.setData(SORT_ROLE, float(dist_mi))

            # Store / Event: plain.
            store_item = QTableWidgetItem(e.get("store", "?"))
            event_item = QTableWidgetItem(e.get("title", "?"))

            # Entry: numeric sort, dollar display, "-" for missing.
            fee_str = e.get("fee", "") or ""
            if fee_str.startswith("$"):
                try:
                    fee_num = float(fee_str[1:])
                except ValueError:
                    fee_num = 0.0
                fee_display = fee_str
            else:
                fee_num = 0.0
                fee_display = "—"
            entry_item = SortItem(fee_display)
            entry_item.setData(SORT_ROLE, fee_num)

            # Format: prefer eventFormat.id, fallback to tag scan.
            fmt_id = e.get("format_id", "") or ""
            if fmt_id:
                fmt_str = fmt_id.replace("_", " ").title()
            else:
                fmt_tags = [t for t in e.get("raw_tags", [])
                            if t in ("modern", "standard", "pioneer", "legacy", "pauper",
                                     "booster_draft", "commander", "historic", "explorer")]
                fmt_str = ", ".join(t.replace("_", " ").title() for t in fmt_tags) or "—"
            fmt_item = QTableWidgetItem(fmt_str)

            cells = [date_item, time_item, dist_item, store_item,
                     event_item, entry_item, fmt_item]
            for col, item in enumerate(cells):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if "regional_championship_qualifier" in e.get("raw_tags", []):
                    item.setBackground(rcq_bg)
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
