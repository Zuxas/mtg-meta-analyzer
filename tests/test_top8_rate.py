"""Top-8 rate must be computed over the appearances where top 8 was observable.

Found by driving the analysis layer against a POPULATED database: an
archetype came back with "top8_rate": 1.422 -- a rate of 142%, which
meta_table.py renders verbatim as "142.2%" and chart_canvas.py plots as a
"Top 8 Rate %" series.

Mechanism. _fetch_appearances defines max_placement as the MAX RECORDED
placement in an event, so an event whose published field stops short of 8th
(MTGO leagues publish only 5-0 decks; partial paper coverage) has
max_placement < 8. The old code counted:

    numerator   = appearances with placement <= 8        (ALL rows)
    denominator = appearances with max_placement >= 8    (ELIGIBLE rows only)

Two different sets, so the ratio was not a rate at all. Three failure modes,
all reproduced below:

  * ABOVE 100%  -- partial events add to the numerator but not the
    denominator (test_rate_can_never_exceed_one).
  * INFLATED    -- a mixed field reported 92% where the truth was 50%
    (test_partial_events_do_not_inflate_a_mixed_field).
  * A FALSE 0%  -- an archetype seen only in partial events got
    denominator 0, and the `else 0.0` fallback reported "0% top-8 rate" for
    a deck that had made the cut in every event it played. That is the worst
    of the three: it reads as a real measurement of total failure
    (test_unmeasurable_reads_unknown_not_zero).

Fix: restrict the numerator to the same eligible set, and report None --
already the established "unknown" sentinel here, emitted by the
match-derived paths at win_rates.py:503 and :624 and handled by every
display site -- when nothing was measurable.

An event that stops short of 8th cannot be evidence either way: every deck
recorded in it made "top 8" trivially, so including it in both halves would
drag every archetype's rate toward 100% instead.
"""
import pytest

from analysis.win_rates import _aggregate_appearances


def _row(placement, max_placement, event_id, event_type="mtgo_challenge_32"):
    """One appearance. max_placement = deepest placement RECORDED in that
    event, which is what _fetch_appearances computes via a MAX subquery."""
    return {"placement": placement, "max_placement": max_placement,
            "event_id": event_id, "event_type": event_type}


def _full_event(event_id, size=16, arch_places=(1, 9)):
    """An event with `size` decks recorded; our archetype took arch_places."""
    return [_row(p, size, event_id) for p in arch_places]


# ---------------------------------------------------------------------------
# The three failure modes
# ---------------------------------------------------------------------------

def test_rate_can_never_exceed_one():
    """The headline symptom: 142% top-8 rate.

    Three fully-recorded events (our archetype misses the cut in each) plus
    ten partial events it "won" -- the partials pile into the numerator
    while only the three fulls count in the denominator.
    """
    rows  = [_row(12, 16, 100 + e) for e in range(3)]      # eligible, not top 8
    rows += [_row(1, 4, 200 + e) for e in range(10)]        # partial, trivially "top 8"

    rate = _aggregate_appearances(rows)["top8_rate"]
    assert rate is None or rate <= 1.0, (
        f"top8_rate={rate} is above 100%, which meta_table.py renders as "
        f"{(rate or 0)*100:.1f}%"
    )


def test_partial_events_do_not_inflate_a_mixed_field():
    """True rate 50%, previously reported 92%.

    3 full events x 16 recorded decks: our archetype takes every placement,
    so exactly half of those 48 appearances are genuine top 8s. The 20
    partial-event appearances are unmeasurable and must not count.
    """
    rows  = [_row(p, 16, 100 + e) for e in range(3) for p in range(1, 17)]
    rows += [_row(p, 4, 200 + e) for e in range(5) for p in (1, 2, 3, 4)]

    s = _aggregate_appearances(rows)
    assert s["top8_rate"] == pytest.approx(0.5), (
        f"expected the 24/48 genuine top 8s = 0.5, got {s['top8_rate']}"
    )


def test_unmeasurable_reads_unknown_not_zero():
    """Seen only in partial events -> unknown, not a confident 0%.

    This archetype made top 4 in all five events it entered. Reporting "0%
    top-8 rate" for it is not a rounding quibble, it is backwards.
    """
    rows = [_row(p, 4, e) for e in range(1, 6) for p in (1, 2, 3, 4)]

    s = _aggregate_appearances(rows)
    assert s["top8_rate"] is None, (
        f"unmeasurable top-8 rate should be None, got {s['top8_rate']!r} "
        f"(rendered as {(s['top8_rate'] or 0)*100:.0f}%)"
    )


