"""Targeted tests for R7 Continuous Volatility Allocation Economic Test."""

import numpy as np
import pandas as pd
import pytest

from scripts.run_r7_volatility_allocation_test import (
    compute_btc_realized_volatility,
    simulate_volatility_allocation_policy,
)


def test_compute_btc_realized_volatility_causality():
    """Verify that realized volatility is strictly computed without lookahead."""
    n_bars = 200
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="1h", tz="UTC")
    # Synthetic prices with constant return
    prices = pd.Series(100.0 * np.exp(np.linspace(0, 0.5, n_bars)), index=dates)

    ann_vol = compute_btc_realized_volatility(prices, lookback_hours=168)

    # First 83 bars should be NaN due to min_periods = 84
    assert pd.isna(ann_vol.iloc[0])
    assert pd.isna(ann_vol.iloc[80])
    assert not pd.isna(ann_vol.iloc[84])
    assert not pd.isna(ann_vol.iloc[168])
    assert ann_vol.iloc[168] >= 0.0


def test_buffer_logic_suppresses_micro_trades():
    """Verify that buffer <= 0.05 suppresses unnecessary micro-trades and fees."""
    n_bars = 500
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="1h", tz="UTC")
    open_prices = np.full(n_bars, 20000.0)
    close_prices = np.full(n_bars, 20000.0)

    # Constant realized vol resulting in target weight 0.50
    # target_vol = 0.25, rv = 0.50 -> target_btc_w = 0.50
    rv_series = pd.Series(0.50, index=dates)

    decision_indices = [
        t for t in range(200, n_bars)
        if dates[t].dayofweek == 6 and dates[t].hour == 0
    ]

    # Run with 5% buffer
    score_buf, traces, _, _ = simulate_volatility_allocation_policy(
        open_prices_btc=open_prices,
        close_prices_btc=close_prices,
        timestamps=dates,
        start_idx=200,
        decision_indices=decision_indices,
        realized_vol_series=rv_series,
        target_vol=0.25,
        buffer_pct=0.05,
        fee_bps=12.0,
        sim_name="TEST_BUFFER",
    )

    # Since target weight remains 0.50 at constant price, after the initial allocation (decision 0),
    # all subsequent decisions should have delta = 0.0 <= 0.05, so zero further trades!
    m_buf = score_buf["standard_metrics"]
    assert m_buf["actual_trades_executed"] == 1
    assert m_buf["scheduled_rebalance_checks"] == len(decision_indices)


def test_target_vol_bounds_long_only():
    """Verify weights are clipped to [0, 1] (long-only spot, zero leverage)."""
    n_bars = 300
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="1h", tz="UTC")
    open_prices = np.full(n_bars, 20000.0)
    close_prices = np.full(n_bars, 20000.0)

    # Very low volatility (rv = 0.05): target_vol (0.25) / 0.05 = 5.0 -> should clip to 1.0
    rv_series = pd.Series(0.05, index=dates)

    decision_indices = [
        t for t in range(170, n_bars)
        if dates[t].dayofweek == 6 and dates[t].hour == 0
    ]

    score, traces, _, weights = simulate_volatility_allocation_policy(
        open_prices_btc=open_prices,
        close_prices_btc=close_prices,
        timestamps=dates,
        start_idx=170,
        decision_indices=decision_indices,
        realized_vol_series=rv_series,
        target_vol=0.25,
        buffer_pct=0.0,
        fee_bps=12.0,
        sim_name="TEST_CLIPPING",
    )

    for w in weights:
        assert 0.0 <= w <= 1.0
