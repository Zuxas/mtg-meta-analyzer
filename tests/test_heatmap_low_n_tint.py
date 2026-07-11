"""Tests for the low-N matchup-cell tint (GR-8, Wave B item 6 of
harness/handoffs/mta-gui-polish-2026-07-10.md).

GR-8 gate:
  "two cells at the same WR with N=1 vs N>=20 are visibly distinct (unit
  test on the tint function's returned QColor alpha + screenshot); legend
  gains a low-N key."

This file gates four things:
  1. gui/theme.py::winrate_bg_n(winrate, n) -- a new ADDITIVE helper (does
     not modify winrate_bg()/winrate_fg()) whose returned QColor alpha
     differs by a stated threshold between N=1 and N>=20 at the same WR.
  2. gui/tabs/heatmap_tab.py wires real matchup cells through
     winrate_bg_n() (not the old flat winrate_bg()), and always puts the
     match count N in the cell tooltip (not just when N is truthy).
  3. HeatmapTab's legend gains a low-N key entry.
  4. The alpha difference actually RENDERS as different pixels (not just a
     different QColor object that Qt might silently ignore) -- verified by
     grabbing the real table viewport and sampling pixel color at the two
     same-WR cells. This closes a gap a pure "read back the QColor I just
     set" test can't: this table's own comment elsewhere notes
     setBackground() is fragile under the app's global stylesheet, so
     confirming actual rendered pixels differ (not just the stored QColor)
     is the literal "screenshot-verifiable" half of the gate. A saved PNG
     of this exact render is written to
     C:/temp/gr8_lowN_render_check.png (same convention as the handoff's
     own Verification runbook screenshots) for visual inspection.

No pytest-qt plugin is installed in this environment -- these tests follow
the established offscreen-Qt pattern (QT_QPA_PLATFORM=offscreen env
fixture + QApplication.instance()) from tests/test_heatmap_toolbar_groups.py
/ tests/test_heatmap_header_elide.py. The synthetic-matrix + direct
_draw_grid() call pattern is lifted from
tests/test_heatmap_header_elide.py::_make_loaded_tab.
"""
import os
import time

import pytest

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# Stated threshold for "visibly distinct" alpha (out of 0-255). The
# implementation's ramp is WR-independent (LOW_N_ALPHA_FLOOR at n=0 up to
# a flat 255 at n>=LOW_N_THRESHOLD=20), so the real measured delta for
# N=1 vs N=20 is a constant ~176 regardless of win rate -- 40 leaves
# generous headroom while still being an unmistakable, non-noise-level
# difference.
ALPHA_DELTA_THRESHOLD = 40

# Stated threshold for "visibly distinct" on the RENDERED pixel (0-255 per
# channel, after alpha-compositing over the panel background) -- verified
# empirically via a real viewport grab (see
# test_matchup_cells_render_as_different_pixels below). The green channel
# is the most reliable signal for this palette's green-tinted bands (the
# ones exercised here); a plain per-channel absolute-difference floor
# would be too strict for the red/grey bands where the base color itself
# has a smaller green component, so this threshold is checked against
# whichever channel has the largest swing between the two sampled cells.
PIXEL_CHANNEL_DELTA_THRESHOLD = 10


# ---------------------------------------------------------------------------
# 1. Pure unit tests on gui.theme.winrate_bg_n
# ---------------------------------------------------------------------------

def test_winrate_bg_n_returns_qcolor(app):
    import gui.theme as theme

    c = theme.winrate_bg_n(0.55, 20)
    assert isinstance(c, QColor)


@pytest.mark.parametrize("wr", [0.35, 0.5, 0.55, 0.65, 1.0])
def test_low_n_alpha_visibly_lower_than_high_n_at_same_winrate(app, wr):
    """Same win rate, N=1 vs N=20: alpha must differ by at least
    ALPHA_DELTA_THRESHOLD, and the low-N cell must be the more
    transparent (lower-alpha) one -- never the reverse."""
    import gui.theme as theme

    low_n_color  = theme.winrate_bg_n(wr, 1)
    high_n_color = theme.winrate_bg_n(wr, 20)

    assert high_n_color.alpha() - low_n_color.alpha() >= ALPHA_DELTA_THRESHOLD, (
        f"wr={wr}: N=1 alpha={low_n_color.alpha()}, N=20 alpha={high_n_color.alpha()} "
        f"-- delta {high_n_color.alpha() - low_n_color.alpha()} below threshold "
        f"{ALPHA_DELTA_THRESHOLD}"
    )


