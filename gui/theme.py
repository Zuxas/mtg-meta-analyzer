"""
Theme module — single source of truth for the GUI design system.

Modern dark theme inspired by untapped.gg, mobalytics, and Discord.
Uses Inter font family for clean, professional typography.

Call apply_theme(app) once at startup before any windows are shown.
"""
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFontDatabase, QFont

# ── Colour tokens ──────────────────────────────────────────────────────────
BG        = "#111219"   # main background — near black
PANEL     = "#1a1b27"   # card / panel surface
INPUT     = "#1f2133"   # input fields / deeper surface
ALT_ROW   = "#1e1f2d"   # alternating table row
SURFACE   = "#252639"   # elevated surface (modals, popovers)
BORDER    = "#2d2e3f"   # subtle panel border
BORDER_LO = "#242536"   # very subtle separator

ACCENT    = "#5eb5cf"   # primary cyan — softer, more refined
ACCENT2   = "#7c8da4"   # secondary — cool grey-blue
ACCENT_DK = "#3d8ba3"   # darker cyan (pressed / active states)
ACCENT_LT = "#8ad4eb"   # lighter cyan (hover glow)

TEXT      = "#e4e6ed"   # primary text — warm white
TEXT_DIM  = "#7a8194"   # secondary / labels
TEXT_OFF  = "#4a5060"   # disabled / placeholder

BTN_FG    = "#0c0d14"   # text on primary buttons
WHITE     = "#ffffff"

# Status colors
OK        = "#34d058"   # softer green
WARN      = "#f0a030"   # warm amber
ERR       = "#f04040"   # softer red

# Chart colour palette — curated, not neon
CHART_PALETTE = [
    "#5eb5cf", "#f04040", "#34d058", "#f0a030", "#a078e0",
    "#40c8e8", "#e868c8", "#b8e040", "#f0a0b8", "#50b0a0",
    "#c8a0f0", "#c09048", "#d0b888", "#e06840", "#90e8c0",
]
CHART_BG    = "#111219"
CHART_PANEL = "#1a1b27"
CHART_GRID  = "#2d2e3f"

# ── Shared timeframe selector options ──────────────────────────────────────
# (label, weeks_or_None)   None = All Time (no date filter)
TIMEFRAME_OPTIONS: list[tuple[str, int | None]] = [
    ("1 week",   1),
    ("2 weeks",  2),
    ("4 weeks",  4),
    ("8 weeks",  8),
    ("3 months", 13),
    ("6 months", 26),
    ("1 year",   52),
    ("2 years",  104),
    ("All Time", None),
]
TIMEFRAME_DEFAULT = "2 weeks"

# ── MTG mana color pips — official Wizards hex values ──────────────────────
MANA_COLORS = {
    "W": "#F9FAF4",   # white/cream
    "U": "#0E68AB",   # blue
    "B": "#150B00",   # black
    "R": "#D3202A",   # red
    "G": "#00733E",   # green
}

_GUILD_COLORS = {
    "azorius": "WU",  "dimir": "UB",   "rakdos": "BR",  "gruul": "RG",
    "selesnya": "WG", "orzhov": "WB",  "izzet": "UR",   "golgari": "BG",
    "boros": "WR",    "simic": "UG",
    "esper": "WUB",   "jeskai": "WUR", "mardu": "WBR",  "naya": "WRG",
    "bant": "WUG",    "grixis": "UBR", "sultai": "UBG", "temur": "URG",
    "jund": "BRG",    "abzan": "WBG",
    "domain": "WUBRG",
    "4c": "WUBR",     "5c": "WUBRG",
    "mono-white": "W", "mono-blue": "U", "mono-black": "B",
    "mono-red":   "R", "mono-green":  "G",
    "monowhite":  "W", "monoblue":    "U", "monoblack":   "B",
    "monored":    "R", "monogreen":   "G",
    "weenie white": "W", "white": "W", "blue": "U", "black": "B",
    "red": "R", "green": "G",
}


