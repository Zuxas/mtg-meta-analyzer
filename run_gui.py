"""
MTG Meta Analyzer — GUI launcher.

Normal usage:
    python run_gui.py

Elevated task-registration mode (called internally by the first-run wizard):
    python run_gui.py --register-tasks

The --register-tasks flag must be run as Administrator. It registers all
Windows Task Scheduler tasks and exits immediately (no GUI shown).
"""
import sys
import os
import argparse

# Set matplotlib backend BEFORE any other imports that might touch matplotlib.
# analysis/charts.py sets "Agg" at import time; never import that module in GUI
# context. The GUI uses gui/widgets/chart_canvas.py instead.
import matplotlib
matplotlib.use("QtAgg")

# Ensure project root is on sys.path (needed when run as frozen .exe via PyInstaller)
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)


def _db_sanity_error() -> "str | None":
    """Return an error message if the main DB looks missing/empty, else None."""
    from db.database import DB_PATH
    try:
        if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1_000_000:
            return (
                f"Database not found or empty at {DB_PATH}.\n\n"
                "Expected the main meta database. Check config.ini [database] "
                "path, or run fill_database.bat to build a new one."
            )
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='decks'"
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return (
                f"Database at {DB_PATH} has no 'decks' table.\n\n"
                "Expected the main meta database. Check config.ini [database] "
                "path, or run fill_database.bat to build a new one."
            )
    except Exception as exc:
        return f"Database sanity check failed for {DB_PATH}:\n{exc}"
    return None


def _handle_register_tasks():
    """Run as Administrator: register all tasks and exit."""
    import register_tasks
    register_tasks.main()


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--register-tasks", action="store_true")
    args, _ = parser.parse_known_args()

    if args.register_tasks:
        _handle_register_tasks()
        return

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    # Install crash handlers BEFORE importing MainWindow so an import-time
    # error in the deep widget tree leaves a forensic log on disk.
    from gui.crash_handler import install_handlers
    install_handlers()
    from gui.single_instance import SingleInstanceLock
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("MTG Meta Analyzer")
    app.setOrganizationName("MTGMeta")

    # DB sanity guard — fail with a clear message instead of letting tabs crash
    _db_err = _db_sanity_error()
    if _db_err:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "MTG Meta Analyzer — database problem", _db_err)
        sys.exit(1)

    # Single-instance enforcement: refuse second-launch attempts
    _instance_lock = SingleInstanceLock()
    if not _instance_lock.acquire():
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "MTG Meta Analyzer already running",
            "Another instance is already running.\n\n"
            "Check the system tray (bottom-right corner of your taskbar) "
            "for the Team Resolve icon.\n\n"
            "If the existing window is unresponsive, use Ctrl+Shift+Q on "
            "it to force-quit, then wait 30 seconds before relaunching.",
        )
        sys.exit(1)

    # Application icon — shown in taskbar, title bar, alt-tab
    _icon_path = os.path.join(_root, "gui", "icons", "app.ico")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # Keep process alive when the main window is hidden (tray mode)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()

    # One-time setup wizard — shown if Task Scheduler tasks are not yet registered
    from gui.first_run_setup import is_setup_complete, FirstRunSetupDialog
    if not is_setup_complete():
        dlg = FirstRunSetupDialog(window)
        dlg.exec()

    # System tray icon (shown after wizard so status reflects current state)
    from gui.tray_icon import TrayIcon
    tray = TrayIcon(window)
    window.set_tray(tray)

    # Stop all workers cleanly before the process exits
    app.aboutToQuit.connect(window.cleanup)
    app.aboutToQuit.connect(_instance_lock.release)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
