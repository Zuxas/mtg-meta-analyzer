"""Shared oracle-text predicates.

Exists because three engines -- blunders.py, chapin.py and deck_roles.py --
each carried their own near-duplicate keyword list for "is this card
interaction", and all three had the same defect in the same place: they
tested for the LITERAL substring "deals damage to" / "deals damage to
target", which cannot match real oracle text because the damage amount sits
between "deals" and "damage":

    "Lightning Bolt deals 3 damage to any target."
     ................^^^^^^^^^^^^^^^^^^

So every damage-based removal spell was invisible to all three: a burn deck
reported "0 interactive spells", scored 0.0 on Chapin's Answers principle,
and had its removal density undercounted when its role was classified.

The repo already knew the right shape -- analysis/sb_advisor.py:48 matches
`deals? \\d+ damage to any target` -- which is what makes the other three
provably wrong rather than merely different.

Kept as ONE predicate rather than a fourth keyword list: three copies
drifting out of sync is the root cause, not an incidental detail.
"""
import re

# Matches the damage-removal templates Wizards actually prints.
#
#   deals 3 damage to any target        (post-M19 wording)
#   deals 3 damage to target creature   (restricted wording)
#   deals X damage to any target        (variable)
#   deals damage to target creature     (rare, no amount)
#   deals 2 damage to each creature     (sweeper -- still interaction)
#
# The target clause is REQUIRED so that self-damage ("deals 1 damage to
# you" on a pain land, "deals 2 damage to its controller") is not counted as
# removal, which a bare "damage to" would wrongly pick up.
_DAMAGE_REMOVAL = re.compile(
    r"deals?\s+(?:\d+|x)?\s*damage\s+to\s+"
    r"(?:any target|target|each creature|each other creature|"
    r"that creature|that permanent)",
    re.IGNORECASE,
)

# "deals damage equal to its power to target creature" and friends.
_DAMAGE_EQUAL = re.compile(
    r"damage\s+equal\s+to\b[^.]{0,80}?\bto\s+"
    r"(?:any target|target|that creature|that permanent)",
    re.IGNORECASE,
)


def is_damage_removal(oracle_text: str | None) -> bool:
    """True when the text deals damage to something targetable.

    Deliberately narrow: this answers ONLY the damage question. Each engine
    keeps its own list for destroy/exile/counter/bounce, because those lists
    legitimately differ (deck_roles counts sweepers toward control, blunders
    counts -N/-N shrink effects) and unifying them would change behaviour
    beyond the bug being fixed.
    """
    if not oracle_text:
        return False
    return bool(_DAMAGE_REMOVAL.search(oracle_text)
                or _DAMAGE_EQUAL.search(oracle_text))
