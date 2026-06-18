"""
Run calibration experiment using 70/20/10 sequential split.
Saves report to `logs/calibration_70_20_10.json` and (optionally) saves the best calibrated model.
"""
import os
import sys
import json
from pathlib import Path
import numpy as np

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals_v2.json"
OUT = LOGS / "calibration_70_20_10.json"
MODEL_OUT = LOGS / "meta_model_calibrated_70_20_10.joblib"

sys.path.insert(0, str(BASE))

from btc_scraper.ml_engine.feature_extractor import records_to_dataset
from btc_scraper.ml_engine.meta_model import EnsembleMetaModel, compute_calibration_buckets

from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import PredefinedSplit
from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss
import joblib


def main():
    if not INPUT.exists():
        print(f"Missing input records: {INPUT}")
        return 1

    with open(INPUT, 'r', encoding='utf-8') as f:
        recs = json.load(f)

    # Sort records by timestamp if possible
    try:
        from btc_scraper.ml_engine.meta_model import _get_record_timestamp
        recs = sorted(recs, key=_get_record_timestamp)
    except Exception:
        pass

    X_list, y_list, feature_names = records_to_dataset(recs)
    X = np.array(X_list)
    y = np.array(y_list)
    n = len(y)
    if n < 30:
        print("Too few samples to run experiment")
        return 1

    train_n = int(n * 0.7)
    calib_n = int(n * 0.2)
    test_n = n - train_n - calib_n
    if test_n <= 0:
        print("Not enough samples for 70/20/10 split")
        return 1

    X_train = X[:train_n]
    y_train = y[:train_n]
    X_calib = X[train_n:train_n+calib_n]
    y_calib = y[train_n:train_n+calib_n]
    X_test = X[train_n+calib_n:]
    y_test = y[train_n+calib_n:]

    report = {
        'n_total': int(n),
        'split': {'train': train_n, 'calib': calib_n, 'test': int(test_n)},
        'feature_names': feature_names,
        'results': {},
    }

    # Base ensemble
    ensemble = EnsembleMetaModel(n_estimators=200)
    ensemble.fit(np.vstack([X_train, X_calib, X_test]), np.concatenate([y_train, y_calib, y_test]))

    # Fit on train only for calibration candidate
    ensemble_train = EnsembleMetaModel(n_estimators=200)
    ensemble_train.fit(X_train, y_train)

    # Evaluate uncalibrated on test
    try:
        probs_unc = ensemble_train.predict_proba(X_test)[:, 1]
        auc_unc = float(roc_auc_score(y_test, probs_unc)) if len(set(y_test)) > 1 else None
        brier_unc = float(brier_score_loss(y_test, probs_unc))
    except Exception:
        auc_unc = None
        brier_unc = None

    report['results']['uncalibrated'] = {'roc_auc': auc_unc, 'brier': brier_unc}

    best = {'method': None, 'error': float('inf'), 'metrics': None}

    for method in ('sigmoid', 'isotonic'):
        print(f"Trying calibration method: {method}")
        try:
            # Prepare PredefinedSplit where train part = -1, calib part = 0
            test_fold = np.concatenate([np.full(len(y_train), -1, dtype=int), np.zeros(len(y_calib), dtype=int)])
            calibrator = CalibratedClassifierCV(estimator=ensemble_train, method=method, cv=PredefinedSplit(test_fold), n_jobs=-1)
            X_stack = np.vstack([X_train, X_calib])
            y_stack = np.concatenate([y_train, y_calib])
            calibrator.fit(X_stack, y_stack)

            probs = calibrator.predict_proba(X_test)[:, 1]
            auc = float(roc_auc_score(y_test, probs)) if len(set(y_test)) > 1 else None
            brier = float(brier_score_loss(y_test, probs))
            buckets = compute_calibration_buckets(probs, ["WIN" if v == 1 else "LOSS" for v in y_test])
            # compute mean abs calibration error across buckets with values
            errs = [abs(v['calibration_error']) for v in buckets.values() if v.get('calibration_error') is not None]
            mean_err = float(np.mean(errs)) if errs else None

            report['results'][method] = {'roc_auc': auc, 'brier': brier, 'mean_calibration_error': mean_err, 'buckets': buckets}

            if mean_err is not None and mean_err < best['error']:
                best['method'] = method
                best['error'] = mean_err
                best['metrics'] = report['results'][method]
                # Save calibrated model
                try:
                    joblib.dump({'model': calibrator, 'features': feature_names}, MODEL_OUT)
                    report['saved_model'] = str(MODEL_OUT)
                except Exception as e:
                    report['saved_model_error'] = str(e)
        except Exception as e:
            report['results'][method] = {'error': str(e)}
            print(f"Calibration {method} failed: {e}")

    report['best'] = best

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report['best'], indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
