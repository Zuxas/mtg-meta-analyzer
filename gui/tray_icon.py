"""
System tray icon for MTG Meta Analyzer.

Shows a small M-logo icon in the Windows system tray with:
  - Status dot: green (current), yellow (updating), red (error)
  - Right-click menu: Last updated | Next run | Open App | Run Now | Exit
  - Double-click to restore window

The icon is drawn programmatically with QPainter — no external image file needed.
"""

import os
import json
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QFont
from PyQt6.QtCore import Qt, QTimer, QRect

import gui.theme as theme

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE_FILE  = os.path.join(_ROOT, "data", "scrape_state.json")

# Status constants
STATUS_IDLE    = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR   = "error"

_DOT_COLORS = {
    STATUS_IDLE:    "#3cb44b",   # green — data current
    STATUS_RUNNING: "#f58231",   # orange — update in progress
    STATUS_ERROR:   "#e6194b",   # red — last run failed
}


# ---------------------------------------------------------------------------
# Scrape state persistence
# ---------------------------------------------------------------------------

def write_scrape_state(status="ok", error=None):
    """
    Persist last-updated timestamp and status to data/scrape_state.json.
    Called by MainWindow when a background scrape finishes.
    """
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    state = {}
    try:
        with open(_STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        pass
    state["last_updated"] = datetime.now().isoformat(timespec="seconds")
    state["last_status"]  = status
    if error:
        state["last_error"] = str(error)
    elif "last_error" in state:
        del state["last_error"]
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def read_scrape_state() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _format_last_updated() -> str:
    state = read_scrape_state()
    ts = state.get("last_updated")
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts)
        # e.g. "20 Mar 6:14 AM"
        day  = dt.day
        mon  = dt.strftime("%b")
        hour = dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
        return f"{day} {mon} {hour}"
    except Exception:
        return "unknown"


def _next_run_label() -> str:
    """Return a human-readable next scheduled run time (6 AM or 5 PM)."""
    now = datetime.now()
    candidates = []
    for hour in (6, 17):
        t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        candidates.append(t)
    nxt = min(candidates)
    label = nxt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
    if nxt.date() == now.date():
        return f"today at {label}"
    return f"tomorrow at {label}"


# ---------------------------------------------------------------------------
# Icon drawing
# ---------------------------------------------------------------------------

_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")


def _make_icon(status: str) -> QIcon:
    """Load the Team Resolve logo and overlay a status dot in the corner."""
    size = 64

    # Try to use the real logo
    logo_path = os.path.join(_ICON_DIR, "icon_64.png")
    if os.path.exists(logo_path):
        pix = QPixmap(logo_path).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    else:
        # Fallback: draw "M" programmatically
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(theme.PANEL)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, size - 4, size - 4, 10, 10)
        p.setPen(QColor(theme.ACCENT))
        p.setFont(QFont("Arial", 30, QFont.Weight.Bold))
        p.drawText(QRect(0, -4, size, size), Qt.AlignmentFlag.AlignCenter, "M")
        p.end()

    # Overlay status dot — bottom-right corner
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    dot_r = 14
    dot_x = size - dot_r - 2
    dot_y = size - dot_r - 2
    dot_color = QColor(_DOT_COLORS.get(status, _DOT_COLORS[STATUS_IDLE]))

    from PyQt6.QtGui import QPen
    # Dark outline ring for visibility
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 180)))
    p.drawEllipse(dot_x - 2, dot_y - 2, dot_r + 4, dot_r + 4)

    # Dot fill
    p.setBrush(QBrush(dot_color))
    p.drawEllipse(dot_x, dot_y, dot_r, dot_r)

    p.end()
    return QIcon(pix)


# ---------------------------------------------------------------------------
# TrayIcon widget
# ---------------------------------------------------------------------------

class TrayIcon(QSystemTrayIcon):
    """
    System tray icon.  Instantiated by run_gui.py after MainWindow is shown.
    Wire status updates from MainWindow via set_status().
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent=parent or main_window)
        self._main   = main_window
        self._status = STATUS_IDLE
        self._run_now_fn = None

        self.setIcon(_make_icon(STATUS_IDLE))
        self.setToolTip("MTG Meta Analyzer")
        self._build_menu()

        self.activated.connect(self._on_activated)

        # Refresh "Last updated" / "Next run" labels every 60 s
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_labels)
        self._refresh_timer.start(60_000)

        self.show()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        menu = QMenu()

        self._last_act = menu.addAction("Last updated: —")
        self._last_act.setEnabled(False)

        self._next_act = menu.addAction(f"Next run: {_next_run_label()}")
        self._next_act.setEnabled(False)

        menu.addSeparator()

        open_act = menu.addAction("Open App")
        open_act.triggered.connect(self._open_app)

        self._run_now_act = menu.addAction("Run Now")
        self._run_now_act.triggered.connect(self._trigger_run_now)

        menu.addSeparator()

        exit_act = menu.addAction("Exit")
        exit_act.triggered.connect(self._exit)

        self.setContextMenu(menu)
        self._refresh_labels()

    def _refresh_labels(self):
        self._last_act.setText(f"Last updated: {_format_last_updated()}")
        self._next_act.setText(f"Next run: {_next_run_label()}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, status: str, tooltip: str = ""):
        """
        Update the status dot color and tooltip.
        status: STATUS_IDLE | STATUS_RUNNING | STATUS_ERROR
        """
        self._status = status
        self.setIcon(_make_icon(status))
        base = "MTG Meta Analyzer"
        if tooltip:
            self.setToolTip(f"{base} — {tooltip}")
        elif status == STATUS_RUNNING:
            self.setToolTip(f"{base} — updating...")
        elif status == STATUS_ERROR:
            self.setToolTip(f"{base} — last run had errors")
        else:
            self.setToolTip(base)
        self._refresh_labels()

    def set_run_now_callback(self, fn):
        """Register the callable triggered by 'Run Now' menu item."""
        self._run_now_fn = fn

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_app()

    def _open_app(self):
        self._main.show()
        self._main.raise_()
        self._main.activateWindow()

    def _trigger_run_now(self):
        if self._run_now_fn:
            self._run_now_fn()

    def _exit(self):
        self.hide()
        QApplication.quit()
