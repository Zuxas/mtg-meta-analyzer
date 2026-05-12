"""
analysis/nbac_classifier.py — NBAC archetype classifier wrapper

Uses the Videre Project's Naive Bayes Archetype Classifier API at
https://ml.videreproject.com/nbac to classify decks by archetype from
a card list. No API key required; trained on MTGO tournament results.

Supports: standard, modern, pioneer, vintage, legacy, pauper
"""
import json
import urllib.request
import urllib.error

_URL = "https://ml.videreproject.com/nbac"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def classify_deck(cards, format_name="modern", explain=False, top_n=5, timeout=10):
    """Classify a deck by archetype using the NBAC API.

    Args:
        cards: list of card name strings (or dicts with 'name'/'quantity')
        format_name: 'modern', 'standard', 'pioneer', 'vintage', 'legacy', 'pauper'
        explain: if True, return per-card evidence for each archetype
        top_n: number of top archetypes to return
        timeout: request timeout in seconds

    Returns:
        dict with keys:
          'archetype': str — top archetype name
          'confidence': float — top archetype probability (0-1)
          'top': list of (archetype, probability) tuples sorted descending
          'meta': dict — API metadata (exec_ms, model, backend)
          'explain': dict — per-card evidence if explain=True, else {}
    """
    url = f"{_URL}?format={format_name.lower()}"
    if explain:
        url += "&explain=1&explain_method=lift&explain_n=5&explain_top=3"

    data = json.dumps(cards).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "archetype": None, "confidence": 0}
    except Exception as e:
        return {"error": str(e), "archetype": None, "confidence": 0}

    raw = resp.get("data", {})
    if not raw:
        return {"error": "empty response", "archetype": None, "confidence": 0}

    sorted_archs = sorted(raw.items(), key=lambda x: -x[1])
    top = sorted_archs[:top_n]

    return {
        "archetype": top[0][0] if top else None,
        "confidence": top[0][1] if top else 0.0,
        "top": top,
        "meta": resp.get("meta", {}),
        "explain": resp.get("explain", {}),
        "error": None,
    }


def classify_deck_file(filepath, format_name="modern", **kwargs):
    """Read a mtg-sim deck file and classify it."""
    import re
    cards = []
    with open(filepath, encoding="utf-8", errors="ignore") as f:
        in_side = False
        for line in f:
            l = line.strip()
            if "sideboard" in l.lower():
                in_side = True
            if not in_side:
                m = re.match(r"(\d+)\s+(.+)", l)
                if m:
                    qty, name = int(m.group(1)), m.group(2).strip()
                    cards.extend([name] * qty)
    return classify_deck(cards, format_name, **kwargs)


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Quick test
    tests = [
        ("Boros Energy", "modern", ["Guide of Souls","Ocelot Pride","Ragavan, Nimble Pilferer",
                                     "Galvanic Discharge","Phlage, Titan of Fire's Fury"]),
        ("Izzet Lessons", "standard", ["Gran-Gran","Firebending Lesson","Combustion Technique",
                                        "Accumulate Wisdom","Abandon Attachments"]),
        ("Amulet Titan", "modern", ["Primeval Titan","Amulet of Vigor","Gruul Turf","Arboreal Grazer"]),
    ]
    print(f"{'Deck':<25} {'Format':<10} {'Result':<30} {'Conf':>6}")
    print("-" * 75)
    for label, fmt, cards in tests:
        r = classify_deck(cards, fmt)
        if r.get("error"):
            print(f"  {label:<23} {fmt:<10} ERROR: {r['error']}")
        else:
            print(f"  {label:<23} {fmt:<10} {r['archetype']:<30} {r['confidence']:>6.1%}")
