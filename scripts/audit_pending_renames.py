"""Audit what `python -m analysis.archetypes --apply` would rename -- READ-ONLY.

For every stored `decks.archetype` label L with normalize(L) != L (a pending
rename L -> N), per format, all time:
  * cosine of L's mainboard card profile vs the profile of decks already
    labelled N (or any other label normalizing to N);
  * for small or low-scoring rows, where each of L's decks sits among N's OWN
    decks (each vs N's centroid): below N's 5th percentile = OUTLIER, i.e. the
    alias probably merges a different deck.
Also lists 'formatting-only' renames (no ALIASES key involved), which is where
title-casing makes names worse ('WW Heroics' -> 'Ww Heroics').

Opens the live DB read-only (mode=ro). Writes a Markdown report.

Usage:
    python -m scripts.audit_pending_renames --out docs/audits/pending-renames.md
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date

from analysis.archetypes import ALIASES, normalize, pre_normalize

SUSPECT_BELOW = 0.90   # set-level cosine below this -> per-deck check


def _cos(a: dict, b: dict) -> float:
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def pending_renames(con) -> list[dict]:
    alias_keys = {k.lower() for k in ALIASES}
    sizes: dict = defaultdict(int)
    cards: dict = defaultdict(lambda: defaultdict(int))
    for fmt, label, n in con.execute(
            """SELECT e.format, d.archetype, COUNT(*) FROM decks d JOIN events e ON e.id = d.event_id
               WHERE d.archetype IS NOT NULL AND d.archetype != ''
               GROUP BY e.format, d.archetype"""):
        sizes[(fmt, label)] = n
    for fmt, label, card, n in con.execute(
            """SELECT e.format, d.archetype, lower(c.name), COUNT(DISTINCT d.id)
               FROM decks d JOIN events e ON e.id = d.event_id
               JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
               JOIN cards c ON c.id = dc.card_id
               WHERE d.archetype IS NOT NULL AND d.archetype != ''
               GROUP BY e.format, d.archetype, lower(c.name)"""):
        cards[(fmt, label)][card] += n
    norm = {label: normalize(label) for (_f, label) in sizes}
    out = []
    for (fmt, label), n in sizes.items():
        tgt = norm[label]
        if tgt == label:
            continue
        is_alias = (pre_normalize(label) or "").lower() in alias_keys
        peers = [p for p in sizes if p[0] == fmt and p[1] != label and norm[p[1]] == tgt]
        n_t = sum(sizes[p] for p in peers)
        c = None
        if n_t >= 3:
            a = {k: v / n for k, v in cards[(fmt, label)].items()}
            tb: dict = defaultdict(int)
            for p in peers:
                for k, v in cards[p].items():
                    tb[k] += v
            c = round(_cos(a, {k: v / n_t for k, v in tb.items()}), 3)
        out.append({"format": fmt, "label": label, "target": tgt, "n": n, "n_tgt": n_t,
                    "cos": c, "kind": "alias" if is_alias else "formatting",
                    "peers": [p[1] for p in peers]})
    return out


def per_deck_check(con, row: dict) -> dict:
    def decks(labels):
        q = ",".join("?" * len(labels))
        per: dict = defaultdict(set)
        for did, card in con.execute(
                f"""SELECT d.id, lower(c.name) FROM decks d JOIN events e ON e.id = d.event_id
                    JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
                    JOIN cards c ON c.id = dc.card_id
                    WHERE e.format = ? AND d.archetype IN ({q})""", (row["format"], *labels)):
            per[did].add(card)
        return per
    tgt, src = decks(row["peers"]), decks([row["label"]])
    cent: dict = defaultdict(float)
    for cs in tgt.values():
        for c in cs:
            cent[c] += 1 / len(tgt)
    own = sorted(_cos({c: 1 for c in cs}, cent) for cs in tgt.values())
    p5 = own[max(0, int(0.05 * len(own)) - 1)]
    scores = sorted((round(_cos({c: 1 for c in cs}, cent), 2) for cs in src.values()), reverse=True)
    below = sum(1 for s in scores if s < p5)
    return {"src": scores, "p5": round(p5, 2), "median": round(own[len(own) // 2], 2),
            "below": below,
            "verdict": "OUTLIER" if below == len(scores) else ("MIXED" if below else "fits")}


def report(rows: list[dict], checks: dict) -> str:
    labels = {r["label"] for r in rows}
    decks = sum(r["n"] for r in rows)
    ok = [r for r in rows if r["cos"] is not None and r["cos"] >= SUSPECT_BELOW]
    L = [f"# Pending archetype renames -- audit {date.today().isoformat()}", "",
         "What `python -m analysis.archetypes --apply` would change in `decks.archetype` "
         f"(read-only audit, `scripts/audit_pending_renames.py`): **{len(labels)} labels, "
         f"{decks:,} decks** ({len(rows)} format/label rows).", "",
         f"- {len(ok)} rows look like the same deck (set cosine >= {SUSPECT_BELOW}).",
         f"- {sum(1 for c in checks.values() if c['verdict'] != 'fits')} rows need a decision (below).",
         f"- {sum(1 for r in rows if r['cos'] is None)} rows have no same-format target decks to compare "
         "(pure renames; listed last).", "",
         "## Needs a decision", "",
         "Per-deck check: each source deck vs the target's own decks. OUTLIER = every source deck is "
         "below the target's 5th percentile; MIXED = some are.", "",
         "| Verdict | Format | Label -> target | Decks | Set cos | Source decks | Target p5 / median | Kind |",
         "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (checks.get(id(r), {}).get("verdict", "z"), r["format"])):
        c = checks.get(id(r))
        if not c or c["verdict"] == "fits":
            continue
        L.append(f"| **{c['verdict']}** | {r['format']} | {r['label']} -> {r['target']} | {r['n']} | "
                 f"{r['cos']} | {', '.join(map(str, c['src'][:6]))} | {c['p5']} / {c['median']} | {r['kind']} |")
    L += ["", "## Checked, fits the target (set cosine < 0.90 but each deck within the target's range)", "",
          "| Format | Label -> target | Decks | Set cos | Kind |", "|---|---|---|---|---|"]
    for r in rows:
        c = checks.get(id(r))
        if c and c["verdict"] == "fits":
            L.append(f"| {r['format']} | {r['label']} -> {r['target']} | {r['n']} | {r['cos']} | {r['kind']} |")
    L += ["", "## Formatting-only renames (no alias involved)", "",
          "Title-casing can make a name worse or leave it split from its real group "
          "(e.g. 'Mono U Fae' never joins 'Mono Blue Faeries').", "",
          "| Format | Label -> result | Decks |", "|---|---|---|"]
    for r in sorted((r for r in rows if r["kind"] == "formatting"), key=lambda r: -r["n"]):
        L.append(f"| {r['format']} | {r['label']} -> {r['target']} | {r['n']} |")
    L += ["", "## No same-format target decks (cannot be compared)", "",
          "| Format | Label -> target | Decks | Kind |", "|---|---|---|---|"]
    for r in sorted((r for r in rows if r["cos"] is None), key=lambda r: -r["n"]):
        L.append(f"| {r['format']} | {r['label']} -> {r['target']} | {r['n']} | {r['kind']} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Audit pending archetype renames (read-only).")
    ap.add_argument("--out", default="docs/audits/pending-renames.md")
    args = ap.parse_args(argv)
    from db import database
    con = sqlite3.connect(f"file:{database.DB_PATH}?mode=ro", uri=True)
    rows = pending_renames(con)
    checks = {id(r): per_deck_check(con, r) for r in rows
              if r["cos"] is not None and r["cos"] < SUSPECT_BELOW}
    text = report(rows, checks)
    import os
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{len({r['label'] for r in rows})} labels / {sum(r['n'] for r in rows)} decks; "
          f"{sum(1 for c in checks.values() if c['verdict'] != 'fits')} need a decision -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
