"""Pure tool logic for the MTG Meta Analyzer MCP server.

Read-only metagame analytics, exposed as plain functions that return
JSON-able dicts. Every matchup/win-rate result carries an explicit `source`
(provenance) field so an agent never confuses *real recorded match results*
(melee.gg) with the *placement-based proxy* (best finish when two decks shared
an event). The underlying analysis layer is deliberate that these are different
signals -- we surface both, labelled, and preserve its data-quality notes.

All functions are read-only. Unknown deck names raise DeckNotFoundError, which
carries machine-usable suggestions so an agent can retry without a human.
"""
from __future__ import annotations

from analysis import win_rates, archetypes

DEFAULT_FORMAT = "standard"
# Formats with enough scraped data to resolve deck names against.
KNOWN_FORMATS = ("standard", "modern", "pioneer", "legacy", "pauper")


class DeckNotFoundError(ValueError):
    """A deck name couldn't be resolved to a tracked archetype.

    Attributes (machine-usable so an agent can self-correct):
        deck:          the unresolved name as given
        format_name:   the format searched
        suggestions:   closest tracked archetype names in that format
        other_formats: formats where this deck DOES appear (if any)
    """

    def __init__(self, deck, format_name, suggestions, other_formats=None):
        self.deck = deck
        self.format_name = format_name
        self.suggestions = list(suggestions or [])
        self.other_formats = list(other_formats or [])
        parts = [f"No deck matching '{deck}' is tracked in {format_name}."]
        if self.suggestions:
            parts.append("Did you mean: " + ", ".join(self.suggestions) + "?")
        if self.other_formats:
            parts.append(
                f"'{deck}' does appear in these formats: "
                + ", ".join(self.other_formats) + "."
            )
        parts.append("Call list_decks to see available decks.")
        super().__init__(" ".join(parts))


# ── deck-name resolution ──────────────────────────────────────────────

def _known_decks(format_name, top=120):
    """Tracked archetype names for a format (the queryable universe)."""
    standings = win_rates.get_meta_standings(
        format_name, top=top, min_appearances=3)
    return [s["archetype"] for s in standings]


def _fuzzy_suggest(name, universe, limit=5, cutoff=60):
    try:
        from rapidfuzz import process, fuzz
    except Exception:  # pragma: no cover - rapidfuzz is a project dep
        return []
    hits = process.extract(name, universe, scorer=fuzz.WRatio, limit=limit)
    return [m for m, score, _ in hits if score >= cutoff]


def _formats_with_deck(name, exclude=None):
    out = []
    target = name.lower()
    for f in KNOWN_FORMATS:
        if f == exclude:
            continue
        if any(d.lower() == target for d in _known_decks(f)):
            out.append(f)
    return out


def _resolve_deck(name, format_name):
    """Resolve a user-supplied deck name to a tracked archetype.

    Uses the analyzer's own normalization (pre_normalize + 250+ aliases +
    fuzzy) so the server speaks the same names as the app. Raises
    DeckNotFoundError with suggestions when it can't.
    """
    if not name or not name.strip():
        raise DeckNotFoundError(name, format_name, [], [])
    universe = _known_decks(format_name)
    by_lower = {d.lower(): d for d in universe}

    # 1. Exact (case-insensitive).
    if name.lower() in by_lower:
        return by_lower[name.lower()]

    # 2. The app's alias + fuzzy normalization layer.
    canon = archetypes.normalize(name, fuzzy=True)
    if canon and canon.lower() in by_lower:
        return by_lower[canon.lower()]

    # 3. No match -> raise with suggestions + where it does appear.
    suggestions = _fuzzy_suggest(name, universe)
    other = _formats_with_deck(canon or name, exclude=format_name)
    raise DeckNotFoundError(name, format_name, suggestions, other)


# ── tools ─────────────────────────────────────────────────────────────

