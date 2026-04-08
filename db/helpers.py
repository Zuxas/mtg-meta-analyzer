"""
Shared DB helper functions — table init, timestamps, JSON serialization.

Import from here instead of duplicating per-module.
"""

import json
from datetime import datetime, timezone

from db.database import get_connection


# ── Table initialization ──────────────────────────────────────────────────

def ensure_table(create_sql: str):
    """Execute a CREATE TABLE IF NOT EXISTS statement."""
    with get_connection() as conn:
        conn.executescript(create_sql)


# ── Timestamps ────────────────────────────────────────────────────────────

def utc_now() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── JSON helpers ──────────────────────────────────────────────────────────

def json_loads_dict(raw: str | None) -> dict:
    """Safely parse a JSON string to dict, returning {} on failure."""
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def json_loads_list(raw: str | None) -> list:
    """Safely parse a JSON string to list, returning [] on failure."""
    try:
        return json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
