"""A format's most-played deck was being labelled "Fringe".

classify_status assigns four labels, and the catch-all was "Fringe". But
three rules all require an EXTREME win rate:

    share >= 5%  and wr >= 54%  -> Pillar
    share >= 5%  and wr <  48%  -> Trap
    share <  3%  and wr >= 54%  -> Underplayed
    everything else             -> Fringe

So a deck with a large share and an ORDINARY win rate -- 48% to 54%, which
is the single most common region of any real metagame -- fell through to
Fringe. The most-played deck in a format at a flat 50% win rate displayed
"Fringe" in the Dashboard's Status column.

This is a bug rather than a taste question, because the code contradicts its
own stated contract in two places:

    analysis/meta_scoring.py:12  "Fringe  — low share, middling win rate"
    gui/tabs/dashboard.py:496    "Fringe  (grey)  Low share, middling win rate"

Both define Fringe as LOW SHARE. The code returned it for high share. The
taxonomy simply had a hole where high-share/ordinary-WR should have been,
and that cell fell into the low-share bucket.

Fixed by giving that cell its own label. The WORD is a one-line change
(_ESTABLISHED in meta_scoring) since it is team vocabulary; the behaviour
being tested here is that a major deck is no longer described as marginal.
"""
import pytest

from analysis.meta_scoring import classify_status, _ESTABLISHED, _HIGH_SHARE


def _label(share, wr):
    return classify_status(share, wr)[0]


# ---------------------------------------------------------------------------
# The bug
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("share", [0.05, 0.07, 0.10, 0.15, 0.22, 0.30])
@pytest.mark.parametrize("wr", [0.48, 0.49, 0.50, 0.52, 0.535])
def test_major_deck_with_ordinary_winrate_is_not_called_fringe(share, wr):
    """The whole 24-cell region that used to read "Fringe"."""
    got = _label(share, wr)
    assert got != "Fringe", (
        f"a deck at {share*100:.0f}% of the field and {wr*100:.1f}% win rate "
        f"is not fringe"
    )
    assert got == _ESTABLISHED


def test_the_headline_case():
    """30% of the field at a flat 50% win rate -- the format's defining deck."""
    assert _label(0.30, 0.50) == _ESTABLISHED


def test_fringe_now_matches_its_documented_definition():
    """Both the module docstring and the Dashboard legend define Fringe as
    LOW share. Pin that the label is only used that way."""
    assert _label(0.01, 0.50) == "Fringe"
    assert _label(0.02, 0.50) == "Fringe"
    # just under the high-share line is still legitimately low share
    assert _label(_HIGH_SHARE - 0.001, 0.50) == "Fringe"


# ---------------------------------------------------------------------------
# The three labels that already worked must be untouched
# ---------------------------------------------------------------------------

def test_pillar_unchanged():
    assert _label(0.10, 0.55) == "Pillar"
    assert _label(0.05, 0.54) == "Pillar"


def test_trap_unchanged():
    assert _label(0.10, 0.44) == "Trap"
    assert _label(0.05, 0.479) == "Trap"


def test_underplayed_unchanged():
    assert _label(0.02, 0.58) == "Underplayed"
    assert _label(0.01, 0.54) == "Underplayed"


def test_boundaries_are_exact():
    """The thresholds themselves, so a refactor cannot drift them."""
    assert _label(_HIGH_SHARE, 0.54) == "Pillar"          # >= on both
    assert _label(_HIGH_SHARE, 0.48) == _ESTABLISHED      # 48 is NOT < 48
    assert _label(_HIGH_SHARE, 0.4799) == "Trap"


def test_every_label_carries_a_colour():
    """The Dashboard reads status_color straight from here, so a label with
    no colour would render as whatever the default happens to be."""
    seen = {}
    for share in (0.001, 0.02, 0.04, 0.05, 0.10, 0.30):
        for wr in (0.30, 0.44, 0.48, 0.50, 0.54, 0.70):
            label, colour = classify_status(share, wr)
            assert label, f"empty label at {share}/{wr}"
            assert isinstance(colour, str) and colour.startswith("#"), (
                f"{label} has no colour: {colour!r}")
            seen.setdefault(label, colour)
    assert len(seen) == 5, f"expected 5 distinct labels, got {sorted(seen)}"
    assert len(set(seen.values())) == 5, (
        f"two labels share a colour, so they are indistinguishable: {seen}")
