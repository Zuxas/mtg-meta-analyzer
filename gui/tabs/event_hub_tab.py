"""
gui/tabs/event_hub_tab.py -- Event Hub

Four views: Search, Calendar, My Events, My Stores.
Replaces EventFinderTab in Tournament Prep.
"""

import json
import calendar as _cal
from datetime import date, datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QStackedWidget,
    QGridLayout, QScrollArea, QFileDialog, QMessageBox,
    QTextEdit, QSizePolicy, QMenu,
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QColor, QFont, QAction

import gui.theme as theme
from gui.worker_threads import DataLoadWorker
from gui.worker_utils import cancel_worker
from db.event_hub_db import (
    ensure_tables, upsert_event_bookmark, upsert_store_bookmark,
    get_all_bookmarks, get_all_store_bookmarks,
    update_bookmark_field, remove_event_bookmark, remove_store_bookmark,
    is_bookmarked, export_ics,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_OPTIONS = [
    ("All Types",           None),
    ("RCQ",                 "regional_championship_qualifier"),
    ("Store Championship",  "store_championship"),
    ("Standard Showdown",   "standard_showdown"),
    ("Magic Presents",      "magicpresents"),
]
_FMT_OPTIONS = [
    ("All Formats", None),
    ("Modern",   "modern"),
    ("Standard", "standard"),
    ("Pioneer",  "pioneer"),
    ("Legacy",   "legacy"),
    ("Pauper",   "pauper"),
]
_RADIUS_OPTIONS = [25, 50, 75, 100, 150, 200]

_STATUS_OPTIONS = ["interested", "going", "attended"]
_STATUS_LABELS  = {"interested": "Interested", "going": "Going", "attended": "Attended"}

_CHIP_COLORS = {
    "rcq":                "#c0392b",
    "store_championship": "#2471a3",
    "standard_showdown":  "#7d3c98",
    "magicpresents":      "#1a7a4a",
    "fnm":                "#5d6d7e",
    "other":              "#4a5568",
}
_CHIP_BOOKMARK_BORDER = "#f39c12"

# Premier event colors (multi-day travel events)
_PREMIER_COLORS = {
    "pro_tour":             "#8e44ad",   # purple
    "regional_championship":"#d35400",   # orange
    "world_championship":   "#c0392b",   # red
    "magic_spotlight":      "#117a65",   # teal
}

DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# ---------------------------------------------------------------------------
# Session 2 helpers
# ---------------------------------------------------------------------------

def _estimate_drive(dist_mi) -> str:
    """Heuristic drive time: 55 mph average + 30 min overhead."""
    if not dist_mi:
        return ""
    total_min = int(dist_mi / 55 * 60 + 30)
    if total_min < 60:
        return f"~{total_min}m"
    h, m = divmod(total_min, 60)
    return f"~{h}h {m}m" if m else f"~{h}h"


def _next_rc_event() -> dict | None:
    """Return the next upcoming regional championship from the hardcoded schedule."""
    today_str = date.today().isoformat()
    rcs = [e for e in _PREMIER_EVENTS_2026
           if e.get("type") == "regional_championship" and e["start"] >= today_str]
    return min(rcs, key=lambda e: e["start"]) if rcs else None


def _days_until(date_str: str) -> int:
    return (date.fromisoformat(date_str) - date.today()).days


_PREMIER_EVENTS_2026 = [
    {"name":"SCG CON Atlanta","subtitle":"Magic Spotlight: The Avatar","type":"magic_spotlight","format":"Standard","start":"2026-01-09","end":"2026-01-11","location":"Atlanta, GA","url":"https://scgcon.starcitygames.com/"},
    {"name":"SCG CON Portland","subtitle":"Regional Championship","type":"regional_championship","format":"Standard","start":"2026-01-23","end":"2026-01-25","location":"Portland, OR","url":"https://scgcon.starcitygames.com/event/scg-con-portland-2026/"},
    {"name":"Pro Tour Lorwyn Eclipsed","subtitle":"Booster Draft + Standard","type":"pro_tour","format":"Standard/Draft","start":"2026-01-30","end":"2026-02-01","location":"Richmond, VA","url":"https://magic.gg/pro-tour"},
    {"name":"SCG CON Milwaukee","subtitle":"Regional Championship","type":"regional_championship","format":"Standard","start":"2026-02-20","end":"2026-02-22","location":"Milwaukee, WI","url":"https://scgcon.starcitygames.com/event/scg-con-milwaukee-2026/"},
    {"name":"SCG CON Richmond","subtitle":"Magic Spotlight: TMNT","type":"magic_spotlight","format":"Standard","start":"2026-03-06","end":"2026-03-08","location":"Richmond, VA","url":"https://scgcon.starcitygames.com/"},
    {"name":"Pro Tour Secrets of Strixhaven","subtitle":"Booster Draft + Standard","type":"pro_tour","format":"Standard/Draft","start":"2026-05-01","end":"2026-05-03","location":"Las Vegas, NV","url":"https://magic.gg/pro-tour"},
    {"name":"Magic Spotlight: Secrets","subtitle":"Standard Constructed","type":"magic_spotlight","format":"Standard","start":"2026-05-08","end":"2026-05-10","location":"London, England","url":"https://magic.gg/events"},
    {"name":"SCG CON Cincinnati","subtitle":"Regional Championship","type":"regional_championship","format":"Standard","start":"2026-05-15","end":"2026-05-17","location":"Cincinnati, OH","url":"https://scgcon.starcitygames.com/"},
    {"name":"SCG CON Washington DC","subtitle":"Regional Championship","type":"regional_championship","format":"Standard","start":"2026-05-29","end":"2026-05-31","location":"Washington, DC","url":"https://scgcon.starcitygames.com/"},
    {"name":"Magic Spotlight: Secrets","subtitle":"Standard Constructed","type":"magic_spotlight","format":"Standard","start":"2026-05-29","end":"2026-05-31","location":"Chiba, Japan","url":"https://magic.gg/events"},
    {"name":"SCG CON Las Vegas","subtitle":"Magic Spotlight: Marvel","type":"magic_spotlight","format":"Team Limited","start":"2026-06-26","end":"2026-06-28","location":"Las Vegas, NV","url":"https://scgcon.starcitygames.com/"},
    {"name":"Pro Tour Marvel Super Heroes","subtitle":"Booster Draft + Modern","type":"pro_tour","format":"Modern/Draft","start":"2026-07-17","end":"2026-07-19","location":"Amsterdam, Netherlands","url":"https://magic.gg/pro-tour"},
    {"name":"Magic Spotlight: Marvel","subtitle":"Team Limited","type":"magic_spotlight","format":"Team Limited","start":"2026-07-24","end":"2026-07-26","location":"Brussels, Belgium","url":"https://magic.gg/events"},
    {"name":"Magic Spotlight: The Hobbit","subtitle":"Modern Constructed","type":"magic_spotlight","format":"Modern","start":"2026-08-28","end":"2026-08-30","location":"Brisbane, Australia","url":"https://magic.gg/events"},
    {"name":"SCG CON Dallas/Fort Worth","subtitle":"Magic Spotlight: The Hobbit","type":"magic_spotlight","format":"Modern","start":"2026-09-04","end":"2026-09-06","location":"Dallas, TX","url":"https://scgcon.starcitygames.com/"},
    {"name":"SCG CON Baltimore","subtitle":"Regional Championship","type":"regional_championship","format":"TBD","start":"2026-09-11","end":"2026-09-13","location":"Baltimore, MD","url":"https://scgcon.starcitygames.com/"},
    {"name":"SCG CON Los Angeles","subtitle":"Regional Championship","type":"regional_championship","format":"TBD","start":"2026-10-09","end":"2026-10-11","location":"Los Angeles, CA","url":"https://scgcon.starcitygames.com/"},
    {"name":"SCG CON Hartford","subtitle":"Magic Spotlight: Fracture","type":"magic_spotlight","format":"Standard","start":"2026-10-23","end":"2026-10-25","location":"Hartford, CT","url":"https://scgcon.starcitygames.com/"},
    {"name":"Magic Spotlight: Fracture","subtitle":"Standard Constructed","type":"magic_spotlight","format":"Standard","start":"2026-10-31","end":"2026-11-01","location":"Beijing, China","url":"https://magic.gg/events"},
    {"name":"Magic World Championship 32","subtitle":"TBA formats","type":"world_championship","format":"TBA","start":"2026-11-13","end":"2026-11-15","location":"Atlanta, GA","url":"https://magic.gg/events"},
]


def _load_premier_events() -> list[dict]:
    """Return the hardcoded 2026 premier events schedule."""
    return _PREMIER_EVENTS_2026


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _fetch_mtgo_events() -> list[dict]:
    """Fetch and parse the official MTGO calendar ICS. Returns list of event dicts."""
    import urllib.request, re
    from datetime import datetime, timezone

    url = "https://www.mtgo.com/calendar.ics"
    req = urllib.request.Request(url, headers={"User-Agent": "mtg-meta-analyzer/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read().decode("utf-8", errors="replace")

    events = []
    current: dict = {}
    for line in data.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current.get("SUMMARY") and current.get("DTSTART"):
                events.append(current.copy())
            current = {}
        elif ":" in line:
            key, _, val = line.partition(":")
            key = key.split(";")[0]
            current[key] = val.strip()

    result = []
    local_tz = datetime.now().astimezone().tzinfo
    for e in events:
        raw_dt = e["DTSTART"].replace("Z", "")
        try:
            if "T" in raw_dt:
                utc_dt = datetime.strptime(raw_dt, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                local_dt = utc_dt.astimezone(local_tz)
                d_str = local_dt.strftime("%Y-%m-%d")
                # Windows-compatible 12-hour time (no %-I)
                t_str = local_dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
            else:
                d_str = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}"
                t_str = ""
        except Exception:
            continue

        title = e["SUMMARY"]
        uid   = e.get("UID", "")
        result.append({
            "id":         f"mtgo-{uid}",
            "title":      title,
            "date":       d_str,
            "local_time": t_str,
            "store":      "MTGO",
            "fee":        "",
            "raw_tags":   [],
            "_mtgo":      True,
        })

    return result


def _fetch_events(zipcode, radius, event_type, format_filter):
    from scrapers.event_finder import geocode_zipcode, search_events, _format_event
    lat, lng = geocode_zipcode(zipcode)
    tags = [event_type] if event_type else None
    raw  = search_events(lat, lng, radius_miles=radius, tags=tags, limit=200)
    results = []
    for e in raw:
        fe = _format_event(e)
        if fe["online"]:
            continue
        if format_filter and format_filter.lower() not in [t.lower() for t in fe["raw_tags"]]:
            continue
        results.append(fe)
    results.sort(key=lambda x: (x["date"], x["dist_mi"]))
    return results


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _btn_style(color=None, text_color="#111"):
    c = color or theme.ACCENT
    return (
        f"QPushButton {{ background: {c}; color: {text_color}; font-weight: 600; "
        "font-size: 11px; border-radius: 3px; padding: 4px 10px; border: none; }}"
        f"QPushButton:hover {{ opacity: 0.85; }}"
        f"QPushButton:disabled {{ background: {theme.BORDER}; color: {theme.TEXT_OFF}; }}"
    )

def _combo_style():
    return (
        f"QComboBox {{ background: {theme.BG}; color: {theme.TEXT}; "
        f"border: 1px solid {theme.BORDER}; border-radius: 3px; padding: 3px 8px; font-size: 11px; }}"
        f"QComboBox QAbstractItemView {{ background: {theme.SURFACE}; color: {theme.TEXT}; "
        f"selection-background-color: {theme.ACCENT_DK}; }}"
    )

def _input_style():
    return (
        f"QLineEdit {{ background: {theme.BG}; color: {theme.TEXT}; "
        f"border: 1px solid {theme.BORDER}; border-radius: 3px; padding: 3px 8px; font-size: 11px; }}"
        f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
    )

def _lbl(text, dim=False):
    l = QLabel(text)
    l.setStyleSheet(
        f"color: {theme.TEXT_DIM if dim else theme.TEXT}; "
        "font-size: 11px; font-weight: 600; background: transparent;"
    )
    return l

def _tag_display(raw_tags):
    fmt_tags = [t for t in raw_tags
                if t not in ("magic:_the_gathering",)
                and t not in ("regional_championship_qualifier", "store_championship",
                               "friday_night_magic", "new_player_event", "magic_academy",
                               "commander_party", "commander_nights", "magicpresents")]
    return ", ".join(t.replace("_", " ").title() for t in fmt_tags) or "—"


# ---------------------------------------------------------------------------
# Search View
# ---------------------------------------------------------------------------

class SearchView(QWidget):
    events_loaded = pyqtSignal(list)   # emitted when search completes
    bookmark_added = pyqtSignal()      # notify My Events / Calendar to refresh

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._events: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_SM)

        root.addWidget(self._build_controls())

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;")
        root.addWidget(self._status)

        self._table = self._build_table()
        root.addWidget(self._table, 1)

        footer = QLabel("Click a row to open event page  |  Right-click to bookmark store")
        footer.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px; background: transparent;")
        root.addWidget(footer)

    def _build_controls(self):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(theme.SPACE_MD)

        row.addWidget(_lbl("Zip", True))
        self._zip = QLineEdit()
        self._zip.setPlaceholderText("e.g. 98367")
        self._zip.setFixedWidth(80)
        self._zip.setStyleSheet(_input_style())
        self._zip.returnPressed.connect(self._search)
        row.addWidget(self._zip)

        row.addWidget(_lbl("Radius", True))
        self._radius = QComboBox()
        for mi in _RADIUS_OPTIONS:
            self._radius.addItem(f"{mi} mi", mi)
        self._radius.setCurrentIndex(3)
        self._radius.setFixedWidth(75)
        self._radius.setStyleSheet(_combo_style())
        row.addWidget(self._radius)

        row.addWidget(_lbl("Type", True))
        self._etype = QComboBox()
        for lbl, val in _TYPE_OPTIONS:
            self._etype.addItem(lbl, val)
        self._etype.setFixedWidth(145)
        self._etype.setStyleSheet(_combo_style())
        row.addWidget(self._etype)

        row.addWidget(_lbl("Format", True))
        self._fmt = QComboBox()
        for lbl, val in _FMT_OPTIONS:
            self._fmt.addItem(lbl, val)
        self._fmt.setCurrentIndex(1)
        self._fmt.setFixedWidth(100)
        self._fmt.setStyleSheet(_combo_style())
        row.addWidget(self._fmt)

        row.addStretch()

        self._btn = QPushButton("Find Events")
        self._btn.setFixedWidth(105)
        self._btn.setStyleSheet(_btn_style())
        self._btn.clicked.connect(self._search)
        row.addWidget(self._btn)

        return frame

    def _build_table(self):
        tbl = QTableWidget(0, 7)
        tbl.setHorizontalHeaderLabels(["", "Date", "Dist", "Store", "Event", "Entry", "Format"])
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setAlternatingRowColors(True)
        tbl.verticalHeader().setVisible(False)
        tbl.setSortingEnabled(True)
        tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tbl.customContextMenuRequested.connect(self._context_menu)

        h = tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)           # star
        tbl.setColumnWidth(0, 28)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        tbl.setStyleSheet(
            f"QTableWidget {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"gridline-color: {theme.BORDER_LO}; border: 1px solid {theme.BORDER}; border-radius: 4px; font-size: 12px; }}"
            f"QTableWidget::item:alternate {{ background: #161822; }}"
            f"QTableWidget::item:selected {{ background: {theme.ACCENT_DK}; color: #fff; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; border-bottom: 1px solid {theme.BORDER}; padding: 3px 6px; font-size: 11px; }}"
        )
        tbl.cellDoubleClicked.connect(self._open_url)
        return tbl

    # ── search ───────────────────────────────────────────────────────────────

    def _search(self):
        zipcode = self._zip.text().strip()
        if not zipcode:
            self._set_status("Enter a zipcode.", True)
            return
        cancel_worker(self._worker)
        self._btn.setEnabled(False)
        self._btn.setText("Searching...")
        self._table.setRowCount(0)
        self._events = []
        self._set_status(f"Geocoding {zipcode}...")
        self._worker = DataLoadWorker(
            _fetch_events,
            kwargs={"zipcode": zipcode, "radius": self._radius.currentData(),
                    "event_type": self._etype.currentData(),
                    "format_filter": self._fmt.currentData()},
        )
        self._worker.result.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_results(self, events):
        self._events = events
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._populate(events)
        self._set_status(
            f"{len(events)} event(s) — {self._etype.currentText()}"
            f"{' / ' + self._fmt.currentText() if self._fmt.currentData() else ''}"
        )
        self.events_loaded.emit(events)

    def _on_error(self, msg):
        self._btn.setEnabled(True)
        self._btn.setText("Find Events")
        self._set_status(f"Error: {msg}", True)

    def _populate(self, events):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(events))
        for row, e in enumerate(events):
            fmt_str = _tag_display(e.get("raw_tags", []))
            bookmarked = is_bookmarked(e.get("id", ""))

            # Star column
            star_btn = QPushButton("★" if bookmarked else "☆")
            star_btn.setFixedSize(24, 24)
            star_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: "
                f"{'#f39c12' if bookmarked else theme.TEXT_OFF}; "
                "border: none; font-size: 14px; padding: 0; }}"
                f"QPushButton:hover {{ color: #f39c12; }}"
            )
            star_btn.clicked.connect(lambda _, ev=e, b=star_btn: self._toggle_bookmark(ev, b))
            self._table.setCellWidget(row, 0, star_btn)

            cells = [
                None,  # star (widget)
                e["date"],
                f"{e['dist_mi']:.0f} mi",
                e["store"],
                e["title"],
                e["fee"] or "—",
                fmt_str,
            ]
            for col in range(1, 7):
                item = QTableWidgetItem(cells[col])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if "regional_championship_qualifier" in e.get("raw_tags", []):
                    item.setForeground(QColor(theme.ACCENT_LT))
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._table.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    def _toggle_bookmark(self, event: dict, btn: QPushButton):
        eid = event.get("id", "")
        if is_bookmarked(eid):
            remove_event_bookmark(eid)
            btn.setText("☆")
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT_OFF}; "
                "border: none; font-size: 14px; padding: 0; }}"
                f"QPushButton:hover {{ color: #f39c12; }}"
            )
        else:
            upsert_event_bookmark(event)
            btn.setText("★")
            btn.setStyleSheet(
                "QPushButton { background: transparent; color: #f39c12; "
                "border: none; font-size: 14px; padding: 0; }"
                "QPushButton:hover { color: #f39c12; }"
            )
            self.bookmark_added.emit()

    def _context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._events):
            return
        e = self._events[row]
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.SURFACE}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; }}"
            f"QMenu::item:selected {{ background: {theme.ACCENT_DK}; }}"
        )
        bm_action = QAction(
            "Remove Bookmark" if is_bookmarked(e.get("id", "")) else "Bookmark Event", menu
        )
        bm_action.triggered.connect(lambda: self._toggle_bookmark(
            e, self._table.cellWidget(row, 0)
        ))
        store_action = QAction("Bookmark Store", menu)
        store_action.triggered.connect(lambda: self._bookmark_store(e))
        menu.addAction(bm_action)
        menu.addSeparator()
        menu.addAction(store_action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _bookmark_store(self, event: dict):
        upsert_store_bookmark({
            "org_id":  event.get("org_id") or event.get("store", ""),
            "name":    event.get("store", "Unknown"),
            "lat":     event.get("lat"),
            "lng":     event.get("lng"),
            "dist_mi": event.get("dist_mi"),
        })
        self.bookmark_added.emit()

    def _open_url(self, row, _col):
        if row < len(self._events):
            eid = self._events[row].get("id", "")
            if eid:
                QDesktopServices.openUrl(QUrl(f"https://locator.wizards.com/event/{eid}"))

    def _set_status(self, msg, error=False):
        self._status.setStyleSheet(
            f"color: {'#e74c3c' if error else theme.TEXT_DIM}; font-size: 11px; background: transparent;"
        )
        self._status.setText(msg)

    def set_zipcode(self, zipcode: str):
        """Called when user taps 'Show Events' from My Stores."""
        self._zip.setText(zipcode)
        self._search()


# ---------------------------------------------------------------------------
# Calendar View
# ---------------------------------------------------------------------------

class DayCell(QFrame):
    def __init__(self, day_num: int, in_month: bool, parent=None):
        super().__init__(parent)
        self.day_num = day_num
        self.in_month = in_month
        self._events: list[dict] = []

        self.setFixedHeight(90)
        self.setStyleSheet(
            f"QFrame {{ background: {'#161822' if in_month else theme.BG}; "
            f"border: 1px solid {theme.BORDER_LO}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(1)

        lbl_color = theme.TEXT_DIM if in_month else theme.TEXT_OFF
        self._day_lbl = QLabel(str(day_num) if day_num else "")
        self._day_lbl.setStyleSheet(
            f"color: {lbl_color}; font-size: 10px; font-weight: 600; background: transparent;"
        )
        self._day_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._day_lbl)
        layout.addStretch()

    def add_event(self, event: dict, bookmarked: bool):
        self._events.append(event)
        layout = self.layout()
        # Remove stretch before adding chip
        item = layout.itemAt(layout.count() - 1)
        if item and item.spacerItem():
            layout.removeItem(item)

        if layout.count() - 1 >= 3:  # max 3 chips (1 day label + up to 3 chips)
            overflow = layout.itemAt(layout.count() - 1)
            if overflow and isinstance(overflow.widget(), QLabel) and "+" in overflow.widget().text():
                n = int(overflow.widget().text().strip("+").split()[0]) + 1
                overflow.widget().setText(f"+{n} more")
            else:
                lbl = QLabel("+1 more")
                lbl.setStyleSheet(
                    f"color: {theme.TEXT_OFF}; font-size: 9px; background: transparent;"
                )
                layout.addWidget(lbl)
            layout.addStretch()
            return

        raw_tags = event.get("raw_tags") or []
        evt_type = event.get("_premier_type")  # set for premier events
        if evt_type:
            chip_color = _PREMIER_COLORS.get(evt_type, "#555")
        elif "regional_championship_qualifier" in raw_tags:
            chip_color = _CHIP_COLORS["rcq"]
        elif "store_championship" in raw_tags:
            chip_color = _CHIP_COLORS["store_championship"]
        elif "standard_showdown" in raw_tags:
            chip_color = _CHIP_COLORS["standard_showdown"]
        elif "magicpresents" in raw_tags:
            chip_color = _CHIP_COLORS["magicpresents"]
        elif "friday_night_magic" in raw_tags:
            chip_color = _CHIP_COLORS["fnm"]
        elif event.get("_mtgo"):
            # MTGO events: color by competitive level
            title = event.get("title", "").lower()
            if any(k in title for k in ("qualifier", "super qualifier", "mocs", "showcase")):
                chip_color = "#0e6655"   # teal — high stakes
            elif "challenge 64" in title or "challenge 32" in title:
                chip_color = "#1a6b9a"   # blue — weekly challenge
            else:
                chip_color = "#424949"   # dark gray — preliminary/trial
        else:
            chip_color = _CHIP_COLORS["other"]

        border = f"2px solid {_CHIP_BOOKMARK_BORDER}" if bookmarked else "none"
        title = event.get("title") or event.get("name") or "?"
        subtitle = event.get("subtitle") or event.get("store") or ""
        tooltip_loc = event.get("location") or event.get("store") or ""
        chip = QLabel(title[:22])
        chip.setStyleSheet(
            f"background: {chip_color}; color: #fff; font-size: 9px; "
            f"border-radius: 2px; padding: 1px 3px; border: {border};"
        )
        chip.setToolTip(
            f"{title}\n{subtitle}\n{tooltip_loc}\n"
            + (f"Entry: {event.get('fee')}" if event.get("fee") else "")
        )
        layout.addWidget(chip)
        layout.addStretch()


class CalendarView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._today = date.today()
        self._year  = self._today.year
        self._month = self._today.month
        self._search_events: list[dict] = []
        self._premier_events: list[dict] = _load_premier_events()
        self._mtgo_events: list[dict] = []
        self._show_mtgo: bool = True
        self._selected_day: str | None = None
        self._day_events_map: dict[str, list] = {}
        self._mtgo_worker = None
        self._build_ui()
        self._refresh_mtgo()

    def cleanup(self):
        from gui.worker_utils import stop_worker
        stop_worker(self._mtgo_worker)
        self._mtgo_worker = None

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_SM)

        # Nav row
        nav = QHBoxLayout()
        self._prev_btn = QPushButton("< Prev")
        self._prev_btn.setFixedWidth(65)
        self._prev_btn.setStyleSheet(_btn_style(theme.SURFACE, theme.TEXT))
        self._prev_btn.clicked.connect(self._prev_month)
        nav.addWidget(self._prev_btn)

        self._today_btn = QPushButton("Today")
        self._today_btn.setFixedWidth(60)
        self._today_btn.setStyleSheet(_btn_style(theme.ACCENT_DK, "#fff"))
        self._today_btn.clicked.connect(self._go_today)
        nav.addWidget(self._today_btn)

        self._month_lbl = QLabel()
        self._month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._month_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        nav.addWidget(self._month_lbl, 1)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._summary_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; background: transparent;"
        )
        nav.addWidget(self._summary_lbl)

        self._next_btn = QPushButton("Next >")
        self._next_btn.setFixedWidth(65)
        self._next_btn.setStyleSheet(_btn_style(theme.SURFACE, theme.TEXT))
        self._next_btn.clicked.connect(self._next_month)
        nav.addWidget(self._next_btn)

        self._mtgo_btn = QPushButton("MTGO: ON")
        self._mtgo_btn.setFixedWidth(85)
        self._mtgo_btn.setStyleSheet(_btn_style("#1a5276", "#7fc3e8"))
        self._mtgo_btn.clicked.connect(self._toggle_mtgo)
        nav.addWidget(self._mtgo_btn)

        self._refresh_mtgo_btn = QPushButton("↻")
        self._refresh_mtgo_btn.setFixedWidth(28)
        self._refresh_mtgo_btn.setToolTip("Refresh MTGO schedule (updates every 3 hours)")
        self._refresh_mtgo_btn.setStyleSheet(_btn_style(theme.SURFACE, theme.TEXT_DIM))
        self._refresh_mtgo_btn.clicked.connect(lambda: self._refresh_mtgo(force=True))
        nav.addWidget(self._refresh_mtgo_btn)

        root.addLayout(nav)

        # Legend
        legend = QHBoxLayout()
        legend.setSpacing(theme.SPACE_SM)
        legend.addStretch()
        legend_items = [
            ("Pro Tour", _PREMIER_COLORS["pro_tour"]),
            ("Regional Champ", _PREMIER_COLORS["regional_championship"]),
            ("Worlds", _PREMIER_COLORS["world_championship"]),
            ("Spotlight", _PREMIER_COLORS["magic_spotlight"]),
            ("RCQ", _CHIP_COLORS["rcq"]),
            ("Store Champ", _CHIP_COLORS["store_championship"]),
            ("Showdown", _CHIP_COLORS["standard_showdown"]),
            ("FNM/Other", _CHIP_COLORS["fnm"]),
            ("MTGO Challenge", "#1a6b9a"),
            ("MTGO Qualifier", "#0e6655"),
        ]
        for label, color in legend_items:
            chip = QLabel(f"  {label}  ")
            chip.setStyleSheet(
                f"background: {color}; color: #fff; font-size: 9px; "
                "border-radius: 2px; padding: 1px 5px;"
            )
            legend.addWidget(chip)
        bm_chip = QLabel("  Bookmarked  ")
        bm_chip.setStyleSheet(
            f"background: {_CHIP_COLORS['fnm']}; color: #fff; font-size: 9px; "
            f"border-radius: 2px; padding: 1px 5px; border: 2px solid {_CHIP_BOOKMARK_BORDER};"
        )
        legend.addWidget(bm_chip)
        legend.addStretch()
        root.addLayout(legend)

        # Grid container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {theme.BG}; }}")
        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(1)
        self._grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._grid_widget)
        root.addWidget(scroll, 1)

        # Day detail panel (shown when a day is clicked)
        self._detail_panel = QFrame()
        self._detail_panel.setMaximumHeight(0)
        self._detail_panel.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border-top: 2px solid {theme.ACCENT}; }}"
        )
        detail_layout = QVBoxLayout(self._detail_panel)
        detail_layout.setContentsMargins(12, 8, 12, 8)
        detail_layout.setSpacing(4)
        self._detail_title = QLabel("")
        self._detail_title.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 12px; font-weight: 700; background: transparent;"
        )
        detail_layout.addWidget(self._detail_title)
        self._detail_list = QLabel("")
        self._detail_list.setWordWrap(True)
        self._detail_list.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; background: transparent;"
        )
        detail_layout.addWidget(self._detail_list)
        root.addWidget(self._detail_panel)

        self._render()

    def _render(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._month_lbl.setText(f"{_cal.month_name[self._month]} {self._year}")

        # Day headers
        for col, day_name in enumerate(DAYS_OF_WEEK):
            hdr = QLabel(day_name)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 10px; font-weight: 600; "
                f"background: {theme.SURFACE}; padding: 4px;"
            )
            hdr.setFixedHeight(22)
            self._grid.addWidget(hdr, 0, col)

        bookmarks_set: set[str] = {b["event_id"] for b in get_all_bookmarks()}
        self._day_events_map = {}

        def add_to_map(d, e):
            self._day_events_map.setdefault(d, []).append(e)

        # Search results
        for e in self._search_events:
            if e.get("date"):
                add_to_map(e["date"], e)

        # Bookmarked events
        for b in get_all_bookmarks():
            if b.get("event_date"):
                add_to_map(b["event_date"], {
                    "id": b["event_id"], "title": b["title"], "store": b["store_name"],
                    "date": b["event_date"],
                    "fee": f"${b['entry_fee_cents']//100}" if b.get("entry_fee_cents") else "",
                    "raw_tags": json.loads(b.get("format_tags") or "[]"),
                })

        # Premier events — expand date ranges
        for p in self._premier_events:
            try:
                start = date.fromisoformat(p["start"])
                end   = date.fromisoformat(p["end"])
                cur   = start
                while cur <= end:
                    d_str = cur.isoformat()
                    p_event = dict(p, date=d_str, _premier_type=p["type"])
                    add_to_map(d_str, p_event)
                    cur += timedelta(days=1)
            except Exception:
                pass

        # MTGO events from official ICS feed
        if self._show_mtgo:
            for e in self._mtgo_events:
                if e.get("date"):
                    add_to_map(e["date"], e)

        # Count notable events this month for summary
        month_str = f"{self._year:04d}-{self._month:02d}"
        rcq_count    = sum(1 for events in self._day_events_map.values()
                          for e in events if "regional_championship_qualifier" in e.get("raw_tags",[]))
        sc_count     = sum(1 for events in self._day_events_map.values()
                          for e in events if "store_championship" in e.get("raw_tags",[]))
        sd_count     = sum(1 for events in self._day_events_map.values()
                          for e in events if "standard_showdown" in e.get("raw_tags",[]))
        premier_count= sum(1 for d, events in self._day_events_map.items()
                          for e in events
                          if d.startswith(month_str) and e.get("_premier_type") and e.get("start") == d)

        parts = []
        if premier_count: parts.append(f"{premier_count} premier")
        if rcq_count:     parts.append(f"{rcq_count} RCQ")
        if sc_count:      parts.append(f"{sc_count} Store Champ")
        if sd_count:      parts.append(f"{sd_count} Showdown")
        self._summary_lbl.setText("  |  ".join(parts) if parts else "")

        # Month calendar matrix (Sun-first)
        weeks = _cal.monthcalendar(self._year, self._month)
        for week_idx, week in enumerate(weeks):
            sun_first = [week[6]] + week[:6]
            for col, day_num in enumerate(sun_first):
                in_month = day_num != 0
                cell = DayCell(day_num if in_month else 0, in_month)

                if (in_month and day_num == self._today.day
                        and self._month == self._today.month
                        and self._year == self._today.year):
                    cell.setStyleSheet(
                        f"QFrame {{ background: #1a2535; border: 2px solid {theme.ACCENT}; }}"
                    )
                    cell._day_lbl.setStyleSheet(
                        f"color: {theme.ACCENT}; font-size: 10px; font-weight: 800; background: transparent;"
                    )

                if in_month:
                    date_str = f"{self._year:04d}-{self._month:02d}-{day_num:02d}"
                    # Add premier events first (they appear at top)
                    for e in self._day_events_map.get(date_str, []):
                        if e.get("_premier_type"):
                            cell.add_event(e, False)
                    # Then local events
                    for e in self._day_events_map.get(date_str, []):
                        if not e.get("_premier_type"):
                            bookmarked = e.get("id", "") in bookmarks_set
                            cell.add_event(e, bookmarked)

                    # Click to show detail panel
                    cell.mousePressEvent = lambda ev, ds=date_str: self._show_day_detail(ds)
                    cell.setCursor(Qt.CursorShape.PointingHandCursor)

                self._grid.addWidget(cell, week_idx + 1, col)

        for col in range(7):
            self._grid.setColumnStretch(col, 1)

    def _show_day_detail(self, date_str: str):
        events = self._day_events_map.get(date_str, [])
        if not events:
            self._detail_panel.setMaximumHeight(0)
            return
        d = date.fromisoformat(date_str)
        self._detail_title.setText(
            f"{_cal.day_name[d.weekday()]}, {_cal.month_name[d.month]} {d.day}, {d.year}"
            f"  —  {len(events)} event(s)"
        )
        lines = []
        for e in events:
            if e.get("_premier_type"):
                color = _PREMIER_COLORS.get(e["_premier_type"], "#555")
                location = e.get("location", "")
                subtitle = e.get("subtitle", "")
                lines.append(
                    f'<span style="color:{color};font-weight:700">'
                    f'{e.get("name",e.get("title","?"))}</span>'
                    f' <span style="color:#aaa">— {subtitle} — {location}</span>'
                )
            elif e.get("_mtgo"):
                title = e.get("title", "?")
                time_str = e.get("local_time", "")
                t_lower = title.lower()
                if any(k in t_lower for k in ("qualifier", "mocs", "showcase")):
                    color = "#0e6655"
                elif "challenge" in t_lower:
                    color = "#1a6b9a"
                else:
                    color = "#5d6d7e"
                lines.append(
                    f'<span style="color:{color}">[MTGO] {title}</span>'
                    f'<span style="color:#888"> {time_str}</span>'
                )
            else:
                raw_tags = e.get("raw_tags", [])
                if "regional_championship_qualifier" in raw_tags:
                    color = _CHIP_COLORS["rcq"]
                elif "store_championship" in raw_tags:
                    color = _CHIP_COLORS["store_championship"]
                elif "standard_showdown" in raw_tags:
                    color = _CHIP_COLORS["standard_showdown"]
                else:
                    color = theme.TEXT_DIM
                fee = f" — {e.get('fee')}" if e.get("fee") else ""
                lines.append(
                    f'<span style="color:{color}">{e.get("title","?")}</span>'
                    f' <span style="color:#888">@ {e.get("store","?")}{fee}</span>'
                )
        self._detail_list.setText("<br>".join(lines))
        self._detail_panel.setMaximumHeight(200)

    def _go_today(self):
        self._year  = self._today.year
        self._month = self._today.month
        self._render()

    def _toggle_mtgo(self):
        self._show_mtgo = not self._show_mtgo
        self._mtgo_btn.setText(f"MTGO: {'ON' if self._show_mtgo else 'OFF'}")
        self._mtgo_btn.setStyleSheet(
            _btn_style("#1a5276" if self._show_mtgo else theme.SURFACE,
                       "#7fc3e8" if self._show_mtgo else theme.TEXT_OFF)
        )
        self._render()

    def _refresh_mtgo(self, force: bool = False):
        """Fetch MTGO calendar ICS in background."""
        if not force and self._mtgo_events:
            return  # already loaded this session
        from gui.worker_utils import stop_worker
        stop_worker(self._mtgo_worker)
        self._refresh_mtgo_btn.setEnabled(False)
        worker = DataLoadWorker(_fetch_mtgo_events)
        worker.result.connect(self._on_mtgo_loaded)
        worker.error.connect(lambda _: self._refresh_mtgo_btn.setEnabled(True))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "_mtgo_worker", None))
        worker.start()
        self._mtgo_worker = worker

    def _on_mtgo_loaded(self, events: list[dict]):
        self._mtgo_events = events
        self._refresh_mtgo_btn.setEnabled(True)
        count = len(events)
        self._mtgo_btn.setToolTip(f"{count} MTGO events loaded  (refreshes every 3h)")
        self._render()

    def load_search_events(self, events: list[dict]):
        self._search_events = events
        self._render()

    def refresh(self):
        self._premier_events = _load_premier_events()
        self._render()

    def _prev_month(self):
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self._render()

    def _next_month(self):
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self._render()


