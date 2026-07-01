"""
polite_client.py -- shared, sanctioned, POLITE HTTP client for all scrapers.

Design: docs/superpowers/specs/2026-06-26-polite-fetch-client-design.md (sec 3)
Spec:   harness/specs/2026-06-26-modern-data-acquisition.md

ETHICS ANCHOR
-------------
Sanctioned + polite acquisition only. No proxy/UA rotation, no CAPTCHA/Cloudflare
bypass, no spoofed fingerprints, no ban evasion. A host that blocks us (mtgdecks.net)
is RESPECTED and REPLACED, never routed around. Every request carries an honest,
descriptive User-Agent that names the app and its public repository.

The per-host CIRCUIT BREAKER is the structural guarantee that we can NEVER hammer a
host into a ban again: after N consecutive 403/429 responses the breaker OPENs and all
further get()s to that host raise HostCircuitOpen with ZERO network I/O until the reset
timeout elapses. Hosts flagged blocked=True (mtgdecks.net) are born OPEN forever -- the
breaker check runs BEFORE robots.txt and before any socket is opened, so a blocked host
is never contacted at all, not even for its robots.txt.

Minimum-dependency build: only requests-cache is "nice to have". If it is absent the
module STILL LOADS and uses a hand-rolled on-disk cache that supports conditional
requests (ETag / If-Modified-Since). Backoff + breaker are hand-rolled (no tenacity /
pybreaker dependency).

Public surface
--------------
    get(url, *, host_rate=None, cache_ttl=None, conditional=True, timeout=20,
        headers=None, params=None, respect_robots=True, max_retries=4,
        force_refresh=False) -> PoliteResponse
    post(url, *, json=None, data=None, **kw) -> PoliteResponse   # cache off by default
    get_json(url, **kw) -> dict
    host_state(host) -> dict                                     # diagnostics
    HOST_CONFIG: dict                                            # per-host registry
    class PoliteClientError(Exception)
    class RobotsDisallowed(PoliteClientError)
    class HostCircuitOpen(PoliteClientError)

A PoliteResponse exposes: .status (alias .status_code), .text, .json(), .content,
.headers, .url, .from_cache (bool), .ok.
"""

from __future__ import annotations

import base64
import hashlib
import json as _json
import os
import random
import threading
import time
from urllib.parse import urlparse, urlencode
from urllib import robotparser

import requests

# --- optional dependency: requests-cache (conditional requests + storage) ----
try:
    import requests_cache  # type: ignore

    _HAVE_REQUESTS_CACHE = True
except Exception:  # pragma: no cover - environment dependent
    requests_cache = None  # type: ignore
    _HAVE_REQUESTS_CACHE = False


# ============================================================================
# Configuration
# ============================================================================

# Honest, descriptive UA naming the app + its public repo (ethics anchor).
# Repo URL only, NO personal contact, per the project's privacy preference.
DEFAULT_UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"

# Per-host config registry. Keeps call sites tiny: callers usually pass only a URL.
#   min_interval     -- floor seconds between requests to this host (rate limiter)
#   cache_ttl        -- default cache lifetime (seconds); 0 = no-store
#   accept           -- Accept header (Scryfall REQUIRES one)
#   needs_cloudscraper -- Cloudflare-fronted host; uses cloudscraper session if available
#   blocked          -- ETHICS: breaker born OPEN forever; never contacted
#   max_per_run      -- optional per-host soft cap on issued (non-cache) requests
DEFAULT_MIN_INTERVAL = 1.5  # polite default for unknown / non-Scryfall hosts

HOST_CONFIG = {
    "api.scryfall.com": dict(
        min_interval=0.1, cache_ttl=86400,
        accept="application/json;q=0.9,*/*;q=0.8",
    ),
    "scryfall.com": dict(
        min_interval=0.1, cache_ttl=86400,
        accept="application/json;q=0.9,*/*;q=0.8",
    ),
    "www.mtgtop8.com": dict(min_interval=1.5, cache_ttl=21600),
    "www.mtgo.com": dict(min_interval=1.5, cache_ttl=21600),      # NEW primary
    "magic.gg": dict(min_interval=1.5, cache_ttl=86400),          # NEW premier
    "api.mtga.untapped.gg": dict(min_interval=0.5, cache_ttl=3600),
    "mtgajson.untapped.gg": dict(min_interval=1.0, cache_ttl=604800),
    "melee.gg": dict(min_interval=1.5, cache_ttl=0, needs_cloudscraper=True),
    # ETHICS: soft-banned. Breaker OPEN forever -> never auto-fetch, not even robots.
    "mtgdecks.net": dict(min_interval=0.0, blocked=True, needs_cloudscraper=True),
}