def color_identity(name: str) -> str:
    """Infer MTG color identity from an archetype name. Returns e.g. 'UR', 'WG'."""
    nl = name.lower()
    for kw, ci in sorted(_GUILD_COLORS.items(), key=lambda x: -len(x[0])):
        if kw in nl:
            return ci
    return ""


def make_pip_widget(identity: str):
    """
    Return a QWidget of colored circle pips for a mana identity string.
    Each pip is drawn with QPainter.drawEllipse() — the only reliable way
    to get true circles in Qt (stylesheet border-radius doesn't clip bg).
    """
    from PyQt6.QtWidgets import QWidget, QHBoxLayout
    from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
    from PyQt6.QtCore import Qt

    class _Pip(QWidget):
        def __init__(self, color_hex: str, border: bool = False, parent=None):
            super().__init__(parent)
            self._c = QColor(color_hex)
            self._b = border
            self.setFixedSize(12, 12)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self._b:
                p.setPen(QPen(QColor(180, 180, 180, 140), 1.2))
            else:
                p.setPen(QPen(QColor(50, 50, 60, 120), 0.8))
            p.setBrush(QBrush(self._c))
            p.drawEllipse(1, 1, 10, 10)
            p.end()

    w = QWidget()
    w.setStyleSheet("background: transparent;")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(4, 0, 4, 0)
    hl.setSpacing(3)
    for ch in identity:
        # Pure black (#150B00) is near-invisible on dark bg
        color = "#6a5a50" if ch == "B" else MANA_COLORS.get(ch, "#888888")
        hl.addWidget(_Pip(color, border=(ch == "W")))
    hl.addStretch()
    return w

