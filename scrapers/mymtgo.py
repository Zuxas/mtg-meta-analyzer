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

DATA QUALITY (audit 2026-09-26, harness/knowledge candidate: inbox/promoted/mymtgo-data-audit-2026-09-26.md)
    Verified : site math (matchup symmetry, k=27 shrinkage, Wilson ranges, seat sums) and
               challenge standings/records/archetype labels vs mtgo.com (32/32 exact), and
               reconstructed pairings reproduce every published player's official W-L.
    Caveats  : tracker pilots win ~51-68% of league matches depending on deck (their lean
               lands on the deck they pilot); published-vs-published challenge matches
               attenuate matchups toward 50% by ~0.5-3pp; '(Provisional)' / Rogue labels
               soak up fast losses; the site's matchup window is a fixed 90 days that can
               cross set releases / B&R. Store raw counts; derive estimates downstream
               (analysis/mymtgo_quality.py). Swiss pairings are NOT published by MTGO, so
               event matches carry provenance 'mymtgo_reconstructed'.

PUBLIC SURFACE
    extract_page(html) -> dict                   # {'component', 'url', 'props', '_sha256'}; raises MyMtgoParseError
    parse_index(page)  -> dict                   # field shares + win rates (one page of the index)
    parse_deck(page)   -> dict                   # one archetype: matchups, mulligans, openers
    fetch_index(fmt, days=30) -> dict            # all index pages merged
    fetch_deck(fmt, slug) -> dict
    snapshot(fmt, days=30, top=20) -> dict       # index + the top-N decks' matchup spreads
    matchup_matrix(snap, rate='shrunk') -> {deck: {opp: rate}}
    parse_events_index(page) / parse_event(page) -> dict   # events + reconstructed pairings
    fetch_events(fmt, since, until=None) -> list[dict]     # event pages in a date window
    CLI: python -m scrapers.mymtgo --format modern --days 30 --top 20
         python -m scrapers.mymtgo --format modern --events-since 2026-08-14

