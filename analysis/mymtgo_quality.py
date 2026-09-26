"""analysis/mymtgo_quality.py -- accuracy layer for MyMTGO data (scrapers/mymtgo.py).

What the 2026-09-26 audit found, and what this module enforces:

  * The site's DISPLAYED MATH is right. validate_snapshot() re-derives it on every
    scrape (matchup symmetry, k-shrinkage, seat accounting, share sum), so a silent
    backend change in the alpha site is caught instead of ingested.
  * The SAMPLING FRAME is the risk, not the arithmetic:
      - tracker pilots out-win the field, by deck (tracker_lean());
      - challenge matches are only published-vs-published, which pulls matchups toward 50%;
      - '(Provisional)' labels and Rogue seats absorb fast losses (family());
      - the site's matchup window is a fixed 90 days that crosses set releases.
  * So: keep RAW counts with provenance, aggregate only INSIDE an epoch
    (event_matchups() refuses to cross one unless told to), report a pilot-clustered
    interval beside Wilson, and never publish a single "bias-corrected true" rate.

Pure functions; no network, no DB.
Spec: harness/specs/2026-09-26-session-assets-intake.md (amendment 2)
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict

# Paper release dates from Scryfall /sets (MTGO usually lands within days -- check
# before trusting an edge case). The B&R entry is the ANNOUNCEMENT date; update it
# with the effective date once published.
MODERN_EPOCHS: list[tuple[str, str, str]] = [
    ("msh", "2026-06-26", "Marvel Super Heroes"),
    ("hob", "2026-08-14", "The Hobbit"),
    ("fra", "2026-10-02", "Reality Fracture"),
    ("br-2026-10-12", "2026-10-12", "B&R announcement (announced date; effective TBD)"),
]

SHRINK_K = {"modern": 27, "legacy": 35, "pauper": 30, "vintage": 56,
            "premodern": 32, "standard": 66, "pioneer": 36}   # site methodology, 2026-09


# --------------------------------------------------------------------------- labels / epochs

def family(label: str | None) -> str | None:
    """'Affinity (Provisional)' -> 'Affinity'. The raw label must still be stored;
    this is for sensitivity analysis, not a destructive merge."""
    if label is None:
        return None
    return re.sub(r"\s*\(provisional\)\s*$", "", str(label), flags=re.IGNORECASE).strip()


def epoch_of(day: str, epochs=MODERN_EPOCHS) -> str | None:
    """Epoch name containing ISO date `day` (None if before the first boundary)."""
    cur = None
    for name, start, _ in epochs:
        if day[:10] >= start:
            cur = name
    return cur


def epoch_range(name: str, epochs=MODERN_EPOCHS) -> tuple[str, str | None]:
    for i, (n, start, _) in enumerate(epochs):
        if n == name:
            nxt = epochs[i + 1][1] if i + 1 < len(epochs) else None
            if nxt:
                y, m, d = map(int, nxt.split("-"))
                import datetime as _dt
                end = (_dt.date(y, m, d) - _dt.timedelta(days=1)).isoformat()
            else:
                end = None
            return start, end
    raise KeyError(f"unknown epoch {name!r}")


class EpochCrossingError(ValueError):
    pass


# --------------------------------------------------------------------------- snapshot checks

def validate_snapshot(snap: dict, tol: float = 0.15) -> list[str]:
    """Re-derive the site's math from a scrapers.mymtgo.snapshot(). Returns problems
    ([] = the numbers are internally coherent). Checks:
      1. every fetched A-vs-B matchup mirrors B-vs-A (same matches, wins sum);
      2. raw rate == wins/matches;
      3. shrunk rate == (w + k*deckWR)/(n + k) with the format's k;
      4. listed seats + rogue + other == 2 x matches (30-day window);
      5. shares + rogue + other within 1.5 points of 100.
    """
    problems = []
    fmt = snap.get("format", "modern")
    k = SHRINK_K.get(fmt)
    pages = snap.get("deck_pages", {})
    for a, pa in pages.items():
        p = (pa.get("win_rate") or 0) / 100
        for m in pa.get("matchups", []):
            if m.get("wins") is None or not m.get("matches"):
                continue
            raw = 100 * m["wins"] / m["matches"]
            if m.get("win_rate") is not None and abs(raw - m["win_rate"]) > tol:
                problems.append(f"{pa['name']} vs {m['opp_name']}: raw {m['win_rate']} != {raw:.2f}")
            if k and m.get("shrunk_rate") is not None:
                pred = 100 * (m["wins"] + k * p) / (m["matches"] + k)
                if abs(pred - m["shrunk_rate"]) > tol:
                    problems.append(f"{pa['name']} vs {m['opp_name']}: shrunk {m['shrunk_rate']} "
                                    f"!= {pred:.2f} (k={k}; site may have refit k)")
            b = m.get("opp_slug")
            if b in pages and b != a:
                rev = [x for x in pages[b].get("matchups", []) if x.get("opp_slug") == a]
                if not rev:
                    problems.append(f"{pa['name']} vs {m['opp_name']}: reverse row missing")
                elif rev[0]["matches"] != m["matches"] or rev[0]["wins"] + m["wins"] != m["matches"]:
                    problems.append(f"{pa['name']} vs {m['opp_name']}: asymmetric "
                                    f"{m['wins']}/{m['matches']} vs {rev[0]['wins']}/{rev[0]['matches']}")
    idx = snap.get("index") or {}
    decks = idx.get("decks") or []
    if decks and idx.get("matches"):
        un = idx.get("unlisted") or {}
        seats = sum(d.get("played") or 0 for d in decks) + sum((un.get(x) or {}).get("played") or 0
                                                               for x in ("rogue", "other"))
        if seats != 2 * idx["matches"]:
            problems.append(f"seat accounting: {seats} seats != 2 x {idx['matches']} matches")
        share = sum(d.get("share") or 0 for d in decks) + sum((un.get(x) or {}).get("share") or 0
                                                              for x in ("rogue", "other"))
        if abs(share - 100) > 1.5:
            problems.append(f"shares sum to {share:.1f}")
    return problems


def tracker_lean(snap: dict) -> list[dict]:
    """Per deck: tracker pilots' complete-league-run win rate vs the deck's overall rate.
    Positive lean = the deck's reported matches are carried by above-field pilots."""
    out = []
    for pa in snap.get("deck_pages", {}).values():
        tl = pa.get("tracker_league") or {}
        if tl.get("win_rate") is None:
            continue
        out.append({"deck": pa["name"], "tracker_runs": tl.get("runs"),
                    "tracker_league_wr": tl["win_rate"], "deck_wr": pa.get("win_rate"),
                    "lean_pp": round(tl["win_rate"] - (pa.get("win_rate") or 0), 1)})
    return sorted(out, key=lambda r: -r["lean_pp"])