def test_zero_n_is_never_fully_transparent(app):
    """A cell with no logged matches at all (n=0) is the maximally-uncertain
    case -- it should still render some color (a floor alpha), not vanish
    entirely, so an empty cell and a 0-match cell remain visually distinct
    concepts."""
    import gui.theme as theme

    c = theme.winrate_bg_n(0.5, 0)
    assert c.alpha() == theme.LOW_N_ALPHA_FLOOR
    assert c.alpha() > 0


def test_high_n_alpha_approaches_full_opacity(app):
    """A very well-supported cell (N=200) should render at or very near
    full opacity, same visual weight as the un-modulated winrate_bg()."""
    import gui.theme as theme

    c = theme.winrate_bg_n(0.55, 200)
    assert c.alpha() >= 230


def test_winrate_bg_n_hue_matches_winrate_bg(app):
    """winrate_bg_n() must reuse the SAME color bands as winrate_bg() --
    only alpha should differ, never the RGB hue, at any N."""
    import gui.theme as theme

    for wr in (0.62, 0.57, 0.50, 0.42, 0.30):
        base = theme.winrate_bg(wr)
        tinted = theme.winrate_bg_n(wr, 20)
        assert (tinted.red(), tinted.green(), tinted.blue()) == (
            base.red(), base.green(), base.blue(),
        )


# ---------------------------------------------------------------------------
# Additive-only regression guard: winrate_bg()/winrate_fg() untouched.
# ---------------------------------------------------------------------------

def test_winrate_bg_and_fg_untouched(app):
    """Pin winrate_bg()/winrate_fg()'s existing outputs (including their
    always-255 alpha) so this item's addition of winrate_bg_n() can never
    have silently modified them -- ADDITIVE-ONLY rule."""
    import gui.theme as theme

    assert theme.winrate_bg(0.60) == QColor(12, 50, 22)
    assert theme.winrate_fg(0.60) == QColor(50, 220, 90)
    assert theme.winrate_bg(0.60).alpha() == 255
    assert theme.winrate_fg(0.60).alpha() == 255


# ---------------------------------------------------------------------------
# 2. Legend gains a low-N key
# ---------------------------------------------------------------------------

def test_legend_contains_low_n_key(app):
    from gui.tabs.heatmap_tab import HeatmapTab

    tab = HeatmapTab()
    key_widget = tab.findChild(QWidget, "heatmap_legend_low_n_key")
    assert key_widget is not None, "no low-N legend key found in widget tree"

    key_label = tab.findChild(QLabel, "heatmap_legend_low_n_label")
    assert key_label is not None
    assert "low n" in key_label.text().lower() or "low sample" in key_label.text().lower()


# ---------------------------------------------------------------------------
# 3. Real matchup cells wired through winrate_bg_n() + always show N
# ---------------------------------------------------------------------------

_ARCHS = ["Izzet Prowess", "Mono Red Aggro", "Boros Aggro"]


def _synthetic_matrix_with_varied_n():
    """Izzet Prowess vs Mono Red Aggro: same WR as vs Boros Aggro, but N=1
    vs N=50 -- the literal 'low-N vs robust cell at the same WR' scenario
    from the handoff. A third cell (Mono Red Aggro vs Boros Aggro) carries
    N=0 to exercise the "no matches logged yet" tooltip path."""
    return {
        "Izzet Prowess": {
            "Mono Red Aggro": {"winrate": 0.55, "matches": 1},
            "Boros Aggro":    {"winrate": 0.55, "matches": 50},
        },
        "Mono Red Aggro": {
            "Izzet Prowess": {"winrate": 0.45, "matches": 1},
            "Boros Aggro":   {"winrate": 0.50, "matches": 0},
        },
        "Boros Aggro": {
            "Izzet Prowess":  {"winrate": 0.45, "matches": 50},
            "Mono Red Aggro": {"winrate": 0.50, "matches": 0},
        },
    }


