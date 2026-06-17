"""Pure unit tests for scripts/ingest_set.py helpers.

No network, no DB. Guards the slug-normalization and gallery-coverage
logic -- a regex/normalization bug there would silently report
"coverage OK" while real cards went un-ingested.
"""
from scripts.ingest_set import (
    card_slug_keys,
    is_basic_land,
    normalize_slug,
    slugs_from_gallery,
)


# --- normalize_slug --------------------------------------------------------

def test_normalize_folds_accents():
    # Mjolnir must compare equal whether or not the o carries a diaeresis.
    assert normalize_slug("Mjolnir") == normalize_slug("Mjölnir")


def test_normalize_strips_punctuation_and_spaces_and_case():
    assert normalize_slug("Tony Stark // The Invincible Iron Man") == \
        "tonystarktheinvincibleironman"
    assert normalize_slug("U.S.Agent, John Walker") == "usagentjohnwalker"
    assert normalize_slug("the-unbeatable-squirrel-girl") == \
        "theunbeatablesquirrelgirl"


def test_normalize_url_decodes():
    # Gallery slugs arrive percent-encoded; %C3%B6 == o-diaeresis -> folds away.
    assert normalize_slug("Mj%C3%B6lnir") == normalize_slug("Mjolnir")
    assert normalize_slug("a%2Cb") == "ab"


# --- card_slug_keys --------------------------------------------------------

def test_single_face_card_yields_one_key():
    assert card_slug_keys({"name": "Giant Growth"}) == {"giantgrowth"}


def test_dfc_includes_both_face_slugs():
    card = {
        "name": "Tony Stark // The Invincible Iron Man",
        "card_faces": [
            {"name": "Tony Stark"},
            {"name": "The Invincible Iron Man"},
        ],
    }
    keys = card_slug_keys(card)
    # The back face is linked under its own slug in modal-DFC galleries.
    assert "tonystark" in keys
    assert "theinvincibleironman" in keys
    assert normalize_slug(card["name"]) in keys


# --- is_basic_land ---------------------------------------------------------

def test_is_basic_land():
    assert is_basic_land({"type_line": "Basic Land — Forest"})
    assert not is_basic_land({"type_line": "Legendary Creature — God"})
    assert not is_basic_land({})  # missing type_line must not blow up


# --- slugs_from_gallery ----------------------------------------------------

def test_slugs_from_gallery_extracts_set_scoped_slugs(tmp_path):
    html = """
    <a href="https://scryfall.com/card/msh/12/thor-odinson">Thor</a>
    <a href="https://scryfall.com/card/msh/5/giant-growth?utm=x">GG</a>
    <a href="https://scryfall.com/card/otj/3/take-up-the-shield">other set</a>
    """
    f = tmp_path / "gallery.html"
    f.write_text(html, encoding="utf-8")
    slugs = slugs_from_gallery(str(f), "msh")
    # Only msh-scoped slugs, query string stripped, other sets excluded.
    assert slugs == {"thor-odinson", "giant-growth"}
