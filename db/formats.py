"""The analyzer's supported formats, and the ONE way to filter a query by format.

"All formats" means every format in SUPPORTED_FORMATS, not every string present in the data:
`matches` also holds valid rows of formats the analyzer does not support yet (e.g. 159 Vintage
trios-seat matches, re-tagged 2026-10-02). They stay stored and out of every combined statistic
until the format is added here -- which also makes it selectable.

Use `format_clause()` wherever a query filters by a format that may be the "all" sentinel; never
drop the filter for "all".
"""
from __future__ import annotations

SUPPORTED_FORMATS: tuple[str, ...] = ("standard", "pioneer", "modern", "legacy", "pauper")

_ALL_SENTINELS = {"", "all", "all formats", "(any)", "any"}


def is_all_formats(fmt) -> bool:
    """True if `fmt` is the cross-format sentinel: None, '', 'all', 'All Formats', '(any)', 'any'
    (case-insensitive, whitespace-trimmed)."""
    return fmt is None or str(fmt).strip().lower() in _ALL_SENTINELS


def formats_for(fmt) -> list[str]:
    """The concrete formats a selection covers: all supported ones for the sentinel, else [fmt]."""
    return list(SUPPORTED_FORMATS) if is_all_formats(fmt) else [str(fmt).strip().lower()]


def format_clause(fmt, col: str = "format") -> tuple[str, list]:
    """(' AND <filter>', params) restricting `col` to the selected format -- or, for "all", to
    the supported formats (never no filter)."""
    if is_all_formats(fmt):
        return (f" AND lower({col}) IN ({','.join('?' * len(SUPPORTED_FORMATS))})",
                list(SUPPORTED_FORMATS))
    return f" AND lower({col}) = lower(?)", [fmt]
