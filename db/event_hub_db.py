"""
db/event_hub_db.py -- Event Hub persistence layer.

Two tables in mtg_meta.db:
  event_bookmarks  -- saved events with status, notes, results
  store_bookmarks  -- saved stores for quick-filter
"""

import json
from db.database import get_connection


def ensure_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_bookmarks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id         TEXT UNIQUE NOT NULL,
                title            TEXT NOT NULL,
                store_name       TEXT,
                event_date       TEXT,
                format_tags      TEXT DEFAULT '[]',
                event_type       TEXT,
                entry_fee_cents  INTEGER,
                event_url        TEXT,
                lat              REAL,
                lng              REAL,
                dist_mi          REAL,
                status           TEXT DEFAULT 'interested',
                personal_notes   TEXT DEFAULT '',
                result           TEXT DEFAULT '',
                deck_played      TEXT DEFAULT '',
                prize            TEXT DEFAULT '',
                added_at         TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_bookmarks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id    TEXT UNIQUE NOT NULL,
                name      TEXT NOT NULL,
                lat       REAL,
                lng       REAL,
                dist_mi   REAL,
                notes     TEXT DEFAULT '',
                added_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ---------------------------------------------------------------------------
# Event bookmarks
# ---------------------------------------------------------------------------

def upsert_event_bookmark(event: dict) -> int:
    ensure_tables()
    tags = json.dumps(event.get("raw_tags") or [])
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO event_bookmarks
                (event_id, title, store_name, event_date, format_tags, event_type,
                 entry_fee_cents, event_url, lat, lng, dist_mi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                title=excluded.title, store_name=excluded.store_name,
                event_date=excluded.event_date, format_tags=excluded.format_tags,
                event_url=excluded.event_url
        """, (
            event.get("id"), event.get("title"), event.get("store"),
            event.get("date"), tags,
            _infer_type(event.get("raw_tags") or []),
            _fee_cents(event.get("fee")),
            _event_url(event.get("id")),
            event.get("lat"), event.get("lng"), event.get("dist_mi"),
        ))
        return conn.execute(
            "SELECT id FROM event_bookmarks WHERE event_id=?", (event.get("id"),)
        ).fetchone()["id"]


def get_all_bookmarks() -> list[dict]:
    ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM event_bookmarks ORDER BY event_date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_bookmark_field(event_id: str, field: str, value: str):
    """Update a single editable field (status, notes, result, deck_played, prize)."""
    allowed = {"status", "personal_notes", "result", "deck_played", "prize"}
    if field not in allowed:
        raise ValueError(f"Field '{field}' not editable")
    ensure_tables()
    with get_connection() as conn:
        conn.execute(f"UPDATE event_bookmarks SET {field}=? WHERE event_id=?",
                     (value, event_id))


def remove_event_bookmark(event_id: str):
    ensure_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM event_bookmarks WHERE event_id=?", (event_id,))


def is_bookmarked(event_id: str) -> bool:
    ensure_tables()
    with get_connection() as conn:
        r = conn.execute(
            "SELECT 1 FROM event_bookmarks WHERE event_id=?", (event_id,)
        ).fetchone()
    return r is not None


# ---------------------------------------------------------------------------
# Store bookmarks
# ---------------------------------------------------------------------------

def upsert_store_bookmark(store: dict) -> int:
    ensure_tables()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO store_bookmarks (org_id, name, lat, lng, dist_mi)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET name=excluded.name
        """, (store.get("org_id"), store.get("name"),
              store.get("lat"), store.get("lng"), store.get("dist_mi")))
        return conn.execute(
            "SELECT id FROM store_bookmarks WHERE org_id=?", (store.get("org_id"),)
        ).fetchone()["id"]


def get_all_store_bookmarks() -> list[dict]:
    ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM store_bookmarks ORDER BY dist_mi ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_store_bookmark(org_id: str):
    ensure_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM store_bookmarks WHERE org_id=?", (org_id,))


# ---------------------------------------------------------------------------
# .ics export
# ---------------------------------------------------------------------------

def export_ics(bookmarks: list[dict] | None = None) -> str:
    """Generate iCalendar string from bookmarks (default: going + interested)."""
    if bookmarks is None:
        all_bm = get_all_bookmarks()
        bookmarks = [b for b in all_bm if b["status"] in ("going", "interested")]

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MTG Event Hub//EN",
        "CALSCALE:GREGORIAN",
    ]
    for b in bookmarks:
        date_str = (b.get("event_date") or "").replace("-", "")
        if not date_str:
            continue
        try:
            tags = json.loads(b.get("format_tags") or "[]")
        except Exception:
            tags = []
        fmt = ", ".join(t.replace("_", " ").title() for t in tags
                        if t != "magic:_the_gathering")
        fee_str = f"${b['entry_fee_cents'] // 100}" if b.get("entry_fee_cents") else "?"
        desc = (
            f"Entry: {fee_str} | Format: {fmt or '?'} | "
            f"Status: {b['status'].title()}"
        )
        if b.get("personal_notes"):
            desc += f"\\nNotes: {b['personal_notes']}"

        lines += [
            "BEGIN:VEVENT",
            f"UID:{b['event_id']}@mtg-event-hub",
            f"DTSTART:{date_str}T120000Z",
            f"DTEND:{date_str}T200000Z",
            f"SUMMARY:{b['title']} @ {b['store_name'] or '?'}",
            f"LOCATION:{b['store_name'] or ''}",
            f"DESCRIPTION:{desc}",
        ]
        if b.get("event_url"):
            lines.append(f"URL:{b['event_url']}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_type(tags: list[str]) -> str:
    for t in tags:
        if "regional_championship" in t:
            return "rcq"
        if "store_championship" in t:
            return "store_championship"
        if "friday_night_magic" in t:
            return "fnm"
    return "other"


def _fee_cents(fee_str: str | None) -> int | None:
    if not fee_str:
        return None
    try:
        return int(float(fee_str.replace("$", "").strip()) * 100)
    except Exception:
        return None


def _event_url(event_id: str | None) -> str:
    if not event_id:
        return ""
    return f"https://locator.wizards.com/event/{event_id}"
