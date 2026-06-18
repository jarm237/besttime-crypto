"""
Periodic recalibration utility.
Run manually or schedule weekly. It trains an EnsembleMetaModel on all available
records, selects best calibrator (sigmoid/isotonic) using a sequential holdout,
and saves calibrated model with timestamp. Writes JSON report and appends to log.

Usage:
  python scripts/periodic_recalibration.py

Optional env var:
  RECALIBRATE_FORCE_SAVE=1  # force saving even if no improvement
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime
import time
import numpy as np

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals_v2.json"
LOGFILE = LOGS / "recalibration.log"

sys.path.insert(0, str(BASE))

from btc_scraper.ml_engine.feature_extractor import records_to_dataset
from btc_scraper.ml_engine.meta_model import EnsembleMetaModel, compute_calibration_buckets, _get_record_timestamp
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import PredefinedSplit
from sklearn.metrics import roc_auc_score, brier_score_loss
import joblib


def timestamp():
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def save_report(report, fname):
    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def append_log(line):
    with open(LOGFILE, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.utcnow().isoformat()} - {line}\n")


def main():
    start = time.time()
    if not INPUT.exists():
        print(f"Missing input: {INPUT}")
        return 1
    with open(INPUT, 'r', encoding='utf-8') as f:
        recs = json.load(f)

    # sort by timestamp if available
    try:
        recs = sorted(recs, key=_get_record_timestamp)
    except Exception:
        pass

    X_list, y_list, feature_names = records_to_dataset(recs)
    X = np.array(X_list)
    y = np.array(y_list)
    n = len(y)
    if n < 30:
        print("Too few samples for recalibration")
        return 1

    # Use sequential split: train 70%, calib 20%, test 10%
    train_n = int(n * 0.7)
    calib_n = int(n * 0.2)
    test_n = n - train_n - calib_n
    if test_n <= 0:
        # fallback to 80/10/10
        train_n = int(n * 0.8)
        calib_n = int(n * 0.1)
        test_n = n - train_n - calib_n

    X_train = X[:train_n]
    y_train = y[:train_n]
    X_calib = X[train_n:train_n+calib_n]
    y_calib = y[train_n:train_n+calib_n]
    X_test = X[train_n+calib_n:]
    y_test = y[train_n+calib_n:]

    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'n_total': int(n),
        'split': {'train': train_n, 'calib': calib_n, 'test': int(test_n)},
        'feature_names': feature_names,
        'results': {}
    }

    # Train base on train only
    clf = EnsembleMetaModel(n_estimators=200)
    clf.fit(X_train, y_train)

    # Baseline on test
    try:
        probs_unc = clf.predict_proba(X_test)[:, 1]
        report['results']['uncalibrated'] = {
            'roc_auc': float(roc_auc_score(y_test, probs_unc)) if len(set(y_test))>1 else None,
            'brier': float(brier_score_loss(y_test, probs_unc))
        }
    except Exception as e:
        report['results']['uncalibrated'] = {'error': str(e)}

    best = {'method': None, 'error': float('inf'), 'metrics': None, 'model_path': None}

    for method in ('sigmoid', 'isotonic'):
        try:
            test_fold = np.concatenate([np.full(len(y_train), -1, dtype=int), np.zeros(len(y_calib), dtype=int)])
            calibrator = CalibratedClassifierCV(estimator=clf, method=method, cv=PredefinedSplit(test_fold), n_jobs=-1)
            X_stack = np.vstack([X_train, X_calib])
            y_stack = np.concatenate([y_train, y_calib])
            calibrator.fit(X_stack, y_stack)

            probs = calibrator.predict_proba(X_test)[:, 1]
            auc = float(roc_auc_score(y_test, probs)) if len(set(y_test))>1 else None
            brier = float(brier_score_loss(y_test, probs))
            buckets = compute_calibration_buckets(probs, ["WIN" if v==1 else "LOSS" for v in y_test])
            errs = [abs(v['calibration_error']) for v in buckets.values() if v.get('calibration_error') is not None]
            mean_err = float(np.mean(errs)) if errs else None

            report['results'][method] = {'roc_auc': auc, 'brier': brier, 'mean_calibration_error': mean_err, 'buckets': buckets}

            if mean_err is not None and mean_err < best['error']:
                best['method'] = method
                best['error'] = mean_err
                best['metrics'] = report['results'][method]
                # save
                model_name = f"meta_model_calibrated_periodic_{timestamp()}.joblib"
                model_path = LOGS / model_name
                try:
                    joblib.dump({'model': calibrator, 'features': feature_names}, model_path)
                    best['model_path'] = str(model_path)
                except Exception as e:
                    report.setdefault('errors', []).append(str(e))
        except Exception as e:
            report['results'][method] = {'error': str(e)}

    report['best'] = best
    elapsed = time.time() - start
    report['elapsed_s'] = elapsed

    report_fname = LOGS / f"recalibration_{timestamp()}.json"
    save_report(report, report_fname)
    append_log(f"Recalibration run saved: {report_fname} best={best['method']} error={best['error']}")

    # Also write a short summary file latest
    save_report({'last_run': report}, LOGS / 'recalibration_latest.json')

    # Optional: auto-commit artifact to git when AUTO_COMMIT=1
    try:
        auto_commit = os.getenv('AUTO_COMMIT', '0') == '1'
        if auto_commit and best.get('model_path'):
            model_path = best['model_path']
            # run git add/commit/push
            import subprocess
            commit_msg = f"Auto: recalibrated meta model ({best.get('method')}) {timestamp()}"
            try:
                subprocess.run(['git', 'add', model_path, str(report_fname)], check=True)
                subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
                subprocess.run(['git', 'push'], check=True)
                append_log(f"Auto-commit succeeded for {model_path}")
            except Exception as e:
                append_log(f"Auto-commit failed: {e}")
    except Exception:
        pass

    print(json.dumps({'best': best, 'report': str(report_fname)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