# Circuit breaker defaults (task: N defaults to 2 consecutive 403/429).
BREAKER_FAIL_MAX = int(os.environ.get("POLITE_BREAKER_FAIL_MAX", "2"))
BREAKER_RESET_TIMEOUT = float(os.environ.get("POLITE_BREAKER_RESET_TIMEOUT", "900"))

# Per-run request cap (fixes runaway nested loops; Driver A/D in the spec).
MAX_REQUESTS_PER_RUN = int(os.environ.get("POLITE_MAX_REQUESTS_PER_RUN", "5000"))

ROBOTS_TTL = 86400  # re-read robots.txt at most once / day per host

# Cache lives under <project>/data/http_cache/ (gitignored, sibling to data/untapped/).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "data", "http_cache")
_FALLBACK_CACHE_DIR = os.path.join(_CACHE_DIR, "fallback")


# ============================================================================
# Errors
# ============================================================================

class PoliteClientError(Exception):
    """Base error for the polite client."""


class RobotsDisallowed(PoliteClientError):
    """robots.txt forbids fetching this url for our UA."""


class HostCircuitOpen(PoliteClientError):
    """Host tripped the breaker (repeated 403/429) or is blocked. Surfaced, not hidden."""


# ============================================================================
# Response wrapper (uniform across both cache backends)
# ============================================================================

class PoliteResponse:
    """Minimal response-like object. Uniform whether the body came from the
    network, a 304 revalidation, or the on-disk cache."""

    __slots__ = ("status", "status_code", "headers", "content", "url", "from_cache")

    def __init__(self, status, headers, content, url, from_cache):
        self.status = int(status)
        self.status_code = self.status  # requests-compatible alias
        self.headers = dict(headers or {})
        self.content = content if isinstance(content, (bytes, bytearray)) else (content or b"")
        self.url = url
        self.from_cache = bool(from_cache)

    @property
    def ok(self):
        return 200 <= self.status < 400

    @property
    def text(self):
        if isinstance(self.content, (bytes, bytearray)):
            return self.content.decode("utf-8", errors="replace")
        return self.content

    def json(self):
        return _json.loads(self.text)

    def __repr__(self):
        return (
            "PoliteResponse(status=%d, from_cache=%s, bytes=%d, url=%r)"
            % (self.status, self.from_cache, len(self.content or b""), self.url)
        )


# ============================================================================
# Per-host rate limiter (min-interval gate with jitter)
# ============================================================================

class _RateGate:
    """Per-host minimum-interval governor. Sleeps just long enough to honor
    max(min_interval, robots Crawl-delay), plus a small jitter so requests do
    not arrive on a perfectly regular clock (mitigates pattern detection)."""

    def __init__(self, min_interval):
        self.min_interval = float(min_interval)
        self._last = 0.0
        self._lock = threading.Lock()

    def set_floor(self, floor):
        if floor and floor > self.min_interval:
            self.min_interval = float(floor)

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                jitter = random.uniform(0, 0.3 * self.min_interval) if self.min_interval else 0
                time.sleep(wait + jitter)
            self._last = time.monotonic()


# ============================================================================
# Per-host circuit breaker (hand-rolled; no pybreaker dependency)
# ============================================================================

class _Breaker:
    """CLOSED -> OPEN after fail_max consecutive failures; OPEN rejects all calls
    for reset_timeout, then HALF-OPEN allows one probe. blocked hosts start OPEN
    with an effectively infinite reset (never closes)."""

    def __init__(self, fail_max=BREAKER_FAIL_MAX, reset_timeout=BREAKER_RESET_TIMEOUT,
                 start_open=False, permanent=False):
        self.fail_max = int(fail_max)
        self.reset_timeout = float(reset_timeout)
        self.permanent = bool(permanent)
        self.fails = 0
        self.opened_at = time.monotonic() if start_open else None
        self._lock = threading.Lock()

    def allow(self):
        """True if a call may proceed (CLOSED or HALF-OPEN probe)."""
        with self._lock:
            if self.opened_at is None:
                return True  # CLOSED
            if self.permanent:
                return False  # blocked host: never closes
            if time.monotonic() - self.opened_at >= self.reset_timeout:
                return True  # HALF-OPEN probe allowed
            return False  # OPEN, still cooling down

    def record_success(self):
        with self._lock:
            self.fails = 0
            self.opened_at = None

    def record_failure(self):
        """Returns True if this failure tripped the breaker OPEN."""
        with self._lock:
            self.fails += 1
            if self.fails >= self.fail_max and self.opened_at is None:
                self.opened_at = time.monotonic()
                return True
            # re-open immediately on a failed half-open probe
            if self.opened_at is not None:
                self.opened_at = time.monotonic()
            return self.opened_at is not None and self.fails >= self.fail_max

    def state(self):
        with self._lock:
            if self.opened_at is None:
                return "closed"
            if self.permanent:
                return "open(permanent)"
            if time.monotonic() - self.opened_at >= self.reset_timeout:
                return "half-open"
            return "open"