# ---------------------------------------------------------------------------
# My Events View
# ---------------------------------------------------------------------------

class MyEventsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_SM)

        # Toolbar
        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_SM)

        self._filter = QComboBox()
        for label in ["All Statuses", "Interested", "Going", "Attended"]:
            self._filter.addItem(label, label.lower() if label != "All Statuses" else None)
        self._filter.setFixedWidth(130)
        self._filter.setStyleSheet(_combo_style())
        self._filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(_lbl("Filter:", True))
        bar.addWidget(self._filter)

        bar.addStretch()

        self._export_btn = QPushButton("Export .ics")
        self._export_btn.setFixedWidth(100)
        self._export_btn.setStyleSheet(_btn_style("#27ae60", "#fff"))
        self._export_btn.clicked.connect(self._export_ics)
        bar.addWidget(self._export_btn)

        root.addLayout(bar)

        self._conflict_banner = QLabel("")
        self._conflict_banner.setWordWrap(True)
        self._conflict_banner.setStyleSheet(
            "QLabel { background: #7d3c00; color: #f0a500; font-size: 11px; "
            "font-weight: 600; padding: 4px 8px; border-radius: 3px; }"
        )
        self._conflict_banner.hide()
        root.addWidget(self._conflict_banner)

        self._table = self._build_table()
        root.addWidget(self._table, 1)

        hint = QLabel("Double-click Notes / Result / Deck to edit  |  Click status to change  |  Del key to remove  |  Right-click for Spicerack enrichment")
        hint.setStyleSheet(f"color: {theme.TEXT_OFF}; font-size: 10px; background: transparent;")
        root.addWidget(hint)

    def _build_table(self):
        cols = ["Date", "Dist", "Store", "Event", "Status", "Notes", "Result", "Deck", ""]
        tbl = QTableWidget(0, len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.setAlternatingRowColors(True)
        tbl.verticalHeader().setVisible(False)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"gridline-color: {theme.BORDER_LO}; border: 1px solid {theme.BORDER}; border-radius: 4px; font-size: 11px; }}"
            f"QTableWidget::item:alternate {{ background: #161822; }}"
            f"QTableWidget::item:selected {{ background: {theme.ACCENT_DK}; color: #fff; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; border-bottom: 1px solid {theme.BORDER}; padding: 3px 6px; font-size: 10px; }}"
        )

        h = tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(4, 100)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(8, 28)

        tbl.itemChanged.connect(self._on_item_changed)
        tbl.keyPressEvent = self._key_press
        tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tbl.customContextMenuRequested.connect(self._show_context_menu)
        return tbl

    def refresh(self):
        bookmarks = get_all_bookmarks()

        # Conflict detection: find date collisions among active events
        active = [b for b in bookmarks if b["status"] in ("interested", "going")]
        date_map: dict[str, list[str]] = {}
        for b in active:
            d = b.get("event_date") or ""
            if d:
                date_map.setdefault(d, []).append(b.get("title") or "event")
        conflicts = {d: titles for d, titles in date_map.items() if len(titles) > 1}
        if conflicts:
            lines = [f"{d}: {', '.join(ts)}" for d, ts in sorted(conflicts.items())]
            self._conflict_banner.setText("Date conflicts: " + "  |  ".join(lines))
            self._conflict_banner.show()
        else:
            self._conflict_banner.hide()

        status_filter = self._filter.currentData()
        if status_filter:
            bookmarks = [b for b in bookmarks if b["status"] == status_filter]

        self._table.blockSignals(True)
        self._table.setRowCount(len(bookmarks))
        self._bm_data = bookmarks

        for row, b in enumerate(bookmarks):
            fee_str = f"${b['entry_fee_cents']//100}" if b.get("entry_fee_cents") else "—"
            tags = json.loads(b.get("format_tags") or "[]")
            fmt_str = _tag_display(tags)

            # Fixed columns
            dist_mi = b.get("dist_mi")
            drive_str = _estimate_drive(dist_mi)
            dist_display = f"{dist_mi:.0f} mi" if dist_mi else "—"
            for col, (text, tip) in enumerate([
                (b.get("event_date") or "—", ""),
                (dist_display, drive_str),
                (b.get("store_name") or "—", ""),
                (b.get("title") or "—", ""),
            ]):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if tip:
                    item.setToolTip(tip)
                self._table.setItem(row, col, item)

            # Status dropdown
            status_cb = QComboBox()
            status_cb.addItems([_STATUS_LABELS[s] for s in _STATUS_OPTIONS])
            status_cb.setCurrentText(_STATUS_LABELS.get(b["status"], "Interested"))
            status_cb.setStyleSheet(_combo_style())
            status_cb.currentTextChanged.connect(
                lambda txt, eid=b["event_id"]: update_bookmark_field(
                    eid, "status", {v: k for k, v in _STATUS_LABELS.items()}.get(txt, "interested")
                )
            )
            self._table.setCellWidget(row, 4, status_cb)

            # Editable columns: Notes, Result, Deck
            for col, key in [(5, "personal_notes"), (6, "result"), (7, "deck_played")]:
                item = QTableWidgetItem(b.get(key) or "")
                item.setData(Qt.ItemDataRole.UserRole, (b["event_id"], key))
                self._table.setItem(row, col, item)

            # Remove button
            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT_OFF}; "
                "border: none; font-size: 12px; }}"
                "QPushButton:hover { color: #e74c3c; }"
            )
            del_btn.clicked.connect(lambda _, eid=b["event_id"]: self._remove(eid))
            self._table.setCellWidget(row, 8, del_btn)

        self._table.blockSignals(False)

    def _show_context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._bm_data):
            return
        b = self._bm_data[row]
        event_date = b.get("event_date") or ""
        today_str = date.today().isoformat()

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.SURFACE}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; font-size: 11px; }}"
            f"QMenu::item:selected {{ background: {theme.ACCENT_DK}; }}"
        )

        if event_date and event_date < today_str:
            enrich_act = QAction("Pull Spicerack Top 8", self)
            enrich_act.triggered.connect(lambda: self._spicerack_enrich(b))
            menu.addAction(enrich_act)

        open_act = QAction("Open Event URL", self)
        open_act.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(b.get("event_url") or ""))
            if b.get("event_url") else None
        )
        open_act.setEnabled(bool(b.get("event_url")))
        menu.addAction(open_act)

        if not menu.isEmpty():
            menu.exec(self._table.viewport().mapToGlobal(pos))

    def _spicerack_enrich(self, b: dict):
        """Fetch Spicerack top 8 for a past event and offer to save to notes."""
        event_date = b.get("event_date") or ""
        tags = json.loads(b.get("format_tags") or "[]")
        fmt = next((t for t in tags if t in ("modern", "standard", "pioneer", "legacy")), "standard")

        try:
            from scrapers.spicerack_scraper import fetch_tournaments
        except ImportError:
            QMessageBox.warning(self, "Spicerack", "Spicerack scraper not available.")
            return

        QMessageBox.information(self, "Fetching...",
            f"Fetching Spicerack {fmt.title()} results near {event_date}.\nThis may take a few seconds.")

        try:
            tournaments = fetch_tournaments(fmt, num_days=60)
        except Exception as e:
            QMessageBox.warning(self, "Spicerack Error", str(e))
            return

        # Match tournament by date proximity (within 3 days)
        target = date.fromisoformat(event_date)
        nearby = []
        for t in tournaments:
            t_date_str = (t.get("date") or t.get("start_date") or "")[:10]
            if not t_date_str:
                continue
            try:
                delta = abs((date.fromisoformat(t_date_str) - target).days)
                if delta <= 3:
                    nearby.append((delta, t))
            except Exception:
                continue

        if not nearby:
            QMessageBox.information(self, "Spicerack",
                f"No {fmt.title()} events found near {event_date} on Spicerack.")
            return

        nearby.sort(key=lambda x: x[0])
        best = nearby[0][1]
        name = best.get("name") or best.get("tournament_name") or "Event"
        players = best.get("players") or "?"
        top_entries = best.get("top8") or best.get("standings") or []

        lines = [f"{name}  ({players} players)  —  {fmt.title()}"]
        if top_entries:
            for i, e in enumerate(top_entries[:8], 1):
                player = e.get("player") or e.get("name") or "?"
                deck = e.get("deck") or e.get("archetype") or "?"
                lines.append(f"  {i}. {player} — {deck}")
        else:
            lines.append("  (No top-8 breakdown available)")

        result_text = "\n".join(lines)

        reply = QMessageBox.question(
            self, "Spicerack Results",
            result_text + "\n\nSave to event notes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            update_bookmark_field(b["event_id"], "personal_notes", result_text)
            self.refresh()

    def _on_item_changed(self, item: QTableWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            event_id, field = data
            update_bookmark_field(event_id, field, item.text())

    def _remove(self, event_id: str):
        remove_event_bookmark(event_id)
        self.refresh()

    def _key_press(self, event):
        if event.key() == Qt.Key.Key_Delete:
            row = self._table.currentRow()
            if 0 <= row < len(self._bm_data):
                self._remove(self._bm_data[row]["event_id"])
        else:
            QTableWidget.keyPressEvent(self._table, event)

    def _export_ics(self):
        bookmarks = get_all_bookmarks()
        going = [b for b in bookmarks if b["status"] in ("going", "interested")]
        if not going:
            QMessageBox.information(self, "No Events", "No Going or Interested events to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Calendar", "mtg_events.ics", "iCalendar Files (*.ics)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(export_ics(going))
            QMessageBox.information(self, "Exported",
                f"Exported {len(going)} event(s) to {path}\n\n"
                "Open the file to import into Google Calendar, Outlook, or Apple Calendar.")


# ---------------------------------------------------------------------------
# My Stores View
# ---------------------------------------------------------------------------

class MyStoresView(QWidget):
    show_store_events = pyqtSignal(str)   # store name, triggers search in Search view

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_SM)

        hint = QLabel(
            "Bookmark stores from the Search view (right-click a row). "
            "Click 'Show Events' to filter the search to that store."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;")
        root.addWidget(hint)

        cols = ["Store", "Distance", "Notes", "Added", ""]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {theme.BG}; color: {theme.TEXT}; "
            f"gridline-color: {theme.BORDER_LO}; border: 1px solid {theme.BORDER}; border-radius: 4px; font-size: 12px; }}"
            f"QTableWidget::item:alternate {{ background: #161822; }}"
            f"QTableWidget::item:selected {{ background: {theme.ACCENT_DK}; color: #fff; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE}; color: {theme.TEXT_DIM}; "
            f"border: none; border-bottom: 1px solid {theme.BORDER}; padding: 3px 6px; font-size: 11px; }}"
        )

        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 110)

        self._table.itemChanged.connect(self._on_notes_changed)
        root.addWidget(self._table, 1)

    def refresh(self):
        stores = get_all_store_bookmarks()
        self._stores = stores

        self._table.blockSignals(True)
        self._table.setRowCount(len(stores))
        for row, s in enumerate(stores):
            for col, text in enumerate([
                s["name"],
                f"{s['dist_mi']:.0f} mi" if s.get("dist_mi") else "—",
            ]):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

            notes_item = QTableWidgetItem(s.get("notes") or "")
            notes_item.setData(Qt.ItemDataRole.UserRole, s["org_id"])
            self._table.setItem(row, 2, notes_item)

            date_item = QTableWidgetItem((s.get("added_at") or "")[:10])
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 3, date_item)

            # Show Events button
            show_btn = QPushButton("Show Events")
            show_btn.setFixedHeight(22)
            show_btn.setStyleSheet(_btn_style(theme.ACCENT_DK, "#fff"))
            show_btn.clicked.connect(
                lambda _, name=s["name"]: self.show_store_events.emit(name)
            )
            self._table.setCellWidget(row, 4, show_btn)

        self._table.blockSignals(False)

    def _on_notes_changed(self, item: QTableWidgetItem):
        org_id = item.data(Qt.ItemDataRole.UserRole)
        if org_id:
            with __import__("db.database", fromlist=["get_connection"]).get_connection() as conn:
                conn.execute(
                    "UPDATE store_bookmarks SET notes=? WHERE org_id=?",
                    (item.text(), org_id)
                )


