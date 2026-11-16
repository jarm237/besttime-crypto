"""Hermetic unit and integration tests for CARM Read-Only Shadow Observer.

Verifies the 8 core requirements:
  1. All-negative momentum cash allocation.
  2. Missing held-asset price preserves equity without corrupting valuation.
  3. UTC weekly clock cadence and recovery after missing ticks.
  4. Duplicate and out-of-order observation idempotency.
  5. Restart before and after rebalance with state persistence.
  6. Decision price versus executable price causal timing.
  7. Fee, equity, and Max Drawdown consistency.
  8. Forward versus historical warmup classification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.carm_market_data import (
    CANONICAL_UNIVERSE,
    CarmMarketDataProvider,
    MarketDataObservation,
)
from btc_scraper.research.carm_scorecard import CarmComparativeScorecard, CarmValuationLedger
from btc_scraper.research.carm_shadow_observer import (
    BENCHMARK_BTC_SYMBOL,
    DEFAULT_FEE_BPS,
    DEFAULT_INITIAL_CAPITAL_USD,
    DEFAULT_REBALANCE_HOURS,
    LIVE_EXCHANGE_PERMISSION,
    PRODUCTION_CANDIDATE,
    REAL_TRADING,
    CarmShadowObserver,
    VirtualPortfolioState,
)


def test_safety_invariants():
    """Verify that execution safety flags remain strictly disabled."""
    assert REAL_TRADING is False
    assert LIVE_EXCHANGE_PERMISSION is False
    assert PRODUCTION_CANDIDATE is False


def test_initial_capital_parity():
    """Verify that all three portfolios initialize with identical $10,000.00 capital."""
    observer = CarmShadowObserver(initial_capital_usd=10_000.0)
    assert observer.carm_portfolio.cash_usd == 10_000.0
    assert observer.btc_portfolio.cash_usd == 10_000.0
    assert observer.cash_portfolio.cash_usd == 10_000.0
    assert observer.carm_portfolio.equity_usd == 10_000.0
    assert observer.btc_portfolio.equity_usd == 10_000.0
    assert observer.cash_portfolio.equity_usd == 10_000.0


def test_btc_buy_and_hold_inception():
    """Verify BTC buy-and-hold inception applies exactly 12 bps entry fee."""
    observer = CarmShadowObserver(initial_capital_usd=10_000.0, fee_bps=12.0)
    btc_price = 50_000.0
    prices = {BENCHMARK_BTC_SYMBOL: btc_price}

    # Step at t=0
    res = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)

    expected_fee = 10_000.0 * (12.0 / 10_000.0)  # $12.00
    expected_invested = 10_000.0 - expected_fee  # $9,988.00
    expected_units = expected_invested / btc_price

    assert observer.btc_portfolio.cumulative_fees_usd == pytest.approx(12.0, rel=1e-5)
    assert observer.btc_portfolio.holdings[BENCHMARK_BTC_SYMBOL] == pytest.approx(expected_units, rel=1e-5)
    assert observer.btc_portfolio.equity_usd == pytest.approx(9_988.0, rel=1e-5)
    assert observer.btc_portfolio.rebalance_count == 1
    assert observer.btc_portfolio.cumulative_turnover == 1.0

    # Step at t=1 with 10% price increase
    btc_price_2 = 55_000.0
    res2 = observer.step(timestamp="2026-01-04T01:00:00Z", prices={BENCHMARK_BTC_SYMBOL: btc_price_2})
    expected_eq_2 = expected_units * btc_price_2
    assert observer.btc_portfolio.equity_usd == pytest.approx(expected_eq_2, rel=1e-5)
    assert observer.btc_portfolio.cumulative_fees_usd == pytest.approx(12.0, rel=1e-5)
    assert observer.btc_portfolio.rebalance_count == 1


def test_cash_benchmark_invariance():
    """Verify CASH benchmark remains strictly invariant across price movements."""
    observer = CarmShadowObserver(initial_capital_usd=10_000.0)
    for i in range(5):
        prices = {BENCHMARK_BTC_SYMBOL: 50_000.0 * (1.0 + 0.05 * i)}
        res = observer.step(timestamp=f"2026-01-04T0{i}:00:00Z", prices=prices)
        assert res.cash_equity == 10_000.0
        assert observer.cash_portfolio.cumulative_fees_usd == 0.0
        assert observer.cash_portfolio.max_drawdown_pct == 0.0


def test_1_all_negative_momentum_cash_allocation():
    """Requirement 1: When all momentum values are negative, CARM allocates 100% to Cash."""
    universe = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(
        universe=universe,
        top_k=3,
        require_positive_momentum=True,
    )

    current_prices = {"ADAUSDT": 1.0, "BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0}
    # All assets have strictly negative momentum
    negative_momentum = {
        "ADAUSDT": -0.05,
        "BTCUSDT": -0.02,
        "ETHUSDT": -0.08,
        "SOLUSDT": -0.15,
    }

    details = observer._rebalance_carm(current_prices, negative_momentum, timestamp_utc="2026-01-04T00:00:00Z")

    assert details["selected_assets"] == []
    assert details["target_cash_weight"] == 1.0
    # CARM holdings must be strictly 0 for all assets
    for sym in universe:
        assert observer.carm_portfolio.holdings[sym] == 0.0
    # Cash holds all post-fee equity
    assert observer.carm_portfolio.cash_usd == pytest.approx(observer.carm_portfolio.equity_usd, rel=1e-5)


def test_1b_partial_positive_momentum_cash_allocation():
    """Requirement 1b: Only positive-momentum assets receive allocations; remaining slots go to Cash."""
    universe = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(
        universe=universe,
        top_k=3,
        require_positive_momentum=True,
    )

    current_prices = {"ADAUSDT": 1.0, "BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0}
    # Only 1 asset has positive momentum (SOLUSDT)
    mixed_momentum = {
        "SOLUSDT": 0.12,
        "BTCUSDT": -0.02,
        "ETHUSDT": -0.05,
        "ADAUSDT": -0.10,
    }

    details = observer._rebalance_carm(current_prices, mixed_momentum, timestamp_utc="2026-01-04T00:00:00Z")

    assert details["selected_assets"] == ["SOLUSDT"]
    # SOLUSDT gets 1/3 (0.3333), cash gets 2/3 (0.6667)
    assert details["target_weights"]["SOLUSDT"] == pytest.approx(1.0 / 3.0, rel=1e-5)
    assert details["target_cash_weight"] == pytest.approx(2.0 / 3.0, rel=1e-5)
    assert observer.carm_portfolio.holdings["SOLUSDT"] > 0.0
    assert observer.carm_portfolio.holdings["BTCUSDT"] == 0.0


def test_2_missing_held_asset_price_preserves_equity():
    """Requirement 2: Missing price on a held asset preserves last valid equity without fabricating 0."""
    observer = CarmShadowObserver(universe=["BTCUSDT", "ETHUSDT"], initial_capital_usd=10_000.0)

    # Incept BTC Buy & Hold at t0
    prices_t0 = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}
    res0 = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices_t0)
    initial_btc_equity = observer.btc_portfolio.equity_usd
    assert initial_btc_equity == pytest.approx(9_988.0, rel=1e-5)

    # Next tick: BTC price is missing or None
    prices_t1 = {"ETHUSDT": 3_100.0}  # BTCUSDT omitted
    res1 = observer.step(timestamp="2026-01-04T01:00:00Z", prices=prices_t1)

    assert res1.data_quality_status == "DATA_QUALITY_FAILURE_MISSING_PRICE"
    assert "Missing or non-positive price for held assets" in res1.rejection_reason
    assert observer.rejected_observations_count == 1
    # Valuation must preserve the previous valid equity, NOT collapse to $0.00
    assert observer.btc_portfolio.equity_usd == pytest.approx(initial_btc_equity, rel=1e-5)


def test_3_utc_weekly_clock_after_missing_ticks():
    """Requirement 3: Rebalance schedule is anchored to UTC weekly periods, invariant to missing ticks."""
    universe = ["BTCUSDT", "ETHUSDT"]
    observer = CarmShadowObserver(
        universe=universe,
        rebalance_interval_hours=168,
        require_positive_momentum=False,
    )

    # Warmup data: 200 bars
    warmup_df = pd.DataFrame([{sym: 100.0 + i for sym in universe} for i in range(200)])

    # Week 1 anchor: 2026-01-04 00:00:00 UTC (Sunday)
    res0 = observer.step(
        timestamp="2026-01-04T00:00:00Z",
        prices={"BTCUSDT": 200.0, "ETHUSDT": 200.0},
        warmup_history=warmup_df,
    )
    assert res0.rebalance_triggered is True
    assert observer.scheduled_rebalances_count == 1

    # Simulate feed outage: 8 days (192 hours) missing!
    # Next observation arrives in Week 2: 2026-01-12 12:00:00 UTC
    res_after_outage = observer.step(
        timestamp="2026-01-12T12:00:00Z",
        prices={"BTCUSDT": 220.0, "ETHUSDT": 210.0},
        warmup_history=warmup_df,
    )
    # Weekly clock triggers rebalance cleanly for the new period
    assert res_after_outage.rebalance_triggered is True
    assert observer.scheduled_rebalances_count == 2


def test_4_duplicate_and_out_of_order_observation():
    """Requirement 4: Duplicate timestamps and out-of-order ticks are rejected idempotently."""
    observer = CarmShadowObserver(universe=["BTCUSDT", "ETHUSDT"])

    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}
    res0 = observer.step(timestamp="2026-01-04T10:00:00Z", prices=prices)
    assert res0.data_quality_status == "VALID"
    assert observer.authentic_forward_observations_count == 1

    # Duplicate timestamp
    res_dup = observer.step(timestamp="2026-01-04T10:00:00Z", prices=prices)
    assert res_dup.data_quality_status == "REJECTED_DUPLICATE"
    assert observer.rejected_observations_count == 1
    assert observer.authentic_forward_observations_count == 1  # not incremented

    # Out-of-order timestamp
    res_ooo = observer.step(timestamp="2026-01-04T09:00:00Z", prices=prices)
    assert res_ooo.data_quality_status == "REJECTED_OUT_OF_ORDER"
    assert observer.rejected_observations_count == 2


def test_5_restart_idempotency_before_and_after_rebalance(tmp_path: Path):
    """Requirement 5: Complete state persistence and restart recovery is fully idempotent."""
    state_file = tmp_path / "carm_state.json"
    universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    observer = CarmShadowObserver(universe=universe, initial_capital_usd=10_000.0)
    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 100.0}
    observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)

    # Persist state
    observer.save_state(state_file)
    assert state_file.exists()

    # Recover in new instance
    recovered = CarmShadowObserver.load_state(state_file)

    assert recovered.carm_portfolio.equity_usd == pytest.approx(observer.carm_portfolio.equity_usd, rel=1e-5)
    assert recovered.btc_portfolio.equity_usd == pytest.approx(observer.btc_portfolio.equity_usd, rel=1e-5)
    assert recovered.cash_portfolio.equity_usd == 10_000.0
    assert recovered.configuration_fingerprint == observer.configuration_fingerprint
    assert recovered.last_accepted_timestamp_utc == observer.last_accepted_timestamp_utc

    # Replaying the last accepted tick on recovered observer must be rejected as duplicate
    res_replay = recovered.step(timestamp="2026-01-04T00:00:00Z", prices=prices)
    assert res_replay.data_quality_status == "REJECTED_DUPLICATE"
    assert recovered.modeled_virtual_fills_count == observer.modeled_virtual_fills_count


def test_6_decision_price_vs_executable_price_timing():
    """Requirement 6: Decision momentum uses strictly historical bars and executes at current price."""
    universe = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(universe=universe, rebalance_interval_hours=2, causal_delay_bars=1)

    prices_history = [
        {"ADAUSDT": 100.0, "BTCUSDT": 100.0, "ETHUSDT": 100.0, "SOLUSDT": 100.0},
        {"ADAUSDT": 120.0, "BTCUSDT": 100.0, "ETHUSDT": 90.0, "SOLUSDT": 110.0},
        {"ADAUSDT": 130.0, "BTCUSDT": 100.0, "ETHUSDT": 80.0, "SOLUSDT": 105.0},
        {"ADAUSDT": 500.0, "BTCUSDT": 500.0, "ETHUSDT": 500.0, "SOLUSDT": 500.0},  # current bar
    ]
    df_history = pd.DataFrame(prices_history)

    mom = observer._compute_causal_momentum(warmup_history=df_history)
    assert mom is not None
    # Evaluated at t=2 vs t=0:
    # ADA: 130/100 - 1 = +0.30 (not 500/120)
    assert mom["ADAUSDT"] == pytest.approx(0.30, rel=1e-5)
    assert mom["SOLUSDT"] == pytest.approx(0.05, rel=1e-5)


def test_7_fee_equity_and_drawdown_consistency():
    """Requirement 7: Transaction fees deduct from equity, peak tracks highs, drawdown is non-positive."""
    universe = ["BTCUSDT", "ETHUSDT"]
    observer = CarmShadowObserver(universe=universe, top_k=1, fee_bps=12.0)

    # Inception trade with 100% BTC ($10,000)
    current_prices = {"BTCUSDT": 100.0, "ETHUSDT": 100.0}
    details = observer._rebalance_carm(current_prices, {"BTCUSDT": 0.10, "ETHUSDT": 0.05}, "2026-01-04T00:00:00Z")

    # Fee = $10,000 * 1.0 * 0.0012 = $12.00
    assert details["fee_usd"] == pytest.approx(12.0, rel=1e-5)
    assert observer.carm_portfolio.equity_usd == pytest.approx(9_988.0, rel=1e-5)

    # Next step: BTC price drops 10%
    observer.step(timestamp="2026-01-04T01:00:00Z", prices={"BTCUSDT": 90.0, "ETHUSDT": 100.0})
    assert observer.carm_portfolio.peak_equity_usd == pytest.approx(10_000.0, rel=1e-5)
    assert observer.carm_portfolio.max_drawdown_pct < 0.0


def test_8_forward_vs_historical_warmup_classification():
    """Requirement 8: Strict counter separation for forward vs historical warmup observations."""
    observer = CarmShadowObserver(universe=["BTCUSDT", "ETHUSDT"])

    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}

    # Step as warmup
    observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices, is_forward=False)
    assert observer.historical_warmup_observations_count == 1
    assert observer.authentic_forward_observations_count == 0

    # Step as forward
    observer.step(timestamp="2026-01-04T01:00:00Z", prices=prices, is_forward=True)
    assert observer.historical_warmup_observations_count == 1
    assert observer.authentic_forward_observations_count == 1


def test_valuation_ledger_and_persistence(tmp_path: Path):
    """Verify ledger recording and append-only JSONL readback."""
    log_file = tmp_path / "valuation_ledger.jsonl"
    ledger = CarmValuationLedger(log_path=log_file)
    observer = CarmShadowObserver(universe=["BTCUSDT", "ETHUSDT"])

    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}
    res1 = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)
    ledger.append(res1)

    prices2 = {"BTCUSDT": 52_000.0, "ETHUSDT": 3_100.0}
    res2 = observer.step(timestamp="2026-01-04T01:00:00Z", prices=prices2)
    ledger.append(res2)

    assert len(ledger.records) == 2
    assert log_file.exists()

    readback_ledger = CarmValuationLedger(log_path=log_file)
    assert len(readback_ledger.records) == 2
    assert readback_ledger.records[0]["carm_equity"] == pytest.approx(10_000.0, rel=1e-5)
    assert readback_ledger.records[1]["btc_bh_equity"] > 10_000.0

    df = ledger.to_dataframe()
    assert len(df) == 2
    assert "carm_equity" in df.columns
    assert "btc_bh_equity" in df.columns


def test_comparative_scorecard_generation():
    """Verify comparative scorecard computes all required economic metrics."""
    records = [
        {
            "timestamp": "2026-01-04T00:00:00Z",
            "carm_equity": 10000.0,
            "btc_bh_equity": 9988.0,
            "cash_equity": 10000.0,
            "carm_fees_usd": 12.0,
            "carm_turnover": 1.0,
            "carm_rebalances": 1,
            "carm_drawdown_pct": 0.0,
            "btc_drawdown_pct": -0.12,
        },
        {
            "timestamp": "2026-01-11T00:00:00Z",
            "carm_equity": 12000.0,
            "btc_bh_equity": 10500.0,
            "cash_equity": 10000.0,
            "carm_fees_usd": 24.0,
            "carm_turnover": 2.0,
            "carm_rebalances": 2,
            "carm_drawdown_pct": 0.0,
            "btc_drawdown_pct": 0.0,
        },
    ]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)

    metrics = CarmComparativeScorecard.calculate_metrics(df, initial_capital_usd=10_000.0)

    assert "CARM_WEEKLY_ONLY" in metrics
    assert "BTC_BUY_AND_HOLD" in metrics
    assert "CASH" in metrics

    carm_m = metrics["CARM_WEEKLY_ONLY"]
    assert carm_m.net_return_pct == pytest.approx(20.0, rel=1e-5)
    assert carm_m.excess_return_vs_btc_pct == pytest.approx(15.0, rel=1e-5)
    assert carm_m.excess_return_vs_cash_pct == pytest.approx(20.0, rel=1e-5)

    md = CarmComparativeScorecard.generate_markdown_scorecard(metrics)
    assert "| **CARM_WEEKLY_ONLY** |" in md
    assert "| **BTC_BUY_AND_HOLD** |" in md
    assert "| **CASH** |" in md
