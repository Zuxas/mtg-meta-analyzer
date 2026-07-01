"""
mtgo_decklists.py -- FIRST-PARTY MTGO official decklist scraper.

Source : https://www.mtgo.com/decklists  (WotC / Daybreak; robots-clean, sanctioned)
Spec   : harness/specs/2026-06-26-modern-data-acquisition.md  (rank 1 PRIMARY, step S7)
Fetch  : ALWAYS through scrapers.polite_client.get (per-host >=1.5s gate, robots-checked,
         circuit-breaker protected, honest descriptive User-Agent). NEVER raw requests.

WHY MTGO IS THE PRIMARY
-----------------------
mtgo.com is the literal first-party feed that the (now soft-banned) mtgdecks aggregator
was re-publishing -- weekly Modern Challenges / Preliminaries / Leagues, full decklists.
Each event page embeds a single JSON blob carrying EVERY deck, so one HTTP request yields
the whole event (NO one-request-per-deck fan-out -- that pattern is what got us banned).

PUBLIC SURFACE
--------------
    discover_recent(format="Modern", limit=1) -> list[str]   # event URLs (ONE index request)
    fetch_event(url) -> dict                                  # parsed event (ONE request)
    map_to_db_rows(event) -> dict                             # pure: rows that WOULD be inserted
    PARSE markers / failure reporting are explicit (no retry loops).

The page blob shape is treated as UNTRUSTED (the site restructured ~2024-06 and the spec
hedges: "window.MTGO.decklists.data OR SIMILAR"). The extractor probes several known
markers + the Next.js __NEXT_DATA__ island, and key access is defensive: on any miss it
returns a structured failure with a status + HTML snippet + the markers tried, rather than
guessing or retrying.
"""

from __future__ import annotations

import json
import re

# polite client -- works both as `python -m scrapers.mtgo_decklists` and direct import.
try:
    from scrapers import polite_client
except ImportError:  # pragma: no cover - direct-script fallback
    import polite_client  # type: ignore

# polite_client raises these; we surface them as the test result, never fight them.
PoliteClientError = polite_client.PoliteClientError
RobotsDisallowed = polite_client.RobotsDisallowed
HostCircuitOpen = polite_client.HostCircuitOpen

BASE = "https://www.mtgo.com"          # NOTE: keep the www -- HOST_CONFIG registers www.mtgo.com
INDEX_URL = BASE + "/decklists"
SOURCE = "mtgo"

# Format slugs/names we accept as "Modern" (case-insensitive substring on slug or title).
_MODERN_RE = re.compile(r"\bmodern\b", re.IGNORECASE)

# Blob assignment markers we know MTGO has used. Order = preference.
_BLOB_ASSIGN_MARKERS = (
    "window.MTGO.decklists.data",
    "MTGO.decklists.data",
    "window.MTGO.decklists",
    "decklists.data",
)


# ============================================================================
# Generic / defensive accessors (blob shape is UNTRUSTED)
# ============================================================================

def _first_key(d, *keys, default=None):
    """Return d[k] for the first present, non-empty k. Case-insensitive fallback."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, "", [], {}):
            return v
    return default


def _norm_date(value):
    """Pull YYYY-MM-DD out of an ISO string / 'MM/DD/YYYY' / slug fragment."""
    if not value:
        return ""
    s = str(value)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        mm, dd, yy = m.group(1), m.group(2), m.group(3)
        return "%s-%s-%s" % (yy, mm.zfill(2), dd.zfill(2))
    return ""


def _event_type_from(name):
    """Map a human event name/slug to the project's event_type vocabulary."""
    n = (name or "").lower()
    if "challenge" in n:
        if "64" in n:
            return "mtgo_challenge_64"
        if "32" in n:
            return "mtgo_challenge_32"
        return "mtgo_challenge_64"
    if "prelim" in n:
        return "mtgo_preliminary"
    if "league" in n:
        return "mtgo_league"
    if "showcase" in n or "qualifier" in n or "championship" in n:
        return "mtgo_showcase"
    return "mtgo"


