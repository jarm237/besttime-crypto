"""
Meta Model (confidence layer) for adaptive trading system.

Provides training and prediction utilities using FEATURE_SCHEMA from feature_extractor.
Train reads `logs/adaptive_signals.json` and learns a binary label (win vs loss).

Usage:
  python -m btc_scraper.meta_model --train
  python -m btc_scraper.meta_model --train --n 200
"""
import sys
import json
import os
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Force stdout/stderr to UTF-8 to support Vietnamese characters in Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit, cross_val_score, PredefinedSplit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.base import BaseEstimator, ClassifierMixin

BASE = Path(__file__).parent.parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals_v2.json"
MODEL_OUT = LOGS / "meta_model.joblib"
MODEL_CANDIDATE_OUT = LOGS / "meta_model_candidate.joblib"
METRIC_OUT = LOGS / "meta_model.json"
FEATURE_IMPORTANCE_OUT = LOGS / "meta_feature_importance.json"

# Schema version — tăng lên khi đổi FEATURE_SCHEMA
MODEL_VERSION = "v3.1"

# AUC gates:
# Candidate: phải pass ngưỡng tối thiểu, được lưu vào candidate file.
# Production: chỉ ghi đè production nếu vượt ngưỡng này VÀ không tệ hơn model cũ.
_MIN_CANDIDATE_AUC = 0.50
_MIN_PRODUCTION_AUC = 0.56


def should_replace_model(
    candidate_auc: float,
    production_auc: "float | None",
    min_auc: float = _MIN_PRODUCTION_AUC,
    max_regression: float = 0.01,
) -> "tuple[bool, list[str]]":
    """Kiểm tra candidate có đủ điều kiện ghi đè production model không.

    Returns:
        (should_replace, list_of_failure_reasons)
    """
    reasons: list[str] = []
    if candidate_auc < min_auc:
        reasons.append(f"candidate_auc_{candidate_auc:.4f}_below_min_{min_auc:.2f}")
    if production_auc is not None and candidate_auc < production_auc - max_regression:
        reasons.append(
            f"candidate_{candidate_auc:.4f}_worse_than_production_{production_auc:.4f}_by_more_than_{max_regression}"
        )
    return not reasons, reasons



def compute_calibration_buckets(probs, actual_results, min_samples=3):
    buckets = {
        "0.0-0.4": [],
        "0.4-0.6": [],
        "0.6-0.7": [],
        "0.7-0.8": [],
        "0.8-1.0": [],
    }

    for prob, res in zip(probs, actual_results):
        label = 1 if res == "WIN" else 0
        if prob < 0.4:
            buckets["0.0-0.4"].append(label)
        elif prob < 0.6:
            buckets["0.4-0.6"].append(label)
        elif prob < 0.7:
            buckets["0.6-0.7"].append(label)
        elif prob < 0.8:
            buckets["0.7-0.8"].append(label)
        else:
            buckets["0.8-1.0"].append(label)

    analysis = {}
    for bucket, labels in buckets.items():
        if len(labels) < min_samples:
            analysis[bucket] = {
                "count": len(labels),
                "actual_wr": None,
                "predicted_wr": None,
                "calibration_error": None,
                "calibrated": False,
            }
            continue

        wins = sum(labels)
        actual_wr = wins / len(labels) * 100
        parts = bucket.split("-")
        lo, hi = float(parts[0]), float(parts[1])
        predicted_wr = (lo + hi) / 2 * 100
        error = actual_wr - predicted_wr
        calibrated = abs(error) <= 10.0

        analysis[bucket] = {
            "count": len(labels),
            "wins": wins,
            "losses": len(labels) - wins,
            "actual_wr": round(actual_wr, 1),
            "predicted_wr": round(predicted_wr, 1),
            "calibration_error": round(error, 1),
            "calibrated": calibrated,
        }
    return analysis