# ── Font setup ─────────────────────────────────────────────────────────────
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def _load_fonts():
    """Register bundled fonts with Qt. Returns the heading font family name."""
    loaded_family = None
    for fname in ("Inter-Regular.ttf", "Inter-Medium.ttf",
                  "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        fpath = os.path.join(_FONTS_DIR, fname)
        if os.path.exists(fpath):
            fid = QFontDatabase.addApplicationFont(fpath)
            if fid >= 0 and loaded_family is None:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    loaded_family = families[0]

    # Also load Orbitron as a fallback / special use
    orbitron_path = os.path.join(_FONTS_DIR, "Orbitron.ttf")
    if os.path.exists(orbitron_path):
        QFontDatabase.addApplicationFont(orbitron_path)

    return loaded_family or "Segoe UI"


HEADING_FONT = None    # resolved at runtime by apply_theme()
BODY_FONT    = "Inter"

# ── Full Qt stylesheet ──────────────────────────────────────────────────────

def _build_stylesheet(heading: str) -> str:
    """Build the full application stylesheet using the resolved font family."""
    return f"""
    /* ── Global ──────────────────────────────────────────────── */
    * {{
        font-family: "{heading}", "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        color: {TEXT};
    }}
    QWidget {{
        background: {BG};
    }}

    /* ── Tab bar — modern underline style ──────────────────────── */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {BORDER};
    }}
    QTabBar {{
        background: {PANEL};
        border: none;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {TEXT_DIM};
        padding: 11px 20px;
        border: none;
        border-bottom: 2px solid transparent;
        font-family: "{heading}", "Segoe UI", sans-serif;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin: 0;
        min-width: 90px;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom: 2px solid {ACCENT};
        background: rgba(94, 181, 207, 0.06);
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT};
        background: rgba(255, 255, 255, 0.03);
    }}

    /* ── Section headers (QLabel used as section titles) ──────── */
    QLabel[class="section-header"] {{
        font-family: "{heading}", "Segoe UI", sans-serif;
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: 0.3px;
    }}

    /* ── Panels / GroupBox ────────────────────────────────────── */
    QGroupBox {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 8px;
        margin-top: 14px;
        padding: 14px 10px 10px 10px;
        color: {TEXT_DIM};
        font-family: "{heading}", "Segoe UI", sans-serif;
        font-size: 11px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 8px;
        color: {TEXT};
    }}

    /* ── Inputs ───────────────────────────────────────────────── */
    QComboBox, QSpinBox, QLineEdit, QPlainTextEdit,
    QTextBrowser, QDateEdit {{
        background: {INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 10px;
        selection-background-color: {ACCENT};
        selection-color: {BTN_FG};
    }}
    QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
    QPlainTextEdit:focus, QDateEdit:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
        border-top-right-radius: 6px;
        border-bottom-right-radius: 6px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_DIM};
        width: 0; height: 0;
    }}
    QComboBox:hover::down-arrow {{
        border-top-color: {ACCENT};
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        selection-background-color: rgba(94, 181, 207, 0.2);
        selection-color: {ACCENT_LT};
        padding: 4px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 5px 10px;
        border-radius: 4px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: rgba(94, 181, 207, 0.12);
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0; border: none;
    }}

    /* ── Scrollbars — slim, modern ────────────────────────────── */
    QScrollBar:vertical   {{ background: transparent; width:  6px; border: none; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 6px; border: none; margin: 2px; }}
    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 3px;
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {{ background: {TEXT_DIM}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* ── Table — clean, spacious ─────────────────────────────── */
    QTableWidget {{
        background: {PANEL};
        gridline-color: {BORDER_LO};
        border: 1px solid {BORDER};
        border-radius: 8px;
        alternate-background-color: {ALT_ROW};
        outline: none;
    }}
    QTableWidget::item {{
        padding: 4px 8px;
        border: none;
    }}
    QTableWidget::item:selected {{
        background: rgba(94, 181, 207, 0.15);
        color: {ACCENT_LT};
    }}
    QHeaderView::section {{
        background: {INPUT};
        color: {TEXT_DIM};
        border: none;
        border-right: 1px solid {BORDER_LO};
        border-bottom: 1px solid {BORDER};
        padding: 7px 10px;
        font-family: "{heading}", "Segoe UI", sans-serif;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }}
    QHeaderView::section:hover {{ background: {SURFACE}; color: {TEXT}; }}
    QHeaderView::section:first {{ border-top-left-radius: 8px; }}
    QHeaderView::section:last {{ border-top-right-radius: 8px; border-right: none; }}

    /* ── Progress bars ────────────────────────────────────────── */
    QProgressBar {{
        border: 1px solid {BORDER};
        border-radius: 4px;
        background: {INPUT};
        color: {TEXT};
        text-align: center;
        height: 20px;
        font-size: 11px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_DK}, stop:1 {ACCENT}
        );
        border-radius: 3px;
    }}

    /* ── Checkboxes ───────────────────────────────────────────── */
    QCheckBox {{ color: {TEXT_DIM}; spacing: 8px; }}
    QCheckBox:hover {{ color: {TEXT}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1.5px solid {BORDER};
        border-radius: 4px;
        background: {INPUT};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    /* ── Splitters ────────────────────────────────────────────── */
    QSplitter::handle:horizontal {{ background: {BORDER_LO}; width:  1px; }}
    QSplitter::handle:vertical   {{ background: {BORDER_LO}; height: 1px; }}

    /* ── Status bar ───────────────────────────────────────────── */
    QStatusBar {{
        background: {PANEL};
        color: {TEXT_DIM};
        border-top: 1px solid {BORDER};
        font-size: 11px;
        padding: 2px 8px;
    }}
    QStatusBar QLabel {{ color: {TEXT_DIM}; background: transparent; }}

    /* ── Tool tips — floating card style ──────────────────────── */
    QToolTip {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 11px;
    }}

    /* ── Labels (default) ─────────────────────────────────────── */
    QLabel {{ color: {TEXT_DIM}; background: transparent; }}

    /* ── Matplotlib nav toolbar ───────────────────────────────── */
    QToolBar {{
        background: {PANEL};
        border: none;
        border-top: 1px solid {BORDER_LO};
        spacing: 4px;
        padding: 3px 6px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        color: {TEXT_DIM};
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QToolBar QToolButton:hover {{
        background: rgba(94, 181, 207, 0.1);
        border-color: {BORDER};
        color: {ACCENT};
    }}
    QToolBar QToolButton:pressed {{ background: rgba(94, 181, 207, 0.2); }}

    /* ── Frames ───────────────────────────────────────────────── */
    QFrame[frameShape="4"] {{ color: {BORDER_LO}; }}  /* HLine */
    QFrame[frameShape="5"] {{ color: {BORDER_LO}; }}  /* VLine */

    /* ── Dialog / wizard ──────────────────────────────────────── */
    QDialog {{ background: {BG}; border-radius: 8px; }}
    QStackedWidget {{ background: {BG}; }}

    /* ── Menu (context menus) ─────────────────────────────────── */
    QMenu {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: rgba(94, 181, 207, 0.15);
        color: {ACCENT_LT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 8px;
    }}
    """


# ── Apply theme ────────────────────────────────────────────────────────────

def apply_theme(app: QApplication):
    """
    Call once at startup. Loads Inter, sets Qt palette, applies stylesheet.
    """
    global HEADING_FONT
    app.setStyle("Fusion")

    HEADING_FONT = _load_fonts()

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base,            QColor(INPUT))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(ALT_ROW))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Text,            QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_OFF))
    pal.setColor(QPalette.ColorRole.Button,          QColor(PANEL))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT))
    pal.setColor(QPalette.ColorRole.BrightText,      QColor(WHITE))
    pal.setColor(QPalette.ColorRole.Link,            QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(BTN_FG))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text,       QColor(TEXT_OFF))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, QColor(TEXT_OFF))

    app.setPalette(pal)
    app.setStyleSheet(_build_stylesheet(HEADING_FONT))

    return HEADING_FONT


