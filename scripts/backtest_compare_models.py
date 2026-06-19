"""
Compare backtest PnL between current production `meta_model.joblib` (baseline)
and a SMOTE-trained + sigmoid-calibrated meta model.

Steps:
 - Backup existing logs/meta_model.joblib
 - Copy backup to logs/meta_model_baseline.joblib
 - Train SMOTE+sigmoid calibrated model and save to logs/meta_model_smote_sigmoid.joblib
 - For each candidate model, copy it into logs/meta_model.joblib and run `python backtest.py`
 - Save results to logs/backtest_comparison_<timestamp>.json
 - Restore original meta_model.joblib

Run: python scripts/backtest_compare_models.py
"""
from __future__ import annotations
import os
import sys
import json
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LOGS = os.path.join(ROOT, "logs")
os.makedirs(LOGS, exist_ok=True)
MODEL_OUT = os.path.join(LOGS, "meta_model.joblib")
BASELINE_OUT = os.path.join(LOGS, "meta_model_baseline.joblib")
SMOTE_OUT = os.path.join(LOGS, "meta_model_smote_sigmoid.joblib")
RESULT_OUT = os.path.join(LOGS, f"backtest_comparison_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json")

print("Preparing backtest comparison...")

# 1. Backup current model
backup = MODEL_OUT + ".bak"
if os.path.exists(MODEL_OUT):
    shutil.copy2(MODEL_OUT, backup)
    print(f"Backed up existing model to {backup}")

# 2. Ensure baseline copy exists
if os.path.exists(MODEL_OUT):
    shutil.copy2(MODEL_OUT, BASELINE_OUT)
    print(f"Saved baseline copy to {BASELINE_OUT}")
else:
    print("Warning: production meta_model.joblib not found. Baseline will be empty.")

# 3. Train SMOTE+sigmoid calibrated model and save to SMOTE_OUT
try:
    import numpy as np
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import PredefinedSplit
    from imblearn.over_sampling import SMOTE
    from btc_scraper.ml_engine.feature_extractor import records_to_dataset
    from btc_scraper.ml_engine.meta_model import EnsembleMetaModel
    from btc_scraper.ml_engine.meta_model import _load_records, _sort_records_by_time
    import joblib

    recs = _load_records()
    recs = _sort_records_by_time(recs)
    X_list, y_list, feature_names = records_to_dataset(recs)
    X = np.array(X_list)
    y = np.array(y_list)
    n = len(y)
    if n < 50:
        raise RuntimeError("Not enough data to train SMOTE model")

    split_idx_1 = int(n * 0.70)
    split_idx_2 = int(n * 0.85)
    X_train, X_calib, X_test = X[:split_idx_1], X[split_idx_1:split_idx_2], X[split_idx_2:]
    y_train, y_calib, y_test = y[:split_idx_1], y[split_idx_1:split_idx_2], y[split_idx_2:]

    sm = SMOTE(random_state=42)
    X_res, y_res = sm.fit_resample(X_train, y_train)

    ensemble_sm = EnsembleMetaModel(n_estimators=200, calibration=None)
    ensemble_sm.fit(X_res, y_res, cv=5)

    # Calibrate with PredefinedSplit
    X_calib_combined = np.vstack([X_res, X_calib])
    y_calib_combined = np.concatenate([y_res, y_calib])
    test_fold = np.concatenate([np.full(len(y_res), -1, dtype=int), np.zeros(len(y_calib), dtype=int)])
    ps = PredefinedSplit(test_fold)
    calibrator = CalibratedClassifierCV(estimator=ensemble_sm, method='sigmoid', cv=ps, n_jobs=-1)
    calibrator.fit(X_calib_combined, y_calib_combined)

    # Save calibrated estimator as model bundle compatible with meta_model.load_model()
    model_bundle = {
        "model": calibrator,
        "features": feature_names,
        "version": "v3.0",
        "n_samples": int(n),
        "calibrated": True,
    }
    joblib.dump(model_bundle, SMOTE_OUT)
    print(f"Saved SMOTE+sigmoid calibrated model to {SMOTE_OUT}")
except Exception as e:
    print(f"Failed to train/save SMOTE model: {e}")

# 4. Run backtest for each candidate
candidates = [
    {"name": "baseline", "path": BASELINE_OUT},
    {"name": "smote_sigmoid", "path": SMOTE_OUT},
]
results = {"generated_at": datetime.utcnow().isoformat(), "runs": []}

for cand in candidates:
    name = cand["name"]
    path = cand["path"]
    run_entry = {"name": name, "model_path": path}
    if not os.path.exists(path):
        run_entry["error"] = "model file missing"
        results["runs"].append(run_entry)
        continue

    # copy candidate to MODEL_OUT
    try:
        shutil.copy2(path, MODEL_OUT)
    except Exception as e:
        run_entry["error"] = f"copy_failed: {e}"
        results["runs"].append(run_entry)
        continue

    # Run backtest
    print(f"Running backtest with model: {name}...")
    rc = os.system(f"python backtest.py")
    run_entry["exit_code"] = int(rc)
    # Attempt to read logs/backtest_trades.csv and summary from printed output saved; return value of backtest printed to console
    # For now capture exit code and include path to trade log
    trade_log_path = os.path.join(LOGS, "backtest_trades.csv")
    run_entry["trade_log"] = trade_log_path
    # Copy trade log to per-run file to preserve results
    try:
        if os.path.exists(trade_log_path):
            per_run = os.path.join(LOGS, f"backtest_trades_{name}.csv")
            shutil.copy2(trade_log_path, per_run)
            run_entry["trade_log_copy"] = per_run
    except Exception:
        pass
    results["runs"].append(run_entry)

# 5. Restore original model
if os.path.exists(backup):
    try:
        shutil.copy2(backup, MODEL_OUT)
        print("Restored original meta_model.joblib from backup")
    except Exception as e:
        print(f"Failed to restore original model: {e}")

# 6. Save results
with open(RESULT_OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Saved comparison results to {RESULT_OUT}")

print("Done.")
