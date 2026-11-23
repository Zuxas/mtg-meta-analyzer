"""#54: the no-op ``--include-archive`` CLI flags are removed.

After #24, ``include_archive`` only does real work on the average-deck path
(``get_average_deck``), so the four commands that reach it keep the flag:
``average``, ``compare``, ``blunder``, ``chapin``. Every other command ATTACHed
the archive but never queried ``archive.*`` -- a silent no-op -- so the flag is
gone from them. These tests pin that contract via the argparse parser alone
(no DB), so they run anywhere.
"""
import pytest

from analysis.query import build_parser

KEEP = {
    "average": ["Izzet Prowess"],
    "compare": ["--deck-id", "1"],
    "blunder": ["Izzet Prowess"],
    "chapin": ["Izzet Prowess"],
}

# command -> the minimal required positionals/options so parsing reaches the
# flag check (argparse validates required args before unknown-flag errors).
REMOVE = {
    "top-cards": [],
    "meta": [],
    "trend": ["Izzet Prowess"],
    "h2h": ["Izzet Prowess", "Azorius Control"],
    "matchups": ["Izzet Prowess"],
    "matrix": [],
    "field-optimizer": ["--field", "Izzet Prowess x4"],
}

CHART_REMOVE = {
    "meta": [],
    "trend": ["Izzet Prowess"],
    "heatmap": [],
}


def _parses(argv):
    try:
        build_parser().parse_args(argv)
        return True
    except SystemExit:
        return False


@pytest.mark.parametrize("cmd,extra", KEEP.items())
def test_functional_commands_still_accept_flag(cmd, extra):
    assert _parses([cmd, *extra, "--include-archive"]), f"{cmd} should accept --include-archive"
    # and still parse without it
    assert _parses([cmd, *extra]), f"{cmd} should parse without the flag"


@pytest.mark.parametrize("cmd,extra", REMOVE.items())
def test_noop_commands_reject_flag(cmd, extra):
    assert not _parses([cmd, *extra, "--include-archive"]), (
        f"{cmd} no longer implements include_archive -- the flag must be rejected, not silently ignored"
    )
    # the command itself must still work without the flag
    assert _parses([cmd, *extra]), f"{cmd} should still parse without the flag"


@pytest.mark.parametrize("sub,extra", CHART_REMOVE.items())
def test_chart_subcommands_reject_flag(sub, extra):
    assert not _parses(["chart", sub, *extra, "--include-archive"]), (
        f"chart {sub} no longer implements include_archive -- the flag must be rejected"
    )
    assert _parses(["chart", sub, *extra]), f"chart {sub} should still parse without the flag"
