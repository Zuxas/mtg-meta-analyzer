"""
Win rate and performance tracking for MTG archetypes.

Important note on data limitations:
  MTGTop8 publishes top finishing decklists, not full round-by-round records.
  True match W/L is not available from this source. Where "win %" is shown,
  it is ESTIMATED from placement tiers in known event formats (see _estimate_record).
  All estimates are labeled clearly so you know what's real vs inferred.

Core functions (no UI coupling):
    parse_date_range(text)
    get_archetype_stats(archetype, format_name, event_type, since, until)
    get_meta_standings(format_name, event_type, min_appearances, top, since, until)
    get_archetype_trend(archetype, format_name, weeks, event_type, since, until)
    get_head_to_head(archetype_a, archetype_b, format_name, since, until)
    get_archetype_matchups(archetype, format_name, since, until, min_shared_events)
    get_matchup_matrix(format_name, min_appearances, since, until, top)
    optimize_field_composition(field, format_name, since, until)
"""

import re
from datetime import datetime, timedelta
from db.database import get_connection, get_combined_connection


# ---------------------------------------------------------------------------
# Natural language date range parsing
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10,
    'november': 11, 'december': 12,
}


def _parse_single_date(s, default_year=None):
    """
    Parse one date token into a datetime.
    Handles: "feb2", "feb 2", "feb 2 2025", "2025-02-14", "today", "now".
    """
    s = s.strip().lower()
    if s in ('today', 'now'):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # ISO format
    try:
        return datetime.strptime(s, '%Y-%m-%d')
    except ValueError:
        pass

    # Insert space between letters and digits: "feb2" -> "feb 2", "oct25" -> "oct 25"
    s = re.sub(r'([a-z])(\d)', r'\1 \2', s)
    parts = s.split()

    if len(parts) >= 2:
        month = _MONTH_MAP.get(parts[0])
        if month is None:
            return None
        try:
            day = int(parts[1])
        except ValueError:
            return None
        year = default_year or datetime.now().year
        if len(parts) >= 3:
            try:
                year = int(parts[2])
            except ValueError:
                pass
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    return None


