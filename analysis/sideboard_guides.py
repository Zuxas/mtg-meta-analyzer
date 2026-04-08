"""
analysis/sideboard_guides.py — Knowledge-base sideboard guide integration.

Queries the local guides table for matchup-relevant entries, parses sideboard
plans from comment text, and produces G2/G3 win-rate estimates.

Public functions:
    parse_sb_plan(comment)                    -> dict
    get_matchup_guides(my_arch, opp_arch, fmt) -> dict
    estimate_postboard_wr(g1_wr, my_in, opp_in) -> float
    flip_analysis(g1_wr, g23_wr)             -> dict
"""
import re

# ---------------------------------------------------------------------------
# Sideboard plan parsing
# ---------------------------------------------------------------------------

# Matches:  +4 Card Name  |  + 4 Card Name  (leading +)
_IN_PLUS  = re.compile(r'^\+\s*(\d+)\s+([A-Z][^\n+\-]{2,50})', re.MULTILINE)
# Matches:  -4 Card Name  |  - 4 Card Name  (leading -)
_OUT_MINUS = re.compile(r'^\-\s*(\d+)\s+([A-Z][^\n+\-]{2,50})', re.MULTILINE)
# Matches:  IN: 3 Card, 2 Other  /  Bring in 3x Card  /  Side in 3 Card
_IN_LABEL  = re.compile(
    r'(?:^|\b)(?:IN|bring\s+in|side\s+in)[:\s]+(\d+)x?\s+([A-Z][^\n,+\-]{2,50})',
    re.MULTILINE | re.IGNORECASE,
)
# Matches:  OUT: 3 Card  /  Take out 3 Card  /  Cut 3 Card  /  Side out 3 Card
_OUT_LABEL = re.compile(
    r'(?:^|\b)(?:OUT|take\s+out|cut|side\s+out)[:\s]+(\d+)x?\s+([A-Z][^\n,+\-]{2,50})',
    re.MULTILINE | re.IGNORECASE,
)


def _extract_cards(text: str, *patterns) -> list[tuple[int, str]]:
    """Return [(qty, card_name), ...] from all matches across given patterns."""
    results = []
    for pat in patterns:
        for m in pat.finditer(text):
            qty  = int(m.group(1))
            name = m.group(2).strip().rstrip('.,;').strip()
            if qty > 0 and len(name) >= 3:
                results.append((qty, name))
    return results


# Play/draw section markers
_ON_PLAY = re.compile(r'(?:^|\n)\s*(?:on\s+the\s+play|OTP)\s*[:\-]?\s*', re.IGNORECASE)
_ON_DRAW = re.compile(r'(?:^|\n)\s*(?:on\s+the\s+draw|OTD)\s*[:\-]?\s*', re.IGNORECASE)


def _split_play_draw(comment: str) -> tuple[str | None, str | None]:
    """Split comment into play-specific and draw-specific sections.

    Returns (play_section, draw_section). If no markers found, returns (None, None).
    """
    play_m = _ON_PLAY.search(comment)
    draw_m = _ON_DRAW.search(comment)
    if not play_m and not draw_m:
        return None, None

    # Figure out section boundaries
    play_start = play_m.end() if play_m else None
    draw_start = draw_m.end() if draw_m else None

    play_text = None
    draw_text = None

    if play_start is not None and draw_start is not None:
        if play_start < draw_start:
            play_text = comment[play_start:draw_m.start()]
            draw_text = comment[draw_start:]
        else:
            draw_text = comment[draw_start:play_m.start()]
            play_text = comment[play_start:]
    elif play_start is not None:
        play_text = comment[play_start:]
    elif draw_start is not None:
        draw_text = comment[draw_start:]

    return play_text, draw_text