def _make_loaded_tab(app):
    """Build a HeatmapTab, skip the GR-4 auto-load path (real workers are
    out of scope here), show it inside a QMainWindow, then draw the
    synthetic matrix directly via _draw_grid() -- mirrors
    tests/test_heatmap_header_elide.py::_make_loaded_tab."""
    from gui.tabs.heatmap_tab import HeatmapTab

    tab = HeatmapTab()
    tab._hydrated_state = True  # skip sticky-state hydrate + GR-4 auto-load

    win = QMainWindow()
    win.setCentralWidget(tab)
    win.resize(1400, 900)
    win.show()
    for _ in range(3):
        app.processEvents()

    tab._source_map = {}
    tab._draw_grid(_synthetic_matrix_with_varied_n(), _ARCHS,
                    total_archetypes=len(_ARCHS), fmt="standard")
    for _ in range(3):
        app.processEvents()

    return win, tab


def _drain_and_close(app, win, tab):
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and tab._worker is not None:
        app.processEvents()
        time.sleep(0.02)
    tab.cleanup()
    win.close()


def test_matchup_cells_use_winrate_bg_n_not_flat_winrate_bg(app):
    """Izzet Prowess vs Mono Red Aggro (N=1) and vs Boros Aggro (N=50) share
    the identical 55% win rate -- their rendered cell backgrounds must
    differ in alpha by at least ALPHA_DELTA_THRESHOLD, and must match
    theme.winrate_bg_n()'s own output exactly (proves the grid is wired
    through the new helper, not still calling the flat winrate_bg())."""
    import gui.theme as theme
    from gui.tabs.heatmap_tab import _MatchupTableWidget

    win, tab = _make_loaded_tab(app)
    try:
        tbl = tab._grid_container.findChild(_MatchupTableWidget)
        assert tbl is not None

        row_izzet = _ARCHS.index("Izzet Prowess")
        col_mono  = _ARCHS.index("Mono Red Aggro") + 1  # +1 for Overall col
        col_boros = _ARCHS.index("Boros Aggro") + 1

        low_n_item  = tbl.item(row_izzet, col_mono)
        high_n_item = tbl.item(row_izzet, col_boros)
        assert low_n_item is not None and high_n_item is not None

        low_n_alpha  = low_n_item.background().color().alpha()
        high_n_alpha = high_n_item.background().color().alpha()

        assert high_n_alpha - low_n_alpha >= ALPHA_DELTA_THRESHOLD, (
            f"N=1 alpha={low_n_alpha}, N=50 alpha={high_n_alpha} at the same "
            f"55% WR -- delta {high_n_alpha - low_n_alpha} below threshold "
            f"{ALPHA_DELTA_THRESHOLD}"
        )

        # Cross-check against the pure helper directly -- confirms the grid
        # is actually calling winrate_bg_n(), not independently reinventing
        # some other alpha scheme that happens to also differ.
        assert low_n_item.background().color() == theme.winrate_bg_n(0.55, 1)
        assert high_n_item.background().color() == theme.winrate_bg_n(0.55, 50)
    finally:
        _drain_and_close(app, win, tab)


