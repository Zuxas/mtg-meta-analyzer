"""Read-only survey: which in-scope Melee events are team or mixed-format events?

For every event in the relabel scope it fetches the public tournament page once (cached in
E:\\mtg-data\\raw\\melee_relabel\\event_meta\\<tid>.html, resumable), reads the published
"Format:" header and title, and compares them with the formats the stored rows carry. Writes a
report; never writes the database.

  python -m scripts.survey_melee_event_formats            # fetch missing pages, then report
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

META_DIR = Path(r"E:\mtg-data\raw\melee_relabel\event_meta")
OUT_DIR = Path(r"E:\mtg-data\reports\melee_relabel")
CUTOFF_ID = 7812278
TEAM_WORDS = re.compile(r"(?i)\b(team|teams|trios?|duos?|pairs|2hg|two-headed|unified)\b")
FORMAT_RE = re.compile(r"Format:\s*([^|<]+?)\s*\|")
TITLE_RE = re.compile(r"<title>(.*?)\s*\|\s*Melee</title>", re.S)


def parse_page(html: str) -> dict:
    title = (TITLE_RE.search(html).group(1).strip() if TITLE_RE.search(html) else "")
    m = FORMAT_RE.search(html)
    formats = [f.strip().lower() for f in m.group(1).split(",")] if m else []
    return {"title": title, "published_formats": formats,
            "team_signal": bool(TEAM_WORDS.search(title)),
            "team_in_description": "Team Captain" in html or "team captain" in html.lower()}


def main() -> int:
    from db.database import DB_PATH
    from scrapers import mtgmelee_scraper as ms
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=60)
    stored = defaultdict(Counter)
    for eid, fmt, n in con.execute("SELECT event_id, format, COUNT(*) FROM matches WHERE source='mtgmelee' "
                                   "AND id <= ? GROUP BY event_id, format", (CUTOFF_ID,)):
        stored[eid][fmt] = n
    META_DIR.mkdir(parents=True, exist_ok=True)
    session = ms._session()
    todo = [e for e in sorted(stored) if not (META_DIR / f"{e.removeprefix('mtgmelee_')}.html").exists()]
    print(f"{len(stored)} events, {len(todo)} pages to fetch", flush=True)
    for i, eid in enumerate(todo, 1):
        tid = eid.removeprefix("mtgmelee_")
        try:
            r = session.get(ms._VIEW_URL.format(tid=tid), timeout=30)
            r.raise_for_status()
            (META_DIR / f"{tid}.html").write_text(r.text, encoding="utf-8")
        except Exception as exc:                                       # noqa: BLE001
            print(f"  [{i}/{len(todo)}] {eid} FAILED {exc}", flush=True)
        time.sleep(ms._SLEEP)
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}]", flush=True)

    rows = []
    for eid, fmts in sorted(stored.items()):
        path = META_DIR / f"{eid.removeprefix('mtgmelee_')}.html"
        page = parse_page(path.read_text(encoding="utf-8")) if path.exists() else None
        stored_f = sorted(fmts)
        flags = []
        if page is None:
            flags.append("page-missing")
        else:
            pub = [f for f in page["published_formats"] if f]
            if len(pub) > 1:
                flags.append("multi-format")
            if page["team_signal"] or page["team_in_description"]:
                flags.append("team")
            if pub and not set(stored_f) <= set(pub):
                flags.append("stored-format-not-published")
        if len(stored_f) > 1:
            flags.append("rows-in-several-formats")
        rows.append({"event_id": eid, "title": page["title"] if page else "",
                     "published_formats": page["published_formats"] if page else [],
                     "stored_formats": dict(fmts), "rows": sum(fmts.values()), "flags": flags})
    flagged = [r for r in rows if r["flags"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"event-format-survey-{datetime.now():%Y%m%d-%H%M%S}"
    stem.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# Melee event format / team survey (read-only)", "",
         f"{len(rows)} in-scope events; {len(flagged)} flagged. Nothing was modified.", "",
         "Flag counts: " + ", ".join(f"{k} {v}" for k, v in
                                      Counter(f for r in flagged for f in r["flags"]).most_common()), "",
         "| event | title | published | stored rows by format | flags |", "|---|---|---|---|---|"]
    for r in sorted(flagged, key=lambda r: -r["rows"]):
        L.append(f"| {r['event_id']} | {r['title']} | {', '.join(r['published_formats'])} | "
                 f"{', '.join(f'{k} {v}' for k, v in r['stored_formats'].items())} | {', '.join(r['flags'])} |")
    stem.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{len(flagged)} flagged; report {stem.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