def parse_date_range(text):
    """
    Parse a natural language date range into (since, until) datetimes.

    Supported patterns:
      "last 30 days" / "last 2 weeks" / "last 3 months"
      "since 2025-01-01" / "since feb 2"
      "feb2-mar9"           (current year)
      "feb 2 - mar 9"
      "oct 25 2025 - today"
      "2025-01-01 - 2025-03-01"

    Returns (since_dt, until_dt) or (None, None) if unparseable.
    """
    if not text:
        return None, None

    text = text.strip().lower()
    now = datetime.now()

    # "last N days/weeks/months"
    m = re.match(r'last\s+(\d+)\s+(day|days|week|weeks|month|months)', text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if 'month' in unit:
            delta = timedelta(days=n * 30)
        elif 'week' in unit:
            delta = timedelta(weeks=n)
        else:
            delta = timedelta(days=n)
        return now - delta, now

    # "since DATE"
    m = re.match(r'since\s+(.+)', text)
    if m:
        since = _parse_single_date(m.group(1).strip())
        return since, now

    # Split range on " - " (with spaces) first
    if ' - ' in text:
        left, right = text.split(' - ', 1)
    else:
        # Try splitting on "-" where one side starts with a letter (e.g. "feb2-mar9")
        m = re.match(r'^(.+?)-([a-z].+)$', text)
        if m:
            left, right = m.group(1), m.group(2)
        else:
            left, right = text, None

    if right is not None:
        since = _parse_single_date(left.strip())
        until = _parse_single_date(right.strip())
        if since and until:
            return since, until + timedelta(days=1)  # until is inclusive
        if since:
            return since, now

    # Single token — treat as "since DATE"
    since = _parse_single_date(text)
    if since:
        return since, now

    return None, None


# ---------------------------------------------------------------------------
# Match record estimation
# ---------------------------------------------------------------------------

_TOTAL_PLAYERS = {
    "mtgo_challenge_32": 32,
    "mtgo_challenge_64": 64,
    "mtgo_league":        5,
    "mtgo_preliminary":  32,
}

_POINTS = {1: 8, 2: 6, 3: 5, 4: 5, 5: 4, 6: 4, 7: 4, 8: 4}


def _swiss_rounds(total_players):
    if total_players <= 8:   return 3
    if total_players <= 16:  return 4
    if total_players <= 32:  return 5
    if total_players <= 64:  return 6
    return 7


def _estimate_record(placement, event_type, max_placement):
    """
    Estimate match wins/losses from placement.
    Returns (wins, losses, is_estimated: bool).
    League 5-0 is the only exact record; all others are estimated.
    """
    if event_type == "mtgo_league":
        return 5, 0, False

    total = _TOTAL_PLAYERS.get(event_type)
    if total is None:
        total = max(max_placement * 2, 8)

    rounds = _swiss_rounds(total)
    top8 = total >= 8

    if top8 and placement <= 8:
        top8_wins   = {1: 3, 2: 2, 3: 1, 4: 1, 5: 0, 6: 0, 7: 0, 8: 0}
        top8_losses = {1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1}
        swiss_wins   = rounds - 1
        swiss_losses = 1
        w = swiss_wins  + top8_wins.get(placement, 0)
        l = swiss_losses + top8_losses.get(placement, 0)
    else:
        fraction = 1.0 - (placement - 1) / max(max_placement - 1, 1)
        max_wins = rounds - 1
        min_wins = rounds // 2
        w = round(min_wins + fraction * (max_wins - min_wins))
        l = rounds - w

    return max(w, 0), max(l, 0), True


def _performance_score(placement, max_placement):
    if max_placement <= 1:
        return 100.0
    return round(100 * (1 - (placement - 1) / (max_placement - 1)), 1)


def _points_for_placement(placement):
    return _POINTS.get(placement, 1 if placement <= 16 else 0)


def _parse_date(date_str):
    for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _dt_to_db_str(dt):
    # Normalize to YYYYMMDD for comparison against _DATE_KEY
    return dt.strftime('%Y%m%d') if dt else None


# Normalize stored dates to YYYYMMDD for correct ordering and filtering.
# MTGTop8 stores DD/MM/YY; MTGDecks stores YYYY-MM-DD.
_DATE_KEY = (
    "CASE WHEN instr(e.date,'/')>0 "
    "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
    "ELSE replace(e.date,'-','') END"
)


# ---------------------------------------------------------------------------
# Core DB queries
# ---------------------------------------------------------------------------

def _fetch_appearances(conn, archetype, format_name=None, event_type=None,
                       since=None, until=None):
    """
    Return all deck appearances for an archetype with event context.
    since/until: datetime objects or None.
    """
    q = """
        SELECT
            d.id          AS deck_id,
            d.archetype,
            d.player,
            d.placement,
            e.id          AS event_id,
            e.name        AS event_name,
            e.date,
            e.format,
            e.event_type,
            (SELECT MAX(d2.placement) FROM decks d2 WHERE d2.event_id = e.id)
                          AS max_placement
        FROM decks d
        JOIN events e ON e.id = d.event_id
        WHERE lower(d.archetype) LIKE lower(?)
    """
    params = [f"%{archetype}%"]

    if format_name:
        q += " AND lower(e.format) = lower(?)"
        params.append(format_name)
    if event_type:
        q += " AND e.event_type = ?"
        params.append(event_type)
    if since:
        q += f" AND {_DATE_KEY} >= ?"
        params.append(_dt_to_db_str(since))
    if until:
        q += f" AND {_DATE_KEY} <= ?"
        params.append(_dt_to_db_str(until))

    q += f" ORDER BY {_DATE_KEY} DESC, d.placement ASC"
    return conn.execute(q, params).fetchall()


def _aggregate_appearances(rows):
    if not rows:
        return None

    appearances   = len(rows)
    event_ids     = {r["event_id"] for r in rows}
    wins          = sum(1 for r in rows if r["placement"] == 1)
    top8          = sum(1 for r in rows if r["placement"] <= 8)
    top8_eligible = sum(1 for r in rows if r["max_placement"] >= 8)

    total_est_w = total_est_l = 0
    total_score = total_pts   = 0

    for r in rows:
        w, l, _ = _estimate_record(r["placement"], r["event_type"], r["max_placement"])
        total_est_w += w
        total_est_l += l
        total_score += _performance_score(r["placement"], r["max_placement"])
        total_pts   += _points_for_placement(r["placement"])

    est_total  = total_est_w + total_est_l
    est_winpct = total_est_w / est_total if est_total else 0.0

    return {
        "appearances":       appearances,
        "unique_events":     len(event_ids),
        "event_wins":        wins,
        "win_rate":          round(wins / len(event_ids), 3) if event_ids else 0,
        "top8_appearances":  top8,
        "top8_eligible":     top8_eligible,
        "top8_rate":         round(top8 / top8_eligible, 3) if top8_eligible else 0.0,
        "avg_performance":   round(total_score / appearances, 1),
        "total_points":      total_pts,
        "avg_points":        round(total_pts / appearances, 2),
        "est_match_wins":    total_est_w,
        "est_match_losses":  total_est_l,
        "est_match_winpct":  round(est_winpct, 3),
        "est_note":          "Match W/L estimated from placement tiers -- not actual records",
    }


def _best_per_event(rows):
    """Reduce appearance rows to {event_id: best_placement}."""
    best = {}
    for r in rows:
        eid = r["event_id"]
        if eid not in best or r["placement"] < best[eid]:
            best[eid] = r["placement"]
    return best


def _matchup_stats(self_best, opp_best):
    """
    Compute placement-based matchup stats given two {event_id: placement} dicts.
    Returns dict with wins/losses/ties/win_rate/shared_events, or None if no shared events.
    """
    shared = set(self_best) & set(opp_best)
    if not shared:
        return None

    wins = losses = ties = 0
    self_pl = []
    opp_pl  = []
    for eid in shared:
        sp = self_best[eid]
        op = opp_best[eid]
        self_pl.append(sp)
        opp_pl.append(op)
        if sp < op:
            wins += 1
        elif op < sp:
            losses += 1
        else:
            ties += 1

    total = len(shared)
    return {
        "wins":             wins,
        "losses":           losses,
        "ties":             ties,
        "win_rate":         round(wins / total, 3),
        "shared_events":    total,
        "avg_placement":    round(sum(self_pl) / total, 1),
        "opp_avg_placement": round(sum(opp_pl) / total, 1),
    }


def _confidence_label(shared_events):
    if shared_events is None or shared_events == 0:
        return "none"
    if shared_events >= 8:
        return "high"
    if shared_events >= 3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_archetype_stats(archetype, format_name="standard", event_type=None,
                        include_archive=False, since=None, until=None):
    """
    Full performance stats for one archetype.
    since/until: datetime objects (use parse_date_range() for natural language input).
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows = _fetch_appearances(conn, archetype, format_name, event_type, since, until)
    finally:
        conn.close()

    if not rows:
        return None

    stats = _aggregate_appearances(rows)
    stats["archetype"]         = archetype
    stats["format"]            = format_name
    stats["event_type_filter"] = event_type
    return stats


def get_meta_standings(format_name="standard", event_type=None,
                       min_appearances=3, top=20, include_archive=False,
                       since=None, until=None):
    """
    Ranked performance table for all archetypes in a format.
    Returns list of stats dicts sorted by avg_points descending.

    Uses a single bulk query (instead of one query per archetype) to avoid
    the N+1 performance problem on large databases.
    """
    from collections import defaultdict

    conn = get_combined_connection(include_archive=include_archive)
    try:
        # Single query: fetch all deck+event rows for the format at once.
        # max_placement per event is pre-aggregated via a subquery join.
        q = """
            SELECT
                d.id          AS deck_id,
                d.archetype,
                d.player,
                d.placement,
                e.id          AS event_id,
                e.name        AS event_name,
                e.date,
                e.format,
                e.event_type,
                mp.max_placement
            FROM decks d
            JOIN events e ON e.id = d.event_id
            JOIN (
                SELECT event_id, MAX(placement) AS max_placement
                FROM decks
                GROUP BY event_id
            ) mp ON mp.event_id = e.id
            WHERE lower(e.format) = lower(?) AND d.archetype != ''
        """
        params = [format_name]
        if event_type:
            q += " AND e.event_type = ?"
            params.append(event_type)
        if since:
            q += " AND e.date >= ?"
            params.append(_dt_to_db_str(since))
        if until:
            q += " AND e.date <= ?"
            params.append(_dt_to_db_str(until))

        all_rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    # Group by archetype in Python, then aggregate each group
    arch_rows = defaultdict(list)
    for row in all_rows:
        arch_rows[row["archetype"]].append(row)

    results = []
    for arch, rows in arch_rows.items():
        if len(rows) < min_appearances:
            continue
        stats = _aggregate_appearances(rows)
        stats["archetype"] = arch
        results.append(stats)

    results.sort(key=lambda s: (s["avg_points"], s["top8_rate"]), reverse=True)
    return results[:top]


def get_archetype_trend(archetype, format_name="standard", weeks=8,
                        event_type=None, include_archive=False,
                        since=None, until=None):
    """
    Week-by-week performance breakdown for an archetype.
    If since/until are given, buckets the window they define (up to `weeks` buckets).
    Returns list of weekly stats dicts, most recent first.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        all_rows = _fetch_appearances(conn, archetype, format_name, event_type, since, until)
    finally:
        conn.close()

    if not all_rows:
        return []

    conn2 = get_combined_connection(include_archive=include_archive)
    try:
        total_q = """
            SELECT e.date, COUNT(d.id) as n
            FROM decks d JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?)
        """
        total_params = [format_name]
        if since:
            total_q += f" AND {_DATE_KEY} >= ?"
            total_params.append(_dt_to_db_str(since))
        if until:
            total_q += f" AND {_DATE_KEY} <= ?"
            total_params.append(_dt_to_db_str(until))
        total_q += " GROUP BY e.id"
        total_rows = conn2.execute(total_q, total_params).fetchall()
    finally:
        conn2.close()

    window_end   = until or datetime.now()
    window_start = since or (window_end - timedelta(weeks=weeks))
    span_weeks   = max(1, int((window_end - window_start).days / 7) + 1)
    num_buckets  = min(span_weeks, weeks)

    weekly = []
    for w in range(num_buckets):
        week_end   = window_end - timedelta(weeks=w)
        week_start = window_end - timedelta(weeks=w + 1)

        week_rows = [
            r for r in all_rows
            if _parse_date(r["date"]) and
               week_start <= _parse_date(r["date"]) < week_end
        ]
        total_in_week = sum(
            r["n"] for r in total_rows
            if _parse_date(r["date"]) and
               week_start <= _parse_date(r["date"]) < week_end
        )

        if not week_rows and total_in_week == 0:
            continue

        stats = _aggregate_appearances(week_rows) if week_rows else None
        weekly.append({
            "week_start":            week_start.strftime("%Y-%m-%d"),
            "week_end":              week_end.strftime("%Y-%m-%d"),
            "appearances":           len(week_rows),
            "total_decks_in_format": total_in_week,
            "meta_share":            round(len(week_rows) / total_in_week, 3) if total_in_week else 0,
            "top8_rate":             stats["top8_rate"]       if stats else None,
            "avg_points":            stats["avg_points"]      if stats else None,
            "event_wins":            stats["event_wins"]      if stats else 0,
            "est_winpct":            stats["est_match_winpct"] if stats else None,
        })

    return weekly


def get_head_to_head(archetype_a, archetype_b, format_name="standard",
                     include_archive=False, since=None, until=None):
    """
    Head-to-head: events where both archetypes appeared.
    A "win" = archetype_a's best placement in the event was better than B's.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows_a = _fetch_appearances(conn, archetype_a, format_name, since=since, until=until)
        rows_b = _fetch_appearances(conn, archetype_b, format_name, since=since, until=until)
    finally:
        conn.close()

    best_a = _best_per_event(rows_a)
    best_b = _best_per_event(rows_b)

    shared = set(best_a) & set(best_b)
    if not shared:
        return {"shared_events": 0, "note": "No events where both archetypes appeared"}

    a_wins = b_wins = ties = 0
    a_placements = []
    b_placements = []
    matchups = []

    # Rebuild rows_a/rows_b dicts for event metadata
    meta_a = {r["event_id"]: dict(r) for r in rows_a}
    meta_b = {r["event_id"]: dict(r) for r in rows_b}

    for eid in sorted(shared):
        pa = best_a[eid]
        pb = best_b[eid]
        a_placements.append(pa)
        b_placements.append(pb)

        if pa < pb:
            result = f"{archetype_a} wins"
            a_wins += 1
        elif pb < pa:
            result = f"{archetype_b} wins"
            b_wins += 1
        else:
            result = "Tie"
            ties += 1

        ev = meta_a.get(eid) or meta_b.get(eid)
        matchups.append({
            "event":                      ev["event_name"],
            "date":                       ev["date"],
            f"{archetype_a}_place":       pa,
            f"{archetype_b}_place":       pb,
            "result":                     result,
        })

    total = len(shared)
    return {
        "archetype_a":     archetype_a,
        "archetype_b":     archetype_b,
        "shared_events":   total,
        "a_wins":          a_wins,
        "b_wins":          b_wins,
        "ties":            ties,
        "a_win_rate":      round(a_wins / total, 3),
        "b_win_rate":      round(b_wins / total, 3),
        "a_avg_placement": round(sum(a_placements) / total, 1),
        "b_avg_placement": round(sum(b_placements) / total, 1),
        "confidence":      _confidence_label(total),
        "matchups":        sorted(matchups, key=lambda m: m["date"], reverse=True),
        "note": "H2H based on best placement when both appeared in same event, not actual match results",
    }


def get_archetype_matchups(archetype, format_name="standard",
                           include_archive=False, since=None, until=None,
                           min_shared_events=2):
    """
    One archetype vs every other archetype it shared events with.
    Returns list of matchup dicts sorted by win_rate descending.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows_self = _fetch_appearances(conn, archetype, format_name, since=since, until=until)
        if not rows_self:
            return []

        self_event_ids = {r["event_id"] for r in rows_self}
        ph = ",".join("?" * len(self_event_ids))
        opponents = [
            r["archetype"]
            for r in conn.execute(
                f"""SELECT DISTINCT d.archetype
                    FROM decks d JOIN events e ON e.id = d.event_id
                    WHERE d.event_id IN ({ph})
                      AND lower(e.format) = lower(?)
                      AND d.archetype != ''
                      AND lower(d.archetype) NOT LIKE lower(?)""",
                list(self_event_ids) + [format_name, f"%{archetype}%"]
            ).fetchall()
        ]

        self_best = _best_per_event(rows_self)

        matchups = []
        for opp in opponents:
            opp_rows = _fetch_appearances(conn, opp, format_name, since=since, until=until)
            opp_best = _best_per_event(opp_rows)
            stats = _matchup_stats(self_best, opp_best)
            if stats is None or stats["shared_events"] < min_shared_events:
                continue
            matchups.append({
                "opponent":          opp,
                "confidence":        _confidence_label(stats["shared_events"]),
                **stats,
            })
    finally:
        conn.close()

    matchups.sort(key=lambda m: (-m["win_rate"], -m["shared_events"]))
    return matchups


def get_matchup_matrix(format_name="standard", min_appearances=5,
                       include_archive=False, since=None, until=None, top=15):
    """
    Full NxN placement-based matchup matrix for top archetypes.
    Returns:
    {
        "archetypes": [list of archetype names, ranked],
        "matrix": {
            archetype_a: {
                archetype_b: {wins, losses, ties, win_rate, shared_events, confidence}
            }
        },
        "note": str,
    }
    """
    standings = get_meta_standings(
        format_name=format_name, min_appearances=min_appearances,
        include_archive=include_archive, since=since, until=until, top=top
    )
    if not standings:
        return {"archetypes": [], "matrix": {}, "note": "No data"}

    archetypes = [s["archetype"] for s in standings]

    conn = get_combined_connection(include_archive=include_archive)
    try:
        all_best = {}
        for arch in archetypes:
            rows = _fetch_appearances(conn, arch, format_name, since=since, until=until)
            all_best[arch] = _best_per_event(rows)
    finally:
        conn.close()

    matrix = {a: {} for a in archetypes}
    for arch_a in archetypes:
        for arch_b in archetypes:
            if arch_a == arch_b:
                continue
            stats = _matchup_stats(all_best[arch_a], all_best[arch_b])
            if stats:
                matrix[arch_a][arch_b] = {
                    **stats,
                    "confidence": _confidence_label(stats["shared_events"]),
                }

    return {
        "archetypes": archetypes,
        "matrix":     matrix,
        "note":       "Based on best placement when both archetypes appeared in the same event",
    }


# ---------------------------------------------------------------------------
# Field Optimizer
# ---------------------------------------------------------------------------

def parse_field_string(field_str):
    """
    Parse a field specification string into {archetype_name: count}.

    Supported formats (comma-separated entries):
      "Izzet Prowess x4"
      "Izzet Prowess x 4"
      "Izzet Prowess 4"
      "4 Izzet Prowess"
      "Izzet Prowess"        (count defaults to 1)

    Returns dict mapping archetype name -> integer count.
    """
    field = {}
    for entry in field_str.split(','):
        entry = entry.strip()
        if not entry:
            continue

        # "Name x4" or "Name x 4"
        m = re.match(r'^(.+?)\s+x\s*(\d+)$', entry, re.IGNORECASE)
        if m:
            field[m.group(1).strip()] = int(m.group(2))
            continue

        # "4 Name"
        m = re.match(r'^(\d+)\s+(.+)$', entry)
        if m:
            field[m.group(2).strip()] = int(m.group(1))
            continue

        # "Name 4"
        m = re.match(r'^(.+?)\s+(\d+)$', entry)
        if m:
            field[m.group(1).strip()] = int(m.group(2))
            continue

        # Just "Name" (count = 1)
        field[entry] = 1

    return field


def optimize_field_composition(field, format_name="standard",
                                include_archive=False, since=None, until=None):
    """
    Calculate weighted win rates for each archetype against a specific expected field.

    field: dict of {archetype_name: count}, e.g. {"Izzet Prowess": 4, "Mono Green": 3}
    Each entry should use a partial archetype name that matches the DB via LIKE.

    Returns:
    {
        "field": {archetype: count},
        "total_players": int,
        "results": [
            {
                "archetype":           str,
                "field_count":         int,
                "weighted_win_rate":   float,   # 0.0-1.0 weighted against the field
                "confidence":          str,     # overall: high/medium/low/none
                "matchups": [
                    {
                        "opponent":        str,
                        "opponent_count":  int,
                        "weight":          float,  # fraction of opponent slots in field
                        "win_rate":        float,
                        "shared_events":   int,
                        "confidence":      str,
                        "favored":         bool,   # win_rate > 0.5
                    },
                    ...
                ],
            },
            ...  (sorted by weighted_win_rate descending)
        ],
        "best_deck":  str,   # highest weighted win rate
        "note": str,
    }
    """
    archetypes = list(field.keys())
    total_players = sum(field.values())

    conn = get_combined_connection(include_archive=include_archive)
    try:
        # Fetch best-per-event for every archetype in the field
        all_best = {}
        for arch in archetypes:
            rows = _fetch_appearances(conn, arch, format_name, since=since, until=until)
            all_best[arch] = _best_per_event(rows)
    finally:
        conn.close()

    results = []
    for arch in archetypes:
        arch_count    = field[arch]
        # Opponents = everyone else in the field
        opp_total     = total_players - arch_count
        if opp_total <= 0:
            # Only archetype in the field
            results.append({
                "archetype":         arch,
                "field_count":       arch_count,
                "weighted_win_rate": None,
                "confidence":        "none",
                "matchups":          [],
            })
            continue

        matchup_details = []
        weighted_sum    = 0.0
        min_shared      = None

        for opp in archetypes:
            if opp == arch:
                continue
            opp_count = field[opp]
            weight    = opp_count / opp_total

            stats = _matchup_stats(all_best[arch], all_best[opp])
            if stats is None:
                wr             = 0.5   # no data: assume even
                shared_events  = 0
                confidence     = "none"
            else:
                wr             = stats["win_rate"]
                shared_events  = stats["shared_events"]
                confidence     = _confidence_label(shared_events)

            weighted_sum += wr * weight

            if min_shared is None or shared_events < min_shared:
                min_shared = shared_events

            matchup_details.append({
                "opponent":       opp,
                "opponent_count": opp_count,
                "weight":         round(weight, 3),
                "win_rate":       wr,
                "shared_events":  shared_events,
                "confidence":     confidence,
                "favored":        wr > 0.5,
            })

        # Sort matchups: most impactful (weight * abs deviation from 0.5) first
        matchup_details.sort(
            key=lambda m: m["weight"] * abs(m["win_rate"] - 0.5),
            reverse=True
        )

        overall_confidence = _confidence_label(min_shared if min_shared is not None else 0)

        results.append({
            "archetype":         arch,
            "field_count":       arch_count,
            "weighted_win_rate": round(weighted_sum, 3),
            "confidence":        overall_confidence,
            "matchups":          matchup_details,
        })

    results.sort(
        key=lambda r: r["weighted_win_rate"] if r["weighted_win_rate"] is not None else -1,
        reverse=True
    )

    best_deck = results[0]["archetype"] if results else None

    return {
        "field":          field,
        "total_players":  total_players,
        "format":         format_name,
        "results":        results,
        "best_deck":      best_deck,
        "note": (
            "Win rates are based on placement comparison in shared events, not actual match records. "
            "Matchups with no data default to 50%."
        ),
    }
