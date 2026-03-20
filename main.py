"""
MTG Meta Analyzer — entry point
Usage:
    python main.py                        # scrape Pioneer (default), 1 page, up to 10 events
    python main.py --format modern        # scrape Modern
    python main.py --format standard --pages 2 --max-events 20
    python main.py --init-only            # just set up the database
"""

import argparse
from db.database import init_db
from db.maintenance import run_maintenance
from scrapers.mtgtop8 import run as scrape_mtgtop8, FORMATS


def main():
    parser = argparse.ArgumentParser(description="MTG Meta Analyzer scraper")
    parser.add_argument(
        "--format", default="pioneer",
        choices=list(FORMATS.keys()),
        help="Format to scrape (default: pioneer)"
    )
    parser.add_argument(
        "--pages", type=int, default=1,
        help="Number of event listing pages to fetch (default: 1)"
    )
    parser.add_argument(
        "--max-events", type=int, default=10,
        help="Max events to process per run (default: 10)"
    )
    parser.add_argument(
        "--init-only", action="store_true",
        help="Only initialize the database, do not scrape"
    )
    args = parser.parse_args()

    init_db()

    if args.init_only:
        print("Database initialized. Done.")
        return

    scrape_mtgtop8(
        format_name=args.format,
        pages=args.pages,
        max_events=args.max_events,
    )

    run_maintenance(formats=[args.format])


if __name__ == "__main__":
    main()
