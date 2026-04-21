"""
Thin wrapper around qtawesome — returns themed QIcons for common actions.

If qtawesome isn't installed, every helper returns a null QIcon. Qt's
QPushButton.setIcon() accepts null icons gracefully (no icon shown), so
call sites don't need to check availability.

Usage:
    from gui.icons_util import btn_icon
    run_btn.setIcon(btn_icon("run"))
"""
import gui.theme as theme

try:
    import qtawesome as _qta
    _HAVE_QTA = True
except ImportError:
    _qta = None
    _HAVE_QTA = False


from PyQt6.QtGui import QIcon


# Semantic action → font-awesome glyph name
_ICON_MAP = {
    "run":        "fa5s.play",
    "refresh":    "fa5s.sync-alt",
    "export":     "fa5s.download",
    "copy":       "fa5s.copy",
    "delete":     "fa5s.trash",
    "add":        "fa5s.plus",
    "edit":       "fa5s.pen",
    "analyze":    "fa5s.microscope",
    "tournament": "fa5s.flag-checkered",
    "deck":       "fa5s.layer-group",
    "field":      "fa5s.users",
    "cancel":     "fa5s.times",
    "save":       "fa5s.save",
    "search":     "fa5s.search",
    "close":      "fa5s.times-circle",
    "simulate":   "fa5s.dice",
}


def btn_icon(name: str, color: str = None) -> QIcon:
    """Return a QIcon for the named action, themed to `color` (defaults to TEXT).
    Returns a null QIcon when qtawesome isn't installed — Qt handles that
    gracefully (button renders without an icon). Unknown names also return
    a null icon instead of raising."""
    if not _HAVE_QTA:
        return QIcon()
    glyph = _ICON_MAP.get(name)
    if glyph is None:
        return QIcon()
    try:
        return _qta.icon(glyph, color=color or theme.TEXT)
    except Exception:
        return QIcon()


def is_available() -> bool:
    """True if qtawesome is installed. Callers can use this for conditional UI."""
    return _HAVE_QTA
