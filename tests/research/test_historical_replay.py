"""Unit tests for Historical Data Loader and Historical Market Replay Engine."""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path

from btc_scraper.research.historical_data_loader import HistoricalDataLoader, DatasetQualityReport
from scripts.run_full_historical_replay import compute_metrics, replay_buy_and_hold, replay_carm_utc_sunday


def test_audit_dataset_integrity():
    loader = HistoricalDataLoader()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts = [start + timedelta(hours=i) for i in range(10)]
    df = pd.DataFrame({
        "timestamp": ts,
        "open": np.full(10, 100.0),
        "high": np.full(10, 105.0),
        "low": np.full(10, 95.0),
        "close": np.full(10, 101.0),
        "volume": np.full(10, 50.0),
    })

    rep = loader.audit_dataset_integrity(df, "BTCUSDT")
    assert rep.symbol == "BTCUSDT"
    assert rep.total_bars == 10
    assert rep.missing_bars == 0
    assert rep.gap_count == 0
    assert rep.is_continuous is True


def test_replay_buy_and_hold():
    T, N = 100, 2
    prices = np.full((T, N), 100.0)
    # Price doubles by end
    prices[-1, 0] = 200.0
    target_weights = np.array([1.0, 0.0])

    res = replay_buy_and_hold(prices, target_weights, fee_bps=12.0, initial_capital_usd=10000.0)
    assert res["total_fees"] == pytest.approx(12.0)
    assert res["one_way_turnover"] == 1.0
    assert res["gross_asset_turnover"] == 1.0
    # Final equity should be approximately $10,000 * (1 - 0.0012) * 2 = 19976.0
    assert res["equities"][-1] == pytest.approx((10000.0 - 12.0) * 2.0)


def test_compute_metrics():
    dates = pd.date_range("2024-01-01", periods=100, freq="1h", tz="UTC")
    eq_series = pd.Series(np.linspace(10000.0, 12000.0, 100), index=dates)

    m = compute_metrics("TEST_PORTFOLIO", eq_series, 10000.0, 12.0, 1.0, 1)
    assert m["portfolio_name"] == "TEST_PORTFOLIO"
    assert m["net_return_pct"] == 20.0
    assert m["final_equity_usd"] == 12000.0
    assert m["total_fees_usd"] == 12.0


def test_gap_detection_and_missing_timestamps():
    loader = HistoricalDataLoader()
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    # Generate 10 hours with 1 hour missing (hour 5)
    ts = [start + timedelta(hours=i) for i in range(10) if i != 5]
    df = pd.DataFrame({
        "timestamp": ts,
        "open": np.full(len(ts), 100.0),
        "high": np.full(len(ts), 105.0),
        "low": np.full(len(ts), 95.0),
        "close": np.full(len(ts), 101.0),
        "volume": np.full(len(ts), 50.0),
    })

    rep = loader.audit_dataset_integrity(df, "BTCUSDT")
    assert rep.gap_count == 1
    assert rep.is_continuous is False
    assert len(rep.missing_timestamps) == 1
    assert "2024-01-01T05:00:00+00:00" in rep.missing_timestamps[0]


def test_carm_utc_sunday_warmup_parity_skip():
    """Verify first Sunday prior to 168h warmup skips rebalance without charging fees."""
    # 2024-01-06 was Saturday 00:00 UTC. Hour 24 is Sunday 00:00 UTC (t=24).
    start = datetime(2024, 1, 6, 0, 0, tzinfo=timezone.utc)
    periods = 200
    timestamps = pd.date_range(start, periods=periods, freq="1h", tz="UTC")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"]

    # Simple constant price series
    prices_data = np.full((periods, len(symbols)), 100.0)
    piv_close = pd.DataFrame(prices_data, index=timestamps, columns=symbols)
    piv_open = pd.DataFrame(prices_data, index=timestamps, columns=symbols)

    res = replay_carm_utc_sunday(
        piv_close=piv_close,
        symbols=symbols,
        timestamps=timestamps,
        piv_open=piv_open,
        top_k=2,
        rebalance_interval_hours=168,
        causal_delay_bars=2,
        fee_bps=12.0,
        initial_capital_usd=10000.0,
    )

    # Inception at t=0 is rebalance #1
    assert res["fees_paid"][0] == pytest.approx(10000.0 * 0.0012)

    # Hour 24 is Sunday 00:00 UTC, but t=24 < 170 (signal not ready).
    # PARITY REQUIREMENT: Must NOT rebalance, 0 fees, 0 turnover.
    assert res["fees_paid"][24] == 0.0

    # Hour 192 is next Sunday 00:00 UTC (t=192 >= 170). Signal is ready.
    # Rebalance #2 triggers.
    assert res["rebalance_count"] == 2


def test_standardized_sortino_calculation():
    """Verify Sortino ratio applies root-mean-square of negative returns."""
    dates = pd.date_range("2024-01-01", periods=100, freq="1h", tz="UTC")
    # Generate oscillating returns: half positive +1%, half negative -1%
    values = [10000.0]
    for i in range(1, 100):
        ret = 0.01 if i % 2 == 1 else -0.01
        values.append(values[-1] * (1.0 + ret))

    eq_series = pd.Series(values, index=dates)
    m = compute_metrics("OSCILLATING", eq_series, 10000.0, 0.0, 0.0, 0)

    # Downside deviation calculation check
    rets = eq_series.pct_change().dropna()
    neg_rets = np.minimum(rets.to_numpy(), 0.0)
    expected_dd = np.sqrt(np.mean(neg_rets ** 2))
    expected_sortino = (rets.mean() / expected_dd) * np.sqrt(8760.0)

    assert m["annualized_sortino"] == pytest.approx(round(expected_sortino, 3))
