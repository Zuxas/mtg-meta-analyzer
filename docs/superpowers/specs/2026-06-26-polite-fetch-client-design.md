# Polite-Fetch Client — Design Spec

Date: 2026-06-26
Status: PROPOSAL (research + design only; no code written, no scrapers changed)
Scope: a single shared HTTP client (`mtg-meta-analyzer/scrapers/polite_client.py`)
that every scraper routes through, providing rate limiting, caching, conditional
requests, backoff, a per-host circuit breaker, and robots.txt enforcement.

> ETHICS ANCHOR: This is for SUSTAINABLE, SANCTIONED, POLITE acquisition.
> No proxy/UA rotation to defeat blocks, no CAPTCHA bypass. mtgdecks.net blocked
> us (Cloudflare) and per project policy is RESPECTED and replaced — the design
> below does NOT try to route around its block; it makes that host trip the
> circuit breaker and stay tripped. A real descriptive User-Agent with contact
> is used everywhere.

---

## 1. Why

Today each scraper hand-rolls its own transport with inconsistent politeness:

| Scraper | Transport | Rate limit | Backoff | Cache | Conditional req | robots.txt |
|---|---|---|---|---|---|---|
| `scryfall.py` | `requests` | `time.sleep(0.12)` | `raise_for_status` only | bulk file freshness (7d), no HTTP cache | none | none |
| `mtgtop8.py` | `requests` | `time.sleep(1.5)` | manual 3x, linear `DELAY*(n+1)` | none | none | none |
| `mtgdecks.py` | `cloudscraper` | `random 2.5-5.0s` | manual 3x | none | none | none (DISABLED — blocked) |
| `matchup_scraper.py` | `requests` | inline | manual | none | none | none |
| `untapped_*` (7 files) | `urllib.request` | `time.sleep(0.5)` | manual 429 + Retry-After (replay_fetcher only) | on-disk JSON archives | none | none |
| `mtgmelee_scraper.py` | `cloudscraper` | `DELAY 1.5s` | manual | none | none | none |

Problems: no host honors `Retry-After` uniformly (only `untapped_replay_fetcher`
does); no ETag/Last-Modified revalidation so unchanged pages are re-downloaded in
full every run; no circuit breaker, so a host that starts 403/429-ing gets
hammered by the retry loop until the run ends; `robots.txt`/`Crawl-delay` is never
consulted; rate limits are per-call `sleep()` constants with no global per-host
governor (two scrapers hitting the same host in one run can burst).

A shared client fixes all of this in one place and makes each scraper a thin
caller.

---

## 2. Grounded reference facts (every external claim sourced)

- **Scryfall rate limits** (https://scryfall.com/docs/api/rate-limits): keep traffic
  "under 10 requests per second"; insert "50-100 milliseconds of delay between
  requests". HTTP 429 → "access being limited for 30 seconds"; "It is not
  acceptable to ignore HTTP 429 responses". All requests "must include a
  User-Agent header and an Accept header"; UA must name the app (e.g.
  `MTGExampleApp/1.0`); `Accept: */*` or `application/json;q=0.9,*/*;q=0.8` is fine.