def btn_primary(text: str = "") -> str:
    """Return a QPushButton stylesheet string for primary action buttons."""
    return (
        f"QPushButton {{ background: {ACCENT}; color: {BTN_FG}; border: none; "
        f"padding: 7px 20px; border-radius: 6px; font-weight: 600; "
        f"font-size: 12px; }}"
        f"QPushButton:hover {{ background: {ACCENT_LT}; }}"
        f"QPushButton:pressed {{ background: {ACCENT_DK}; }}"
        f"QPushButton:disabled {{ background: {BORDER}; color: {TEXT_OFF}; }}"
    )


def btn_secondary(text: str = "") -> str:  # noqa: ARG001
    """Return a QPushButton stylesheet for secondary / outline buttons."""
    return (
        f"QPushButton {{ background: rgba(94, 181, 207, 0.08); color: {ACCENT2}; "
        f"border: 1px solid {BORDER}; padding: 6px 16px; border-radius: 6px; "
        f"font-weight: 500; }}"
        f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; "
        f"background: rgba(94, 181, 207, 0.12); }}"
        f"QPushButton:disabled {{ color: {TEXT_OFF}; border-color: {BORDER_LO}; "
        f"background: transparent; }}"
    )


def btn_success() -> str:
    return (
        f"QPushButton {{ background: rgba(52, 208, 88, 0.12); color: {OK}; "
        f"border: 1px solid rgba(52, 208, 88, 0.3); padding: 6px 16px; "
        f"border-radius: 6px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: rgba(52, 208, 88, 0.2); "
        f"border-color: rgba(52, 208, 88, 0.5); }}"
    )


def section_header_style() -> str:
    """Stylesheet for bold section headers inside tabs."""
    return (
        f"font-family: '{HEADING_FONT}', 'Segoe UI', sans-serif; "
        f"font-size: 13px; font-weight: 600; color: {TEXT}; "
        f"letter-spacing: 0.3px;"
    )
