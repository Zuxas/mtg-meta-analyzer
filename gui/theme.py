"""
Theme module — single source of truth for the GUI design system.

Colours extracted from the user's personal website CSS:
  #3b3c4d  body/window background
  #39465c  nav / panel background
  #65bcd5  h1 / primary accent (cyan)
  #6c8c94  h2 / secondary accent (muted teal)
  #f0f0f0  body text
  'pirulen' heading font → shipped as Orbitron (closest freely-available match)
  Arial    body font

Call apply_theme(app) once at startup before any windows are shown.
"""
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFontDatabase, QFont

# ── Colour tokens ──────────────────────────────────────────────────────────
BG        = "#3b3c4d"   # window / body background
PANEL     = "#39465c"   # nav / panel / sidebar
INPUT     = "#2e3848"   # input fields (darker than panel)
ALT_ROW   = "#344052"   # alternating table row
BORDER    = "#4a5a6e"   # subtle panel border
BORDER_LO = "#3a4a5c"   # very subtle separator

ACCENT    = "#65bcd5"   # h1 / primary cyan
ACCENT2   = "#6c8c94"   # h2 / secondary muted teal
ACCENT_DK = "#4a8fa0"   # darker cyan (pressed states)

TEXT      = "#f0f0f0"   # body text
TEXT_DIM  = "#8a9aaa"   # secondary / placeholder text
TEXT_OFF  = "#5a7080"   # very dim text (disabled labels)

BTN_FG    = "#0a0e14"   # text on primary cyan buttons
WHITE     = "#ffffff"

# Status colors (kept for blunder/prediction coloring)
OK        = "#3cb44b"
WARN      = "#f58231"
ERR       = "#e6194b"

