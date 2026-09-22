"""Burn spells were invisible to every deck-evaluation engine.

blunders.py, chapin.py and deck_roles.py each carried their own near-identical
"is this interaction?" keyword list, and all three tested for a LITERAL
substring that cannot occur in real oracle text:

    blunders.py:274    "deals damage to target"
    chapin.py:117      "deals damage to target"
    deck_roles.py:32   "deals damage to"

Real text puts the amount between "deals" and "damage" -- "deals 3 damage to
any target" -- so none of those substrings ever matched a burn spell.
Consequences, all reproduced below against a deck built from real templates:

  * blunders raised a MAJOR "Very low interaction: only 0 interactive
    spells" on a deck that is 40% removal (10 points of blunder score, which
    drags the construction-quality grade down for a correctly built deck).
  * chapin scored the Answers principle 0.0 for the same deck.
  * deck_roles undercounted removal density.

This is not a matter of taste about wording: analysis/sb_advisor.py:48, in
this same repo, already matches `deals? \\d+ damage to any target`. One part
of the codebase had the template right and three did not.

Fixed with a single shared predicate (analysis/card_text.is_damage_removal)
rather than a fourth keyword list, because three copies drifting apart is the
root cause.
"""
import pytest

from analysis.card_text import is_damage_removal


# Oracle snippets in the templates Wizards actually prints. Kept as text
# rather than card names so the test states exactly what is being matched.
BURN_TEMPLATES = [
    "Lightning Bolt deals 3 damage to any target.",
    "Shock deals 2 damage to any target.",
    "Abrade deals 3 damage to target creature.",
    "Flame Slash deals 4 damage to target creature.",
    "Fireball deals X damage to any target.",
    "Deals damage to target creature equal to the number of Mountains you control.",
    "Pyroclasm deals 2 damage to each creature.",
]

NOT_REMOVAL = [
    "Prowess (Whenever you cast a noncreature spell, this creature gets +1/+1 "
    "until end of turn.)",
    "{T}: Add {R}.",
    "Draw two cards.",
    "Flying, vigilance.",
    # The reason the target clause is required: self-damage is a drawback,
    # not interaction. A bare "damage to" would count these.
    "{T}: Add {B} or {R}. This land deals 1 damage to you.",
    "When this creature dies, it deals 2 damage to you.",
]


@pytest.mark.parametrize("oracle", BURN_TEMPLATES)
def test_real_burn_templates_are_detected(oracle):
    assert is_damage_removal(oracle), f"missed: {oracle!r}"


@pytest.mark.parametrize("oracle", NOT_REMOVAL)
def test_non_removal_is_not_detected(oracle):
    assert not is_damage_removal(oracle), f"false positive: {oracle!r}"


def test_the_exact_substrings_the_old_code_looked_for_never_matched():
    """The mechanism itself, pinned.

    If someone reintroduces a literal-substring check, this documents why it
    cannot work.
    """
    bolt = "Lightning Bolt deals 3 damage to any target.".lower()
    assert "deals damage to target" not in bolt
    assert "deals damage to" not in bolt
    assert is_damage_removal(bolt)


def test_empty_and_none_are_safe():
    assert not is_damage_removal(None)
    assert not is_damage_removal("")


# ---------------------------------------------------------------------------
# The three engines, end to end
# ---------------------------------------------------------------------------