Spec: harness/specs/2026-09-26-session-assets-intake.md (amendment 1)
"""
from __future__ import annotations

import argparse
import hashlib
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
    # Archive-friendly fingerprint of the raw payload: lets a later audit tell
    # "the metagame changed" from "the (alpha) site revised its backend".
    page["_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
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
            "provisional": "(provisional)" in str(d.get("name", "")).lower(),
        })
    pg = p.get("pagination") or {}
    return {
        "format": p.get("format"), "days": p.get("days"), "since": p.get("since"),
        "matches": p.get("matches"), "sources": p.get("sources") or {},
        "win_rate_window_days": p.get("winRateWindowDays"),
        "total_decks": p.get("decks"), "unlisted": p.get("unlisted") or {},
        "page": pg.get("page", 1), "last_page": pg.get("lastPage", 1),
        "decks": decks, "payload_sha256": page.get("_sha256"),
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
            "unit": "match",
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
    lr = d.get("leagueRuns") or {}
    lw = sum((f.get("wins") or 0) * (f.get("runs") or 0) for f in lr.get("finishes") or [])
    ln = sum(5 * (f.get("runs") or 0) for f in lr.get("finishes") or [])
    cr = d.get("challengeResults") or {}
    rows = cr.get("rows") or []
    return {
        "payload_sha256": page.get("_sha256"),
        # Tracker pilots' COMPLETE 5-match league runs only (drops excluded -> reads high).
        # This is the tracker-skill lean that reported matches inherit for this deck.
        "tracker_league": {"runs": lr.get("runs"), "wins": lw, "matches": ln,
                           "win_rate": round(100 * lw / ln, 1) if ln else None},
        "challenge": {"entries": cr.get("entries"), "trophies": cr.get("trophies"),
                      "top8s": cr.get("topEights"), "recent_rows": len(rows),
                      "recent_unique_pilots": len({r.get("pilot") for r in rows})},
        "slug": d.get("slug"), "name": d.get("name"), "format": d.get("formatSlug"),
        "colors": d.get("colors"), "lineage": d.get("lineage"),
        "win_rate": _num(d.get("winRate")), "wr_lo": lo, "wr_hi": hi,
        "matches": d.get("matches"), "games": d.get("games"),
        "game_win_rate": _num(d.get("gameWinRate")), "sources": d.get("sources") or {},
        "refreshed_at": d.get("refreshedAt"),
        "matchups": matchups, "matchups_other": mu.get("other"),
        "mulligan": mull, "openers": openers, "cards": cards,
    }


# --------------------------------------------------------------------------- events (pure)

PROVENANCE_EVENT = "mymtgo_reconstructed"   # MTGO does not publish swiss pairings; see audit


def parse_events_index(page: dict) -> dict:
    if page.get("component") != "events/Index":
        raise MyMtgoParseError(f"expected component events/Index, got {page.get('component')!r}")
    p = page["props"]
    evs = []
    for e in p.get("events") or []:
        evs.append({"number": e.get("number"), "description": e.get("description"),
                    "format": e.get("format"), "started_at": e.get("startedAt"),
                    "player_count": e.get("playerCount"), "published_decks": e.get("publishedDecks"),
                    "has_matches": bool(e.get("hasMatches"))})
    pg = p.get("pagination") or {}
    return {"events": evs, "page": pg.get("page", 1), "last_page": pg.get("lastPage", 1)}


def _score(s):
    """'2-1' -> (2, 1); None/garbage -> None."""
    m = re.fullmatch(r"\s*(\d+)-(\d+)(?:-(\d+))?\s*", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_event(page: dict) -> dict:
    """One event: standings (published 32) + every pairing the site reconstructed.

    Each match is emitted ONCE (deduped on event+round+both login ids) with:
      a_*/b_* player + raw archetype label (None = unpublished or unclassified),
      a_games/b_games, result ('a'|'b'|'draw'), both_published, playoff,
      fingerprint, provenance='mymtgo_reconstructed'.
    Also returns `reconciliation`: for every published player, W-L rebuilt from the
    pairings vs the official standings record -- the check that the reconstruction
    is coherent (it is NOT proof of where the pairings came from).
    """
    if page.get("component") != "events/Show":
        raise MyMtgoParseError(f"expected component events/Show, got {page.get('component')!r}")
    p = page["props"]
    ev = p.get("event") or {}
    if not isinstance(p.get("rounds"), list) or not isinstance(p.get("standings"), list):
        raise MyMtgoParseError("event props lack rounds[] / standings[]")
    standings = [{"login_id": s.get("loginId"), "player": s.get("playerName"),
                  "final_rank": s.get("finalRank"), "swiss_rank": s.get("swissRank"),
                  "record": s.get("record"), "deck_uuid": s.get("deckUuid"),
                  "archetype": (s.get("archetype") or {}).get("name")}
                 for s in p["standings"]]
    published = {s["login_id"] for s in standings if s["deck_uuid"]}
    labels = {s["login_id"]: s["archetype"] for s in standings}
    seen, matches, rebuilt = set(), [], {}
    for r in p["rounds"]:
        rnd = r.get("round")
        for row in r.get("rows") or []:
            opp = row.get("opponent")
            sc = _score(row.get("score"))
            if not opp or row.get("bye") or sc is None:
                continue
            a, b = row.get("loginId"), opp.get("loginId")
            ga, gb = sc
            w = rebuilt.setdefault(a, [0, 0])
            if ga > gb:
                w[0] += 1
            elif gb > ga:
                w[1] += 1
            key = (ev.get("number"), rnd, min(a, b), max(a, b))
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "event": ev.get("number"), "round": rnd, "playoff": bool(r.get("playoff")),
                "a_login": a, "a_player": row.get("playerName"),
                "a_archetype": (row.get("archetype") or {}).get("name") or labels.get(a),
                "b_login": b, "b_player": opp.get("playerName"),
                "b_archetype": (opp.get("archetype") or {}).get("name") or labels.get(b),
                "a_games": ga, "b_games": gb,
                "result": "a" if ga > gb else ("b" if gb > ga else "draw"),
                "both_published": a in published and b in published,
                "fingerprint": "%s:%s:%s:%s" % key,
                "provenance": PROVENANCE_EVENT,
            })
    recon = []
    for s in standings:
        w = rebuilt.get(s["login_id"], [0, 0])
        recon.append({"player": s["player"], "official": s["record"], "rebuilt": f"{w[0]}-{w[1]}",
                      "ok": s["record"] == f"{w[0]}-{w[1]}"})
    return {
        "number": ev.get("number"), "description": ev.get("description"),
        "format": ev.get("format"), "started_at": ev.get("startedAt"),
        "player_count": ev.get("playerCount"), "published_decks": ev.get("publishedDecks"),
        "payload_sha256": page.get("_sha256"),
        "standings": standings, "matches": matches, "reconciliation": recon,
        "reconciled": all(x["ok"] for x in recon) if recon else None,
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


def fetch_event(fmt: str, number: int) -> dict:
    return parse_event(_get_page(f"/events/{fmt}/{int(number)}"))


def fetch_events(fmt: str = "modern", since: str = "", until: str | None = None,
                 max_pages: int = 40) -> list[dict]:
    """Every event in [since, until] (ISO dates, inclusive; the site lists newest first).
    One index request per 15 events + one request per event. Stops paging once a
    whole index page predates `since`."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since or ""):
        raise ValueError("since must be YYYY-MM-DD")
    out, page = [], 1
    while page <= max_pages:
        idx = parse_events_index(_get_page(f"/events/{fmt}?page={page}"))
        # The listing is only roughly newest-first (an RCQ can sort after later
        # challenges), so stop only once a WHOLE page predates `since`.
        older = bool(idx["events"])
        for e in idx["events"]:
            day = (e["started_at"] or "")[:10]
            if day < since:
                continue
            older = False
            if until and day > until:
                continue
            if not e["has_matches"]:
                continue
            try:
                out.append(fetch_event(fmt, e["number"]))
            except MyMtgoParseError as err:
                out.append({"number": e["number"], "error": str(err)})
        if older or page >= idx["last_page"]:
            break
        page += 1
    return out


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
    ap.add_argument("--events-since", metavar="YYYY-MM-DD",
                    help="instead: fetch every event (with pairings) since this date")
    ap.add_argument("--events-until", metavar="YYYY-MM-DD")
    a = ap.parse_args(argv)
    if a.events_since:
        evs = fetch_events(a.format, a.events_since, a.events_until)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = {"source": "mymtgo.com", "fetched_at": stamp, "format": a.format,
               "since": a.events_since, "until": a.events_until, "events": evs}
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, f"{a.format}_events_{a.events_since}_{stamp[:10]}.json")
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        os.replace(path + ".tmp", path)
        ok = [e for e in evs if "error" not in e]
        bad_recon = [e["number"] for e in ok if e["reconciled"] is False]
        print(f"{len(ok)} events, {sum(len(e['matches']) for e in ok)} matches "
              f"({sum(m['both_published'] for e in ok for m in e['matches'])} both-published); "
              f"{len(evs) - len(ok)} errors; reconciliation failures: {bad_recon or 'none'}")
        print(f"Wrote {path}")
        return 1 if bad_recon else 0
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
