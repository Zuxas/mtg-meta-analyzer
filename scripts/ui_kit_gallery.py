"""UI kit gallery -- a live preview of every kit component with the real
theme applied. Dev tool; touches no database.

    python scripts/ui_kit_gallery.py              # open a window
    python scripts/ui_kit_gallery.py --png out.png  # render offscreen to PNG
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build(win):
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QGridLayout,
        QFrame,
    )
    import gui.theme as theme
    from gui.widgets.kit import (
        KpiStrip, WinRateBar, RecordPill, SegmentedControl, toast,
    )
    from gui.widgets.sidebar_tabbar import install_sidebar
    from gui.widgets.summary_bar import SummaryBar

    tabs = QTabWidget()
    install_sidebar(tabs)

    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG)
    lay.setSpacing(theme.SPACE_MD + 2)

    head = QHBoxLayout()
    title = QLabel("Dashboard")
    title.setStyleSheet(f"font-size: {theme.FONT_XL}px; font-weight: 700;")
    head.addWidget(title)
    head.addStretch(1)
    head.addWidget(SegmentedControl(["Standard", "Modern", "Pioneer"], current="Modern"))
    head.addWidget(SegmentedControl(["2w", "4w", "3m", "All"], current="4w"))
    lay.addLayout(head)

    bar = SummaryBar()
    bar.update("MODERN", ["1,284 events", "Top share: Boros Energy 14.1%", "Updated 6:02 AM"])
    lay.addWidget(bar)

    strip = KpiStrip([("wr", "Win rate"), ("rec", "Record"), ("form", "Last 10"),
                      ("deck", "Best deck")])
    strip.set("wr", "57.4%", "116 matches, last 30 days", tone="win")
    strip.set("rec", "66-49", "games 142-110")
    strip.set("form", "7-3", "rolling", tone="accent")
    strip.set("deck", "Boros Energy", "61% over 38 matches")
    lay.addWidget(strip)

    card = QFrame()
    card.setProperty("kit", "card")
    grid = QGridLayout(card)
    grid.setContentsMargins(theme.SPACE_MD + 2, theme.SPACE_MD, theme.SPACE_MD + 2, theme.SPACE_MD)
    grid.setHorizontalSpacing(theme.SPACE_LG)
    grid.setVerticalSpacing(theme.SPACE_SM)
    hdr = QLabel("MATCHUP SPREAD")
    hdr.setProperty("kit", "card-label")
    grid.addWidget(hdr, 0, 0, 1, 3)
    rows = [("Affinity", 0.62, 21, (8, 5)), ("Broodscale", 0.55, 44, (12, 10)),
            ("Goryo's", 0.48, 25, (6, 7)), ("Eldrazi Tron", 0.41, 9, (2, 3)),
            ("Living End", 0.30, 4, (1, 2))]
    for r, (name, wr, n, (w, l)) in enumerate(rows, start=1):
        grid.addWidget(QLabel(name), r, 0)
        b = WinRateBar(wr, n)
        b.setMinimumWidth(220)
        grid.addWidget(b, r, 1)
        grid.addWidget(RecordPill(w, l), r, 2)
        nl = QLabel(f"n={n}")
        nl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_XS}px;")
        grid.addWidget(nl, r, 3)
    lay.addWidget(card)
    lay.addStretch(1)

    tabs.addTab(page, "DASHBOARD")
    for label in ("META", "DECKS", "SEARCH", "TOURNAMENT", "RESOURCES", "PUZZLES", "SETTINGS"):
        tabs.addTab(QWidget(), label)
    win.setCentralWidget(tabs)
    return lambda: toast(win, "Plans Saved", "Sideboard plan for Broodscale saved.", "success", ms=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", help="render offscreen to this PNG and exit")
    args = ap.parse_args()
    if args.png:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QMainWindow
    import gui.theme as theme

    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_theme(app)
    win = QMainWindow()
    win.setWindowTitle("UI kit gallery")
    win.resize(1280, 760)
    show_toast = build(win)
    win.show()
    show_toast()
    if args.png:
        for _ in range(5):
            app.processEvents()
        win.grab().save(args.png)
        print(f"saved {args.png}")
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
