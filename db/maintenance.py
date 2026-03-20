"""
Database maintenance: archive old data, clean orphans.

Data outside the retention window is MOVED to the archive DB (not deleted),
so historical analysis is always available via --include-archive.

Usage:
    python -m db.maintenance              # archive across all formats
    python -m db.maintenance --dry-run    # show what would move, nothing changes
    python -m db.maintenance --format standard
"""

import os
import logging
import argparse
import configparser
from datetime import datetime, timedelta
from db.database import get_connection, get_archive_connection, DB_PATH, ARCHIVE_PATH

_LOG_PATH = os.path.join(os.path.dirname(DB_PATH), 'maintenance.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

ALL_FORMATS = ['standard', 'pioneer', 'modern', 'legacy', 'vintage', 'pauper']


def _load_config():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(project_root, 'config.ini'))

    retention = {fmt: cfg.getint('retention', fmt, fallback=1095) for fmt in ALL_FORMATS}
    foundations_days = cfg.getint('retention', 'foundations_days', fallback=1825)
    foundations_sets = {
        s.strip().upper()
        for s in cfg.get('retention', 'foundations_sets', fallback='FDN').split(',')
    }
    return retention, foundations_days, foundations_sets


def _parse_event_date(date_str):
    if not date_str:
        return None
    for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _event_contains_foundations_card(conn, event_id, foundations_sets):
    try:
        result = conn.execute("""
            SELECT 1 FROM deck_cards dc
            JOIN decks d ON d.id = dc.deck_id
            JOIN cards c ON c.id = dc.card_id
            WHERE d.event_id = ? AND c.set_code IN ({})
            LIMIT 1
        """.format(','.join('?' * len(foundations_sets))),
            [event_id] + list(foundations_sets)
        ).fetchone()
        return result is not None
    except Exception:
        return False  # set_code not available yet


def _get_events_to_archive(conn, format_name, cutoff, foundations_cutoff, foundations_sets):
    events = conn.execute(
        "SELECT id, date FROM events WHERE format = ?", (format_name,)
    ).fetchall()

    to_archive = []
    for ev in events:
        parsed = _parse_event_date(ev['date'])
        if parsed is None:
            continue

        if format_name == 'standard' and foundations_cutoff is not None:
            if parsed >= cutoff:
                continue  # within active window
            elif parsed >= foundations_cutoff:
                if _event_contains_foundations_card(conn, ev['id'], foundations_sets):
                    continue  # Foundations card — use extended window
                to_archive.append(ev['id'])
            else:
                to_archive.append(ev['id'])  # beyond even extended window
        else:
            if parsed < cutoff:
                to_archive.append(ev['id'])

    return to_archive


