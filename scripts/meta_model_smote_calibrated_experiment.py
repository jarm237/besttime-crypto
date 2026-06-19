"""
SMOTE + Calibrated Ensemble experiment.
- Uses EnsembleMetaModel from btc_scraper.ml_engine.meta_model
- Splits data sequentially into train/calib/test (70/15/15 as in train_meta_model)
- Applies SMOTE on the train set, fits ensemble, calibrates using PredefinedSplit on train+calib
- Evaluates on test for methods: uncalibrated ensemble (baseline), calibrated sigmoid, calibrated isotonic

Saves results to logs/meta_model_smote_calibrated_results.json
"""
from __future__ import annotations
import os
import sys
import json
from datetime import datetime
from typing import Dict, Any

# ensure project root import
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import PredefinedSplit

from btc_scraper.ml_engine.meta_model import EnsembleMetaModel, _load_records, _sort_records_by_time
from btc_scraper.ml_engine.feature_extractor import records_to_dataset

LOGS = os.path.join(ROOT, "logs")
OUT = os.path.join(LOGS, "meta_model_smote_calibrated_results.json")


def safe_import_smote():
    try:
        from imblearn.over_sampling import SMOTE
        return SMOTE
    except Exception:
        return None


def evaluate_probs(probs, y_true) -> Dict[str, Any]:
    out = {"roc_auc": None, "pr_auc": None, "brier": None}
    try:
        out["roc_auc"] = float(roc_auc_score(y_true, probs))
    except Exception:
        out["roc_auc"] = None
    try:
        out["pr_auc"] = float(average_precision_score(y_true, probs))
    except Exception:
        out["pr_auc"] = None
    try:
        out["brier"] = float(brier_score_loss(y_true, probs))
    except Exception:
        out["brier"] = None
    return out


def load_dataset():
    recs = _load_records()
    recs = _sort_records_by_time(recs)
    X_list, y_list, feature_names = records_to_dataset(recs)
    X = np.array(X_list)
    y = np.array(y_list)
    return X, y, feature_names


def run():
    X, y, feature_names = load_dataset()
    n = len(y)
    if n < 50:
        raise RuntimeError("Not enough data")

    split_idx_1 = int(n * 0.70)
    split_idx_2 = int(n * 0.85)

    X_train, X_calib, X_test = X[:split_idx_1], X[split_idx_1:split_idx_2], X[split_idx_2:]
    y_train, y_calib, y_test = y[:split_idx_1], y[split_idx_1:split_idx_2], y[split_idx_2:]

    results: Dict[str, Any] = {"generated_at": datetime.utcnow().isoformat(), "n_samples": int(n), "split": {"train": len(y_train), "calib": len(y_calib), "test": len(y_test)}, "methods": {}}

    # Build base EnsembleMetaModel
    ensemble = EnsembleMetaModel(n_estimators=200, calibration=None)

    # Fit baseline on full train (no SMOTE)
    try:
        ensemble.fit(X_train, y_train, cv=5)
        probs_baseline = ensemble.predict_proba(X_test)[:, 1]
        results["methods"]["ensemble_baseline"] = evaluate_probs(probs_baseline, y_test)
    except Exception as e:
        results["methods"]["ensemble_baseline"] = {"error": str(e)}

    # SMOTE + ensemble
    SMOTE = safe_import_smote()
    if SMOTE is None:
        results["methods"]["smote_calibrated"] = {"error": "imbalanced-learn not installed"}
        return results

    try:
        sm = SMOTE(random_state=42)
        X_res, y_res = sm.fit_resample(X_train, y_train)
        ensemble_sm = EnsembleMetaModel(n_estimators=200, calibration=None)
        ensemble_sm.fit(X_res, y_res, cv=5)

        # Uncalibrated SMOTE ensemble
        probs_sm_uncal = ensemble_sm.predict_proba(X_test)[:, 1]
        results["methods"]["smote_uncalibrated"] = {"n_train_resampled": int(len(y_res)), **evaluate_probs(probs_sm_uncal, y_test)}

        # Prepare for calibration using PredefinedSplit over X_res + X_calib
        X_calib_combined = np.vstack([X_res, X_calib])
        y_calib_combined = np.concatenate([y_res, y_calib])
        test_fold = np.concatenate([np.full(len(y_res), -1, dtype=int), np.zeros(len(y_calib), dtype=int)])
        ps = PredefinedSplit(test_fold)

        for method in ("sigmoid", "isotonic"):
            try:
                calibrator = CalibratedClassifierCV(estimator=ensemble_sm, method=method, cv=ps, n_jobs=-1)
                calibrator.fit(X_calib_combined, y_calib_combined)
                probs_cal = calibrator.predict_proba(X_test)[:, 1]
                results["methods"][f"smote_calibrated_{method}"] = evaluate_probs(probs_cal, y_test)
            except Exception as e:
                results["methods"][f"smote_calibrated_{method}"] = {"error": str(e)}
    except Exception as e:
        results["methods"]["smote_pipeline_error"] = {"error": str(e)}

    # Save
    os.makedirs(LOGS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Wrote results to: {OUT}")
    return results


if __name__ == "__main__":
    res = run()
    print(json.dumps(res, indent=2, ensure_ascii=False))
