"""Personal matchup spread: your record per opponent archetype, with advice
only where the sample supports it.

Why not `matchup_advisor.get_advice` as-is (probe 2026-09-28 on the live copy):
meta win rates are missing for most opponents, it rated 2-game matchups
'strong', it rated the blank-opponent bucket like a deck, and it cannot tell
casual practice rooms from competitive play. This module keeps the advisor's
severity thresholds and meta lookup, but
  - gives advice only at MIN_ADVICE_N+ games,
  - keeps unknown opponents in their own bucket, never rated,
  - can exclude casual games (MTGO Casual rooms, Arena Direct Games),
  - says "no meta baseline" instead of implying a comparison.
"""
from __future__ import annotations

MIN_ADVICE_N = 5
CASUAL_SQL = "(event_name = 'MTGO Casual' OR event_name LIKE 'Direct Game%')"


def _wr(w: int, n: int) -> float | None:
    return w / n if n else None


def deck_choices(con) -> list[tuple[str, int]]:
    """Every deck with decided matches, by name (text label or saved deck's
    archetype), most-played first."""
    rows = con.execute(
        """SELECT COALESCE(NULLIF(m.my_deck, ''), sd.archetype, sd.name) AS d, COUNT(*)
           FROM match_log m LEFT JOIN saved_decks sd ON sd.id = m.my_deck_id
           WHERE m.result IN ('win', 'loss')
           GROUP BY d HAVING d IS NOT NULL AND d != ''
           ORDER BY 2 DESC, 1""").fetchall()
    return [(r[0], r[1]) for r in rows]


def _severity(wr: float, meta: float | None, n: int) -> tuple[str, str]:
    if meta is not None:
        delta = wr - meta
        if delta <= -0.10 and n >= MIN_ADVICE_N:
            return "critical", f"{delta:+.0%} vs meta ({meta:.0%}) -- review the SB plan"
        if delta <= -0.05:
            return "warning", f"{delta:+.0%} vs meta ({meta:.0%})"
        if wr >= 0.60:
            return "strong", f"{delta:+.0%} vs meta ({meta:.0%})"
        return "ok", f"{delta:+.0%} vs meta ({meta:.0%})"
    if wr >= 0.60:
        return "strong", "no meta baseline"
    if wr < 0.40:
        return "low", "losing record -- no meta baseline to compare"
    return "ok", "no meta baseline"


def matchup_spread(con, my_deck: str, format_name: str | None = None,
                   competitive_only: bool = False, meta_wrs: dict | None = None) -> dict:
    """meta_wrs: {normalized opponent: expected WR}; looked up via the
    advisor when omitted and the format is concrete (never for 'All')."""
    from db.match_log import _my_deck_clause, _my_deck_params
    sql = (f"SELECT opp_deck, result, play_draw FROM match_log "
           f"WHERE {_my_deck_clause()} AND result IN ('win', 'loss')")
    params = _my_deck_params(my_deck)
    if format_name:
        sql += " AND format = ?"
        params.append(format_name)
    if competitive_only:
        sql += f" AND NOT {CASUAL_SQL}"
    rows = con.execute(sql, params).fetchall()

    if meta_wrs is None:
        meta_wrs = {}
        if format_name and rows:
            from analysis.matchup_advisor import _get_meta_wrs
            meta_wrs = _get_meta_wrs(my_deck, format_name)
    from analysis.archetypes import normalize

    tot = {"w": 0, "n": 0, "pw": 0, "pn": 0, "dw": 0, "dn": 0}
    by_opp: dict[str, dict] = {}
    for opp, result, pd in rows:
        win = result == "win"
        for key, cond in (("", True), ("p", pd == "play"), ("d", pd == "draw")):
            if cond:
                tot[key + "n" if key else "n"] += 1
                tot[key + "w" if key else "w"] += win
        o = by_opp.setdefault((opp or "").strip(), {"w": 0, "n": 0})
        o["w"] += win
        o["n"] += 1

    kpis = {
        "wins": tot["w"], "losses": tot["n"] - tot["w"], "matches": tot["n"],
        "wr": _wr(tot["w"], tot["n"]),
        "play_wr": _wr(tot["pw"], tot["pn"]), "play_n": tot["pn"],
        "draw_wr": _wr(tot["dw"], tot["dn"]), "draw_n": tot["dn"],
    }
    unknown = by_opp.pop("", None)
    out_rows = []
    for opp, o in by_opp.items():
        wr = o["w"] / o["n"]
        meta = meta_wrs.get(normalize(opp) or opp)
        row = {"opponent": opp, "wins": o["w"], "losses": o["n"] - o["w"], "n": o["n"],
               "wr": wr, "meta_wr": meta, "severity": None, "note": "small sample"}
        if o["n"] >= MIN_ADVICE_N:
            row["severity"], row["note"] = _severity(wr, meta, o["n"])
        out_rows.append(row)
    rated = sorted((r for r in out_rows if r["severity"]), key=lambda r: (r["wr"], -r["n"]))
    small = sorted((r for r in out_rows if not r["severity"]), key=lambda r: (-r["n"], r["opponent"]))
    return {
        "deck": my_deck, "format": format_name, "competitive_only": competitive_only,
        "kpis": kpis, "rows": rated + small,
        "unknown": ({"wins": unknown["w"], "losses": unknown["n"] - unknown["w"],
                     "n": unknown["n"], "wr": unknown["w"] / unknown["n"]} if unknown else None),
        "has_meta": bool(meta_wrs),
    }