def _load_records():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing {INPUT}")
    with open(INPUT, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_record_timestamp(record: dict) -> float:
    ts = record.get("timestamp")
    if ts is not None:
        try:
            return float(ts)
        except Exception:
            pass
    entry_time = record.get("entry_time") or record.get("timestamp_str")
    if entry_time:
        try:
            return float(datetime.fromisoformat(entry_time).timestamp())
        except Exception:
            try:
                return float(datetime.strptime(entry_time, "%Y-%m-%d %H:%M").timestamp())
            except Exception:
                return 0.0
    return 0.0


def _sort_records_by_time(records: list[dict]) -> list[dict]:
    return sorted(records, key=_get_record_timestamp)


def _import_optional_estimators():
    estimators = {}
    try:
        from lightgbm import LGBMClassifier
        estimators["lgbm"] = LGBMClassifier
    except Exception:
        pass
    try:
        from catboost import CatBoostClassifier
        estimators["catboost"] = CatBoostClassifier
    except Exception:
        pass
    try:
        from xgboost import XGBClassifier
        estimators["xgboost"] = XGBClassifier
    except Exception:
        pass
    return estimators


def _get_backend_kwargs(backend: str, use_gpu: bool = False, device_id: int = 0) -> dict:
    if not use_gpu:
        return {}
    if backend == "lgbm":
        return {
            "device": "gpu",
            "gpu_platform_id": 0,
            "gpu_device_id": device_id,
        }
    if backend == "catboost":
        return {
            "task_type": "GPU",
            "devices": f"{device_id}",
        }
    if backend == "xgboost":
        device = "gpu" if device_id == 0 else f"gpu:{device_id}"
        return {
            "tree_method": "hist",
            "device": device,
        }
    return {}


def _make_lgbm_classifier(n_estimators: int = 200, random_state: int = 42, use_gpu: bool = False, device_id: int = 0, **overrides):
    optional = _import_optional_estimators()
    if "lgbm" not in optional:
        raise ImportError("LightGBM is required for Meta Model v3.1 training.")
    params = {
        "n_estimators": n_estimators,
        "max_depth": 5,
        "num_leaves": 31,
        "learning_rate": 0.03,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "class_weight": "balanced",
        "random_state": random_state,
        "n_jobs": -1,
        "verbosity": -1,
        "verbose": -1,
    }
    params.update(_get_backend_kwargs("lgbm", use_gpu=use_gpu, device_id=device_id))
    params.update(overrides)
    return optional["lgbm"](**params)


def _prepare_feature_matrix(X, feature_names=None):
    """Convert inference input into a feature-aligned DataFrame when possible."""
    if feature_names is None or len(feature_names) == 0:
        return np.asarray(X)

    try:
        import pandas as pd
    except Exception:
        return np.asarray(X)

    if isinstance(X, pd.DataFrame):
        return X

    X_arr = np.asarray(X)
    if X_arr.ndim == 1:
        return pd.DataFrame([X_arr], columns=feature_names)
    return pd.DataFrame(X_arr, columns=feature_names)


def _supports_feature_names(model) -> bool:
    """Return True when the estimator can safely consume pandas DataFrames with feature names."""
    if model is None:
        return False
    if hasattr(model, "feature_names_in_"):
        return True
    if hasattr(model, "steps"):
        return any(_supports_feature_names(step) for _, step in model.steps)
    if hasattr(model, "estimator"):
        return _supports_feature_names(model.estimator)
    if hasattr(model, "base_estimator"):
        return _supports_feature_names(model.base_estimator)
    if hasattr(model, "calibrated_classifiers_"):
        return any(_supports_feature_names(cls) for cls in model.calibrated_classifiers_)
    return False


def model_predict_proba(model, X, feature_names=None, *args, **kwargs):
    """Run predict_proba while preserving feature names when available."""
    if feature_names is None or len(feature_names) == 0 or not _supports_feature_names(model):
        prepared = np.asarray(X)
    else:
        prepared = _prepare_feature_matrix(X, feature_names)
    return model.predict_proba(prepared, *args, **kwargs)


def model_predict(model, X, feature_names=None, *args, **kwargs):
    """Run predict while preserving feature names when available."""
    if feature_names is None or len(feature_names) == 0 or not _supports_feature_names(model):
        prepared = np.asarray(X)
    else:
        prepared = _prepare_feature_matrix(X, feature_names)
    return model.predict(prepared, *args, **kwargs)


class _InferenceWrapper:
    def __init__(self, estimator, feature_names):
        self._estimator = estimator
        self._feature_names = feature_names

    def __getattr__(self, name):
        return getattr(self._estimator, name)

    def _prepare(self, X):
        if _supports_feature_names(self._estimator):
            return _prepare_feature_matrix(X, self._feature_names)
        return np.asarray(X)

    def predict_proba(self, X, *args, **kwargs):
        return self._estimator.predict_proba(self._prepare(X), *args, **kwargs)

    def predict(self, X, *args, **kwargs):
        return self._estimator.predict(self._prepare(X), *args, **kwargs)


def _build_estimators(n_estimators: int = 200, random_state: int = 42, use_gpu: bool = False, device_id: int = 0) -> dict:
    estimators = {}
    optional = _import_optional_estimators()
    if "lgbm" in optional:
        estimators["lgbm"] = _make_lgbm_classifier(
            n_estimators=n_estimators,
            random_state=random_state,
            use_gpu=use_gpu,
            device_id=device_id,
        )
    if "catboost" in optional:
        catboost_params = {
            "iterations": n_estimators,
            "depth": 5,
            "learning_rate": 0.03,
            "l2_leaf_reg": 3,
            "verbose": 0,
            "thread_count": -1,
            "random_seed": random_state,
        }
        catboost_params.update(_get_backend_kwargs("catboost", use_gpu=use_gpu, device_id=device_id))
        estimators["catboost"] = optional["catboost"](**catboost_params)
    if "xgboost" in optional:
        xgboost_params = {
            "n_estimators": n_estimators,
            "max_depth": 5,
            "learning_rate": 0.03,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "eval_metric": "logloss",
            "n_jobs": -1,
            "random_state": random_state,
        }
        xgboost_params.update(_get_backend_kwargs("xgboost", use_gpu=use_gpu, device_id=device_id))
        estimators["xgboost"] = optional["xgboost"](**xgboost_params)
    return estimators


def _normalize_weights(weights: dict, available: list[str]) -> list[float]:
    selected = {k: weights[k] for k in available if k in weights}
    total = sum(selected.values())
    if total <= 0:
        return [1.0 / len(available)] * len(available)
    return [selected[k] / total for k in available]


def _safe_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _normalize_probability(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _extract_tp_sl_profile(analysis_info: dict) -> dict:
    tp_sl = analysis_info.get("tp_sl") if isinstance(analysis_info.get("tp_sl"), dict) else {}
    entry = _safe_float(
        tp_sl.get("entry") or analysis_info.get("entry") or analysis_info.get("close") or analysis_info.get("close_price"),
        0.0,
    )
    sl = _safe_float(tp_sl.get("sl") or analysis_info.get("sl"), 0.0)
    tp1 = _safe_float(tp_sl.get("tp1") or analysis_info.get("tp1"), 0.0)
    tp2 = _safe_float(tp_sl.get("tp2") or analysis_info.get("tp2"), 0.0)
    rr1 = _safe_float(tp_sl.get("rr1") or analysis_info.get("rr1"), 0.0)
    rr2 = _safe_float(tp_sl.get("rr2") or analysis_info.get("rr2"), 0.0)

    direction_text = str(analysis_info.get("action") or analysis_info.get("signal") or "").upper()
    is_short = any(token in direction_text for token in ("SELL", "SHORT", "BEAR"))
    is_long = any(token in direction_text for token in ("BUY", "LONG", "BULL"))
    if not is_short and not is_long:
        is_long = True

    if entry <= 0:
        entry = 1.0

    def to_pct(value: float) -> float:
        if value <= 0:
            return 0.0
        return abs((entry - value) / entry * 100.0) if is_short else abs((value - entry) / entry * 100.0)

    sl_pct = to_pct(sl) if sl > 0 else _safe_float(analysis_info.get("sl_pct") or analysis_info.get("stop_loss_pct"), 1.0)
    tp1_pct = to_pct(tp1) if tp1 > 0 else 0.0
    tp2_pct = to_pct(tp2) if tp2 > 0 else 0.0

    if tp1_pct <= 0.0 and rr1 > 0.0 and sl_pct > 0.0:
        tp1_pct = rr1 * sl_pct
    if tp2_pct <= 0.0 and rr2 > 0.0 and sl_pct > 0.0:
        tp2_pct = rr2 * sl_pct
    if tp1_pct <= 0.0 and tp2_pct > 0.0:
        tp1_pct = max(1.0, tp2_pct / 2.0)
    if tp2_pct <= 0.0 and tp1_pct > 0.0:
        tp2_pct = max(tp1_pct * 1.5, tp1_pct)
    if sl_pct <= 0.0:
        sl_pct = max(1.0, tp1_pct * 0.5)

    return {
        "entry": entry,
        "sl_pct": float(sl_pct),
        "tp1_pct": float(tp1_pct),
        "tp2_pct": float(tp2_pct),
        "direction": "SHORT" if is_short else "LONG",
    }


def _compute_expected_value_metrics(prob: float, analysis_info: dict) -> dict:
    prob = _normalize_probability(prob)
    profile = _extract_tp_sl_profile(analysis_info)

    tp1_prob = prob if profile["tp2_pct"] <= 0.0 else prob * 0.70
    tp2_prob = 0.0 if profile["tp2_pct"] <= 0.0 else prob * 0.30
    prob_sl = 1.0 - prob

    expected_return = (
        tp1_prob * profile["tp1_pct"]
        + tp2_prob * profile["tp2_pct"]
        - prob_sl * profile["sl_pct"]
    )
    expected_drawdown = prob_sl * profile["sl_pct"]
    expected_hold_time = _safe_float(
        analysis_info.get("expected_hold_time")
        or analysis_info.get("hold_hours")
        or analysis_info.get("hold_time")
        or analysis_info.get("hold_bars")
        or 4.0,
        4.0,
    )

    return {
        "expected_return": round(expected_return, 4),
        "expected_drawdown": round(expected_drawdown, 4),
        "expected_hold_time": round(expected_hold_time, 2),
        "prob_tp1": round(tp1_prob, 4),
        "prob_tp2": round(tp2_prob, 4),
        "prob_sl": round(prob_sl, 4),
        "tp1_pct": round(profile["tp1_pct"], 4),
        "tp2_pct": round(profile["tp2_pct"], 4),
        "sl_pct": round(profile["sl_pct"], 4),
        "ev": round(expected_return, 4),
    }


class EnsembleMetaModel(ClassifierMixin, BaseEstimator):
    def __init__(self, weights=None, calibration=None, n_estimators=200, random_state=42, base_params=None, use_gpu: bool = False, device_id: int = 0):
        self.weights = weights if weights is not None else {"lgbm": 0.33, "catboost": 0.33, "xgboost": 0.34}
        self.calibration = calibration  # "sigmoid", "isotonic" or None
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.base_params = base_params if base_params is not None else {}
        self.use_gpu = use_gpu
        self.device_id = device_id
        self.classes_ = np.array([0, 1])
        self.models_ = {}
        self.normalized_weights_ = {}
        self.feature_importances_ = None

    def fit(self, X, y, cv=5):
        X = np.array(X)
        y = np.array(y)
        self.classes_ = np.unique(y)

        # Import base classifiers optionally
        optional = _import_optional_estimators()
        
        # Set default base params and override with provided base_params
        lgbm_params = {"n_estimators": self.n_estimators, "max_depth": 5, "num_leaves": 31, "learning_rate": 0.03, "subsample": 0.8, "colsample_bytree": 0.8, "class_weight": "balanced", "random_state": self.random_state, "n_jobs": -1, "verbosity": -1, "verbose": -1}
        lgbm_params.update(self.base_params.get("lgbm", {}))
        lgbm_params.update(_get_backend_kwargs("lgbm", use_gpu=self.use_gpu, device_id=self.device_id))
        
        catboost_params = {"iterations": self.n_estimators, "depth": 5, "learning_rate": 0.03, "l2_leaf_reg": 3, "verbose": 0, "thread_count": -1, "random_seed": self.random_state}
        catboost_params.update(self.base_params.get("catboost", {}))
        catboost_params.update(_get_backend_kwargs("catboost", use_gpu=self.use_gpu, device_id=self.device_id))
        
        xgboost_params = {"n_estimators": self.n_estimators, "max_depth": 5, "learning_rate": 0.03, "subsample": 0.8, "colsample_bytree": 0.8, "eval_metric": "logloss", "n_jobs": -1, "random_state": self.random_state}
        xgboost_params.update(self.base_params.get("xgboost", {}))
        xgboost_params.update(_get_backend_kwargs("xgboost", use_gpu=self.use_gpu, device_id=self.device_id))

        estimators = {}
        if "lgbm" in optional:
            estimators["lgbm"] = optional["lgbm"](**lgbm_params)
        if "catboost" in optional:
            estimators["catboost"] = optional["catboost"](**catboost_params)
        if "xgboost" in optional:
            estimators["xgboost"] = optional["xgboost"](**xgboost_params)

        # Filter weights based on availability
        available_keys = [k for k in self.weights if k in estimators]
        if not available_keys:
            raise RuntimeError("No v3.1 ensemble estimators are available. Install lightgbm, catboost, or xgboost.")
            
        selected_weights = {k: self.weights[k] for k in available_keys}
        total_w = sum(selected_weights.values())
        if total_w <= 0:
            self.normalized_weights_ = {k: 1.0 / len(available_keys) for k in available_keys}
        else:
            self.normalized_weights_ = {k: v / total_w for k, v in selected_weights.items()}

        # Fit base models (with calibration if requested)
        self.models_ = {}
        for name in self.normalized_weights_:
            base_clf = estimators[name]
            if self.calibration in ("sigmoid", "isotonic"):
                model = CalibratedClassifierCV(estimator=base_clf, method=self.calibration, cv=cv)
            else:
                model = base_clf
            model.fit(X, y)
            self.models_[name] = model

        # Compute self.feature_importances_
        importances_list = []
        weights_list = []
        for name, model in self.models_.items():
            imp = None
            if hasattr(model, "calibrated_classifiers_"):
                cal_imps = []
                for cc in model.calibrated_classifiers_:
                    est = getattr(cc, "estimator", None)
                    if est is not None and hasattr(est, "feature_importances_"):
                        cal_imps.append(est.feature_importances_)
                if cal_imps:
                    imp = np.mean(cal_imps, axis=0)
            elif hasattr(model, "feature_importances_"):
                imp = model.feature_importances_

            if imp is not None:
                total_imp = np.sum(imp)
                if total_imp > 0:
                    imp = imp / total_imp
                importances_list.append(imp)
                weights_list.append(self.normalized_weights_[name])

        if importances_list:
            weighted_imp = np.zeros_like(importances_list[0])
            sum_w = sum(weights_list)
            if sum_w > 0:
                for imp, w in zip(importances_list, weights_list):
                    weighted_imp += imp * (w / sum_w)
            self.feature_importances_ = weighted_imp
        else:
            self.feature_importances_ = None

        return self

    def _prepare_for_model(self, model, X):
        if not isinstance(X, (np.ndarray, pd.DataFrame)):
            return np.asarray(X)
        return X

    def predict_proba(self, X):
        import warnings

        if not isinstance(X, (np.ndarray, pd.DataFrame)):
            X = np.asarray(X)

        n_samples = X.shape[0]
        combined_prob = np.zeros((n_samples, 2))
        for name, model in self.models_.items():
            w = self.normalized_weights_[name]
            x_input = self._prepare_for_model(model, X)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="X does not have valid feature names", category=UserWarning)
                probs = model.predict_proba(x_input)
            if probs.ndim == 1:
                probs = np.column_stack([1.0 - probs, probs])
            elif probs.shape[1] == 1:
                probs = np.column_stack([1.0 - probs[:, 0], probs[:, 0]])
            combined_prob += w * probs
        return combined_prob

    def predict(self, X):
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1)


