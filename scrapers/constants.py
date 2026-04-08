"""
Shared constants for all scrapers — headers, format mappings, delays.

Import from here instead of defining per-scraper.
"""

# ── HTTP Headers ──────────────────────────────────────────────────────────
# Chrome-like User-Agent shared by all request-based scrapers.
# cloudscraper-based scrapers (mtgmelee, mtgdecks) handle their own headers.

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS_MINIMAL = {
    "User-Agent": USER_AGENT,
}

HEADERS_FULL = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── Rate Limiting ─────────────────────────────────────────────────────────

DELAY_DEFAULT = 1.5      # seconds between requests (mtgtop8, mtgmelee)
DELAY_SCRYFALL = 0.1     # Scryfall API rate limit
DELAY_MYTHICSPOILER = 1.0

# ── Format Mappings ───────────────────────────────────────────────────────
# Each source uses different format identifiers.

FORMATS_MTGTOP8 = {
    "standard": "ST",
    "pioneer":  "PI",
    "modern":   "MO",
    "legacy":   "LE",
    "vintage":  "VI",
    "pauper":   "PAU",
}

FORMATS_DISPLAY = {
    "standard": "Standard",
    "pioneer":  "Pioneer",
    "modern":   "Modern",
    "legacy":   "Legacy",
    "vintage":  "Vintage",
    "pauper":   "Pauper",
}

# ── Base URLs ─────────────────────────────────────────────────────────────

URL_MTGTOP8 = "https://www.mtgtop8.com"
URL_MTGDECKS = "https://mtgdecks.net"
URL_MELEE = "https://melee.gg"
URL_MYTHICSPOILER = "https://mythicspoiler.com"
