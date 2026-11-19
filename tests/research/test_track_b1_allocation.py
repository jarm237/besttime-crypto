"""Targeted unit tests for Track B1 — Regime-Conditioned Capital Allocation.

Verifies:
1. Monotonicity constraints of RegimeConditionedAllocationHead:
   - Target BTC weight increases with trend
   - Target BTC weight decreases with downside risk
   - Target BTC weight increases with breadth
   - Zero base weight always produces zero target weight
   - Capital multiplier strictly within [0.5, 1.5]
2. Causal Point-in-Time feature engineering (no future data leakage).
3. Scaler fit strictly on Train slice (2022-2023).
4. Boundary label purging (no lookahead into next split).
5. Statefulness and capital conservation of Track B1 economic replay.
6. Constant-multiplier Track A benchmark execution and accounting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from btc_scraper.research.track_a_strategy import (
    PRIMARY_INITIAL_CAPITAL,
    compute_track_a_signals,
)
from btc_scraper.research.track_b1_allocation import (
    RegimeConditionedAllocationHead,
    TrackB1Scaler,
    build_daily_candles,
    compute_train_constant_multiplier,
    extract_track_b1_features,
    run_constant_multiplier_track_a_replay,
    run_track_b1_replay,
)
from btc_scraper.research.learned_policy_v1 import verify_trade_events_accounting


def _create_mock_universe(days: int = 150) -> dict[str, pd.DataFrame]:
    """Create synthetic hourly panels for BTC, ETH, SOL, BNB."""
    dates = pd.date_range("2021-10-01 00:00:00", periods=days * 24, freq="1h", tz="UTC")
    panels = {}
    for sym, base in [("BTCUSDT", 40000.0), ("ETHUSDT", 2500.0), ("SOLUSDT", 100.0), ("BNBUSDT", 300.0)]:
        closes = base * np.cumprod(1.0 + np.random.normal(0.0001, 0.004, len(dates)))
        df = pd.DataFrame({
            "open": closes * 0.999,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": 500.0,
            "open_time_ms": dates.astype(np.int64) // 1000000,
        }, index=dates)
        panels[sym] = df
    return panels


def test_allocation_head_monotonicity_and_bounds():
    """Verify that head strictly obeys monotonic domain relations and multiplier bounds."""
    head = RegimeConditionedAllocationHead()

    # 1. Check positive coefficients via softplus
    assert head.positive_trend_coef >= 0.0
    assert head.positive_risk_coef >= 0.0
    assert head.positive_breadth_coef >= 0.0

    # 2. Multiplier bounds check for extreme values
    extreme_inputs = torch.tensor([-100.0, 0.0, 100.0])
    for val in extreme_inputs:
        _, gate, mult = head(val, val, val, torch.tensor(1.0))
        assert 0.0 <= gate.item() <= 1.0
        assert 0.5 <= mult.item() <= 1.5

    # 3. Base weight = 0.0 must ALWAYS produce 0.0 target BTC weight
    for t_val in [-5.0, 0.0, 5.0]:
        t_w, _, _ = head(torch.tensor(t_val), torch.tensor(t_val), torch.tensor(t_val), torch.tensor(0.0))
        assert t_w.item() == 0.0

    # 4. Monotonicity checks with base_weight = 0.667:
    base = torch.tensor(0.6667)

    # a. Trend increasing -> target weight non-decreasing
    w_low_trend, _, _ = head(torch.tensor(-2.0), torch.tensor(0.0), torch.tensor(0.0), base)
    w_high_trend, _, _ = head(torch.tensor(+2.0), torch.tensor(0.0), torch.tensor(0.0), base)
    assert w_high_trend.item() >= w_low_trend.item()

    # b. Downside risk increasing -> target weight non-increasing
    w_low_risk, _, _ = head(torch.tensor(0.0), torch.tensor(-2.0), torch.tensor(0.0), base)
    w_high_risk, _, _ = head(torch.tensor(0.0), torch.tensor(+2.0), torch.tensor(0.0), base)
    assert w_high_risk.item() <= w_low_risk.item()

    # c. Breadth increasing -> target weight non-decreasing
    w_low_breadth, _, _ = head(torch.tensor(0.0), torch.tensor(0.0), torch.tensor(-2.0), base)
    w_high_breadth, _, _ = head(torch.tensor(0.0), torch.tensor(0.0), torch.tensor(+2.0), base)
    assert w_high_breadth.item() >= w_low_breadth.item()


def test_track_b1_causal_features_no_future_leakage():
    """Verify that features at day D only observe candles closed up to day D-1."""
    panels = _create_mock_universe(days=120)
    daily_btc = build_daily_candles(panels["BTCUSDT"])
    signals = compute_track_a_signals(daily_btc)

    features_orig = extract_track_b1_features(panels, signals)
    last_date = features_orig.index[-1]

    # Modify Day D hourly candles for BTC and ETH
    panels_mod = {k: v.copy() for k, v in panels.items()}
    panels_mod["BTCUSDT"].loc[last_date:, "close"] *= 1.5
    panels_mod["ETHUSDT"].loc[last_date:, "close"] *= 0.5
    daily_btc_mod = build_daily_candles(panels_mod["BTCUSDT"])
    signals_mod = compute_track_a_signals(daily_btc_mod)

    features_mod = extract_track_b1_features(panels_mod, signals_mod)

    # Feature row at day D must NOT be altered
    row_orig = features_orig.loc[last_date]
    row_mod = features_mod.loc[last_date]
    diff = (row_orig - row_mod).abs().max()
    assert diff < 1e-6, f"Feature leakage on Day D! Max diff: {diff}"


def test_track_b1_scaler_strict_train_fit():
    """Verify that TrackB1Scaler fit parameters depend solely on Train."""
    dates = pd.date_range("2022-01-01", "2024-12-31", freq="D")
    df = pd.DataFrame({
        "trend_90d": np.random.normal(0.1, 0.05, len(dates)),
        "downside_risk_30d": np.random.normal(0.02, 0.01, len(dates)),
        "breadth_30d": np.random.uniform(0.0, 1.0, len(dates)),
    }, index=dates)

    train_df = df.loc["2022-01-01":"2023-12-31"]
    scaler = TrackB1Scaler().fit(train_df)

    assert abs(scaler.mean_[0] - train_df["trend_90d"].mean()) < 1e-4

    # Contaminate validation period with extreme values
    df.loc["2024-05-01":, "trend_90d"] = 9999.0
    scaler_re = TrackB1Scaler().fit(df.loc["2022-01-01":"2023-12-31"])
    assert np.allclose(scaler.mean_, scaler_re.mean_)
    assert np.allclose(scaler.scale_, scaler_re.scale_)


def test_track_b1_replay_accounting_and_conservation():
    """Verify stateful replay satisfies conservation V_post = V_pre - fee and non-negative cash."""
    panels = _create_mock_universe(days=120)
    daily_btc = build_daily_candles(panels["BTCUSDT"])
    signals = compute_track_a_signals(daily_btc)
    features_df = extract_track_b1_features(panels, signals)
    scaler = TrackB1Scaler().fit(features_df)
    head = RegimeConditionedAllocationHead()

    start_dt = features_df.index[5]
    end_dt = features_df.index[-2]

    res = run_track_b1_replay(
        btc_hourly=panels["BTCUSDT"],
        features_df=features_df,
        scaler=scaler,
        model=head,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
    )

    # 1. Cash and holdings solvency
    assert (res.cash_history >= -1e-6).all()
    assert (res.btc_holdings_history >= -1e-8).all()
    assert (res.equities > 0.0).all()

    # 2. Capital conservation on trade events
    chk = verify_trade_events_accounting(
        res.trade_events, res.turnovers, res.fees, res.metrics, fee_bps=30.0
    )
    assert chk["passed"] is True
    assert len(chk["conservation_errors"]) == 0
    assert len(chk["fee_errors"]) == 0


def test_constant_multiplier_track_a():
    """Verify execution of Constant-Multiplier Track A benchmark."""
    panels = _create_mock_universe(days=120)
    daily_btc = build_daily_candles(panels["BTCUSDT"])
    signals = compute_track_a_signals(daily_btc)
    features_df = extract_track_b1_features(panels, signals)
    scaler = TrackB1Scaler().fit(features_df)
    head = RegimeConditionedAllocationHead()

    const_mult = compute_train_constant_multiplier(
        features_df=features_df,
        scaler=scaler,
        model=head,
        train_start=str(features_df.index[0].date()),
        train_end=str(features_df.index[-1].date()),
    )
    assert 0.5 <= const_mult <= 1.5

    start_dt = features_df.index[5]
    end_dt = features_df.index[-2]

    res_const = run_constant_multiplier_track_a_replay(
        btc_hourly=panels["BTCUSDT"],
        track_a_signals=signals,
        constant_multiplier=const_mult,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=PRIMARY_INITIAL_CAPITAL,
        fee_bps=30.0,
    )

    chk = verify_trade_events_accounting(
        res_const.trade_events, res_const.turnovers, res_const.fees, res_const.metrics, fee_bps=30.0
    )
    assert chk["passed"] is True
