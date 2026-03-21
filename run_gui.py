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
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("MTG Meta Analyzer")
    app.setOrganizationName("MTGMeta")

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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