def parse_sb_plan(comment: str | None) -> dict:
    """
    Parse a sideboard plan from free-form comment text.

    Recognises these formats (all case-variants):
      +4 Card Name / -4 Card Name
      IN: 4 Card Name / OUT: 4 Card Name
      Bring in 4 Card Name / Take out 4 Card Name

    If the comment contains "On the play" / "On the draw" (or OTP/OTD) markers,
    also returns play-specific and draw-specific IN/OUT lists.

    Returns:
      {
        "in":           [(qty, name), ...],
        "out":          [(qty, name), ...],
        "total_in":     int,
        "play_in":      [(qty, name), ...],   # play-specific (empty if no markers)
        "play_out":     [(qty, name), ...],
        "draw_in":      [(qty, name), ...],   # draw-specific (empty if no markers)
        "draw_out":     [(qty, name), ...],
        "has_play_draw": bool,
      }
    """
    if not comment:
        return {"in": [], "out": [], "total_in": 0,
                "play_in": [], "play_out": [], "draw_in": [], "draw_out": [],
                "has_play_draw": False}

    # Global IN/OUT (entire comment)
    cards_in  = _extract_cards(comment, _IN_PLUS,  _IN_LABEL)
    cards_out = _extract_cards(comment, _OUT_MINUS, _OUT_LABEL)

    # Play/draw split
    play_text, draw_text = _split_play_draw(comment)
    has_pd = play_text is not None or draw_text is not None

    play_in = play_out = draw_in = draw_out = []
    if play_text:
        play_in  = _extract_cards(play_text, _IN_PLUS, _IN_LABEL)
        play_out = _extract_cards(play_text, _OUT_MINUS, _OUT_LABEL)
    if draw_text:
        draw_in  = _extract_cards(draw_text, _IN_PLUS, _IN_LABEL)
        draw_out = _extract_cards(draw_text, _OUT_MINUS, _OUT_LABEL)

    return {
        "in":            cards_in,
        "out":           cards_out,
        "total_in":      sum(q for q, _ in cards_in),
        "play_in":       play_in,
        "play_out":      play_out,
        "draw_in":       draw_in,
        "draw_out":      draw_out,
        "has_play_draw": has_pd,
    }


# ---------------------------------------------------------------------------
# Archetype matching helpers
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    return s.lower().strip()


def _arch_matches(guide_arch: str, target: str) -> bool:
    """
    True when guide_arch is relevant to target archetype.
    Checks substring both ways and first-two-word match.
    """
    g = _normalise(guide_arch)
    t = _normalise(target)
    if t in g or g in t:
        return True
    # first 2 meaningful words of target present in guide arch
    words = [w for w in t.split() if len(w) > 2][:2]
    return len(words) >= 2 and all(w in g for w in words)


# ---------------------------------------------------------------------------
# Guide DB lookup
# ---------------------------------------------------------------------------

def get_matchup_guides(my_archetype: str, opp_archetype: str, fmt: str) -> dict:
    """
    Query the guides table for entries relevant to either archetype in this matchup.

    Returns:
      {
        "my_guides":   [row_dict, ...],
        "opp_guides":  [row_dict, ...],
        "my_sb_plan":  {"in": [...], "out": [...], "total_in": int},
        "opp_sb_plan": {"in": [...], "out": [...], "total_in": int},
        "my_count":    int,
        "opp_count":   int,
      }
    """
    from db.database import get_combined_connection

    my_n  = _normalise(my_archetype)
    opp_n = _normalise(opp_archetype)

    conn = get_combined_connection()
    try:
        rows = conn.execute(
            """
            SELECT archetype, type, comment, url, source, author, date
            FROM guides
            WHERE (
                lower(archetype) LIKE ?
                OR lower(archetype) LIKE ?
                OR lower(archetype) LIKE ?
                OR lower(archetype) LIKE ?
            )
            AND (lower(format) = ? OR format IS NULL OR format = '')
            LIMIT 60
            """,
            [
                f"%{my_n}%",
                f"%{opp_n}%",
                f"%{my_n.split()[0] if my_n.split() else my_n}%",
                f"%{opp_n.split()[0] if opp_n.split() else opp_n}%",
                fmt.lower(),
            ],
        ).fetchall()
    finally:
        conn.close()

    my_guides  = []
    opp_guides = []
    for row in rows:
        arch = row["archetype"] or ""
        g    = dict(row)
        if _arch_matches(arch, my_archetype):
            my_guides.append(g)
        if _arch_matches(arch, opp_archetype):
            opp_guides.append(g)

    my_sb  = _merge_sb_plans([parse_sb_plan(g.get("comment")) for g in my_guides])
    opp_sb = _merge_sb_plans([parse_sb_plan(g.get("comment")) for g in opp_guides])

    return {
        "my_guides":   my_guides,
        "opp_guides":  opp_guides,
        "my_sb_plan":  my_sb,
        "opp_sb_plan": opp_sb,
        "my_count":    len(my_guides),
        "opp_count":   len(opp_guides),
    }