# ============================================================================
# Module state (per-process globals)
# ============================================================================

_lock = threading.Lock()
_gates = {}            # host -> _RateGate
_breakers = {}         # host -> _Breaker
_robots = {}           # host -> (RobotFileParser | None, fetched_at)
_sessions = {}         # host -> requests.Session / CachedSession / cloudscraper
_req_count = {"_total": 0}  # host -> issued (non-cache) request count; "_total" global


def _cfg(host):
    return HOST_CONFIG.get(host, {})


def _gate(host):
    with _lock:
        g = _gates.get(host)
        if g is None:
            cfg = _cfg(host)
            mi = cfg.get("min_interval", DEFAULT_MIN_INTERVAL)
            g = _RateGate(mi)
            _gates[host] = g
        return g


def _breaker(host):
    with _lock:
        b = _breakers.get(host)
        if b is None:
            cfg = _cfg(host)
            if cfg.get("blocked"):
                b = _Breaker(start_open=True, permanent=True)
            else:
                b = _Breaker()
            _breakers[host] = b
        return b


# ============================================================================
# Sessions (pluggable per host: CachedSession / cloudscraper / plain requests)
# ============================================================================

def _session_for(host):
    with _lock:
        s = _sessions.get(host)
        if s is not None:
            return s
        cfg = _cfg(host)
        if cfg.get("needs_cloudscraper"):
            try:
                import cloudscraper  # lazy: never block module load or the get() path

                s = cloudscraper.create_scraper()
            except Exception:
                s = requests.Session()
        elif _HAVE_REQUESTS_CACHE:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            s = requests_cache.CachedSession(
                cache_name=os.path.join(_CACHE_DIR, "http_cache"),
                backend="sqlite",
                cache_control=True,        # honor server Cache-Control
                allowable_codes=(200,),    # never cache 4xx/5xx/Cloudflare pages
                expire_after=cfg.get("cache_ttl", 3600),
                stale_if_error=False,
            )
        else:
            s = requests.Session()
        _sessions[host] = s
        return s


# ============================================================================
# Hand-rolled on-disk cache (used when requests-cache is absent)
# ============================================================================

