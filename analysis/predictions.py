"""
Self-Validation & Prediction Logging System.

Tracks the tool's own meta predictions and validates them against subsequent
tournament results. Over time, this tells you which signals (MTGO, paper,
week-over-week trend) are most reliable for near-term calls.

Usage:
    python -m analysis.predictions generate --format standard
    python -m analysis.predictions validate
    python -m analysis.predictions report

Or from query.py:
    python -m analysis.query predict --format standard
    python -m analysis.query validate-predictions
    python -m analysis.query prediction-report
"""

import json
from datetime import datetime, timedelta
from db.database import get_connection, DB_PATH
import sqlite3
import os


# ---------------------------------------------------------------------------
# Schema — created on first use, separate from main init_db()
# ---------------------------------------------------------------------------

_PREDICTIONS_DDL = """
CREATE TABLE IF NOT EXISTS predictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    format            TEXT NOT NULL,
    archetype         TEXT NOT NULL,
    prediction_type   TEXT NOT NULL,   -- 'top_meta', 'trending_up', 'trending_down', 'rising'
    predicted_rank    INTEGER,         -- predicted position in meta standings
    predicted_share   REAL,            -- predicted meta share fraction
    predicted_dir     TEXT,            -- 'up' / 'down' / 'stable' (for trend predictions)
    signals           TEXT,            -- JSON: {signal_name: signal_value}
    target_week       TEXT NOT NULL,   -- YYYY-MM-DD: first day of the week to validate against
    validated_at      TEXT,
    actual_rank       INTEGER,
    actual_share      REAL,
    correct           INTEGER,         -- 1=correct, 0=wrong, NULL=pending
    notes             TEXT
);
"""


def _ensure_predictions_table():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(_PREDICTIONS_DDL)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _week_start(dt=None):
    """Return the Monday of the given (or current) week as YYYY-MM-DD."""
    d = (dt or datetime.now()).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def _next_week_start(dt=None):
    """Return the Monday of next week."""
    d = (dt or datetime.now()).date()
    monday = d - timedelta(days=d.weekday())
    return (monday + timedelta(weeks=1)).isoformat()


def _get_meta_snapshot(format_name, since=None, until=None):
    """Pull current meta standings for prediction signal generation."""
    from analysis.win_rates import get_meta_standings
    return get_meta_standings(
        format_name=format_name,
        min_appearances=3,
        top=20,
        since=since,
        until=until,
    )


def _get_trend_snapshot(archetype, format_name, weeks=4):
    """Pull recent weekly trend for one archetype."""
    from analysis.win_rates import get_archetype_trend
    return get_archetype_trend(archetype, format_name=format_name, weeks=weeks)


# ---------------------------------------------------------------------------
# Generating predictions
# ---------------------------------------------------------------------------

