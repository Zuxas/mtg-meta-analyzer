"""Tests for the KNN archetype-classifier accuracy harness.

Verifies the held-out evaluation logic (train/test split + accuracy) against
synthetic, well-separated data so it's fast and deterministic — independent of
the embeddings parquet or DB contents.
"""
from __future__ import annotations

import numpy as np
import pytest

from analysis import knn_classifier as knn


def _separated_training_set(per_class=20, seed=0):
    """3 well-separated clusters in 4-D space -> KNN should near-perfectly split."""
    rng = np.random.RandomState(seed)
    centers = [np.array([10., 0, 0, 0]), np.array([0, 10., 0, 0]),
               np.array([0, 0, 10., 0])]
    X, y = [], []
    for i, ctr in enumerate(centers):
        for _ in range(per_class):
            X.append(ctr + rng.randn(4) * 0.1)
            y.append(f"arch{i}")
    return np.stack(X), y, ["arch0", "arch1", "arch2"]


def test_evaluate_knn_reports_held_out_accuracy(monkeypatch):
    monkeypatch.setattr(knn, "build_training_set",
                        lambda fmt, **kw: _separated_training_set())
    res = knn.evaluate_knn("modern", test_size=0.25, random_state=0)
    assert res is not None
    assert {"format", "accuracy", "n_train", "n_test", "n_classes"} <= set(res)
    assert res["format"] == "modern"
    assert res["n_classes"] == 3
    assert res["n_train"] + res["n_test"] == 60
    assert 0.0 <= res["accuracy"] <= 1.0
    # well-separated clusters -> KNN should be near-perfect
    assert res["accuracy"] >= 0.9


def test_evaluate_knn_returns_none_without_data(monkeypatch):
    monkeypatch.setattr(knn, "build_training_set", lambda fmt, **kw: None)
    assert knn.evaluate_knn("modern") is None
