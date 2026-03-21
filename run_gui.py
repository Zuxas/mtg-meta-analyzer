"""
MTG Meta Analyzer — GUI launcher.

Usage:
    python run_gui.py
"""
import sys
import os

# Set matplotlib backend BEFORE any other imports that might touch matplotlib.
# analysis/charts.py sets "Agg" at import time; we never import that module
# in GUI context. The GUI uses gui/widgets/chart_canvas.py instead.
import matplotlib
matplotlib.use("QtAgg")

# Ensure project root is on sys.path (needed when run as frozen .exe via PyInstaller)
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MTG Meta Analyzer")
    app.setOrganizationName("MTGMeta")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
