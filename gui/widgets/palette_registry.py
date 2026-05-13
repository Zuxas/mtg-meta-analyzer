"""PaletteRegistry — searchable command catalog for the command palette.

Pure Python. No Qt. The QDialog layer (command_palette.py) consumes this.

Entries have stable IDs (`tab:dashboard`, `arch:izzet-prowess`, etc.) so
recents stored in UIState survive renames and tab reorganization.

Card category is gated behind the `c:` prefix only — short or long queries
without the prefix never surface CARDs, so the 32k-card namespace doesn't
drown other results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from thefuzz import fuzz, process

CATEGORIES = ("TAB", "ARCH", "DECK", "CARD", "ACT")

_CATEGORY_PRIORITY = {"TAB": 0, "ACT": 1, "ARCH": 2, "DECK": 3, "CARD": 4}

_MIN_FUZZ_SCORE = 50  # WRatio cutoff; below this, treat as "no match"


@dataclass
class PaletteEntry:
    id: str                   # stable; e.g. "tab:my-decks"
    category: str             # one of CATEGORIES
    name: str                 # display name (the searchable text)
    secondary: str = ""       # context line shown below name
    handler: Callable[[], None] = field(default=lambda: None)
    context_predicate: Optional[Callable[[], bool]] = None


def parse_prefix(query: str) -> tuple[Optional[str], str]:
    """Return (category_filter_or_None, remaining_query)."""
    if query.startswith("c:"):
        return ("CARD", query[2:].strip())
    if query and query[0] in ">#@:":
        prefix_map = {">": "ACT", "#": "TAB", "@": "ARCH", ":": "DECK"}
        return (prefix_map[query[0]], query[1:].strip())
    return (None, query.strip())


class PaletteRegistry:
    def __init__(self) -> None:
        self._entries: list[PaletteEntry] = []
        self._by_id: dict[str, PaletteEntry] = {}

    def register(self, entry: PaletteEntry) -> None:
        if entry.id in self._by_id:
            self._entries.remove(self._by_id[entry.id])
        self._entries.append(entry)
        self._by_id[entry.id] = entry

    def unregister(self, entry_id: str) -> None:
        e = self._by_id.pop(entry_id, None)
        if e is not None:
            self._entries.remove(e)

    def get(self, entry_id: str) -> Optional[PaletteEntry]:
        return self._by_id.get(entry_id)

    def has(self, entry_id: str) -> bool:
        return entry_id in self._by_id

    def search(self, query: str, limit: int = 8) -> list[PaletteEntry]:
        category, q = parse_prefix(query)
        candidates = [
            e for e in self._entries
            if (category is None or e.category == category)
            and (e.context_predicate is None or e.context_predicate())
        ]

        # No prefix: hide CARD entries entirely (cards are gated by `c:` only).
        if category is None:
            candidates = [e for e in candidates if e.category != "CARD"]

        if not q:
            candidates.sort(key=lambda e: (_CATEGORY_PRIORITY.get(e.category, 9), e.name))
            return candidates[:limit]

        choices = {e.id: e.name for e in candidates}
        matches = process.extract(q, choices, scorer=fuzz.WRatio, limit=limit)
        # matches: list of (name, score, id)
        return [self._by_id[m[2]] for m in matches if m[1] >= _MIN_FUZZ_SCORE]

    def prune_recents(self, recents: list[str]) -> list[str]:
        return [r for r in recents if r in self._by_id]