def _merge_card_lists(plans: list[dict], field: str) -> list[tuple[int, str]]:
    """Merge card lists from multiple plans, keeping the highest qty per card."""
    seen: dict[str, int] = {}
    for plan in plans:
        for qty, name in plan.get(field, []):
            seen[name] = max(seen.get(name, 0), qty)
    return sorted([(q, n) for n, q in seen.items()], key=lambda x: -x[0])


def _merge_sb_plans(plans: list[dict]) -> dict:
    """Merge multiple parsed plans, keeping the highest qty seen per card name."""
    merged_in  = _merge_card_lists(plans, "in")
    merged_out = _merge_card_lists(plans, "out")
    has_pd = any(p.get("has_play_draw") for p in plans)
    return {
        "in":            merged_in,
        "out":           merged_out,
        "total_in":      sum(q for q, _ in merged_in),
        "play_in":       _merge_card_lists(plans, "play_in"),
        "play_out":      _merge_card_lists(plans, "play_out"),
        "draw_in":       _merge_card_lists(plans, "draw_in"),
        "draw_out":      _merge_card_lists(plans, "draw_out"),
        "has_play_draw": has_pd,
    }


# ---------------------------------------------------------------------------
# Post-board win-rate model
# ---------------------------------------------------------------------------

# Each dedicated sideboard card = ~1.3% swing, hard-capped at 13% per side.
# The asymmetry (+0.008 my side, -0.013 opp side) reflects that reactive/hate
# cards tend to have a larger impact on the matchup than proactive additions.
_MY_PER_CARD  = 0.010
_OPP_PER_CARD = 0.013
_CAP          = 0.13


def estimate_postboard_wr(g1_wr: float, my_sb_in: int, opp_sb_in: int) -> float:
    """
    Estimate the G2/G3 match win rate from a G1 baseline.

    Each side's dedicated sideboard cards shift the win rate:
      - Opponent bringing hate cards hurts our post-board rate.
      - Our targeted answers improve it.

    Returns a float in [0.18, 0.84].
    """
    opp_impact = min(opp_sb_in * _OPP_PER_CARD, _CAP)
    my_impact  = min(my_sb_in  * _MY_PER_CARD,  _CAP)
    adjusted   = g1_wr - opp_impact + my_impact
    return round(max(0.18, min(0.84, adjusted)), 3)


# ---------------------------------------------------------------------------
# Flip / post-board verdict
# ---------------------------------------------------------------------------

def flip_analysis(g1_wr: float, g23_wr: float, has_guide_data: bool = True) -> dict:
    """
    Classify whether the matchup dynamic changes post-board.

    Returns:
      {
        "flipped":             bool,
        "significantly_worse": bool,
        "delta":               float,
        "verdict":             str,
        "color":               str,
        "has_data":            bool,
      }
    """
    delta   = round(g23_wr - g1_wr, 3)
    g1_fav  = g1_wr  >= 0.50
    g23_fav = g23_wr >= 0.50

    no_data = not has_guide_data

    if no_data:
        verdict = (
            f"G1: {g1_wr*100:.0f}%  —  No sideboard guide data available. "
            f"G2/G3 estimate unavailable; treat G1 rate as your only signal."
        )
        return {
            "flipped":             False,
            "significantly_worse": False,
            "delta":               0.0,
            "verdict":             verdict,
            "color":               "#8a9aaa",
            "has_data":            False,
        }

    if g1_fav and not g23_fav:
        verdict = (
            f"FLIPPED — You are favored game 1 ({g1_wr*100:.0f}%) but this matchup "
            f"flips games 2 and 3 based on available sideboard guides "
            f"({g23_wr*100:.0f}%). The opponent's sideboard is crushing you. "
            f"Address their hate cards or find a different approach."
        )
        color   = "#e6194b"
        flipped = True
    elif not g1_fav and g23_fav:
        verdict = (
            f"FLIPS IN YOUR FAVOR — Unfavored game 1 ({g1_wr*100:.0f}%), "
            f"but your sideboard flips this matchup games 2 and 3 "
            f"({g23_wr*100:.0f}%). Winning game 1 is key; you get better after."
        )
        color   = "#3cb44b"
        flipped = True
    elif delta <= -0.07:
        verdict = (
            f"Significantly worse post-board: {g1_wr*100:.0f}% G1 → "
            f"{g23_wr*100:.0f}% G2/G3. Opponent's sideboard cards are highly "
            f"effective against your strategy. Prioritise finding answers."
        )
        color   = "#f58231"
        flipped = False
    elif delta >= 0.06:
        verdict = (
            f"Improves post-board: {g1_wr*100:.0f}% G1 → "
            f"{g23_wr*100:.0f}% G2/G3. Your sideboard is doing real work here."
        )
        color   = "#3cb44b"
        flipped = False
    else:
        adj = "slightly worse" if delta < -0.02 else ("slightly better" if delta > 0.02 else "stable")
        verdict = (
            f"Matchup is {adj} post-board: "
            f"G1 {g1_wr*100:.0f}% → G2/G3 {g23_wr*100:.0f}%."
        )
        color   = "#8a9aaa" if abs(delta) < 0.02 else ("#bfef45" if delta > 0 else "#f0c020")
        flipped = False

    return {
        "flipped":             flipped,
        "significantly_worse": delta <= -0.05,
        "delta":               delta,
        "verdict":             verdict,
        "color":               color,
        "has_data":            True,
    }


