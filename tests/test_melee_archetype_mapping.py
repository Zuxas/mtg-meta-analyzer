"""scrapers.mtgmelee_scraper._map_archetype must never invent a label.

Found 2026-10-01: it called `normalize(deck_name, fmt)`, so the FORMAT string landed in
normalize's positional `fuzzy` parameter and every Melee scrape fuzzy-matched deck names --
the docstring of normalize itself forbids that for scrapers ("false positives would silently
corrupt data"). Live examples: 'Mono-Green Broodscale' -> 'Mono Red Aggro',
'Mono-Red Ruby Storm' -> 'Cycle Storm' or 'Poison Storm' depending on the run. Now: exact
canonical / alias resolution only, otherwise the published name (pre-normalized); names the
alias table flags as junk ('' alias, e.g. 'Decklist') are unlabelled."""
import scrapers.mtgmelee_scraper as mm


def test_no_fuzzy_renames():
    assert mm._map_archetype("Mono-Green Broodscale", "modern") == "Mono Green Broodscale"
    assert mm._map_archetype("Mono-Red Ruby Storm", "modern") == "Mono Red Ruby Storm"
    assert mm._map_archetype("Abzan Devoted Druid Combo", "modern") == "Abzan Devoted Druid Combo"
    assert mm._map_archetype("Mono-Green Eldrazi", "modern") == "Mono Green Eldrazi"


def test_canonical_and_alias_names_still_resolve():
    assert mm._map_archetype("Izzet Prowess", "modern") == "Izzet Prowess"
    assert mm._map_archetype("Colorless", "modern") == "Eldrazi Tron"        # explicit alias


def test_blank_and_junk_names_are_unlabelled():
    assert mm._map_archetype("", "modern") == ""
    assert mm._map_archetype("   ", "modern") == ""
    assert mm._map_archetype("Decklist", "modern") == ""                     # alias table marks it junk


def test_mapping_is_deterministic_and_never_fuzzy(monkeypatch):
    calls = []
    real = mm.normalize_arch

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(mm, "normalize_arch", spy)
    first = [mm._map_archetype(n, "modern") for n in ("Mono-Red Ruby Storm", "Izzet", "Grixis Cosmogoyf")]
    second = [mm._map_archetype(n, "modern") for n in ("Mono-Red Ruby Storm", "Izzet", "Grixis Cosmogoyf")]
    assert first == second
    assert calls and all(len(a) == 1 and not k.get("fuzzy") for a, k in calls)
