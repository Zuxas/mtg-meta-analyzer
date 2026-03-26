"""
core/data_engine/duplicate_analysis.py

Read-only analysis of event and deck duplicates using stored fingerprints.

All functions accept a sqlite3 connection and return plain dicts/lists —
no printing, no side effects, safe to call from GUI or CLI.

Duplicate classification
------------------------
Events:
  cross_source        — same fingerprint, different source values (real target)
  same_source_same_day — same source, same date (fingerprint too aggressive —
                         e.g. "LCQ #1"…"LCQ #22" on the same day all share a fp
                         because trailing numbers are stripped)
  same_source_multi_day — same source, different dates (rarer; worth reviewing)

Decks:
  cross_source        — same 75, different scraper sources (real target)
  same_player_multi_event — same player, same 75, different events
  multi_player_same_build — different players, same 75 (popular archetype copies)
"""

from collections import defaultdict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_event_group(sources: list, dates: list) -> str:
    if len(set(sources)) > 1:
        return "cross_source"
    if len(set(dates)) == 1:
        return "same_source_same_day"
    return "same_source_multi_day"


def _classify_deck_group(sources: list, players: list) -> str:
    if len(set(sources)) > 1:
        return "cross_source"
    clean_players = [p for p in players if p]
    if clean_players and len(set(clean_players)) == 1:
        return "same_player_multi_event"
    return "multi_player_same_build"


def _source_counts(items: list) -> dict:
    counts = defaultdict(int)
    for v in items:
        counts[v] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Event duplicates
# ---------------------------------------------------------------------------

def get_duplicate_events(conn, min_count=2):
    """
    Return all event fingerprint groups where count >= min_count.

    Each group dict:
      fingerprint       str
      count             int
      duplicate_type    'cross_source' | 'same_source_same_day' | 'same_source_multi_day'
      sources           list[str]       — distinct source values
      source_counts     dict[str, int]  — events per source
      names             list[str]       — raw event names (all members)
      dates             list[str]       — distinct dates in group
      formats           list[str]       — distinct formats in group
      members           list[dict]      — one dict per row: id, source, source_id,
                                          name, date, format

    Sorted by count descending (largest clusters first).
    """
    rows = conn.execute(
        """
        SELECT e.event_fingerprint, e.id, e.source, e.source_id,
               e.name, e.date, e.format
        FROM events e
        INNER JOIN (
            SELECT event_fingerprint
            FROM events
            WHERE event_fingerprint IS NOT NULL
            GROUP BY event_fingerprint
            HAVING COUNT(*) >= ?
        ) dup USING (event_fingerprint)
        ORDER BY e.event_fingerprint, e.id
        """,
        (min_count,),
    ).fetchall()

    buckets = defaultdict(list)
    for r in rows:
        buckets[r["event_fingerprint"]].append(dict(r))

    groups = []
    for fp, members in buckets.items():
        sources = [m["source"] for m in members]
        dates   = [m["date"]   for m in members]
        groups.append({
            "fingerprint":    fp,
            "count":          len(members),
            "duplicate_type": _classify_event_group(sources, dates),
            "sources":        sorted(set(sources)),
            "source_counts":  _source_counts(sources),
            "names":          [m["name"] for m in members],
            "dates":          sorted(set(dates)),
            "formats":        sorted(set(m["format"] or "" for m in members)),
            "members":        members,
        })

    return sorted(groups, key=lambda x: -x["count"])


# ---------------------------------------------------------------------------
# Deck duplicates
# ---------------------------------------------------------------------------

