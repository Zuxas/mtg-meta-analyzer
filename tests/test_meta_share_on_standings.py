"""The Prep Checklist called every missing sideboard plan "LOW PRIO".

get_meta_standings has two implementations behind one documented shape:

    the placement-based path  (the default, what nearly every caller gets)
    _meta_standings_from_matches  (a sparse-data fallback, win_rates.py:~500)

Only the fallback emitted a "meta_share" key. Consumers written against the
documented shape used `s.get("meta_share", 0)` -- which is exactly the kind of
defensive default that hides a missing key -- and silently received 0 on every
call.

Two consumers were affected:

  * gui/tabs/prep_checklist.py:185 builds each row with
    `"meta_share": s.get("meta_share", 0)`. The Meta % column therefore showed
    0.0% for every opponent. Worse, _readiness() decides priority with
    `if meta_share >= 0.05: return "GAP"` -- which could never fire, so a
    missing sideboard plan against a 25%-of-the-field deck reported
    "LOW PRIO". For a checklist whose entire job is flagging which plans you
    are missing against decks that matter, it reported that nothing mattered.

  * analysis/deck_recommender.py:66 does the same, though its only consumer
    (the Dashboard's Best Deck dialog) does not currently display the field --
    latent rather than visible.

Fixed at the root, in get_meta_standings, so both paths agree and every
present and future caller gets a real number. Computed over the TRIMMED list,
so the share is a fraction of the field the caller was actually handed.
"""
import pytest


@pytest.fixture
def populated_standings(tmp_path, monkeypatch):
    """Real get_meta_standings output over a purpose-built database.

    Built here rather than against the developer's DB so the expected shares
    are known by construction: 50/30/15/5 decks -> 50%/30%/15%/5%.
    """
    import sqlite3
    from datetime import datetime, timedelta

    db = tmp_path / "share.db"
    arch_db = tmp_path / "share_arch.db"
    import db.database as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(db))
    monkeypatch.setattr(dbmod, "ARCHIVE_PATH", str(arch_db))
    dbmod.init_db()

    con = sqlite3.connect(str(db))
    today = datetime.now()
    eids = []
    for i in range(8):
        con.execute(
            "INSERT INTO events (source_id, source, name, date, format,"
            " event_type, url) VALUES (?,?,?,?,?,?,?)",
            (f"e{i}", "mtgtop8", f"Event {i}",
             (today - timedelta(days=i * 2)).strftime("%Y-%m-%d"),
             "standard", "mtgo_challenge_32", f"http://e/{i}"))
        eids.append(con.execute("SELECT last_insert_rowid()").fetchone()[0])

    n = 0
    for arch, count in (("Big Deck", 50), ("Mid Deck", 30),
                        ("Small Deck", 15), ("Tiny Deck", 5)):
        for k in range(count):
            n += 1
            con.execute(
                "INSERT INTO decks (event_id, source_id, player, archetype,"
                " placement, url) VALUES (?,?,?,?,?,?)",
                (eids[k % len(eids)], f"d{n}", f"P{n}", arch,
                 (k % 16) + 1, f"http://d/{n}"))
    con.commit(); con.close()

    from analysis.win_rates import get_meta_standings
    import analysis.win_rates as wr
    wr._CACHE.clear() if hasattr(wr, "_CACHE") else None
    return get_meta_standings("standard", top=20, min_appearances=1)


def test_placement_path_emits_meta_share(populated_standings):
    """The key must exist at all -- its absence is the whole bug."""
    assert populated_standings, "fixture produced no standings"
    for s in populated_standings:
        assert "meta_share" in s, (
            f"{s['archetype']} has no meta_share; consumers using "
            f".get('meta_share', 0) will silently read 0"
        )


def test_meta_share_matches_appearances(populated_standings):
    total = sum(s["appearances"] for s in populated_standings)
    for s in populated_standings:
        assert s["meta_share"] == pytest.approx(
            s["appearances"] / total, abs=1e-4), (
            f"{s['archetype']}: share {s['meta_share']} != "
            f"{s['appearances']}/{total}")


def test_shares_sum_to_one(populated_standings):
    total = sum(s["meta_share"] for s in populated_standings)
    assert total == pytest.approx(1.0, abs=1e-3), (
        f"shares sum to {total}, so they are not a partition of the field")


def test_no_share_is_zero_when_the_archetype_has_appearances(populated_standings):
    """The exact symptom: a real deck reporting 0% of the field."""
    zeros = [s["archetype"] for s in populated_standings
             if s["appearances"] > 0 and not s["meta_share"]]
    assert not zeros, f"archetypes with appearances but 0 share: {zeros}"


def test_prep_checklist_readiness_can_reach_GAP(populated_standings):
    """End to end through the consumer that was broken.

    _readiness returns "GAP" only when meta_share >= 0.05. With the key
    missing that branch was unreachable, so this asserts a major deck with no
    sideboard plan is now flagged.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from gui.tabs.prep_checklist import _readiness

    biggest = max(populated_standings, key=lambda s: s["meta_share"])
    assert biggest["meta_share"] >= 0.05, (
        "fixture's top archetype is under 5%, so this test proves nothing")

    label, _reason = _readiness({
        "meta_share": biggest["meta_share"], "has_plan": False,
        "real_wr": None, "real_sample": 0, "p_wr": None, "p_n": 0,
    })
    assert label == "GAP", (
        f"a missing sideboard plan against {biggest['archetype']} at "
        f"{biggest['meta_share']*100:.1f}% of the field should be a GAP, "
        f"got {label!r}")

    # counterpart: a genuinely marginal deck stays low priority, so the test
    # above is not passing because everything is now a GAP
    low, _ = _readiness({"meta_share": 0.01, "has_plan": False,
                         "real_wr": None, "real_sample": 0,
                         "p_wr": None, "p_n": 0})
    assert low == "LOW PRIO", f"a 1% deck should stay low priority, got {low!r}"


def test_both_standings_paths_agree_on_the_key():
    """The root cause was two implementations disagreeing about the shape.

    Pinned in source so a future edit to either path cannot silently drop the
    key again.
    """
    import inspect
    import analysis.win_rates as wr

    src = inspect.getsource(wr)
    assert '_s["meta_share"] = ' in src, (
        "the placement-based path no longer sets meta_share")
    assert src.count('"meta_share"') >= 3, (
        "expected meta_share in both standings builders")
