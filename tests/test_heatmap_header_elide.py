"""Tests for gui/tabs/heatmap_tab.py column-header eliding + legend width
fix (GR-2, amended per harness/handoffs/mta-gui-polish-2026-07-10.md
Wave B item 5).

GR-2 gate (amended):
  "with 27 archetypes loaded, no two rendered header strings are
  identical and none clips mid-glyph on EITHER side (programmatic read
  of rendered header text + screenshot); every truncated header carries
  a full-name tooltip; right dead-gutter <= one column width."

Plus the folded-in legend-width defect: HeatmapTab.minimumSizeHint()
must be <= 1180px wide (was ~1660px, driven by the Legend row's
un-wrapped QHBoxLayout -- see tests/test_heatmap_toolbar_groups.py's
docstring for the pre-existing defect this closes).

No pytest-qt plugin is installed in this environment -- these tests
follow the established offscreen-Qt pattern (QT_QPA_PLATFORM=offscreen
env fixture + QApplication.instance() or QApplication([])) from
tests/test_heatmap_toolbar_groups.py / tests/test_gr4_empty_on_open.py.
"""
import time

import pytest

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QMainWindow


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Synthetic 27-archetype fixture -- deliberately includes clusters of
# names sharing a long common prefix (e.g. four "Boros ..." decks) so the
# elide-uniqueness logic is actually stressed, not just exercised on
# already-distinct-looking strings.
# ---------------------------------------------------------------------------

_ARCHETYPES = [
    "Izzet Prowess", "Izzet Pyromancer", "Izzet Phoenix", "Izzet Control",
    "Boros Convoke", "Boros Energy", "Boros Aggro", "Boros Midrange",
    "Azorius Control", "Azorius Tempo", "Azorius Soldiers",
    "Dimir Midrange", "Dimir Control", "Dimir Reanimator",
    "Golgari Midrange", "Golgari Sacrifice",
    "Rakdos Sacrifice", "Rakdos Aggro",
    "Gruul Aggro", "Gruul Ramp",
    "Selesnya Enchantments", "Selesnya Convoke",
    "Orzhov Control", "Orzhov Midrange",
    "Simic Ramp", "Simic Tempo",
    "Mono Red Aggro",
]
assert len(_ARCHETYPES) == 27


def _synthetic_matrix(names):
    matrix = {}
    for a in names:
        matrix[a] = {}
        for b in names:
            if a != b:
                matrix[a][b] = {"winrate": 0.5, "matches": 20}
    return matrix


def _make_loaded_tab(app, width=2200, height=900):
    """Build a HeatmapTab, skip the GR-4 auto-load path (real workers are
    out of scope for this test -- see test_gr4_empty_on_open.py for that
    coverage), show it inside a sized QMainWindow, then draw a synthetic
    27-archetype grid directly via the tab's own _draw_grid()."""
    from gui.tabs.heatmap_tab import HeatmapTab

    tab = HeatmapTab()
    tab._hydrated_state = True  # skip sticky-state hydrate + GR-4 auto-load

    win = QMainWindow()
    win.setCentralWidget(tab)
    win.resize(width, height)
    win.show()
    for _ in range(3):
        app.processEvents()

    tab._source_map = {}
    tab._draw_grid(_synthetic_matrix(_ARCHETYPES), _ARCHETYPES,
                    total_archetypes=len(_ARCHETYPES), fmt="standard")
    for _ in range(3):
        app.processEvents()
    # Column widths are (re)computed on resizeEvent; force one more pass
    # at the final size so measurements below reflect steady state.
    win.resize(width, height)
    for _ in range(3):
        app.processEvents()

    return win, tab


