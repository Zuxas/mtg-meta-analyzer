import sqlite3
from datetime import date

from analysis import observed_deck_classifier as odc
from analysis.observed_deck_classifier import ProfileCache, load_profiles, score_profiles

PROFILES = {
    "Boros Energy": {"guide of souls": 1.0, "ocelot pride": 1.0, "ajani, nacatl pariah": 0.9,
                     "galvanic discharge": 1.0, "arid mesa": 0.8, "phlage, titan of fire's fury": 0.7},
    "Izzet Murktide": {"murktide regent": 1.0, "counterspell": 1.0, "dragon's rage channeler": 1.0,
                       "scalding tarn": 0.9, "consider": 0.8},
    "Jeskai Control": {"counterspell": 0.9, "phlage, titan of fire's fury": 0.9,
                       "arid mesa": 0.8, "solitude": 1.0, "prismatic ending": 0.9},
}


def test_signature_cards_win_over_shared_staples():
    seen = {"Guide of Souls", "Galvanic Discharge", "Arid Mesa", "Phlage, Titan of Fire's Fury"}
    arch, conf, overlap = score_profiles(seen, PROFILES)
    assert arch == "Boros Energy" and overlap == 4


def test_too_few_cards_is_unknown():
    assert score_profiles({"Counterspell", "Consider"}, PROFILES) is None


def test_basics_do_not_count_as_evidence():
    assert score_profiles({"Island", "Mountain", "Counterspell"}, PROFILES) is None


def test_confidence_scales_with_cards_seen():
    few = score_profiles({"Murktide Regent", "Counterspell", "Consider"}, PROFILES)
    many = score_profiles({"Murktide Regent", "Counterspell", "Consider", "Scalding Tarn",
                           "Dragon's Rage Channeler", "Lightning Bolt", "Unholy Heat",
                           "Mishra's Bauble"}, PROFILES)
    assert few[0] == many[0] == "Izzet Murktide"
    assert few[1] < many[1]


def test_unrelated_cards_do_not_match():
    assert score_profiles({"Thoughtseize", "Tarmogoyf", "Liliana of the Veil"}, PROFILES) is None


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, date TEXT, format TEXT);
        CREATE TABLE decks (id INTEGER PRIMARY KEY, event_id INT, archetype TEXT);
        CREATE TABLE cards (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE deck_cards (deck_id INT, card_id INT, quantity INT, is_sideboard INT);
        INSERT INTO cards VALUES (1,'Guide of Souls'),(2,'Ocelot Pride'),(3,'Galvanic Discharge'),
                                 (4,'Murktide Regent'),(5,'Counterspell'),(6,'Consider');
    """)
    did = 0
    for dt, arch, cards in [("2026-09-01", "Boros Energy", (1, 2, 3))] * 3 + \
                           [("15/08/26", "Izzet Murktide", (4, 5, 6))] * 3 + \
                           [("2024-01-01", "Old Deck", (1, 2, 3))] * 3:
        did += 1
        con.execute("INSERT INTO events VALUES (?,?,?)", (did, dt, "modern"))
        con.execute("INSERT INTO decks VALUES (?,?,?)", (did, did, arch))
        con.executemany("INSERT INTO deck_cards VALUES (?,?,4,0)", [(did, c) for c in cards])
    return con


def test_load_profiles_date_window_and_mixed_date_formats(monkeypatch):
    monkeypatch.setattr(odc, "_canonical", lambda: (lambda s: s))
    prof = load_profiles(_db(), "modern", date(2026, 9, 20))
    assert set(prof) == {"Boros Energy", "Izzet Murktide"}  # 2024 deck is out of window
    assert prof["Boros Energy"]["guide of souls"] == 1.0


def test_load_profiles_merges_alias_labels(monkeypatch):
    monkeypatch.setattr(odc, "_canonical",
                        lambda: (lambda s: "Energy" if s in ("Boros Energy", "Izzet Murktide") else s))
    prof = load_profiles(_db(), "modern", date(2026, 9, 20))
    assert set(prof) == {"Energy"}
    assert prof["Energy"]["guide of souls"] == 0.5  # 3 of 6 merged decks


def test_profile_cache_classifies_and_skips_limited():
    cache = ProfileCache(_db())
    seen = {"Guide of Souls", "Ocelot Pride", "Galvanic Discharge"}
    assert cache.classify(seen, "modern", date(2026, 9, 20))[0] == "Boros Energy"
    assert cache.classify(seen, "limited", date(2026, 9, 20)) is None


def test_umbrella_label_folds_into_most_played_specific_label():
    counts = {
        "Boros": {"guide of souls": 3, "ocelot pride": 3, "galvanic discharge": 3},
        "Boros Energy": {"guide of souls": 20, "ocelot pride": 20, "galvanic discharge": 19},
        "Boros Aggro": {"guide of souls": 5, "ocelot pride": 5, "galvanic discharge": 5},
        "Izzet Prowess": {"slickshot show-off": 10, "monastery swiftspear": 10},
        "Prowess": {"monastery swiftspear": 4, "lava dart": 4},   # different profile: stays
    }
    totals = {"Boros": 3, "Boros Energy": 20, "Boros Aggro": 5, "Izzet Prowess": 10, "Prowess": 4}
    c, t = odc.merge_umbrellas(counts, totals)
    assert "Boros" not in c and t["Boros Energy"] == 23
    assert c["Boros Energy"]["guide of souls"] == 23
    assert "Boros Aggro" in c                       # not an umbrella of anything
    assert "Prowess" in c                           # words match but decklists don't


def test_umbrella_merge_never_crosses_unrelated_words():
    counts = {"Tron": {"urza's tower": 5}, "Eldrazi Tron": {"urza's tower": 9}}
    c, t = odc.merge_umbrellas(counts, {"Tron": 5, "Eldrazi Tron": 9})
    assert "Tron" not in c                          # same profile + subset words -> merged
    counts2 = {"Tron": {"urza's tower": 5}, "Mono Green Stompy": {"urza's tower": 9}}
    c2, _ = odc.merge_umbrellas(counts2, {"Tron": 5, "Mono Green Stompy": 9})
    assert set(c2) == {"Tron", "Mono Green Stompy"}


def test_common_name_never_folds_into_a_rarer_label():
    counts = {"Boros Energy": {"a": 40, "b": 40}, "Boros Energy Gingerkush": {"a": 2, "b": 2}}
    c, t = odc.merge_umbrellas(counts, {"Boros Energy": 40, "Boros Energy Gingerkush": 2})
    assert "Boros Energy" in c and t["Boros Energy"] == 40


def test_merge_map_records_what_folded_where():
    mapping = {}
    odc.merge_umbrellas({"Boros": {"a": 3}, "Boros Energy": {"a": 20}},
                        {"Boros": 3, "Boros Energy": 20}, mapping=mapping)
    assert mapping == {"Boros": "Boros Energy"}


def test_ties_between_equivalent_targets_go_to_the_all_time_name():
    counts = {"Boros": {"a": 3}, "Boros Energy": {"a": 5}, "Boros Ocelot": {"a": 9}}
    totals = {"Boros": 3, "Boros Energy": 5, "Boros Ocelot": 9}     # Ocelot hot this month
    mapping = {}
    odc.merge_umbrellas(counts, totals, mapping=mapping,
                        popularity={"Boros Energy": 900, "Boros Ocelot": 40})
    assert mapping["Boros"] == "Boros Energy"
