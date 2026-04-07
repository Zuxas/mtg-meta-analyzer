"""
Card embeddings: similarity search and deck vectors.

Uses pre-computed 768-dim ModernBERT embeddings from HuggingFace
(minimaxir/mtg-embeddings).  The parquet file must be downloaded first
via scripts/download_embeddings.py or the Settings tab button.

Core capabilities:
    - find_similar_cards(name)   → cards with similar mechanics/text
    - deck_embedding(card_list)  → single vector representing a deck
    - deck_similarity(a, b)     → cosine similarity between two decks
"""

from __future__ import annotations

import os
import numpy as np

_PARQUET_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "mtg_embeddings.parquet"
)

# Module-level singleton cache
_embeddings: dict[str, np.ndarray] | None = None
_name_lower_map: dict[str, str] | None = None  # lowercase → original name


def is_available() -> bool:
    """Check if the embeddings parquet file has been downloaded."""
    return os.path.exists(os.path.abspath(_PARQUET_PATH))


def _load() -> dict[str, np.ndarray]:
    """Load embeddings from parquet into memory (once)."""
    global _embeddings, _name_lower_map
    if _embeddings is not None:
        return _embeddings

    path = os.path.abspath(_PARQUET_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Card embeddings not downloaded. "
            "Run: python -m scripts.download_embeddings"
        )

    import pandas as pd
    df = pd.read_parquet(path, columns=["name", "embedding"])

    _embeddings = {}
    _name_lower_map = {}
    for _, row in df.iterrows():
        name = row["name"]
        vec = np.array(row["embedding"], dtype=np.float32)
        # Ensure unit normalized
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        _embeddings[name] = vec
        _name_lower_map[name.lower()] = name

    return _embeddings


def _resolve_name(name: str) -> str | None:
    """Resolve a card name (case-insensitive) to its canonical form."""
    _load()
    if name in _embeddings:
        return name
    return _name_lower_map.get(name.lower())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_similar_cards(
    card_name: str,
    top_n: int = 10,
    format_filter: str | None = None,
) -> list[dict]:
    """Find cards with similar text/mechanics via cosine similarity.

    Parameters
    ----------
    card_name     : card to search for
    top_n         : number of results
    format_filter : optional format name to restrict to legal cards

    Returns
    -------
    [{"name": str, "similarity": float}] sorted by similarity desc
    """
    embs = _load()
    resolved = _resolve_name(card_name)
    if not resolved:
        return []

    query = embs[resolved]

    # Build matrix of all other card vectors
    names = []
    vecs = []
    for n, v in embs.items():
        if n == resolved:
            continue
        names.append(n)
        vecs.append(v)

    if not vecs:
        return []

    mat = np.stack(vecs)  # (N, 768)
    # Cosine similarity (vectors are unit-normalized)
    sims = mat @ query  # (N,)

    # Optional format filter
    legal_set = None
    if format_filter:
        try:
            from db.database import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT card_name, legalities FROM card_data"
                ).fetchall()
            import json
            legal_set = set()
            for r in rows:
                try:
                    legs = json.loads(r["legalities"]) if r["legalities"] else {}
                    if legs.get(format_filter.lower()) == "legal":
                        legal_set.add(r["card_name"])
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            legal_set = None

    # Sort and return top N
    top_indices = np.argsort(-sims)
    results = []
    for idx in top_indices:
        if len(results) >= top_n:
            break
        name = names[idx]
        if legal_set is not None and name not in legal_set:
            continue
        results.append({
            "name": name,
            "similarity": round(float(sims[idx]), 4),
        })

    return results


def deck_embedding(card_list: dict[str, int]) -> np.ndarray | None:
    """Compute a single vector representing a deck.

    Parameters
    ----------
    card_list : {card_name: quantity} dict

    Returns
    -------
    768-dim unit vector (weighted average of card embeddings), or None
    """
    embs = _load()
    vecs = []
    weights = []

    for name, qty in card_list.items():
        resolved = _resolve_name(name)
        if resolved and resolved in embs:
            vecs.append(embs[resolved])
            weights.append(qty)

    if not vecs:
        return None

    mat = np.stack(vecs)
    w = np.array(weights, dtype=np.float32)
    centroid = (mat.T @ w) / w.sum()

    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid /= norm

    return centroid


def deck_similarity(deck_a: dict[str, int], deck_b: dict[str, int]) -> float | None:
    """Cosine similarity between two decks (0-1 scale).

    Parameters
    ----------
    deck_a, deck_b : {card_name: quantity} dicts

    Returns
    -------
    Similarity score 0.0–1.0, or None if either deck can't be embedded.
    """
    va = deck_embedding(deck_a)
    vb = deck_embedding(deck_b)
    if va is None or vb is None:
        return None
    return float(np.dot(va, vb))


def find_closest_archetype(
    card_list: dict[str, int],
    format_name: str = "standard",
    top_n: int = 5,
) -> list[dict]:
    """Find which meta archetypes a deck is most similar to.

    Computes deck embedding for the input and compares against average
    decklists from meta standings.

    Returns
    -------
    [{"archetype": str, "similarity": float}] sorted by similarity desc
    """
    from analysis.win_rates import get_meta_standings
    from analysis.deck_analysis import get_average_deck

    user_vec = deck_embedding(card_list)
    if user_vec is None:
        return []

    standings = get_meta_standings(format_name, top=20, min_appearances=5)
    results = []

    for s in standings:
        try:
            avg = get_average_deck(s["archetype"], format_name)
            if not avg:
                continue
            # avg is a list of dicts with card_name, avg_copies
            avg_cards = {c["card_name"]: round(c["avg_copies"])
                         for c in avg if c.get("avg_copies", 0) >= 1}
            arch_vec = deck_embedding(avg_cards)
            if arch_vec is None:
                continue
            sim = float(np.dot(user_vec, arch_vec))
            results.append({
                "archetype": s["archetype"],
                "similarity": round(sim, 4),
            })
        except Exception:
            continue

    results.sort(key=lambda x: -x["similarity"])
    return results[:top_n]
