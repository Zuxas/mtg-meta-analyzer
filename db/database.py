import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'mtg_meta.db')


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   TEXT NOT NULL,
                source      TEXT NOT NULL,
                name        TEXT,
                date        TEXT,
                format      TEXT,
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
                deck_id     INTEGER NOT NULL REFERENCES decks(id),
                card_id     INTEGER NOT NULL REFERENCES cards(id),
                quantity    INTEGER NOT NULL DEFAULT 1,
                is_sideboard INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (deck_id, card_id, is_sideboard)
            );
        """)
    print(f"Database ready at: {os.path.abspath(DB_PATH)}")


def upsert_event(source, source_id, name, date, fmt, url):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO events (source, source_id, name, date, format, url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                name=excluded.name, date=excluded.date,
                format=excluded.format, url=excluded.url
        """, (source, source_id, name, date, fmt, url))
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
