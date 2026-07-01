import sqlite3
import os
import configparser

def _resolve_path(key, fallback, env_var=None):
    # Resolution ladder (2026-07-01): env var > config.ini > repo-relative default.
    # The env var is the machine-wide "one knob" so the DB can live outside the
    # repo tree (e.g. D:\mtg-data\); GUI, scrapers, MCP server, generate_site_data
    # and mtg-sim's db_bridge all follow it.
    if env_var:
        env = os.environ.get(env_var)
        if env:
            return env
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(project_root, 'config.ini'))
    raw = cfg.get('database', key, fallback=fallback)
    if not os.path.isabs(raw):
        return os.path.join(project_root, raw)
    return raw

DB_PATH      = _resolve_path('path',         'data/mtg_meta.db',    env_var='MTG_META_DB')
ARCHIVE_PATH = _resolve_path('archive_path', 'data/mtg_archive.db', env_var='MTG_META_ARCHIVE_DB')


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
    CREATE TABLE IF NOT EXISTS guides (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        date      TEXT,
        url       TEXT NOT NULL UNIQUE,
        format    TEXT,
        archetype TEXT,
        type      TEXT,
        author    TEXT,
        source    TEXT,
        comment   TEXT,
        added_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS bookmarks (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        added_at  TEXT NOT NULL,
        url       TEXT NOT NULL UNIQUE,
        title     TEXT,
        format    TEXT,
        archetype TEXT,
        type      TEXT,
        note      TEXT
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
    # Additive migrations — safe to re-run; OperationalError = column exists
    for stmt in [
        "ALTER TABLE events ADD COLUMN event_type TEXT",
        "ALTER TABLE events ADD COLUMN event_fingerprint TEXT",
        "ALTER TABLE events ADD COLUMN event_fingerprint_cs TEXT",
        "ALTER TABLE decks  ADD COLUMN deck_fingerprint  TEXT",
    ]:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    # Indexes for fast fingerprint duplicate lookups
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_fp    ON events(event_fingerprint)"
    )
    conn.execute(
        # Cross-source fingerprint index — used by upsert_event dup detection
        # and filter_cross_source_duplicates in the deck dedup layer.
        "CREATE INDEX IF NOT EXISTS idx_events_fp_cs ON events(event_fingerprint_cs)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decks_fp ON decks(deck_fingerprint)"
    )


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
    from core.data_engine.dedup import generate_event_fingerprint, generate_event_fingerprint_cs
    # Strict fingerprint — stored for analysis; preserves trailing numbers so
    # numbered same-source same-day events (LCQ #1 … #22) stay distinct.
    fp    = generate_event_fingerprint(name, date, fmt)
    # Cross-source fingerprint — strips trailing serials; used to detect when
    # the same real-world event was scraped by both mtgtop8 and mtgdecks.
    fp_cs = generate_event_fingerprint_cs(name, date, fmt)

    with get_connection() as conn:
        # Cross-source duplicate detection uses fp_cs so that e.g.
        # "MTGO Challenge 32" (mtgtop8) matches "MTGO Challenge 32 #12835978" (mtgdecks).
        dup = conn.execute(
            "SELECT id, source, source_id, name FROM events "
            "WHERE event_fingerprint_cs = ? AND NOT (source = ? AND source_id = ?)",
            (fp_cs, source, source_id),
        ).fetchone()
        if dup:
            print(
                f"  [DEDUP:event] '{name}' ({source}/{source_id})"
                f" matches '{dup['name']}' ({dup['source']}/{dup['source_id']})"
                f" fp_cs={fp_cs}"
            )

        conn.execute("""
            INSERT INTO events
                (source, source_id, name, date, format, event_type, url,
                 event_fingerprint, event_fingerprint_cs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                name=excluded.name, date=excluded.date,
                format=excluded.format, event_type=excluded.event_type,
                url=excluded.url,
                event_fingerprint=excluded.event_fingerprint,
                event_fingerprint_cs=excluded.event_fingerprint_cs
        """, (source, source_id, name, date, fmt, event_type, url, fp, fp_cs))
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
    from core.data_engine.dedup import generate_deck_fingerprint
    fp = generate_deck_fingerprint(mainboard, sideboard)

    def _get_or_create_card(conn, name):
        conn.execute("INSERT OR IGNORE INTO cards (name) VALUES (?)", (name,))
        return conn.execute("SELECT id FROM cards WHERE name=?", (name,)).fetchone()["id"]

    with get_connection() as conn:
        # Detect cross-event deck duplicates (non-blocking — log only)
        dup = conn.execute(
            "SELECT d.id, d.player, e.name AS event_name, e.source AS event_source "
            "FROM decks d JOIN events e ON e.id = d.event_id "
            "WHERE d.deck_fingerprint = ? AND d.id != ?",
            (fp, deck_id),
        ).fetchone()
        if dup:
            print(
                f"  [DEDUP:deck] deck {deck_id}"
                f" matches deck {dup['id']}"
                f" (player: {dup['player'] or 'unknown'},"
                f" event: {(dup['event_name'] or '?')[:40]} [{dup['event_source']}])"
                f" fp={fp}"
            )

        # Store fingerprint on the deck row
        conn.execute(
            "UPDATE decks SET deck_fingerprint = ? WHERE id = ?", (fp, deck_id)
        )

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
