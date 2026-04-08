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
from core.query_engine.dedup_filters import apply_deck_filters

# Archetype names to exclude from real-match win rate calculations.
# These are melee.gg placeholder labels for decks with no name or unrecognized type.
EXCLUDE_ARCHETYPES = frozenset({
    "Decklist",
    "All Other Decklists",
    "Rogue Decklists",
    "Others",
    "Other",
})

# Simple TTL cache for expensive queries (60-second expiry)
_query_cache: dict = {}  # key → (timestamp, result)
_CACHE_TTL = 60  # seconds


def _cached(key, fn):
    """Return cached result if <60s old, otherwise call fn() and cache."""
    import time
    now = time.time()
    if key in _query_cache:
        ts, result = _query_cache[key]
        if now - ts < _CACHE_TTL:
            return result
    result = fn()
    _query_cache[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Natural language date range parsing (extracted to analysis/date_parsing.py)
# ---------------------------------------------------------------------------
from analysis.date_parsing import _MONTH_MAP, _parse_single_date, parse_date_range  # noqa: F401

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
                       since=None, until=None,
                       dedup_cross_source=True, unique_player_decks=False):
    """
    Return all deck appearances for an archetype with event context.
    since/until: datetime objects or None.

    dedup_cross_source (default True):
        Remove rows where the same 75 cards were scraped from multiple sources
        for the same real event (matched by deck_fingerprint + event_fingerprint).
        Prevents double-counting ~7% of standard decks that appear in both
        mtgtop8 and mtgdecks.

    unique_player_decks (default False):
        Collapse a player's repeated appearances with the same 75 to their
        single best result.  Useful for "unique builds" views; off by default
        so each tournament appearance counts as a separate data point.
    """
    q = """
        SELECT
            d.id              AS deck_id,
            d.archetype,
            d.player,
            d.placement,
            d.deck_fingerprint,
            e.id              AS event_id,
            e.name            AS event_name,
            e.date,
            e.format,
            e.event_type,
            e.source          AS event_source,
            e.event_fingerprint,
            e.event_fingerprint_cs,
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
    rows = conn.execute(q, params).fetchall()
    return apply_deck_filters(rows, dedup_cross_source=dedup_cross_source,
                              unique_player_decks=unique_player_decks)


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
                        include_archive=False, since=None, until=None,
                        dedup_cross_source=True, unique_player_decks=False):
    """
    Full performance stats for one archetype.
    since/until: datetime objects (use parse_date_range() for natural language input).
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows = _fetch_appearances(conn, archetype, format_name, event_type, since, until,
                                  dedup_cross_source=dedup_cross_source,
                                  unique_player_decks=unique_player_decks)
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
                       since=None, until=None,
                       dedup_cross_source=True, unique_player_decks=False):
    """
    Ranked performance table for all archetypes in a format.
    Returns list of stats dicts sorted by avg_points descending.

    Uses a single bulk query (instead of one query per archetype) to avoid
    the N+1 performance problem on large databases.

    dedup_cross_source (default True):
        Remove cross-source duplicates before counting.  Without this, decks
        scraped from both mtgtop8 and mtgdecks inflate every archetype's
        appearance count and meta-share by ~7% in standard.

    unique_player_decks (default False):
        Collapse a player's repeated identical 75 to their best result.
    """
    from collections import defaultdict

    conn = get_combined_connection(include_archive=include_archive)
    try:
        # Single query: fetch all deck+event rows for the format at once.
        # max_placement per event is pre-aggregated via a subquery join.
        q = """
            SELECT
                d.id              AS deck_id,
                d.archetype,
                d.player,
                d.placement,
                d.deck_fingerprint,
                e.id              AS event_id,
                e.name            AS event_name,
                e.date,
                e.format,
                e.event_type,
                e.source          AS event_source,
                e.event_fingerprint,
                e.event_fingerprint_cs,
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
            q += f" AND ({_DATE_KEY}) >= ?"
            params.append(_dt_to_db_str(since))
        if until:
            q += f" AND ({_DATE_KEY}) <= ?"
            params.append(_dt_to_db_str(until))

        all_rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    # Remove cross-source and/or player duplicates before counting.
    # This must happen before grouping so appearance counts are accurate.
    all_rows = apply_deck_filters(all_rows, dedup_cross_source=dedup_cross_source,
                                  unique_player_decks=unique_player_decks)

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

    trimmed = results[:top]

    # Fallback: if decks data is too sparse (top archetype < 20 appearances,
    # or total appearances across all results < 100), use matches table instead
    top_apps = trimmed[0]["appearances"] if trimmed else 0
    total_apps = sum(s["appearances"] for s in trimmed)
    if top_apps < 20 or total_apps < 100:
        fallback = _meta_standings_from_matches(format_name, since, until, top,
                                                min_appearances)
        if fallback:
            return fallback

    return trimmed


def _meta_standings_from_matches(format_name, since=None, until=None,
                                 top=20, min_appearances=3):
    """
    Build meta standings from the matches table (melee.gg data) as a fallback
    when the decks table has stale or missing data for the requested format/timeframe.

    Returns a list of dicts compatible with get_meta_standings() output.
    """
    real_wrs = get_real_archetype_winrates(format_name, since=since, min_matches=5)
    if not real_wrs:
        return []

    # Total match appearances across all archetypes
    total = sum(v["total"] for v in real_wrs.values())

    results = []
    for arch, stats in real_wrs.items():
        if arch in EXCLUDE_ARCHETYPES:
            continue
        if stats["total"] < min_appearances:
            continue
        results.append({
            "archetype":         arch,
            "appearances":       stats["total"],
            "meta_share":        round(stats["total"] / total, 4) if total else 0,
            "est_match_winpct":  stats["win_rate"],
            "avg_points":        0,
            "top8_rate":         None,
            "event_wins":        0,
            "_source":           "matches",  # marker for dashboard warning
        })

    results.sort(key=lambda s: -s["appearances"])
    return results[:top]


def _parse_match_date(raw: str):
    """Parse event_date from matches table — handles both YYYY-MM-DD and DD/MM/YY."""
    if not raw:
        return None
    try:
        if "/" in raw:
            return datetime.strptime(raw, "%d/%m/%y")
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _archetype_trend_from_matches(archetype, format_name, weeks, since, until,
                                   granularity="weekly"):
    """
    Build archetype trend data from the matches table as a fallback when the
    decks table has no data for this archetype.

    Groups matches by time bucket, counts appearances and calculates win rate.
    Returns the same data structure as get_archetype_trend().
    """
    from db.database import get_connection

    window_end   = until or datetime.now()
    window_start = since or (window_end - timedelta(weeks=weeks or 52))

    excl_ph = ",".join("?" * len(EXCLUDE_ARCHETYPES))
    excl_list = list(EXCLUDE_ARCHETYPES)

    # Query ALL matches for this archetype (no date filter in SQL — we filter in Python
    # because dates use mixed formats DD/MM/YY and YYYY-MM-DD)
    q = f"""
        SELECT event_date, result, player1_arch, player2_arch
        FROM matches
        WHERE lower(format) = lower(?)
          AND (player1_arch = ? OR player2_arch = ?)
          AND player1_arch NOT IN ({excl_ph})
          AND player2_arch NOT IN ({excl_ph})
          AND result IS NOT NULL
    """
    params = [format_name, archetype, archetype] + excl_list + excl_list

    try:
        with get_connection() as conn:
            rows = conn.execute(q, params).fetchall()

            total_q = f"""
                SELECT event_date, COUNT(*) as n
                FROM matches
                WHERE lower(format) = lower(?)
                  AND player1_arch NOT IN ({excl_ph})
                  AND player2_arch NOT IN ({excl_ph})
                  AND result IS NOT NULL
                GROUP BY event_date
            """
            total_params = [format_name] + excl_list + excl_list
            total_rows = conn.execute(total_q, total_params).fetchall()
    except Exception:
        return []

    if not rows:
        return []

    # Buckets
    is_daily = granularity == "daily"
    if is_daily:
        num_buckets = min(max(1, (window_end - window_start).days + 1), 90)
        bucket_delta = timedelta(days=1)
    else:
        span_weeks = max(1, int((window_end - window_start).days / 7) + 1)
        num_buckets = min(span_weeks, weeks if weeks is not None else span_weeks)
        bucket_delta = timedelta(weeks=1)

    weekly = []
    for w in range(num_buckets):
        bucket_end   = window_end - bucket_delta * w
        bucket_start = window_end - bucket_delta * (w + 1)

        wins = losses = draws = appearances = 0
        total_in_bucket = 0

        for r in rows:
            d = _parse_match_date(r["event_date"])
            if d is None or not (bucket_start <= d < bucket_end):
                continue
            appearances += 1
            is_p1 = r["player1_arch"] == archetype
            if r["result"] == "draw":
                draws += 1
            elif (r["result"] == "player1" and is_p1) or (r["result"] == "player2" and not is_p1):
                wins += 1
            else:
                losses += 1

        for r in total_rows:
            d = _parse_match_date(r["event_date"])
            if d is not None and bucket_start <= d < bucket_end:
                total_in_bucket += r["n"]

        if appearances == 0 and total_in_bucket == 0:
            continue

        decisive = wins + losses
        wr = wins / decisive if decisive else None
        meta_share = (appearances / total_in_bucket) if total_in_bucket else 0

        weekly.append({
            "week_start":            bucket_start.strftime("%Y-%m-%d"),
            "week_end":              bucket_end.strftime("%Y-%m-%d"),
            "appearances":           appearances,
            "total_decks_in_format": total_in_bucket,
            "meta_share":            round(meta_share, 4),
            "top8_rate":             None,
            "avg_points":            None,
            "event_wins":            0,
            "est_winpct":            round(wr, 4) if wr is not None else None,
        })

    return weekly


def get_archetype_trend(archetype, format_name="standard", weeks=8,
                        event_type=None, include_archive=False,
                        since=None, until=None,
                        dedup_cross_source=True, unique_player_decks=False,
                        granularity="weekly"):
    """
    Time-bucketed performance breakdown for an archetype.
    If since/until are given, buckets the window they define.
    Returns list of stats dicts, most recent first.

    granularity: "weekly" (default, ISO week buckets) or "daily" (calendar day buckets).

    Note: when dedup_cross_source=True, the total_decks_in_format denominator
    uses COUNT(DISTINCT deck_fp + event_fp_cs) to match the numerator's dedup
    logic.  When unique_player_decks=True, the denominator is left as a raw
    per-event count because that filter is a global cross-event dedup that
    cannot be expressed as a per-event GROUP BY; meta_share may be slightly
    underestimated in that case, but the effect is small and trend direction
    is unaffected.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        all_rows = _fetch_appearances(conn, archetype, format_name, event_type, since, until,
                                      dedup_cross_source=dedup_cross_source,
                                      unique_player_decks=unique_player_decks)
    finally:
        conn.close()

    if not all_rows:
        # Fallback: try matches table when decks table has no data for this archetype
        fallback = _archetype_trend_from_matches(
            archetype, format_name, weeks, since, until, granularity)
        return fallback

    conn2 = get_combined_connection(include_archive=include_archive)
    try:
        # When dedup_cross_source is active, count distinct (deck_fp, event_fp_cs)
        # pairs per event so the denominator uses the same dedup logic as the
        # numerator.  NULL fingerprints fall back to d.id (same as the filter:
        # rows with NULL fingerprints pass through and are counted individually).
        # unique_player_decks cannot be expressed as a per-event GROUP BY (it is a
        # global cross-event dedup), so the denominator is left raw in that case.
        if dedup_cross_source:
            count_expr = (
                "COUNT(DISTINCT COALESCE("
                "d.deck_fingerprint || '|' || e.event_fingerprint_cs,"
                "CAST(d.id AS TEXT)"
                ")) as n"
            )
        else:
            count_expr = "COUNT(d.id) as n"

        total_q = f"""
            SELECT e.date, {count_expr}
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
    window_start = since or (window_end - timedelta(weeks=weeks or 520))

    is_daily = granularity == "daily"
    if is_daily:
        span_days   = max(1, (window_end - window_start).days + 1)
        num_buckets = min(span_days, 90)  # cap at 90 daily buckets
        bucket_delta = timedelta(days=1)
    else:
        span_weeks   = max(1, int((window_end - window_start).days / 7) + 1)
        num_buckets  = min(span_weeks, weeks if weeks is not None else span_weeks)
        bucket_delta = timedelta(weeks=1)

    weekly = []
    for w in range(num_buckets):
        bucket_end   = window_end - bucket_delta * w
        bucket_start = window_end - bucket_delta * (w + 1)

        bucket_rows = [
            r for r in all_rows
            if _parse_date(r["date"]) and
               bucket_start <= _parse_date(r["date"]) < bucket_end
        ]
        total_in_bucket = sum(
            r["n"] for r in total_rows
            if _parse_date(r["date"]) and
               bucket_start <= _parse_date(r["date"]) < bucket_end
        )

        if not bucket_rows and total_in_bucket == 0:
            continue

        stats = _aggregate_appearances(bucket_rows) if bucket_rows else None
        weekly.append({
            "week_start":            bucket_start.strftime("%Y-%m-%d"),
            "week_end":              bucket_end.strftime("%Y-%m-%d"),
            "appearances":           len(bucket_rows),
            "total_decks_in_format": total_in_bucket,
            "meta_share":            round(len(bucket_rows) / total_in_bucket, 3) if total_in_bucket else 0,
            "top8_rate":             stats["top8_rate"]       if stats else None,
            "avg_points":            stats["avg_points"]      if stats else None,
            "event_wins":            stats["event_wins"]      if stats else 0,
            "est_winpct":            stats["est_match_winpct"] if stats else None,
        })

    # Fallback: if decks-based trend produced no meaningful data, try matches table
    total_trend_apps = sum(w["appearances"] for w in weekly)
    if total_trend_apps == 0:
        fallback = _archetype_trend_from_matches(
            archetype, format_name, weeks, since, until, granularity)
        if fallback and sum(w["appearances"] for w in fallback) > 0:
            return fallback

    return weekly


def get_head_to_head(archetype_a, archetype_b, format_name="standard",
                     include_archive=False, since=None, until=None,
                     dedup_cross_source=True, unique_player_decks=False):
    """
    Head-to-head: events where both archetypes appeared.
    A "win" = archetype_a's best placement in the event was better than B's.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows_a = _fetch_appearances(conn, archetype_a, format_name, since=since, until=until,
                                    dedup_cross_source=dedup_cross_source,
                                    unique_player_decks=unique_player_decks)
        rows_b = _fetch_appearances(conn, archetype_b, format_name, since=since, until=until,
                                    dedup_cross_source=dedup_cross_source,
                                    unique_player_decks=unique_player_decks)
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
                           min_shared_events=2,
                           dedup_cross_source=True, unique_player_decks=False):
    """
    One archetype vs every other archetype it shared events with.
    Returns list of matchup dicts sorted by win_rate descending.
    """
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows_self = _fetch_appearances(conn, archetype, format_name, since=since, until=until,
                                       dedup_cross_source=dedup_cross_source,
                                       unique_player_decks=unique_player_decks)
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
            opp_rows = _fetch_appearances(conn, opp, format_name, since=since, until=until,
                                          dedup_cross_source=dedup_cross_source,
                                          unique_player_decks=unique_player_decks)
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
                       include_archive=False, since=None, until=None, top=15,
                       dedup_cross_source=True, unique_player_decks=False):
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
        include_archive=include_archive, since=since, until=until, top=top,
        dedup_cross_source=dedup_cross_source, unique_player_decks=unique_player_decks,
    )
    if not standings:
        return {"archetypes": [], "matrix": {}, "note": "No data"}

    archetypes = [s["archetype"] for s in standings]

    conn = get_combined_connection(include_archive=include_archive)
    try:
        all_best = {}
        for arch in archetypes:
            rows = _fetch_appearances(conn, arch, format_name, since=since, until=until,
                                      dedup_cross_source=dedup_cross_source,
                                      unique_player_decks=unique_player_decks)
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
# Real match win rates (from matches table — MTGMelee + bracket inference)
# ---------------------------------------------------------------------------

