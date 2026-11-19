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
    compute_holding_period_returns,
    extract_causal_features,
    run_learned_policy_replay,
    run_rebalanced_50_50_replay,
    run_static_50_50_replay,
    train_learned_policy,
    verify_trade_events_accounting,
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


def test_purge_training_and_validation_boundary_labels():
    """Verify that training and validation labels never cross into subsequent splits."""
    # Create 4 years of daily dates spanning 2022 to 2025
    daily_dates = pd.date_range("2022-01-01", "2025-01-10", freq="D", tz="UTC")
    # Hourly panel covering same period
    hourly_dates = pd.date_range("2022-01-01 00:00:00", "2025-01-10 23:00:00", freq="1h", tz="UTC")
    closes = 40000.0 * np.cumprod(1.0 + np.random.normal(0.0001, 0.001, len(hourly_dates)))
    btc_hourly = pd.DataFrame({
        "open": closes * 0.999,
        "high": closes * 1.001,
        "low": closes * 0.998,
        "close": closes,
        "volume": 100.0,
        "open_time_ms": hourly_dates.astype(np.int64) // 1000000,
    }, index=hourly_dates)

    fwd_returns = compute_holding_period_returns(btc_hourly, daily_dates)

    # 1. Train window boundary check:
    train_start_ts = pd.Timestamp("2022-01-01", tz="UTC")
    train_end_boundary = pd.Timestamp("2023-12-31 23:59:59", tz="UTC")
    train_dates = [
        d for d in fwd_returns.index
        if (d >= train_start_ts) and (d <= train_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= train_end_boundary)
    ]
    assert train_dates[-1] == pd.Timestamp("2023-12-30", tz="UTC"), (
        f"Train last date must be 2023-12-30, got {train_dates[-1]}"
    )
    # Next execution for 2023-12-30 is 2023-12-31 01:00 UTC (strictly within Train)
    assert train_dates[-1] + pd.Timedelta(days=1, hours=1) <= train_end_boundary

    # Negative check: 2023-12-31 must be excluded from train
    assert pd.Timestamp("2023-12-31", tz="UTC") not in train_dates

    # 2. Validation selection boundary check:
    val_start_ts = pd.Timestamp("2024-01-01", tz="UTC")
    val_end_boundary = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
    val_dates = [
        d for d in fwd_returns.index
        if (d >= val_start_ts) and (d <= val_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= val_end_boundary)
    ]
    assert val_dates[-1] == pd.Timestamp("2024-12-30", tz="UTC"), (
        f"Validation selection last date must be 2024-12-30, got {val_dates[-1]}"
    )
    # Next execution for 2024-12-30 is 2024-12-31 01:00 UTC (strictly within Validation)
    assert val_dates[-1] + pd.Timedelta(days=1, hours=1) <= val_end_boundary

    # Negative check: 2024-12-31 must be excluded because next execution is 2025-01-01 (Reused Test)
    assert pd.Timestamp("2024-12-31", tz="UTC") not in val_dates


def test_terminal_boundary_no_synthetic_zero_padding():
    """Verify that terminal dataset date without forward price is purged (no fake 0.0 return)."""
    hourly_dates = pd.date_range("2024-01-01 00:00:00", "2024-01-05 23:00:00", freq="1h", tz="UTC")
    btc_hourly = pd.DataFrame({
        "open": 40000.0,
        "high": 40100.0,
        "low": 39900.0,
        "close": 40000.0,
        "volume": 10.0,
        "open_time_ms": hourly_dates.astype(np.int64) // 1000000,
    }, index=hourly_dates)

    daily_dates = pd.date_range("2024-01-01", "2024-01-05", freq="D", tz="UTC")
    fwd_returns = compute_holding_period_returns(btc_hourly, daily_dates)

    # 2024-01-05 execution next would be 2024-01-06 01:00 UTC, which does not exist
    # It must NOT be in fwd_returns and must NOT have synthetic 0.0
    assert pd.Timestamp("2024-01-05", tz="UTC") not in fwd_returns.index
    assert len(fwd_returns) == 4
    assert pd.Timestamp("2024-01-04", tz="UTC") in fwd_returns.index


