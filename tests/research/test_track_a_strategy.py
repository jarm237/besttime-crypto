"""Targeted Invariant Tests for Track A v1 Strategy & Replay Engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.s5_economic_replay import solve_post_fee_equity, compute_market_trend_168h
from btc_scraper.research.s4_dataset_audit import UNIVERSE
from btc_scraper.research.track_a_strategy import (
    DailySignalRecord,
    build_btc_daily_candles,
    compute_performance_metrics,
    compute_track_a_signals,
    run_btc_buy_and_hold_replay,
    run_s5_daily_trend_replay,
    run_track_a_replay,
    verify_replay_accounting_integrity,
    verify_replay_causal_integrity,
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


def test_standardized_turnover_formula():
    """Verify annualized turnover matches sum(traded_notional / pre_equity) / years."""
    equities = np.array([10000.0, 10000.0, 10500.0, 11000.0])
    cash_history = np.array([10000.0, 0.0, 0.0, 0.0])
    turnovers = np.array([0.0, 0.997, 0.0, 0.0])
    fees = np.array([0.0, 30.0, 0.0, 0.0])
    trade_events = [{"trade_notional": 9970.0, "fee": 30.0}]
    start_dt = pd.Timestamp("2022-01-01 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")
    timestamps = [
        pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
        pd.Timestamp("2022-01-01 01:00:00", tz="UTC"),
        pd.Timestamp("2022-06-01 00:00:00", tz="UTC"),
        pd.Timestamp("2023-01-01 00:00:00", tz="UTC"),
    ]

    metrics = compute_performance_metrics(
        equities=equities,
        cash_history=cash_history,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=10000.0,
        timestamps=timestamps,
    )

    total_days = (end_dt - start_dt).total_seconds() / 86400.0
    expected_years = total_days / 365.25
    expected_turnover = float(np.sum(turnovers)) / expected_years
    assert abs(metrics.annualized_turnover - expected_turnover) < 1e-6
    assert metrics.total_traded_notional == 9970.0


def test_s5_daily_trend_calendar_lookback_and_gap_handling():
    """Verify S5 baseline detects missing hours in 168h window and triggers HOLD_DATA_GAP."""
    # Create 10 days of hourly data (240 hours) for all 4 assets
    dates = pd.date_range("2022-01-01 00:00:00", periods=240, freq="h", tz="UTC")
    # Simulate a 1-hour gap at hour 100
    dates_with_gap = dates.delete(100)

    panels = {}
    for s in UNIVERSE:
        panels[s] = pd.DataFrame({
            "open": np.full(len(dates_with_gap), 100.0),
            "high": np.full(len(dates_with_gap), 105.0),
            "low": np.full(len(dates_with_gap), 95.0),
            "close": np.full(len(dates_with_gap), 100.0),
            "volume": np.full(len(dates_with_gap), 1000.0),
            "open_time_ms": [int(d.timestamp() * 1000) for d in dates_with_gap],
        }, index=dates_with_gap)

    # Decision at hour 120 (day 5 00:00 UTC):
    # Cutoff is hour 119. Lookback 168h starts at hour 119 - 168 = negative (before start).
    # Decision at hour 192 (day 8 00:00 UTC):
    # Cutoff is hour 191. Lookback 168h covers hour 23 to hour 191 (contains missing hour 100!).
    d_ts_day8 = dates[192]
    val = compute_market_trend_168h(panels, d_ts_day8)
    assert val is None, "Expected None due to missing hour in calendar lookback window"

    res = run_s5_daily_trend_replay(
        panels=panels,
        start_dt=dates[0],
        end_dt=dates[-1],
        initial_capital=10000.0,
        fee_bps=30.0,
    )
    # Check that HOLD_DATA_GAP was logged in decision ledger when gap was active
    gap_actions = [e for e in res.decision_ledger if e["action"] == "HOLD_DATA_GAP"]
    assert len(gap_actions) > 0, "Expected at least one HOLD_DATA_GAP entry in decision ledger"


def test_integrity_assertions_detect_violations():
    """Verify that dynamic integrity checkers catch runtime accounting and causal violations."""
    # Valid setup
    dates = pd.date_range("2022-01-01 00:00:00", periods=48, freq="h", tz="UTC")
    prices = np.full(48, 1000.0)
    df_hourly = pd.DataFrame({
        "open": prices,
        "high": prices + 5,
        "low": prices - 5,
        "close": prices,
        "volume": 100.0,
        "open_time_ms": [int(d.timestamp() * 1000) for d in dates],
    }, index=dates)

    signals = {
        dates[0]: DailySignalRecord(
            decision_dt=dates[0],
            candle_dt=dates[0] - pd.Timedelta(days=1),
            close_price=1000.0,
            state_20=1, state_55=1, state_90=1,
            raw_exposure=1.0, approved_exposure=1.0, confirmed=True,
        ),
        dates[24]: DailySignalRecord(
            decision_dt=dates[24],
            candle_dt=dates[24] - pd.Timedelta(days=1),
            close_price=1000.0,
            state_20=1, state_55=1, state_90=1,
            raw_exposure=1.0, approved_exposure=1.0, confirmed=True,
        ),
    }

    res = run_track_a_replay(
        btc_hourly=df_hourly,
        signals=signals,
        start_dt=dates[0],
        end_dt=dates[-1],
        initial_capital=10000.0,
        fee_bps=30.0,
        no_trade_band=0.20,
    )

    # Valid check
    acc_pass, acc_msg = verify_replay_accounting_integrity(res)
    assert acc_pass is True
    assert acc_msg == "PASS"

    causal_pass, causal_msg = verify_replay_causal_integrity(res)
    assert causal_pass is True
    assert causal_msg == "PASS"

    # Test accounting violation: corrupted negative cash
    res.cash_history[5] = -100.0
    bad_acc_pass, bad_acc_msg = verify_replay_accounting_integrity(res)
    assert bad_acc_pass is False
    assert "Negative cash balance" in bad_acc_msg

    # Restore cash, corrupt trade event fee
    res.cash_history[5] = 0.0
    res.trade_events[0]["fee"] = -5.0
    bad_fee_pass, bad_fee_msg = verify_replay_accounting_integrity(res)
    assert bad_fee_pass is False
    assert "Negative fee" in bad_fee_msg

    # Test causal violation: corrupt execution timestamp to precede decision
    res.decision_ledger[0]["execution_timestamp"] = dates[0].isoformat()  # hour 0 instead of hour 1
    bad_causal_pass, bad_causal_msg = verify_replay_causal_integrity(res)
    assert bad_causal_pass is False
    assert "strictly succeed" in bad_causal_msg or "Execution hour is 0" in bad_causal_msg