# ---------------------------------------------------------------------------
# The cases that already worked must keep working
# ---------------------------------------------------------------------------

def test_fully_recorded_event_is_unchanged():
    """A 32-deck event with the full field recorded: 8 of 32 are top 8.

    This is the path that was always correct, pinned so the fix cannot
    "solve" the bug by degrading the normal case.
    """
    rows = [_row(p, 32, 300) for p in range(1, 33)]
    assert _aggregate_appearances(rows)["top8_rate"] == pytest.approx(0.25)


def test_exactly_eight_recorded_counts_as_measurable():
    """Boundary: max_placement == 8 is eligible (>= 8, not > 8).

    An 8-deck field genuinely measures top-8 conversion -- everyone in it
    made top 8 and that is a true 100%, unlike a 4-deck field.
    """
    rows = [_row(p, 8, 400) for p in range(1, 9)]
    assert _aggregate_appearances(rows)["top8_rate"] == pytest.approx(1.0)


def test_eligible_count_still_reports_the_measurable_field():
    """top8_eligible keeps its meaning -- the fix moves the NUMERATOR onto
    the eligible set, it does not redefine the denominator."""
    rows  = [_row(p, 16, 100) for p in range(1, 17)]   # 16 eligible
    rows += [_row(1, 4, 200)]                          # 1 not eligible
    s = _aggregate_appearances(rows)
    assert s["top8_eligible"] == 16
    assert s["appearances"] == 17, "unrelated totals must not shrink"


def test_none_is_a_sentinel_display_sites_already_handle():
    """None is not a new contract: the match-derived standings path already
    emits top8_rate=None, and meta_table renders it as an em dash.

    Pinned because a future 'simplification' back to 0.0 would silently
    restore the false-zero, and 0.0 is indistinguishable from a real 0%.
    """
    import inspect
    import analysis.win_rates as wr

    src = inspect.getsource(wr)
    assert '"top8_rate":         None' in src, (
        "the match-derived paths no longer emit None -- if that sentinel is "
        "gone, this fix needs revisiting alongside its display sites"
    )


# ---------------------------------------------------------------------------
# Regression introduced BY the fix above, caught before it reached a user
# ---------------------------------------------------------------------------

def test_standings_sort_survives_a_none_rate():
    """get_meta_standings sorts on (avg_points, top8_rate).

    Making top8_rate None (correct -- see above) put a None into that sort
    key. Python only compares the second element when the first TIES, so this
    raises TypeError exactly when two archetypes share an avg_points, which is
    common since it is a rounded average. The exception escapes
    get_meta_standings and would take out the Dashboard, Charts and the CLI
    together.

    Reproduces the precise shape: equal avg_points, one measurable rate and
    one not.
    """
    def mk(name, rows):
        d = _aggregate_appearances(rows)
        d["archetype"] = name
        return d

    measurable = mk("Measurable", [_row(1, 16, 1)])
    unmeasurable = mk("Unmeasurable", [_row(1, 4, 2)])
    assert measurable["avg_points"] == unmeasurable["avg_points"], (
        "this test only bites on an avg_points tie -- the inputs drifted")
    assert measurable["top8_rate"] is not None
    assert unmeasurable["top8_rate"] is None

    # The exact sort key used in get_meta_standings.
    key = lambda s: (s["avg_points"],
                     s["top8_rate"] if s["top8_rate"] is not None else -1.0)
    ordered = sorted([unmeasurable, measurable], key=key, reverse=True)
    assert [d["archetype"] for d in ordered] == ["Measurable", "Unmeasurable"], (
        "a measured top-8 rate should outrank an unmeasurable one on a tie")


def test_the_real_standings_sort_key_is_none_safe():
    """Pins the guard in the source, so a refactor cannot drop it and
    reintroduce a crash that only fires on a tie."""
    import inspect
    import analysis.win_rates as wr

    src = inspect.getsource(wr)
    assert 'results.sort(key=lambda s: (s["avg_points"],' in src
    assert 's["top8_rate"] if s["top8_rate"] is not None' in src, (
        "the standings sort no longer guards None -- it will raise TypeError "
        "whenever two archetypes tie on avg_points")