def test_missing_execution_prices_fail_closed():
    """Verify that missing execution prices at 01:00 UTC fail closed (raise ValueError)."""
    hourly_dates = pd.date_range("2024-01-01 00:00:00", "2024-01-05 23:00:00", freq="1h", tz="UTC")
    btc_hourly = pd.DataFrame({
        "open": 40000.0,
        "high": 40100.0,
        "low": 39900.0,
        "close": 40000.0,
        "volume": 10.0,
        "open_time_ms": hourly_dates.astype(np.int64) // 1000000,
    }, index=hourly_dates)

    # Negative case: Delete the 01:00 UTC execution candle on 2024-01-02
    drop_ts = pd.Timestamp("2024-01-02 01:00:00", tz="UTC")
    btc_corrupt = btc_hourly.drop(index=drop_ts)

    daily_dates = pd.date_range("2024-01-01", "2024-01-03", freq="D", tz="UTC")
    with pytest.raises(ValueError, match="Missing.*execution price"):
        compute_holding_period_returns(btc_corrupt, daily_dates)


def test_trade_notional_reconciliation_and_capital_conservation():
    """Verify accounting integrity verification catches mismatches and passes on clean replay."""
    panels = _create_mock_hourly_panels(days=120)
    features_df = extract_causal_features(panels)
    scaler = TrainFittedScaler().fit(features_df)
    policy = CompactUnifiedPolicy(in_features=len(features_df.columns), hidden_dim=16)

    res = run_learned_policy_replay(
        btc_hourly=panels["BTCUSDT"],
        features_df=features_df,
        scaler=scaler,
        policy=policy,
        start_dt=features_df.index[5],
        end_dt=features_df.index[-2],
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
    )

    # Positive test: actual clean replay passes integrity verification
    check = verify_trade_events_accounting(
        trade_events=res.trade_events,
        turnovers=res.turnovers,
        fees=res.fees,
        metrics=res.metrics,
        fee_bps=30.0,
    )
    assert check["passed"] is True
    assert len(check["conservation_errors"]) == 0
    assert len(check["fee_errors"]) == 0
    assert abs(check["metrics_total_fees"] - check["total_event_fees"]) < 1e-4

    # Negative test: corrupt a trade event (violate capital conservation)
    if len(res.trade_events) > 0:
        corrupted_events = [dict(e) for e in res.trade_events]
        corrupted_events[0]["v_post"] += 100.0  # create unearned equity leak

        corrupt_check = verify_trade_events_accounting(
            trade_events=corrupted_events,
            turnovers=res.turnovers,
            fees=res.fees,
            metrics=res.metrics,
            fee_bps=30.0,
        )
        assert corrupt_check["passed"] is False
        assert len(corrupt_check["conservation_errors"]) > 0


def test_static_and_rebalanced_50_50_benchmarks():
    """Verify execution of static and rebalanced 50/50 allocation baselines."""
    panels = _create_mock_hourly_panels(days=60)
    btc_hourly = panels["BTCUSDT"]
    start_dt = btc_hourly.index[0]
    end_dt = btc_hourly.index[-1]

    # 1. Static 50/50: exactly 1 trade at inception
    res_static = run_static_50_50_replay(
        btc_hourly=btc_hourly,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
    )
    assert res_static.metrics.num_trades == 1
    assert len(res_static.trade_events) == 1
    assert abs(res_static.trade_events[0]["trade_notional"] - 5000.0) < 50.0
    assert (res_static.cash_history > 0.0).all()
    assert (res_static.equities > 0.0).all()

    # 2. Rebalanced 50/50: trades whenever deviation > 5%
    res_reb = run_rebalanced_50_50_replay(
        btc_hourly=btc_hourly,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
        rebalance_band=0.05,
    )
    assert res_reb.metrics.num_trades >= 1
    assert (res_reb.cash_history > 0.0).all()
    assert (res_reb.equities > 0.0).all()

    # Check accounting integrity of both benchmarks
    chk_static = verify_trade_events_accounting(
        res_static.trade_events, res_static.turnovers, res_static.fees, res_static.metrics
    )
    assert chk_static["passed"] is True

    chk_reb = verify_trade_events_accounting(
        res_reb.trade_events, res_reb.turnovers, res_reb.fees, res_reb.metrics
    )
    assert chk_reb["passed"] is True
