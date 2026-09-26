"""
mymtgo.py -- MyMTGO (mymtgo.com) metagame + matchup snapshots.

Source : https://mymtgo.com/metagame/<format>  and  /metagame/<format>/<deck-slug>
         MTGO match data from the MyMTGO desktop tracker (player-reported) plus the
         published top 32 of every Challenge. Early-alpha site, per its own terms, so
         treat every number as provisional.
Why    : it is the only source we have with MTGO MATCH win rates per matchup. The
         untapped_* tables are Arena-only, and melee is paper. It also publishes
         mulligan-depth and lands-in-opener win rates per archetype.
Fetch  : ALWAYS through scrapers.polite_client.get (robots-checked, rate-gated,
         circuit-breaker). robots.txt disallows /api/, so this module reads only the
         public HTML pages. Each page embeds its full data as an Inertia JSON island,
         <script data-page="app" type="application/json">, so ONE request per page
         and no /api/ calls.
Writes : JSON snapshot files under data/mymtgo/. There is NO DB write here on purpose
         (the live DB is a hot zone). A DB mapping is a follow-up that needs sign-off.

PUBLIC SURFACE
    extract_page(html) -> dict                   # {'component', 'url', 'props'}; raises MyMtgoParseError
    parse_index(page)  -> dict                   # field shares + win rates (one page of the index)
    parse_deck(page)   -> dict                   # one archetype: matchups, mulligans, openers
    fetch_index(fmt, days=30) -> dict            # all index pages merged
    fetch_deck(fmt, slug) -> dict
    snapshot(fmt, days=30, top=20) -> dict       # index + the top-N decks' matchup spreads
    matchup_matrix(snap, rate='shrunk') -> {deck: {opp: rate}}
    CLI: python -m scrapers.mymtgo --format modern --days 30 --top 20

Spec: harness/specs/2026-09-26-session-assets-intake.md (amendment 1)
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from scrapers import polite_client
except ImportError:  # pragma: no cover - direct script run
    import polite_client  # type: ignore

BASE = "https://mymtgo.com"
FORMATS = ("modern", "legacy", "pauper", "vintage", "premodern", "standard", "pioneer")
WINDOWS = (7, 30, 90)
MAX_INDEX_PAGES = 10
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_ROOT, "data", "mymtgo")

_PAGE_RE = re.compile(
    r"<script\b[^>]*\bdata-page=[\"']app[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


class MyMtgoParseError(ValueError):
    """The page did not carry the data island or it changed shape. Never retried."""


# --------------------------------------------------------------------------- parsing (pure)

def extract_page(html: str) -> dict:
    m = _PAGE_RE.search(html or "")
    if not m:
        raise MyMtgoParseError("no <script data-page=\"app\"> island found "
                               f"(page starts: {(html or '')[:120]!r})")
    raw = m.group(1).strip()
    for candidate in (raw, _html.unescape(raw)):
        try:
            page = json.loads(candidate)
            break
        except ValueError:
            page = None
    if not isinstance(page, dict) or not isinstance(page.get("props"), dict):
        raise MyMtgoParseError("data-page island is not an Inertia page object")
    return page


def _num(v):
    return None if v is None else float(v)


def _range(r):
    r = r or {}
    return _num(r.get("lo")), _num(r.get("hi"))


def parse_index(page: dict) -> dict:
    if page.get("component") != "metagame/Index":
        raise MyMtgoParseError(f"expected component metagame/Index, got {page.get('component')!r}")
    p = page["props"]
    if not isinstance(p.get("decksData"), list):
        raise MyMtgoParseError("index props lack decksData[]")
    decks = []
    for d in p["decksData"]:
        lo, hi = _range(d.get("winRateRange"))
        decks.append({
            "slug": d.get("slug"), "name": d.get("name"),
            "share": _num(d.get("share")), "change": _num(d.get("change")),
            "played": d.get("played"), "low_sample": bool(d.get("lowSample")),
            "win_rate": _num(d.get("winRate")), "wr_lo": lo, "wr_hi": hi,
            "wr_matches": d.get("winRateMatches"), "signature": d.get("signature"),
            "has_page": bool(d.get("hasPage", True)),
        })
    pg = p.get("pagination") or {}
    return {
        "format": p.get("format"), "days": p.get("days"), "since": p.get("since"),
        "matches": p.get("matches"), "sources": p.get("sources") or {},
        "win_rate_window_days": p.get("winRateWindowDays"),
        "total_decks": p.get("decks"), "unlisted": p.get("unlisted") or {},
        "page": pg.get("page", 1), "last_page": pg.get("lastPage", 1),
        "decks": decks,
    }


def parse_deck(page: dict) -> dict:
    if page.get("component") != "metagame/Show":
        raise MyMtgoParseError(f"expected component metagame/Show, got {page.get('component')!r}")
    d = page["props"].get("deck")
    if not isinstance(d, dict) or "slug" not in d:
        raise MyMtgoParseError("deck page props lack deck{}")
    lo, hi = _range(d.get("winRateRange"))
    mu = d.get("matchups") or {}
    matchups = []
    for r in mu.get("rows") or []:
        if r.get("isMirror"):
            continue
        rlo, rhi = _range(r.get("range"))
        matchups.append({
            "opp_slug": r.get("slug"), "opp_name": r.get("name"),
            "win_rate": _num(r.get("winRate")),        # raw record
            "shrunk_rate": _num(r.get("shrunkRate")),  # pulled toward the deck's field rate
            "lo": rlo, "hi": rhi, "favoured_chance": r.get("favouredChance"),
            "wins": r.get("wins"), "matches": r.get("matches"), "games": r.get("games"),
        })
    mull = [{"kept": x.get("kept"), "games": x.get("games"), "share": _num(x.get("share")),
             "win_rate": _num(x.get("winRate")), "pooled": bool(x.get("pooled"))}
            for x in (d.get("mulliganDepth") or {}).get("levels") or []]
    openers = [{"lands": x.get("lands"), "hands": x.get("hands"),
                "win_rate": _num(x.get("winRate")),
                "lo": _range(x.get("range"))[0], "hi": _range(x.get("range"))[1]}
               for x in (d.get("openingHands") or {}).get("buckets") or []]
    cards = [{"name": c.get("name"), "zone": c.get("zone"), "used": c.get("used"),
              "cast_wr": _num(c.get("winRate")), "impact": _num(c.get("impact")),
              "drawn_wr": _num(c.get("drawnWinRate")), "reliance": _num(c.get("reliance")),
              "opener_wr": _num(c.get("openingHand")),
              "sided_in": _num(c.get("sidedIn")), "sided_out": _num(c.get("sidedOut"))}
             for c in (d.get("main") or []) + (d.get("side") or [])]
    return {
        "slug": d.get("slug"), "name": d.get("name"), "format": d.get("formatSlug"),
        "colors": d.get("colors"), "lineage": d.get("lineage"),
        "win_rate": _num(d.get("winRate")), "wr_lo": lo, "wr_hi": hi,
        "matches": d.get("matches"), "games": d.get("games"),
        "game_win_rate": _num(d.get("gameWinRate")), "sources": d.get("sources") or {},
        "refreshed_at": d.get("refreshedAt"),
        "matchups": matchups, "matchups_other": mu.get("other"),
        "mulligan": mull, "openers": openers, "cards": cards,
    }


def matchup_matrix(snap: dict, rate: str = "shrunk") -> dict:
    """{deck_name: {opp_name: pct}} from a snapshot. rate='shrunk' (default; the
    site's small-sample-adjusted figure) or 'raw'."""
    key = "shrunk_rate" if rate == "shrunk" else "win_rate"
    return {d["name"]: {m["opp_name"]: m[key] for m in d["matchups"] if m[key] is not None}
            for d in snap.get("deck_pages", {}).values()}


# --------------------------------------------------------------------------- network (polite)

def _get_page(path: str) -> dict:
    resp = polite_client.get(BASE + path)
    if not resp.ok:
        raise MyMtgoParseError(f"HTTP {resp.status} for {path}")
    return extract_page(resp.text)


def fetch_index(fmt: str = "modern", days: int = 30) -> dict:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    if days not in WINDOWS:
        raise ValueError(f"days must be one of {WINDOWS}")
    first = parse_index(_get_page(f"/metagame/{fmt}?days={days}"))
    decks = list(first["decks"])
    for n in range(2, min(first["last_page"], MAX_INDEX_PAGES) + 1):
        decks += parse_index(_get_page(f"/metagame/{fmt}?days={days}&page={n}"))["decks"]
    seen, unique = set(), []
    for d in decks:                    # a page boundary can shift while we paginate
        if d["slug"] not in seen:
            seen.add(d["slug"])
            unique.append(d)
    first["decks"] = unique
    first.pop("page", None)
    return first


def fetch_deck(fmt: str, slug: str) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug or ""):
        raise ValueError(f"bad deck slug {slug!r}")
    return parse_deck(_get_page(f"/metagame/{fmt}/{slug}"))