def get_real_matchup_winrates(format_name: str = "standard",
                               since=None, min_matches: int = 20,
                               min_arch_appearances: int = 10) -> dict:
    """
    Return per-pairing win rates calculated from real recorded match results.

    Sources: MTGMelee round-by-round data + bracket-inferred finals/SF matches.
    Only pairs with at least ``min_matches`` recorded games are included.

    Returns:
        {arch_a: {arch_b: {"win_rate": float, "wins": int, "losses": int,
                            "draws": int, "total": int}}}
    where arch_a < arch_b alphabetically (canonical ordering).
    The caller can look up either direction:
        rate_a_vs_b = result[a][b]["win_rate"]       # a's win rate vs b
        rate_b_vs_a = 1.0 - result[a][b]["win_rate"] # b's win rate vs a
    """
    since_key = since.isoformat() if hasattr(since, "isoformat") else str(since)
    cache_key = f"real_mu_wr:{format_name}:{since_key}:{min_matches}:{min_arch_appearances}"
    return _cached(cache_key, lambda: _get_real_matchup_winrates_impl(
        format_name, since, min_matches, min_arch_appearances))


def _get_real_matchup_winrates_impl(format_name, since, min_matches, min_arch_appearances):
    try:
        from db.matches_queries import _ensure_table
        _ensure_table()
    except Exception:
        return {}

    from db.database import get_connection
    q = """
        SELECT
            CASE WHEN player1_arch < player2_arch
                 THEN player1_arch ELSE player2_arch END  AS arch_a,
            CASE WHEN player1_arch < player2_arch
                 THEN player2_arch ELSE player1_arch END  AS arch_b,
            SUM(CASE
                WHEN player1_arch < player2_arch AND result = 'player1' THEN 1
                WHEN player1_arch >= player2_arch AND result = 'player2' THEN 1
                ELSE 0 END)                               AS wins_a,
            SUM(CASE
                WHEN player1_arch < player2_arch AND result = 'player2' THEN 1
                WHEN player1_arch >= player2_arch AND result = 'player1' THEN 1
                ELSE 0 END)                               AS wins_b,
            SUM(CASE WHEN result = 'draw' THEN 1 ELSE 0 END) AS draws,
            COUNT(*)                                      AS total
        FROM matches
        WHERE lower(format) = lower(?)
          AND player1_arch != ''
          AND player2_arch != ''
          AND player1_arch NOT IN ({excl_ph})
          AND player2_arch NOT IN ({excl_ph})
          AND result IS NOT NULL
    """.format(excl_ph=",".join("?" * len(EXCLUDE_ARCHETYPES)))
    params = [format_name] + list(EXCLUDE_ARCHETYPES) + list(EXCLUDE_ARCHETYPES)
    if since:
        q += " AND event_date >= ?"
        params.append(since.strftime("%Y-%m-%d") if hasattr(since, "strftime") else str(since))
    q += " GROUP BY arch_a, arch_b HAVING total >= ?"
    params.append(min_matches)

    result = {}
    try:
        with get_connection() as conn:
            # Pre-compute which archetypes have enough total appearances
            excl_params = list(EXCLUDE_ARCHETYPES)
            freq_q = f"""
                SELECT arch, SUM(n) AS total FROM (
                    SELECT player1_arch AS arch, COUNT(*) AS n
                    FROM matches WHERE lower(format)=lower(?) AND player1_arch != ''
                      AND player1_arch NOT IN ({",".join("?" * len(EXCLUDE_ARCHETYPES))})
                    GROUP BY player1_arch
                    UNION ALL
                    SELECT player2_arch, COUNT(*)
                    FROM matches WHERE lower(format)=lower(?) AND player2_arch != ''
                      AND player2_arch NOT IN ({",".join("?" * len(EXCLUDE_ARCHETYPES))})
                    GROUP BY player2_arch
                ) GROUP BY arch HAVING total >= ?
            """
            freq_rows = conn.execute(
                freq_q, [format_name] + excl_params + [format_name] + excl_params + [min_arch_appearances]
            ).fetchall()
            valid_archs = {r["arch"] for r in freq_rows}

            rows = conn.execute(q, params).fetchall()
        for r in rows:
            a, b     = r["arch_a"], r["arch_b"]
            if a not in valid_archs or b not in valid_archs:
                continue
            wins_a   = r["wins_a"] or 0
            wins_b   = r["wins_b"] or 0
            draws    = r["draws"]  or 0
            total    = r["total"]
            decisive = wins_a + wins_b
            wr_a     = wins_a / decisive if decisive else 0.5
            result.setdefault(a, {})[b] = {
                "win_rate": round(wr_a, 4),
                "wins":     wins_a,
                "losses":   wins_b,
                "draws":    draws,
                "total":    total,
            }
    except Exception:
        pass
    return result


