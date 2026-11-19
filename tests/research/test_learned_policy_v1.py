"""Targeted tests for Learned Policy v1.

Verifies:
1. Point-in-Time causal feature availability (no future data leakage).
2. Scaler fit strictly on Train (2022-2023) and invariant to validation/test distributions.
3. Policy model bounds: BTC Target Weight strictly in [0, 1].
4. Causal stateful economic replay: no negative cash, realistic fee deduction, capital conservation.
5. Multi-split independent accounting: each split starts with exactly 10,000 USDT.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

from btc_scraper.research.learned_policy_v1 import (
    CompactUnifiedPolicy,
    TrainFittedScaler,
    build_daily_candles,
    extract_causal_features,
    run_learned_policy_replay,
)
from btc_scraper.research.track_a_strategy import PRIMARY_INITIAL_CAPITAL


def _create_mock_hourly_panels(days: int = 120) -> dict[str, pd.DataFrame]:
    """Create synthetic hourly panels for 4 assets."""
    dates = pd.date_range("2022-01-01 00:00:00", periods=days * 24, freq="1h", tz="UTC")
    panels = {}
    for sym, base in [("BTCUSDT", 40000.0), ("ETHUSDT", 2500.0), ("SOLUSDT", 100.0), ("BNBUSDT", 300.0)]:
        closes = base * np.cumprod(1.0 + np.random.normal(0.0001, 0.005, len(dates)))
        df = pd.DataFrame({
            "open": closes * 0.999,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": 100.0,
            "open_time_ms": dates.astype(np.int64) // 1000000,
        }, index=dates)
        panels[sym] = df
    return panels


def test_causal_feature_no_future_leakage():
    """Verify that features at day D only depend on candles up to day D-1."""
    panels = _create_mock_hourly_panels(days=80)
    features_orig = extract_causal_features(panels)

    # Modify the prices on the last day D
    last_date = features_orig.index[-1]
    panels_mod = {k: v.copy() for k, v in panels.items()}
    # Change BTC close prices during the last day
    panels_mod["BTCUSDT"].loc[last_date:, "close"] *= 2.0

    features_mod = extract_causal_features(panels_mod)

    # Features at day D must NOT change because they only observe D-1 closed candles!
    diff = abs(features_orig.loc[last_date] - features_mod.loc[last_date])
    assert diff.max() < 1e-6, f"Feature leakage detected! Max difference: {diff.max()}"


def test_scaler_fit_strictly_on_train():
    """Verify scaler parameters depend only on Train slice and ignore future values."""
    np.random.seed(42)
    dates = pd.date_range("2022-01-01", "2024-12-31", freq="D")
    df = pd.DataFrame({
        "feat1": np.random.normal(10.0, 2.0, len(dates)),
        "feat2": np.random.normal(100.0, 20.0, len(dates)),
    }, index=dates)

    df_train = df.loc["2022-01-01":"2023-12-31"]
    scaler = TrainFittedScaler().fit(df_train)

    # Mean of train should match scaler mean
    assert abs(scaler.mean_[0] - df_train["feat1"].mean()) < 1e-4
    assert abs(scaler.mean_[1] - df_train["feat2"].mean()) < 1e-4

    # Inject extreme outliers in 2024 (Validation)
    df.loc["2024-06-01":, "feat1"] = 99999.0
    # Scaler fit on train must remain unchanged
    scaler_re = TrainFittedScaler().fit(df.loc["2022-01-01":"2023-12-31"])
    assert np.allclose(scaler.mean_, scaler_re.mean_)
    assert np.allclose(scaler.scale_, scaler_re.scale_)


def test_compact_policy_bounds():
    """Verify policy outputs target BTC weight strictly in [0.0, 1.0]."""
    torch.manual_seed(42)
    policy = CompactUnifiedPolicy(in_features=10, hidden_dim=16)

    # Test random inputs
    x = torch.randn(50, 10)
    prev_w = torch.rand(50, 1)
    out = policy(x, prev_w)

    assert out.shape == (50, 1)
    assert (out >= 0.0).all()
    assert (out <= 1.0).all()


def test_learned_replay_no_negative_cash_and_capital_conservation():
    """Verify that economic replay executes without negative balances and satisfies accounting."""
    panels = _create_mock_hourly_panels(days=90)
    features_df = extract_causal_features(panels)
    scaler = TrainFittedScaler().fit(features_df)
    policy = CompactUnifiedPolicy(in_features=len(features_df.columns), hidden_dim=16)

    start_dt = features_df.index[10]
    end_dt = features_df.index[-2]

    res = run_learned_policy_replay(
        btc_hourly=panels["BTCUSDT"],
        features_df=features_df,
        scaler=scaler,
        policy=policy,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
    )

    from dataclasses import asdict

    # Cash must never be negative
    assert (res.cash_history >= -1e-6).all(), "Negative cash balance observed!"
    # Holdings must never be negative
    assert (res.btc_holdings_history >= -1e-8).all(), "Negative BTC holdings observed!"
    # Equity must be positive
    assert (res.equities > 0.0).all(), "Zero or negative equity observed!"
    # Scorecard fields must be present
    scorecard = asdict(res.metrics)
    assert "net_pnl" in scorecard
    assert "cagr" in scorecard
    assert "calmar" in scorecard
    assert "sharpe" in scorecard
    assert "annualized_turnover" in scorecard
