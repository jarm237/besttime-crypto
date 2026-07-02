from __future__ import annotations

import numpy as np
import pandas as pd

from btc_scraper.feature_engineering.feature_validator import FeatureValidationConfig, FeatureValidator


def test_feature_validator_flags_missing_correlation_and_leakage():
    rows = 120
    x = np.arange(rows, dtype="float64")
    frame = pd.DataFrame(
        {
            "entry_time": pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC"),
            "coin": ["BTC"] * rows,
            "feature_ok": x,
            "feature_corr_a": x,
            "feature_corr_b": x * 1.0,
            "future_return": x,
            "missing_bad": [np.nan] * 100 + list(np.linspace(0.0, 1.0, 20)),
        }
    )

    validator = FeatureValidator(FeatureValidationConfig(max_missing_rate=0.5, correlation_threshold=0.99))
    quality, rejection = validator.validate(frame, time_col="entry_time")

    rejected = {r["feature"]: r["reasons"] for r in rejection["rejections"]}
    assert "missing_bad" in rejected
    assert "high_missing_rate" in rejected["missing_bad"]
    assert "future_return" in rejected
    assert "leakage_risk" in rejected["future_return"]
    assert "feature_corr_b" in rejected
    assert "high_correlation" in rejected["feature_corr_b"]
    assert len(quality["correlation"]["groups"]) >= 1


def test_feature_validator_computes_psi_findings():
    rows = 200
    baseline = np.linspace(0.0, 1.0, rows)
    drifted = np.linspace(2.0, 3.0, rows)

    frame = pd.DataFrame(
        {
            "entry_time": pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC"),
            "coin": ["BTC"] * rows,
            "feature_stable": baseline,
            "feature_drifted": np.concatenate([baseline[:140], drifted[140:]]),
        }
    )

    validator = FeatureValidator(
        FeatureValidationConfig(psi_threshold=0.05, psi_reject_threshold=0.10, correlation_threshold=0.9999)
    )
    quality, rejection = validator.validate(frame, time_col="entry_time")

    psi_features = {f["feature"] for f in quality["psi"]["findings"]}
    assert "feature_drifted" in psi_features
    rejected = {r["feature"] for r in rejection["rejections"]}
    assert "feature_drifted" in rejected
