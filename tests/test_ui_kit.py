"""Tests for the UI kit (gui/widgets/kit.py), the sidebar nav bar and the
chip-style SummaryBar. Offscreen Qt, no DB."""
import pytest

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QTabWidget, QWidget,
)


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_kit_stylesheet_is_additive_and_scoped(app):
    import gui.theme as theme
    qss = theme.kit_stylesheet("Inter")
    # every kit rule is scoped by objectName or the dynamic `kit` property
    assert "QFrame[kit=\"card\"]" in qss
    assert "#sidebarTabBar" in qss and "#rootTabs" in qss
    assert "QWidget {" not in qss and "* {" not in qss


def test_stat_card_value_and_tone(app):
    from gui.widgets.kit import StatCard
    c = StatCard("Win rate", "50%", "n=10")
    c.set_value("61%", hint="n=44", tone="win")
    assert c.value_text() == "61%"
    assert "color" in c._value.styleSheet()
    c.set_value("48%", tone="neutral")
    assert c._value.styleSheet() == ""


def test_kpi_strip_keys(app):
    from gui.widgets.kit import KpiStrip
    s = KpiStrip([("wr", "Win rate"), ("rec", "Record")])
    s.set("rec", "5-2")
    assert s.card("rec").value_text() == "5-2"
    with pytest.raises(KeyError):
        s.set("nope", "x")


def test_record_pill_tones(app):
    import gui.theme as theme
    from gui.widgets.kit import RecordPill
    p = RecordPill(5, 2)
    assert p.text() == "5-2" and theme.WIN in p.styleSheet()
    p.set_record(1, 3)
    assert theme.LOSS in p.styleSheet()
    p.set_record(2, 2, 1)
    assert p.text() == "2-2-1" and theme.TEXT_DIM in p.styleSheet()


def test_winrate_bar_paints(app):
    from gui.widgets.kit import WinRateBar
    b = WinRateBar(0.57, n=40)
    b.resize(140, 18)
    img = b.grab()
    assert not img.isNull()
    b.set_winrate(None)
    assert b.winrate() is None
    assert not b.grab().isNull()


def test_segmented_control(app):
    from gui.widgets.kit import SegmentedControl
    seg = SegmentedControl(["Standard", "Modern"], current="Modern")
    got = []
    seg.valueChanged.connect(got.append)
    assert seg.value() == "Modern"
    seg._buttons["Standard"].click()
    assert seg.value() == "Standard" and got == ["Standard"]
    seg.set_value("Modern", emit=True)
    assert got[-1] == "Modern"


def test_toast_info_shows_toast_for_short_message(app, monkeypatch):
    from gui.widgets import kit
    called = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: called.append(a))
    win = QMainWindow(); win.resize(900, 600); win.show()
    kit.toast_info(win, "Saved", "Deck saved.")
    host = kit._ToastHost.for_window(win)
    assert called == []
    assert len(host.active()) == 1
    t = host.active()[0]
    assert t.title_label.text() == "Saved"
    # positioned inside the window's bottom-right corner
    assert t.x() + t.width() <= win.width()
    assert t.y() + t.height() <= win.height()
    win.close()


def test_toast_info_falls_back_to_dialog(app, monkeypatch):
    from gui.widgets import kit
    called = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: called.append(a) or QMessageBox.StandardButton.Ok)
    hidden = QWidget()                      # never shown -> no host window
    kit.toast_info(hidden, "Info", "short")
    long_text = "x" * (kit.TOAST_MAX_CHARS + 1)
    win = QMainWindow(); win.show()
    kit.toast_info(win, "Help", long_text)  # too long for a toast
    kit.toast_info(win, "Q", "hi", QMessageBox.StandardButton.Ok)  # extra args
    assert len(called) == 3
    win.close()


def test_toast_stack_is_capped(app):
    from gui.widgets import kit
    win = QMainWindow(); win.resize(900, 700); win.show()
    for i in range(7):
        kit.toast(win, f"t{i}", "", ms=0)
    host = kit._ToastHost.for_window(win)
    # older toasts are dismissed (fading) once more than 4 are queued
    assert sum(1 for t in host.active() if not t._closing) <= 4
    win.close()


def test_sidebar_tabbar_keeps_tabwidget_api(app):
    import gui.theme as theme
    from gui.widgets.sidebar_tabbar import SidebarTabBar, install_sidebar
    tabs = QTabWidget()
    install_sidebar(tabs)
    assert tabs.objectName() == "rootTabs"
    assert tabs.tabPosition() == QTabWidget.TabPosition.West
    for label in ("DASHBOARD", "META", "MATCH LOG"):
        tabs.addTab(QWidget(), label)
    bar = tabs.tabBar()
    assert isinstance(bar, SidebarTabBar)
    assert tabs.tabText(2) == "MATCH LOG"          # path lookups unaffected
    assert bar.tabSizeHint(0).width() == theme.SIDEBAR_W
    assert SidebarTabBar.display_label("MATCH LOG") == "Match Log"
    tabs.resize(900, 500); tabs.show()
    assert not bar.grab().isNull()
    idx = bar.tabAt(bar.tabRect(1).center())
    assert idx == 1
    tabs.close()


def test_summary_bar_chips_keep_api(app):
    from gui.widgets.summary_bar import SummaryBar
    bar = SummaryBar()
    bar.update("STANDARD", ["3,843 events", "Top: Boros 12%"])
    assert bar._title.text() == "STANDARD"
    assert bar.stat_texts() == ["3,843 events", "Top: Boros 12%"]
    assert "3,843 events" in bar._stats.text()
    bar.update("MODERN", ["1 event"])
    assert bar.stat_texts() == ["1 event"]
    bar.clear()
    assert bar.stat_texts() == [] and not bar._title.isVisibleTo(bar)


def test_install_sidebar_refuses_populated_tabs(app):
    from gui.widgets.sidebar_tabbar import install_sidebar
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "X")
    with pytest.raises(RuntimeError):
        install_sidebar(tabs)


def test_bundled_fonts_are_real_font_files():
    """Regression: gui/fonts/Inter-*.ttf were saved GitHub HTML pages, so
    Inter never loaded and the app silently fell back to Segoe UI."""
    from pathlib import Path
    fonts = Path(__file__).resolve().parent.parent / "gui" / "fonts"
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf",
                 "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        head = (fonts / name).read_bytes()[:4]
        assert head in (b"\x00\x01\x00\x00", b"OTTO", b"true"), name


def test_apply_theme_resolves_inter(app):
    import gui.theme as theme
    assert theme.apply_theme(app) == "Inter"
