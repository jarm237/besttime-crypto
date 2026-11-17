"""Tests for Predictive Information and Feature Auditing Engine."""

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.predictive_audit import (
    apply_benjamini_hochberg_fdr,
    compute_mutual_information,
    compute_spearman_rank_ic,
    extract_forward_targets,
    extract_multi_timeframe_features,
    PredictiveInformationResult,
)


def _create_synthetic_universe(n_hours: int = 400, symbols: list[str] = None):
    if symbols is None:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    idx = pd.date_range("2024-01-01 00:00:00+00:00", periods=n_hours, freq="1h")

    rng = np.random.RandomState(42)
    data_close = {}
    data_open = {}
    data_high = {}
    data_low = {}
    data_vol = {}

    for sym in symbols:
        drift = 0.0001
        shocks = rng.normal(drift, 0.01, size=n_hours)
        prices = 100.0 * np.exp(np.cumsum(shocks))
        data_close[sym] = prices
        data_open[sym] = np.roll(prices, 1)
        data_open[sym][0] = prices[0]
        data_high[sym] = np.maximum(data_close[sym], data_open[sym]) * (1.0 + rng.uniform(0.001, 0.005, size=n_hours))
        data_low[sym] = np.minimum(data_close[sym], data_open[sym]) * (1.0 - rng.uniform(0.001, 0.005, size=n_hours))
        data_vol[sym] = rng.uniform(10.0, 50.0, size=n_hours)

    piv_close = pd.DataFrame(data_close, index=idx)
    piv_open = pd.DataFrame(data_open, index=idx)
    piv_high = pd.DataFrame(data_high, index=idx)
    piv_low = pd.DataFrame(data_low, index=idx)
    piv_volume = pd.DataFrame(data_vol, index=idx)

    return piv_close, piv_open, piv_high, piv_low, piv_volume


def test_extract_multi_timeframe_features_shapes_and_causality():
    piv_close, piv_open, piv_high, piv_low, piv_volume = _create_synthetic_universe(400)
    features = extract_multi_timeframe_features(
        piv_close=piv_close,
        piv_open=piv_open,
        piv_high=piv_high,
        piv_low=piv_low,
        piv_volume=piv_volume,
    )

    assert "ret_1h" in features
    assert "ret_24h" in features
    assert "ret_168h" in features
    assert "vol_24h" in features
    assert "vol_168h" in features
    assert "ma_dist_168h" in features
    assert "rel_btc_mom_24h" in features
    assert "market_breadth_sma168" in features

    # Check shape alignment
    for feat_name, f_df in features.items():
        assert f_df.shape == piv_close.shape
        assert (f_df.index == piv_close.index).all()


def test_extract_forward_targets_alignment():
    piv_close, _, _, _, _ = _create_synthetic_universe(400)
    targets = extract_forward_targets(piv_close, horizons=[1, 4, 24])

    assert "raw_return" in targets
    assert "rel_btc" in targets
    assert "market_exposure_btc" in targets

    fwd_24 = targets["raw_return"][24]
    assert fwd_24.shape == piv_close.shape

    # Verify target at t is log(P[t+24] / P[t])
    expected_0 = np.log(piv_close.iloc[24]["BTCUSDT"] / piv_close.iloc[0]["BTCUSDT"])
    actual_0 = fwd_24.iloc[0]["BTCUSDT"]
    assert np.isclose(expected_0, actual_0, atol=1e-6)

    # Last 24 rows should be NaN because future is beyond series end
    assert fwd_24.iloc[-24:].isna().all().all()


def test_spearman_rank_ic_and_mutual_info():
    rng = np.random.RandomState(42)
    x = np.linspace(-5.0, 5.0, 500)
    y_mono = 2.0 * x + rng.normal(0, 0.1, size=500)
    y_noise = rng.normal(0, 1.0, size=500)

    # Spearman rank IC
    ic_mono, p_mono = compute_spearman_rank_ic(x, y_mono)
    ic_noise, p_noise = compute_spearman_rank_ic(x, y_noise)

    assert ic_mono > 0.95
    assert p_mono < 1e-10
    assert abs(ic_noise) < 0.15

    # Mutual information
    mi_mono = compute_mutual_information(x, y_mono)
    mi_noise = compute_mutual_information(x, y_noise)
    assert mi_mono > mi_noise
    assert mi_mono > 0.5


def test_benjamini_hochberg_fdr():
    # Construct 10 results with varying p-values
    results = []
    p_vals = [0.001, 0.004, 0.01, 0.03, 0.04, 0.10, 0.20, 0.50, 0.80, 0.95]
    for i, p in enumerate(p_vals):
        r = PredictiveInformationResult(
            feature_name=f"f_{i}",
            family="Test",
            target_type="test",
            horizon_hours=24,
            pooled_rank_ic=0.08,
            rank_ic_pvalue=p,
            mean_cross_sectional_rank_ic=0.08,
            pearson_ic=0.08,
            directional_hit_rate=0.55,
            mutual_information_nats=0.02,
            train_rank_ic=0.08,
            val_rank_ic=0.06,
            holdout_rank_ic=0.05,
            temporal_stability_score=0.75,
            regime_bull_rank_ic=0.08,
            regime_bear_rank_ic=0.07,
            regime_highvol_rank_ic=0.08,
            regime_lowvol_rank_ic=0.07,
            incremental_ic_vs_btc_beta=0.05,
        )
        results.append(r)

    fdr_results = apply_benjamini_hochberg_fdr(results, alpha=0.05)
    # Check that q-values are calculated and monotonic
    q_vals = [r.fdr_adjusted_qvalue for r in fdr_results]
    for q in q_vals:
        assert 0.0 <= q <= 1.0
    # Smallest p-value should have q-value <= 0.05
    assert q_vals[0] <= 0.05
    assert fdr_results[0].is_significant_train_val is True
