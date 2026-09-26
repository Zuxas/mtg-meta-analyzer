"""analysis/sb_matrix.py -- sideboard-matrix interchange for saved_sb_plans.

The canonical sideboard model is ``saved_sb_plans`` (db/saved_decks.py):
per (deck, opponent) JSON lists of REPEATED card names for play_in /
play_out / draw_in / draw_out. This module does not add a second model. It
is an import/export boundary around that one:

    matrix JSON --parse_matrix--> Matrix
                --resolve_against_deck--> Matrix with names spelled as in the 75,
                                          plus every error found
                --to_plan_rows--> rows shaped for db.saved_decks.save_sb_plans_atomic
    saved rows  --plans_to_matrix--> matrix dict (tolerant of dirty legacy rows)
                --render_html--> standalone red/green matrix page

Everything here is pure: no DB and no network. The CLI is
scripts/import_sb_matrix.py.

Matrix schema ("sb-matrix/1")::

    {
      "schema": "sb-matrix/1",
      "source": "free text: where the plan came from",
      "deck":   {"name": "...", "format": "modern", "archetype": "Izzet Prowess"},
      "matchups": {
        "Eldrazi Tron": {
          "out":  {"Expressive Iteration": 3, "Lightning Bolt": 3, "Lava Dart": 1},
          "in":   {"Consign to Memory": 4, "Unholy Heat": 2, "Spell Pierce": 1},
          "note": "Consign Trinisphere.",
          "difficulty": "Hard",                      # optional: Easy|Medium|Hard
          "play": {"out": {...}, "in": {...}},       # optional full override
          "draw": {"out": {...}, "in": {...}}        # optional full override
        }
      }
    }

"out"/"in" are the default for BOTH play and draw. A "play" or "draw" block
replaces the default for that side entirely (it is not merged into it).

Spec: harness/specs/2026-09-26-session-assets-intake.md
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA = "sb-matrix/1"
DIFFICULTIES = ("Easy", "Medium", "Hard")
PROVENANCE_TAG = "[sb-matrix]"
_PROV_RE = re.compile(r"\[sb-matrix\]\s+fp=([0-9a-f]{12})\b")


class MatrixError(ValueError):
    """Raised with EVERY problem found, one per line, never just the first."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


# ---------------------------------------------------------------------------
# Card names
# ---------------------------------------------------------------------------