# --------------------------------------------------------------------------- event matchups

def wilson(w: float, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    ph = w / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    r = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return round(100 * (c - r) / d, 1), round(100 * (c + r) / d, 1)


def _cluster_ci(by_pilot: dict, iters: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    """95% bootstrap interval resampling PILOTS (of the row deck) with replacement.
    Wider than Wilson when a few grinders supply most of the matches."""
    pilots = list(by_pilot.values())
    if len(pilots) < 3:
        return None
    rng = random.Random(seed)
    rates = []
    for _ in range(iters):
        w = n = 0
        for _ in pilots:
            pw, pn = pilots[rng.randrange(len(pilots))]
            w += pw
            n += pn
        if n:
            rates.append(w / n)
    rates.sort()
    return round(100 * rates[int(0.025 * len(rates))], 1), round(100 * rates[int(0.975 * len(rates)) - 1], 1)


def event_matchups(events: list[dict], start: str, end: str | None = None,
                   only_both_published: bool = True, include_playoffs: bool = True,
                   use_family: bool = False, allow_cross_epoch: bool = False,
                   epochs=MODERN_EPOCHS) -> dict:
    """Aggregate reconstructed event matches into raw matchup counts for [start, end].

    Returns {(deck_a, deck_b): {...}} for EVERY ordered pair seen, each with
    wins/losses/draws/matches, unique pilots on both sides, Wilson and
    pilot-clustered intervals, events, and provenance. Draws count as matches
    but not as wins. Raises EpochCrossingError if the window spans an epoch
    boundary (pass allow_cross_epoch=True to override deliberately).
    """
    if not allow_cross_epoch:
        e0 = epoch_of(start, epochs)
        e1 = epoch_of(end, epochs) if end else epoch_of("9999-12-31", epochs)
        if e0 != e1:
            raise EpochCrossingError(f"{start}..{end or 'now'} spans epochs {e0} -> {e1}")
    lab = family if use_family else (lambda x: x)
    acc = defaultdict(lambda: {"wins": 0, "losses": 0, "draws": 0, "pilots_a": defaultdict(lambda: [0, 0]),
                               "pilots_b": set(), "events": set()})
    for ev in events:
        day = (ev.get("started_at") or "")[:10]
        if "error" in ev or day < start or (end and day > end):
            continue
        for m in ev.get("matches", []):
            if only_both_published and not m.get("both_published"):
                continue
            if m.get("playoff") and not include_playoffs:
                continue
            A, B = lab(m.get("a_archetype")), lab(m.get("b_archetype"))
            if not A or not B or A == B:
                continue
            for x, y, xp, yp, res in ((A, B, m["a_login"], m["b_login"], m["result"]),
                                      (B, A, m["b_login"], m["a_login"],
                                       {"a": "b", "b": "a", "draw": "draw"}[m["result"]])):
                r = acc[(x, y)]
                r["events"].add(ev.get("number"))
                r["pilots_b"].add(yp)
                pw = r["pilots_a"][xp]
                pw[1] += 1
                if res == "a":
                    r["wins"] += 1
                    pw[0] += 1
                elif res == "b":
                    r["losses"] += 1
                else:
                    r["draws"] += 1
    out = {}
    for key, r in acc.items():
        n = r["wins"] + r["losses"] + r["draws"]
        out[key] = {"wins": r["wins"], "losses": r["losses"], "draws": r["draws"], "matches": n,
                    "win_rate": round(100 * r["wins"] / n, 1) if n else None,
                    "wilson": wilson(r["wins"], n),
                    "pilot_ci": _cluster_ci(r["pilots_a"]) if n >= 10 else None,
                    "unique_pilots_a": len(r["pilots_a"]), "unique_pilots_b": len(r["pilots_b"]),
                    "events": len(r["events"]), "window": [start, end],
                    "unit": "match", "provenance": "mymtgo_reconstructed",
                    "labels": "family" if use_family else "raw"}
    return out


def sensitivity(rows: list[dict], parent: str) -> dict:
    """Matchup-spread rows (scrapers.mymtgo.parse_deck()['matchups']) -> raw rate vs
    `parent` alone and merged with every '<parent> (Provisional)'-style sibling.
    If a conclusion flips between the two, it is not safe to act on."""
    main = [r for r in rows if r["opp_name"] == parent and r.get("wins") is not None]
    sib = [r for r in rows if r["opp_name"] != parent and family(r["opp_name"]) == parent
           and r.get("wins") is not None]
    def rate(rs):
        w = sum(r["wins"] for r in rs)
        n = sum(r["matches"] for r in rs)
        return (round(100 * w / n, 1) if n else None), w, n
    a, b = rate(main), rate(main + sib)
    return {"parent_only": {"rate": a[0], "wins": a[1], "matches": a[2]},
            "with_provisional": {"rate": b[0], "wins": b[1], "matches": b[2]},
            "siblings": [r["opp_name"] for r in sib]}
