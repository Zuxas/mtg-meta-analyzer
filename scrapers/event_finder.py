"""
event_finder.py -- Find upcoming sanctioned MTG events by zipcode.

Uses the Wizards of the Coast event locator GraphQL API
(api.tabletop.wizards.com/silverbeak-griffin-service/graphql).
No API key required.

For geocoding zipcode -> lat/lng: uses OpenStreetMap Nominatim (free, no key).

Usage:
    python -m scrapers.event_finder --zipcode 90210 --radius 100
    python -m scrapers.event_finder --zipcode 90210 --radius 50 --types rcq,store_championship
    python -m scrapers.event_finder --zipcode 90210 --format modern --radius 150 --days 60
    python -m scrapers.event_finder --zipcode 90210 --types rcq --format modern

Event types (WPN tag names):
    rcq              = Regional Championship Qualifiers
    store_championship = Store Championships
    modern / standard / pioneer / legacy / pauper  = FNM-level events by format
    booster_draft = Draft events
    commander     = Commander events
    all           = All event types (default)
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

GQL_URL  = "https://api.tabletop.wizards.com/silverbeak-griffin-service/graphql"
GEO_URL  = "https://nominatim.openstreetmap.org/search"

GQL_HEADERS = {
    "Content-Type": "application/json",
    "X-wotc-client": "client:event-finder version:1.0 platform:python",
}

# Human-readable names for WPN event tags
TAG_LABELS = {
    "regional_championship_qualifier": "RCQ",
    "store_championship": "Store Championship",
    "modern": "Modern",
    "standard": "Standard",
    "pioneer": "Pioneer",
    "legacy": "Legacy",
    "pauper": "Pauper",
    "booster_draft": "Booster Draft",
    "commander": "Commander",
    "commander_party": "Commander Party",
    "new_player_event": "New Player Event",
    "magic_academy": "Magic Academy",
    "magic:_the_gathering": None,   # base tag, don't display
}

# Shorthand aliases for --types arg
TYPE_ALIASES = {
    "rcq": "regional_championship_qualifier",
    "sc": "store_championship",
    "store": "store_championship",
    "draft": "booster_draft",
    "cmd": "commander",
}


def geocode_zipcode(zipcode: str, country: str = "US") -> tuple[float, float]:
    """Convert a zipcode to (lat, lng) using OpenStreetMap Nominatim."""
    params = urllib.parse.urlencode({
        "postalcode": zipcode,
        "country": country,
        "format": "json",
        "limit": 1,
    })
    url = f"{GEO_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "mtg-event-finder/1.0 (mtg-meta-analyzer)"
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        results = json.loads(r.read())
    if not results:
        raise ValueError(f"Could not geocode zipcode '{zipcode}'. Try --lat/--lng directly.")
    lat = float(results[0]["lat"])
    lng = float(results[0]["lon"])
    return lat, lng


def search_events(lat: float, lng: float, radius_miles: int = 100,
                  tags: list[str] | None = None,
                  limit: int = 50) -> list[dict]:
    """
    Search for upcoming sanctioned MTG events near a location.

    Args:
        lat, lng: Coordinates of search center
        radius_miles: Search radius in miles
        tags: WPN event tag filters (e.g. ['regional_championship_qualifier'])
              Empty list = all event types
        limit: Max events to return

    Returns:
        List of event dicts with title, date, distance, org, tags
    """
    max_meters = int(radius_miles * 1609.34)

    if tags:
        tag_filter = "tags: $tags,"
        vars_decl  = "$latitude: Float!, $longitude: Float!, $maxMeters: Int!, $tags: [String!]!, $pageSize: Int"
    else:
        tag_filter = ""
        vars_decl  = "$latitude: Float!, $longitude: Float!, $maxMeters: Int!, $pageSize: Int"

    query = f"""
    query searchEvents({vars_decl}) {{
      searchEvents(query: {{
        latitude: $latitude
        longitude: $longitude
        maxMeters: $maxMeters
        {tag_filter}
        pageSize: $pageSize
      }}) {{
        events {{
          id
          title
          scheduledStartTime
          tags
          distance
          organization {{ name }}
          eventFormat {{ id }}
          entryFee {{ amount currency }}
          isOnline
          venue {{ city state }}
        }}
        pageInfo {{ totalResults }}
      }}
    }}
    """

    variables: dict = {
        "latitude": lat,
        "longitude": lng,
        "maxMeters": max_meters,
        "pageSize": limit,
    }
    if tags:
        variables["tags"] = tags

    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(GQL_URL, data=payload, headers=GQL_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    if data.get("errors"):
        for err in data["errors"]:
            print(f"  [GraphQL error] {err.get('message','?')}", file=sys.stderr)

    return ((data.get("data") or {}).get("searchEvents") or {}).get("events") or []


def _format_event(e: dict) -> dict:
    """Convert raw event dict to a clean display record."""
    from datetime import datetime as _dt

    tags = e.get("tags", [])
    display_tags = [TAG_LABELS.get(t, t) for t in tags if TAG_LABELS.get(t) is not None]

    dist_m = e.get("distance", 0) or 0
    dist_mi = dist_m / 1609.34

    fee = e.get("entryFee") or {}
    fee_str = ""
    if fee.get("amount"):
        # API returns amount in cents (e.g. 2000 = $20.00)
        fee_str = f"${fee['amount'] / 100:.0f}"

    start_iso = e.get("scheduledStartTime") or ""
    date_str = start_iso[:10]
    weekday = ""
    time_str = ""
    if start_iso:
        try:
            # Wizards returns "...Z" -- fromisoformat (3.11+) handles "Z" directly,
            # but to be safe across 3.10/3.11 we normalize to +00:00.
            iso_norm = start_iso.replace("Z", "+00:00")
            dt_utc = _dt.fromisoformat(iso_norm)
            local = dt_utc.astimezone()  # convert to local tz
            weekday = local.strftime("%a")          # "Sat"
            # %I is 01-12; lstrip("0") yields "6:00 PM", "12:00 AM" etc.
            # Cross-platform -- Windows doesn't support %-I.
            time_str = local.strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            pass

    ef = e.get("eventFormat") or {}
    format_id = ef.get("id", "") if isinstance(ef, dict) else ""

    venue = e.get("venue") or {}
    if not isinstance(venue, dict):
        venue = {}
    city = venue.get("city", "") or ""
    state = venue.get("state", "") or ""

    return {
        "date":      date_str,
        "start_iso": start_iso,
        "weekday":   weekday,
        "time_str":  time_str,
        "title":     e.get("title", "?"),
        "store":     (e.get("organization") or {}).get("name", "?"),
        "tags":      display_tags,
        "dist_mi":   round(dist_mi, 1),
        "fee":       fee_str,
        "format_id": format_id,
        "city":      city,
        "state":     state,
        "online":    e.get("isOnline", False),
        "id":        e.get("id", ""),
        "raw_tags":  tags,
    }


def print_events(events: list[dict], format_filter: str | None = None,
                 show_online: bool = False):
    """Print events in a readable table."""
    formatted = [_format_event(e) for e in events]

    # Filter by format if specified
    if format_filter:
        formatted = [e for e in formatted
                     if format_filter.lower() in [t.lower() for t in e["raw_tags"]]]

    # Filter out online events unless requested
    if not show_online:
        formatted = [e for e in formatted if not e["online"]]

    if not formatted:
        print("  No events found matching your criteria.")
        return

    # Group by event type for cleaner display
    from collections import defaultdict
    by_type: dict = defaultdict(list)
    for e in formatted:
        primary = next(
            (t for t in e["tags"] if t not in ("Modern", "Standard", "Pioneer",
                                                 "Legacy", "Pauper", "Commander",
                                                 "Booster Draft")),
            e["tags"][0] if e["tags"] else "Event"
        )
        by_type[primary].append(e)

    for type_name, evs in sorted(by_type.items()):
        print(f"\n  [{type_name}] ({len(evs)} events)")
        print(f"  {'Date':<12} {'Distance':>8}  {'Store':<35} {'Title':<40} {'Fee'}")
        print(f"  {'-'*12} {'-'*8}  {'-'*35} {'-'*40} {'-'*5}")
        for e in sorted(evs, key=lambda x: (x["date"], x["dist_mi"])):
            store = e["store"][:35]
            title = e["title"][:40]
            print(f"  {e['date']:<12} {e['dist_mi']:>6.0f}mi  {store:<35} {title:<40} {e['fee']}")


def main():
    ap = argparse.ArgumentParser(description="Find upcoming sanctioned MTG events near you")
    loc = ap.add_mutually_exclusive_group(required=True)
    loc.add_argument("--zipcode", help="US zipcode to search near (e.g. 90210)")
    loc.add_argument("--lat",     type=float, help="Latitude (use with --lng)")
    ap.add_argument("--lng",      type=float, help="Longitude (use with --lat)")
    ap.add_argument("--radius",   type=int, default=100,
                    help="Search radius in miles (default: 100)")
    ap.add_argument("--types",    default="",
                    help="Event types to show, comma-separated (e.g. rcq,store_championship). "
                         "Omit for all types.")
    ap.add_argument("--format",   default="",
                    help="Filter by format (modern/standard/pioneer/legacy/pauper)")
    ap.add_argument("--limit",    type=int, default=100,
                    help="Max events to fetch (default: 100)")
    ap.add_argument("--online",   action="store_true",
                    help="Include online events")
    ap.add_argument("--json",     action="store_true",
                    help="Output raw JSON instead of table")
    args = ap.parse_args()

    # Resolve location
    if args.zipcode:
        print(f"Geocoding {args.zipcode}...")
        try:
            lat, lng = geocode_zipcode(args.zipcode)
            print(f"  -> {lat:.4f}, {lng:.4f}")
        except Exception as e:
            print(f"Geocoding failed: {e}")
            sys.exit(1)
    else:
        if args.lng is None:
            print("--lat requires --lng")
            sys.exit(1)
        lat, lng = args.lat, args.lng

    # Resolve event type tags
    raw_types = [t.strip() for t in args.types.split(",") if t.strip()]
    tags = [TYPE_ALIASES.get(t, t) for t in raw_types]

    print(f"Searching within {args.radius}mi for "
          f"{', '.join(tags) if tags else 'all event types'}"
          f"{' (' + args.format + ')' if args.format else ''}...")

    events = search_events(lat, lng, radius_miles=args.radius,
                           tags=tags or None, limit=args.limit)

    if args.json:
        print(json.dumps([_format_event(e) for e in events], indent=2))
        return

    if not events:
        print("No events found.")
        return

    total_label = f"{len(events)} events" + (" (limit reached)" if len(events) == args.limit else "")
    print(f"\nFound {total_label} within {args.radius}mi:")
    print_events(events, format_filter=args.format or None,
                 show_online=args.online)

    print(f"\nData from: locator.wizards.com")


if __name__ == "__main__":
    main()