def _sample_bg_color(img, rect):
    """Sample the cell's background fill color, avoiding the centered
    percentage-text glyph ("55%") painted on top of it. The text is
    horizontally AND vertically centered in the cell, so a small cluster
    of points hugging the left edge (well inside the cell, clear of the
    gridline) lands on background regardless of exact font/DPI/stylesheet
    state -- and taking the MODE across several such points (rather than
    one single pixel) rejects any stray anti-aliased edge pixel. This is
    intentionally more robust than reading the exact rect center, which
    was observed to occasionally land on a text-colored pixel when this
    test ran after other test files that mutate the shared QApplication's
    global font/stylesheet state."""
    from collections import Counter

    x = rect.left() + max(2, min(6, rect.width() // 10))
    ys = [rect.top() + int(rect.height() * f) for f in (0.2, 0.35, 0.5, 0.65, 0.8)]
    samples = [
        (img.pixelColor(x, y).red(), img.pixelColor(x, y).green(),
         img.pixelColor(x, y).blue())
        for y in ys if rect.top() <= y < rect.bottom()
    ]
    return Counter(samples).most_common(1)[0][0]  # (r, g, b)


def test_matchup_cells_render_as_different_pixels(app):
    """The QColor-alpha assertions above prove the tint FUNCTION returns
    different values and that the grid is WIRED to it -- but a table whose
    own comments elsewhere note that `setBackground()` is fragile under
    this app's global stylesheet (`gui/tabs/heatmap_tab.py::_draw_grid`:
    "The global stylesheet sets QTableWidget::item { padding } which
    prevents setBackground() from working... apply via palette instead")
    could in principle still paint both cells identically despite the
    QColor objects differing. Close that gap by grabbing the REAL
    viewport pixels at both cell centers and asserting they differ by a
    stated per-channel threshold -- this is the actual "screenshot-
    verifiable" claim in the gate, exercised as a pixel read instead of a
    human eyeballing a PNG."""
    from gui.tabs.heatmap_tab import _MatchupTableWidget

    win, tab = _make_loaded_tab(app)
    try:
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        row_izzet = _ARCHS.index("Izzet Prowess")
        col_mono  = _ARCHS.index("Mono Red Aggro") + 1   # N=1
        col_boros = _ARCHS.index("Boros Aggro") + 1      # N=50

        low_n_item  = tbl.item(row_izzet, col_mono)
        high_n_item = tbl.item(row_izzet, col_boros)
        rect_low  = tbl.visualItemRect(low_n_item)
        rect_high = tbl.visualItemRect(high_n_item)
        assert not rect_low.isEmpty() and not rect_high.isEmpty(), (
            "cell rects are empty -- table geometry never settled"
        )

        img = tbl.viewport().grab().toImage()
        low_rgb  = _sample_bg_color(img, rect_low)
        high_rgb = _sample_bg_color(img, rect_high)

        channel_deltas = [
            abs(high_rgb[0] - low_rgb[0]),
            abs(high_rgb[1] - low_rgb[1]),
            abs(high_rgb[2] - low_rgb[2]),
        ]
        max_delta = max(channel_deltas)
        assert max_delta >= PIXEL_CHANNEL_DELTA_THRESHOLD, (
            f"rendered N=1 cell RGB={low_rgb} vs N=50 cell RGB={high_rgb} -- "
            f"max channel delta {max_delta} below threshold "
            f"{PIXEL_CHANNEL_DELTA_THRESHOLD} (alpha may not be rendering)"
        )
        # The higher-N cell must render CLOSER to the un-modulated base
        # color (theme.winrate_bg(0.55) == QColor(14, 40, 20)) than the
        # low-N cell does -- i.e. the direction of the shift is "low-N
        # fades toward the panel background", not an arbitrary difference.
        import gui.theme as theme
        base = theme.winrate_bg(0.55)
        high_dist = abs(high_rgb[1] - base.green())
        low_dist  = abs(low_rgb[1]  - base.green())
        assert high_dist < low_dist, (
            f"N=50 cell (green={high_rgb[1]}) should render closer to "
            f"the un-modulated base green={base.green()} than the N=1 cell "
            f"(green={low_rgb[1]}) does"
        )

        # Save a copy of this exact render for visual/screenshot review --
        # written to C:/temp (same convention as the handoff's own
        # Verification runbook screenshots, e.g. C:/temp/mta_0*.png), NOT
        # into the repo working tree, so it never needs a git add.
        try:
            os.makedirs("C:/temp", exist_ok=True)
            img.save("C:/temp/gr8_lowN_render_check.png")
        except Exception:
            pass  # best-effort -- saving a debug PNG must never fail the test
    finally:
        _drain_and_close(app, win, tab)


def test_matchup_cell_tooltip_always_includes_match_count(app):
    """N must appear in the tooltip for every real matchup cell -- including
    the N=0 case (no matches logged yet), which the old code silently
    omitted (guarded by `if matches:`)."""
    from gui.tabs.heatmap_tab import _MatchupTableWidget

    win, tab = _make_loaded_tab(app)
    try:
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        row_izzet = _ARCHS.index("Izzet Prowess")
        col_mono  = _ARCHS.index("Mono Red Aggro") + 1
        col_boros = _ARCHS.index("Boros Aggro") + 1

        low_n_tip  = tbl.item(row_izzet, col_mono).toolTip()
        high_n_tip = tbl.item(row_izzet, col_boros).toolTip()
        assert "Matches logged: 1" in low_n_tip
        assert "Matches logged: 50" in high_n_tip
        # Low-N cell gets an explicit low-confidence callout; robust cell
        # does not.
        assert "low sample size" in low_n_tip.lower()
        assert "low sample size" not in high_n_tip.lower()

        row_mono = _ARCHS.index("Mono Red Aggro")
        col_boros2 = _ARCHS.index("Boros Aggro") + 1
        zero_n_tip = tbl.item(row_mono, col_boros2).toolTip()
        assert "Matches logged: 0" in zero_n_tip
        assert "low sample size" in zero_n_tip.lower()
    finally:
        _drain_and_close(app, win, tab)
