"""
KNN Archetype Classifier — deck embedding → archetype prediction.

Uses card embeddings (Phase 4 text-based or Phase 5 co-occurrence) to
represent each deck as a vector, then classifies unknown decks via
K-Nearest Neighbors against known tournament decklists.

This serves as Layer 4 in the archetype normalization pipeline —
a fallback when name-based matching and signature cards fail.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import numpy as np

_MODEL_DIR = Path(__file__).parent.parent / "data" / "models"


def _ensure_model_dir():
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)


def build_training_set(
    format_name: str,
    min_decks_per_arch: int = 5,
) -> tuple[np.ndarray, list[str], list[str]] | None:
    """Build training data from known decklists.

    Returns (X, y, card_names_order) or None if insufficient data.
    X: (n_decks, embedding_dim) array
    y: archetype labels
    """
    from analysis.card_embeddings import is_available, deck_embedding
    if not is_available():
        return None

    from db.database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT d.id AS deck_id, d.archetype, c.name AS card_name, dc.quantity
            FROM decks d
            JOIN deck_cards dc ON dc.deck_id = d.id
            JOIN cards c ON c.id = dc.card_id
            JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?)
              AND d.archetype IS NOT NULL AND d.archetype != ''
              AND dc.is_sideboard = 0
            ORDER BY d.id
        """, [format_name]).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    # Group into decklists
    from collections import defaultdict
    deck_cards: dict[int, dict[str, int]] = defaultdict(dict)
    deck_archs: dict[int, str] = {}
    for r in rows:
        deck_cards[r["deck_id"]][r["card_name"]] = r["quantity"]
        deck_archs[r["deck_id"]] = r["archetype"]

    # Count archetypes, filter to those with enough samples
    arch_counts: dict[str, int] = defaultdict(int)
    for arch in deck_archs.values():
        arch_counts[arch] += 1
    valid_archs = {a for a, c in arch_counts.items() if c >= min_decks_per_arch}

    X_list = []
    y_list = []
    for deck_id, cards in deck_cards.items():
        arch = deck_archs[deck_id]
        if arch not in valid_archs:
            continue
        vec = deck_embedding(cards)
        if vec is not None:
            X_list.append(vec)
            y_list.append(arch)

    if len(X_list) < 10:
        return None

    return np.stack(X_list), y_list, list(valid_archs)


def train_knn(
    format_name: str,
    n_neighbors: int = 5,
) -> "sklearn.neighbors.KNeighborsClassifier | None":
    """Train and save a KNN classifier for the given format.

    Returns the trained classifier, or None if insufficient data.
    """
    from sklearn.neighbors import KNeighborsClassifier

    result = build_training_set(format_name)
    if result is None:
        return None

    X, y, _ = result
    print(f"Training KNN on {len(X)} decklists, {len(set(y))} archetypes...")

    clf = KNeighborsClassifier(n_neighbors=n_neighbors, metric="cosine")
    clf.fit(X, y)

    _ensure_model_dir()
    path = _MODEL_DIR / f"knn_{format_name}.pkl"
    with open(path, "wb") as f:
        pickle.dump(clf, f)
    print(f"Model saved to {path}")

    return clf


def load_knn(format_name: str) -> "sklearn.neighbors.KNeighborsClassifier | None":
    """Load a previously trained KNN model."""
    path = _MODEL_DIR / f"knn_{format_name}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def classify_deck(
    card_list: dict[str, int],
    format_name: str,
) -> tuple[str, float] | None:
    """Classify a deck's archetype using KNN.

    Parameters
    ----------
    card_list    : {card_name: quantity}
    format_name  : format for model selection

    Returns
    -------
    (predicted_archetype, confidence) or None if no model / can't embed.
    Confidence is the proportion of k neighbors that agree.
    """
    from analysis.card_embeddings import deck_embedding, is_available
    if not is_available():
        return None

    clf = load_knn(format_name)
    if clf is None:
        return None

    vec = deck_embedding(card_list)
    if vec is None:
        return None

    vec = vec.reshape(1, -1)

    # Get prediction and confidence via predict_proba
    prediction = clf.predict(vec)[0]
    proba = clf.predict_proba(vec)[0]
    confidence = float(proba.max())

    return prediction, round(confidence, 3)


def hybrid_classify(
    card_list: dict[str, int],
    format_name: str,
    min_confidence: float = 0.6,
) -> str | None:
    """Classify using signature cards first, then KNN fallback.

    Returns archetype name or None if no confident match.
    """
    # Layer 1: try signature-card classification
    try:
        from analysis.archetype_classifier import classify_by_cards
        result = classify_by_cards(card_list, format_name)
        if result:
            return result
    except Exception:
        pass

    # Layer 2: KNN on deck embedding
    knn_result = classify_deck(card_list, format_name)
    if knn_result:
        archetype, confidence = knn_result
        if confidence >= min_confidence:
            return archetype

    return None
