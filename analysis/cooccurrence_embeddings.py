"""
Card2Vec: co-occurrence embeddings trained on tournament decklists.

Each deck is a "sentence", each card is a "word". Cards that appear
together in real decks get similar vectors.  This captures *functional*
similarity — cards that fill the same slot — rather than text similarity.

Trained on the app's own decklist data using gensim Word2Vec.
Models saved to data/models/card2vec_{format}.model.
"""

from __future__ import annotations

import os
from pathlib import Path

_MODEL_DIR = Path(__file__).parent.parent / "data" / "models"


def _ensure_model_dir():
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)


def train_card2vec(
    format_name: str | None = None,
    vector_size: int = 100,
    window: int = 60,
    min_count: int = 5,
    epochs: int = 20,
) -> "gensim.models.Word2Vec":
    """Train Card2Vec on decklists from the database.

    Parameters
    ----------
    format_name : restrict to a single format (None = all formats)
    vector_size : embedding dimensions
    window      : context window (60 = whole deck)
    min_count   : minimum card appearances to include
    epochs      : training passes

    Returns the trained model (also saved to disk).
    """
    from gensim.models import Word2Vec
    from db.database import get_connection

    conn = get_connection()
    try:
        # Build "sentences": each deck → list of card names (repeated by qty)
        q = """
            SELECT dc.deck_id, c.name, dc.quantity
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            JOIN decks d ON d.id = dc.deck_id
            WHERE dc.is_sideboard = 0
        """
        params = []
        if format_name:
            q += """
                AND d.event_id IN (
                    SELECT id FROM events WHERE lower(format) = lower(?)
                )
            """
            params.append(format_name)
        q += " ORDER BY dc.deck_id"

        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"No decklists found{' for ' + format_name if format_name else ''}")

    # Group by deck_id
    decks: dict[int, list[str]] = {}
    for r in rows:
        deck_id = r["deck_id"]
        card_name = r["name"]
        qty = r["quantity"]
        decks.setdefault(deck_id, []).extend([card_name] * qty)

    sentences = list(decks.values())
    print(f"Training Card2Vec on {len(sentences)} decklists, "
          f"{sum(len(s) for s in sentences)} total card instances...")

    model = Word2Vec(
        sentences=sentences,
        vector_size=vector_size,
        window=window,
        min_count=min_count,
        epochs=epochs,
        workers=4,
        sg=1,  # skip-gram (better for small corpora)
    )

    _ensure_model_dir()
    suffix = format_name or "all"
    path = _MODEL_DIR / f"card2vec_{suffix}.model"
    model.save(str(path))
    print(f"Model saved to {path} ({len(model.wv)} card vectors)")

    return model


def load_card2vec(format_name: str | None = None) -> "gensim.models.Word2Vec | None":
    """Load a previously trained model. Returns None if not trained."""
    from gensim.models import Word2Vec

    suffix = format_name or "all"
    path = _MODEL_DIR / f"card2vec_{suffix}.model"
    if not path.exists():
        return None
    return Word2Vec.load(str(path))


def is_trained(format_name: str | None = None) -> bool:
    """Check if a model exists for the given format."""
    suffix = format_name or "all"
    return (_MODEL_DIR / f"card2vec_{suffix}.model").exists()


def find_functional_substitutes(
    card_name: str,
    format_name: str | None = None,
    top_n: int = 10,
) -> list[dict]:
    """Find cards that fill the same role in real decks.

    Uses Word2Vec most_similar — cards that appear in the same "slot"
    across many decklists.

    Returns
    -------
    [{"name": str, "similarity": float}] sorted by similarity desc
    """
    model = load_card2vec(format_name)
    if model is None:
        return []

    if card_name not in model.wv:
        # Try case-insensitive lookup
        lower_map = {k.lower(): k for k in model.wv.key_to_index}
        resolved = lower_map.get(card_name.lower())
        if not resolved:
            return []
        card_name = resolved

    try:
        similar = model.wv.most_similar(card_name, topn=top_n)
        return [{"name": name, "similarity": round(sim, 4)}
                for name, sim in similar]
    except KeyError:
        return []


if __name__ == "__main__":
    import sys
    fmt = sys.argv[1] if len(sys.argv) > 1 else None
    model = train_card2vec(fmt)
    print(f"\nTrained {len(model.wv)} card vectors")

    # Quick test
    test_cards = ["Lightning Bolt", "Counterspell", "Fatal Push",
                  "Ragavan, Nimble Pilferer", "Thoughtseize"]
    for card in test_cards:
        if card in model.wv:
            subs = find_functional_substitutes(card, fmt, top_n=5)
            print(f"\n{card}:")
            for s in subs:
                print(f"  {s['name']:35s} {s['similarity']:.3f}")
