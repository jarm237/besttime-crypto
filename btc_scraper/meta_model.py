"""
Meta Model (confidence layer) for adaptive trading system.

Provides training and prediction utilities using FEATURE_SCHEMA from feature_extractor.
Train reads `logs/adaptive_signals.json` and learns a binary label (win vs loss).

Usage:
  python -m btc_scraper.meta_model --train
  python -m btc_scraper.meta_model --train --n 200
"""
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.calibration import CalibratedClassifierCV

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals.json"
MODEL_OUT = LOGS / "meta_model.joblib"
METRIC_OUT = LOGS / "meta_model.json"
FEATURE_IMPORTANCE_OUT = LOGS / "meta_feature_importance.json"

# Schema version — tăng lên khi đổi FEATURE_SCHEMA
MODEL_VERSION = "v1.0"


def _load_records():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing {INPUT}")
    with open(INPUT, "r", encoding="utf-8") as f:
        return json.load(f)


def train_meta_model(n_estimators: int = 200, cv: int = 5, calibrate: bool = True):
    """
    Train RandomForest Meta Model trên adaptive_signals.json.
    
    Dùng FEATURE_SCHEMA cố định từ feature_extractor.build_meta_features().
    Lưu model, metrics và feature importance.
    
    Args:
        n_estimators: số cây RandomForest
        cv: số fold cross-validation
        calibrate: có dùng Platt scaling để calibrate probability không
    
    Returns:
        dict với metrics
    """
    from btc_scraper.feature_extractor import FEATURE_SCHEMA, records_to_dataset

    recs = _load_records()
    X_list, y_list, feature_names = records_to_dataset(recs)

    if len(y_list) < 30:
        raise RuntimeError(
            f"Chỉ có {len(y_list)} samples. Cần ít nhất 30 để train."
        )

    X = np.array(X_list)
    y = np.array(y_list)

    print(f"  Training với {len(y)} samples, {len(feature_names)} features")
    print(f"  Label distribution: WIN={y.sum()}, LOSS={len(y)-y.sum()}")

    # Base RandomForest
    base_clf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    # Cross-validation
    skf = StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
    try:
        aucs = cross_val_score(base_clf, X, y, cv=skf, scoring="roc_auc")
        accs = cross_val_score(base_clf, X, y, cv=skf, scoring="accuracy")
        cv_auc_mean = float(np.mean(aucs))
        cv_auc_std = float(np.std(aucs))
        cv_acc_mean = float(np.mean(accs))
    except Exception as e:
        print(f"  [Warning] CV failed: {e}")
        cv_auc_mean = cv_auc_std = cv_acc_mean = None

    # Fit base model
    base_clf.fit(X, y)

    # Calibration (Platt scaling) để probability có ý nghĩa thực sự
    if calibrate and len(y) >= 50:
        try:
            # Dùng CalibratedClassifierCV với cv=5 (không dùng prefit)
            # Fit từ đầu với calibration built-in
            clf = CalibratedClassifierCV(
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=8,
                    min_samples_leaf=5,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                ),
                method="sigmoid",
                cv=5,
            )
            clf.fit(X, y)
            print("  [OK] Probability calibration (Platt/sigmoid) applied.")
        except Exception as e:
            print(f"  [Warning] Calibration failed, dung base model: {e}")
            clf = base_clf
    else:
        clf = base_clf

    # Feature importance (chỉ có ở base RF, không có ở calibrated wrapper)
    feature_importance = {}
    try:
        if hasattr(base_clf, "feature_importances_"):
            importances = base_clf.feature_importances_
            feature_importance = dict(
                sorted(
                    zip(feature_names, importances.tolist()),
                    key=lambda x: x[1],
                    reverse=True,
                )
            )
    except Exception:
        pass

    # Lưu model
    model_bundle = {
        "model": clf,
        "features": feature_names,
        "version": MODEL_VERSION,
        "n_samples": int(len(y)),
        "calibrated": calibrate and len(y) >= 50,
    }
    LOGS.mkdir(exist_ok=True)
    joblib.dump(model_bundle, MODEL_OUT)

    # Lưu metrics
    metrics = {
        "version": MODEL_VERSION,
        "n_samples": int(len(y)),
        "n_features": len(feature_names),
        "features": feature_names,
        "cv_auc_mean": cv_auc_mean,
        "cv_auc_std": cv_auc_std,
        "cv_acc_mean": cv_acc_mean,
        "calibrated": calibrate and len(y) >= 50,
        "label_dist": {"WIN": int(y.sum()), "LOSS": int(len(y) - y.sum())},
    }
    with open(METRIC_OUT, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    # Lưu feature importance
    if feature_importance:
        with open(FEATURE_IMPORTANCE_OUT, "w", encoding="utf-8") as f:
            json.dump(feature_importance, f, indent=2, ensure_ascii=False)
        print("\n  📊 Feature Importance:")
        for feat, imp in list(feature_importance.items())[:8]:
            bar = "█" * int(imp * 40)
            print(f"    {feat:<30} {imp:.4f} {bar}")

    return metrics


_MODEL_CACHE = None


def load_model():
    """Load model từ file. Trả về None nếu chưa có."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    if not MODEL_OUT.exists():
        return None
    try:
        _MODEL_CACHE = joblib.load(MODEL_OUT)
        # Optimize n_jobs to avoid multiprocessing overhead on single-row predictions
        if isinstance(_MODEL_CACHE, dict) and "model" in _MODEL_CACHE:
            clf = _MODEL_CACHE["model"]
            if hasattr(clf, "calibrated_classifiers_") and clf.calibrated_classifiers_:
                for c in clf.calibrated_classifiers_:
                    if hasattr(c, "estimator") and hasattr(c.estimator, "n_jobs"):
                        c.estimator.n_jobs = 1
            elif hasattr(clf, "n_jobs"):
                clf.n_jobs = 1
        return _MODEL_CACHE
    except Exception:
        return None


def predict_meta_confidence(analysis_info: dict) -> dict:
    """
    Predict win probability cho một tín hiệu.
    
    Args:
        analysis_info: analysis dict từ analyze_market() hoặc dict có các fields cần thiết.
                       Nên là output trực tiếp từ analyze_market() để có đủ features.
    
    Returns:
        dict với keys:
        - 'probability': float 0-1 (xác suất thắng)
        - 'error': str (nếu model chưa train hoặc lỗi)
    """
    from btc_scraper.feature_extractor import FEATURE_SCHEMA, build_meta_features

    obj = load_model()
    if obj is None:
        return {"error": "no_model", "probability": None}

    clf = obj.get("model") if isinstance(obj, dict) else obj
    feature_names = obj.get("features", FEATURE_SCHEMA) if isinstance(obj, dict) else FEATURE_SCHEMA

    try:
        feat = build_meta_features(analysis_info)
        row = [float(feat.get(k, 0.0)) for k in feature_names]
        prob = float(clf.predict_proba([row])[0, 1])
        return {"probability": prob}
    except Exception as e:
        return {"error": str(e), "probability": None}


def get_feature_importance() -> dict:
    """Load feature importance từ file. Trả về {} nếu chưa có."""
    if not FEATURE_IMPORTANCE_OUT.exists():
        return {}
    try:
        with open(FEATURE_IMPORTANCE_OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_model_metrics() -> dict:
    """Load model metrics từ file. Trả về {} nếu chưa có."""
    if not METRIC_OUT.exists():
        return {}
    try:
        with open(METRIC_OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true", help="Train meta model")
    p.add_argument("--n", type=int, default=200, help="So cay RandomForest")
    p.add_argument("--no-calibrate", action="store_true", help="Tat Platt calibration")
    args = p.parse_args()

    if args.train:
        print("[Meta Model] Training RandomForest...")
        try:
            m = train_meta_model(n_estimators=args.n, calibrate=not args.no_calibrate)
            print(f"\n[OK] Model saved to {MODEL_OUT}")
            print(f"   Samples: {m['n_samples']}")
            if m.get("cv_auc_mean"):
                print(f"   CV AUC: {m['cv_auc_mean']:.4f} +/- {m.get('cv_auc_std', 0):.4f}")
            if m.get("cv_acc_mean"):
                print(f"   CV Acc: {m['cv_acc_mean']:.4f}")
        except Exception as e:
            print(f"[ERROR] Training failed: {e}")
    else:
        print("Run voi --train de train Meta Model")
        metrics = get_model_metrics()
        if metrics:
            print(f"\nModel hien tai ({metrics.get('version', 'unknown')}):")
            print(f"  Samples: {metrics.get('n_samples', 'N/A')}")
            print(f"  CV AUC: {metrics.get('cv_auc_mean', 'N/A')}")
