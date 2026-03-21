"""
Deck export utilities.

Supported formats:
  - MTGO          — "4 Lightning Bolt" + "Sideboard" separator (.txt)
  - MTGA          — "Deck" header + "4 Lightning Bolt" + "Sideboard" (.txt)
  - decklist.org  — opens the official tournament registration sheet in browser

All file exports land in  <project_root>/exports/
and the folder is opened in Explorer after a successful save.
"""
import os
from datetime import datetime
from urllib.parse import quote

from PyQt6.QtWidgets import QMenu, QMessageBox
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtCore import QUrl


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _exports_dir() -> str:
    here = os.path.dirname(__file__)                          # gui/widgets/
    root = os.path.normpath(os.path.join(here, "..", ".."))  # project root
    d = os.path.join(root, "exports")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _normalise(entries) -> dict:
    """
    Accept either:
      - {card_name: qty}          (from deck analyzer parse)
      - [{name, avg_qty, ...}]    (from archetype detail avg deck)
    Returns {card_name: int_qty}.
    """
    if isinstance(entries, dict):
        return dict(entries)
    return {e["name"]: max(1, round(e["avg_qty"])) for e in entries}


# ---------------------------------------------------------------------------
# MTGO export
# ---------------------------------------------------------------------------

def export_mtgo(mainboard, sideboard, archetype: str, format_name: str) -> str:
    """Export in MTGO format and return the saved file path."""
    main = _normalise(mainboard)
    side = _normalise(sideboard)

    lines = [f"{qty} {name}" for name, qty in sorted(main.items())]
    if side:
        lines += ["", "Sideboard"]
        lines += [f"{qty} {name}" for name, qty in sorted(side.items())]

    path = os.path.join(_exports_dir(),
                        f"{_safe_name(archetype)}_{_stamp()}_MTGO.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# MTGA export
# ---------------------------------------------------------------------------

def export_mtga(mainboard, sideboard, archetype: str, format_name: str) -> str:
    """Export in MTG Arena format and return the saved file path."""
    main = _normalise(mainboard)
    side = _normalise(sideboard)

    lines = ["Deck"]
    lines += [f"{qty} {name}" for name, qty in sorted(main.items())]
    if side:
        lines += ["", "Sideboard"]
        lines += [f"{qty} {name}" for name, qty in sorted(side.items())]

    path = os.path.join(_exports_dir(),
                        f"{_safe_name(archetype)}_{_stamp()}_MTGA.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# decklist.org registration sheet
# ---------------------------------------------------------------------------

_FORMAT_MAP = {
    "standard": "Standard",
    "pioneer":  "Pioneer",
    "modern":   "Modern",
    "legacy":   "Legacy",
    "vintage":  "Vintage",
    "pauper":   "Pauper",
}


def open_decklist_org(mainboard, sideboard, archetype: str, format_name: str):
    """
    Open decklist.org in the default browser with the deck pre-loaded.
    The site generates a printable tournament registration sheet.
    URL format: deckmain=4%20Lightning%20Bolt%0A...&deckside=...&eventformat=Standard
    """
    main = _normalise(mainboard)
    side = _normalise(sideboard)

    def _encode(cards: dict) -> str:
        lines = [f"{qty} {name}" for name, qty in sorted(cards.items())]
        return quote("\n".join(lines), safe="")

    fmt_param = _FORMAT_MAP.get(format_name.lower(), "Standard")
    url = (
        "https://decklist.org/?"
        f"deckmain={_encode(main)}"
        f"&deckside={_encode(side)}"
        f"&eventformat={fmt_param}"
    )
    QDesktopServices.openUrl(QUrl(url))


# ---------------------------------------------------------------------------
# Shared menu helper — called from a QPushButton
# ---------------------------------------------------------------------------

def show_export_menu(btn_widget, mainboard, sideboard,
                     archetype: str, format_name: str, deck_count: int = 0):
    """
    Pop a small menu under btn_widget with export options.
    btn_widget should be the QPushButton that was clicked.
    """
    import gui.theme as theme

    menu = QMenu(btn_widget)
    menu.setStyleSheet(
        f"QMenu {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; }}"
        f"QMenu::item {{ color: {theme.TEXT}; padding: 6px 20px; }}"
        f"QMenu::item:selected {{ background: {theme.ACCENT_DK}; }}"
    )

    act_mtgo  = QAction("MTGO Format  (.txt)", menu)
    act_mtga  = QAction("MTGA Format  (.txt)", menu)
    act_sheet = QAction("Tournament Sheet  (decklist.org)", menu)

    menu.addAction(act_mtgo)
    menu.addAction(act_mtga)
    menu.addSeparator()
    menu.addAction(act_sheet)

    def _save(export_fn, *args):
        try:
            path = export_fn(*args)
            QMessageBox.information(
                btn_widget, "Export Complete",
                f"Saved to:\n{path}"
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        except Exception as exc:
            QMessageBox.critical(btn_widget, "Export Error", str(exc))

    act_mtgo.triggered.connect(
        lambda: _save(export_mtgo, mainboard, sideboard, archetype, format_name))
    act_mtga.triggered.connect(
        lambda: _save(export_mtga, mainboard, sideboard, archetype, format_name))
    act_sheet.triggered.connect(
        lambda: open_decklist_org(mainboard, sideboard, archetype, format_name))

    menu.exec(btn_widget.mapToGlobal(btn_widget.rect().bottomLeft()))