# ---------------------------------------------------------------------------
# HTML rendering helper (used by the UI layer)
# ---------------------------------------------------------------------------

def _sb_list_html(cards: list[tuple[int, str]], label: str, color: str) -> str:
    if not cards:
        return ""
    items = "  ".join(f"<b>+{q}</b> {n}" if label == "IN" else f"<b>-{q}</b> {n}"
                      for q, n in cards)
    return (
        f'<span style="color:{color}; font-weight:bold;">{label}:</span> '
        f'<span style="color:{color};">{items}</span><br>'
    )


def render_guide_html(guide_data: dict, my_archetype: str, opp_archetype: str) -> str:
    """
    Return an HTML snippet describing the guide-based sideboard information
    for one matchup. Called per-matchup from the UI layer.
    """
    my_sb   = guide_data["my_sb_plan"]
    opp_sb  = guide_data["opp_sb_plan"]
    my_cnt  = guide_data["my_count"]
    opp_cnt = guide_data["opp_count"]

    parts = []

    if my_cnt == 0 and opp_cnt == 0:
        parts.append(
            f'<span style="color:#8a9aaa; font-style:italic;">'
            f'No sideboard guides found for this matchup in the knowledge base.</span><br>'
        )
        return "".join(parts)

    # Your perspective
    if my_cnt > 0:
        parts.append(
            f'<span style="color:#5eb5cf;"><b>Your guides</b></span> '
            f'<span style="color:#8a9aaa;">({my_cnt} guide{"s" if my_cnt > 1 else ""} '
            f'for {my_archetype})</span><br>'
        )
        if my_sb["in"] or my_sb["out"]:
            if my_sb.get("has_play_draw") and (my_sb.get("play_in") or my_sb.get("draw_in")):
                # Show play/draw split
                parts.append('<span style="color:#bfef45; font-weight:bold;">ON THE PLAY:</span><br>')
                parts.append(_sb_list_html(my_sb.get("play_in", []),  "IN",  "#3cb44b"))
                parts.append(_sb_list_html(my_sb.get("play_out", []), "OUT", "#e6194b"))
                parts.append('<span style="color:#bfef45; font-weight:bold;">ON THE DRAW:</span><br>')
                parts.append(_sb_list_html(my_sb.get("draw_in", []),  "IN",  "#3cb44b"))
                parts.append(_sb_list_html(my_sb.get("draw_out", []), "OUT", "#e6194b"))
            else:
                # Fallback: show generic IN/OUT
                parts.append(_sb_list_html(my_sb["in"],  "IN",  "#3cb44b"))
                parts.append(_sb_list_html(my_sb["out"], "OUT", "#e6194b"))
        else:
            parts.append(
                '<span style="color:#8a9aaa; font-style:italic;">'
                'Guides found but no +/- sideboard plan detected in comments.</span><br>'
            )

    # Opponent's perspective
    if opp_cnt > 0:
        parts.append(
            f'<span style="color:#f58231;"><b>Opponent guides</b></span> '
            f'<span style="color:#8a9aaa;">({opp_cnt} guide{"s" if opp_cnt > 1 else ""} '
            f'for {opp_archetype} — what they bring against you)</span><br>'
        )
        if opp_sb["in"] or opp_sb["out"]:
            parts.append(_sb_list_html(opp_sb["in"],  "IN",  "#f58231"))
            parts.append(_sb_list_html(opp_sb["out"], "OUT", "#8a9aaa"))
        else:
            parts.append(
                '<span style="color:#8a9aaa; font-style:italic;">'
                'Opponent guides found but no sideboard plan detected in comments.</span><br>'
            )

    return "".join(parts)
