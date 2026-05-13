"""Action registration for the command palette.

Called once from MainWindow.__init__ after tabs are built. Each function
adds a set of entries to the registry, with handlers that close over the
MainWindow instance.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from gui.widgets.palette_registry import PaletteEntry, PaletteRegistry

if TYPE_CHECKING:
    from gui.main_window import MainWindow


def register_tab_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Walk the QTabWidget tree and register every leaf tab as TAB:..."""
    root = window._tabs  # verified: top-level QTabWidget in MainWindow (main_window.py:129)

    def _walk(tabs, path_prefix: str) -> None:
        from PyQt6.QtWidgets import QTabWidget
        for i in range(tabs.count()):
            child = tabs.widget(i)
            label = tabs.tabText(i)
            path = f"{path_prefix}/{label}" if path_prefix else label
            if isinstance(child, QTabWidget):
                _walk(child, path)
            else:
                slug = path.lower().replace(" ", "-").replace("/", "-")
                entry_id = f"tab:{slug}"
                def make_handler(p=path):
                    return lambda: window.activate_tab_by_path(p)
                reg.register(PaletteEntry(
                    id=entry_id, category="TAB",
                    name=f"Jump to {path}", secondary="",
                    handler=make_handler(),
                ))

    _walk(root, "")


def register_action_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Register built-in ACT:* entries."""
    reg.register(PaletteEntry(
        id="act:refresh-current-tab", category="ACT",
        name="Refresh current tab", secondary="Same as F5",
        handler=window._refresh_current_tab,
    ))
    reg.register(PaletteEntry(
        id="act:open-settings", category="ACT",
        name="Open Settings", secondary="",
        handler=lambda: window.activate_tab_by_path("SETTINGS"),
    ))
    reg.register(PaletteEntry(
        id="act:reset-ui-state", category="ACT",
        name="Reset UI state", secondary="Clears persisted selections/filters",
        handler=window.reset_ui_state,
    ))
    for fmt in ("standard", "modern", "pioneer", "legacy", "pauper"):
        reg.register(PaletteEntry(
            id=f"act:format-{fmt}", category="ACT",
            name=f"Set format -> {fmt.title()}", secondary="",
            handler=lambda f=fmt: window.set_format(f),
        ))


def register_archetype_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Enumerate distinct archetypes from the decks table and register ARCH:*.

    `analysis/archetypes.py` does NOT expose a public "list all archetypes"
    function (only `merge_archetypes()`, `pre_normalize()`, `ALIASES`).
    Source-of-truth archetype names come from the decks table directly.
    """
    try:
        from db.database import get_combined_connection
        conn = get_combined_connection()
        cur = conn.execute(
            "SELECT DISTINCT archetype FROM decks "
            "WHERE archetype IS NOT NULL AND archetype != '' "
            "ORDER BY archetype"
        )
        names = [row[0] for row in cur]
    except Exception:
        return
    for name in names:
        slug = name.lower().replace(" ", "-")
        reg.register(PaletteEntry(
            id=f"arch:{slug}", category="ARCH",
            name=name, secondary="",
            handler=lambda n=name: window.open_archetype_detail(n),
        ))


def register_deck_entries(reg: PaletteRegistry, window: "MainWindow") -> None:
    """Enumerate saved_decks rows and register DECK:* entries.

    Verified signature: `db.saved_decks.get_decks(format_name: str = None)
    -> list[dict]`. Each dict has keys 'id', 'name', 'format', 'archetype',
    'mainboard', 'sideboard', 'notes', 'created_at' (see save_deck schema
    in db/saved_decks.py).
    """
    try:
        from db.saved_decks import get_decks
        rows = get_decks()
    except Exception:
        return
    for row in rows:
        deck_id = row["id"]
        name = row["name"]
        reg.register(PaletteEntry(
            id=f"deck:{deck_id}", category="DECK",
            name=name, secondary=f"id={deck_id}",
            handler=lambda d=deck_id: window.open_saved_deck(d),
        ))


def register_card_entries(reg: PaletteRegistry) -> None:
    """Enumerate card_data names (large) and register CARD:* entries.

    Card category is gated behind `c:` prefix in the registry; registering
    all ~32k is fine because thefuzz only scores when a query is present.

    Note: slug truncation to [:60] can collide on very long card names that
    share the first 60 characters. PaletteRegistry.register deduplicates by
    replacing on collision, so only the last entry survives. Acceptable for v1.
    """
    try:
        from db.database import get_combined_connection
        conn = get_combined_connection()
        cur = conn.execute("SELECT name FROM card_data")
        for (name,) in cur:
            slug = name.lower().replace(" ", "-").replace(",", "")[:60]
            reg.register(PaletteEntry(
                id=f"card:{slug}", category="CARD",
                name=name, secondary="",
                handler=lambda n=name: None,  # v1: cards are searchable but selecting is no-op
            ))
    except Exception:
        return


def register_all(reg: PaletteRegistry, window: "MainWindow") -> None:
    register_tab_entries(reg, window)
    register_action_entries(reg, window)
    register_archetype_entries(reg, window)
    register_deck_entries(reg, window)
    register_card_entries(reg)
