"""Canonical calibration metrics shared by training and runtime reporting."""
from __future__ import annotations

from typing import Iterable
import numpy as np

from .meta_model_v3 import compute_calibration_buckets, expected_calibration_error


def calibration_report(probabilities: Iterable[float], labels: Iterable[int]) -> dict:
    probs = np.asarray(list(probabilities), dtype=float)
    actual = np.asarray(list(labels), dtype=int)
    if len(probs) != len(actual):
        raise ValueError("probabilities and labels must have equal length")
    return {
        "sample_count": int(len(probs)),
        "ece": expected_calibration_error(probs, actual),
        "buckets": compute_calibration_buckets(probs, actual, min_samples=1),
    }
