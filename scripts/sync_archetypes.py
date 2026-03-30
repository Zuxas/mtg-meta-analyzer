"""
Archetype sync — runs every 2 weeks to identify unclassified archetypes.

Queries the matches table for archetype names with 20+ appearances that
have no matching definition in config/archetypes/. Outputs a report CSV
and summary to stdout for logging.

Usage:
    python scripts/sync_archetypes.py
    python scripts/sync_archetypes.py --format modern
"""
import sys, os, io, csv, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_connection
from analysis.archetype_classifier import load_archetype_configs
from analysis.win_rates import EXCLUDE_ARCHETYPES


def sync(format_name=None):
    conn = get_connection()
    formats = [format_name] if format_name else ["standard", "modern", "pioneer", "legacy", "pauper"]

    all_rows = []
    for fmt in formats:
        # Get archetype names with 20+ matches
        rows = conn.execute("""
            SELECT player1_arch, COUNT(*) as n FROM matches
            WHERE format=? AND player1_arch NOT IN ('', 'Unclassified')
            AND player1_arch NOT IN ({excl})
            GROUP BY player1_arch HAVING n >= 20
            ORDER BY n DESC
        """.format(excl=",".join("?" * len(EXCLUDE_ARCHETYPES))),
            [fmt] + list(EXCLUDE_ARCHETYPES)).fetchall()

        # Load config definitions
        configs = load_archetype_configs(fmt)
        defined_names = {c["name"].lower() for c in configs}

        classified = 0
        unclassified = 0
        for r in rows:
            name = r[0]
            count = r[1]
            is_defined = name.lower() in defined_names
            if is_defined:
                classified += 1
            else:
                unclassified += 1
                all_rows.append({"archetype_name": name, "match_count": count, "format": fmt})

        print(f"{fmt:10s}: {classified:>4} classified, {unclassified:>4} unclassified (20+ matches)")

    # Write report CSV
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "unclassified_archetypes.csv")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["archetype_name", "match_count", "format"])
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nReport: {len(all_rows)} unclassified archetypes → {report_path}")

    conn.close()
    return all_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default=None)
    args = ap.parse_args()
    sync(args.format)
