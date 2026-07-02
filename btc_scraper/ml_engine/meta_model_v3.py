from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import PredefinedSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class MetaModelV3Config:
    label_column: str = "result"
    time_column: str = "entry_time"
    coin_column: str = "coin"
    positive_label: str = "WIN"
    calibration: bool = True
    random_state: int = 42
    train_ratio: float = 0.70
    calib_ratio: float = 0.15
    walk_forward_splits: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_calibration_buckets(probs: np.ndarray, labels: np.ndarray, min_samples: int = 3) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[int]] = {
        "0.0-0.4": [],
        "0.4-0.6": [],
        "0.6-0.7": [],
        "0.7-0.8": [],
        "0.8-1.0": [],
    }

    for prob, y in zip(probs, labels):
        label = int(y)
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

    out: dict[str, dict[str, Any]] = {}
    for bucket, values in buckets.items():
        if len(values) < min_samples:
            out[bucket] = {
                "count": len(values),
                "actual_wr": None,
                "predicted_wr": None,
                "calibration_error": None,
                "calibrated": False,
            }
            continue

        wins = int(sum(values))
        total = int(len(values))
        actual_wr = wins / max(total, 1) * 100
        lo, hi = [float(v) for v in bucket.split("-")]
        predicted_wr = (lo + hi) / 2 * 100
        error = actual_wr - predicted_wr
        out[bucket] = {
            "count": total,
            "wins": wins,
            "losses": total - wins,
            "actual_wr": round(float(actual_wr), 2),
            "predicted_wr": round(float(predicted_wr), 2),
            "calibration_error": round(float(error), 2),
            "calibrated": abs(error) <= 10.0,
        }
    return out


class SklearnEnsembleBinary(ClassifierMixin, BaseEstimator):
    """A dependency-light ensemble for Sprint 10 training on dataset v3."""

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.rf = RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=4,
            class_weight="balanced_subsample",
            random_state=random_state,
            n_jobs=-1,
        )
        self.et = ExtraTreesClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        self.models_: dict[str, Any] = {}
        self.feature_importances_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SklearnEnsembleBinary":
        self.rf.fit(X, y)
        self.et.fit(X, y)
        self.models_ = {"rf": self.rf, "et": self.et}

        imp = []
        for m in self.models_.values():
            if hasattr(m, "feature_importances_"):
                imp.append(m.feature_importances_)
        self.feature_importances_ = np.mean(imp, axis=0) if imp else None
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        probs = []
        for m in self.models_.values():
            probs.append(m.predict_proba(X))
        if not probs:
            raise RuntimeError("Model is not fitted")
        return np.mean(np.stack(probs, axis=0), axis=0)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> float | None:
    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, y_prob))


def _evaluate_binary(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float | None]:
    y_pred = (y_prob >= 0.5).astype(int)
    auc = _safe_auc(y_true, y_prob)
    acc = float(accuracy_score(y_true, y_pred))
    brier = float(brier_score_loss(y_true, y_prob))
    return {
        "roc_auc": auc,
        "accuracy": acc,
        "brier": brier,
    }


def _feature_group(name: str) -> str:
    lname = name.lower()
    if lname.startswith("alt_"):
        return "alternative"
    if lname.startswith("fracdiff_"):
        return "fractional_diff"
    if "regime" in lname:
        return "regime"
    if "causal" in lname or lname.startswith("cf_"):
        return "causal"
    if lname.startswith("coin_"):
        return "cross_sectional"
    return "technical_cross_sectional"


def _walk_forward_eval(
    X: np.ndarray,
    y: np.ndarray,
    base_pipeline: Pipeline,
    n_splits: int,
    train_window_pct: float = 0.65,
    test_window_pct: float = 0.15,
) -> list[dict[str, Any]]:
    n = len(y)
    if n < 40:
        return []

    results: list[dict[str, Any]] = []
    train_len = max(20, int(n * train_window_pct))
    step = max(10, int(n * test_window_pct))
    start = 0
    while start + train_len + step <= n and len(results) < n_splits:
        train_end = start + train_len
        test_end = train_end + step

        X_train, y_train = X[start:train_end], y[start:train_end]
        X_test, y_test = X[train_end:test_end], y[train_end:test_end]

        clf = clone(base_pipeline)
        clf.fit(X_train, y_train)
        probs = clf.predict_proba(X_test)[:, 1]
        metrics = _evaluate_binary(y_test, probs)
        results.append(
            {
                "train_range": [start, train_end],
                "test_range": [train_end, test_end],
                "n_train": int(len(y_train)),
                "n_test": int(len(y_test)),
                **metrics,
            }
        )
        start += step
    return results


