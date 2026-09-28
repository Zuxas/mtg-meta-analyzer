"""Name an archetype from a PARTIAL decklist (the cards seen in a match).

Scores each archetype's card profile against the seen cards. Cards are
weighted by rarity across archetypes (a card in every deck, e.g. a fetchland,
says little) and by how often the archetype plays them. Confidence scales
with how many distinct cards were seen -- three cards is a guess, eight is
evidence -- and drops when the top two archetypes are close.

Profiles come from the scraped decklists of the same format around the
match date, so a 2024 match is judged against the 2024 meta.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache

BASICS = {"plains", "island", "swamp", "mountain", "forest", "wastes",
          "snow-covered plains", "snow-covered island", "snow-covered swamp",
          "snow-covered mountain", "snow-covered forest"}
MIN_OVERLAP = 3
MIN_SCORE = 0.30
FULL_EVIDENCE = 8
AMBIGUITY_GAP = 0.05


def score_profiles(seen: set[str], profiles: dict[str, dict[str, float]]):
    """profiles: {archetype: {card_lower: share of that archetype's decks}}.
    Returns (archetype, confidence, overlap) or None."""
    seen = {c.lower() for c in seen} - BASICS
    if len(seen) < MIN_OVERLAP or not profiles:
        return None
    n_arch = len(profiles)
    df: dict[str, int] = defaultdict(int)
    for prof in profiles.values():
        for c in prof:
            df[c] += 1
    weight = {c: math.log((n_arch + 1) / (df.get(c, 0) + 1)) + 0.05 for c in seen}
    total = sum(weight.values())
    ranked = []
    for arch, prof in profiles.items():
        overlap = [c for c in seen if c in prof]
        if len(overlap) < MIN_OVERLAP:
            continue
        s = sum(weight[c] * prof[c] for c in overlap) / total
        ranked.append((s, arch, len(overlap)))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    best, arch, overlap = ranked[0]
    if best < MIN_SCORE:
        return None
    conf = best * min(1.0, len(seen) / FULL_EVIDENCE)
    if len(ranked) > 1 and best - ranked[1][0] < AMBIGUITY_GAP:
        conf *= 0.7
    return arch, round(conf, 3), overlap


def load_profiles(con, format_name: str, around: date,
                  before_days: int = 270, after_days: int = 90,
                  mapping_out: dict | None = None) -> dict[str, dict[str, float]]:
    from db.helpers import SQL_NORM_DATE
    lo = (around - timedelta(days=before_days)).isoformat()
    hi = (around + timedelta(days=after_days)).isoformat()
    nd = SQL_NORM_DATE.format(col="e.date")
    rows = con.execute(
        f"""SELECT d.archetype, lower(c.name), COUNT(DISTINCT d.id)
            FROM decks d
            JOIN events e ON e.id = d.event_id
            JOIN deck_cards dc ON dc.deck_id = d.id AND dc.is_sideboard = 0
            JOIN cards c ON c.id = dc.card_id
            WHERE e.format = ? AND d.archetype IS NOT NULL AND d.archetype != ''
              AND {nd} BETWEEN ? AND ?
            GROUP BY d.archetype, lower(c.name)""",
        (format_name, lo, hi)).fetchall()
    sizes = dict(con.execute(
        f"""SELECT d.archetype, COUNT(*) FROM decks d JOIN events e ON e.id = d.event_id
            WHERE e.format = ? AND d.archetype IS NOT NULL AND d.archetype != ''
              AND {nd} BETWEEN ? AND ? GROUP BY d.archetype""",
        (format_name, lo, hi)).fetchall())
    canon = _canonical()
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for arch, n in sizes.items():
        totals[canon(arch)] += n
    for arch, card, n in rows:
        counts[canon(arch)][card] += n
    popularity: dict[str, int] = defaultdict(int)
    for arch, n in con.execute(
            """SELECT d.archetype, COUNT(*) FROM decks d JOIN events e ON e.id = d.event_id
               WHERE e.format = ? AND d.archetype IS NOT NULL AND d.archetype != ''
               GROUP BY d.archetype""", (format_name,)).fetchall():
        popularity[canon(arch)] += n
    counts, totals = merge_umbrellas(counts, totals, mapping=mapping_out, popularity=popularity)
    return {a: {c: n / totals[a] for c, n in cards.items()}
            for a, cards in counts.items() if totals[a] >= 3}


UMBRELLA_MIN_COSINE = 0.95


def _cosine(a: dict, b: dict) -> float:
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def merge_umbrellas(counts: dict, totals: dict, mapping: dict | None = None,
                    popularity: dict | None = None) -> tuple[dict, dict]:
    """Fold an umbrella label into the specific label it abbreviates, within
    ONE format's window: "Boros" -> "Boros Energy" when the words of "Boros"
    are a strict subset of "Boros Energy" and the decklists match (cosine of
    per-card shares >= UMBRELLA_MIN_COSINE). With several candidates the most
    played wins, and it must be at least as common as the umbrella -- else a
    common name folds into a rare pilot/typo label ("Boros Energy" ->
    "Boros Energy Gingerkush", seen on the 2026-09-28 dry run). Per-format
    only -- never a global alias, since "Boros" means different decks in
    different formats. `mapping`, if given, records {umbrella: specific}."""
    def words(s):
        return set(s.lower().replace("-", " ").split())

    def shares(a):
        return {c: n / totals[a] for c, n in counts[a].items()} if totals.get(a) else {}

    merged = {a: dict(c) for a, c in counts.items()}
    tot = dict(totals)
    for small in sorted(counts, key=lambda a: len(words(a))):
        ws = words(small)
        cands = [big for big in counts if big != small and ws < words(big)
                 and big in merged and totals.get(big, 0) >= totals.get(small, 0)
                 and _cosine(shares(small), shares(big)) >= UMBRELLA_MIN_COSINE]
        if not cands or small not in merged:
            continue
        # the format's all-time most common name wins, so one umbrella resolves
        # to the same label every month (Boros -> Boros Energy, not Ocelot in May)
        pop = popularity or {}
        big = max(cands, key=lambda a: (pop.get(a, 0), tot.get(a, 0), a))
        for card, n in merged.pop(small).items():
            merged[big][card] = merged[big].get(card, 0) + n
        tot[big] = tot.get(big, 0) + tot.pop(small, 0)
        if mapping is not None:
            mapping[small] = big
    if mapping is not None:  # resolve chains: A -> B, B -> C  =>  A -> C
        for k in list(mapping):
            seen = {k}
            while mapping[k] in mapping and mapping[k] not in seen:
                seen.add(mapping[k])
                mapping[k] = mapping[mapping[k]]
    return merged, tot


def _canonical():
    try:
        from analysis.archetypes import normalize
    except ImportError:  # pragma: no cover
        return lambda s: s
    return lambda s: normalize(s) or s


FORMATS = {"standard", "pioneer", "modern", "legacy", "vintage", "pauper"}


class ProfileCache:
    """One profile set per (format, month) -- matches in the same month share it."""

    def __init__(self, con):
        self.con = con
        self._get = lru_cache(maxsize=64)(self._load)

    def _load(self, format_name: str, year: int, month: int):
        mapping: dict = {}
        prof = load_profiles(self.con, format_name, date(year, month, 15), mapping_out=mapping)
        return prof, mapping

    def classify(self, seen: set[str], format_name: str, when: date):
        if format_name not in FORMATS:
            return None
        return score_profiles(seen, self._get(format_name, when.year, when.month)[0])

    def rename(self, label: str, format_name: str, when: date) -> str:
        """A stored label under the approved merges ONLY: the global spelling
        aliases, then the umbrella fold of that format and month. Never a
        re-classification."""
        if not label:
            return label
        canon = _canonical()(label)
        if format_name not in FORMATS:
            return canon
        return self._get(format_name, when.year, when.month)[1].get(canon, canon)