def _drain_and_close(app, win, tab):
    """Same worker-drain pattern as test_gr4_empty_on_open.py /
    test_heatmap_toolbar_groups.py: _hydrated_state=True above means no
    GR-4 worker should ever start, but drain defensively in case a stray
    click/signal started one, since destroying a live QThread wrapper
    aborts the whole pytest process (see gui/worker_utils.py)."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and tab._worker is not None:
        app.processEvents()
        time.sleep(0.02)
    tab.cleanup()
    win.close()


# ---------------------------------------------------------------------------
# Legend-width defect (folded into this item)
# ---------------------------------------------------------------------------

def test_heatmap_tab_minimum_width_fits_1180(app):
    """HeatmapTab.minimumSizeHint().width() must be <= 1180 -- the Legend
    row's un-wrapped QHBoxLayout previously forced ~1660px, which is why
    the tab could never actually honor a ~1200px-wide window (documented
    in tests/test_heatmap_toolbar_groups.py's
    test_toolbar_buttons_reachable_at_1200x700 docstring)."""
    from gui.tabs.heatmap_tab import HeatmapTab

    tab = HeatmapTab()
    hint = tab.minimumSizeHint()
    assert hint.width() <= 1180, (
        f"HeatmapTab.minimumSizeHint().width() = {hint.width()}, "
        "expected <= 1180"
    )


def test_legend_still_shows_all_entries_after_wrap(app):
    """Regression guard: wrapping the legend into a FlowLayout must not
    drop any of the 5 color-scale entries or the source-marker legend."""
    from gui.tabs.heatmap_tab import HeatmapTab
    from PyQt6.QtWidgets import QLabel

    tab = HeatmapTab()
    texts = [lbl.text() for lbl in tab.findChildren(QLabel)]
    assert any(t == "Legend:" for t in texts)
    for expected in (
        "≥60% (Strong Fav)", "55–59% (Favored)",
        "45–54% (Even)", "40–44% (Unfav)", "≤39% (Bad)",
    ):
        assert expected in texts, f"missing legend entry: {expected!r}"
    assert any("real match data" in t for t in texts)


# ---------------------------------------------------------------------------
# GR-2: column-header uniqueness / no mid-glyph clip / tooltips / waste
# ---------------------------------------------------------------------------

def test_headers_unique_with_27_archetypes(app):
    """No two of the 27 rendered column headers may be identical, even
    though several archetype names here share long common prefixes
    (four "Boros ..." decks, three "Izzet ..." decks, etc.) that a plain
    end-ellipsis would collapse together."""
    win, tab = _make_loaded_tab(app)
    try:
        from gui.tabs.heatmap_tab import _MatchupTableWidget
        tbl = tab._grid_container.findChild(_MatchupTableWidget)
        assert tbl is not None
        assert tbl.columnCount() == len(_ARCHETYPES) + 1

        texts = [tbl.horizontalHeaderItem(c).text()
                 for c in range(1, tbl.columnCount())]
        assert len(texts) == len(_ARCHETYPES)
        assert len(texts) == len(set(texts)), (
            f"duplicate header strings among 27 archetypes: {texts}"
        )
    finally:
        _drain_and_close(app, win, tab)


def test_headers_never_clip_mid_glyph(app):
    """Every elided header must be a genuine prefix/suffix split of its
    full archetype name around a single ellipsis (or the full name
    unmodified) -- never an arbitrary/mangled slice."""
    win, tab = _make_loaded_tab(app)
    try:
        from gui.tabs.heatmap_tab import _MatchupTableWidget
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        for col in range(1, tbl.columnCount()):
            full = _ARCHETYPES[col - 1]
            disp = tbl.horizontalHeaderItem(col).text()
            if disp == full:
                continue
            parts = disp.split("…")
            assert len(parts) <= 2, f"malformed elided header: {disp!r}"
            prefix = parts[0]
            suffix = parts[1] if len(parts) == 2 else ""
            assert full.startswith(prefix), (
                f"{disp!r} prefix isn't a real prefix of {full!r}"
            )
            if suffix:
                assert full.endswith(suffix), (
                    f"{disp!r} suffix isn't a real suffix of {full!r}"
                )
    finally:
        _drain_and_close(app, win, tab)


def test_header_text_never_exceeds_its_own_column_width(app):
    """The whole point of eliding to a pixel budget is defeated if the
    RENDERED text still doesn't fit -- QHeaderView's default
    Qt.ElideRight would silently paint its own additional ellipsis over
    ours if the logical string we set is wider than the column, which
    would (a) reintroduce mid-glyph-looking clipping and (b) risk
    collapsing two of our already-disambiguated headers back into the
    same rendered string. Assert the text's own pixel advance fits
    inside its column at three window widths (comfortable / tight /
    scrollbar-fallback), so what tests read via .text() is provably what
    Qt actually paints, not just the string we assigned it."""
    for width in (2200, 1400, 900):
        win, tab = _make_loaded_tab(app, width=width, height=900)
        try:
            from gui.tabs.heatmap_tab import _MatchupTableWidget
            tbl = tab._grid_container.findChild(_MatchupTableWidget)
            fm = QFontMetrics(tbl.horizontalHeader().font())

            for col in range(1, tbl.columnCount()):
                text = tbl.horizontalHeaderItem(col).text()
                advance = fm.horizontalAdvance(text)
                col_w = tbl.columnWidth(col)
                assert advance <= col_w, (
                    f"width={width} col={col} {text!r}: advance {advance}px "
                    f"exceeds column width {col_w}px -- Qt's own ElideRight "
                    "would re-elide this on top of ours"
                )
        finally:
            _drain_and_close(app, win, tab)


def test_every_header_carries_a_full_name_tooltip(app):
    """Every column header's tooltip must be the full, un-elided
    archetype name (not just the ones that got visibly truncated --
    simpler and strictly a superset of the gate's requirement)."""
    win, tab = _make_loaded_tab(app)
    try:
        from gui.tabs.heatmap_tab import _MatchupTableWidget
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        for col in range(1, tbl.columnCount()):
            full = _ARCHETYPES[col - 1]
            item = tbl.horizontalHeaderItem(col)
            assert item.toolTip() == full, (
                f"col {col}: tooltip {item.toolTip()!r} != full name {full!r}"
            )
    finally:
        _drain_and_close(app, win, tab)


def test_right_dead_gutter_at_most_one_column_width(app):
    """With a window wide enough to comfortably fit 27 archetype columns
    at their minimum readable width, the archetype columns must expand
    to consume the viewport -- leaving at most one column's width of
    unused space on the right (here: exactly 0, since the fill algorithm
    distributes the remainder pixel-for-pixel across columns)."""
    win, tab = _make_loaded_tab(app, width=2200, height=900)
    try:
        from gui.tabs.heatmap_tab import _MatchupTableWidget
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        viewport_w = tbl.viewport().width()
        header_len = tbl.horizontalHeader().length()
        waste = viewport_w - header_len
        col_widths = [tbl.columnWidth(c) for c in range(1, tbl.columnCount())]
        one_col = min(col_widths)

        assert waste <= one_col, (
            f"dead gutter {waste}px exceeds one column's width ({one_col}px); "
            f"viewport={viewport_w} header_length={header_len}"
        )
    finally:
        _drain_and_close(app, win, tab)


def test_narrow_window_falls_back_to_min_width_without_crashing(app):
    """Regression/edge-case guard: when the window is too narrow to fit
    all 27 columns even at minimum width, the table should fall back to
    the minimum column width (accepting a horizontal scrollbar) rather
    than shrinking columns to unreadable/zero width or crashing."""
    win, tab = _make_loaded_tab(app, width=900, height=700)
    try:
        from gui.tabs.heatmap_tab import _MatchupTableWidget
        tbl = tab._grid_container.findChild(_MatchupTableWidget)

        col_widths = [tbl.columnWidth(c) for c in range(1, tbl.columnCount())]
        assert all(w >= 40 for w in col_widths), (
            f"columns shrank below a sane readable minimum: {col_widths}"
        )
        # Still must not crash header eliding / stay unique even when
        # squeezed to the minimum.
        texts = [tbl.horizontalHeaderItem(c).text()
                 for c in range(1, tbl.columnCount())]
        assert len(texts) == len(set(texts))
    finally:
        _drain_and_close(app, win, tab)


# ---------------------------------------------------------------------------
# Unit tests for the pure elide helper (gui/widgets/header_elide.py)
# ---------------------------------------------------------------------------

def test_elide_helper_returns_full_name_when_it_fits(app):
    from gui.widgets.header_elide import elide_headers_unique

    f = QApplication.font()
    metrics = QFontMetrics(f)
    names = ["A", "BB", "CCC"]
    result = elide_headers_unique(names, metrics, 10_000)
    for name in names:
        assert result[name] == name


def test_elide_helper_resolves_collisions_under_tight_width(app):
    """Force an artificially tiny width budget so every name in a
    prefix-colliding cluster WOULD middle-elide to the same string, then
    verify the collision-resolution pass still produces 27 unique
    outputs."""
    from gui.widgets.header_elide import elide_headers_unique

    f = QApplication.font()
    metrics = QFontMetrics(f)
    # Tight enough that "Boros Convoke"/"Boros Energy"/"Boros Aggro"/
    # "Boros Midrange" would collide at a naive fixed split.
    narrow = max(4, metrics.horizontalAdvance("Bo…e") )
    result = elide_headers_unique(_ARCHETYPES, metrics, narrow)
    values = list(result.values())
    assert len(values) == len(_ARCHETYPES)
    assert len(values) == len(set(values)), (
        f"collision resolution failed under tight width: {values}"
    )