def name_key(name: str) -> str:
    """Comparison key for a card name.

    NFKC folding, curly apostrophes/quotes straightened, dashes unified,
    whitespace collapsed, casefolded. Used only to MATCH names. The spelling
    written back is always the deck's own.
    """
    s = unicodedata.normalize("NFKC", str(name))
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    s = re.sub(r"\s*//\s*", " // ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


def _name_index(names) -> dict[str, str]:
    """key -> deck spelling. Double-faced / split cards are reachable by the
    full 'A // B' name AND by the front face 'A' (how most lists write them).
    If two cards share a key, the full name wins over a face alias."""
    idx: dict[str, str] = {}
    faces: dict[str, str] = {}
    for n in names:
        idx[name_key(n)] = n
        if "//" in n:
            front = n.split("//")[0]
            faces.setdefault(name_key(front), n)
    for k, v in faces.items():
        idx.setdefault(k, v)
    return idx


def resolve_name(name: str, pool) -> str | None:
    """Return the pool's spelling of ``name`` or None if it is not in the pool."""
    idx = _name_index(pool)
    hit = idx.get(name_key(name))
    if hit is None and "//" in name:
        hit = idx.get(name_key(name.split("//")[0]))
    return hit


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class SidePlan:
    out: Counter = field(default_factory=Counter)
    inn: Counter = field(default_factory=Counter)

    def total_out(self) -> int:
        return sum(self.out.values())

    def total_in(self) -> int:
        return sum(self.inn.values())


@dataclass
class MatchupPlan:
    opponent: str
    play: SidePlan
    draw: SidePlan
    note: str = ""
    difficulty: str = "Medium"


@dataclass
class Matrix:
    matchups: list[MatchupPlan]
    source: str = ""
    deck: dict = field(default_factory=dict)


def _parse_counts(obj, where: str, problems: list[str]) -> Counter:
    c: Counter = Counter()
    if obj is None:
        return c
    if not isinstance(obj, dict):
        problems.append(f"{where}: expected an object of card -> count, got {type(obj).__name__}")
        return c
    for card, n in obj.items():
        if not isinstance(card, str) or not card.strip():
            problems.append(f"{where}: empty card name")
            continue
        if isinstance(n, bool) or not isinstance(n, int):
            problems.append(f"{where}: count for {card!r} must be an integer, got {n!r}")
            continue
        if n < 0:
            problems.append(f"{where}: negative count for {card!r}")
            continue
        if n == 0:
            continue            # explicit zero = not boarded; dropped silently
        c[card.strip()] += n
    return c


def _parse_side(block, where: str, problems: list[str]) -> SidePlan:
    if not isinstance(block, dict):
        problems.append(f"{where}: expected an object with 'out' and 'in'")
        return SidePlan()
    unknown = set(block) - {"out", "in"}
    if unknown:
        problems.append(f"{where}: unknown keys {sorted(unknown)}")
    return SidePlan(out=_parse_counts(block.get("out"), f"{where}.out", problems),
                    inn=_parse_counts(block.get("in"), f"{where}.in", problems))


def parse_matrix(data: dict) -> Matrix:
    """Structural parse. Raises MatrixError listing every problem.

    Does not check the plan against a deck; resolve_against_deck() does that.
    """
    problems: list[str] = []
    if not isinstance(data, dict):
        raise MatrixError(["matrix: top level must be an object"])
    if data.get("schema") != SCHEMA:
        problems.append(f"matrix: schema must be {SCHEMA!r}, got {data.get('schema')!r}")
    mus = data.get("matchups")
    if not isinstance(mus, dict) or not mus:
        problems.append("matrix: 'matchups' must be a non-empty object")
        mus = {}
    out: list[MatchupPlan] = []
    seen: set[str] = set()
    allowed = {"out", "in", "note", "difficulty", "play", "draw"}
    for opp, m in mus.items():
        w = f"matchup {opp!r}"
        if not isinstance(opp, str) or not opp.strip():
            problems.append("matrix: empty matchup name")
            continue
        k = opp.strip().casefold()
        if k in seen:
            problems.append(f"{w}: duplicate matchup name")
            continue
        seen.add(k)
        if not isinstance(m, dict):
            problems.append(f"{w}: expected an object")
            continue
        unknown = set(m) - allowed
        if unknown:
            problems.append(f"{w}: unknown keys {sorted(unknown)}")
        default = SidePlan(out=_parse_counts(m.get("out"), f"{w}.out", problems),
                           inn=_parse_counts(m.get("in"), f"{w}.in", problems))
        play = _parse_side(m["play"], f"{w}.play", problems) if "play" in m else default
        draw = _parse_side(m["draw"], f"{w}.draw", problems) if "draw" in m else default
        diff = m.get("difficulty", "Medium")
        if diff not in DIFFICULTIES:
            problems.append(f"{w}: difficulty must be one of {DIFFICULTIES}, got {diff!r}")
        note = m.get("note", "")
        if not isinstance(note, str):
            problems.append(f"{w}: note must be a string")
            note = str(note)
        out.append(MatchupPlan(opponent=opp.strip(), play=play, draw=draw,
                               note=note.strip(), difficulty=diff))
    if problems:
        raise MatrixError(problems)
    return Matrix(matchups=out, source=str(data.get("source", "")),
                  deck=dict(data.get("deck") or {}))


# ---------------------------------------------------------------------------
# Validation against a real 75
# ---------------------------------------------------------------------------

def _resolve_side(sp: SidePlan, where: str, main: dict, side: dict,
                  main_idx: dict, side_idx: dict, problems: list[str]) -> SidePlan:
    r = SidePlan()
    for card, n in sp.out.items():
        real = main_idx.get(name_key(card)) or (
            main_idx.get(name_key(card.split("//")[0])) if "//" in card else None)
        if real is None:
            hint = " (it is in the SIDEBOARD)" if resolve_name(card, side_idx) else ""
            problems.append(f"{where}: OUT {card!r} is not in the main deck{hint}")
            continue
        r.out[real] += n
    for card, n in sp.inn.items():
        real = side_idx.get(name_key(card)) or (
            side_idx.get(name_key(card.split("//")[0])) if "//" in card else None)
        if real is None:
            hint = " (it is in the MAIN deck)" if resolve_name(card, main_idx) else ""
            problems.append(f"{where}: IN {card!r} is not in the sideboard{hint}")
            continue
        r.inn[real] += n
    for real, n in r.out.items():
        if n > main[real]:
            problems.append(f"{where}: OUT {n} {real} but the main deck has {main[real]}")
    for real, n in r.inn.items():
        if n > side[real]:
            problems.append(f"{where}: IN {n} {real} but the sideboard has {side[real]}")
    both = set(r.out) & set(r.inn)
    for real in sorted(both):
        problems.append(f"{where}: {real} is both boarded out and in")
    if r.total_out() != r.total_in():
        problems.append(f"{where}: {r.total_out()} out vs {r.total_in()} in "
                        f"(main would be {sum(main.values()) - r.total_out() + r.total_in()})")
    return r


def resolve_against_deck(matrix: Matrix, main: dict, side: dict) -> tuple[Matrix, list[str]]:
    """Check every matchup against the 75 and respell names as the deck does.

    OUT cards are bounded by MAIN copies and IN cards by SIDE copies. A card
    may not be both out and in within one side. Outs must equal ins, so the
    post-board main keeps its pre-board size. Returns (resolved, problems).
    The plan may be committed only when problems is empty.
    """
    main = {k: int(v) for k, v in main.items() if int(v) > 0}
    side = {k: int(v) for k, v in side.items() if int(v) > 0}
    main_idx, side_idx = _name_index(main), _name_index(side)
    problems: list[str] = []
    resolved: list[MatchupPlan] = []
    for mp in matrix.matchups:
        play = _resolve_side(mp.play, f"{mp.opponent} [play]", main, side,
                             main_idx, side_idx, problems)
        if mp.draw is mp.play:
            draw = play
        else:
            draw = _resolve_side(mp.draw, f"{mp.opponent} [draw]", main, side,
                                 main_idx, side_idx, problems)
        resolved.append(MatchupPlan(mp.opponent, play, draw, mp.note, mp.difficulty))
    return Matrix(resolved, matrix.source, matrix.deck), problems


# ---------------------------------------------------------------------------
# Fingerprint + provenance
# ---------------------------------------------------------------------------

def deck_fingerprint(main: dict, side: dict) -> str:
    """12-hex digest of the exact 75. Card-name spelling/case does not matter;
    quantities and main/side placement do."""
    parts = [f"M:{int(n)}:{name_key(c)}" for c, n in main.items() if int(n) > 0]
    parts += [f"S:{int(n)}:{name_key(c)}" for c, n in side.items() if int(n) > 0]
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:12]


