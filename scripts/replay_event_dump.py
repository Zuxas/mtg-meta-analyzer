"""CLI: pretty-print the events[] stream for a cached match.

Usage:
    python scripts/replay_event_dump.py <arena_match_id>
    python scripts/replay_event_dump.py --cache-dir /path/to/cache <arena_match_id>

Validates the M1 extractor without any GUI dependency. Reads the
already-cached JSON; does NOT rebuild from Player.log (use the GUI's
'Refresh from log' for that).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump cached replay events[] for a match.",
    )
    parser.add_argument("arena_match_id",
                        help="Arena match ID (cache filename without .json)")
    parser.add_argument("--cache-dir", default=None,
                        help="Override cache dir (default: data/match_replays)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Show at most N events")
    args = parser.parse_args(argv)

    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
    else:
        cache_dir = (Path(__file__).resolve().parent.parent
                     / "data" / "match_replays")

    cache_file = cache_dir / f"{args.arena_match_id}.json"
    if not cache_file.exists():
        print(f"ERROR: cache file not found: {cache_file}", file=sys.stderr)
        return 2

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: failed to read cache: {e}", file=sys.stderr)
        return 3

    caps = data.get("capabilities") or {}
    if not caps.get("events"):
        print(f"ERROR: cache does not have events[] populated. "
              f"Open the match in the GUI to trigger rebuild, "
              f"or delete the file and let the watcher re-create it.",
              file=sys.stderr)
        return 4

    events = data.get("events") or []
    meta = data.get("match_meta") or {}

    print(f"# Match {data.get('arena_match_id')}")
    print(f"# Event: {meta.get('event_name', '?')}")
    print(f"# Opp: {data.get('opp_name', '?')} "
          f"(my_seat={data.get('my_seat')}, opp_seat={data.get('opp_seat')})")
    print(f"# Winner seat: {meta.get('winner_seat')} "
          f"reason: {meta.get('winner_reason')}")
    print(f"# Total events: {len(events)}")
    print()
    print(f"{'#':>5}  {'G':>2}  {'T':>3}  {'phase':<18} {'step':<22} "
          f"{'pri':>3}  {'kind':<22} card / details")
    print("-" * 110)

    shown = events if args.limit is None else events[: args.limit]
    for ev in shown:
        phase = (ev.get("phase") or "")[:18]
        step = (ev.get("step") or "")[:22]
        nm = ev.get("card_name") or ""
        details = ev.get("details") or {}
        detail_str = ""
        if details:
            detail_str = " " + ", ".join(
                f"{k}={v!r}" for k, v in details.items() if k != "raw"
            )
        print(f"{ev.get('seq'):>5}  {ev.get('game_num'):>2}  "
              f"{ev.get('turn_num'):>3}  {phase:<18} {step:<22} "
              f"{str(ev.get('priority_seat')):>3}  "
              f"{ev.get('kind'):<22} {nm}{detail_str}")

    if args.limit is not None and len(events) > args.limit:
        print(f"\n... {len(events) - args.limit} more events truncated")

    return 0


if __name__ == "__main__":
    sys.exit(main())