def get_real_archetype_winrates(format_name: str = "standard",
                                 since=None, min_matches: int = 20) -> dict:
    """
    Return per-archetype win rates from real recorded match results.

    Returns:
        {archetype: {"win_rate": float, "wins": int, "losses": int,
                      "draws": int, "total": int, "source": "real"}}
    Only archetypes with at least ``min_matches`` total games are included.
    """
    since_key = since.isoformat() if hasattr(since, "isoformat") else str(since)
    cache_key = f"real_arch_wr:{format_name}:{since_key}:{min_matches}"
    return _cached(cache_key, lambda: _get_real_archetype_winrates_impl(
        format_name, since, min_matches))


def _get_real_archetype_winrates_impl(format_name, since, min_matches):
    try:
        from db.matches_queries import _ensure_table
        _ensure_table()
    except Exception:
        return {}

    from db.database import get_connection
    excl = ",".join("?" * len(EXCLUDE_ARCHETYPES))
    excl_list = list(EXCLUDE_ARCHETYPES)

    since_clause = ""
    params_base  = [format_name]
    if since:
        since_str    = since.strftime("%Y-%m-%d") if hasattr(since, "strftime") else str(since)
        since_clause = " AND event_date >= ?"
        params_base.append(since_str)

    q = f"""
        SELECT archetype,
               SUM(wins)    AS total_wins,
               SUM(losses)  AS total_losses,
               SUM(draws)   AS total_draws,
               SUM(matches) AS total_matches
        FROM (
            SELECT player1_arch AS archetype,
                   SUM(CASE WHEN result='player1' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN result='player2' THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN result='draw'    THEN 1 ELSE 0 END) AS draws,
                   COUNT(*)                                           AS matches
            FROM matches
            WHERE lower(format)=lower(?){since_clause}
              AND player1_arch != '' AND player1_arch NOT IN ({excl})
              AND result IS NOT NULL
            GROUP BY player1_arch
            UNION ALL
            SELECT player2_arch,
                   SUM(CASE WHEN result='player2' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN result='player1' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN result='draw'    THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM matches
            WHERE lower(format)=lower(?){since_clause}
              AND player2_arch != '' AND player2_arch NOT IN ({excl})
              AND result IS NOT NULL
            GROUP BY player2_arch
        )
        GROUP BY archetype
        HAVING total_matches >= ?
        ORDER BY (CAST(total_wins AS REAL) / NULLIF(total_wins+total_losses, 0)) DESC
    """
    # params: two copies of [format, (since?), excl...] for the two subqueries + min_matches
    params = (params_base + excl_list) + (params_base + excl_list) + [min_matches]

    result = {}
    try:
        with get_connection() as conn:
            rows = conn.execute(q, params).fetchall()
        for r in rows:
            w = r["total_wins"]  or 0
            l = r["total_losses"] or 0
            d = r["total_draws"] or 0
            n = r["total_matches"] or 0
            wr = w / (w + l) if (w + l) else 0.5
            result[r["archetype"]] = {
                "win_rate": round(wr, 4),
                "wins":     w,
                "losses":   l,
                "draws":    d,
                "total":    n,
                "source":   "real",
            }
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Field Optimizer (extracted to analysis/field_optimizer.py, re-exported here)
# ---------------------------------------------------------------------------
from analysis.field_optimizer import parse_field_string, optimize_field_composition  # noqa: F401, E402