def _burn_deck():
    """A legal 60-card burn deck: 20 lands, 24 creatures, 16 burn spells."""
    main = {"Mountain": 20, "Ember Sprinter": 4, "Prowess Adept": 4,
            "Goblin Firebrand": 4, "Riverbank Scout": 4,
            "Lightning Bolt": 4, "Shock": 4, "Abrade": 4, "Flame Slash": 4,
            "Sunlit Paladin": 4, "Grave Warden": 4}
    card_data = {
        "Mountain":        {"type_line": "Basic Land — Mountain",
                            "oracle_text": "{T}: Add {R}.", "cmc": 0.0},
        "Ember Sprinter":  {"type_line": "Creature — Elemental",
                            "oracle_text": "Haste.", "cmc": 1.0},
        "Prowess Adept":   {"type_line": "Creature — Human Wizard",
                            "oracle_text": "Prowess.", "cmc": 2.0},
        "Goblin Firebrand": {"type_line": "Creature — Goblin",
                             "oracle_text": "Haste.", "cmc": 1.0},
        "Riverbank Scout": {"type_line": "Creature — Merfolk",
                            "oracle_text": "Flying.", "cmc": 1.0},
        "Sunlit Paladin":  {"type_line": "Creature — Human Knight",
                            "oracle_text": "Vigilance.", "cmc": 3.0},
        "Grave Warden":    {"type_line": "Creature — Zombie",
                            "oracle_text": "Menace.", "cmc": 3.0},
        "Lightning Bolt":  {"type_line": "Instant",
                            "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                            "cmc": 1.0},
        "Shock":           {"type_line": "Instant",
                            "oracle_text": "Shock deals 2 damage to any target.",
                            "cmc": 1.0},
        "Abrade":          {"type_line": "Instant",
                            "oracle_text": "Abrade deals 3 damage to target creature.",
                            "cmc": 2.0},
        "Flame Slash":     {"type_line": "Sorcery",
                            "oracle_text": "Flame Slash deals 4 damage to target creature.",
                            "cmc": 1.0},
    }
    return main, card_data


def test_blunders_counts_burn_as_interaction():
    """The headline symptom: 16 burn spells must not read as 0."""
    from analysis.blunders import _check_interaction, _norms

    main, card_data = _burn_deck()
    issues = []
    count, names = _check_interaction(
        main, card_data, {"Mountain"}, _norms("standard"), issues)

    assert count == 16, (
        f"expected the 16 burn spells to count as interaction, got {count} "
        f"(matched: {sorted(names)})"
    )
    assert not any(i.category == "interaction" for i in issues), (
        "a deck with 16 removal spells must not raise a low-interaction issue"
    )


def test_chapin_classifies_burn_as_interaction():
    from analysis.chapin import _classify_cards

    main, card_data = _burn_deck()
    cats = _classify_cards(main, card_data)
    interaction = cats["interaction"] if isinstance(cats, dict) else cats[3]

    for burn in ("Lightning Bolt", "Shock", "Abrade", "Flame Slash"):
        assert burn in interaction, f"{burn} not classified as interaction"


def test_deck_roles_sees_burn_as_removal():
    from analysis.deck_roles import _is_removal

    assert _is_removal("Lightning Bolt deals 3 damage to any target.")
    assert _is_removal("Abrade deals 3 damage to target creature.")
    # unchanged behaviour for the keywords that already worked
    assert _is_removal("Destroy target creature.")
    assert _is_removal("Counter target spell.")
    assert not _is_removal("Flying, vigilance.")


def test_archetype_detail_groups_burn_under_removal():
    """The fourth site, found by a repo-wide sweep rather than by the probe.

    gui/widgets/archetype_detail.py::_classify_card_role carried a fourth
    copy of the same list, feeding the Tech Choices tab's role grouping
    (Threat / Removal / Card Advantage / Mana / Protection / Utility). With
    the broken literal, burn spells fell through to Threat or Utility, so a
    burn deck's flex slots were grouped under the wrong heading.

    Needs a QApplication because the module imports PyQt widgets at import
    time, but the function under test is pure.
    """
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from gui.widgets.archetype_detail import _classify_card_role

    assert _classify_card_role(
        "Instant", "Lightning Bolt deals 3 damage to any target.") == "Removal"
    assert _classify_card_role(
        "Instant", "Abrade deals 3 damage to target creature.") == "Removal"
    # the keywords that already worked must be untouched
    assert _classify_card_role("Sorcery", "Destroy target creature.") == "Removal"
    assert _classify_card_role("Creature — Goblin", "Haste.") == "Threat"
    assert _classify_card_role("Basic Land — Mountain", "{T}: Add {R}.") == "Mana"
