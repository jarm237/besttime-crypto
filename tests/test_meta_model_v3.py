from __future__ import annotations

from pathlib import Path

import pandas as pd

from btc_scraper.ml_engine.meta_model_v3 import MetaModelV3Config, train_from_dataset_v3


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