def list_decks(format_name=DEFAULT_FORMAT, limit=20):
    """List the most-played decks (archetypes) in a format, ranked.

    This is the discovery tool: call it first to learn valid deck names and
    get a metagame overview. `meta_share` is each deck's approximate share of
    tracked appearances. `win_rate_source` is 'real_matches' (recorded
    melee.gg results) when available, else 'placement_estimate' (inferred
    from tournament finish -- NOT an actual W/L record).
    """
    all_standings = win_rates.get_meta_standings(
        format_name, top=500, min_appearances=1)
    total = sum(s.get("appearances", 0) for s in all_standings) or 1
    real = win_rates.get_real_archetype_winrates(format_name, min_matches=20)

    decks = []
    for s in all_standings[:limit]:
        arch = s["archetype"]
        entry = {
            "deck": arch,
            "appearances": s.get("appearances", 0),
            "meta_share": round(s.get("appearances", 0) / total, 4),
            "top8_rate": s.get("top8_rate"),
        }
        r = real.get(arch)
        if r:
            entry["win_rate"] = r["win_rate"]
            entry["win_rate_source"] = "real_matches"
            entry["match_record"] = f"{r['wins']}-{r['losses']}"
            entry["sample_size"] = r["total"]
        else:
            entry["win_rate"] = s.get("est_match_winpct", 0.0)
            entry["win_rate_source"] = "placement_estimate"
        decks.append(entry)

    return {
        "format": format_name,
        "deck_count": len(decks),
        "decks": decks,
        "note": (
            "meta_share = approximate share of tracked appearances in this "
            "format. win_rate_source 'real_matches' = recorded melee.gg "
            "results; 'placement_estimate' = inferred from tournament "
            "placement tiers, not actual match records."
        ),
    }


def get_matchup(deck, opponent, format_name=DEFAULT_FORMAT):
    """How `deck` performs against `opponent` in a format.

    Prefers REAL recorded match results (melee.gg) when available; otherwise
    falls back to the placement-based proxy (best finish when both decks were
    in the same event). The `source` field says which -- never treat the
    proxy as a true head-to-head win rate. Unknown deck names raise an error
    listing valid alternatives.
    """
    deck = _resolve_deck(deck, format_name)
    opponent = _resolve_deck(opponent, format_name)

    # 1. Real recorded matches (preferred). Keys are alphabetical; flip if needed.
    real = win_rates.get_real_matchup_winrates(format_name, min_matches=20)
    a, b = sorted([deck, opponent])
    entry = real.get(a, {}).get(b)
    if entry:
        if deck == a:
            wr, wins, losses = entry["win_rate"], entry["wins"], entry["losses"]
        else:
            wr, wins, losses = round(1.0 - entry["win_rate"], 4), entry["losses"], entry["wins"]
        return {
            "deck": deck, "opponent": opponent, "format": format_name,
            "source": "real_matches",
            "win_rate": wr, "wins": wins, "losses": losses,
            "draws": entry["draws"], "sample_size": entry["total"],
            "note": ("Win rate from real recorded match results "
                     "(melee.gg round data + bracket inference)."),
        }

    # 2. Placement-based proxy, clearly labelled (note preserved from source).
    h2h = win_rates.get_head_to_head(deck, opponent, format_name)
    if h2h.get("shared_events"):
        return {
            "deck": deck, "opponent": opponent, "format": format_name,
            "source": "placement_proxy",
            "win_rate": h2h["a_win_rate"],
            "wins": h2h["a_wins"], "losses": h2h["b_wins"], "ties": h2h["ties"],
            "shared_events": h2h["shared_events"],
            "confidence": h2h["confidence"],
            "note": h2h["note"],
        }

    return {
        "deck": deck, "opponent": opponent, "format": format_name,
        "source": "none",
        "note": (f"No recorded matches or shared events between {deck} and "
                 f"{opponent} in {format_name}."),
    }


def _real_matchups_for(deck, format_name, min_matches=20):
    """All of `deck`'s matchups from real recorded results, `deck`-relative.

    Returns a list sorted by win_rate desc, or [] if no real data.
    """
    real = win_rates.get_real_matchup_winrates(format_name, min_matches=min_matches)
    out = []
    for a, opps in real.items():
        for b, st in opps.items():
            if a == deck:
                out.append({
                    "opponent": b, "win_rate": st["win_rate"],
                    "wins": st["wins"], "losses": st["losses"],
                    "draws": st["draws"], "sample_size": st["total"],
                })
            elif b == deck:
                out.append({
                    "opponent": a, "win_rate": round(1.0 - st["win_rate"], 4),
                    "wins": st["losses"], "losses": st["wins"],
                    "draws": st["draws"], "sample_size": st["total"],
                })
    out.sort(key=lambda m: m["win_rate"], reverse=True)
    return out