# Chart colour palette — cyan first to match accent
CHART_PALETTE = [
    "#65bcd5", "#e6194b", "#3cb44b", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#d4a96a", "#e05a2b", "#aaffc3",
]
CHART_BG    = "#3b3c4d"
CHART_PANEL = "#39465c"
CHART_GRID  = "#4a5a6e"

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
    Uses QFrame + WA_StyledBackground so border-radius clips the background
    into a proper circle (QLabel alone doesn't clip its background in Qt).
    Import lazily so theme.py stays importable before QApplication exists.
    """
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame
    from PyQt6.QtCore import Qt
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(4, 0, 4, 0)
    hl.setSpacing(2)
    for ch in identity:
        # Black (#150B00) is near-invisible on dark bg — use dark charcoal
        color = "#6a5a50" if ch == "B" else MANA_COLORS.get(ch, "#888888")
        pip = QFrame()
        pip.setFixedSize(11, 11)
        pip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        border = "border: 1px solid rgba(220,220,220,0.5);" if ch == "W" else ""
        pip.setStyleSheet(f"background: {color}; border-radius: 5px; {border}")
        hl.addWidget(pip)
    hl.addStretch()
    return w

# ── Font setup ─────────────────────────────────────────────────────────────
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def _load_fonts():
    """Register bundled fonts with Qt. Returns the heading font family name."""
    orbitron_path = os.path.join(_FONTS_DIR, "Orbitron.ttf")
    if os.path.exists(orbitron_path):
        fid = QFontDatabase.addApplicationFont(orbitron_path)
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                return families[0]   # "Orbitron"
    return "Arial"                   # safe fallback

HEADING_FONT = None    # resolved at runtime by apply_theme()
BODY_FONT    = "Arial"

# ── Full Qt stylesheet ──────────────────────────────────────────────────────

def _build_stylesheet(heading: str) -> str:
    """Build the full application stylesheet using the resolved heading font."""
    return f"""
    /* ── Global ──────────────────────────────────────────────── */
    * {{
        font-family: "Arial", sans-serif;
        font-size: 12px;
        color: {TEXT};
    }}
    QWidget {{
        background: {BG};
    }}

    /* ── Tab bar — website navbar style ──────────────────────── */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {BORDER_LO};
    }}
    QTabBar {{
        background: {PANEL};
        border-bottom: 2px solid {ACCENT};
    }}
    QTabBar::tab {{
        background: {PANEL};
        color: {TEXT_DIM};
        padding: 10px 24px;
        border: none;
        border-bottom: 2px solid transparent;
        font-family: "{heading}", "Arial", sans-serif;
        font-size: 11px;
        letter-spacing: 1px;
        font-weight: bold;
        margin-right: 1px;
        min-width: 110px;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom: 2px solid {ACCENT};
        background: {BG};
    }}
    QTabBar::tab:hover:!selected {{
        color: {ACCENT2};
        background: #3a4558;
    }}

    /* ── Section headers (QLabel used as section titles) ──────── */
    QLabel[class="section-header"] {{
        font-family: "{heading}", "Arial", sans-serif;
        font-size: 13px;
        font-weight: bold;
        color: {ACCENT};
        letter-spacing: 1px;
    }}

    /* ── Panels / GroupBox ────────────────────────────────────── */
    QGroupBox {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 3px;
        margin-top: 12px;
        padding-top: 12px;
        color: {ACCENT2};
        font-family: "{heading}", "Arial", sans-serif;
        font-size: 10px;
        letter-spacing: 1px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {ACCENT};
    }}

    /* ── Inputs ───────────────────────────────────────────────── */
    QComboBox, QSpinBox, QLineEdit, QPlainTextEdit,
    QTextBrowser, QDateEdit {{
        background: {INPUT};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 2px;
        padding: 3px 7px;
        selection-background-color: {ACCENT};
        selection-color: {BTN_FG};
    }}
    QComboBox:focus, QSpinBox:focus, QLineEdit:focus,
    QPlainTextEdit:focus, QDateEdit:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {ACCENT};
        width: 0; height: 0;
    }}
    QComboBox QAbstractItemView {{
        background: {PANEL};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        selection-color: {BTN_FG};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0; border: none;
    }}

    /* ── Scrollbars ───────────────────────────────────────────── */
    QScrollBar:vertical   {{ background: {BG}; width:  8px; border: none; }}
    QScrollBar:horizontal {{ background: {BG}; height: 8px; border: none; }}
    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {{
        background: {BORDER};
        border-radius: 4px;
        min-length: 20px;
    }}
    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {{ background: {ACCENT2}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* ── Table — website table style ─────────────────────────── */
    QTableWidget {{
        background: {PANEL};
        gridline-color: {BORDER_LO};
        border: 1px solid {BORDER};
        alternate-background-color: {ALT_ROW};
    }}
    QTableWidget::item {{
        padding: 3px 6px;
    }}
    QTableWidget::item:selected {{
        background: {ACCENT_DK};
        color: {WHITE};
    }}
    QHeaderView::section {{
        background: #2e3848;
        color: {ACCENT};
        border: none;
        border-right: 1px solid {BORDER_LO};
        border-bottom: 1px solid {ACCENT};
        padding: 5px 8px;
        font-family: "{heading}", "Arial", sans-serif;
        font-size: 10px;
        font-weight: bold;
        letter-spacing: 1px;
    }}
    QHeaderView::section:hover {{ background: #39465c; }}

    /* ── Progress bars ────────────────────────────────────────── */
    QProgressBar {{
        border: 1px solid {BORDER};
        border-radius: 2px;
        background: {INPUT};
        color: {ACCENT};
        text-align: center;
        height: 18px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_DK}, stop:1 {ACCENT}
        );
        border-radius: 1px;
    }}

    /* ── Checkboxes ───────────────────────────────────────────── */
    QCheckBox {{ color: {TEXT_DIM}; spacing: 6px; }}
    QCheckBox::indicator {{
        width: 13px; height: 13px;
        border: 1px solid {BORDER};
        border-radius: 2px;
        background: {INPUT};
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
        border-top: 1px solid {BORDER_LO};
        font-size: 11px;
    }}
    QStatusBar QLabel {{ color: {TEXT_DIM}; background: transparent; }}

    /* ── Tool tips ────────────────────────────────────────────── */
    QToolTip {{
        background: {PANEL};
        color: {TEXT};
        border: 1px solid {ACCENT};
        padding: 4px 8px;
    }}

    /* ── Labels (default) ─────────────────────────────────────── */
    QLabel {{ color: {TEXT_DIM}; background: transparent; }}

    /* ── Matplotlib nav toolbar ───────────────────────────────── */
    QToolBar {{
        background: {PANEL};
        border: none;
        border-top: 1px solid {BORDER_LO};
        spacing: 2px;
        padding: 2px 4px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        color: {TEXT_DIM};
        border: 1px solid transparent;
        border-radius: 2px;
        padding: 3px 5px;
    }}
    QToolBar QToolButton:hover {{
        background: {BG};
        border-color: {ACCENT};
        color: {ACCENT};
    }}
    QToolBar QToolButton:pressed {{ background: {ACCENT_DK}; }}

    /* ── Frames ───────────────────────────────────────────────── */
    QFrame[frameShape="4"] {{ color: {BORDER_LO}; }}  /* HLine */
    QFrame[frameShape="5"] {{ color: {BORDER_LO}; }}  /* VLine */

    /* ── Dialog / wizard ──────────────────────────────────────── */
    QDialog {{ background: {BG}; }}
    QStackedWidget {{ background: {BG}; }}
    """


# ── Apply theme ────────────────────────────────────────────────────────────

def apply_theme(app: QApplication):
    """
    Call once at startup. Loads Orbitron, sets Qt palette, applies stylesheet.
    """
    global HEADING_FONT
    app.setStyle("Fusion")

    HEADING_FONT = _load_fonts()

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base,            QColor(INPUT))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(ALT_ROW))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(PANEL))
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
        f"padding: 6px 18px; border-radius: 2px; font-weight: bold; "
        f"font-family: Arial; font-size: 12px; }}"
        f"QPushButton:hover {{ background: #7acee0; }}"
        f"QPushButton:pressed {{ background: {ACCENT_DK}; }}"
        f"QPushButton:disabled {{ background: {BORDER}; color: {TEXT_OFF}; }}"
    )


def btn_secondary(text: str = "") -> str:  # noqa: ARG001
    """Return a QPushButton stylesheet for secondary / outline buttons."""
    return (
        f"QPushButton {{ background: transparent; color: {ACCENT2}; "
        f"border: 1px solid {BORDER}; padding: 5px 14px; border-radius: 2px; }}"
        f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
        f"QPushButton:disabled {{ color: {TEXT_OFF}; border-color: {BORDER_LO}; }}"
    )


def btn_success() -> str:
    return (
        f"QPushButton {{ background: #1e3a28; color: #3cb44b; "
        f"border: 1px solid #2a5a34; padding: 5px 14px; border-radius: 2px; font-weight: bold; }}"
        f"QPushButton:hover {{ background: #2a5a34; color: #4cca5b; }}"
    )


def section_header_style() -> str:
    """Stylesheet for bold cyan section headers inside tabs."""
    return (
        f"font-family: '{HEADING_FONT}', Arial, sans-serif; "
        f"font-size: 12px; font-weight: bold; color: {ACCENT}; "
        f"letter-spacing: 1px;"
    )
