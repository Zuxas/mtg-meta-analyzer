"""'All formats' = the analyzer's SUPPORTED formats (db/formats.py), not every string in the data.

Vintage trios-seat matches (re-tagged 2026-10-02) stay in `matches` but must not enter any combined
statistic until Vintage is added to SUPPORTED_FORMATS."""
import re
import sqlite3
from datetime import date
from pathlib import Path

from analysis import conversion, win_rates
from db import matches_queries as mq
from db.formats import SUPPORTED_FORMATS, format_clause, formats_for, is_all_formats

ROOT = Path(__file__).resolve().parents[1]


def test_supported_formats_definition():
    assert SUPPORTED_FORMATS == ("standard", "pioneer", "modern", "legacy", "pauper")
    assert "vintage" not in SUPPORTED_FORMATS
    assert formats_for("all") == list(SUPPORTED_FORMATS) and formats_for("Modern") == ["modern"]
    sql, params = format_clause("all", "e.format")
    assert sql == " AND lower(e.format) IN (?,?,?,?,?)" and params == list(SUPPORTED_FORMATS)
    assert format_clause("modern") == (" AND lower(format) = lower(?)", ["modern"])
    assert win_rates.is_all_formats("All Formats") and is_all_formats(None) and not is_all_formats("modern")


def test_gui_lists_use_the_shared_definition():
    from gui.main_window import _FORMATS_FOR_ALL
    assert tuple(_FORMATS_FOR_ALL) == SUPPORTED_FORMATS


def test_no_all_formats_branch_drops_the_format_filter():
    """The old idiom `if not is_all_formats(fmt): <add filter>` meant 'all' = no filter at all, which
    let every format string in the data into combined stats. Every query site uses format_clause."""
    offenders = []
    for path in [*ROOT.glob("analysis/**/*.py"), *ROOT.glob("gui/**/*.py"), *ROOT.glob("db/**/*.py"),
                 *ROOT.glob("mcp_server/**/*.py")]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"if not (?:_all_fmts|is_all_formats\()", text) or \
                re.search(r'=\s*""\s*if is_all_formats\(', text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def _seed(fmt, arch_a, arch_b, n, event="mtgmelee_1"):
    rows = []
    for i in range(n):
        rows.append({"event_id": event, "round": 1, "player1": f"{fmt}{i}a", "player2": f"{fmt}{i}b",
                     "player1_arch": arch_a, "player2_arch": arch_b, "winner_arch": arch_a,
                     "result": "player1", "format": fmt, "event_date": date.today().isoformat(),
                     "source": "mtgmelee"})
    mq.save_matches(rows)


def test_vintage_rows_stay_stored_but_leave_combined_stats():
    win_rates._query_cache.clear()
    _seed("modern", "Boros Energy", "Amulet Titan", 20, "mtgmelee_1")
    _seed("vintage", "Doomsday", "Oath", 20, "mtgmelee_2")
    assert len(mq.get_matches("vintage")) == 20                          # preserved
    trend = win_rates._archetype_trend_from_matches("Doomsday", "all", 8, None, None)
    assert not any(trend.values()) if isinstance(trend, dict) else not trend
    assert win_rates._archetype_trend_from_matches("Boros Energy", "all", 8, None, None)
    conv = conversion.conversion_by_archetype("all", "2000-01-01", min_players=1)
    assert "Doomsday" not in conv and "Oath" not in conv
    assert "Boros Energy" in conv
    from db import database
    con = sqlite3.connect(database.DB_PATH)
    assert con.execute("SELECT COUNT(*) FROM matches WHERE format='vintage'").fetchone()[0] == 20
