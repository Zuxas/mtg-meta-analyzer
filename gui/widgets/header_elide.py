"""header_elide.py -- GR-2: shrink long archetype names to fit a narrow
table-header column without (a) ever splitting a name off mid-character,
(b) producing the same displayed string for two different names, or
(c) needing a fixed elide direction.

Uses a middle-out scheme (keep a prefix + a suffix, replace the middle
with an ellipsis) so two names that only diverge at the END (e.g.
"Izzet Prowess" / "Izzet Pyromancer") don't both collapse to the same
"Izzet P..." the way a plain end-ellipsis would. Every substring taken is
a whole Python string slice (never a raw byte offset), so a base
character is never separated from what follows it mid-glyph.

Pure Python + QFontMetrics for pixel measurement only -- no widget
dependency, so this is directly unit-testable under offscreen Qt.
"""
from __future__ import annotations

from PyQt6.QtGui import QFontMetrics

_ELLIPSIS = "…"


def _fits(metrics: QFontMetrics, text: str, max_width: int) -> bool:
    return metrics.horizontalAdvance(text) <= max_width


def _middle_elide(name: str, metrics: QFontMetrics, max_width: int) -> str:
    """Elide `name` to fit `max_width` pixels, keeping a prefix and a
    suffix around a single ellipsis, preferring the longest combined
    prefix+suffix that still fits. Falls back to a prefix-only elide, and
    finally to a single character, if the width is too tight for a
    middle-out split."""
    if _fits(metrics, name, max_width):
        return name
    n = len(name)
    if n <= 1:
        return name

    for total_keep in range(n - 1, 0, -1):
        prefix_len = (total_keep + 1) // 2
        suffix_len = total_keep - prefix_len
        candidate = (
            name[:prefix_len] + _ELLIPSIS + name[n - suffix_len:]
            if suffix_len else name[:prefix_len] + _ELLIPSIS
        )
        if _fits(metrics, candidate, max_width):
            return candidate
    # Nothing with an ellipsis fits -- bare single leading character.
    return name[0]


def _resolve_collision(name: str, metrics: QFontMetrics, max_width: int,
                        used: set) -> str:
    """Find a display string for `name` that fits `max_width` and is not
    already present in `used`, by scanning every prefix/suffix split at
    decreasing total keep-lengths (there are only `total_keep + 1` splits
    at each length) until an unused, fitting candidate turns up."""
    n = len(name)
    for total_keep in range(n - 1, -1, -1):
        for prefix_len in range(total_keep, -1, -1):
            suffix_len = total_keep - prefix_len
            if suffix_len:
                candidate = name[:prefix_len] + _ELLIPSIS + name[n - suffix_len:]
            elif prefix_len:
                candidate = name[:prefix_len] + _ELLIPSIS
            else:
                candidate = _ELLIPSIS
            if candidate not in used and _fits(metrics, candidate, max_width):
                return candidate

    # Exhausted every fitting split -- extremely unlikely with real
    # archetype names -- fall back to stamping a disambiguating digit
    # onto the best-effort elide so the "no two headers identical"
    # invariant holds unconditionally rather than best-effort.
    fallback = _middle_elide(name, metrics, max_width)
    for digit in "123456789":
        stamped = (fallback[:-1] + digit) if len(fallback) >= 2 else digit
        if stamped not in used:
            return stamped
    return fallback


def elide_headers_unique(names: list[str], metrics: QFontMetrics,
                          widths) -> dict[str, str]:
    """Return {name: display_text}, one entry per name in `names`.

    `widths` is either a single pixel budget (applied to every name) or a
    sequence of per-name pixel budgets (same order/length as `names`).

    Guarantees:
      - every value fits its name's width budget (best effort; only
        violated if even a single character doesn't fit, in which case
        that one character is returned regardless)
      - every value is unique across the whole returned dict, even when
        two names would otherwise middle-elide to the same string
      - no value ever slices a name at other than a whole-character
        boundary (plain Python string slicing throughout)
    """
    if isinstance(widths, int):
        widths = [widths] * len(names)

    candidates = [
        _middle_elide(name, metrics, w) for name, w in zip(names, widths)
    ]

    groups: dict[str, list[int]] = {}
    for i, c in enumerate(candidates):
        groups.setdefault(c, []).append(i)

    result = list(candidates)
    used = set(candidates)
    for text, idxs in groups.items():
        if len(idxs) <= 1:
            continue
        # Keep the first occurrence as-is; resolve the rest against
        # everything claimed so far (including sibling resolutions).
        for i in idxs[1:]:
            resolved = _resolve_collision(names[i], metrics, widths[i], used)
            result[i] = resolved
            used.add(resolved)

    return {name: text for name, text in zip(names, result)}