def _cache_key(url, params):
    raw = url
    if params:
        raw = url + "?" + urlencode(sorted(params.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key):
    return os.path.join(_FALLBACK_CACHE_DIR, key + ".json")


def _cache_read(key):
    p = _cache_path(key)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return _json.load(fh)
    except Exception:
        return None


def _cache_write(key, entry):
    os.makedirs(_FALLBACK_CACHE_DIR, exist_ok=True)
    p = _cache_path(key)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        _json.dump(entry, fh)
    os.replace(tmp, p)


# ============================================================================
# robots.txt
# ============================================================================

def _robots_for(host, scheme="https"):
    """Return a cached RobotFileParser for the host, or None if robots is
    unreachable. NOTE: callers MUST check the breaker before calling this so a
    blocked host is never contacted for robots.txt."""
    now = time.time()
    with _lock:
        cached = _robots.get(host)
    if cached is not None:
        parser, fetched_at = cached
        if now - fetched_at < ROBOTS_TTL:
            return parser

    parser = robotparser.RobotFileParser()
    robots_url = "%s://%s/robots.txt" % (scheme, host)
    parser.set_url(robots_url)
    try:
        # Fetch robots ourselves so we control the UA and honor the rate gate.
        _gate(host).acquire()
        resp = requests.get(
            robots_url,
            headers={"User-Agent": DEFAULT_UA},
            timeout=15,
            allow_redirects=True,
        )
        _req_count["_total"] += 1
        _req_count[host] = _req_count.get(host, 0) + 1
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        elif resp.status_code in (401, 403):
            # Edge block / auth wall. Per failure policy: known registry hosts are
            # allowed (we only hit documented endpoints); robots treated unreachable.
            parser = None
        else:
            # 404 / other: no robots rules -> implicit allow.
            parser.parse([])  # empty ruleset -> allow all
    except Exception:
        parser = None  # network error: fall back to conservative-allow for known hosts

    with _lock:
        _robots[host] = (parser, now)
    return parser


def _robots_allows(host, url, scheme):
    parser = _robots_for(host, scheme)
    if parser is None:
        # Unreachable robots: allow ONLY hosts we know about (documented endpoints),
        # at the conservative registry rate. Never broadens crawling.
        return host in HOST_CONFIG
    # Crawl-delay feeds the rate gate floor (never go faster than asked).
    try:
        cd = parser.crawl_delay(DEFAULT_UA)
        if cd:
            _gate(host).set_floor(float(cd))
    except Exception:
        pass
    try:
        return parser.can_fetch(DEFAULT_UA, url)
    except Exception:
        return host in HOST_CONFIG


# ============================================================================
# Retry-After parsing + backoff
# ============================================================================

def _parse_retry_after(headers, body_bytes):
    """Header Retry-After (seconds) wins; else body hint 'available in N'; else None."""
    if headers:
        ra = headers.get("Retry-After")
        if ra:
            try:
                return int(float(ra))
            except Exception:
                pass  # HTTP-date form: ignore, fall through to backoff
    if body_bytes:
        import re

        m = re.search(rb"available in (\d+)", body_bytes)
        if m:
            return int(m.group(1))
    return None


def _backoff_seconds(attempt, retry_after):
    if retry_after is not None:
        return min(retry_after + 1, 60)  # honor server, +1s cushion, 60s cap
    return min(2 ** attempt, 30) + random.uniform(0, 1)  # exp + jitter


# ============================================================================
# Core network issue (rate gate + backoff + breaker) -- returns requests.Response
# ============================================================================

def _check_run_caps(host):
    cfg = _cfg(host)
    if _req_count["_total"] >= MAX_REQUESTS_PER_RUN:
        raise PoliteClientError(
            "per-run request cap reached (%d) -- aborting to avoid runaway crawl"
            % MAX_REQUESTS_PER_RUN
        )
    cap = cfg.get("max_per_run")
    if cap is not None and _req_count.get(host, 0) >= cap:
        raise PoliteClientError(
            "per-host request cap reached for %s (%d)" % (host, cap)
        )


def _issue(session, method, url, host, *, params, data, json_body, headers, timeout,
           max_retries):
    """Issue one logical request with backoff on 429/503. Returns a requests
    Response. Trips the breaker on 403 / exhausted-429. Does NOT consult the
    cache (the caller owns caching in the fallback path; CachedSession owns it
    in the requests-cache path)."""
    breaker = _breaker(host)
    gate = _gate(host)
    attempt = 0
    while True:
        _check_run_caps(host)
        gate.acquire()
        resp = session.request(
            method, url, params=params, data=data, json=json_body,
            headers=headers, timeout=timeout,
        )
        # Count only true network hits (CachedSession may have served from cache).
        if not getattr(resp, "from_cache", False):
            _req_count["_total"] += 1
            _req_count[host] = _req_count.get(host, 0) + 1

        code = resp.status_code

        if code in (200, 304) or (200 <= code < 400):
            breaker.record_success()
            return resp

        if code in (429, 503) and attempt < max_retries:
            body = resp.content[:300] if resp.content else b""
            ra = _parse_retry_after(resp.headers, body)
            wait = _backoff_seconds(attempt, ra)
            print(
                "[polite_client] %s %d on %s -- backing off %.1fs (attempt %d/%d)"
                % (method, code, host, wait, attempt + 1, max_retries)
            )
            time.sleep(wait)
            attempt += 1
            continue

        if code in (403, 429):
            # 403 never retried; 429 here means retries exhausted. Both feed breaker.
            tripped = breaker.record_failure()
            if tripped:
                print(
                    "[polite_client] !! CIRCUIT BREAKER OPEN for %s after %d consecutive "
                    "403/429 -- all further requests to this host are BLOCKED (no network) "
                    "until cooldown. Backing off; not hammering into a ban." % (host, breaker.fails)
                )
                raise HostCircuitOpen(
                    "host blocked, backing off: %s (breaker OPEN after %d consecutive 403/429)"
                    % (host, breaker.fails)
                )
            raise PoliteClientError("HTTP %d from %s (no retry)" % (code, host))

        # Other 4xx/5xx: surface, no breaker, no cache.
        raise PoliteClientError("HTTP %d from %s: %s" % (code, host, url))


# ============================================================================
# Public API
# ============================================================================

def _prepare_headers(host, headers, accept_default):
    h = {"User-Agent": DEFAULT_UA}
    cfg = _cfg(host)
    accept = cfg.get("accept") or accept_default
    if accept:
        h["Accept"] = accept
    if headers:
        h.update(headers)
    return h


def _guard_host(host):
    """Breaker gate -- runs BEFORE robots and BEFORE any network I/O.
    A blocked host (mtgdecks.net) raises here, never contacted at all."""
    cfg = _cfg(host)
    breaker = _breaker(host)
    if not breaker.allow():
        if cfg.get("blocked"):
            print(
                "[polite_client] !! BLOCKED HOST %s -- refusing request (ethics: respected "
                "and replaced, never routed around). No network I/O performed." % host
            )
            raise HostCircuitOpen("host blocked (permanent), backing off: %s" % host)
        print(
            "[polite_client] !! CIRCUIT OPEN for %s -- refusing request (no network) until "
            "cooldown." % host
        )
        raise HostCircuitOpen("host blocked, backing off: %s (circuit OPEN)" % host)


def get(url, *, host_rate=None, cache_ttl=None, conditional=True, params=None,
        headers=None, timeout=20, respect_robots=True, max_retries=4,
        force_refresh=False):
    """Polite GET. Returns a PoliteResponse with a .from_cache flag.

    Lifecycle: breaker gate (blocked/OPEN -> raise, no network) -> robots gate
    -> fresh-cache short-circuit -> rate gate -> network (with backoff) -> cache.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"
    cfg = _cfg(host)

    # 1. Circuit breaker FIRST (ethics: blocked host never contacted, not even robots).
    _guard_host(host)

    # Optional per-call rate override.
    if host_rate:
        _gate(host).set_floor(1.0 / host_rate if host_rate > 0 else 0)

    # 2. robots gate.
    if respect_robots:
        if not _robots_allows(host, url, scheme):
            raise RobotsDisallowed("robots.txt disallows %s for our UA" % url)

    ttl = cfg.get("cache_ttl", 3600) if cache_ttl is None else cache_ttl
    accept_default = cfg.get("accept")
    req_headers = _prepare_headers(host, headers, accept_default)
    session = _session_for(host)

    # ---- requests-cache path: the session owns cache + conditional requests ----
    if _HAVE_REQUESTS_CACHE and not cfg.get("needs_cloudscraper"):
        # force_refresh -> revalidate (CachedSession honors refresh kwarg).
        if force_refresh and hasattr(session, "cache"):
            try:
                session.cache.delete(urls=[url])
            except Exception:
                pass
        resp = _issue(
            session, "GET", url, host, params=params, data=None, json_body=None,
            headers=req_headers, timeout=timeout, max_retries=max_retries,
        )
        return PoliteResponse(
            resp.status_code, resp.headers, resp.content, url,
            from_cache=getattr(resp, "from_cache", False),
        )

    # ---- fallback path: hand-rolled on-disk cache (current environment) ----
    key = _cache_key(url, params)
    entry = None if force_refresh else _cache_read(key)
    now = time.time()

    # 3a. Fresh cache short-circuit -- BEFORE rate gate, BEFORE any network.
    if entry is not None and ttl and (now - entry.get("fetched_at", 0) < ttl):
        return PoliteResponse(
            entry["status"], entry.get("headers", {}),
            base64.b64decode(entry.get("body_b64", "")), url, from_cache=True,
        )

    # 3b. Stale entry with a validator -> conditional revalidation (304 reuse).
    cond_headers = dict(req_headers)
    if entry is not None and conditional:
        if entry.get("etag"):
            cond_headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            cond_headers["If-Modified-Since"] = entry["last_modified"]

    resp = _issue(
        session, "GET", url, host, params=params, data=None, json_body=None,
        headers=cond_headers, timeout=timeout, max_retries=max_retries,
    )

    if resp.status_code == 304 and entry is not None:
        # Revalidated: reuse stored body, refresh the freshness clock.
        entry["fetched_at"] = now
        _cache_write(key, entry)
        return PoliteResponse(
            entry["status"], entry.get("headers", {}),
            base64.b64decode(entry.get("body_b64", "")), url, from_cache=True,
        )

    # Fresh 200: store (only 200s are cached, matching requests-cache policy).
    if resp.status_code == 200 and ttl:
        new_entry = {
            "status": 200,
            "headers": dict(resp.headers),
            "body_b64": base64.b64encode(resp.content or b"").decode("ascii"),
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "fetched_at": now,
        }
        try:
            _cache_write(key, new_entry)
        except Exception:
            pass

    return PoliteResponse(resp.status_code, resp.headers, resp.content, url, from_cache=False)


def post(url, *, json=None, data=None, host_rate=None, headers=None, timeout=20,
         respect_robots=True, max_retries=4, params=None):
    """Polite POST. Same governor (breaker/robots/rate/backoff). Cache OFF by
    default -- POST is how melee.gg / analytics queries are issued."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"
    cfg = _cfg(host)

    _guard_host(host)
    if host_rate:
        _gate(host).set_floor(1.0 / host_rate if host_rate > 0 else 0)
    if respect_robots and not _robots_allows(host, url, scheme):
        raise RobotsDisallowed("robots.txt disallows %s for our UA" % url)

    req_headers = _prepare_headers(host, headers, cfg.get("accept"))
    session = _session_for(host)
    resp = _issue(
        session, "POST", url, host, params=params, data=data, json_body=json,
        headers=req_headers, timeout=timeout, max_retries=max_retries,
    )
    return PoliteResponse(resp.status_code, resp.headers, resp.content, url,
                          from_cache=getattr(resp, "from_cache", False))


def get_json(url, **kw):
    """get(url).json() convenience."""
    return get(url, **kw).json()


def host_state(host):
    """Diagnostics snapshot for a host."""
    breaker = _breakers.get(host)
    gate = _gates.get(host)
    return {
        "host": host,
        "config": _cfg(host),
        "breaker": breaker.state() if breaker else "uninitialized",
        "breaker_fails": breaker.fails if breaker else 0,
        "min_interval": gate.min_interval if gate else _cfg(host).get("min_interval", DEFAULT_MIN_INTERVAL),
        "requests_issued": _req_count.get(host, 0),
        "robots_cached": host in _robots,
        "backend": "requests-cache" if _HAVE_REQUESTS_CACHE else "fallback-ondisk",
    }


def run_stats():
    """Total issued (non-cache) requests this run."""
    return {"total": _req_count["_total"],
            "per_host": {k: v for k, v in _req_count.items() if k != "_total"}}


# ============================================================================
# Self-test: ONE polite GET to a well-documented, generous endpoint.
# ============================================================================

if __name__ == "__main__":
    TARGET = "https://api.scryfall.com/bulk-data"
    print("=" * 70)
    print("polite_client self-test")
    print("requests-cache available:", _HAVE_REQUESTS_CACHE,
          "(backend: %s)" % ("requests-cache" if _HAVE_REQUESTS_CACHE else "fallback on-disk cache"))
    print("User-Agent:", DEFAULT_UA)
    print("Target:", TARGET, "(documented, generous limits)")
    print("=" * 70)

    # First call: should hit the network (from_cache=False).
    r1 = get(TARGET)
    print("\n[call 1] status=%d  from_cache=%s  bytes=%d"
          % (r1.status, r1.from_cache, len(r1.content)))
    try:
        data = r1.json()
        items = data.get("data", [])
        print("         parsed JSON ok: %d bulk-data entries" % len(items))
        if items:
            print("         e.g. %s" % ", ".join(sorted(d.get("type", "?") for d in items)[:6]))
    except Exception as exc:
        print("         (json parse skipped: %s)" % exc)

    # Second call: identical URL -> should be served from cache (from_cache=True),
    # issuing ZERO additional network requests.
    before = _req_count["_total"]
    r2 = get(TARGET)
    after = _req_count["_total"]
    print("\n[call 2] status=%d  from_cache=%s  bytes=%d  (network requests added: %d)"
          % (r2.status, r2.from_cache, len(r2.content), after - before))

    print("\nrun_stats:", run_stats())
    print("host_state(api.scryfall.com):", host_state("api.scryfall.com"))

    # Demonstrate the ethics breaker without any network I/O.
    print("\n[ethics] mtgdecks.net breaker state:", host_state("mtgdecks.net")["breaker"])
    try:
        get("https://mtgdecks.net/Modern")
        print("[ethics] ERROR: blocked host was contacted!")
    except HostCircuitOpen as exc:
        print("[ethics] blocked host correctly refused with NO network I/O:")
        print("         ", exc)

    ok = (r1.status == 200 and r2.from_cache and (after - before) == 0)
    print("\nSELF-TEST", "PASS" if ok else "CHECK OUTPUT")
