"""
Database maintenance: format-aware data retention and orphan cleanup.
Runs automatically at the end of every scraper session.

Can also be run standalone:
    python -m db.maintenance
    python -m db.maintenance --dry-run
    python -m db.maintenance --format standard
"""

import os
import logging
import argparse
import configparser
from datetime import datetime, timedelta
from db.database import get_connection, DB_PATH

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

# Formats the scraper knows about
ALL_FORMATS = ['standard', 'pioneer', 'modern', 'legacy', 'vintage', 'pauper']


def _load_config():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(project_root, 'config.ini'))

    retention = {}
    for fmt in ALL_FORMATS:
        days = cfg.getint('retention', fmt, fallback=1095)
        retention[fmt] = days

    foundations_days = cfg.getint('retention', 'foundations_days', fallback=1825)
    foundations_sets_raw = cfg.get('retention', 'foundations_sets', fallback='FDN')
    foundations_sets = {s.strip().upper() for s in foundations_sets_raw.split(',')}

    return retention, foundations_days, foundations_sets


def _parse_event_date(date_str):
    """
    Parse MTGTop8 date strings. Handles DD/MM/YY, DD/MM/YYYY, YYYY-MM-DD.
    Returns None if unparseable — events with no date are always kept.
    """
    if not date_str:
        return None
    for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _event_contains_foundations_card(conn, event_id, foundations_sets):
    """
    Return True if any deck in this event contains a card tagged as a
    Foundations-lifespan set card. Requires the cards table to have a
    set_code column (populated by Scryfall enrichment). If that column
    doesn't exist yet, returns False so we fall back to standard retention.
    """
    try:
        result = conn.execute("""
            SELECT 1
            FROM deck_cards dc
            JOIN decks d ON d.id = dc.deck_id
            JOIN cards c ON c.id = dc.card_id
            WHERE d.event_id = ?
              AND c.set_code IN ({})
            LIMIT 1
        """.format(','.join('?' * len(foundations_sets))),
            [event_id] + list(foundations_sets)
        ).fetchone()
        return result is not None
    except Exception:
        # set_code column doesn't exist yet — skip foundations check
        return False


def _get_events_to_purge(conn, format_name, cutoff, foundations_cutoff, foundations_sets):
    """
    Return a list of event IDs for a given format that fall outside their
    retention window. Standard events containing Foundations cards use the
    extended foundations_cutoff instead of the standard cutoff.
    """
    events = conn.execute(
        "SELECT id, date, name FROM events WHERE format = ?",
        (format_name,)
    ).fetchall()

    to_purge = []
    for ev in events:
        parsed = _parse_event_date(ev['date'])
        if parsed is None:
            continue  # no date — keep it

        if format_name == 'standard' and foundations_cutoff is not None:
            if parsed >= cutoff:
                continue  # within standard 3-year window — always keep
            elif parsed >= foundations_cutoff:
                # Gray zone: 3–5 years old — keep only if event has Foundations cards
                if _event_contains_foundations_card(conn, ev['id'], foundations_sets):
                    continue
                to_purge.append(ev['id'])
            else:
                # Older than 5-year extended window — purge regardless
                to_purge.append(ev['id'])
        else:
            if parsed < cutoff:
                to_purge.append(ev['id'])

    return to_purge


def purge_format(format_name, retention_days, foundations_days, foundations_sets,
                 dry_run=False):
    """
    Purge events for a single format outside its retention window.
    Returns (events_removed, decks_removed, deck_card_rows_removed).
    """
    if retention_days == 0:
        log.info(f"  {format_name}: retention disabled, skipping.")
        return 0, 0, 0

    cutoff = datetime.now() - timedelta(days=retention_days)

    foundations_cutoff = None
    if format_name == 'standard' and foundations_days > 0:
        foundations_cutoff = datetime.now() - timedelta(days=foundations_days)

    with get_connection() as conn:
        old_event_ids = _get_events_to_purge(
            conn, format_name, cutoff, foundations_cutoff, foundations_sets
        )

        if not old_event_ids:
            return 0, 0, 0

        ep = ','.join('?' * len(old_event_ids))

        old_deck_ids = [
            r['id'] for r in conn.execute(
                f"SELECT id FROM decks WHERE event_id IN ({ep})", old_event_ids
            ).fetchall()
        ]

        deck_card_count = 0
        if old_deck_ids:
            dp = ','.join('?' * len(old_deck_ids))
            deck_card_count = conn.execute(
                f"SELECT COUNT(*) FROM deck_cards WHERE deck_id IN ({dp})",
                old_deck_ids
            ).fetchone()[0]

        if not dry_run:
            if old_deck_ids:
                dp = ','.join('?' * len(old_deck_ids))
                conn.execute(
                    f"DELETE FROM deck_cards WHERE deck_id IN ({dp})", old_deck_ids
                )
            conn.execute(
                f"DELETE FROM decks WHERE event_id IN ({ep})", old_event_ids
            )
            conn.execute(
                f"DELETE FROM events WHERE id IN ({ep})", old_event_ids
            )

    return len(old_event_ids), len(old_deck_ids), deck_card_count


def purge_orphaned_cards(dry_run=False):
    """Remove cards with no deck_card references. Returns count removed."""
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
    Full maintenance pass across all (or specified) formats.
    Called automatically at the end of every scraper run.
    """
    retention_map, foundations_days, foundations_sets = _load_config()
    target_formats = formats if formats else ALL_FORMATS
    prefix = "[DRY RUN] " if dry_run else ""

    log.info(f"{prefix}--- Maintenance started ---")

    total_events = total_decks = total_deck_cards = 0

    for fmt in target_formats:
        days = retention_map.get(fmt, 1095)
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.strftime('%Y-%m-%d')

        extra = ""
        if fmt == 'standard' and foundations_days > 0:
            fc = datetime.now() - timedelta(days=foundations_days)
            extra = f" (Foundations extended to {fc.strftime('%Y-%m-%d')})"

        log.info(
            f"{prefix}  {fmt.capitalize():<10} cutoff={cutoff_str}{extra}"
        )

        ev, dk, dc = purge_format(
            fmt, days, foundations_days, foundations_sets, dry_run
        )
        total_events += ev
        total_decks += dk
        total_deck_cards += dc

        if ev > 0:
            log.info(
                f"{prefix}    Pruned {ev} events, {dk} decks, {dc} deck_card rows"
            )

    orphans = purge_orphaned_cards(dry_run)
    if orphans > 0:
        log.info(f"{prefix}  Orphaned cards removed: {orphans}")

    if total_events == 0 and orphans == 0:
        log.info(f"{prefix}  Nothing to prune — all data within retention windows.")

    log.info(
        f"{prefix}--- Maintenance complete: "
        f"{total_events} events, {total_decks} decks, "
        f"{total_deck_cards} deck_card rows, {orphans} orphaned cards removed ---"
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MTG Meta Analyzer — DB maintenance')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be pruned without deleting')
    parser.add_argument('--format', dest='fmt', choices=ALL_FORMATS,
                        help='Run maintenance for one format only')
    args = parser.parse_args()

    fmt_list = [args.fmt] if args.fmt else None
    run_maintenance(formats=fmt_list, dry_run=args.dry_run)
