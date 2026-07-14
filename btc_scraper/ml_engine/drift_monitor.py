"""Dependency-light rolling calibration and population-stability metrics."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def population_stability_index(expected: Iterable[float], actual: Iterable[float], bins: int = 10) -> float:
    exp, act = np.asarray(list(expected), dtype=float), np.asarray(list(actual), dtype=float)
    exp, act = exp[np.isfinite(exp)], act[np.isfinite(act)]
    if len(exp) == 0 or len(act) == 0:
        return float("nan")
    edges = np.unique(np.quantile(exp, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0
    ep, _ = np.histogram(exp, bins=edges)
    ap, _ = np.histogram(act, bins=edges)
    ep = np.maximum(ep / max(ep.sum(), 1), 1e-6)
    ap = np.maximum(ap / max(ap.sum(), 1), 1e-6)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def calibration_metrics(probabilities: Iterable[float], labels: Iterable[int], bins: int = 10, min_bucket_samples: int = 100) -> dict:
    probs, y = np.asarray(list(probabilities), dtype=float), np.asarray(list(labels), dtype=float)
    mask = np.isfinite(probs) & np.isfinite(y)
    probs, y = np.clip(probs[mask], 0, 1), y[mask]
    if len(probs) == 0:
        return {"sample_count": 0, "brier": None, "ece": None, "mce": None, "buckets": []}
    rows, ece, mce = [], 0.0, 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = (probs >= lo) & ((probs < hi) if i < bins - 1 else (probs <= hi))
        count = int(idx.sum())
        if not count:
            rows.append({"range": f"{lo:.1f}-{hi:.1f}", "count": 0, "status": "insufficient_evidence"})
            continue
        predicted, observed = float(probs[idx].mean()), float(y[idx].mean())
        error = abs(predicted - observed)
        ece += error * count / len(probs)
        mce = max(mce, error)
        rows.append({"range": f"{lo:.1f}-{hi:.1f}", "count": count, "predicted": predicted, "observed": observed,
                     "error": error, "status": "ok" if count >= min_bucket_samples else "insufficient_evidence"})
    return {"sample_count": int(len(probs)), "brier": float(np.mean((probs - y) ** 2)), "ece": float(ece), "mce": float(mce), "buckets": rows,
            "severity": "critical" if ece > .10 else "ok"}
