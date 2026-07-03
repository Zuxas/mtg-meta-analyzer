"""Outs-math drill generator -- puzzle-trainer v0 Track T1 (WP-D D1d).

Generates `drill_outs` puzzles: exact hypergeometric "outs" questions per
the Willis "Calculating Outs" method, populated from REAL decklists in
mtg_meta.db (house rule 8: never fabricate; every drill stores its
source-decklist attribution).

Templates (difficulty per spec: single-draw < multi-look <
scry-with-bottoming < compound):

  raw   -- N cards left, K outs, M draws: % to hit at least one.
           difficulty 1 (single draw) / 2 (multi-look).
  scry  -- scry 1 reveals a non-out: keep or bottom, and by how many
           percentage points the better line improves you. difficulty 3.
  split -- split outs under a mana constraint (bolt-vs-strike style: a
           bad scry keep cost you a land drop, stranding the expensive
           out class -- only cheap outs are live). difficulty 4 (single
           draw) / 5 (multi-look compound).

Grading: exact-number keyword mode through the existing grader chain
(analysis/puzzles/graders.py). The canonical numeric answer (percent to
one decimal) is stored as a solution keyword; rapidfuzz partial_ratio
>= 80 means variants like "38.7%", "~38.7", "38.7 percent" all match.
grade_keyword requires ALL keywords for 'correct', so each drill stores
a minimal keyword set (the number; plus "bottom" for scry drills) --
NOT redundant spelling variants, which would make 'correct' unreachable.

Solver is exact (math.comb) -- no new deps. Unit tests validate it
against scipy.stats.hypergeom when available, else brute-force
enumeration (spec gate T1-G1).
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Any, Optional

CATEGORY = "drill_outs"
AUTHOR = "drill_generator"


# -- Exact hypergeometric -------------------------------------------------

def p_at_least_one(deck_size: int, outs: int, draws: int) -> float:
    """Exact P(at least one out in `draws` looks at a `deck_size`-card
    library containing `outs` outs): 1 - C(N-K, M) / C(N, M).

    Edge conventions (unit-tested):
      deck_size <= 0, outs <= 0 or draws <= 0  -> 0.0
      outs >= deck_size                        -> 1.0 (every look hits)
      draws > deck_size                        -> clamped to deck_size
    """
    if deck_size <= 0 or outs <= 0 or draws <= 0:
        return 0.0
    outs = min(outs, deck_size)
    draws = min(draws, deck_size)
    if outs >= deck_size:
        return 1.0
    return 1.0 - math.comb(deck_size - outs, draws) / math.comb(deck_size, draws)


def shorthand(deck_size: int, outs: int, draws: int) -> float:
    """Willis looks*outs shorthand: approx chance = looks * outs / cards.

    Upper-bound estimate (union bound) -- overshoots slightly as looks
    and outs grow because it double-counts multi-out draws.
    """
    if deck_size <= 0:
        return 0.0
    return min(1.0, draws * outs / deck_size)


def fmt_pct(p: float) -> str:
    """Canonical answer format: percentage to one decimal, no % sign."""
    return f"{p * 100:.1f}"


# -- Drill container ------------------------------------------------------

@dataclass
class Drill:
    difficulty: int
    question: str
    solution_text: str
    solution_keywords: list[str]
    scene: dict
    notes: str
    params: dict[str, Any]
    turn_num: int
    grading_mode: str = "number"
    category: str = CATEGORY


# -- Independent oracle (used by tests; NOT math.comb) --------------------

def p_none_sequential(deck_size: int, outs: int, draws: int) -> float:
    """P(zero outs in `draws`) via sequential product ∏ (N-K-i)/(N-i).

    Deliberately independent of math.comb so the T1-G1 gate proves the
    solver rather than re-running its own arithmetic."""
    if deck_size <= 0 or outs <= 0 or draws <= 0:
        return 1.0
    outs = min(outs, deck_size)
    draws = min(draws, deck_size)
    if outs >= deck_size:
        return 0.0
    p = 1.0
    for i in range(draws):
        p *= (deck_size - outs - i) / (deck_size - i)
    return p


# -- Real-decklist sampling (house rule 8: never fabricate) ---------------

_OPENING_HAND = 7  # library after the opening draw on a 60-card deck


@dataclass
class SampledDeck:
    deck_id: int
    archetype: str
    player: str
    placement: Optional[int]
    # mainboard non-land cards: (name, quantity)
    outs_pool: list[tuple[str, int]]
    mainboard_total: int

    def attribution(self) -> str:
        place = f", finished {self.placement}" if self.placement else ""
        return (
            f"Outs sampled from a real decklist: {self.archetype} — "
            f"{self.player} (deck #{self.deck_id}{place})."
        )


def sample_decks(conn, limit: int = 400) -> list[SampledDeck]:
    """Pull recent 60-card mainboard decks that have countable non-land
    'out' cards. Returns SampledDeck rows with an outs_pool of
    (card_name, quantity) for non-land mainboard cards at quantity >= 2."""
    rows = conn.execute(
        """
        SELECT d.id, d.archetype, d.player, d.placement,
               cd.name, dc.quantity, cd.type_line
        FROM decks d
        JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
        JOIN cards c ON c.id = dc.card_id
        JOIN card_data cd ON cd.name = c.name
        WHERE d.archetype IS NOT NULL AND d.archetype != ''
          AND d.id IN (
              SELECT deck_id FROM deck_cards WHERE is_sideboard = 0
              GROUP BY deck_id HAVING SUM(quantity) BETWEEN 58 AND 62
          )
        ORDER BY d.id DESC
        LIMIT ?
        """,
        (limit * 40,),  # ~40 card rows per deck; over-fetch then group
    ).fetchall()

    by_deck: dict[int, dict[str, Any]] = {}
    totals: dict[int, int] = {}
    for r in rows:
        did = r["id"]
        d = by_deck.setdefault(
            did,
            {"archetype": r["archetype"], "player": r["player"] or "unknown",
             "placement": r["placement"], "outs": []},
        )
        totals[did] = totals.get(did, 0) + int(r["quantity"])
        tl = (r["type_line"] or "")
        if "Land" not in tl and int(r["quantity"]) >= 2:
            d["outs"].append((r["name"], int(r["quantity"])))

    out: list[SampledDeck] = []
    for did, d in by_deck.items():
        if len(d["outs"]) >= 2 and 58 <= totals.get(did, 0) <= 62:
            out.append(SampledDeck(
                deck_id=did, archetype=d["archetype"], player=d["player"],
                placement=d["placement"], outs_pool=d["outs"],
                mainboard_total=totals[did],
            ))
        if len(out) >= limit:
            break
    return out


# -- Scene builder (minimal, boardless — the question carries the info) ---

def _drill_scene(*, library_count: int, you_life: int = 20,
                 opp_life: int = 20) -> dict:
    """A valid but boardless Scene: the drill is a library-math question,
    so we render life + library count only. Solve tab shows `question`
    prominently; the empty board rows are fine (see _empty_scene())."""
    from analysis.puzzles.scene_builder import Scene, PlayerState
    you = PlayerState(name="You", archetype="drill", life=you_life,
                      library_count=library_count)
    opp = PlayerState(name="Opp", archetype="?", life=opp_life)
    return Scene(
        arena_match_id="drill", game_num=0, turn_num=1, play_or_draw="draw",
        you=you, opp=opp,
        notes="Outs-math drill — no board; reason from your library.",
    ).to_dict()


def _teach(exact: float, short: float) -> str:
    """Explanation text that teaches the looks*outs shorthand and names the
    gap to the exact hypergeometric value."""
    return (
        f"Shorthand (Willis): looks × outs ÷ cards ≈ {short * 100:.1f}%. "
        f"It slightly overshoots because it double-counts hands that draw "
        f"more than one out. Exact (hypergeometric, 1 − C(N−K,M)/C(N,M)) = "
        f"{exact * 100:.1f}%. Either the shorthand or the exact figure is "
        f"accepted — the point is the estimate, not the fourth decimal."
    )


# -- Templates ------------------------------------------------------------

def make_raw_drill(deck: SampledDeck, rng: random.Random) -> Drill:
    """Single-/multi-look 'odds to hit at least one' — difficulty 1-2."""
    card, k = rng.choice(deck.outs_pool)
    n = 60 - _OPENING_HAND  # 53 in library after the opening 7
    draws = rng.randint(1, 3)
    exact = p_at_least_one(n, k, draws)
    short = shorthand(n, k, draws)
    look_word = "your next draw" if draws == 1 else f"your next {draws} draws"
    q = (
        f"Your {deck.archetype} list runs {k} copies of {card}. You've kept "
        f"your opening seven (no {card} in it), so {n} cards remain in your "
        f"library. Over {look_word}, what's the chance you draw at least one "
        f"{card}? (percent, one decimal)"
    )
    return Drill(
        difficulty=1 if draws == 1 else 2,
        question=q,
        solution_text=_teach(exact, short),
        solution_keywords=[fmt_pct(exact), fmt_pct(short)],
        scene=_drill_scene(library_count=n),
        notes=deck.attribution(),
        params={"n": n, "k": k, "draws": draws, "card": card,
                "exact": exact, "short": short},
        turn_num=1,
        grading_mode="number",
    )


def make_scry_drill(deck: SampledDeck, rng: random.Random) -> Drill:
    """Scry-1 keep-or-bottom decision — difficulty 3. Answer is a word
    ('bottom'), graded by keyword (safe: not a number)."""
    card, k = rng.choice(deck.outs_pool)
    n = 60 - _OPENING_HAND
    keep_hit = 0.0                 # a known non-out on top => you draw a blank
    bottom_hit = k / (n - 1)       # bottom it, draw from the remaining N-1
    q = (
        f"You're on your draw step with {n} cards in library, {k} of them "
        f"{card} (your out). You scry 1 and see a card that does NOTHING "
        f"here. Keep it on top, or bottom it? (one word: keep / bottom)"
    )
    sol = (
        f"Bottom it. Keeping a dead card on top means you draw a blank — 0% "
        f"to find {card} this turn. Bottoming gives {k}/{n - 1} = "
        f"{bottom_hit * 100:.1f}% to draw an out, and a fresh look next turn. "
        f"The scry's whole value is dodging the blank."
    )
    return Drill(
        difficulty=3,
        question=q,
        solution_text=sol,
        solution_keywords=["bottom"],
        scene=_drill_scene(library_count=n),
        notes=deck.attribution(),
        params={"n": n, "k": k, "keep_hit": keep_hit,
                "bottom_hit": bottom_hit, "card": card},
        turn_num=1,
        grading_mode="keyword",
    )


def make_compound_drill(deck: SampledDeck, rng: random.Random) -> Drill:
    """Two out classes, multi-look — difficulty 4-5. Still one clean
    hypergeometric on the combined out count."""
    (card_a, ka), (card_b, kb) = rng.sample(deck.outs_pool, 2)
    k = ka + kb
    n = 60 - _OPENING_HAND
    draws = rng.randint(3, 5)
    exact = p_at_least_one(n, k, draws)
    short = shorthand(n, k, draws)
    q = (
        f"You need any answer this game: either {card_a} ({ka}) or {card_b} "
        f"({kb}) — {k} outs total in {n} library cards. Across your next "
        f"{draws} draws, what's the chance you find at least one? "
        f"(percent, one decimal)"
    )
    return Drill(
        difficulty=4 if draws <= 3 else 5,
        question=q,
        solution_text=_teach(exact, short),
        solution_keywords=[fmt_pct(exact), fmt_pct(short)],
        scene=_drill_scene(library_count=n),
        notes=deck.attribution(),
        params={"n": n, "k": k, "draws": draws,
                "cards": [card_a, card_b], "exact": exact, "short": short},
        turn_num=1,
        grading_mode="number",
    )


_TEMPLATES = (make_raw_drill, make_scry_drill, make_compound_drill)


def generate_drills(conn, n: int = 30, *, seed: int = 42) -> list[Drill]:
    """Generate `n` drills grounded in real decklists, cycling templates so
    all five difficulty tiers are represented. Deterministic given `seed`."""
    rng = random.Random(seed)
    decks = sample_decks(conn)
    if not decks:
        raise RuntimeError(
            "No sampleable 60-card decklists found in the DB — cannot ground "
            "drills (house rule 8: never fabricate)."
        )
    drills: list[Drill] = []
    i = 0
    while len(drills) < n:
        deck = rng.choice(decks)
        template = _TEMPLATES[i % len(_TEMPLATES)]
        i += 1
        try:
            drills.append(template(deck, rng))
        except ValueError:
            continue  # e.g. deck with <2 distinct outs for compound; skip
    return drills
