"""Conversion ratio + the Cascade status (CHAPIN_METRICS.md Task 2, rule IC-02).

conversion = (share of top finishes) / (share of field). Near 1.00 means the
deck's presence in the top cut is explained by how much it is played, not by
how good it is. Field AND top cut come from the `matches` table only -- the
`decks` table is top-cut biased and its archetype labels come from a
different scraper, so mixing the two produced artifacts.
"""
import os
import sqlite3
from datetime import date

import pytest

from analysis.wilson import wilson_bounds


# ---------------------------------------------------------------------------
# Fixture: one 16-player Modern event, 4 swiss rounds, deterministic results
# ---------------------------------------------------------------------------

def _mk_con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE matches (
        id INTEGER PRIMARY KEY, event_id TEXT, round INTEGER,
        player1 TEXT, player2 TEXT, player1_arch TEXT, player2_arch TEXT,
        winner_arch TEXT, result TEXT, format TEXT, event_date TEXT, source TEXT)""")
    return con


def _seed_event(con, eid, fmt, when, n_players=16, arch_of=None):
    """Players p00..pNN in a full round robin where the lower index always
    wins, so wins(p_i) = n - 1 - i: a strict order with no ties, and the
    top-8 by wins is exactly p00..p07. (The module ignores `round`.)"""
    from itertools import combinations
    arch_of = arch_of or (lambda i: "Boros Energy" if i < 8 else "Jeskai Blink")
    rows = []
    for r, (lo, hi) in enumerate(combinations(range(n_players), 2), start=1):
        rows.append((eid, r, f"p{lo:02d}", f"p{hi:02d}", arch_of(lo), arch_of(hi),
                     arch_of(lo), "player1", fmt, when, "mtgmelee"))
    con.executemany("INSERT INTO matches (event_id, round, player1, player2, player1_arch, "
                    "player2_arch, winner_arch, result, format, event_date, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)


def test_conversion_field_and_top_cut_from_matches_only():
    from analysis.conversion import conversion_by_archetype
    con = _mk_con()
    _seed_event(con, "ev1", "modern", "2026-09-01")
    out = conversion_by_archetype("modern", "2026-08-01", "2026-09-30", con=con)

    assert set(out) == {"Boros Energy", "Jeskai Blink"}
    be, jb = out["Boros Energy"], out["Jeskai Blink"]
    assert be["field_share"] == pytest.approx(0.5) and jb["field_share"] == pytest.approx(0.5)
    assert be["events"] == 1 and jb["events"] == 1
    assert be["events_total"] == 1
    # lower-indexed players always win, so the top 8 by wins are p00..p07 == all Boros
    assert be["top_share"] == pytest.approx(1.0) and jb["top_share"] == pytest.approx(0.0)
    assert be["conversion"] == pytest.approx(2.0) and jb["conversion"] == pytest.approx(0.0)
    assert be["match_wr"] > 0.5 > jb["match_wr"]
    assert be["matches"] + jb["matches"] == 2 * con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    lo, hi = wilson_bounds(round(be["match_wr"] * be["matches"]), be["matches"])
    assert (be["ci_low"], be["ci_high"]) == pytest.approx((lo, hi))


def test_conversion_excludes_small_events_and_other_formats_and_window():
    from analysis.conversion import conversion_by_archetype
    con = _mk_con()
    _seed_event(con, "big", "modern", "2026-09-01")
    _seed_event(con, "small", "modern", "2026-09-02", n_players=8)               # < min_players
    _seed_event(con, "std", "standard", "2026-09-03")                            # other format
    _seed_event(con, "old", "modern", "2026-01-15")                              # outside window
    out = conversion_by_archetype("modern", "2026-08-01", "2026-09-30", con=con)
    assert out["Boros Energy"]["events"] == 1
    assert sum(v["field_share"] for v in out.values()) == pytest.approx(1.0)


def test_conversion_window_includes_slash_dated_rows():
    """The reference script filtered `event_date LIKE '____-__-__'`, silently
    dropping every dd/mm/yy row. The port normalizes instead."""
    from analysis.conversion import conversion_by_archetype
    con = _mk_con()
    _seed_event(con, "iso", "standard", "2026-09-01")
    _seed_event(con, "slash", "standard", "05/09/26")          # 2026-09-05, dd/mm/yy
    out = conversion_by_archetype("standard", "2026-08-01", "2026-09-30", con=con)
    assert out["Boros Energy"]["events"] == 2


def test_conversion_default_until_is_open_ended_and_rows_without_arch_are_skipped():
    from analysis.conversion import conversion_by_archetype
    con = _mk_con()
    _seed_event(con, "ev", "modern", date.today().isoformat(),
                arch_of=lambda i: None if i == 0 else "Boros Energy")
    out = conversion_by_archetype("modern", "2026-01-01", con=con)
    assert set(out) == {"Boros Energy"}
    assert out["Boros Energy"]["field_share"] == pytest.approx(1.0)


def test_conversion_empty_returns_empty_dict():
    from analysis.conversion import conversion_by_archetype
    assert conversion_by_archetype("modern", "2026-01-01", con=_mk_con()) == {}


# ---------------------------------------------------------------------------
# classify_status: the new Cascade axis, old behaviour untouched
# ---------------------------------------------------------------------------

def test_classify_status_unchanged_without_conversion():
    from analysis.meta_scoring import classify_status
    assert classify_status(0.10, 0.55)[0] == "Pillar"
    assert classify_status(0.10, 0.45)[0] == "Trap"
    assert classify_status(0.01, 0.55)[0] == "Underplayed"
    assert classify_status(0.05, 0.50)[0] == "Fringe"


def test_classify_status_cascade_when_presence_is_explained_by_popularity():
    from analysis.meta_scoring import classify_status
    label, color = classify_status(0.08, 0.50, conversion=0.98)
    assert label == "Cascade" and color == "#e67e22"
    # boundaries: share >= 3%, conversion <= 1.02, 48% <= WR <= 52%
    assert classify_status(0.03, 0.48, conversion=1.02)[0] == "Cascade"
    assert classify_status(0.029, 0.50, conversion=0.98)[0] != "Cascade"
    assert classify_status(0.08, 0.50, conversion=1.03)[0] != "Cascade"
    assert classify_status(0.08, 0.53, conversion=0.98)[0] != "Cascade"
    assert classify_status(0.08, 0.47, conversion=0.98)[0] != "Cascade"
    # a real Pillar stays a Pillar even if conversion is supplied
    assert classify_status(0.10, 0.55, conversion=1.30)[0] == "Pillar"
    # conversion=None behaves exactly like the two-arg call
    assert classify_status(0.08, 0.50, conversion=None)[0] == "Fringe"


def test_score_standings_uses_conversions_when_supplied():
    from analysis.meta_scoring import score_standings
    standings = [{"archetype": "Jeskai Blink", "appearances": 50, "est_match_winpct": 0.50},
                 {"archetype": "Boros Energy", "appearances": 50, "est_match_winpct": 0.55}]
    conversions = {"Jeskai Blink": {"conversion": 0.71, "match_wr": 0.505},
                   "Boros Energy": {"conversion": 1.30, "match_wr": 0.535}}
    score_standings(standings, {}, conversions=conversions)
    by = {s["archetype"]: s for s in standings}
    assert by["Jeskai Blink"]["status"] == "Cascade"
    assert by["Jeskai Blink"]["conversion"] == pytest.approx(0.71)
    assert by["Boros Energy"]["status"] == "Pillar"
    # old call signature still works and never yields Cascade
    score_standings(standings, {})
    assert by["Jeskai Blink"]["status"] == "Fringe"


# ---------------------------------------------------------------------------
# Fixture target from the doc: Modern 2025-10-01..2026-06-30 on the live DB
# ---------------------------------------------------------------------------

@pytest.mark.live_db   # reads the real DB by design (guarded otherwise, see conftest)
def test_reference_output_modern_2025_10_to_2026_06():
    """The doc's table was computed on the 2026-09-19 DB (106 qualifying
    events). The DB is live -- today's melee re-scrape already moved it to
    112 events (Boros 9.55% / 11.94% / 1.25) -- so this pins the port to the
    doc within a scrape-drift tolerance rather than to the digit. The port
    was verified digit-for-digit against scripts/data_health_report.py on
    the same DB on 2026-09-21; that is the real equivalence check."""
    from db.database import DB_PATH
    if not os.path.exists(DB_PATH):
        pytest.skip("live DB not present")
    from analysis.conversion import conversion_by_archetype
    out = conversion_by_archetype("modern", "2025-10-01", "2026-06-30")
    if not out:
        pytest.skip("no Modern match rows in the reference window")

    expected = {  # archetype: (field%, top8%, conv, matchWR%, n) per the doc
        "Boros Energy":      (9.63, 12.50, 1.30, 53.5, 8074),
        "Jeskai Blink":      (8.27,  5.90, 0.71, 50.5, 6746),
        "Izzet Prowess":     (8.04,  7.90, 0.98, 49.3, 6125),
        "Izzet Affinity":    (7.00,  9.20, 1.31, 52.6, 5631),
        # Re-pinned 2026-10-02 after the Melee historical relabel (docs/reports/2026-10-02-melee-relabel.md):
        # fuzzy-guessed rows left these two labels ('Mono-Green Broodscale' was stored as Mono Red Aggro,
        # 'W-U-R-G Domain Zoo' as Domain Ramp). Pre-relabel values: (5.30, 7.19, 1.36, 52.3, 3511) and
        # (3.06, 4.48, 1.47, 49.7, 2110); the test still passes on the pre-relabel backup.
        "Mono Red Aggro":    (4.37,  5.69, 1.30, 52.2, 2855),
        "Goryo's Vengeance": (5.09,  3.42, 0.67, 49.0, 3999),
        "Amulet Titan":      (4.02,  2.36, 0.59, 51.6, 3871),
        "Domain Ramp":       (0.70,  1.12, 1.59, 48.3,  484),
    }
    for arch, (fs, ts, conv, wr, n) in expected.items():
        r = out[arch]
        assert r["field_share"] * 100 == pytest.approx(fs, abs=0.25), arch
        assert r["top_share"] * 100 == pytest.approx(ts, abs=0.75), arch
        assert r["conversion"] == pytest.approx(conv, abs=0.10), arch
        assert r["match_wr"] * 100 == pytest.approx(wr, abs=0.3), arch
        assert n <= r["matches"] <= n * 1.05, arch          # rows only get added
        assert 0.0 <= r["ci_low"] <= r["match_wr"] <= r["ci_high"] <= 1.0, arch
    assert out["Boros Energy"]["events_total"] >= 106

    from analysis.meta_scoring import classify_status
    flagged = {a for a, r in out.items()
               if classify_status(r["field_share"], r["match_wr"], conversion=r["conversion"])[0] == "Cascade"}
    # 'Domain Zoo' joined after the 2026-10-02 relabel moved the fuzzy 'Domain Ramp' rows to it.
    assert flagged == {"Jeskai Blink", "Izzet Prowess", "Goryo's Vengeance", "Amulet Titan", "Domain Zoo"}


# ---------------------------------------------------------------------------
# Dashboard: the Status cell explains the conversion axis
# ---------------------------------------------------------------------------

def test_dashboard_status_tooltip_explains_conversion(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from gui.tabs.dashboard import DashboardTab
    tip = DashboardTab._status_tooltip("Cascade", 0.71)
    assert "IC-02" in tip and "0.71" in tip and "top-cut share / field share" in tip
    assert DashboardTab._status_tooltip("Pillar", None) == \
        "High share and high win rate -- the deck to beat."