def _slug_of(url):
    """Last non-empty path segment of an event URL (stable, unique source_id)."""
    path = url.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else path


# ============================================================================
# Blob extraction (robust: balanced-brace assignment + __NEXT_DATA__ island)
# ============================================================================

def _extract_balanced_json(text, start):
    """From the first '{' at/after `start`, return the balanced-brace JSON substring
    (string-literal aware so braces inside quotes don't miscount)."""
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def _find_blob(html):
    """Try every known marker, then __NEXT_DATA__. Returns (data_dict, marker_used)
    or (None, list_of_markers_tried)."""
    tried = []
    for marker in _BLOB_ASSIGN_MARKERS:
        tried.append(marker)
        idx = html.find(marker)
        if idx < 0:
            continue
        eq = html.find("=", idx + len(marker))
        if eq < 0:
            continue
        candidate = _extract_balanced_json(html, eq + 1)
        if not candidate:
            continue
        try:
            return json.loads(candidate), marker
        except json.JSONDecodeError:
            continue

    # Next.js island: <script id="__NEXT_DATA__" type="application/json">{...}</script>
    tried.append("__NEXT_DATA__")
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if m:
        try:
            return json.loads(m.group(1)), "__NEXT_DATA__"
        except json.JSONDecodeError:
            pass

    return None, tried


def _dig_for_decklists(obj, _depth=0):
    """Recursively locate the per-deck list inside an arbitrarily-nested blob
    (handles __NEXT_DATA__ wrappers like props.pageProps.decklists)."""
    if _depth > 8 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        for key in ("decklists", "decks", "Decklists", "Decks"):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in obj.values():
            found = _dig_for_decklists(v, _depth + 1)
            if found is not None:
                return found
    else:
        for v in obj:
            found = _dig_for_decklists(v, _depth + 1)
            if found is not None:
                return found
    return None


def _dig_for_meta(obj, _depth=0):
    """Find the dict that carries event name/date/format (the level holding the
    decklists list, or any dict with a recognizable name+date)."""
    if _depth > 8 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        has_decks = any(
            isinstance(obj.get(k), list) for k in ("decklists", "decks", "Decklists", "Decks")
        )
        has_name = _first_key(obj, "description", "name", "title", "event_name", "event_title")
        if has_decks and has_name:
            return obj
        for v in obj.values():
            found = _dig_for_meta(v, _depth + 1)
            if found is not None:
                return found
    else:
        for v in obj:
            found = _dig_for_meta(v, _depth + 1)
            if found is not None:
                return found
    return None


# ============================================================================
# Per-deck card extraction (untrusted card shapes)
# ============================================================================

def _card_name(entry):
    """Pull a card name from a card entry, however it is nested."""
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        return ""
    attrs = entry.get("card_attributes") or entry.get("attributes") or {}
    name = _first_key(attrs, "card_name", "name", "cardname")
    if name:
        return str(name).strip()
    name = _first_key(entry, "card_name", "cardname", "name", "card")
    if isinstance(name, dict):
        return _card_name(name)
    return str(name).strip() if name else ""


def _card_qty(entry):
    if not isinstance(entry, dict):
        return 1
    q = _first_key(entry, "qty", "quantity", "count", "number", default=1)
    try:
        return int(q)
    except (ValueError, TypeError):
        return 1


def _accumulate(card_list):
    """Turn a list of card entries into {name: qty}."""
    out = {}
    if not isinstance(card_list, list):
        return out
    for entry in card_list:
        name = _card_name(entry)
        if not name:
            continue
        out[name] = out.get(name, 0) + _card_qty(entry)
    return out


