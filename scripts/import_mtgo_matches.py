"""Import local MTGO matches into match_log.  DRY-RUN unless --commit.

  python -m scripts.import_mtgo_matches                      # live MTGO install
  python -m scripts.import_mtgo_matches --raw data/raw/mtgo/2026-09-27
  python -m scripts.import_mtgo_matches --commit --db <path> # write (idempotent)

Merges three MTGO sources per match:
  mtgo_game_history  result, game W/L, format, event, round  (authoritative)
  Match_GameLog .dat per-game winner, play/draw, mulligans, turns, cards seen
  mtgo.log           exact 75 for games in the current session
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.helpers import utc_now  # noqa: E402
from scrapers import mtgo_log_parser as p  # noqa: E402

SOURCE = "mtgo_log"


# ---------------------------------------------------------------- loading

def load_sources(raw: Path | None):
    if raw:
        dats = sorted(raw.glob("Match_GameLog_*.dat"))
        hist_files = sorted(raw.glob("*mtgo_game_history"))
        logs = sorted(raw.glob("mtgo*.log"))
    else:
        src = p.discover_sources()
        dats = p.unique_gamelogs(src["appfiles"])
        hist_files = [d / "mtgo_game_history" for d in src["appfiles"]
                      if (d / "mtgo_game_history").exists()]
        logs = src["logs"]
    history: dict[int, dict] = {}
    for f in hist_files:
        for h in p.read_game_history(f):
            history.setdefault(h["id"], h)
    texts = [p.parse_text_log(f) for f in logs]
    return dats, list(history.values()), texts


def _names(ids: dict[int, int], space: dict[int, str], inline: dict[int, str]) -> dict[str, int]:
    out: Counter = Counter()
    for cid, n in ids.items():
        name = space.get(cid) or inline.get(cid)
        if name and not p.is_token_name(name):
            out[name] += n
    return dict(out)


# ---------------------------------------------------------------- merge

def build_records(dats, history, texts, names, local: str | None = None):
    logs = [p.read_gamelog(f) for f in dats]
    local = local or next((t["username"] for t in texts if t["username"]), None) \
        or p.guess_local_player(logs)
    decks_by_game: dict[int, dict] = {}
    formats_by_token: dict[str, str] = {}
    for t in texts:
        decks_by_game.update(t["decks"])
        formats_by_token.update(t["match_formats"])

    stats = Counter()
    records, used_hist = [], set()
    for log in logs:
        if not log.entries:
            stats["empty_log"] += 1
            continue
        m = p.parse_match(log, local)
        if m["spectated"]:
            stats["spectated"] += 1
            continue
        h = p.link_history(m, history)
        if h:
            used_hist.add(h["id"])
        records.append(_record(m, h, local, names, decks_by_game, formats_by_token, stats))
    for h in history:
        if h["id"] not in used_hist and (h["winners"] or h["losers"]):
            records.append(_record(None, h, local, names, decks_by_game, formats_by_token, stats))
    return records, stats, local


def _record(m, h, local, names, decks_by_game, formats_by_token, stats):
    inline = m["card_names"] if m else {}
    dat_result = m["result"] if m else None
    hist_result = p.history_result(h, local) if h else None
    if h and hist_result != "incomplete":
        result, result_src = hist_result, "history"
        if dat_result in ("win", "loss") and dat_result != hist_result:
            stats["result_conflict"] += 1
    else:
        result, result_src = dat_result or "incomplete", "gamelog"
    stats[f"result_from_{result_src}"] += 1

    games = m["games"] if m else []
    opp = (m["opponent"] if m else None) or (h["opponents"][0] if h and h["opponents"] else "")
    fmt = (h["format"] if h and h["format"] != "unknown" else None) \
        or formats_by_token.get(m["token"] if m else "", None) or "unknown"

    my_seen: Counter = Counter()
    opp_seen: Counter = Counter()
    for g in games:
        my_seen.update(g["cards"].get(local, {}))
        opp_seen.update(g["cards"].get(opp, {}))
    exact = next((decks_by_game[g] for g in (h["game_ids"] if h else []) if g in decks_by_game), None)
    my_cards = (_names(exact["main"], names["catalog"], {}) if exact
                else _names(dict(my_seen), names["texture"], inline))
    opp_cards = _names(dict(opp_seen), names["texture"], inline)

    g_results = []
    for g in games[:3]:
        g_results.append("" if not g["winner"] else "win" if g["winner"] == local else "loss")
    first = games[0] if games else None
    play_draw = "" if not first or not first["on_play"] else \
        "play" if first["on_play"] == local else "draw"
    started = (h["start"] if h and h["start"] else m["started_at"] if m else None)
    return {
        "mtgo_match_id": (m["token"] if m else f"h:{h['id']}"),
        "history_id": h["id"] if h else None,
        "event_name": (h["event"] if h and h["event"] else "MTGO"),
        "event_date": started.date().isoformat() if started else "",
        "started": started,
        "format": fmt,
        "round": h["round"] if h else 0,
        "opp_name": opp,
        "result": result,
        "result_src": result_src,
        "play_draw": play_draw,
        "g": (g_results + ["", "", ""])[:3],
        "game_wins": h["game_wins"] if h else None,
        "game_losses": h["game_losses"] if h else None,
        "my_cards": my_cards,
        "my_deck_exact": exact is not None,
        "opp_cards": opp_cards,
        "per_game": {i + 1: {"n_turns": g["turns"] or None,
                             "my_mull_to": g["hand_size"].get(local),
                             "opp_mull_to": g["hand_size"].get(opp)}
                     for i, g in enumerate(games)},
        "linked": bool(m and h),
    }


def classify(records, con):
    from analysis.observed_deck_classifier import ProfileCache
    cache = ProfileCache(con)
    for r in records:
        for side in ("my", "opp"):
            got = None
            if r["started"] and r[f"{side}_cards"]:
                got = cache.classify(set(r[f"{side}_cards"]), r["format"], r["started"].date())
            r[f"{side}_deck"] = got[0] if got else ""
            r[f"{side}_conf"] = got[1] if got else 0.0


# ---------------------------------------------------------------- report

def report(records, stats, local, n_dats, names) -> dict:
    decided = [r for r in records if r["result"] in ("win", "loss")]
    seen_tex = {c for r in records for c in r["opp_cards"]}
    gates = {
        "G3 local player": local,
        "matches (not spectated)": len(records),
        "decided": len(decided),
        "incomplete (skipped)": len(records) - len(decided),
        "spectated (skipped)": stats["spectated"],
        "empty logs": stats["empty_log"],
        "linked .dat<->history": sum(r["linked"] for r in records),
        "history-only": sum(1 for r in records if r["mtgo_match_id"].startswith("h:")),
        "result conflicts .dat vs history": stats["result_conflict"],
        "format unknown": sum(1 for r in decided if r["format"] == "unknown"),
        "opp archetype named": sum(1 for r in decided if r.get("opp_deck")),
        "my archetype named": sum(1 for r in decided if r.get("my_deck")),
        "exact 75 known": sum(r["my_deck_exact"] for r in decided),
        "distinct opp cards named": len(seen_tex),
    }
    print("\n== MTGO import dry-run ==")
    for k, v in gates.items():
        print(f"  {k:36s} {v}")
    w = sum(r["result"] == "win" for r in decided)
    print(f"\n  record {w}-{len(decided) - w}"
          f"  ({100 * w / max(1, len(decided)):.1f}%)")
    print("  by format:", dict(Counter(r["format"] for r in decided).most_common()))
    print("  by year:  ", dict(sorted(Counter(r["event_date"][:4] for r in decided).items())))
    top = Counter(r["opp_deck"] for r in decided if r.get("opp_deck")).most_common(10)
    print("  top opp archetypes:", top)
    mine = Counter(r["my_deck"] for r in decided if r.get("my_deck")).most_common(8)
    print("  my archetypes:", mine)
    return gates


# ---------------------------------------------------------------- write

def ensure_schema(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(match_log)")}
    if "mtgo_match_id" not in cols:
        con.execute("ALTER TABLE match_log ADD COLUMN mtgo_match_id TEXT")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_match_log_mtgo_id "
                "ON match_log(mtgo_match_id) WHERE mtgo_match_id IS NOT NULL")


def write_records(con, records) -> int:
    ensure_schema(con)
    have = {r[0] for r in con.execute(
        "SELECT mtgo_match_id FROM match_log WHERE mtgo_match_id IS NOT NULL")}
    inserted = 0
    for r in records:
        if r["result"] not in ("win", "loss") or r["mtgo_match_id"] in have:
            continue
        notes = "MTGO import"
        mulls = [f"G{n}: {s['my_mull_to']}" for n, s in r["per_game"].items()
                 if s["my_mull_to"] and s["my_mull_to"] < 7]
        if mulls:
            notes += "; mull to " + ", ".join(mulls)
        if r["my_deck"] and not r["my_deck_exact"]:
            notes += f"; my deck inferred from {len(r['my_cards'])} cards seen"
        if r["opp_deck"]:
            notes += (f"; opp deck inferred from {len(r['opp_cards'])} cards seen"
                      f" (confidence {r['opp_conf']:.2f})")
        cur = con.execute(
            """INSERT INTO match_log
               (event_name, event_date, format, round, my_deck, opp_deck, opp_name,
                result, play_draw, g1_result, g2_result, g3_result, notes, created_at,
                source, backfill_status, mtgo_match_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["event_name"], r["event_date"], r["format"], r["round"], r["my_deck"],
             r["opp_deck"], r["opp_name"], r["result"], r["play_draw"], *r["g"], notes,
             utc_now(), SOURCE, "live" if r["my_deck"] else "orphan", r["mtgo_match_id"]))
        mid = cur.lastrowid
        for n, s in r["per_game"].items():
            con.execute(
                """INSERT OR IGNORE INTO match_log_games
                   (match_log_id, game_num, n_turns, my_mull_to, opp_mull_to)
                   VALUES (?,?,?,?,?)""", (mid, n, s["n_turns"], s["my_mull_to"], s["opp_mull_to"]))
        have.add(r["mtgo_match_id"])
        inserted += 1
    return inserted


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, help="snapshot dir instead of the live MTGO install")
    ap.add_argument("--local", help="your MTGO username (default: from mtgo.log)")
    ap.add_argument("--commit", action="store_true", help="write to --db (default: dry-run)")
    ap.add_argument("--db", type=Path, help="database path (default: the configured DB)")
    a = ap.parse_args(argv)

    from db.database import DB_PATH
    db_path = a.db or Path(DB_PATH)
    dats, history, texts = load_sources(a.raw)
    card_dir = p.discover_sources()["card_data"]
    names = p.load_card_names(card_dir) if card_dir else {"catalog": {}, "texture": {}}
    records, stats, local = build_records(dats, history, texts, names, a.local)

    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    classify(records, ro)
    ro.close()
    report(records, stats, local, len(dats), names)

    if not a.commit:
        print(f"\nDRY-RUN: nothing written. Target DB would be {db_path}")
        return 0
    con = sqlite3.connect(db_path)
    try:
        with con:
            n = write_records(con, records)
    finally:
        con.close()
    print(f"\nCOMMITTED: {n} new match_log rows -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
