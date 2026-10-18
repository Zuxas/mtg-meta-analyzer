"""
Testing gauntlet built from the current metagame (#9).

build_gauntlet() ranks the field over a date window, picks the archetypes to
test against, weights them, and resolves each to a real recent decklist with
event / date provenance. reweight() re-applies manual include / exclude /
weight edits without touching the DB, and save_gauntlet() writes the snapshot
as JSON: the saved file is both the record of the exact field used and the
export other tools (mtg-sim, the harness) read.

Qt-free; the GUI lives in gui/tabs/gauntlet.py.

Snapshot schema "mtg-meta-analyzer/gauntlet@1":
  format, created_at, window {since, until, days}, params, field_source
  ("decks" = tournament placements, "matches" = melee.gg match seats),
  total_field (observations behind the shares; None for the matches source),
  field     {archetype: percent}  normalized TESTING weights of the selected
            archetypes, 1 decimal, summing to ~100 -- the same shape as
            mtg-sim's format_config get_field()
  observed_field {archetype: percent}  observed field share of the same
            archetypes (does not sum to 100: the rest of the field is untested)
  entries   every candidate: archetype, share (observed, 0-1), weight
            (testing, 0-1, 0 when not selected), selected, included (manual),
            weight_override, decklist (or None), warnings
  content_sha256  hash of the snapshot minus this key, so results produced
            from a file can be tied to its exact content
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta

from db.helpers import SQL_NORM_DATE

SCHEMA = "mtg-meta-analyzer/gauntlet@1"
STALE_LIST_DAYS = 30
MIN_MAIN = 60


def _canon(name: str) -> str:
    from analysis.archetypes import normalize
    return normalize(name) or name


def _key(name: str) -> str:
    return _canon(name).casefold()


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------

def field_shares(format_name: str, since: date, until: date) -> tuple[list[dict], str, int | None]:
    """([{archetype, appearances, share}], source, total_field) for the window,
    with stored aliases merged under their canonical name (#32 has not
    relabelled stored rows yet). Ranked by share desc, then name, so ties are
    deterministic."""
    from analysis.win_rates import get_meta_standings
    rows = get_meta_standings(
        format_name, since=datetime.combine(since, datetime.min.time()),
        until=datetime.combine(until, datetime.max.time()),
        min_appearances=1, top=1_000_000, sort_by="appearances")
    source = "matches" if any(r.get("_source") == "matches" for r in rows) else "decks"
    total = rows[0].get("total_field") if rows and source == "decks" else None
    merged: dict[str, dict] = {}
    for r in rows:
        name = _canon(r["archetype"])
        m = merged.setdefault(name.casefold(), {"archetype": name, "appearances": 0,
                                                "share": 0.0, "aliases": []})
        m["appearances"] += r["appearances"]
        m["share"] += r.get("meta_share") or 0.0
        if r["archetype"] != name:
            m["aliases"].append(r["archetype"])
    ranked = sorted(merged.values(), key=lambda m: (-m["share"], m["archetype"].casefold()))
    for m in ranked:
        m["share"] = round(m["share"], 6)
    return ranked, source, total


# ---------------------------------------------------------------------------
# Representative decklists
# ---------------------------------------------------------------------------

def stored_names(con, format_name: str) -> dict[str, list[str]]:
    """{canonical key: [stored archetype labels]} for one format, so a list
    lookup also finds decks still stored under an old alias."""
    out: dict[str, list[str]] = {}
    for (n,) in con.execute(
            "SELECT DISTINCT d.archetype FROM decks d JOIN events e ON e.id = d.event_id "
            "WHERE lower(e.format) = ?", (format_name.lower(),)):
        if n:
            out.setdefault(_key(n), []).append(n)
    return out


def representative_deck(con, format_name: str, archetype: str, since: date,
                        until: date, today: date, allow_stale: bool = False,
                        names: dict | None = None):
    """(decklist dict or None, warnings). The NEWEST qualifying list in the
    window, then the best placement, then the highest deck id. Outside the
    window only when allow_stale -- an old list is never used silently.
    `names` = stored_names() output, passed in to avoid rebuilding it."""
    d = SQL_NORM_DATE.format(col="e.date")
    if names is None:
        names = stored_names(con, format_name)
    stored = sorted(names.get(archetype.casefold(), []))
    if not stored:
        return None, ["no decklist for this archetype in the database"]
    marks = ",".join("?" * len(stored))
    base = (f"SELECT d.id, d.player, d.placement, d.url, e.name, {d} AS dt, e.url "
            f"FROM decks d JOIN events e ON e.id = d.event_id "
            f"WHERE lower(e.format) = ? AND d.archetype IN ({marks}) "
            f"AND EXISTS (SELECT 1 FROM deck_cards c WHERE c.deck_id = d.id AND c.is_sideboard = 0)")
    order = " ORDER BY dt DESC, (d.placement IS NULL), d.placement, d.id DESC LIMIT 1"
    args = [format_name.lower(), *stored]
    row = con.execute(base + f" AND {d} BETWEEN ? AND ?" + order,
                      args + [since.isoformat(), until.isoformat()]).fetchone()
    warnings = []
    if row is None:
        newest = con.execute(base + order, args).fetchone()
        if newest is None:
            return None, ["no decklist for this archetype in the database"]
        if not allow_stale:
            return None, [f"no decklist in the window; newest is from {newest[5]} "
                          "(allow older lists to use it)"]
        row = newest
        warnings.append(f"list is from outside the window ({row[5]})")
    deck_id, player, placement, url, event, dt, event_url = row
    if dt and (today - date.fromisoformat(dt)).days > STALE_LIST_DAYS:
        warnings.append(f"list is {(today - date.fromisoformat(dt)).days} days old")
    cards = con.execute(
        "SELECT c.quantity, k.name, c.is_sideboard FROM deck_cards c "
        "JOIN cards k ON k.id = c.card_id WHERE c.deck_id = ? "
        "ORDER BY c.is_sideboard, c.quantity DESC, k.name", (deck_id,)).fetchall()
    main = [[q, n] for q, n, sb in cards if not sb]
    side = [[q, n] for q, n, sb in cards if sb]
    n_main = sum(q for q, _ in main)
    if n_main < MIN_MAIN:
        warnings.append(f"incomplete list: {n_main} main-deck cards")
    if not side:
        warnings.append("no sideboard recorded")
    text = "\n".join(f"{q} {n}" for q, n in main)
    if side:
        text += "\n\nSideboard\n" + "\n".join(f"{q} {n}" for q, n in side)
    return {"deck_id": deck_id, "event": event, "event_date": dt, "placement": placement,
            "player": player, "url": url or event_url,
            "main": main, "side": side, "text": text}, warnings


# ---------------------------------------------------------------------------
# Selection and weights
# ---------------------------------------------------------------------------

def _select(entries, size, min_share, include, exclude):
    inc = {_key(n) for n in include}
    exc = {_key(n) for n in exclude} - inc
    for e in entries:
        k = e["archetype"].casefold()
        e["included"] = k in inc
        e["selected"] = k in inc
    room = size - sum(e["selected"] for e in entries)
    for e in entries:                     # entries are already ranked
        if room <= 0:
            break
        if not e["selected"] and e["archetype"].casefold() not in exc and e["share"] >= min_share:
            e["selected"] = True
            room -= 1


def reweight(g: dict, selected=None, weights=None) -> dict:
    """Apply manual selection / weight overrides to a built gauntlet, in place.
    `selected` = archetype names to test (None keeps the current selection);
    `weights` = {archetype: relative weight} overrides (None keeps them).
    Weights are relative: each selected entry uses its override, else its
    observed share; they are normalized to sum to 1. All zero -> equal."""
    if selected is not None:
        sel = {_key(n) for n in selected}
        for e in g["entries"]:
            e["selected"] = e["archetype"].casefold() in sel
    if weights is not None:
        ov = {_key(n): float(w) for n, w in weights.items()}
        for e in g["entries"]:
            e["weight_override"] = ov.get(e["archetype"].casefold())
    chosen = [e for e in g["entries"] if e["selected"]]
    raw = {id(e): (e["weight_override"] if e.get("weight_override") is not None
                   else e["share"]) for e in chosen}
    total = sum(max(v, 0.0) for v in raw.values())
    for e in g["entries"]:
        if not e["selected"]:
            e["weight"] = 0.0
        elif total > 0:
            e["weight"] = round(max(raw[id(e)], 0.0) / total, 6)
        else:
            e["weight"] = round(1 / len(chosen), 6)
    g["field"] = {e["archetype"]: round(e["weight"] * 100, 1)
                  for e in sorted(chosen, key=lambda e: (-e["weight"], e["archetype"].casefold()))}
    g["observed_field"] = {e["archetype"]: round(e["share"] * 100, 1) for e in chosen
                           if e["archetype"] in g["field"]}
    over = sum(e["included"] for e in chosen) > g["params"]["size"]
    g["warnings"] = ([f"manual includes exceed the field size ({g['params']['size']})"]
                     if over else [])
    return g


def build_gauntlet(format_name: str, days: int = 14, size: int = 8,
                   min_share: float = 0.02, include=(), exclude=(), weights=None,
                   allow_stale: bool = False, today: date | None = None,
                   con=None) -> dict:
    """Rank the field over the last `days` days, select `size` archetypes
    (manual includes first, excludes skipped, then by share >= min_share),
    weight them and resolve a representative list for every candidate."""
    today = today or date.today()
    since = today - timedelta(days=days - 1)
    ranked, source, total = field_shares(format_name, since, today)
    known = {m["archetype"].casefold() for m in ranked}
    for name in include:                  # a manual include absent from the data
        c = _canon(name)
        if c.casefold() not in known:
            ranked.append({"archetype": c, "appearances": 0, "share": 0.0, "aliases": []})
            known.add(c.casefold())
    entries = [{**m, "selected": False, "included": False, "weight": 0.0,
                "weight_override": None, "decklist": None, "warnings": []} for m in ranked]
    for e in entries:
        if e["appearances"] == 0:
            e["warnings"].append("not in the field data for this window")
    _select(entries, size, min_share, include, exclude)

    own = con is None
    if own:
        from db.database import get_connection
        con = get_connection()
    try:
        names = stored_names(con, format_name)
        for e in entries:
            e["decklist"], w = representative_deck(con, format_name, e["archetype"],
                                                   since, today, today, allow_stale, names)
            e["warnings"] += w
    finally:
        if own:
            con.close()

    g = {"schema": SCHEMA, "format": format_name.lower(),
         "created_at": None,
         "window": {"since": since.isoformat(), "until": today.isoformat(), "days": days},
         "params": {"size": size, "min_share": min_share, "include": list(include),
                    "exclude": list(exclude), "allow_stale": allow_stale,
                    "list_policy": "newest list in the window, then best placement, "
                                   "then highest deck id"},
         "field_source": source, "total_field": total, "entries": entries}
    return reweight(g, weights=weights or {})


# ---------------------------------------------------------------------------
# Persistence / export
# ---------------------------------------------------------------------------

def _hash(g: dict) -> str:
    body = {k: v for k, v in g.items() if k != "content_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def default_dir() -> str:
    """Beside the database (like the raw MTGO captures), so every checkout and
    the backups see the same snapshots."""
    from db import database
    return os.path.join(os.path.dirname(os.path.abspath(database.DB_PATH)), "gauntlets")


def save_gauntlet(g: dict, directory: str | None = None, now: datetime | None = None) -> str:
    """Write the snapshot to <directory>/<format>-<YYYYMMDD-HHMMSS>.json and
    return the path. Never overwrites: a name collision gets a -2, -3 suffix."""
    now = now or datetime.now()
    directory = os.path.normpath(directory or default_dir())
    os.makedirs(directory, exist_ok=True)
    out = dict(g, created_at=now.isoformat(timespec="seconds"))
    out["content_sha256"] = _hash(out)
    stem = f"{out['format']}-{now:%Y%m%d-%H%M%S}"
    path, n = os.path.join(directory, stem + ".json"), 1
    while True:
        try:
            with open(path, "x", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            return path
        except FileExistsError:
            n += 1
            path = os.path.join(directory, f"{stem}-{n}.json")


def load_gauntlet(path: str) -> dict:
    """Read a snapshot and check its schema tag and content hash."""
    with open(path, encoding="utf-8") as f:
        g = json.load(f)
    if g.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} file: {g.get('schema')!r}")
    if g.get("content_sha256") != _hash(g):
        raise ValueError("content hash mismatch: the file was edited after it was saved")
    return g