def _copy_events_to_archive(active_conn, archive_conn, event_ids):
    """
    Copy events, their decks, deck_cards, and referenced cards to the archive DB.
    Cards are copied only if not already present in the archive.
    """
    ep = ','.join('?' * len(event_ids))

    events    = active_conn.execute(f"SELECT * FROM events WHERE id IN ({ep})", event_ids).fetchall()
    deck_rows = active_conn.execute(f"SELECT * FROM decks WHERE event_id IN ({ep})", event_ids).fetchall()

    deck_ids = [d['id'] for d in deck_rows]
    deck_card_rows = []
    card_ids = set()

    if deck_ids:
        dp = ','.join('?' * len(deck_ids))
        deck_card_rows = active_conn.execute(
            f"SELECT * FROM deck_cards WHERE deck_id IN ({dp})", deck_ids
        ).fetchall()
        card_ids = {r['card_id'] for r in deck_card_rows}

    card_rows = []
    if card_ids:
        cp = ','.join('?' * len(card_ids))
        card_rows = active_conn.execute(
            f"SELECT * FROM cards WHERE id IN ({cp})", list(card_ids)
        ).fetchall()

    # Insert into archive (ignore conflicts — already archived)
    for row in card_rows:
        archive_conn.execute(
            "INSERT OR IGNORE INTO cards (id, name) VALUES (?, ?)",
            (row['id'], row['name'])
        )
    for row in events:
        archive_conn.execute("""
            INSERT OR IGNORE INTO events
                (id, source_id, source, name, date, format, event_type, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (row['id'], row['source_id'], row['source'], row['name'],
              row['date'], row['format'], row['event_type'], row['url']))
    for row in deck_rows:
        archive_conn.execute("""
            INSERT OR IGNORE INTO decks
                (id, event_id, source_id, player, archetype, placement, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (row['id'], row['event_id'], row['source_id'], row['player'],
              row['archetype'], row['placement'], row['url']))
    for row in deck_card_rows:
        archive_conn.execute("""
            INSERT OR IGNORE INTO deck_cards (deck_id, card_id, quantity, is_sideboard)
            VALUES (?, ?, ?, ?)
        """, (row['deck_id'], row['card_id'], row['quantity'], row['is_sideboard']))

    return len(events), len(deck_rows), len(deck_card_rows)


def _delete_from_active(conn, event_ids, deck_ids):
    if not event_ids:
        return
    ep = ','.join('?' * len(event_ids))
    if deck_ids:
        dp = ','.join('?' * len(deck_ids))
        conn.execute(f"DELETE FROM deck_cards WHERE deck_id IN ({dp})", deck_ids)
    conn.execute(f"DELETE FROM decks WHERE event_id IN ({ep})", event_ids)
    conn.execute(f"DELETE FROM events WHERE id IN ({ep})", event_ids)


def archive_format(format_name, retention_days, foundations_days, foundations_sets,
                   dry_run=False):
    """Move events outside the retention window to the archive DB."""
    if retention_days == 0:
        log.info(f"  {format_name}: retention disabled, skipping.")
        return 0, 0, 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    foundations_cutoff = (
        datetime.now() - timedelta(days=foundations_days)
        if format_name == 'standard' and foundations_days > 0 else None
    )

    with get_connection() as active_conn, get_archive_connection() as archive_conn:
        event_ids = _get_events_to_archive(
            active_conn, format_name, cutoff, foundations_cutoff, foundations_sets
        )

        if not event_ids:
            return 0, 0, 0

        ep = ','.join('?' * len(event_ids))
        deck_ids = [
            r['id'] for r in active_conn.execute(
                f"SELECT id FROM decks WHERE event_id IN ({ep})", event_ids
            ).fetchall()
        ]

        ev_count, dk_count, dc_count = _copy_events_to_archive(
            active_conn, archive_conn, event_ids
        )

        if not dry_run:
            _delete_from_active(active_conn, event_ids, deck_ids)

    return ev_count, dk_count, dc_count


def archive_orphaned_cards(dry_run=False):
    """Remove cards from active DB that no longer appear in any deck_card row."""
    with get_connection() as conn:
        count = conn.execute("""
            SELECT COUNT(*) FROM cards
            WHERE id NOT IN (SELECT DISTINCT card_id FROM deck_cards)
        """).fetchone()[0]
        if not dry_run and count > 0:
            conn.execute("""
                DELETE FROM cards
                WHERE id NOT IN (SELECT DISTINCT card_id FROM deck_cards)
            """)
    return count


def run_maintenance(formats=None, dry_run=False):
    """
    Archive all out-of-window data across formats, then clean orphaned cards.
    Called automatically at the end of every scraper run.
    """
    retention_map, foundations_days, foundations_sets = _load_config()
    target_formats = formats if formats else ALL_FORMATS
    prefix = "[DRY RUN] " if dry_run else ""

    log.info(f"{prefix}--- Maintenance started (archive mode) ---")
    log.info(f"{prefix}  Active DB : {DB_PATH}")
    log.info(f"{prefix}  Archive DB: {ARCHIVE_PATH}")

    total_events = total_decks = total_deck_cards = 0

    for fmt in target_formats:
        days = retention_map.get(fmt, 1095)
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        extra = ""
        if fmt == 'standard' and foundations_days > 0:
            fc = (datetime.now() - timedelta(days=foundations_days)).strftime('%Y-%m-%d')
            extra = f" (Foundations window: {fc})"
        log.info(f"{prefix}  {fmt.capitalize():<10} cutoff={cutoff}{extra}")

        ev, dk, dc = archive_format(
            fmt, days, foundations_days, foundations_sets, dry_run
        )
        total_events += ev
        total_decks += dk
        total_deck_cards += dc

        if ev > 0:
            action = "Would archive" if dry_run else "Archived"
            log.info(f"{prefix}    {action}: {ev} events, {dk} decks, {dc} deck_card rows")

    orphans = archive_orphaned_cards(dry_run)
    if orphans > 0:
        action = "Would remove" if dry_run else "Removed"
        log.info(f"{prefix}  {action} {orphans} orphaned card records from active DB")

    if total_events == 0 and orphans == 0:
        log.info(f"{prefix}  Nothing to archive — all data within retention windows.")

    log.info(
        f"{prefix}--- Maintenance complete: "
        f"{total_events} events, {total_decks} decks, "
        f"{total_deck_cards} deck_card rows archived; {orphans} orphans cleaned ---"
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MTG Meta Analyzer — DB maintenance')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be archived without moving anything')
    parser.add_argument('--format', dest='fmt', choices=ALL_FORMATS,
                        help='Run for one format only')
    args = parser.parse_args()

    fmt_list = [args.fmt] if args.fmt else None
    run_maintenance(formats=fmt_list, dry_run=args.dry_run)
