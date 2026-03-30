"""
generate_site_data.py
Queries the MTG Meta Analyzer DB and writes 3 JSON files to the website's
data/ directory. Run this before any RC event or after major meta shifts.

Usage:
    cd "E:\\vscode ai project\\mtg-meta-analyzer"
    python scripts/generate_site_data.py

Output:
    E:/vscode ai project/My-Website/data/modern-meta.json
    E:/vscode ai project/My-Website/data/modern-matchups.json
    E:/vscode ai project/My-Website/data/modern-guides.json
"""

import sqlite3, json, os, sys
from datetime import datetime, timezone

DB_PATH     = r"E:\vscode ai project\mtg-meta-analyzer\data\mtg_meta.db"
SITE_DATA   = r"E:\vscode ai project\My-Website\data"

# The 6 decks we have playbooks for — map DB names to playbook accent colors
OUR_DECKS = {
    "Boros Energy":      "#c0392b",
    "Izzet Prowess":     "#e05a3a",
    "Jeskai Blink":      "#d45a2a",
    "Grixis Reanimator": "#3a3ab0",
    "Azorius Control":   "#5b7fd4",
}
# Also track these for meta context even without a playbook
META_CONTEXT_DECKS = [
    "Izzet Affinity", "Ruby Storm", "Eldrazi Tron", "Amulet Titan",
    "Simic Neoform", "Domain Aggro", "Living End", "Dimir Midrange",
    "Tameshi Belcher", "Esper Reanimator", "Esper Blink",
    "Golgari Yawgmoth", "Eldrazi Ramp",
]

FORMAT = "modern"
MIN_MATCHES = 20   # minimum matches for a WR to be shown
META_TOP_N  = 20   # archetypes to include in meta.json

def verdict(wr):
    if wr >= 60: return "Heavily Favored"
    if wr >= 55: return "Favored"
    if wr >= 52: return "Slight Edge"
    if wr >= 48: return "Even"
    if wr >= 45: return "Slight Dog"
    if wr >= 40: return "Unfavored"
    return "Heavily Unfavored"

def verdict_class(wr):
    if wr >= 55: return "v-good"
    if wr >= 48: return "v-even"
    return "v-hard"

def generate_meta(conn):
    """Meta share by archetype from tournament decklists."""
    cur = conn.cursor()
    cur.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM events WHERE format=?", (FORMAT,))
    min_date, max_date, n_events = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM decks d JOIN events e ON d.event_id=e.id WHERE e.format=?", (FORMAT,))
    total_decks = cur.fetchone()[0]

    cur.execute("""
        SELECT d.archetype, COUNT(*) as cnt
        FROM decks d JOIN events e ON d.event_id=e.id
        WHERE e.format=?
        GROUP BY d.archetype ORDER BY cnt DESC LIMIT ?
    """, (FORMAT, META_TOP_N))
    rows = cur.fetchall()

    archetypes = []
    for rank, (name, cnt) in enumerate(rows, 1):
        share = round(cnt / total_decks * 100, 1) if total_decks else 0
        archetypes.append({
            "rank":      rank,
            "name":      name,
            "decks":     cnt,
            "share":     share,
            "has_playbook": name in OUR_DECKS,
            "color":     OUR_DECKS.get(name, "#65bcd5"),
        })

    return {
        "generated":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "format":       FORMAT,
        "event_range":  {"min": min_date, "max": max_date},
        "total_events": n_events,
        "total_decks":  total_decks,
        "archetypes":   archetypes,
    }


def generate_matchups(conn):
    """Real match win rates for our 5 decks vs the field."""
    cur = conn.cursor()
    decks_data = {}

    for deck in OUR_DECKS:
        cur.execute("""
            SELECT archetype_b, ROUND(winrate * 100, 1), matches
            FROM matchup_matrix
            WHERE format=? AND archetype_a=? AND matches >= ?
            ORDER BY matches DESC
        """, (FORMAT, deck, MIN_MATCHES))
        rows = cur.fetchall()

        matchups = []
        for opp, wr, n in rows:
            matchups.append({
                "vs":      opp,
                "wr":      wr,
                "matches": n,
                "verdict": verdict(wr),
                "cls":     verdict_class(wr),
            })

        # Also check the reverse direction (archetype_b = our deck)
        cur.execute("""
            SELECT archetype_a, ROUND((1 - winrate) * 100, 1), matches
            FROM matchup_matrix
            WHERE format=? AND archetype_b=? AND matches >= ?
              AND archetype_a NOT IN (
                  SELECT archetype_b FROM matchup_matrix
                  WHERE format=? AND archetype_a=? AND matches >= ?
              )
            ORDER BY matches DESC
        """, (FORMAT, deck, MIN_MATCHES, FORMAT, deck, MIN_MATCHES))
        for opp, wr, n in cur.fetchall():
            matchups.append({
                "vs":      opp,
                "wr":      wr,
                "matches": n,
                "verdict": verdict(wr),
                "cls":     verdict_class(wr),
            })

        matchups.sort(key=lambda x: x["matches"], reverse=True)
        decks_data[deck] = matchups

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "format":    FORMAT,
        "min_matches": MIN_MATCHES,
        "decks":     decks_data,
    }

def generate_guides(conn):
    """Guide links per deck from the Skill Issue sheet."""
    cur = conn.cursor()
    cur.execute("""
        SELECT archetype, type, author, url, date, comment
        FROM guides WHERE format=? ORDER BY date DESC
    """, (FORMAT,))
    rows = cur.fetchall()

    by_deck = {}
    for name, gtype, author, url, date, comment in rows:
        if name not in by_deck:
            by_deck[name] = []
        by_deck[name].append({
            "type":    gtype,
            "author":  author,
            "url":     url,
            "date":    date,
            "comment": comment or "",
        })

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "format":    FORMAT,
        "guides":    by_deck,
    }


def main():
    os.makedirs(SITE_DATA, exist_ok=True)
    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)

    print("Generating modern-meta.json...")
    meta = generate_meta(conn)
    path = os.path.join(SITE_DATA, "modern-meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"  -> {len(meta['archetypes'])} archetypes, {meta['total_decks']:,} decks "
          f"({meta['total_events']} events)")

    print("Generating modern-matchups.json...")
    matchups = generate_matchups(conn)
    path = os.path.join(SITE_DATA, "modern-matchups.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matchups, f, indent=2, ensure_ascii=False)
    for deck, rows in matchups["decks"].items():
        print(f"  {deck}: {len(rows)} matchups (min {MIN_MATCHES} matches each)")

    print("Generating modern-guides.json...")
    guides = generate_guides(conn)
    path = os.path.join(SITE_DATA, "modern-guides.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(guides, f, indent=2, ensure_ascii=False)
    total_guides = sum(len(v) for v in guides["guides"].values())
    print(f"  -> {total_guides} guides across {len(guides['guides'])} archetypes")

    conn.close()
    print(f"\nDone. Files written to {SITE_DATA}")
    print("Run this script again after any major meta shift or scrape update.")


if __name__ == "__main__":
    main()