def snapshot(fmt: str = "modern", days: int = 30, top: int = 20) -> dict:
    """Index (~3 requests) + the top-N decks by share that have a page (N requests)."""
    idx = fetch_index(fmt, days)
    targets = [d for d in sorted(idx["decks"], key=lambda d: -(d["share"] or 0))
               if d["has_page"] and not d["low_sample"]][:max(0, top)]
    pages, errors = {}, {}
    for d in targets:
        try:
            pages[d["slug"]] = fetch_deck(fmt, d["slug"])
        except (MyMtgoParseError, polite_client.PoliteClientError) as e:
            errors[d["slug"]] = str(e)
            if isinstance(e, polite_client.HostCircuitOpen):
                break
    return {
        "source": "mymtgo.com", "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": fmt, "days": days, "index": idx, "deck_pages": pages, "errors": errors,
        "caveat": "MyMTGO is early alpha; tracker-reported + Challenge top-32 MTGO data. "
                  "Matchup win rates cover the site's 90-day window regardless of `days`.",
    }


def save_snapshot(snap: dict, out_dir: str = OUT_DIR) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{snap['format']}_{snap['days']}d_{snap['fetched_at'][:10]}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    from db.helpers import force_utf8_stdio
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Snapshot the MyMTGO metagame + matchup spreads (no DB writes).")
    ap.add_argument("--format", default="modern", choices=FORMATS)
    ap.add_argument("--days", type=int, default=30, choices=WINDOWS)
    ap.add_argument("--top", type=int, default=20, help="deck pages to fetch (1 request each)")
    ap.add_argument("--deck", help="print one deck's matchup spread from the snapshot")
    a = ap.parse_args(argv)
    snap = snapshot(a.format, a.days, a.top)
    path = save_snapshot(snap)
    idx = snap["index"]
    print(f"MyMTGO {a.format} {a.days}d: {idx['matches']} matches since {idx['since']}, "
          f"{len(idx['decks'])} decks; {len(snap['deck_pages'])} deck pages, {len(snap['errors'])} errors")
    for d in sorted(idx["decks"], key=lambda d: -(d["share"] or 0))[:15]:
        print(f"  {d['share'] or 0:5.1f}%  WR {d['win_rate'] or 0:5.1f}%  {d['name']}")
    if a.deck:
        page = snap["deck_pages"].get(a.deck)
        if page:
            print(f"\n{page['name']} matchups (shrunk WR, raw record):")
            for m in page["matchups"]:
                if m["shrunk_rate"] is None or m["wins"] is None or m["matches"] is None:
                    continue
                print(f"  {m['shrunk_rate']:5.1f}%  {m['wins']}-{m['matches'] - m['wins']:<4} {m['opp_name']}")
    print(f"Wrote {path}")
    return 1 if snap["errors"] and not snap["deck_pages"] else 0


if __name__ == "__main__":
    ROOT = _ROOT
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    sys.exit(main())
