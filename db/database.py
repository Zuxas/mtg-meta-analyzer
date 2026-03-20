import sqlite3
import os
import configparser

def _resolve_path(key, fallback):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(project_root, 'config.ini'))
    raw = cfg.get('database', key, fallback=fallback)
    if not os.path.isabs(raw):
        return os.path.join(project_root, raw)
    return raw

DB_PATH      = _resolve_path('path',         'data/mtg_meta.db')
ARCHIVE_PATH = _resolve_path('archive_path', 'data/mtg_archive.db')


_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id   TEXT NOT NULL,
        source      TEXT NOT NULL,
        name        TEXT,
        date        TEXT,
        format      TEXT,
        event_type  TEXT,
        url         TEXT,
        UNIQUE(source, source_id)
    );
    CREATE TABLE IF NOT EXISTS decks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id    INTEGER NOT NULL REFERENCES events(id),
        source_id   TEXT NOT NULL,
        player      TEXT,
        archetype   TEXT,
        placement   INTEGER,
        url         TEXT,
        UNIQUE(event_id, source_id)
    );
    CREATE TABLE IF NOT EXISTS cards (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS deck_cards (
        deck_id      INTEGER NOT NULL REFERENCES decks(id),
        card_id      INTEGER NOT NULL REFERENCES cards(id),
        quantity     INTEGER NOT NULL DEFAULT 1,
        is_sideboard INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (deck_id, card_id, is_sideboard)
    );
    CREATE TABLE IF NOT EXISTS card_data (
        name           TEXT PRIMARY KEY,
        scryfall_id    TEXT,
        mana_cost      TEXT,
        cmc            REAL,
        colors         TEXT,
        color_identity TEXT,
        type_line      TEXT,
        oracle_text    TEXT,
        power          TEXT,
        toughness      TEXT,
        rarity         TEXT,
        set_code       TEXT,
        legalities     TEXT,
        enriched_at    TEXT
    );
"""


def _make_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection():
    return _make_connection(DB_PATH)


def get_archive_connection():
    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    return _make_connection(ARCHIVE_PATH)


def get_combined_connection(include_archive=False):
    """
    Return an active-DB connection. If include_archive=True, the archive DB
    is ATTACHed as the alias 'archive' so queries can UNION across both.
    Usage:
        conn = get_combined_connection(include_archive=True)
        rows = conn.execute(
            "SELECT * FROM events UNION ALL SELECT * FROM archive.events"
        ).fetchall()
    """
    conn = get_connection()
    if include_archive and os.path.exists(ARCHIVE_PATH):
        conn.execute("ATTACH ? AS archive", (ARCHIVE_PATH,))
    return conn


def _apply_schema(conn):
    conn.executescript(_SCHEMA_SQL)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN event_type TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        _apply_schema(conn)
    print(f"Active DB : {os.path.abspath(DB_PATH)}")

    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    with get_archive_connection() as conn:
        _apply_schema(conn)
    print(f"Archive DB: {os.path.abspath(ARCHIVE_PATH)}")


def upsert_event(source, source_id, name, date, fmt, url, event_type=None):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO events (source, source_id, name, date, format, event_type, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                name=excluded.name, date=excluded.date,
                format=excluded.format, event_type=excluded.event_type, url=excluded.url
        """, (source, source_id, name, date, fmt, event_type, url))
        return conn.execute(
            "SELECT id FROM events WHERE source=? AND source_id=?", (source, source_id)
        ).fetchone()["id"]


def upsert_deck(event_id, source_id, player, archetype, placement, url):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO decks (event_id, source_id, player, archetype, placement, url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, source_id) DO UPDATE SET
                player=excluded.player, archetype=excluded.archetype,
                placement=excluded.placement, url=excluded.url
        """, (event_id, source_id, player, archetype, placement, url))
        return conn.execute(
            "SELECT id FROM decks WHERE event_id=? AND source_id=?", (event_id, source_id)
        ).fetchone()["id"]


def insert_deck_cards(deck_id, mainboard, sideboard):
    """Insert all cards for a deck in a single connection to avoid locking."""
    def _get_or_create_card(conn, name):
        conn.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (name,))
        return conn.execute("SELECT id FROM cards WHERE name=?", (name,)).fetchone()["id"]

    with get_connection() as conn:
        conn.execute("DELETE FROM deck_cards WHERE deck_id=?", (deck_id,))
        for card_name, qty in mainboard.items():
            card_id = _get_or_create_card(conn, card_name)
            conn.execute(
                "INSERT OR REPLACE INTO deck_cards VALUES (?, ?, ?, 0)",
                (deck_id, card_id, qty)
            )
        for card_name, qty in sideboard.items():
            card_id = _get_or_create_card(conn, card_name)
            conn.execute(
                "INSERT OR REPLACE INTO deck_cards VALUES (?, ?, ?, 1)",
                (deck_id, card_id, qty)
            )
