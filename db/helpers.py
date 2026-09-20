"""
Shared DB helper functions — table init, timestamps, JSON serialization.

Import from here instead of duplicating per-module.
"""

import json
import os
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


# ── Active scrape formats (preferences.json) ──────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFERENCES_PATH = os.path.join(_PROJECT_ROOT, "data", "preferences.json")

# The fallback when no valid `formats` selection exists. Deliberately narrow:
# a wide default would hide a broken config just as well as a silent one did.
DEFAULT_FORMATS = ["standard"]

_DEFAULT_WARNING = (
    "DEFAULTING to standard only. Modern/Pioneer will not be scraped. "
    "Fix: add \"formats\": [...] to data/preferences.json or re-save Settings."
)


def load_active_formats(prefs_path: str | None = None, *, log=print) -> list:
    """
    Return the formats the scrape pipeline should run, from preferences.json.

    This is the ONE implementation of that decision -- fill_database.py and
    scripts/run_fill_from_prefs.py both call it (they used to carry near-
    duplicate copies with different defaults). A fallback must never look like
    a setting: whenever DEFAULT_FORMATS is returned, a loud warning naming the
    reason is emitted through `log` first. Before 2026-09-20 a missing
    `formats` key silently returned ["standard"] for ~10 weeks while the log
    printed "[prefs] Active formats: standard".
    """
    path = prefs_path or PREFERENCES_PATH
    reason = None
    try:
        if not os.path.exists(path):
            reason = f"preferences.json not found at {path}"
        else:
            with open(path, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            if not isinstance(prefs, dict):
                reason = "preferences.json top level is not an object"
            elif "formats" not in prefs:
                reason = "No 'formats' key in preferences.json"
            elif not isinstance(prefs["formats"], list):
                reason = f"'formats' is not a list (got {type(prefs['formats']).__name__})"
            elif not prefs["formats"]:
                reason = "'formats' is an empty list"
            else:
                return list(prefs["formats"])
    except (OSError, ValueError) as e:
        reason = f"could not read preferences.json ({type(e).__name__}: {e})"
    log(f"[prefs] WARNING: {reason} -- {_DEFAULT_WARNING}")
    return list(DEFAULT_FORMATS)
