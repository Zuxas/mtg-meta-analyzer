"""
Per-format, PER-SOURCE recency and a diagnosis of what is stale (issue #8).

analysis/data_health.format_freshness() answers "is this format's match data
fresh?". This module answers the follow-up a stale format needs: WHICH source
stopped, since when, what did its last scrape say, and is the whole format stale
or just one source while another is current. It reuses data_health's thresholds,
classify() and date normalization -- no second definition of "stale".

Diagnoses (scheduled sources only -- see db.scrape_sources):
  ok                      every scheduled source is fresh
  source_stale            at least one scheduled source fresh, at least one not
  format_stale            no scheduled source is fresh
  no_data                 no rows from any source
`events_without_matches` is flagged separately: event data is current but the
match source is not -- e.g. Pioneer: MTGTop8 events to 2026-10-01, MTGMelee
matches stop at 2026-05-09.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from analysis.data_health import (STATUS_FRESH, STATUS_STALE, STATUS_DEAD, _VALID, classify)
from db.helpers import SQL_NORM_DATE

_TABLES = {  # kind -> (table, date column)
    "events": ("events", "date"),
    "matches": ("matches", "event_date"),
}


def _source_rows(con, kind: str, fmt: str, d30: str, d60: str) -> dict:
    table, col = _TABLES[kind]
    d = SQL_NORM_DATE.format(col=col)
    out = {}
    for src, last, n30, nprev in con.execute(f"""
            SELECT source,
                   MAX(CASE WHEN {_VALID.format(d=d)} THEN {d} END),
                   SUM(CASE WHEN {d} >= ? THEN 1 ELSE 0 END),
                   SUM(CASE WHEN {d} >= ? AND {d} < ? THEN 1 ELSE 0 END)
            FROM {table} WHERE lower(format) = ? GROUP BY source""",
            (d30, d60, d30, fmt)):
        out[src] = {"kind": kind, "last_date": last,
                    "rows_30d": int(n30 or 0), "rows_prev_30d": int(nprev or 0)}
    return out


def _scrape_evidence(fmt_state: dict, source: str) -> dict:
    s = ((fmt_state or {}).get("sources") or {}).get(source)
    if not s:
        return {"recorded": False}
    return {"recorded": True, **{k: s.get(k) for k in
            ("last_attempt", "last_status", "last_success", "last_error", "error_class")}}


def explain(src: str, info: dict) -> str:
    """Why is this source not fresh? Uses the scrape evidence when there is some."""
    last = info.get("last_date") or "never"
    sc = info.get("scrape") or {}
    if info["status"] == STATUS_FRESH:
        return f"{src}: fresh (data to {last})"
    head = f"{src}: {info['status']} -- data to {last}"
    if not sc.get("recorded"):
        return head + "; no per-source scrape outcome recorded yet"
    if sc.get("last_status") != "ok":
        since = sc.get("last_success") or "never"
        return (head + f"; last scrape FAILED ({sc.get('error_class')}) at "
                f"{sc.get('last_attempt')}, last success {since}")
    return (head + f"; last scrape reported ok at {sc.get('last_attempt')} but brought no "
            "newer data -- upstream has nothing newer, or the scraper is skipping it")


def source_recency(formats=None, selected_formats=None, *, con=None, today=None,
                   state=None) -> dict:
    """
    {fmt: {"format_status", "diagnosis", "events_without_matches",
           "stale_sources", "fresh_sources",
           "sources": {src: {kind, last_date, rows_30d, rows_prev_30d, days_stale,
                             status, scheduled, scrape:{...}}}}}

    `selected_formats` = the user's formats (decides which sources are scheduled);
    defaults to preferences. `con`, `today`, `state` are injectable for tests.
    """
    from analysis.data_health import format_freshness
    from db.scrape_sources import SOURCES, scheduled_sources

    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    d30 = (today - timedelta(days=30)).isoformat()
    d60 = (today - timedelta(days=60)).isoformat()
    if selected_formats is None:
        from db.helpers import load_active_formats
        selected_formats = load_active_formats(log=lambda *_: None)
    if state is None:
        from db.scrape_state import read_scrape_state
        state = read_scrape_state()

    own = con is None
    if own:
        from db.database import get_connection
        con = get_connection()
    try:
        fresh = format_freshness(formats, con=con, today=today)
        out = {}
        for fmt, finfo in fresh.items():
            fmt_state = (state.get("formats") or {}).get(fmt) or {}
            sources = {}
            for kind in _TABLES:
                sources.update(_source_rows(con, kind, fmt, d30, d60))
            scheduled = scheduled_sources(fmt, selected_formats)
            for src in scheduled:                     # scheduled but zero rows ever
                sources.setdefault(src, {"kind": SOURCES[src]["kind"], "last_date": None,
                                         "rows_30d": 0, "rows_prev_30d": 0})
            for src, info in sources.items():
                days = ((today - date.fromisoformat(info["last_date"])).days
                        if info["last_date"] else None)
                info["days_stale"] = days
                info["status"] = classify(days, info["rows_30d"], info["rows_prev_30d"])
                info["scheduled"] = src in scheduled
                info["scrape"] = _scrape_evidence(fmt_state, src)

            sched = {s: sources[s] for s in scheduled}
            fresh_srcs = sorted(s for s, i in sched.items() if i["status"] == STATUS_FRESH)
            stale_srcs = sorted(s for s, i in sched.items() if i["status"] != STATUS_FRESH)
            if not any(i["last_date"] for i in sources.values()):
                diagnosis = "no_data"
            elif not sched or not stale_srcs:
                diagnosis = "ok"
            elif fresh_srcs:
                diagnosis = "source_stale"
            else:
                diagnosis = "format_stale"
            ev_fresh = any(i["kind"] == "events" and i["status"] == STATUS_FRESH
                           for i in sched.values())
            m_stale = any(i["kind"] == "matches" and i["status"] != STATUS_FRESH
                          for i in sched.values())
            out[fmt] = {
                "format_status": finfo["status"],
                "diagnosis": diagnosis,
                "events_without_matches": ev_fresh and m_stale,
                "fresh_sources": fresh_srcs,
                "stale_sources": stale_srcs,
                "sources": dict(sorted(sources.items())),
            }
        return out
    finally:
        if own:
            con.close()


def describe_recency(fmt: str, rec: dict) -> list[str]:
    """Human-readable lines for one format (report / tooltip / recovery output)."""
    lines = [f"{fmt.capitalize()}: {rec['diagnosis'].replace('_', ' ')}"
             + (" (events current, match data behind)" if rec["events_without_matches"] else "")]
    for src, info in rec["sources"].items():
        if info["scheduled"]:
            lines.append("  " + explain(src, info))
        else:
            lines.append(f"  {src}: not scheduled (data to {info['last_date'] or 'never'})")
    for src in rec["stale_sources"]:
        lines.append(f"  -> recover: python scripts/recover_source.py --format {fmt} --source {src}")
    return lines
