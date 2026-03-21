"""
First-run setup wizard — one-time UAC elevation to register Task Scheduler tasks.

Flow:
  1. is_setup_complete() checks config.ini for [setup] tasks_registered = true
  2. If not complete, run_gui.py shows FirstRunSetupDialog after MainWindow loads
  3. User clicks "Set Up Automatic Updates" → single UAC prompt
  4. register_tasks.py (or .exe --register-tasks) runs elevated, registers all tasks
  5. register_tasks.py writes the setup_complete flag on success
  6. Dialog confirms success; never shown again

Skipping: user can click "Skip" — the dialog will reappear next launch until
tasks are registered or the flag is manually set in config.ini.
"""

import os
import sys
import subprocess
import configparser

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import gui.theme as theme

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Setup state helpers
# ---------------------------------------------------------------------------

def is_setup_complete() -> bool:
    """Return True if scheduled tasks have already been registered."""
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(_ROOT, "config.ini"))
    return cfg.getboolean("setup", "tasks_registered", fallback=False)


def _launch_elevated() -> bool:
    """
    Launch the task-registration script with UAC elevation.
    Returns True if the elevated process exited with code 0.

    Frozen .exe:  re-launches self with --register-tasks
    Dev mode:     launches register_tasks.py via current Python interpreter
    """
    if getattr(sys, "frozen", False):
        # PyInstaller .exe — re-launch self elevated
        exe = sys.executable.replace("\\", "\\\\")
        ps_cmd = (
            f"$p = Start-Process '{exe}' "
            f"-ArgumentList '--register-tasks' "
            f"-Verb RunAs -Wait -PassThru; "
            f"exit $p.ExitCode"
        )
    else:
        # Dev: run register_tasks.py elevated
        script  = os.path.join(_ROOT, "register_tasks.py").replace("\\", "\\\\")
        python  = sys.executable.replace("\\", "\\\\")
        ps_cmd  = (
            f"$p = Start-Process '{python}' "
            f"-ArgumentList '\"{script}\"' "
            f"-Verb RunAs -Wait -PassThru; "
            f"exit $p.ExitCode"
        )

    result = subprocess.run(
        ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
        capture_output=True,
        text=True,
    )
    # Exit code 0 = all tasks registered; also recheck the flag file
    return result.returncode == 0 or is_setup_complete()


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class FirstRunSetupDialog(QDialog):
    """
    Shown once on first launch when scheduled tasks are not yet registered.
    One UAC prompt → all three tasks registered → never shown again.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MTG Meta Analyzer — Automatic Updates Setup")
        self.setMinimumWidth(540)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(58)
        header.setStyleSheet(
            f"background: {theme.PANEL}; border-bottom: 2px solid {theme.ACCENT};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 0, 24, 0)
        title = QLabel("Automatic Updates Setup")
        title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.ACCENT};")
        hl.addWidget(title)
        outer.addWidget(header)

        # ── Body ──────────────────────────────────────────────────────
        body = QFrame()
        body.setStyleSheet(f"background: {theme.BG};")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(32, 22, 32, 18)
        bv.setSpacing(14)

        intro = QLabel(
            "To keep your database current automatically, this app needs to register "
            "three background tasks in Windows Task Scheduler.\n\n"
            "This requires a single Administrator (UAC) prompt. After you approve it "
            "once, everything runs silently in the background — no further action needed."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        bv.addWidget(intro)

        # Task list panel
        panel = QFrame()
        panel.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 3px;"
        )
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 12, 16, 12)
        pv.setSpacing(7)

        for time_str, desc in [
            ("6:00 AM  daily  ", "Background fill — Standard, Pioneer, Modern from MTGTop8 + MTGDecks"),
            ("5:00 PM  daily  ", "Standard latest events + archive maintenance"),
            ("Sunday  midnight", "Scryfall card database refresh"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(10)
            t = QLabel(time_str)
            t.setStyleSheet(
                f"color: {theme.ACCENT}; font-weight: bold; font-size: 11px;"
            )
            t.setFixedWidth(120)
            d = QLabel(desc)
            d.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            row.addWidget(t)
            row.addWidget(d)
            row.addStretch()
            pv.addLayout(row)

        bv.addWidget(panel)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setMinimumHeight(18)
        bv.addWidget(self._status_lbl)

        outer.addWidget(body, 1)

        # ── Button bar ────────────────────────────────────────────────
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet(
            f"border-top: 1px solid {theme.BORDER_LO}; background: {theme.BG};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 10, 24, 10)
        bl.setSpacing(10)

        skip_btn = QPushButton("Skip for Now")
        skip_btn.setStyleSheet(theme.btn_secondary())
        skip_btn.clicked.connect(self.reject)
        bl.addWidget(skip_btn)

        bl.addStretch()

        self._setup_btn = QPushButton("Set Up Automatic Updates  (requires Admin)")
        self._setup_btn.setStyleSheet(theme.btn_primary())
        self._setup_btn.clicked.connect(self._run_setup)
        bl.addWidget(self._setup_btn)

        outer.addWidget(bar)

    def _run_setup(self):
        self._setup_btn.setEnabled(False)
        self._status_lbl.setText("Waiting for Windows Administrator approval...")
        self._status_lbl.setStyleSheet(f"color: {theme.ACCENT2}; font-size: 11px;")

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        ok = _launch_elevated()

        if ok:
            self._status_lbl.setText(
                "\u2705  All tasks registered. Updates will now run automatically in the background."
            )
            self._status_lbl.setStyleSheet(f"color: {theme.OK}; font-size: 11px;")
            self._setup_btn.setText("Done")
            self._setup_btn.setEnabled(True)
            self._setup_btn.clicked.disconnect()
            self._setup_btn.clicked.connect(self.accept)
        else:
            self._status_lbl.setText(
                "Setup was cancelled or failed. You can try again by closing and re-opening the app, "
                "or right-click schedule_background_fill.bat \u2192 Run as Administrator."
            )
            self._status_lbl.setStyleSheet(f"color: {theme.WARN}; font-size: 11px;")
            self._setup_btn.setText("Try Again")
            self._setup_btn.setEnabled(True)