def provenance_line(fp: str, source: str, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    src = re.sub(r"\s+", " ", source or "").strip() or "unknown"
    return f"{PROVENANCE_TAG} fp={fp} src={src} imported={when.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def plan_fingerprint(notes: str) -> str | None:
    m = _PROV_RE.search(notes or "")
    return m.group(1) if m else None


def plan_is_stale(row: dict, main: dict, side: dict) -> bool | None:
    """True if the row was imported against a different 75 than the deck has
    now. False if it matches. None if the row carries no import provenance,
    for example a plan typed in the GUI."""
    fp = plan_fingerprint(row.get("notes", ""))
    if fp is None:
        return None
    return fp != deck_fingerprint(main, side)


def _strip_provenance(notes: str) -> str:
    return "\n".join(l for l in (notes or "").splitlines()
                     if not l.startswith(PROVENANCE_TAG)).strip()


# ---------------------------------------------------------------------------
# To / from saved_sb_plans rows
# ---------------------------------------------------------------------------

def _expand(c: Counter) -> list[str]:
    """Counter -> the DB's repeated-name list, in a deterministic order."""
    return [name for name in sorted(c, key=name_key) for _ in range(c[name])]


def to_plan_rows(matrix: Matrix, fingerprint: str, source: str | None = None,
                 when: datetime | None = None) -> list[dict]:
    """Rows shaped like save_sb_plan's arguments (lists of repeated names)."""
    prov = provenance_line(fingerprint, source if source is not None else matrix.source, when)
    rows = []
    for mp in matrix.matchups:
        notes = (mp.note + "\n\n" + prov) if mp.note else prov
        rows.append({
            "opponent_archetype": mp.opponent,
            "play_in": _expand(mp.play.inn), "play_out": _expand(mp.play.out),
            "draw_in": _expand(mp.draw.inn), "draw_out": _expand(mp.draw.out),
            "notes": notes, "difficulty": mp.difficulty,
        })
    return rows


def _as_counter(v) -> Counter:
    """Tolerant: accepts a list of names, a JSON string of one, or junk (-> empty)."""
    import json
    if isinstance(v, str):
        try:
            v = json.loads(v or "[]")
        except ValueError:
            return Counter()
    if not isinstance(v, list):
        return Counter()
    return Counter(x for x in v if isinstance(x, str) and x.strip())


def plans_to_matrix(rows: list[dict], source: str = "", deck: dict | None = None) -> dict:
    """saved_sb_plans rows -> matrix dict. Never raises on dirty legacy rows.

    Play is written as the default. A "draw" override is emitted only when
    the draw side differs. The import provenance line is stripped from the note.
    """
    mus: dict = {}
    for r in rows:
        opp = str(r.get("opponent_archetype") or "").strip() or "(unnamed)"
        pi, po = _as_counter(r.get("play_in")), _as_counter(r.get("play_out"))
        di, do = _as_counter(r.get("draw_in")), _as_counter(r.get("draw_out"))
        m = {"out": dict(sorted(po.items())), "in": dict(sorted(pi.items()))}
        if (di, do) != (pi, po):
            m["draw"] = {"out": dict(sorted(do.items())), "in": dict(sorted(di.items()))}
        note = _strip_provenance(str(r.get("notes") or ""))
        if note:
            m["note"] = note
        diff = r.get("difficulty") or "Medium"
        if diff != "Medium":
            m["difficulty"] = diff
        mus[opp] = m
    return {"schema": SCHEMA, "source": source, "deck": dict(deck or {}), "matchups": mus}


def normalized(matrix: Matrix) -> dict:
    """Matrix -> the dict plans_to_matrix() would give back. Used for round-trip equality."""
    return plans_to_matrix(to_plan_rows(matrix, "0" * 12, matrix.source),
                           source=matrix.source, deck=matrix.deck)


# ---------------------------------------------------------------------------
# Diff (for the CLI dry run)
# ---------------------------------------------------------------------------

def diff_rows(existing: list[dict], new: list[dict]) -> list[str]:
    """Deterministic, human-readable diff of plan rows keyed by opponent."""
    ex = {str(r.get("opponent_archetype")): r for r in existing}
    lines = []
    fields = ("play_in", "play_out", "draw_in", "draw_out")
    for r in sorted(new, key=lambda r: r["opponent_archetype"].casefold()):
        opp = r["opponent_archetype"]
        old = ex.pop(opp, None)
        if old is None:
            lines.append(f"+ NEW      {opp}")
            continue
        changes = [f for f in fields if _as_counter(old.get(f)) != _as_counter(r[f])]
        if (old.get("difficulty") or "Medium") != r["difficulty"]:
            changes.append("difficulty")
        if _strip_provenance(old.get("notes", "")) != _strip_provenance(r["notes"]):
            changes.append("notes")
        lines.append(f"~ CHANGED  {opp}: {', '.join(changes)}" if changes
                     else f"= SAME     {opp} (provenance refreshed)")
    for opp in sorted(ex, key=str.casefold):
        lines.append(f"  KEPT     {opp} (not in matrix; left untouched)")
    return lines


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
:root{--bg:#f6f4f2;--fg:#1d1b1a;--muted:#6b6560;--line:#d9d3cd;--head:#ece7e2;
--out:#e8a09a;--outfg:#5a1510;--in:#a9d8b8;--infg:#0f4424;--cell:#fff;--bad:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#171514;--fg:#eee9e4;--muted:#a39b94;
--line:#3a3532;--head:#24201e;--out:#7a2e28;--outfg:#ffd9d4;--in:#1f5a36;--infg:#d6f5e0;
--cell:#1d1a19;--bad:#ff7b6b}}
body{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif;margin:0;padding:20px 16px 40px}
h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 16px;max-width:75ch}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{border:1px solid var(--line);padding:4px 6px;text-align:center;background:var(--cell)}
thead th{background:var(--head)}th.mu{height:150px;vertical-align:bottom;padding:4px 2px;min-width:30px}
th.mu span{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font-size:12px}
.card{text-align:left;white-space:nowrap;position:sticky;left:0;background:var(--head)}
td.q{background:var(--head);font-weight:600}
td.o{background:var(--out);color:var(--outfg);font-weight:700}
td.i{background:var(--in);color:var(--infg);font-weight:700}
td.x,span.x{color:var(--bad);font-weight:700}tr.sep td{background:var(--fg);height:3px;padding:0}
tr.tot td{background:var(--head);font-size:12px;font-weight:600}
.notes{margin-top:20px;max-width:900px}.notes li{margin:3px 0}
"""


def render_html(title: str, main: dict, side: dict, rows: list[dict],
                subtitle: str = "") -> str:
    """Standalone HTML matrix of a deck's saved plans (tolerant of dirty rows).

    Cells show the play-side count. If draw differs, the cell reads
    "play/draw". A count over the copies in the 75, a card missing from the
    75, or an unbalanced column is drawn in the warning colour, not raised.
    """
    e = html.escape
    rows = sorted(rows, key=lambda r: str(r.get("opponent_archetype", "")).casefold())
    opps = [str(r.get("opponent_archetype") or "(unnamed)") for r in rows]
    sides = []
    for r in rows:
        sides.append((_as_counter(r.get("play_out")), _as_counter(r.get("play_in")),
                      _as_counter(r.get("draw_out")), _as_counter(r.get("draw_in"))))
    main_idx, side_idx = _name_index(main), _name_index(side)

    def _real(name, idx):
        return idx.get(name_key(name))

    out_cards: dict[str, int] = {}
    in_cards: dict[str, int] = {}
    for po, pi, do, di in sides:
        for c in list(po) + list(do):
            real = _real(c, main_idx) or c
            out_cards.setdefault(real, main.get(real, 0))
        for c in list(pi) + list(di):
            real = _real(c, side_idx) or c
            in_cards.setdefault(real, side.get(real, 0))
    for c, n in side.items():
        in_cards.setdefault(c, n)

    def _count(counter, real, idx):
        return sum(n for c, n in counter.items() if (_real(c, idx) or c) == real)

    def _row(card, qty, kind):
        cells = [f'<td class="card">{e(card)}</td><td class="q">{qty or "?"}</td>']
        idx = main_idx if kind == "o" else side_idx
        for po, pi, do, di in sides:
            p = _count(po if kind == "o" else pi, card, idx)
            d = _count(do if kind == "o" else di, card, idx)
            if not p and not d:
                cells.append("<td></td>")
                continue
            txt = str(p) if p == d else f"{p}/{d}"
            bad = (not qty) or max(p, d) > qty
            cells.append(f'<td class="{"x" if bad else kind}">{txt}</td>')
        return "<tr>" + "".join(cells) + "</tr>"

    head = ('<thead><tr><th class="card">Card</th><th>Qty</th>'
            + "".join(f'<th class="mu"><span>{e(o)}</span></th>' for o in opps)
            + "</tr></thead>")
    body = [_row(c, q, "o") for c, q in sorted(out_cards.items(), key=lambda kv: (-kv[1], name_key(kv[0])))]
    body.append(f'<tr class="sep"><td colspan="{len(opps) + 2}"></td></tr>')
    body += [_row(c, q, "i") for c, q in sorted(in_cards.items(), key=lambda kv: (-kv[1], name_key(kv[0])))]
    tot = ['<td class="card">Out / In (play)</td><td></td>']
    for po, pi, do, di in sides:
        a, b = sum(po.values()), sum(pi.values())
        a2, b2 = sum(do.values()), sum(di.values())
        ok = a == b and a2 == b2
        txt = f"{a}/{b}" if (a, b) == (a2, b2) else f"{a}/{b} | {a2}/{b2}"
        tot.append(f'<td class="{"" if ok else "x"}">{txt}</td>')
    body.append('<tr class="tot">' + "".join(tot) + "</tr>")

    notes = []
    stale = []
    for r in rows:
        n = _strip_provenance(str(r.get("notes") or ""))
        if n:
            notes.append(f"<li><b>{e(str(r.get('opponent_archetype')))}:</b> {e(n)}</li>")
        if plan_is_stale(r, main, side):
            stale.append(str(r.get("opponent_archetype")))
    warn = ""
    if stale:
        warn = ('<p class="sub"><span class="x">STALE:</span> imported against a different 75 '
                f'(deck changed since): {e(", ".join(stale))}</p>')
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f'<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>{e(title)}</title><style>{_CSS}</style></head><body>"
            f"<h1>{e(title)}</h1><p class=sub>{e(subtitle)}</p>{warn}"
            f'<div class=wrap><table>{head}<tbody>{"".join(body)}</tbody></table></div>'
            f'<div class=notes><h2>Matchup notes</h2><ul>{"".join(notes)}</ul></div>'
            f"</body></html>")


# ---------------------------------------------------------------------------
# Plain-text decklists (for validating without the DB)
# ---------------------------------------------------------------------------

_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$", re.IGNORECASE)


def parse_decklist(text: str) -> tuple[dict, dict]:
    """'4 Card Name' lines. The sideboard starts at a 'Sideboard' header
    (with or without '//' or ':') or, failing that, at the first blank line
    after cards have been read. Other '//' / '#' comment lines are ignored."""
    main: Counter = Counter()
    side: Counter = Counter()
    cur = main
    saw_header = bool(re.search(r"^\s*(//\s*)?sideboard\b", text, re.IGNORECASE | re.MULTILINE))
    for raw in text.splitlines():
        line = raw.strip()
        if re.match(r"^(//\s*)?sideboard\b", line, re.IGNORECASE):
            cur = side
            continue
        if not line:
            if not saw_header and main and cur is main:
                cur = side
            continue
        if line.startswith(("//", "#")):
            continue
        m = _LINE.match(line)
        if m:
            cur[m.group(2)] += int(m.group(1))
    return dict(main), dict(side)