def walk_forward_eval(X: np.ndarray, y: np.ndarray, clf=None, train_window_pct: float = 0.65, test_window_pct: float = 0.15, n_splits: int = 3):
    """Compute walk-forward ROC-AUC and accuracy on sequential train/test windows."""
    n = len(y)
    if n < 30:
        return []

    results = []
    step = int(n * test_window_pct)
    train_len = int(n * train_window_pct)
    if step < 1:
        step = 1

    start = 0
    while start + train_len + step <= n and len(results) < n_splits:
        train_end = start + train_len
        test_end = train_end + step
        X_train, y_train = X[start:train_end], y[start:train_end]
        X_test, y_test = X[train_end:test_end], y[train_end:test_end]

        if clf is None:
            model = _make_lgbm_classifier(n_estimators=200, random_state=42, max_depth=8)
        else:
            from sklearn.base import clone
            model = clone(clf)

        auc = None
        acc = None
        try:
            model.fit(X_train, y_train)
            if len(y_test) > 0 and len(set(y_test)) > 1:
                from sklearn.metrics import roc_auc_score, accuracy_score
                y_prob = model.predict_proba(X_test)[:, 1]
                y_pred = model.predict(X_test)
                auc = float(roc_auc_score(y_test, y_prob))
                acc = float(accuracy_score(y_test, y_pred))
        except Exception as _eval_err:
            import logging as _log
            _log.getLogger(__name__).warning("[meta_model] walk-forward evaluation failed at step: %s", _eval_err)

        results.append({
            "train_range": [start, train_end],
            "test_range": [train_end, test_end],
            "n_train": len(y_train),
            "n_test": len(y_test),
            "roc_auc": auc,
            "accuracy": acc,
        })
        start += step
    return results


