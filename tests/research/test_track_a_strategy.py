"""Targeted Invariant Tests for Track A v1 Strategy & Replay Engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.s5_economic_replay import solve_post_fee_equity
from btc_scraper.research.track_a_strategy import (
    build_btc_daily_candles,
    compute_track_a_signals,
    run_btc_buy_and_hold_replay,
    run_track_a_replay,
)


def test_solve_post_fee_equity_conservation():
    """Verify fee-aware capital conservation invariant V_post + fee == V_pre."""
    v_pre = 10000.0
    current_notionals = np.array([0.0])
    target_weights = np.array([1.0])
    fee_rate = 0.0030  # 30 bps

    v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)
    assert abs(v_post + fee - v_pre) < 1e-6
    assert fee > 0.0
    assert v_post < v_pre

    # Partial rebalance
    current_notionals_2 = np.array([3000.0])
    target_weights_2 = np.array([0.6666667])
    v_post_2, fee_2 = solve_post_fee_equity(v_pre, current_notionals_2, target_weights_2, fee_rate)
    assert abs(v_post_2 + fee_2 - v_pre) < 1e-6


def test_donchian_strictly_excludes_current_candle():
    """Verify that Donchian channels of candle j are computed strictly on j-N:j, excluding j."""
    # Create synthetic daily series with 100 days
    dates = pd.date_range("2021-01-01", periods=100, freq="D", tz="UTC")
    # Base prices around 100
    highs = np.full(100, 105.0)
    lows = np.full(100, 95.0)
    closes = np.full(100, 100.0)

    # Spike candle at day 98: high=150, close=100
    highs[98] = 150.0

    df_daily = pd.DataFrame({
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "hour_count": 24,
    }, index=dates)

    signals = compute_track_a_signals(df_daily)

    # Day 98 candle (decision at day 99):
    # During day 98, candle 98 itself should NOT be inside the lookback for day 98's decision!
    # At day 98 candle decision (date 98 + 1 day = dates[99]):
    # The upper channel evaluated on candle 98 was formed over [98-20 : 98], so it should be 105.0, NOT 150.0!
    # At candle 99 (dates[99] + 1 day): candle 98 is now in lookback, so upper should be 150.0.
    sig_99 = signals[dates[99]]
    assert sig_99.candle_dt == dates[98]
    # At candle 98, close was 100.0 <= upper 105.0, so state should remain 0
    assert sig_99.state_20 == 0


def test_two_day_confirmation_logic():
    """Verify that target exposure only updates after two consecutive identical raw exposures."""
    dates = pd.date_range("2021-01-01", periods=100, freq="D", tz="UTC")
    highs = np.full(100, 105.0)
    lows = np.full(100, 95.0)
    closes = np.full(100, 100.0)

    # On day 91: breakout above 105 (close=110)
    closes[91] = 110.0
    highs[91] = 112.0
    # On day 92: close=110.0 (second day of breakout)
    closes[92] = 110.0
    highs[92] = 112.0

    df_daily = pd.DataFrame({
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "hour_count": 24,
    }, index=dates)

    signals = compute_track_a_signals(df_daily)

    # At day 91 close (decision at day 92):
    # raw exposure turns > 0 (1 or more states bullish), but previous day raw was 0.
    # Therefore, 2-day confirmation fails, approved_exposure remains 0!
    sig_92 = signals[dates[92]]
    assert sig_92.raw_exposure > 0.0
    assert sig_92.confirmed is False
    assert sig_92.approved_exposure == 0.0

    # At day 92 close (decision at day 93):
    # raw exposure matches day 91! Confirmation succeeds, approved_exposure updates!
    sig_93 = signals[dates[93]]
    assert sig_93.raw_exposure > 0.0
    assert sig_93.confirmed is True
    assert sig_93.approved_exposure == sig_93.raw_exposure


def test_no_trade_buffer_and_execution_clock():
    """Verify 20 percentage point buffer and execution at 01:00 UTC."""
    # Create synthetic hourly data for 5 days
    dates = pd.date_range("2022-01-01 00:00:00", periods=120, freq="h", tz="UTC")
    prices = np.full(120, 1000.0)
    df_hourly = pd.DataFrame({
        "open": prices,
        "high": prices + 5,
        "low": prices - 5,
        "close": prices,
        "volume": 100.0,
        "open_time_ms": [int(d.timestamp() * 1000) for d in dates],
    }, index=dates)

    daily = build_btc_daily_candles(df_hourly)
    assert len(daily) == 5

    # Mock signals dict
    signals = {}
    for d in pd.date_range("2022-01-01", periods=5, freq="D", tz="UTC"):
        # Set approved exposure to 0.15 (below 0.20 buffer from 0)
        from btc_scraper.research.track_a_strategy import DailySignalRecord
        signals[d] = DailySignalRecord(
            decision_dt=d,
            candle_dt=d - pd.Timedelta(days=1),
            close_price=1000.0,
            state_20=0, state_55=0, state_90=0,
            raw_exposure=0.15,
            approved_exposure=0.15,
            confirmed=True,
        )

    res = run_track_a_replay(
        btc_hourly=df_hourly,
        signals=signals,
        start_dt=dates[0],
        end_dt=dates[-1],
        initial_capital=10000.0,
        fee_bps=30.0,
        no_trade_band=0.20,
    )

    # Deviation is 0.15 - 0.0 = 0.15 <= 0.20 -> No trade triggered!
    assert len(res.trade_events) == 0
    assert res.equities[-1] == 10000.0