def _deck_board_lists(deck):
    """Return (main_list, side_list) probing the known key variants."""
    main = _first_key(
        deck, "main_deck", "maindeck", "mainboard", "main", "deck", "Maindeck", default=[]
    )
    side = _first_key(
        deck, "sideboard_deck", "sideboard", "side", "sb", "Sideboard", default=[]
    )
    return (main if isinstance(main, list) else [],
            side if isinstance(side, list) else [])


def _parse_deck(deck, placement_fallback):
    player = _first_key(
        deck, "player", "loginid", "login_name", "display_name", "name", "screen_name",
        default="",
    )
    if isinstance(player, dict):
        player = _first_key(player, "name", "loginid", "display_name", default="")
    placement = _first_key(deck, "rank", "place", "placement", "finish", default=None)
    try:
        placement = int(placement) if placement is not None else placement_fallback
    except (ValueError, TypeError):
        placement = placement_fallback
    main_list, side_list = _deck_board_lists(deck)
    return {
        "player": str(player).strip(),
        "placement": placement,
        "mainboard": _accumulate(main_list),
        "sideboard": _accumulate(side_list),
    }


# ============================================================================
# Public: fetch_event
# ============================================================================

def fetch_event(url):
    """Fetch ONE MTGO event page and parse the embedded JSON blob.

    Returns a structured dict:
      success: {ok:True, source, source_id, url, name, date, format, event_type,
                blob_marker, deck_count, decks:[{player,placement,mainboard,sideboard},...]}
      failure: {ok:False, reason, status, url, markers_tried, snippet}

    Exactly ONE network request (then served from cache on re-run). No retry loop.
    """
    try:
        resp = polite_client.get(url)
    except (RobotsDisallowed, HostCircuitOpen, PoliteClientError) as exc:
        return {
            "ok": False, "reason": "polite_client_refused",
            "error": "%s: %s" % (type(exc).__name__, exc),
            "status": None, "url": url, "markers_tried": list(_BLOB_ASSIGN_MARKERS),
            "snippet": "",
        }

    html = resp.text
    if resp.status != 200:
        return {
            "ok": False, "reason": "http_status", "status": resp.status, "url": url,
            "markers_tried": [], "snippet": html[:400],
        }

    data, marker_or_tried = _find_blob(html)
    if data is None:
        return {
            "ok": False, "reason": "no_blob_found", "status": resp.status, "url": url,
            "markers_tried": marker_or_tried,
            "snippet": _diagnostic_snippet(html),
        }

    decklists = _dig_for_decklists(data)
    meta = _dig_for_meta(data) or (data if isinstance(data, dict) else {})

    if not decklists:
        return {
            "ok": False, "reason": "no_decklists_in_blob", "status": resp.status, "url": url,
            "markers_tried": [marker_or_tried],
            "blob_top_keys": sorted(data.keys()) if isinstance(data, dict) else [],
            "snippet": _diagnostic_snippet(html),
        }

    name = _first_key(meta, "description", "name", "title", "event_name", "event_title",
                      default="") or _slug_of(url)
    date = _norm_date(
        _first_key(meta, "starttime", "date", "start_date", "publish_date", "event_date")
    ) or _norm_date(_slug_of(url))
    fmt_raw = _first_key(meta, "format", "formatname", "Format", default="")

    decks = [_parse_deck(d, i + 1) for i, d in enumerate(decklists)]

    return {
        "ok": True,
        "source": SOURCE,
        "source_id": _slug_of(url),
        "url": url,
        "name": str(name).strip(),
        "date": date,
        "format": str(fmt_raw).strip().lower() or "modern",
        "event_type": _event_type_from(str(name) + " " + _slug_of(url)),
        "blob_marker": marker_or_tried,
        "from_cache": getattr(resp, "from_cache", False),
        "deck_count": len(decks),
        "decks": decks,
    }


