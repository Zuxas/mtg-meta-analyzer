"""Pytest configuration. Adds project root to sys.path so tests can
import `gui.state`, `gui.widgets.palette_registry`, etc.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
