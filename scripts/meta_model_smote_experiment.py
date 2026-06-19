"""
SMOTE experiment for meta model: compare baseline (class_weight='balanced')
vs SMOTE oversampling on training set.

Produces `logs/meta_model_smote_results.json` with metrics: ROC-AUC, PR-AUC, Brier.

Usage:
  python scripts/meta_model_smote_experiment.py

If `imbalanced-learn` is not installed, the script will exit with instructions.
"""
from __future__ import annotations
import os
import json
from datetime import datetime
from typing import Dict, Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from sklearn.model_selection import train_test_split
import sys

# Ensure project root is on sys.path for imports like `btc_scraper`
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.path.dirname(os.path.dirname(__file__))
LOGS = os.path.join(BASE, "logs")
INPUT = os.path.join(LOGS, "adaptive_signals_v2.json")
OUT = os.path.join(LOGS, "meta_model_smote_results.json")


def load_dataset():
    # reuse the existing loader from meta_model pipeline
    try:
        from btc_scraper.ml_engine.feature_extractor import records_to_dataset, FEATURE_SCHEMA_V2
        from btc_scraper.ml_engine.meta_model import _load_records, _sort_records_by_time
    except Exception as e:
        raise RuntimeError(f"Failed to import dataset utilities: {e}")

    recs = _load_records()
    recs = _sort_records_by_time(recs)
    X_list, y_list, feature_names = records_to_dataset(recs)
    X = np.array(X_list)
    y = np.array(y_list)
    return X, y, feature_names


def safe_import_smote():
    try:
        from imblearn.over_sampling import SMOTE
        return SMOTE
    except Exception:
        return None


def evaluate_model(clf, X_test, y_test) -> Dict[str, Any]:
    out = {"roc_auc": None, "pr_auc": None, "brier": None}
    try:
        probs = clf.predict_proba(X_test)[:, 1]
        preds = clf.predict(X_test)
        out["roc_auc"] = float(roc_auc_score(y_test, probs))
    except Exception:
        out["roc_auc"] = None
    try:
        out["pr_auc"] = float(average_precision_score(y_test, probs))
    except Exception:
        out["pr_auc"] = None
    try:
        out["brier"] = float(brier_score_loss(y_test, probs))
    except Exception:
        out["brier"] = None
    return out


def run_experiment():
    X, y, feature_names = load_dataset()
    if len(y) < 50:
        raise RuntimeError("Dataset too small for experiment")

    # Time-aware split: train on first 80%, test on last 20%
    split_idx = int(len(y) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    results: Dict[str, Any] = {"generated_at": datetime.utcnow().isoformat(), "n_samples": int(len(y)), "split_idx": split_idx, "methods": {}}

    # Baseline: class_weight='balanced'
    base = RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=5, class_weight='balanced', random_state=42, n_jobs=-1)
    try:
        base.fit(X_train, y_train)
        results["methods"]["baseline_balanced"] = evaluate_model(base, X_test, y_test)
    except Exception as e:
        results["methods"]["baseline_balanced"] = {"error": str(e)}

    # SMOTE experiment
    SMOTE = safe_import_smote()
    if SMOTE is None:
        results["methods"]["smote"] = {"error": "imbalanced-learn not installed. Install with: pip install imbalanced-learn"}
    else:
        try:
            sm = SMOTE(random_state=42)
            X_res, y_res = sm.fit_resample(X_train, y_train)
            sm_clf = RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=5, class_weight=None, random_state=42, n_jobs=-1)
            sm_clf.fit(X_res, y_res)
            results["methods"]["smote"] = {"n_train_resampled": int(len(y_res)), **evaluate_model(sm_clf, X_test, y_test)}
        except Exception as e:
            results["methods"]["smote"] = {"error": str(e)}

    # Save results
    os.makedirs(LOGS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Wrote SMOTE experiment results to: {OUT}")
    return results


if __name__ == "__main__":
    try:
        res = run_experiment()
    except Exception as e:
        print(f"Experiment failed: {e}")
        raise
