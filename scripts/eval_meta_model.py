"""
Evaluate meta model: compute ROC-AUC, PR-AUC, precision/recall, Brier score
and measure inference latency. Saves results to `logs/meta_model_eval_results.json`.
"""
import os
import sys
import time
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
MODEL_PATH = LOGS / "meta_model.joblib"
INPUT = LOGS / "adaptive_signals_v2.json"
OUT = LOGS / "meta_model_eval_results.json"


def main():
    try:
        import joblib
        import numpy as np
        from sklearn.metrics import roc_auc_score, accuracy_score, precision_recall_fscore_support, brier_score_loss, average_precision_score
    except Exception as e:
        print("Missing dependency:", e)
        return 2

    if not MODEL_PATH.exists():
        print(f"Model not found: {MODEL_PATH}")
        return 1
    if not INPUT.exists():
        print(f"Input records not found: {INPUT}")
        return 1

    print("Loading model...")
    # Ensure project root is on sys.path so unpickling can import local modules
    sys.path.insert(0, str(BASE))
    bundle = joblib.load(MODEL_PATH)
    model = bundle.get("model") if isinstance(bundle, dict) else bundle
    selected_features = bundle.get("features") if isinstance(bundle, dict) else None

    print("Loading records and extracting features...")
    with open(INPUT, "r", encoding="utf-8") as f:
        recs = json.load(f)

    # Use feature extractor from repository
    try:
        from btc_scraper.ml_engine.feature_extractor import records_to_dataset
    except Exception as e:
        print("Failed to import feature_extractor:", e)
        return 1

    X_list, y_list, feature_names = records_to_dataset(recs)
    if not X_list or not y_list:
        print("No data extracted from records.")
        return 1

    X = np.array(X_list)
    y = np.array(y_list)

    # Align features if model saved subset
    if selected_features:
        try:
            idxs = [feature_names.index(f) for f in selected_features]
            X_sel = X[:, idxs]
            feat_used = selected_features
        except Exception:
            # fallback: use full X
            X_sel = X
            feat_used = feature_names
    else:
        X_sel = X
        feat_used = feature_names

    # Compute predictions
    print("Computing predictions and metrics...")
    try:
        # If we have feature names used by the model, present X as DataFrame
        if feat_used:
            import pandas as _pd

            X_input = _pd.DataFrame(X_sel, columns=feat_used)
        else:
            X_input = X_sel

        probs = model.predict_proba(X_input)
        if probs.ndim == 1:
            probs = np.column_stack([1.0 - probs, probs])
        prob_pos = probs[:, 1]
        preds = (prob_pos >= 0.5).astype(int)
    except Exception as e:
        print("Model predict_proba failed:", e)
        try:
            if feat_used:
                import pandas as _pd

                X_input = _pd.DataFrame(X_sel, columns=feat_used)
            else:
                X_input = X_sel
            preds = model.predict(X_input)
            prob_pos = None
        except Exception as e2:
            print("Model predict failed:", e2)
            return 1

    results = {}
    try:
        if prob_pos is not None and len(set(y)) > 1:
            results['roc_auc'] = float(roc_auc_score(y, prob_pos))
            results['pr_auc'] = float(average_precision_score(y, prob_pos))
            results['brier'] = float(brier_score_loss(y, prob_pos))
        else:
            results['roc_auc'] = None
            results['pr_auc'] = None
            results['brier'] = None
    except Exception as e:
        print("Metric computation failed:", e)

    try:
        results['accuracy'] = float(accuracy_score(y, preds))
        prec, rec, f1, _ = precision_recall_fscore_support(y, preds, average='binary', zero_division=0)
        results['precision'] = float(prec)
        results['recall'] = float(rec)
        results['f1'] = float(f1)
    except Exception as e:
        print("Classification metrics failed:", e)

    # Inference latency (average per-sample) — warmup + timed runs
    print("Measuring inference latency...")
    n_warm = 3
    n_runs = 20
    # small batch size for per-sample measurement
    batch = X_sel[: min(128, len(X_sel))]
    # warmup
    if feat_used:
        import pandas as _pd

        batch_input = _pd.DataFrame(batch, columns=feat_used)
    else:
        batch_input = batch

    for _ in range(n_warm):
        try:
            _ = model.predict_proba(batch_input)
        except Exception:
            _ = model.predict(batch_input)
    # timed
    t0 = time.perf_counter()
    for _ in range(n_runs):
        try:
            _ = model.predict_proba(batch_input)
        except Exception:
            _ = model.predict(batch_input)
    t1 = time.perf_counter()
    total_calls = n_runs
    elapsed = t1 - t0
    avg_batch = elapsed / total_calls
    avg_per_sample = avg_batch / max(1, batch.shape[0])

    results['latency'] = {
        'batch_size': int(batch.shape[0]),
        'runs': n_runs,
        'total_time_s': elapsed,
        'avg_batch_time_s': avg_batch,
        'avg_per_sample_s': avg_per_sample,
    }

    results['n_samples'] = int(len(y))
    results['n_features_extracted'] = int(len(feature_names))
    results['n_features_used'] = int(X_sel.shape[1])
    results['features_used'] = feat_used

    print("Saving results to:", OUT)
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("Failed to save results:", e)
        return 1

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