def train_meta_model(n_estimators: int = 200, cv: int = 5, calibrate: bool = True, use_gpu: bool = False, device_id: int = 0):
    """
    Train the ensemble meta model on adaptive_signals.json.

    Uses fixed FEATURE_SCHEMA_V2 from feature_extractor.build_meta_features_v2().
    Saves model, metrics and feature importance.
    """
    from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA_V2, records_to_dataset

    recs = _load_records()
    recs = _sort_records_by_time(recs)
    X_list, y_list, feature_names = records_to_dataset(recs)

    if len(y_list) < 30:
        raise RuntimeError(f"Chỉ có {len(y_list)} samples. Cần ít nhất 30 để train.")

    X = np.array(X_list)
    y = np.array(y_list)

    print(f"  Training với {len(y)} samples, {len(feature_names)} features")
    print(f"  Label distribution: WIN={y.sum()}, LOSS={len(y)-y.sum()}")
    print(f"  [Backend] Meta-model training backend: {'GPU' if use_gpu else 'CPU'} (device_id={device_id})")

    # Determine CV splits
    cv_splits = min(cv, max(2, len(y) // 10))
    tscv = TimeSeriesSplit(n_splits=cv_splits)

    # 1. Quick pre-fit to identify and drop zero-importance features
    print("  [Pre-fit] Đang xác định features có tầm quan trọng = 0...")
    _prefit = _make_lgbm_classifier(n_estimators=100, random_state=42, max_depth=6, use_gpu=use_gpu, device_id=device_id)
    _prefit.fit(X, y)
    _importance = _prefit.feature_importances_
    selected_mask = _importance > 0.0
    selected_features = [f for f, keep in zip(feature_names, selected_mask) if keep]
    dropped_features  = [f for f, keep in zip(feature_names, selected_mask) if not keep]

    if dropped_features:
        print(f"  [Pre-fit] Loại bỏ {len(dropped_features)} features zero-importance: {dropped_features}")
        X = X[:, selected_mask]
        print(f"  [Pre-fit] Features còn lại: {len(selected_features)}")
    else:
        selected_features = list(feature_names)

    # 2. Base model CV (LGBM) for backward-compatible metric comparison
    base_clf = _make_lgbm_classifier(n_estimators=n_estimators, random_state=42, max_depth=8, use_gpu=use_gpu, device_id=device_id)
    try:
        aucs = cross_val_score(base_clf, X, y, cv=tscv, scoring="roc_auc")
        accs = cross_val_score(base_clf, X, y, cv=tscv, scoring="accuracy")
        cv_auc_mean = float(np.mean(aucs))
        cv_auc_std  = float(np.std(aucs))
        cv_acc_mean = float(np.mean(accs))
    except Exception as e:
        print(f"  [Warning] Base CV failed: {e}")
        cv_auc_mean = cv_auc_std = cv_acc_mean = None

    base_clf.fit(X, y)

    # 3. Optuna - boosting models + ensemble weights
    best_base_params: dict = {}
    best_weights: dict = {"lgbm": 0.33, "catboost": 0.33, "xgboost": 0.34}
    try:
        import optuna
        from sklearn.metrics import roc_auc_score
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        print("  [Optuna] Đang tìm kiếm siêu tham số tối ưu (40 trials)...")

        # Determine CV splits for Optuna objective
        optuna_tscv = TimeSeriesSplit(n_splits=3)

        def objective(trial):
            # ── LGBM ────────────────────────────────────────────────────
            lgbm_depth      = trial.suggest_int("lgbm_depth",      3, 7)
            lgbm_leaves     = trial.suggest_int("lgbm_num_leaves", 16, 63)
            lgbm_lr         = trial.suggest_float("lgbm_lr",       0.01, 0.15, log=True)
            lgbm_subsample  = trial.suggest_float("lgbm_subsample",0.6, 1.0)
            lgbm_colsample  = trial.suggest_float("lgbm_colsample",0.6, 1.0)

            # ── CatBoost ─────────────────────────────────────────────────
            cat_depth       = trial.suggest_int("cat_depth",       4, 7)
            cat_lr          = trial.suggest_float("cat_lr",        0.01, 0.1, log=True)
            cat_l2          = trial.suggest_float("cat_l2",        1.0, 10.0)

            # ── XGBoost ─────────────────────────────────────────────────
            xgb_depth       = trial.suggest_int("xgb_depth",      3, 7)
            xgb_lr          = trial.suggest_float("xgb_lr",       0.01, 0.15, log=True)
            xgb_subsample   = trial.suggest_float("xgb_subsample",0.6, 1.0)

            # ── Ensemble weights ─────────────────────────────────────────
            w_lgbm = trial.suggest_float("w_lgbm", 0.0, 1.0)
            w_cat  = trial.suggest_float("w_cat",  0.0, 1.0)
            w_xgb  = trial.suggest_float("w_xgb",  0.0, 1.0)
            if w_lgbm + w_cat + w_xgb == 0:
                return 0.0

            weights = {"lgbm": w_lgbm, "catboost": w_cat, "xgboost": w_xgb}
            bp = {
                "lgbm": {"max_depth": lgbm_depth, "num_leaves": lgbm_leaves,
                         "learning_rate": lgbm_lr, "subsample": lgbm_subsample,
                         "colsample_bytree": lgbm_colsample},
                "catboost": {"depth": cat_depth, "learning_rate": cat_lr, "l2_leaf_reg": cat_l2},
                "xgboost":  {"max_depth": xgb_depth, "learning_rate": xgb_lr, "subsample": xgb_subsample},
            }

            # Evaluate with TimeSeriesSplit to prevent overfitting
            fold_aucs = []
            for train_idx, val_idx in optuna_tscv.split(X):
                X_train, X_val = X[train_idx], X[val_idx]
                y_train, y_val = y[train_idx], y[val_idx]

                # Need both classes to compute ROC-AUC
                if len(np.unique(y_val)) < 2 or len(np.unique(y_train)) < 2:
                    continue

                model = EnsembleMetaModel(weights=weights, base_params=bp, n_estimators=80, use_gpu=use_gpu, device_id=device_id)
                try:
                    model.fit(X_train, y_train)
                    preds = model.predict_proba(X_val)[:, 1]
                    fold_aucs.append(float(roc_auc_score(y_val, preds)))
                except Exception as _fold_err:
                    import logging as _log
                    _log.getLogger(__name__).warning("[meta_model] fold training failed: %s", _fold_err)

            if not fold_aucs:
                return 0.0
            return float(np.mean(fold_aucs))

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=40)
        bp = study.best_params

        print(f"  [Optuna] Best Trial AUC : {study.best_value:.4f}")
        print(f"  [Optuna] Best Params    : {bp}")

        best_base_params = {
            "lgbm": {
                "max_depth": bp.get("lgbm_depth", 5),
                "num_leaves": bp.get("lgbm_num_leaves", 31),
                "learning_rate": bp.get("lgbm_lr", 0.03),
                "subsample": bp.get("lgbm_subsample", 0.8),
                "colsample_bytree": bp.get("lgbm_colsample", 0.8),
            },
            "catboost": {
                "depth": bp.get("cat_depth", 5),
                "learning_rate": bp.get("cat_lr", 0.03),
                "l2_leaf_reg": bp.get("cat_l2", 3.0),
            },
            "xgboost": {
                "max_depth": bp.get("xgb_depth", 5),
                "learning_rate": bp.get("xgb_lr", 0.03),
                "subsample": bp.get("xgb_subsample", 0.8),
            },
        }
        best_weights = {
            "lgbm": bp.get("w_lgbm", 0.33),
            "catboost": bp.get("w_cat", 0.33),
            "xgboost": bp.get("w_xgb", 0.34),
        }
    except ImportError:
        print("  [Optuna] Thư viện optuna chưa được cài đặt. Dùng hyperparameters mặc định.")
    except Exception as e:
        print(f"  [Optuna] Lỗi trong quá trình tối ưu: {e}. Dùng hyperparameters mặc định.")

    # 4. Ensemble CV on filtered feature matrix
    ensemble_clf = EnsembleMetaModel(
        weights=best_weights, base_params=best_base_params,
        calibration=None, n_estimators=n_estimators,
        use_gpu=use_gpu, device_id=device_id,
    )
    ensemble_cv_auc = None
    ensemble_cv_acc = None
    try:
        ensemble_aucs = cross_val_score(ensemble_clf, X, y, cv=tscv, scoring="roc_auc")
        ensemble_accs = cross_val_score(ensemble_clf, X, y, cv=tscv, scoring="accuracy")
        ensemble_cv_auc = float(np.mean(ensemble_aucs))
        ensemble_cv_acc = float(np.mean(ensemble_accs))
    except Exception as e:
        print(f"  [Warning] Ensemble CV failed: {e}")

    # 5. Calibration using separate hold-out calibration set
    clf = ensemble_clf
    calibration_method = None
    calibration_buckets = {}
    calibration_info = {
        "split": None,
        "selected_method": None,
        "selected_error": None,
    }

    if calibrate and len(y) >= 100:
        try:
            # Split train/calib/test sequentially for time-series consistency.
            split_idx_1 = int(len(y) * 0.70)
            split_idx_2 = int(len(y) * 0.85)
            X_train, X_calib, X_test = X[:split_idx_1], X[split_idx_1:split_idx_2], X[split_idx_2:]
            y_train, y_calib, y_test = y[:split_idx_1], y[split_idx_1:split_idx_2], y[split_idx_2:]

            calibration_info["split"] = {
                "train": len(y_train),
                "calib": len(y_calib),
                "test": len(y_test),
            }
            print(f"  [Calibration] Train={len(y_train)}, Calib={len(y_calib)}, Test={len(y_test)}")

            clf.fit(X_train, y_train)

            fitted_clf = clf
            best_calibrator = None
            best_method = None
            best_error = float("inf")
            best_buckets = {}

            for method in ("sigmoid", "isotonic"):
                try:
                    test_fold = np.concatenate([
                        np.full(len(y_train), -1, dtype=int),
                        np.zeros(len(y_calib), dtype=int),
                    ])
                    calibrator = CalibratedClassifierCV(
                        estimator=fitted_clf,
                        method=method,
                        cv=PredefinedSplit(test_fold),
                        n_jobs=-1,
                    )
                    calibrator.fit(np.vstack([X_train, X_calib]), np.concatenate([y_train, y_calib]))
                    probs_test = calibrator.predict_proba(X_test)[:, 1]
                    buckets = compute_calibration_buckets(
                        probs_test, ["WIN" if v == 1 else "LOSS" for v in y_test])
                    err = np.mean([
                        abs(v["calibration_error"]) for v in buckets.values()
                        if v.get("calibration_error") is not None])
                    print(f"    [Calibration] {method:<8} mean error={err:.3f}")
                    if err < best_error:
                        best_error = err
                        best_method = method
                        best_calibrator = calibrator
                        best_buckets = buckets
                except Exception as e:
                    print(f"    [Warning] Calibration {method} failed: {e}")

            if best_calibrator is not None:
                clf = best_calibrator
                calibration_method = best_method
                calibration_buckets = best_buckets
                calibration_info["selected_method"] = best_method
                calibration_info["selected_error"] = float(best_error)
                print(f"  [OK] Selected calibration method: {calibration_method}")
            else:
                print("  [Warning] No calibration method succeeded, using uncalibrated ensemble.")
                clf = fitted_clf
                clf.fit(X, y)
                probs = clf.predict_proba(X)[:, 1]
                calibration_buckets = compute_calibration_buckets(
                    probs, ["WIN" if v == 1 else "LOSS" for v in y])
        except Exception as e:
            print(f"  [Warning] Calibration failed, using uncalibrated ensemble: {e}")
            clf = ensemble_clf
            clf.fit(X, y)
            try:
                probs = clf.predict_proba(X)[:, 1]
                calibration_buckets = compute_calibration_buckets(
                    probs, ["WIN" if v == 1 else "LOSS" for v in y])
            except Exception:
                calibration_buckets = {}
    else:
        clf = ensemble_clf
        clf.fit(X, y)
        try:
            probs = clf.predict_proba(X)[:, 1]
            calibration_buckets = compute_calibration_buckets(
                probs, ["WIN" if v == 1 else "LOSS" for v in y])
        except Exception:
            calibration_buckets = {}

    LOGS.mkdir(exist_ok=True)
    model_bundle = {
        "model": clf,
        "features": selected_features,   # ← chỉ lưu features đã lọc
        "version": MODEL_VERSION,
        "n_samples": int(len(y)),
        "calibrated": calibrate and len(y) >= 50,
        "dropped_features": dropped_features,
        "optuna_weights": best_weights,
        "optuna_base_params": best_base_params,
    }

    # Performance gate — dùng local variable (cv_auc_mean / ensemble_cv_auc)
    # chứ không phải model_bundle.get() vì các key đó không được lưu vào bundle.
    _gate_auc = ensemble_cv_auc if ensemble_cv_auc is not None else cv_auc_mean

    # Load production AUC để so sánh
    _prod_auc: float | None = None
    try:
        _prod_metrics = json.load(open(METRIC_OUT, encoding="utf-8")) if METRIC_OUT.exists() else {}
        _prod_auc = _prod_metrics.get("ensemble_cv_auc_mean") or _prod_metrics.get("cv_auc_mean")
        if _prod_auc is not None:
            _prod_auc = float(_prod_auc)
    except Exception:
        _prod_auc = None

    import logging as _mlog
    _gate_logger = _mlog.getLogger(__name__)

    if _gate_auc is None:
        # Không có AUC → lưu thành candidate, không ghi đè production
        _gate_logger.warning("[meta_model] AUC unavailable — saving candidate only, NOT promoting to production")
        try:
            joblib.dump(model_bundle, MODEL_CANDIDATE_OUT)
        except Exception as _ce:
            _gate_logger.error("[meta_model] Failed to save candidate: %s", _ce)
    elif _gate_auc < _MIN_CANDIDATE_AUC:
        _gate_logger.warning(
            "[meta_model] Model NOT saved: AUC %.4f < candidate gate %.2f",
            _gate_auc, _MIN_CANDIDATE_AUC,
        )
    else:
        # Luôn lưu candidate
        try:
            joblib.dump(model_bundle, MODEL_CANDIDATE_OUT)
        except Exception as _ce:
            _gate_logger.warning("[meta_model] Failed to save candidate: %s", _ce)

        # Chỉ promote lên production nếu qua production gate
        _ok, _reasons = should_replace_model(_gate_auc, _prod_auc)
        if _ok:
            try:
                joblib.dump(model_bundle, MODEL_OUT)
                _gate_logger.info("[meta_model] Promoted to production: AUC %.4f", _gate_auc)
            except Exception as e:
                # Fallback: save to system temp directory (avoids potential FS encoding issues)
                try:
                    import tempfile, shutil
                    tmp_path = Path(tempfile.gettempdir()) / "meta_model.joblib"
                    joblib.dump(model_bundle, tmp_path)
                    try:
                        shutil.move(str(tmp_path), str(MODEL_OUT))
                    except Exception:
                        pass
                    print(f"  [Warning] Could not save model to {MODEL_OUT}. Saved to {tmp_path} instead: {e}")
                except Exception as e2:
                    print(f"  [ERROR] Failed to save model bundle to both MODEL_OUT and temp: {e} / {e2}")
        else:
            _gate_logger.warning(
                "[meta_model] Candidate AUC %.4f saved but NOT promoted to production. Reasons: %s",
                _gate_auc, _reasons,
            )

    # Update feature_names for downstream metric reporting
    feature_names = selected_features

    # 4. Feature Importance Extraction
    feature_importance = {}
    try:
        imp = None
        if hasattr(clf, "feature_importances_") and clf.feature_importances_ is not None:
            imp = clf.feature_importances_
        elif hasattr(ensemble_clf, "feature_importances_") and ensemble_clf.feature_importances_ is not None:
            imp = ensemble_clf.feature_importances_
        elif hasattr(base_clf, "feature_importances_"):
            imp = base_clf.feature_importances_

        if imp is not None:
            feature_importance = dict(sorted(zip(feature_names, imp.tolist()), key=lambda x: x[1], reverse=True))
    except Exception as e:
        print(f"  [Warning] Failed to extract feature importance: {e}")

    # Available keys and weights for metrics
    available_keys = list(clf.normalized_weights_.keys()) if hasattr(clf, "normalized_weights_") else list(ensemble_clf.normalized_weights_.keys())
    weights = list(clf.normalized_weights_.values()) if hasattr(clf, "normalized_weights_") else list(ensemble_clf.normalized_weights_.values())

    metrics = {
        "version": MODEL_VERSION,
        "n_samples": int(len(y)),
        "n_features": len(feature_names),
        "features": feature_names,
        "cv_auc_mean": cv_auc_mean,
        "cv_auc_std": cv_auc_std,
        "cv_acc_mean": cv_acc_mean,
        "ensemble_cv_auc_mean": ensemble_cv_auc,
        "ensemble_cv_acc_mean": ensemble_cv_acc,
        "ensemble_weights": {name: weight for name, weight in zip(available_keys, weights)},
        "available_models": available_keys,
        "calibration_method": calibration_method,
        "calibrated": calibrate and len(y) >= 50,
        "calibration_info": calibration_info,
        "label_dist": {"WIN": int(y.sum()), "LOSS": int(len(y) - y.sum())},
        "calibration_buckets": calibration_buckets,
        "walk_forward": walk_forward_eval(X, y, clf=ensemble_clf, train_window_pct=0.65, test_window_pct=0.15, n_splits=3),
    }

    with open(METRIC_OUT, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    if feature_importance:
        with open(FEATURE_IMPORTANCE_OUT, "w", encoding="utf-8") as f:
            json.dump(feature_importance, f, indent=2, ensure_ascii=False)
        print("\n  📊 Feature Importance:")
        for feat, imp in list(feature_importance.items())[:8]:
            bar = "█" * int(imp * 40)
            print(f"    {feat:<30} {imp:.4f} {bar}")

    return metrics



_MODEL_CACHE = None
_MODEL_LOAD_ERROR = None

_CACHED_MODEL = None


def load_model():
    """Load model từ disk, cache in memory để inference siêu nhanh."""
    global _MODEL_CACHE, _MODEL_LOAD_ERROR
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    global _CACHED_MODEL
    if _CACHED_MODEL is not None:
        _MODEL_LOAD_ERROR = None
        return _CACHED_MODEL

    if not MODEL_OUT.exists():
        _MODEL_LOAD_ERROR = f"no_model_file:{MODEL_OUT}"
        return None
    try:
        # Backward compatibility: some historical model bundles were serialized
        # when this module ran as __main__, so pickle points to __main__.EnsembleMetaModel.
        # Provide that symbol before loading to prevent deserialization failure.
        try:
            import __main__ as _main
            if not hasattr(_main, "EnsembleMetaModel"):
                _main.EnsembleMetaModel = EnsembleMetaModel
            if not hasattr(_main, "_InferenceWrapper"):
                _main._InferenceWrapper = _InferenceWrapper
        except Exception:
            pass

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*xgboost.*(No visible GPU is found|Device is changed from GPU to CPU|Changing updater from `grow_gpu_hist`).*",
                category=UserWarning,
            )
            from btc_scraper.ml_engine.artifact_resolver import DEFAULT_CONFIG
            from btc_scraper.ml_engine.governed_artifact_loader import get_governed_artifact_loader
            canonical_path = get_governed_artifact_loader().resolver.resolve("meta_model").path
            if canonical_path is not None and MODEL_OUT.resolve() == canonical_path.resolve():
                loaded = get_governed_artifact_loader().load_production("meta_model", "meta-v3.1-43f")
                _MODEL_CACHE = loaded.model
            else:
                # Unit tests redirect MODEL_OUT to an isolated fixture.
                _MODEL_CACHE = get_governed_artifact_loader().load_test_artifact(MODEL_OUT)
        if isinstance(_MODEL_CACHE, dict) and "model" in _MODEL_CACHE:
            clf = _MODEL_CACHE["model"]
            feature_names = _MODEL_CACHE.get("features")
            if feature_names:
                _MODEL_CACHE["model"] = _InferenceWrapper(clf, feature_names)

            def _set_n_jobs(est):
                if hasattr(est, "n_jobs"):
                    try:
                        est.n_jobs = 1
                    except Exception:
                        pass
                if hasattr(est, "estimator"):
                    _set_n_jobs(est.estimator)
                if hasattr(est, "best_estimator_"):
                    _set_n_jobs(est.best_estimator_)
                if hasattr(est, "steps"):
                    for _, step in est.steps:
                        _set_n_jobs(step)
                if hasattr(est, "calibrated_classifiers_"):
                    for cls in est.calibrated_classifiers_:
                        _set_n_jobs(cls)
            _set_n_jobs(clf)
        _MODEL_LOAD_ERROR = None
        return _MODEL_CACHE
    except Exception as e:
        _MODEL_LOAD_ERROR = f"model_load_failed:{e}"
        return None


def get_model_load_error() -> Optional[str]:
    """Return latest model load error for diagnostics."""
    return _MODEL_LOAD_ERROR


def predict_meta_confidence(analysis_info: dict) -> dict:
    """
    Predict win probability cho một tín hiệu.
    """
    from btc_scraper.ml_engine.feature_extractor import FEATURE_SCHEMA_V2, build_meta_features_v2

    obj = load_model()
    if obj is None:
        err = get_model_load_error() or "no_model"
        return {"error": err, "probability": None}

    clf = obj.get("model") if isinstance(obj, dict) else obj
    feature_names = obj.get("features", FEATURE_SCHEMA_V2) if isinstance(obj, dict) else FEATURE_SCHEMA_V2

    try:
        feat = build_meta_features_v2(analysis_info)
        row = [float(feat.get(k, 0.0)) for k in feature_names]

        prob = float(model_predict_proba(clf, [row], feature_names)[0, 1])
        # Calibration tails currently have insufficient evidence for position sizing.
        # Retain the raw probability in the audit trail, but expose a bounded value.
        sizing_probability = min(0.80, max(0.40, prob))

        ev_metrics = _compute_expected_value_metrics(prob, analysis_info)

        # Prediction-level logging (append newline-delimited JSON, mỗi ngày 1 file)
        try:
            from datetime import datetime, timezone
            from btc_scraper.ml_engine.artifact_resolver import get_artifact_resolver
            from btc_scraper.ml_engine.prediction_logger import append_prediction

            now_utc = datetime.now(timezone.utc)
            artifact = get_artifact_resolver().resolve("meta_model")
            signal_text = analysis_info.get("signal")
            signal_upper = str(signal_text or "").upper()
            prediction_side = (
                "BUY" if any(token in signal_upper for token in ("BUY", "LONG", "BULLISH"))
                else "SELL" if any(token in signal_upper for token in ("SELL", "SHORT", "BEARISH"))
                else "NO_TRADE"
            )
            prediction_event = append_prediction(
                model_name="meta_model", model_version=MODEL_VERSION,
                artifact_sha256=artifact.sha256, feature_schema_version="meta-v3.1-43f",
                raw_prediction=prob, calibrated_prediction=prob, features=row,
                decision_context="entry", symbol=analysis_info.get("coin"),
                timeframe=analysis_info.get("timeframe") or analysis_info.get("interval") or "15m",
                side=prediction_side,
                calibration_method=(artifact.metadata or {}).get("calibration_method", "isotonic"),
                fallback_used=False,
                signal_id=analysis_info.get("signal_id") or analysis_info.get("id"),
                position_id=analysis_info.get("position_id"), order_id=analysis_info.get("order_id"),
                fill_id=analysis_info.get("fill_id"),
                extra={"signal": analysis_info.get("signal"), "sizing_probability": sizing_probability},
            )
        except Exception as exc:
            import logging
            from btc_scraper.ml_engine.operational_health import record_degradation
            record_degradation("prediction_audit", "prediction_audit_write_failure_total", exc)
            logging.getLogger(__name__).warning(
                "Prediction audit write failed",
                extra={"signal_id": analysis_info.get("signal_id"), "model_version": MODEL_VERSION, "error_type": type(exc).__name__},
            )
            prediction_event = {}

        return {
            "probability": prob,
            "sizing_probability": sizing_probability,
            "prediction_id": prediction_event.get("prediction_id"),
            "model_version": MODEL_VERSION,
            "artifact_sha256": artifact.sha256 if 'artifact' in locals() else None,
            **ev_metrics,
        }
    except Exception as e:
        from btc_scraper.ml_engine.operational_health import record_degradation
        record_degradation("ml_inference", "ml_inference_failure_total", e)
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
    p.add_argument("--n", type=int, default=200, help="So estimators/iterations cho base models")
    p.add_argument("--no-calibrate", action="store_true", help="Tat Platt calibration")
    args = p.parse_args()

    if args.train:
        print("[Meta Model] Training Meta Model...")
        try:
            m = train_meta_model(n_estimators=args.n, calibrate=not args.no_calibrate)
            print(f"\n[OK] Model saved to {MODEL_OUT}")
            print(f"   Samples: {m['n_samples']}")
            if m.get("cv_auc_mean") is not None:
                print(f"   CV AUC: {m['cv_auc_mean']:.4f} +/- {m.get('cv_auc_std', 0):.4f}")
            if m.get("cv_acc_mean") is not None:
                print(f"   CV Acc: {m['cv_acc_mean']:.4f}")
            if m.get("ensemble_cv_auc_mean") is not None:
                print(f"   Ensemble CV AUC: {m['ensemble_cv_auc_mean']:.4f}")
        except Exception as e:
            print(f"[ERROR] Training failed: {e}")
    else:
        print("Run voi --train de train Meta Model")
        metrics = get_model_metrics()
        if metrics:
            print(f"\nModel hien tai ({metrics.get('version', 'unknown')}):")
            print(f"  Samples: {metrics.get('n_samples', 'N/A')}")
            print(f"  CV AUC: {metrics.get('cv_auc_mean', 'N/A')}")