- **Scrython 2.0** (https://pypi.org/project/scrython/): ships built-in rate
  limiting on by default — tiered: **10 req/s** standard endpoints (cards by id,
  sets, bulk-data, autocomplete) and **2 req/s** for heavier endpoints
  (`Search`, `Named`, `Random`, `Collection`). Overridable via
  `rate_limit_per_second`; disable with `rate_limit=False`. We mirror these tiers.
- **requests-cache** (https://requests-cache.readthedocs.io): `CachedSession` is a
  drop-in for `requests.Session`. Backends: SQLite, Redis, MongoDB, DynamoDB,
  filesystem (JSON/YAML files), memory. Expiration: `expire_after` (seconds /
  `timedelta`), per-pattern `urls_expire_after`, and `cache_control=True` to honor
  `Cache-Control` headers. Conditional requests are automatic: adds
  `If-None-Match` when an `ETag` is cached and `If-Modified-Since` when
  `Last-Modified` is cached; on expiry it revalidates and "only updated if the
  remote content has changed" (server 304 → cached body reused). Default
  `allowable_codes=(200,)` — error responses are NOT cached.
- **tenacity** (https://tenacity.readthedocs.io): `@retry`, `stop_after_attempt`,
  `stop_after_delay`, `wait_exponential(multiplier,min,max)`,
  `wait_random_exponential(multiplier,max)` / `wait_exponential_jitter` for
  backoff+jitter, `retry_if_exception_type`, `before_sleep` hook. NOTE: tenacity
  has NO built-in `Retry-After` support — honoring it requires a custom `wait=`
  callable that inspects the raised exception/response.
- **urllib.robotparser** (https://docs.python.org/3/library/urllib.robotparser.html):
  `RobotFileParser.set_url(url)`, `.read()`, `.can_fetch(useragent, url) -> bool`,
  `.crawl_delay(useragent) -> float|None`,
  `.request_rate(useragent) -> RequestRate(requests, seconds)|None`,
  `.site_maps() -> list|None`.
- **pybreaker** (circuit breaker, https://pypi.org/project/pybreaker/):
  `CircuitBreaker(fail_max=N, reset_timeout=S)` with closed/open/half-open states;
  trips to OPEN after `fail_max` consecutive failures, rejects calls with
  `CircuitBreakerError` during cooldown, then allows one half-open probe.
  (Lightweight; the alternative is a ~40-line hand-rolled per-host breaker — see
  §6. Either is acceptable; pybreaker is named so the breaker is not vague.)

### Live robots.txt observed 2026-06-26 (fetched with descriptive UA)
- `scryfall.com` / `api.scryfall.com`: `User-Agent: *`, only `/admin` + error
  pages disallowed, no `Crawl-delay`. Our API paths are allowed.
- `mtgtop8.com`: HTTP 404 — no robots.txt → implicit allow, no crawl-delay.
- `mtga.untapped.gg` (website): names only `Bingbot`/`Googlebot`/`DuckDuckBot`;
  `Disallow: /decks/*`, `/replay/*`, profile/deck paths. A generic UA matches no
  group → technically unrestricted, but the disallow set signals intent; we honor
  it for the website host. NOTE our scrapers hit the **API** host
  `api.mtga.untapped.gg`, which has no robots.txt (gateway returns
  `Missing Authentication Token`). Policy: treat API host as allowed; never crawl
  the website `/decks`,`/replay` HTML paths.
- `mtgdecks.net`: robots.txt itself behind Cloudflare "Sorry, you have been
  blocked" → this is the host we RESPECT and replace; the breaker keeps it tripped.
- `melee.gg`: robots.txt returns 403 at the edge. We use only its documented JSON
  POST endpoints; treat robots as unreachable → fail conservative (see §7).

---

## 3. Module surface (`scrapers/polite_client.py`)

The public surface is one function plus a small config registry and typed errors.

```python
# scrapers/polite_client.py

from __future__ import annotations
import requests  # type for return value

# ---- public errors -------------------------------------------------------
class PoliteClientError(Exception): ...
class RobotsDisallowed(PoliteClientError):
    """robots.txt forbids fetching this url for our UA."""
class HostCircuitOpen(PoliteClientError):
    """Host tripped the breaker (repeated 403/429); not retried. Surfaced, not hidden."""

# ---- main entry point ----------------------------------------------------
def get(
    url: str,
    *,
    host_rate: float | None = None,     # max req/sec for this host; None -> registry default
    cache_ttl: int | None = None,       # seconds; 0 = no-store; None -> registry default
    conditional: bool = True,           # send If-None-Match / If-Modified-Since on revalidation
    params: dict | None = None,
    headers: dict | None = None,        # merged over the host UA/Accept defaults
    timeout: float = 20.0,
    respect_robots: bool = True,
    max_retries: int = 4,               # backoff attempts on 429/503/transient
    force_refresh: bool = False,        # bypass cache read, still writes fresh
) -> requests.Response: ...

def post(url: str, *, json=None, data=None, **kw) -> requests.Response:
    """Same governor (rate/backoff/breaker/robots) but cache disabled by default
    (POST is how melee.gg/untapped analytics queries are issued)."""

# ---- optional helpers ----------------------------------------------------
def get_json(url: str, **kw) -> dict: ...        # get(...).json()
def host_state(host: str) -> dict: ...           # {breaker, tokens, last_request, robots} for diagnostics
```

### Per-host config registry (the backbone that keeps call sites tiny)

A single dict maps host -> defaults so callers usually pass nothing but a URL.
`host_rate`/`cache_ttl` kwargs override per-call when a host has tiered endpoints.

```python
DEFAULT_UA = "mtg-meta-analyzer/1.0 (+https://github.com/Zuxas/mtg-meta-analyzer)"  # contact via the repo issue tracker

HOST_CONFIG = {
  "api.scryfall.com": dict(
      rate=10.0, search_rate=2.0,          # 2 r/s for search/named/random/collection (Scrython tiers)
      min_interval=0.1,                    # 100 ms floor, top of Scryfall's 50-100 ms band
      cache_ttl=86400, ua=DEFAULT_UA,
      accept="application/json;q=0.9,*/*;q=0.8", needs_cloudscraper=False),
  "www.mtgtop8.com": dict(
      rate=0.67, min_interval=1.5,         # current DELAY_DEFAULT; no robots, be gentle
      cache_ttl=21600, needs_cloudscraper=False),
  "api.mtga.untapped.gg": dict(
      rate=2.0, min_interval=0.5,          # current RATE_LIMIT_SLEEP_SEC; upload-log ~50 req/min
      cache_ttl=3600, needs_cloudscraper=False),
  "mtgajson.untapped.gg": dict(
      rate=1.0, cache_ttl=604800, needs_cloudscraper=False),  # card db, weekly
  "melee.gg": dict(
      rate=0.67, min_interval=1.5,
      cache_ttl=0, needs_cloudscraper=True),                  # Cloudflare-fronted JSON API
  "mtgdecks.net": dict(
      rate=0.0, blocked=True,              # ETHICS: blocked host, breaker stays OPEN, never auto-fetch
      needs_cloudscraper=True),
}
```

`crawl_delay(ua)` from robots.txt, when present, is used as a FLOOR on
`min_interval` (we never go faster than a host asked for). For Scryfall, callers
hitting `/cards/search`, `/cards/named`, `/cards/random`, `/cards/collection`
pass `host_rate=2.0` (or the client auto-detects by path) to honor the 2 r/s tier.

---

## 4. Internal architecture (request lifecycle)

```
get(url, ...)
  │
  ├─ 1. parse host; load HOST_CONFIG[host] (or conservative defaults)
  │
  ├─ 2. robots gate (if respect_robots):  _robots_for(host).can_fetch(ua, url)
  │        not allowed -> raise RobotsDisallowed   (never silently skip)
  │
  ├─ 3. circuit breaker check:  if breaker[host] is OPEN -> raise HostCircuitOpen
  │        (blocked=True hosts start OPEN and never close)
  │
  ├─ 4. rate gate:  per-host token bucket / min-interval governor .acquire()
  │        sleeps just long enough to honor max(min_interval, robots crawl_delay)
  │
  ├─ 5. issue via the host's SESSION (CachedSession, or cloudscraper for CF hosts)
  │        cache read may short-circuit to a stored 200 (fresh) or revalidate (304)
  │
  ├─ 6. response handling:
  │        200/304  -> breaker.record_success(); return Response
  │        429/503  -> honor Retry-After (header, else body hint, else backoff);
  │                    retry up to max_retries with exp backoff + jitter
  │        403      -> breaker.record_failure(); after fail_max -> trip OPEN, raise HostCircuitOpen
  │        other 4xx-> raise (no retry, no cache)
  │
  └─ 7. return requests.Response (cached responses are transparent)
```

### 4a. Rate limiting — per-host token bucket / min-interval
A `threading.Lock`-guarded registry `host -> _RateGate`. Simplest correct form is a
**fixed minimum interval** (matches what the scrapers already do): the gate stores
`last_request_ts` and sleeps `max(0, min_interval - (now - last))` before
returning. A token-bucket variant (capacity = `rate`, refill = `rate`/sec) allows
small bursts while holding the long-run average — preferred for Scryfall's 10 r/s.
`min_interval = max(1/rate, robots.crawl_delay(ua) or 0)`. Per-host, so unrelated
hosts never block each other.

### 4b. Caching — requests-cache `CachedSession`
- Backend: `backend="filesystem"` (or `"sqlite"`) at
  `data/http_cache/` (gitignored, sibling to existing `data/untapped/` archives).
  SQLite backend keeps one file; filesystem keeps one file per response (easier to
  eyeball/prune). Either is fine; SQLite recommended for volume.
- `expire_after` = host `cache_ttl` default; `urls_expire_after` overrides per path
  (e.g. Scryfall `bulk-data` index short, oracle download long; mtgtop8 event pages
  long, format-list pages short).
- `cache_control=True` so a server's `Cache-Control`/`max-age` wins when present.
- `allowable_codes=(200,)` (the default) — **error/Cloudflare-block pages are never
  cached**, so a transient 429/503/403 can't poison the cache.
- `force_refresh=True` maps to requests-cache's per-request
  `session.get(..., refresh=True)` (revalidate) or `expire_after=0`.

### 4c. Conditional requests (ETag / If-Modified-Since)
Free with requests-cache: when a cached entry carries `ETag`/`Last-Modified`,
expiry triggers `If-None-Match`/`If-Modified-Since`; a 304 reuses the stored body
at near-zero transfer cost. `conditional=False` disables (forces full GET) for the
rare host that mishandles validators. This is the single biggest bandwidth win —
mtgtop8 event pages and Scryfall bulk index rarely change between daily runs.

### 4d. Backoff — tenacity with a Retry-After-aware custom wait
```python
from tenacity import retry, stop_after_attempt, retry_if_exception_type, before_sleep_log

def _wait_retry_after(retry_state):
    exc = retry_state.outcome.exception()
    ra = _parse_retry_after(exc)            # header -> int secs; else body "available in N"; else None
    if ra is not None:
        return min(ra + 1, 60)              # honor server, +1s cushion, cap 60s
    # fall back to exponential + jitter (wait_random_exponential semantics)
    return min(2 ** retry_state.attempt_number, 30) + random.uniform(0, 1)

@retry(wait=_wait_retry_after,
       stop=stop_after_attempt(max_retries),
       retry=retry_if_exception_type(_RetryableHTTP),   # 429, 503 only
       reraise=True)
def _do_request(...): ...
```
Only 429/503 are retryable; 403 is NOT retried (it feeds the breaker). This
generalizes the good behavior already in `untapped_replay_fetcher` (header →
body-hint → cushion) to every host. (Hand-rolled backoff is equally acceptable if
we prefer zero new deps; tenacity just removes boilerplate.)

### 4e. Circuit breaker — per host, STOP don't hammer
Goal from the task: "never hammer into a block again, and surface it." A
per-host breaker (pybreaker `CircuitBreaker(fail_max=3, reset_timeout=900)` or the
hand-rolled equivalent in §6):
- counts CONSECUTIVE 403/429-after-retries-exhausted as failures;
- at `fail_max` consecutive failures → state OPEN; subsequent `get()` raises
  `HostCircuitOpen` immediately (no network call) for `reset_timeout`;
- after cooldown → HALF-OPEN: one probe; success closes, failure re-opens;
- `blocked=True` hosts (mtgdecks.net) are constructed already-OPEN with effectively
  infinite reset — they are surfaced, never silently retried, honoring the ethics
  rule.
The orchestrator catches `HostCircuitOpen` and prints e.g.
`MTGDecks SKIPPED (circuit open)` instead of looping — same UX as today's manual
`MTGDecks SKIPPED (auto-pull disabled)`.

### 4f. robots.txt + Crawl-delay
One cached `RobotFileParser` per host (TTL ~24h, stored in the same http cache):
`set_url(scheme://host/robots.txt)` → `read()`. Before every fetch:
`can_fetch(ua, url)`; `crawl_delay(ua)` feeds the rate gate floor;
`request_rate(ua)` (if present) is honored as `requests/seconds`. The robots fetch
itself goes through the rate gate but bypasses the robots gate (chicken/egg).

---

## 5. Scheduling (design choice — no external source, tied to existing jobs)

The three Task Scheduler jobs (6AM `background_fill`, 5PM `run_daily`, Sunday
`run_scryfall_weekly`) already spread load across the day. The client adds:
- **Off-peak default**: long-TTL caches + conditional requests mean the 6AM run
  mostly returns 304s; only changed pages cost bandwidth.
- **Per-run request cap**: optional `POLITE_MAX_REQUESTS_PER_RUN` env / arg; the
  client counts issued (non-cache-hit) requests per host and raises a soft stop
  when exceeded, so a runaway loop can't blast a host.
- **Jitter on the gate**: add `random.uniform(0, 0.3*min_interval)` so requests
  don't arrive on a perfectly regular clock.
- Keep MTGDecks disabled (ethics); keep untapped at M/W/F via the existing
  orchestrator gate — the client governs politeness, the orchestrator governs
  *whether* a source runs at all.

---

## 6. Optional hand-rolled breaker (if we avoid the pybreaker dep)

```python
class _Breaker:
    def __init__(self, fail_max=3, reset_timeout=900, start_open=False):
        self.fail_max, self.reset_timeout = fail_max, reset_timeout
        self.fails = 0
        self.opened_at = time.time() if start_open else None
    def allow(self) -> bool:
        if self.opened_at is None: return True            # CLOSED
        if time.time() - self.opened_at >= self.reset_timeout:
            return True                                   # HALF-OPEN probe
        return False                                      # OPEN
    def record_success(self): self.fails = 0; self.opened_at = None
    def record_failure(self):
        self.fails += 1
        if self.fails >= self.fail_max: self.opened_at = time.time()
```
~15 lines, no dependency, thread-lock around mutation. pybreaker is preferred only
for its tested half-open/listener machinery.

---

## 7. robots-unreachable / failure policy (fail OPEN-but-CONSERVATIVE)

| robots.txt result | policy |
|---|---|
| 200 with rules | obey `can_fetch`, apply `crawl_delay`/`request_rate` |
| 404 (mtgtop8) | no restrictions → allow, use registry `min_interval` |
| 403 / Cloudflare block (melee, mtgdecks) | treat as unreachable → ALLOW only the specific documented API endpoints already in use, at the conservative registry rate; do NOT broaden crawling; mtgdecks stays `blocked=True` per ethics |
| network error fetching robots | cache a short-TTL "unknown" → allow registry-known hosts only, conservative rate |

Never cache a robots *block page* as rules. Never fetch a path that a reachable
robots.txt disallows.

---

## 8. Migration — how existing scrapers route through it (minimal change)

"Minimal change" is literally true for the `requests`-based scrapers and a
mechanical (but larger) edit for the `urllib`-based untapped family.

| Scraper | Transport today | Change | Effort |
|---|---|---|---|
| `mtgtop8.py` | `requests.get` in `_get()` | replace body of `_get()` with `polite_client.get(url)`; delete manual retry/sleep | tiny (1 fn) |
| `matchup_scraper.py` | `requests` | same `_get` swap | tiny |
| `scryfall.py` | `requests.get` (API + bulk) | `_api_lookup` → `polite_client.get_json(NAMED_URL, params=..., host_rate=2.0)`; bulk index via `get`; keep the big streamed oracle download on raw `requests` (binary stream, not cacheable usefully) | small |
| `untapped_*` (7 files) | `urllib.request.urlopen` | replace `urllib` Request/urlopen blocks with `polite_client.get_json(url)`; the bespoke 429/Retry-After loop in `untapped_replay_fetcher` is now handled centrally and deleted | medium — LARGEST delta; this is where "minimal" stops being literal |
| `mtgmelee_scraper.py` | `cloudscraper` POST | route via `polite_client.post(url, json=..., )` with `needs_cloudscraper=True` host | small once the cloudscraper session path exists |
| `mtgdecks.py` | `cloudscraper` (DISABLED) | leave disabled; if ever re-enabled it goes through the blocked-host breaker | none |

### Transport heterogeneity (the integration crux)
A `CachedSession` cannot transparently absorb `urllib` or `cloudscraper` callers,
so the client owns a **pluggable session per host**:
- default: `requests_cache.CachedSession(...)` (covers scryfall, mtgtop8, untapped
  API once they call `polite_client`);
- Cloudflare hosts (`needs_cloudscraper=True`): a `cloudscraper` scraper, wrapped
  so the SAME rate gate / breaker / backoff apply but caching is off by default
  (Cloudflare responses + TLS-fingerprint sessions don't cache cleanly). If we want
  caching there too, requests-cache exposes a `CacheMixin` that can be mixed onto a
  cloudscraper class — optional, not required for v1.
- `_session_for(host)` returns the right object; callers never see it.

`constants.py` stays the source of UA/headers/delays but those values move into
`HOST_CONFIG` (or `HOST_CONFIG` imports them) so there is one rate/UA truth.
The Scryfall-specific `HEADERS` (descriptive UA + Accept) becomes the registry
template for a compliant UA across all hosts (today only Scryfall sends a real
descriptive UA; mtgtop8/untapped send a fake Chrome string — the new client
standardizes on the honest descriptive UA, which is the polite/ethical choice).

---

## 9. Known limitations (state, don't hide)
- **Per-process rate limiter.** The gate/breaker live in module globals; the 6AM
  background fill and an open GUI doing a manual refresh are separate processes and
  will NOT coordinate their token buckets. Acceptable (they rarely overlap; each is
  individually polite) but worth a cross-process file-lock if it ever bites.
- **cloudscraper + caching** is best-effort; v1 runs CF hosts uncached.
- The big Scryfall oracle bulk download stays on raw streamed `requests` (it has
  its own 7-day freshness check in `scryfall.py`); only the small JSON API calls
  move under the cache.
- robots/crawl-delay honored per host; we do not implement a global cross-host
  concurrency cap (each host is serialized by its own gate, which is sufficient
  since runs are single-threaded today).

---

## 10. Dependencies to add (requirements.txt)
```
requests-cache>=1.2     # CachedSession, conditional requests, TTL/urls_expire_after
tenacity>=8.2           # retry/backoff/jitter (optional — hand-roll is fine)
pybreaker>=1.0          # circuit breaker (optional — §6 hand-roll is fine)
# urllib.robotparser is stdlib; requests/cloudscraper already present
```
Minimum-dependency variant: add only `requests-cache`; hand-roll backoff (§4d) and
breaker (§6). Recommended variant: add all three for tested, readable behavior.

---

## 11. Acceptance criteria
1. Every scraper's network call goes through `polite_client.get/post`.
2. No host is hit faster than `max(registry min_interval, robots Crawl-delay)`.
3. A 429/503 honors `Retry-After`; repeated 403/429 trips the per-host breaker and
   raises `HostCircuitOpen` instead of looping.
4. Unchanged pages return from cache or via 304 (verified by a second run issuing
   conditional requests and transferring no body).
5. robots.txt is fetched+obeyed per host; `RobotsDisallowed` raised on a disallowed
   path.
6. mtgdecks.net never auto-fetches (blocked host, breaker OPEN) — ethics preserved.
7. A descriptive User-Agent with contact is sent on every request.
```
```
