"""
analysis/scout.py -- pilot scouting queries.

Pre-event scout intel: find pilots playing specific archetypes in
recent events, link them to known Twitter handles, surface their
deck URLs for review.

Two main queries:
  - get_priority_finishers(target_archetypes, days, format_name):
      Top-8 finishers playing the supplied archetypes in the last N
      days. Used to scout what people are bringing in matchups you
      care about.
  - get_pilot_history(player_name, format_name):
      Every event finish for a specific pilot in the supplied format,
      sorted newest-first.

Handle resolution: data/player_handles.json (confirmed players +
candidate handles inferred from guide URLs). No live Twitter scrape
in this module -- the caller renders @handle as an external link.
"""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from db.database import DB_PATH as CENTRAL_DB_PATH


def _handle_db():
    p = Path(__file__).resolve().parent.parent / "data" / "player_handles.json"
    if not p.exists():
        return {"players": {}, "handles": {}, "candidates": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"players": {}, "handles": {}, "candidates": {}}


def _resolve_handle(player_name: str, hdb: dict) -> Optional[str]:
    """Best-effort player_name -> @handle resolver."""
    key = (player_name or "").lower().strip()
    if not key:
        return None
    rec = hdb.get("players", {}).get(key)
    if rec and rec.get("handle"):
        return rec["handle"]
    cands = hdb.get("candidates", {})
    if key in cands:
        return cands[key].get("handle")
    last = key.split()[-1] if " " in key else key
    if last in cands:
        return cands[last].get("handle")
    return None


def get_priority_finishers(
    target_archetypes: list,
    days: int = 30,
    format_name: str = "standard",
    placement_cap: int = 8,
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> list:
    """
    Top-cut finishers playing the supplied archetypes in the last N days.
    Returns rows: player, archetype, placement, event_name, date, source,
    url, handle, event_type.
    """
    db_path = db_path or Path(CENTRAL_DB_PATH)
    if not target_archetypes:
        return []
    since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    placeholders = ",".join("?" * len(target_archetypes))
    sql = f"""
    SELECT d.player, d.archetype, d.placement, e.name, e.date,
           e.source, d.url, e.event_type, e.id
    FROM decks d JOIN events e ON e.id = d.event_id
    WHERE lower(e.format) = ?
      AND d.archetype IN ({placeholders})
      AND d.placement <= ?
      AND d.placement > 0
      AND (CASE WHEN instr(e.date,'/')>0
        THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
        ELSE replace(e.date,'-','') END) >= ?
    ORDER BY (CASE WHEN instr(e.date,'/')>0
        THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
        ELSE replace(e.date,'-','') END) DESC,
        d.placement ASC
    LIMIT ?
    """
    params = [format_name.lower(), *target_archetypes, placement_cap,
              since, limit]
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute(sql, params).fetchall()

    hdb = _handle_db()
    out = []
    for player, arch, place, ename, edate, src, url, etype, eid in rows:
        out.append({
            "player":     player,
            "archetype":  arch,
            "placement":  place,
            "event_name": ename,
            "date":       edate,
            "source":     src,
            "url":        url,
            "event_type": etype,
            "event_id":   eid,
            "handle":     _resolve_handle(player, hdb),
        })
    return out


def get_pilot_history(
    player_name: str,
    format_name: str = "standard",
    days: int = 365,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list:
    """Every event finish for a specific pilot."""
    db_path = db_path or Path(CENTRAL_DB_PATH)
    since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    sql = f"""
    SELECT d.player, d.archetype, d.placement, e.name, e.date,
           e.source, d.url, e.event_type
    FROM decks d JOIN events e ON e.id = d.event_id
    WHERE lower(e.format) = ?
      AND lower(d.player) = ?
      AND (CASE WHEN instr(e.date,'/')>0
        THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
        ELSE replace(e.date,'-','') END) >= ?
    ORDER BY (CASE WHEN instr(e.date,'/')>0
        THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
        ELSE replace(e.date,'-','') END) DESC
    LIMIT ?
    """
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute(
            sql, (format_name.lower(), player_name.lower(), since, limit)
        ).fetchall()
    return [
        {
            "player":     r[0], "archetype":  r[1], "placement":  r[2],
            "event_name": r[3], "date":       r[4], "source":     r[5],
            "url":        r[6], "event_type": r[7],
        }
        for r in rows
    ]


def get_pilot_counts(finishers: list) -> list:
    """Aggregate the finishers list: pilot -> top-cut count + last finish."""
    by_pilot: dict = {}
    for r in finishers:
        p = r["player"]
        if p not in by_pilot:
            by_pilot[p] = {
                "player":      p,
                "count":       0,
                "best":        r["placement"],
                "archetypes":  set(),
                "handle":      r.get("handle"),
                "last_event":  r["event_name"],
                "last_date":   r["date"],
            }
        by_pilot[p]["count"] += 1
        by_pilot[p]["best"] = min(by_pilot[p]["best"], r["placement"])
        by_pilot[p]["archetypes"].add(r["archetype"])
    for v in by_pilot.values():
        v["archetypes"] = sorted(v["archetypes"])
    return sorted(by_pilot.values(),
                  key=lambda v: (-v["count"], v["best"]))