# ---------------------------------------------------------------------------
# Event Hub Tab (main container)
# ---------------------------------------------------------------------------

class EventHubTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        ensure_tables()
        self._build_ui()

    def cleanup(self):
        for view in (self._calendar_view, self._search_view):
            if hasattr(view, "cleanup"):
                view.cleanup()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                theme.SPACE_MD, theme.SPACE_MD)
        root.setSpacing(theme.SPACE_SM)

        # Title + RC countdown
        title_row = QHBoxLayout()
        title = QLabel("Event Hub")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {theme.TEXT}; background: transparent;"
        )
        title_row.addWidget(title)
        title_row.addStretch()

        rc = _next_rc_event()
        if rc:
            days = _days_until(rc["start"])
            if days >= 0:
                urgency = "#e74c3c" if days <= 7 else ("#f39c12" if days <= 21 else theme.ACCENT)
                rc_lbl = QLabel(
                    f"RC {rc['location'].split(',')[0].strip()}: "
                    f"{'TODAY' if days == 0 else f'{days}d'}"
                )
                rc_lbl.setStyleSheet(
                    f"color: {urgency}; font-size: 11px; font-weight: 700; "
                    "background: transparent; padding: 2px 8px;"
                )
                rc_lbl.setToolTip(
                    f"{rc['name']}  |  {rc['start']} → {rc['end']}  |  {rc['location']}"
                )
                title_row.addWidget(rc_lbl)

        root.addLayout(title_row)

        # View selector
        nav_frame = QFrame()
        nav_frame.setFixedHeight(34)
        nav_frame.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 4px; }}"
        )
        nav = QHBoxLayout(nav_frame)
        nav.setContentsMargins(4, 2, 4, 2)
        nav.setSpacing(2)

        self._nav_btns: list[QPushButton] = []
        for i, label in enumerate(["Search", "Calendar", "My Events", "My Stores"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, idx=i: self._switch(idx))
            self._nav_btns.append(btn)
            nav.addWidget(btn)
        nav.addStretch()
        root.addWidget(nav_frame)

        # Views
        self._stack = QStackedWidget()
        self._search_view   = SearchView()
        self._calendar_view = CalendarView()
        self._my_events     = MyEventsView()
        self._my_stores     = MyStoresView()

        for view in [self._search_view, self._calendar_view,
                     self._my_events, self._my_stores]:
            self._stack.addWidget(view)

        root.addWidget(self._stack, 1)

        # Wire signals
        self._search_view.events_loaded.connect(self._calendar_view.load_search_events)
        self._search_view.bookmark_added.connect(self._on_bookmark_changed)
        self._my_stores.show_store_events.connect(self._on_show_store_events)

        self._switch(0)

    def _switch(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            active = i == idx
            btn.setChecked(active)
            btn.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT_DK if active else 'transparent'}; "
                f"color: {'#fff' if active else theme.TEXT_DIM}; "
                "border: none; border-radius: 3px; font-size: 11px; "
                "font-weight: 600; padding: 3px 12px; }}"
                f"QPushButton:hover {{ background: {theme.ACCENT_DK}; color: #fff; }}"
            )
        # Refresh data-driven views on switch
        if idx == 2:
            self._my_events.refresh()
        elif idx == 3:
            self._my_stores.refresh()
        elif idx == 1:
            self._calendar_view.refresh()

    def _on_bookmark_changed(self):
        self._calendar_view.refresh()
        if self._stack.currentIndex() == 2:
            self._my_events.refresh()
        if self._stack.currentIndex() == 3:
            self._my_stores.refresh()

    def _on_show_store_events(self, store_name: str):
        """My Stores -> Show Events: switch to Search, filter by store name."""
        self._switch(0)
        # Pre-populate a note — full store filtering would need store org search
        self._search_view._status.setText(
            f"Showing search results — search near this store's zip to find their events."
        )