def generate_predictions(format_name="standard", weeks_back=4, commit=True):
    """
    Auto-generate predictions based on current meta data.

    Prediction types:
      - top_meta:      Top 5 archetypes predicted to remain top meta next week
      - trending_up:   Archetypes with rising meta share over the last N weeks
      - trending_down: Archetypes with falling meta share
      - rising:        Archetypes that jumped >50% in share week-over-week

    Returns list of prediction dicts that were logged.
    """
    _ensure_predictions_table()

    now = datetime.now()
    since = now - timedelta(weeks=weeks_back)
    target = _next_week_start(now)
    created_at = now.isoformat()

    standings = _get_meta_snapshot(format_name, since=since)
    if not standings:
        print(f"  No meta data for {format_name}. Cannot generate predictions.")
        return []

    predictions = []

    # --- top_meta: top 5 by avg_points ---
    top5 = standings[:5]
    for rank, s in enumerate(top5, 1):
        arch = s["archetype"]
        trend_data = _get_trend_snapshot(arch, format_name, weeks=weeks_back)

        # Compute week-over-week direction
        direction = "stable"
        if len(trend_data) >= 2:
            recent = trend_data[0]["meta_share"]
            prev   = trend_data[1]["meta_share"]
            if recent > prev * 1.1:
                direction = "up"
            elif recent < prev * 0.9:
                direction = "down"

        signals = {
            "appearances":      s["appearances"],
            "avg_points":       round(s.get("avg_points") or 0, 3),
            "est_winpct":       round(s.get("est_match_winpct") or 0, 3),
            "top8_rate":        round(s.get("top8_rate") or 0, 3),
            "meta_share_trend": direction,
            "weeks_analyzed":   weeks_back,
        }

        predictions.append({
            "format":           format_name,
            "archetype":        arch,
            "prediction_type":  "top_meta",
            "predicted_rank":   rank,
            "predicted_share":  round(s.get("meta_share", 0), 4) if "meta_share" in s else None,
            "predicted_dir":    direction,
            "signals":          signals,
            "target_week":      target,
            "created_at":       created_at,
        })

    # --- trending_up / trending_down: look at all archetypes in standings ---
    for s in standings[5:15]:
        arch = s["archetype"]
        trend_data = _get_trend_snapshot(arch, format_name, weeks=weeks_back)
        if len(trend_data) < 2:
            continue

        shares = [w["meta_share"] for w in trend_data]
        # Simple linear trend: last vs average of prior weeks
        recent = shares[0]
        prior_avg = sum(shares[1:]) / len(shares[1:]) if len(shares) > 1 else recent

        if recent > prior_avg * 1.25:
            ptype = "trending_up"
            pred_dir = "up"
        elif recent < prior_avg * 0.75:
            ptype = "trending_down"
            pred_dir = "down"
        else:
            continue  # stable — not interesting to log

        signals = {
            "recent_share":   round(recent, 4),
            "prior_avg_share": round(prior_avg, 4),
            "change_pct":     round((recent - prior_avg) / max(prior_avg, 0.001) * 100, 1),
            "appearances":    s["appearances"],
        }

        predictions.append({
            "format":           format_name,
            "archetype":        arch,
            "prediction_type":  ptype,
            "predicted_rank":   None,
            "predicted_share":  round(recent * 1.2 if pred_dir == "up" else recent * 0.8, 4),
            "predicted_dir":    pred_dir,
            "signals":          signals,
            "target_week":      target,
            "created_at":       created_at,
        })

    if commit:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(_PREDICTIONS_DDL)
            for p in predictions:
                conn.execute("""
                    INSERT INTO predictions
                    (created_at, format, archetype, prediction_type, predicted_rank,
                     predicted_share, predicted_dir, signals, target_week)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    p["created_at"], p["format"], p["archetype"],
                    p["prediction_type"], p["predicted_rank"], p["predicted_share"],
                    p["predicted_dir"], json.dumps(p["signals"]), p["target_week"],
                ))
            conn.commit()
        finally:
            conn.close()
        print(f"  Logged {len(predictions)} predictions for week of {target}.")

    return predictions


# ---------------------------------------------------------------------------
# Validating predictions
# ---------------------------------------------------------------------------

def validate_predictions(format_name=None):
    """
    Validate all pending predictions whose target_week has passed.

    A prediction is 'correct' if:
      - top_meta:      actual_rank <= predicted_rank + 2  (within 2 spots)
      - trending_up:   actual_share > prior share (meta share increased)
      - trending_down: actual_share < prior share (meta share decreased)
      - rising:        archetype still appears in top 15

    Updates predictions.correct, actual_rank, actual_share, validated_at.
    Returns summary dict.
    """
    _ensure_predictions_table()

    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        where = "WHERE correct IS NULL AND target_week <= ?"
        params = [today]
        from analysis.win_rates import is_all_formats
        if not is_all_formats(format_name):
            where += " AND format = ?"
            params.append(format_name)

        pending = conn.execute(
            f"SELECT * FROM predictions {where}", params
        ).fetchall()

        if not pending:
            return {"validated": 0, "correct": 0, "wrong": 0}

        validated = correct = wrong = 0

        # Group by (format, target_week) to fetch standings once per group
        groups = {}
        for p in pending:
            key = (p["format"], p["target_week"])
            groups.setdefault(key, []).append(p)

        from analysis.win_rates import get_meta_standings, get_archetype_trend
        from datetime import datetime as dt

        for (fmt, target_week), preds in groups.items():
            # Fetch actual standings for the target week
            week_start = dt.strptime(target_week, "%Y-%m-%d")
            week_end   = week_start + timedelta(days=7)
            standings  = get_meta_standings(
                format_name=fmt, min_appearances=1, top=30,
                since=week_start, until=week_end,
            )
            rank_map  = {s["archetype"]: i+1 for i, s in enumerate(standings)}
            share_map = {s["archetype"]: s.get("meta_share", 0) for s in standings}

            for p in preds:
                arch         = p["archetype"]
                ptype        = p["prediction_type"]
                actual_rank  = rank_map.get(arch)
                actual_share = share_map.get(arch, 0)

                is_correct = None
                if ptype == "top_meta":
                    if actual_rank is not None:
                        is_correct = int(actual_rank <= (p["predicted_rank"] or 5) + 2)
                    else:
                        is_correct = 0  # didn't appear in top 30 = wrong

                elif ptype == "trending_up":
                    signals = json.loads(p["signals"] or "{}")
                    prior = signals.get("recent_share", 0)
                    is_correct = int(actual_share > prior * 1.05)

                elif ptype == "trending_down":
                    signals = json.loads(p["signals"] or "{}")
                    prior = signals.get("recent_share", 0)
                    is_correct = int(actual_share < prior * 0.95)

                elif ptype == "rising":
                    is_correct = int(actual_rank is not None and actual_rank <= 15)

                conn.execute("""
                    UPDATE predictions
                    SET actual_rank=?, actual_share=?, correct=?, validated_at=?
                    WHERE id=?
                """, (actual_rank, actual_share, is_correct, today, p["id"]))

                validated += 1
                if is_correct == 1:
                    correct += 1
                elif is_correct == 0:
                    wrong += 1

        conn.commit()
        return {"validated": validated, "correct": correct, "wrong": wrong}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Accuracy report
# ---------------------------------------------------------------------------

def accuracy_report(format_name=None, limit=90):
    """
    Return accuracy stats over the last N days.

    Returns dict with per-prediction-type accuracy and overall accuracy.
    """
    _ensure_predictions_table()

    cutoff = (datetime.now() - timedelta(days=limit)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        where = "WHERE correct IS NOT NULL AND created_at >= ?"
        params = [cutoff]
        from analysis.win_rates import is_all_formats
        if not is_all_formats(format_name):
            where += " AND format = ?"
            params.append(format_name)

        rows = conn.execute(
            f"SELECT prediction_type, correct, COUNT(*) as cnt "
            f"FROM predictions {where} "
            f"GROUP BY prediction_type, correct",
            params
        ).fetchall()
    finally:
        conn.close()

    # Aggregate
    stats = {}
    for r in rows:
        pt = r["prediction_type"]
        if pt not in stats:
            stats[pt] = {"correct": 0, "wrong": 0}
        if r["correct"] == 1:
            stats[pt]["correct"] += r["cnt"]
        else:
            stats[pt]["wrong"] += r["cnt"]

    result = {}
    total_correct = total_total = 0
    for pt, s in stats.items():
        total = s["correct"] + s["wrong"]
        acc   = s["correct"] / total if total else None
        result[pt] = {
            "correct": s["correct"],
            "total":   total,
            "accuracy": acc,
        }
        total_correct += s["correct"]
        total_total   += total

    result["_overall"] = {
        "correct":  total_correct,
        "total":    total_total,
        "accuracy": total_correct / total_total if total_total else None,
    }
    return result


def recent_predictions(format_name=None, limit=20, pending_only=False):
    """Return recent prediction rows for display."""
    _ensure_predictions_table()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        where_parts = []
        params = []
        from analysis.win_rates import is_all_formats
        if not is_all_formats(format_name):
            where_parts.append("format = ?")
            params.append(format_name)
        if pending_only:
            where_parts.append("correct IS NULL")

        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        params.append(limit)

        rows = conn.execute(
            f"SELECT * FROM predictions {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            params
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MTG Meta prediction logger")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate", help="Generate and log predictions from current meta")
    p_gen.add_argument("--format", default="standard")
    p_gen.add_argument("--weeks-back", type=int, default=4,
                       help="Weeks of data to base predictions on (default 4)")
    p_gen.add_argument("--dry-run", action="store_true",
                       help="Show predictions without logging them")

    p_val = sub.add_parser("validate", help="Validate pending predictions")
    p_val.add_argument("--format", default=None)

    p_rep = sub.add_parser("report", help="Accuracy report")
    p_rep.add_argument("--format", default=None)
    p_rep.add_argument("--days", type=int, default=90)

    args = parser.parse_args()

    if args.cmd == "generate":
        preds = generate_predictions(
            format_name=args.format,
            weeks_back=args.weeks_back,
            commit=not args.dry_run,
        )
        if args.dry_run:
            print(f"\n  {len(preds)} predictions (dry run — not logged):\n")
            for p in preds:
                sig = p["signals"]
                rank_str = f"  rank {p['predicted_rank']}" if p["predicted_rank"] else ""
                print(f"  [{p['prediction_type']:<14}]{rank_str:>8}  "
                      f"{p['archetype']:<30}  -> {p['predicted_dir']}  "
                      f"(target: {p['target_week']})")

    elif args.cmd == "validate":
        result = validate_predictions(format_name=args.format)
        print(f"\n  Validated: {result['validated']}  "
              f"Correct: {result['correct']}  "
              f"Wrong: {result['wrong']}\n")

    elif args.cmd == "report":
        report = accuracy_report(format_name=args.format, limit=args.days)
        overall = report.pop("_overall")
        print(f"\n  Prediction Accuracy Report (last {args.days} days)\n")
        print(f"  {'Type':<20} {'Correct':>7} {'Total':>6} {'Accuracy':>9}")
        print(f"  {'-'*20} {'-'*7} {'-'*6} {'-'*9}")
        for pt, s in sorted(report.items()):
            acc_str = f"{s['accuracy']*100:.0f}%" if s["accuracy"] is not None else "N/A"
            print(f"  {pt:<20} {s['correct']:>7} {s['total']:>6} {acc_str:>9}")
        print(f"  {'-'*20} {'-'*7} {'-'*6} {'-'*9}")
        acc_str = f"{overall['accuracy']*100:.0f}%" if overall["accuracy"] is not None else "N/A"
        print(f"  {'OVERALL':<20} {overall['correct']:>7} {overall['total']:>6} {acc_str:>9}")
        print()