def get_duplicate_decks(conn, min_count=2, cross_source_only=False):
    """
    Return all deck fingerprint groups where count >= min_count.

    Each group dict:
      fingerprint       str
      count             int
      duplicate_type    'cross_source' | 'same_player_multi_event' |
                        'multi_player_same_build'
      sources           list[str]       — distinct event sources
      source_counts     dict[str, int]
      players           list[str]       — distinct player names
      archetypes        list[str]       — distinct archetype names
      formats           list[str]       — distinct formats
      events            list[str]       — event names (one per member)
      members           list[dict]      — one dict per row: deck_id, player,
                                          archetype, event_name, event_source,
                                          event_date, format

    cross_source_only: if True, return only groups spanning multiple sources.
    Sorted by count descending.
    """
    rows = conn.execute(
        """
        SELECT d.deck_fingerprint,
               d.id    AS deck_id,
               d.player,
               d.archetype,
               e.name  AS event_name,
               e.source AS event_source,
               e.date   AS event_date,
               e.format
        FROM decks d
        JOIN events e ON e.id = d.event_id
        INNER JOIN (
            SELECT deck_fingerprint
            FROM decks
            WHERE deck_fingerprint IS NOT NULL
            GROUP BY deck_fingerprint
            HAVING COUNT(*) >= ?
        ) dup USING (deck_fingerprint)
        ORDER BY d.deck_fingerprint, d.id
        """,
        (min_count,),
    ).fetchall()

    buckets = defaultdict(list)
    for r in rows:
        buckets[r["deck_fingerprint"]].append(dict(r))

    groups = []
    for fp, members in buckets.items():
        sources = [m["event_source"] for m in members]
        players = [m["player"]       for m in members]
        dup_type = _classify_deck_group(sources, players)

        if cross_source_only and dup_type != "cross_source":
            continue

        groups.append({
            "fingerprint":    fp,
            "count":          len(members),
            "duplicate_type": dup_type,
            "sources":        sorted(set(sources)),
            "source_counts":  _source_counts(sources),
            "players":        sorted(set(p for p in players if p)),
            "archetypes":     sorted(set(m["archetype"] or "" for m in members)),
            "formats":        sorted(set(m["format"]    or "" for m in members)),
            "events":         [m["event_name"] for m in members],
            "members":        members,
        })

    return sorted(groups, key=lambda x: -x["count"])


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def get_duplicate_summary(conn):
    """
    Return aggregated duplicate statistics for both events and decks.

    Return value:
    {
      "events": {
        "total": int,
        "in_dup_groups": int,
        "dup_groups": int,
        "pct_duplicated": float,
        "by_type": {"cross_source": int, "same_source_same_day": int,
                    "same_source_multi_day": int},
        "by_source": {"mtgtop8": {"total": int, "in_dups": int}, ...},
      },
      "decks": {
        "total": int,
        "in_dup_groups": int,
        "dup_groups": int,
        "pct_duplicated": float,
        "by_type": {"cross_source": int, "same_player_multi_event": int,
                    "multi_player_same_build": int},
        "by_format": {"standard": {"total": int, "in_dups": int}, ...},
        "by_source": {"mtgtop8": {"total": int, "in_dups": int}, ...},
        "cross_source_groups": int,
        "cross_source_decks": int,
      },
      "fingerprint_health": {
        "event_false_positive_rate": float,  — same_source_same_day / total groups
        "note": str,
      }
    }
    """
    # ---- Events ----
    ev_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    ev_groups = conn.execute(
        """
        SELECT event_fingerprint, COUNT(*) AS cnt,
               COUNT(DISTINCT source) AS src_cnt,
               COUNT(DISTINCT date)   AS date_cnt
        FROM events
        WHERE event_fingerprint IS NOT NULL
        GROUP BY event_fingerprint
        HAVING cnt > 1
        """
    ).fetchall()

    ev_type_counts = {"cross_source": 0, "same_source_same_day": 0,
                      "same_source_multi_day": 0}
    ev_in_dups = 0
    for r in ev_groups:
        ev_in_dups += r["cnt"]
        t = _classify_event_group(
            ["x"] * r["src_cnt"],      # proxy: distinct count
            ["d"] * r["date_cnt"],
        )
        # Re-derive properly
        if r["src_cnt"] > 1:
            ev_type_counts["cross_source"] += 1
        elif r["date_cnt"] == 1:
            ev_type_counts["same_source_same_day"] += 1
        else:
            ev_type_counts["same_source_multi_day"] += 1

    # Per-source event breakdown
    ev_by_source = {}
    src_rows = conn.execute(
        "SELECT source, COUNT(*) AS total FROM events GROUP BY source"
    ).fetchall()
    for r in src_rows:
        ev_by_source[r["source"]] = {"total": r["total"], "in_dups": 0}

    dup_fp_set_ev = {r["event_fingerprint"] for r in ev_groups}
    src_dup_rows = conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM events "
        "WHERE event_fingerprint IS NOT NULL GROUP BY source"
    ).fetchall()
    # Count per source how many are in a dup group
    for r in conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM events "
        "WHERE event_fingerprint IN (SELECT event_fingerprint FROM events "
        "  WHERE event_fingerprint IS NOT NULL "
        "  GROUP BY event_fingerprint HAVING COUNT(*) > 1) "
        "GROUP BY source"
    ).fetchall():
        if r["source"] in ev_by_source:
            ev_by_source[r["source"]]["in_dups"] = r["cnt"]

    # ---- Decks ----
    dk_total = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]

    dk_groups = conn.execute(
        """
        SELECT d.deck_fingerprint, COUNT(*) AS cnt,
               COUNT(DISTINCT e.source) AS src_cnt,
               COUNT(DISTINCT d.player) AS player_cnt
        FROM decks d JOIN events e ON e.id = d.event_id
        WHERE d.deck_fingerprint IS NOT NULL
        GROUP BY d.deck_fingerprint
        HAVING cnt > 1
        """
    ).fetchall()

    dk_type_counts = {"cross_source": 0, "same_player_multi_event": 0,
                      "multi_player_same_build": 0}
    dk_in_dups = 0
    cross_src_decks = 0
    for r in dk_groups:
        dk_in_dups += r["cnt"]
        if r["src_cnt"] > 1:
            dk_type_counts["cross_source"] += 1
            cross_src_decks += r["cnt"]
        elif r["player_cnt"] == 1:
            dk_type_counts["same_player_multi_event"] += 1
        else:
            dk_type_counts["multi_player_same_build"] += 1

    # Per-format deck breakdown
    dk_by_format = {}
    for r in conn.execute(
        "SELECT e.format, COUNT(*) AS total FROM decks d "
        "JOIN events e ON e.id = d.event_id GROUP BY e.format"
    ).fetchall():
        dk_by_format[r["format"] or "unknown"] = {"total": r["total"], "in_dups": 0}

    for r in conn.execute(
        """
        SELECT e.format, COUNT(*) AS cnt
        FROM decks d JOIN events e ON e.id = d.event_id
        WHERE d.deck_fingerprint IN (
            SELECT deck_fingerprint FROM decks
            WHERE deck_fingerprint IS NOT NULL
            GROUP BY deck_fingerprint HAVING COUNT(*) > 1
        )
        GROUP BY e.format
        """
    ).fetchall():
        key = r["format"] or "unknown"
        if key in dk_by_format:
            dk_by_format[key]["in_dups"] = r["cnt"]

    # Per-source deck breakdown
    dk_by_source = {}
    for r in conn.execute(
        "SELECT e.source, COUNT(*) AS total FROM decks d "
        "JOIN events e ON e.id = d.event_id GROUP BY e.source"
    ).fetchall():
        dk_by_source[r["source"]] = {"total": r["total"], "in_dups": 0}

    for r in conn.execute(
        """
        SELECT e.source, COUNT(*) AS cnt
        FROM decks d JOIN events e ON e.id = d.event_id
        WHERE d.deck_fingerprint IN (
            SELECT deck_fingerprint FROM decks
            WHERE deck_fingerprint IS NOT NULL
            GROUP BY deck_fingerprint HAVING COUNT(*) > 1
        )
        GROUP BY e.source
        """
    ).fetchall():
        if r["source"] in dk_by_source:
            dk_by_source[r["source"]]["in_dups"] = r["cnt"]

    # ---- Fingerprint health note ----
    total_ev_groups = len(ev_groups)
    fp_rate = (
        ev_type_counts["same_source_same_day"] / total_ev_groups
        if total_ev_groups else 0.0
    )
    health_note = (
        f"{ev_type_counts['same_source_same_day']}/{total_ev_groups} event dup groups "
        f"are same-source same-day. These are events with identical names published by "
        f"mtgtop8 for multiple independent venues on the same day (e.g. 'RCQ' x10 on "
        f"one weekend). Fingerprinting cannot distinguish them without store/location data. "
        f"Numbered events (e.g. 'LCQ #1'–'LCQ #22') no longer collide — fixed in Phase 1 "
        f"by preserving trailing numbers in event_fingerprint."
    ) if total_ev_groups else "No event duplicates found."

    return {
        "events": {
            "total":           ev_total,
            "in_dup_groups":   ev_in_dups,
            "dup_groups":      total_ev_groups,
            "pct_duplicated":  round(ev_in_dups * 100 / ev_total, 1) if ev_total else 0.0,
            "by_type":         ev_type_counts,
            "by_source":       ev_by_source,
        },
        "decks": {
            "total":                dk_total,
            "in_dup_groups":        dk_in_dups,
            "dup_groups":           len(dk_groups),
            "pct_duplicated":       round(dk_in_dups * 100 / dk_total, 1) if dk_total else 0.0,
            "by_type":              dk_type_counts,
            "by_format":            dk_by_format,
            "by_source":            dk_by_source,
            "cross_source_groups":  dk_type_counts["cross_source"],
            "cross_source_decks":   cross_src_decks,
        },
        "fingerprint_health": {
            "event_false_positive_rate": round(fp_rate, 3),
            "note": health_note,
        },
    }
