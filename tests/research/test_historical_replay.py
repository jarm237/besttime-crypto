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
    assert res["total_turnover"] == 1.0
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