def _diagnostic_snippet(html, n=600):
    """A useful HTML snippet for the failure report: prefer any <script> context that
    mentions 'decklist'/'MTGO', else the page <title> + head."""
    low = html.lower()
    for needle in ("decklist", "mtgo.decklists", "window.mtgo"):
        idx = low.find(needle)
        if idx >= 0:
            start = max(0, idx - 120)
            return html[start:start + n].replace("\n", " ")
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    title = m.group(1).strip() if m else "(no <title>)"
    return ("title=%r | head: %s" % (title, html[:n].replace("\n", " ")))


# ============================================================================
# Public: discover_recent
# ============================================================================

def discover_recent(format="Modern", limit=1):
    """Parse the MTGO decklists index (ONE request) and return up to `limit` event
    URLs whose slug/title matches the requested format (Modern by default).

    Returns list[str]. On refusal/failure returns [] (caller/test reports the reason
    from the raised-and-caught exception via the printed diagnostics)."""
    want_modern = bool(_MODERN_RE.search(format or ""))
    try:
        resp = polite_client.get(INDEX_URL)
    except (RobotsDisallowed, HostCircuitOpen, PoliteClientError) as exc:
        print("[mtgo] discover_recent refused: %s: %s" % (type(exc).__name__, exc))
        return []

    if resp.status != 200:
        print("[mtgo] discover_recent HTTP %s on %s" % (resp.status, INDEX_URL))
        return []

    html = resp.text
    urls = []
    seen = set()
    # Anchor hrefs that point at an individual event decklist page.
    for m in re.finditer(
        r'href=["\'](?P<href>[^"\']*?/decklist/[^"\']+)["\'][^>]*>(?P<text>.*?)</a>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        href = m.group("href")
        text = re.sub(r"<[^>]+>", " ", m.group("text"))
        full = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
        # keep www host (HOST_CONFIG registers www.mtgo.com)
        full = full.replace("https://mtgo.com", "https://www.mtgo.com")
        if full in seen:
            continue
        slug = _slug_of(full)
        hay = (slug + " " + text).lower()
        if want_modern and not _MODERN_RE.search(hay):
            continue
        seen.add(full)
        urls.append(full)
        if len(urls) >= limit:
            break

    if not urls:
        print("[mtgo] discover_recent: no %s event links found in index (parsed %d bytes). "
              "Anchor pattern needed: href*='/decklist/'." % (format, len(html)))
    return urls


# ============================================================================
# Public: map_to_db_rows  (PURE -- returns rows that WOULD be inserted; no DB writes)
# ============================================================================

def map_to_db_rows(event):
    """Map a parsed fetch_event() dict to the events/decks/deck_cards row shape.

    Returns:
      {
        "event":      {source, source_id, name, date, format, event_type, url},
        "decks":      [{source_id, player, archetype, placement, url}, ...],
        "deck_cards": [{deck_source_id, card_name, quantity, is_sideboard}, ...],
      }
    Mirrors db.database.upsert_event / upsert_deck / insert_deck_cards args.
    NO connection is opened; nothing is written. Real DB writes happen in the
    orchestrator, not here.
    """
    if not event.get("ok"):
        return {"event": None, "decks": [], "deck_cards": [], "error": "event not parsed ok"}

    event_row = {
        "source": SOURCE,
        "source_id": event["source_id"],
        "name": event["name"],
        "date": event["date"],
        "format": event["format"],
        "event_type": event["event_type"],
        "url": event["url"],
    }

    deck_rows = []
    card_rows = []
    used_ids = set()
    for i, dk in enumerate(event["decks"]):
        # deck source_id must satisfy UNIQUE(event_id, source_id). Prefer player handle;
        # fall back to placement; disambiguate collisions deterministically.
        base = dk["player"] or ("deck-%d" % (dk["placement"] or i + 1))
        deck_sid = base
        n = 2
        while deck_sid in used_ids:
            deck_sid = "%s#%d" % (base, n)
            n += 1
        used_ids.add(deck_sid)

        deck_rows.append({
            "source_id": deck_sid,
            "player": dk["player"],
            "archetype": "",            # MTGO blob carries no archetype; classifier fills later
            "placement": dk["placement"],
            "url": event["url"],        # MTGO has no per-deck permalink; event URL anchors it
        })
        for name, qty in dk["mainboard"].items():
            card_rows.append({"deck_source_id": deck_sid, "card_name": name,
                              "quantity": qty, "is_sideboard": 0})
        for name, qty in dk["sideboard"].items():
            card_rows.append({"deck_source_id": deck_sid, "card_name": name,
                              "quantity": qty, "is_sideboard": 1})

    return {"event": event_row, "decks": deck_rows, "deck_cards": card_rows}


# ============================================================================
# POLITE TEST: discover ONE Modern event, fetch it, print parse + mapped rows.
#   At most 2 CONTENT requests (+1 robots.txt the polite client fetches once).
#   No retry loop: a parse failure prints the precise blocker and stops.
# ============================================================================

def _selftest():
    print("=" * 74)
    print("mtgo_decklists polite test -- discover 1 Modern event, fetch it, map rows")
    print("polite_client backend:", "requests-cache" if polite_client._HAVE_REQUESTS_CACHE
          else "fallback on-disk cache")
    print("User-Agent:", polite_client.DEFAULT_UA)
    print("=" * 74)

    print("\n[1/2] discover_recent('Modern', limit=1) -- ONE index request")
    urls = discover_recent("Modern", limit=1)
    print("      -> %d url(s): %s" % (len(urls), urls))
    if not urls:
        print("\nRESULT: discover found no Modern event URL. See message above for the "
              "selector needed. Stopping (no retry loop).")
        print("\nrun_stats:", polite_client.run_stats())
        return

    target = urls[0]
    print("\n[2/2] fetch_event(%s) -- ONE event request" % target)
    event = fetch_event(target)

    if not event.get("ok"):
        print("\nRESULT: PARSE FAILED -- reporting exactly what we got (no retry):")
        for k in ("reason", "status", "url", "blob_top_keys", "markers_tried", "error"):
            if k in event:
                print("   %-14s %s" % (k + ":", event[k]))
        if event.get("snippet"):
            print("   snippet:       %s" % event["snippet"][:500])
        print("\nWhat is needed: a working blob marker (one of %s) or the __NEXT_DATA__ "
              "island, then keys for event name/date/format + a decklists[] list with "
              "per-deck player + main_deck/sideboard card entries."
              % list(_BLOB_ASSIGN_MARKERS))
        print("\nrun_stats:", polite_client.run_stats())
        return

    print("\n--- PARSED EVENT ---")
    for k in ("name", "date", "format", "event_type", "source_id", "blob_marker",
              "deck_count", "from_cache"):
        print("   %-12s %s" % (k + ":", event[k]))

    print("\n--- FIRST 2 DECKS ---")
    for dk in event["decks"][:2]:
        print("   [%s] %-20s  main=%d (%d unique)  side=%d (%d unique)" % (
            dk["placement"], dk["player"][:20],
            sum(dk["mainboard"].values()), len(dk["mainboard"]),
            sum(dk["sideboard"].values()), len(dk["sideboard"]),
        ))
        sample = list(dk["mainboard"].items())[:4]
        print("        e.g. " + ", ".join("%dx %s" % (q, n) for n, q in sample))

    rows = map_to_db_rows(event)
    print("\n--- MAPPED DB ROWS (would-be inserts; NOTHING written) ---")
    print("   events row   :", rows["event"])
    print("   decks rows   : %d  (first: %s)" % (
        len(rows["decks"]), rows["decks"][0] if rows["decks"] else None))
    print("   deck_cards   : %d rows total" % len(rows["deck_cards"]))
    for r in rows["deck_cards"][:4]:
        print("        ", r)

    print("\nrun_stats:", polite_client.run_stats())
    print("host_state(www.mtgo.com):", polite_client.host_state("www.mtgo.com"))
    print("\nSELF-TEST PASS")


if __name__ == "__main__":
    _selftest()
