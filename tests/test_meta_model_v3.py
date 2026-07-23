from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np
import pytest

from btc_scraper.ml_engine.meta_model_v3 import (
    MetaModelV3Config, compute_calibration_buckets, expected_calibration_error,
    train_from_dataset_v3,
)


def _build_synthetic_dataset(n: int = 180) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    rows = []
    for i in range(n):
        rows.append(
            {
                "coin": "BTC" if i % 2 == 0 else "ETH",
                "entry_time": ts[i],
                "result": "WIN" if (i % 5 in (0, 1, 2)) else "LOSS",
                "pnl_pct": 0.8 if (i % 5 in (0, 1, 2)) else -0.6,
                "signal_score": float((i % 10) / 10.0),
                "rsi": float(40 + (i % 30)),
                "macd_hist": float((i % 7) - 3),
                "regime_trending_bull": float(1 if i % 3 == 0 else 0),
                "fracdiff_return_1_raw": float((i % 11) / 11.0),
                "alt_macro_stress_composite": float((i % 13) / 13.0),
            }
        )
    return pd.DataFrame(rows)


def test_train_meta_model_v3_generates_required_artifacts(tmp_path: Path):
    df = _build_synthetic_dataset(180)
    dataset_path = tmp_path / "ml_dataset_v3.parquet"
    df.to_parquet(dataset_path, index=False)

    output_dir = tmp_path / "logs"
    out = train_from_dataset_v3(dataset_path, output_dir, MetaModelV3Config())

    assert out["model_path"].exists()
    assert out["metrics_path"].exists()
    assert out["calibration_path"].exists()
    assert out["importance_path"].exists()


def test_train_meta_model_v3_outputs_walkforward_and_comparison(tmp_path: Path):
    df = _build_synthetic_dataset(200)
    dataset_path = tmp_path / "ml_dataset_v3.parquet"
    df.to_parquet(dataset_path, index=False)
    output_dir = tmp_path / "logs"

    out = train_from_dataset_v3(dataset_path, output_dir, MetaModelV3Config())
    metrics = out["metrics"]

    assert metrics["test_metrics"]["accuracy"] is not None
    assert "walk_forward" in metrics
    assert len(metrics["walk_forward"]) >= 1
    assert "model_comparison" in metrics
    assert "baseline_old_style" in metrics["model_comparison"]
    assert "fallback" in metrics
    assert metrics["calibration_selection_split"] == "CALIBRATION"
    assert metrics["final_evaluation_split"] == "FINAL_HOLDOUT"
    assert metrics["holdout_used_for_selection"] is False
    assert metrics["split_manifest_sha256"]
    assert metrics["artifact_sha256"]
    assert metrics["dataset_sha256"]
    assert metrics["training_fingerprint"]
    assert metrics["feature_schema_version"].startswith("meta-v3-")
    assert metrics["status"] == "candidate"
    assert metrics["calibration_method"] in {"sigmoid", "isotonic"}
    assert set(metrics["calibration_selection_metrics"]) == {"sigmoid", "isotonic"}
    assert metrics["test_metrics"]["log_loss"] is not None
    assert metrics["test_metrics"]["ece"] is not None
    assert metrics["test_metrics"]["mce"] is not None
    assert metrics["split_class_distribution"]["final_holdout"]["positive"] > 0
    assert "time_slice_stability" in metrics["calibration_evidence"]
    assert "regime_stability" in metrics["calibration_evidence"]
    assert "cv_holdout_gap" in metrics
    assert all(row["test_range"][1] <= sum(metrics["split"][key] for key in ("train", "calib")) for row in metrics["walk_forward"])


def test_calibration_bucket_uses_mean_probability_not_midpoint():
    buckets = compute_calibration_buckets(
        np.array([.699, .698, .697]), np.array([1, 0, 1]), min_samples=1,
    )
    assert buckets["0.6-0.7"]["predicted_wr"] == pytest.approx(69.8)
    assert buckets["0.6-0.7"]["predicted_wr"] != pytest.approx(65.0)


def test_expected_calibration_error_reference_and_boundaries():
    probs = np.array([0.0, 0.2, 0.8, 1.0])
    labels = np.array([0, 0, 1, 1])
    assert expected_calibration_error(probs, labels) == pytest.approx(0.1)


def test_numeric_meta_label_uses_one_as_positive(tmp_path: Path):
    df = _build_synthetic_dataset(90).drop(columns=["result"])
    df["meta_label"] = [0, 1] * 45
    dataset_path = tmp_path / "numeric_labels.parquet"
    df.to_parquet(dataset_path, index=False)
    out = train_from_dataset_v3(
        dataset_path, tmp_path / "out",
        MetaModelV3Config(label_column="meta_label", positive_label="1", calibration=False),
    )
    assert out["metrics"]["label_distribution"] == {"WIN": 45, "LOSS": 45}