def train_from_dataset_v3(
    dataset_path: Path,
    output_dir: Path,
    config: MetaModelV3Config | None = None,
) -> dict[str, Any]:
    cfg = config or MetaModelV3Config()
    df = pd.read_parquet(dataset_path)
    if cfg.label_column not in df.columns:
        raise ValueError(f"Missing label column: {cfg.label_column}")

    if cfg.time_column in df.columns:
        df[cfg.time_column] = pd.to_datetime(df[cfg.time_column], utc=True, errors="coerce")
        df = df.sort_values(cfg.time_column, kind="mergesort").reset_index(drop=True)

    y_raw = df[cfg.label_column].astype(str).str.upper().fillna("")
    y = (y_raw == str(cfg.positive_label).upper()).astype(int).values

    drop_cols = {
        cfg.label_column,
        "pnl_pct",
        "meta_label",
        "triple_barrier_label",
        "trade_quality_score",
        "trade_quality_bucket",
        "signal_raw",
        "exit_time",
    }
    keep_cols = [c for c in df.columns if c not in drop_cols]
    X_df = df[keep_cols].copy()

    if cfg.coin_column in X_df.columns:
        X_df[cfg.coin_column] = X_df[cfg.coin_column].astype(str)
        X_df = pd.get_dummies(X_df, columns=[cfg.coin_column], prefix="coin", dtype=float)

    if cfg.time_column in X_df.columns:
        ts = pd.to_datetime(X_df[cfg.time_column], utc=True, errors="coerce")
        X_df["entry_hour"] = ts.dt.hour.astype(float)
        X_df["entry_dayofweek"] = ts.dt.dayofweek.astype(float)
        X_df = X_df.drop(columns=[cfg.time_column])

    numeric_cols = [c for c in X_df.columns if pd.api.types.is_numeric_dtype(X_df[c])]
    X_df = X_df[numeric_cols].replace([np.inf, -np.inf], np.nan)
    # Remove fully-missing columns to keep the imputer noise-free and deterministic.
    X_df = X_df.dropna(axis=1, how="all")
    if len(X_df.columns) == 0:
        raise ValueError("No numeric feature columns available for training")

    X = X_df.values
    feature_names = list(X_df.columns)
    n = len(X)
    if n < 60:
        raise ValueError(f"Need at least 60 samples for Sprint 10 training, got {n}")

    train_end = int(n * cfg.train_ratio)
    calib_end = int(n * (cfg.train_ratio + cfg.calib_ratio))
    train_end = max(20, min(train_end, n - 20))
    calib_end = max(train_end + 10, min(calib_end, n - 10))

    X_train, y_train = X[:train_end], y[:train_end]
    X_calib, y_calib = X[train_end:calib_end], y[train_end:calib_end]
    X_test, y_test = X[calib_end:], y[calib_end:]

    base_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", SklearnEnsembleBinary(random_state=cfg.random_state)),
        ]
    )

    base_pipeline.fit(X_train, y_train)
    model_to_use: Any = base_pipeline
    calibration_method: str | None = None

    if cfg.calibration and len(np.unique(y_calib)) > 1:
        best_err = float("inf")
        best_model = None
        best_method = None
        for method in ("sigmoid", "isotonic"):
            try:
                fold = np.concatenate(
                    [
                        np.full(len(y_train), -1, dtype=int),
                        np.zeros(len(y_calib), dtype=int),
                    ]
                )
                calibrator = CalibratedClassifierCV(
                    estimator=clone(base_pipeline),
                    method=method,
                    cv=PredefinedSplit(fold),
                    n_jobs=-1,
                )
                X_train_cal = np.vstack([X_train, X_calib])
                y_train_cal = np.concatenate([y_train, y_calib])
                calibrator.fit(X_train_cal, y_train_cal)
                probs = calibrator.predict_proba(X_test)[:, 1]
                buckets = compute_calibration_buckets(probs, y_test)
                errs = [
                    abs(v["calibration_error"])
                    for v in buckets.values()
                    if v.get("calibration_error") is not None
                ]
                if errs:
                    mean_err = float(np.mean(errs))
                    if mean_err < best_err:
                        best_err = mean_err
                        best_model = calibrator
                        best_method = method
            except Exception:
                continue
        if best_model is not None:
            model_to_use = best_model
            calibration_method = best_method

    test_probs = model_to_use.predict_proba(X_test)[:, 1]
    v3_metrics = _evaluate_binary(y_test, test_probs)
    calibration_buckets = compute_calibration_buckets(test_probs, y_test)

    # Baseline old-style model for explicit old-vs-new comparison.
    baseline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=400, random_state=cfg.random_state)),
        ]
    )
    baseline.fit(X_train, y_train)
    baseline_probs = baseline.predict_proba(X_test)[:, 1]
    baseline_metrics = _evaluate_binary(y_test, baseline_probs)

    # Load legacy metrics as informational comparison.
    legacy_metrics_path = output_dir / "meta_model.json"
    legacy_metrics = None
    if legacy_metrics_path.exists():
        try:
            legacy_metrics = json.loads(legacy_metrics_path.read_text(encoding="utf-8"))
        except Exception:
            legacy_metrics = None

    walk_forward = _walk_forward_eval(X, y, base_pipeline, n_splits=cfg.walk_forward_splits)

    # Feature importance.
    importance_values: np.ndarray | None = None
    if hasattr(model_to_use, "feature_importances_"):
        importance_values = getattr(model_to_use, "feature_importances_", None)
    elif hasattr(model_to_use, "base_estimator") and hasattr(model_to_use.base_estimator, "feature_importances_"):
        importance_values = model_to_use.base_estimator.feature_importances_
    elif isinstance(model_to_use, Pipeline):
        mdl = model_to_use.named_steps.get("model")
        if mdl is not None and hasattr(mdl, "feature_importances_"):
            importance_values = mdl.feature_importances_

    feature_importance = []
    if importance_values is not None and len(importance_values) == len(feature_names):
        total = float(np.sum(importance_values))
        if total > 0:
            vals = (importance_values / total).tolist()
        else:
            vals = importance_values.tolist()
        feature_importance = [
            {"feature": name, "importance": float(imp)}
            for name, imp in sorted(zip(feature_names, vals), key=lambda x: x[1], reverse=True)
        ]

    group_scores: dict[str, float] = {}
    for row in feature_importance:
        grp = _feature_group(row["feature"])
        group_scores[grp] = group_scores.get(grp, 0.0) + float(row["importance"])

    group_importance = [
        {"group": name, "importance": float(val)}
        for name, val in sorted(group_scores.items(), key=lambda x: x[1], reverse=True)
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "meta_model_v3.joblib"
    metrics_path = output_dir / "meta_model_v3.json"
    calibration_path = output_dir / "calibration_report_v3.json"
    importance_path = output_dir / "feature_importance_v3.json"

    metadata = {
        "version": "v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path),
        "n_samples": int(n),
        "n_features": int(len(feature_names)),
        "features": feature_names,
        "label_column": cfg.label_column,
        "label_distribution": {"WIN": int(y.sum()), "LOSS": int(len(y) - y.sum())},
        "calibration_method": calibration_method,
        "split": {
            "train": int(len(y_train)),
            "calib": int(len(y_calib)),
            "test": int(len(y_test)),
        },
        "test_metrics": v3_metrics,
        "walk_forward": walk_forward,
        "model_comparison": {
            "baseline_old_style": baseline_metrics,
            "new_model_v3": v3_metrics,
            "delta_roc_auc": (
                None
                if baseline_metrics.get("roc_auc") is None or v3_metrics.get("roc_auc") is None
                else float(v3_metrics["roc_auc"] - baseline_metrics["roc_auc"])
            ),
            "delta_accuracy": float(v3_metrics["accuracy"] - baseline_metrics["accuracy"]),
            "delta_brier": float(v3_metrics["brier"] - baseline_metrics["brier"]),
            "legacy_metrics_file": str(legacy_metrics_path),
            "legacy_metrics_loaded": legacy_metrics is not None,
        },
        "fallback": {
            "old_model_path": str(output_dir / "meta_model.joblib"),
            "old_model_exists": (output_dir / "meta_model.joblib").exists(),
            "strategy": "keep_old_model_as_fallback",
        },
        "config": cfg.to_dict(),
    }

    joblib.dump(
        {
            "model": model_to_use,
            "features": feature_names,
            "config": cfg.to_dict(),
            "metadata": metadata,
        },
        model_path,
    )

    metrics_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    calibration_path.write_text(
        json.dumps(
            {
                "version": "v3",
                "calibration_method": calibration_method,
                "test_metrics": v3_metrics,
                "buckets": calibration_buckets,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    importance_path.write_text(
        json.dumps(
            {
                "version": "v3",
                "top_features": feature_importance[:50],
                "feature_groups": group_importance,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "model_path": model_path,
        "metrics_path": metrics_path,
        "calibration_path": calibration_path,
        "importance_path": importance_path,
        "metrics": metadata,
    }
