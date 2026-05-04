"""
scrapers/guides.py — Import MTG deck guides from the 'Skill Issue Magic' Google Sheet.

Source spreadsheet:
  https://docs.google.com/spreadsheets/d/1xuOdKC3-LzH-wgmAnwsN1bxJZEEc00HqftWmI-RfA-Q

Columns in sheet: Date, Link, Format, Deck, Type, Author, Source, Comment

Run:
    python -m scrapers.guides
"""
import csv
import io
import os
import sys
from datetime import datetime

_SHEET_ID = "1xuOdKC3-LzH-wgmAnwsN1bxJZEEc00HqftWmI-RfA-Q"
# gid=0 is the main tab. Try additional tabs if they exist.
_SHEET_TABS = [
    f"https://docs.google.com/spreadsheets/d/{_SHEET_ID}/export?format=csv&gid=0",
    f"https://docs.google.com/spreadsheets/d/{_SHEET_ID}/export?format=csv&gid=1",
    f"https://docs.google.com/spreadsheets/d/{_SHEET_ID}/export?format=csv&gid=2",
]
# Keep the original single URL for backwards compatibility
_CSV_URL  = _SHEET_TABS[0]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_tab(url: str) -> list[dict]:
    """Fetch a single sheet tab CSV. Returns [] on error (tab may not exist)."""
    import requests
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []
    lines = resp.text.splitlines()
    # Row 0 = metadata, row 1 = real headers, row 2+ = data
    if len(lines) < 2:
        return []
    # Detect tabs that don't exist: Google returns a single-row HTML error page
    if "<html" in lines[0].lower():
        return []
    content = "\n".join(lines[1:])   # drop the metadata row
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        rows.append({k.strip(): (v.strip() if v else "") for k, v in row.items()})
    return rows


def fetch_guides_csv() -> list[dict]:
    """Download all sheet tabs as CSV and return combined list of row dicts.

    Row 0 of each tab is a metadata row; row 1 is the real header.
    Tabs that don't exist are silently skipped.
    """
    all_rows: list[dict] = []
    seen_urls: set[str] = set()
    for url in _SHEET_TABS:
        for row in _fetch_tab(url):
            link = row.get("Link", "").strip()
            if link and link not in seen_urls:
                seen_urls.add(link)
                all_rows.append(row)
    return all_rows


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def run_scraper():
    from db.database import get_connection, init_db

    init_db()
    conn = get_connection()

    print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Fetching Skill Issue Magic guide database…")

    try:
        rows = fetch_guides_csv()
    except Exception as e:
        print(f"  [error] Could not fetch spreadsheet: {e}")
        conn.close()
        return

    print(f"  {len(rows)} entries found in spreadsheet.")

    added   = 0
    skipped = 0
    now     = datetime.now().isoformat(timespec="seconds")

    try:
        for row in rows:
            url = row.get("Link", "").strip()
            if not url or not url.startswith("http"):
                continue

            fmt = row.get("Format", "").strip().lower()
            # Normalise format names to match the rest of the app
            fmt_map = {
                "std": "standard", "standard": "standard",
                "pio": "pioneer",  "pioneer": "pioneer",
                "mod": "modern",   "modern": "modern",
                "leg": "legacy",   "legacy": "legacy",
            }
            fmt = fmt_map.get(fmt, fmt)

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO guides
                        (date, url, format, archetype, type, author, source, comment, added_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("Date",    ""),
                        url,
                        fmt,
                        row.get("Deck",    ""),
                        row.get("Type",    ""),
                        row.get("Author",  ""),
                        row.get("Source",  ""),
                        row.get("Comment", ""),
                        now,
                    ),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  [skip] {url}: {e}")

        conn.commit()
    finally:
        conn.close()
    print(f"  Added: {added} new guides | Already in DB: {skipped}")
    print("Done.")
    return {"added": added, "skipped": skipped, "total_in_sheet": len(rows)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_scraper()