def get_field_position(deck, format_name=DEFAULT_FORMAT, n_matchups=5):
    """Where `deck` sits in the metagame: meta rank + best/worst matchups.

    `meta_rank` is by tournament performance. best/worst matchups use REAL
    recorded match results when available (`matchup_source` = 'real_matches'),
    otherwise the placement-based proxy. `overall_match_win_rate`, when
    present, is the real recorded win rate across the field. Unknown deck
    names raise an error listing valid alternatives.
    """
    deck = _resolve_deck(deck, format_name)
    standings = win_rates.get_meta_standings(
        format_name, top=500, min_appearances=1)
    rank = next((i + 1 for i, s in enumerate(standings)
                 if s["archetype"] == deck), None)
    mine = next((s for s in standings if s["archetype"] == deck), None)

    # Prefer real recorded matchups; fall back to the placement proxy.
    real_mu = _real_matchups_for(deck, format_name)
    if real_mu:
        best = real_mu[:n_matchups]
        worst = list(reversed(real_mu[-n_matchups:]))
        matchup_source = "real_matches"
        mu_note = ("best/worst matchups are real recorded match win rates "
                   "(melee.gg); sample_size is the games played.")
    else:
        proxy = win_rates.get_archetype_matchups(deck, format_name)

        def _slim(m):
            return {
                "opponent": m["opponent"], "win_rate": m["win_rate"],
                "wins": m["wins"], "losses": m["losses"], "ties": m["ties"],
                "shared_events": m["shared_events"],
                "confidence": m["confidence"],
            }

        best = [_slim(m) for m in proxy[:n_matchups]]
        worst = [_slim(m) for m in reversed(proxy[-n_matchups:])] if proxy else []
        matchup_source = "placement_proxy"
        mu_note = ("best/worst matchups are placement-proxy (best finish when "
                   "both decks were in the same event), not head-to-head "
                   "match records.")

    out = {
        "deck": deck, "format": format_name,
        "meta_rank": rank,
        "total_archetypes": len(standings),
        "appearances": mine.get("appearances", 0) if mine else 0,
        "top8_rate": mine.get("top8_rate") if mine else None,
        "best_matchups": best,
        "worst_matchups": worst,
        "matchup_source": matchup_source,
        "note": mu_note,
    }

    real = win_rates.get_real_archetype_winrates(
        format_name, min_matches=20).get(deck)
    if real:
        out["overall_match_win_rate"] = real["win_rate"]
        out["overall_match_record"] = f"{real['wins']}-{real['losses']}"
        out["overall_win_rate_source"] = "real_matches"
        out["overall_sample_size"] = real["total"]
    return out


def search_matchups(min_win_rate=0.0, max_win_rate=1.0,
                    format_name=DEFAULT_FORMAT, top=15, limit=50):
    """Find matchups whose win rate falls in [min_win_rate, max_win_rate].

    Useful for "which pairings are lopsided?". Built from the placement-based
    matchup matrix of the top `top` archetypes, so `source` is
    'placement_proxy'. Win rates are 0..1; results sorted high to low.
    """
    matrix = win_rates.get_matchup_matrix(format_name, top=top)
    pairs = []
    for a, opps in matrix.get("matrix", {}).items():
        for b, st in opps.items():
            wr = st["win_rate"]
            if min_win_rate <= wr <= max_win_rate:
                pairs.append({
                    "deck": a, "opponent": b, "win_rate": wr,
                    "wins": st["wins"], "losses": st["losses"], "ties": st["ties"],
                    "shared_events": st["shared_events"],
                    "confidence": st["confidence"],
                })
    pairs.sort(key=lambda m: m["win_rate"], reverse=True)
    return {
        "format": format_name,
        "win_rate_band": [min_win_rate, max_win_rate],
        "count": len(pairs),
        "source": "placement_proxy",
        "matchups": pairs[:limit],
        "note": matrix.get("note", ""),
    }
