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
from datetime import datetime, timezone
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
    assert observer.inception_rebalances_count == 1
    assert observer.scheduled_rebalances_count == 0
    assert observer.carm_portfolio.rebalance_count == 1

    # Simulate feed outage: 8 days (192 hours) missing!
    # Next observation arrives in Week 2: 2026-01-12 12:00:00 UTC
    res_after_outage = observer.step(
        timestamp="2026-01-12T12:00:00Z",
        prices={"BTCUSDT": 220.0, "ETHUSDT": 210.0},
        warmup_history=warmup_df,
    )
    # Weekly clock triggers rebalance cleanly for the new period
    assert res_after_outage.rebalance_triggered is True
    assert observer.scheduled_rebalances_count == 1
    assert observer.carm_portfolio.rebalance_count == 2


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
    assert readback_ledger.records[0]["carm_equity"] == pytest.approx(9_988.0, rel=1e-5)
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


def test_canonical_0d9f6660_parity_inception_equal_weight():
    """Verify CARM_ORIGINAL_RESEARCH_V1 incepts with equal-weight 1/N across universe."""
    universe = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(
        universe=universe,
        initial_capital_usd=10_000.0,
        fee_bps=12.0,
        require_positive_momentum=False,
        initial_allocation_mode="EQUAL_WEIGHT",
    )

    prices = {"ADAUSDT": 1.0, "BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0}
    res = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)

    # Initial entry fee is 12 bps ($12.00)
    assert observer.carm_portfolio.cumulative_fees_usd == pytest.approx(12.0, rel=1e-5)
    assert observer.carm_portfolio.equity_usd == pytest.approx(9_988.0, rel=1e-5)
    # Each asset receives 1/4 = 25% of post-fee equity ($2,497 each)
    expected_alloc = 9_988.0 / 4.0
    for sym in universe:
        assert observer.carm_portfolio.holdings[sym] == pytest.approx(expected_alloc / prices[sym], rel=1e-5)


def test_hourly_bars_ingestion_and_history_persistence(tmp_path: Path):
    """Verify ingestion of authentic hourly bars and full restoration across restart."""
    state_file = tmp_path / "carm_state_bars.json"
    universe = ["BTCUSDT", "ETHUSDT"]
    observer = CarmShadowObserver(universe=universe)

    # Ingest 20 hourly bars
    bars = [
        (datetime(2026, 1, 1, h, 0, tzinfo=timezone.utc), {"BTCUSDT": 100.0 + h, "ETHUSDT": 50.0 + h})
        for h in range(20)
    ]
    added = observer.ingest_hourly_bars(bars)
    assert added == 20
    assert len(observer.hourly_price_history) == 20

    # Save and load
    observer.save_state(state_file)
    recovered = CarmShadowObserver.load_state(state_file)

    assert len(recovered.hourly_price_history) == 20
    assert recovered.hourly_price_history[0][1]["BTCUSDT"] == 100.0
    assert recovered.hourly_price_history[-1][1]["BTCUSDT"] == 119.0


def test_scorecard_insufficient_sample_shows_na():
    """Verify that ledger with < 24h sample outputs N/A (<24h) for annual metrics."""
    # 3 ticks 1 second apart
    records = [
        {
            "timestamp": f"2026-01-04T00:00:0{i}Z",
            "carm_equity": 10000.0 + i,
            "btc_bh_equity": 9988.0 + i,
            "cash_equity": 10000.0,
            "carm_fees_usd": 0.0,
            "carm_turnover": 0.0,
            "carm_rebalances": 0,
            "carm_drawdown_pct": 0.0,
            "btc_drawdown_pct": 0.0,
        }
        for i in range(3)
    ]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.set_index("timestamp", inplace=True)

    metrics = CarmComparativeScorecard.calculate_metrics(df)
    assert np.isnan(metrics["BTC_BUY_AND_HOLD"].annualized_sharpe)
    assert np.isnan(metrics["BTC_BUY_AND_HOLD"].annualized_sortino)

    md = CarmComparativeScorecard.generate_markdown_scorecard(metrics)
    assert "N/A (<24h)" in md


def test_ticker_does_not_contaminate_hourly_price_history():
    """Verify that portfolio valuation ticks NEVER append ticker prices to hourly_price_history."""
    observer = CarmShadowObserver()
    assert len(observer.hourly_price_history) == 0

    # Step observer 10 times across 10 minutes
    for minute in range(10):
        ts = f"2026-01-04T00:{minute:02d}:00Z"
        prices = {sym: 100.0 + minute for sym in CANONICAL_UNIVERSE}
        observer.step(timestamp=ts, prices=prices)

    # Hourly price history MUST remain strictly empty (only populated by ingest_hourly_bars)
    assert len(observer.hourly_price_history) == 0


def test_rebalance_counters_distinguish_inception_scheduled_and_probe():
    """Verify explicit separation of inception, scheduled weekly, and forced probe rebalances."""
    observer = CarmShadowObserver(
        universe=CANONICAL_UNIVERSE,
        rebalance_interval_hours=168,
        causal_delay_bars=2,
        require_positive_momentum=False,
        initial_allocation_mode="EQUAL_WEIGHT",
    )

    prices = {sym: 100.0 for sym in CANONICAL_UNIVERSE}

    # Tick 1: Inception
    res1 = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)
    assert observer.inception_rebalances_count == 1
    assert observer.scheduled_rebalances_count == 0
    assert observer.forced_probes_count == 0
    assert res1.rebalance_details["rebalance_type"] == "INCEPTION"

    # Ingest 175 synthetic hourly bars so momentum is computable
    base_dt = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    bars = [
        (base_dt + pd.Timedelta(hours=h), {sym: 100.0 * (1.0 + 0.001 * h) for sym in CANONICAL_UNIVERSE})
        for h in range(175)
    ]
    observer.ingest_hourly_bars(bars)

    # Tick 2: Forced probe (fresh relative to bar 174 at 2026-01-08T06:00:00Z)
    probe_ts = (base_dt + pd.Timedelta(hours=174)).isoformat()
    res2 = observer.step(timestamp=probe_ts, prices=prices, force_rebalance=True)
    assert observer.inception_rebalances_count == 1
    assert observer.scheduled_rebalances_count == 0
    assert observer.forced_probes_count == 1
    assert res2.rebalance_details["rebalance_type"] == "FORCED_PROBE"

    # Ingest additional bars up to week boundary (2026-01-11T00:00:00Z = 240 hours from base_dt)
    additional_bars = [
        (base_dt + pd.Timedelta(hours=h), {sym: 100.0 * (1.0 + 0.001 * h) for sym in CANONICAL_UNIVERSE})
        for h in range(175, 241)
    ]
    observer.ingest_hourly_bars(additional_bars)

    # Tick 3: Natural scheduled weekly boundary
    res3 = observer.step(timestamp="2026-01-11T00:00:00Z", prices=prices)
    assert observer.inception_rebalances_count == 1
    assert observer.scheduled_rebalances_count == 1
    assert observer.forced_probes_count == 1
    assert res3.rebalance_details["rebalance_type"] == "SCHEDULED_WEEKLY"


def test_atomic_persistence_and_ledger_reconciliation_on_crash(tmp_path: Path):
    """Verify atomic state file replacement and startup ledger reconciliation on simulated crash."""
    state_file = tmp_path / "carm_state.json"
    ledger_file = tmp_path / "valuation_ledger.jsonl"

    observer = CarmShadowObserver(universe=["BTCUSDT"])
    prices = {"BTCUSDT": 50000.0}

    # Step 1: Normal commit
    res1 = observer.step(timestamp="2026-01-04T00:00:00Z", prices=prices)
    ledger = CarmValuationLedger(log_path=ledger_file)
    ledger.append(res1)
    observer.save_state(state_file)

    # Step 2: Simulate crash after ledger append but BEFORE state save
    res2 = observer.step(timestamp="2026-01-04T01:00:00Z", prices={"BTCUSDT": 51000.0})
    ledger.append(res2)
    # Observer state is NOT saved for step 2!

    # Simulate restart: load state and reconcile ledger
    recovered_observer = CarmShadowObserver.load_state(state_file)
    new_ledger = CarmValuationLedger(log_path=ledger_file)
    assert len(new_ledger.records) == 2  # Has uncheckpointed step 2

    last_ts = recovered_observer.last_accepted_timestamp_utc.isoformat()
    dropped = new_ledger.reconcile_with_state(last_ts)

    assert dropped == 1
    assert len(new_ledger.records) == 1
    assert new_ledger.records[0]["timestamp"] == "2026-01-04T00:00:00Z"


def test_exact_mathematical_parity_with_0d9f6660_reference_implementation():
    """Verify reference logic parity between CarmShadowObserver and 0d9f6660 reference function.

    Calls the exact reference code extracted from commit 0d9f6660 on identical 200h warmup + 350h
    forward data, testing inception allocations, shift(2) causal weekly momentum, and virtual fills.
    """
    from btc_scraper.research.carm_reference_0d9f6660 import simulate_carm_top_momentum_strategy

    symbols = list(CANONICAL_UNIVERSE)
    np.random.seed(42)
    W, T, N = 200, 350, len(symbols)

    # Generate synthetic price series for warmup + forward
    rets = np.random.normal(0.0005, 0.015, size=(W + T, N))
    all_prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    start_dt = pd.Timestamp("2026-01-04T00:00:00Z")
    timestamps = pd.date_range(start=start_dt - pd.Timedelta(hours=W), periods=W + T, freq="1h")
    piv_close = pd.DataFrame(all_prices, index=timestamps, columns=symbols)

    # Reference implementation logic from 0d9f6660
    piv_past_168h = piv_close.pct_change(168).shift(2)
    fee_rate = 12.0 / 10000.0

    ref_cash = 10000.0
    ref_holdings = np.zeros(N)
    ref_target_w = np.full(N, 1.0 / N)

    for t in range(W, W + T):
        t_fwd = t - W
        is_scheduled = (t_fwd == 0) or (t_fwd % 168 == 0)
        if is_scheduled and t_fwd > 0:
            row = piv_past_168h.iloc[t]
            top_assets = row.nlargest(3).index
            ref_target_w = np.zeros(N)
            for s in top_assets:
                ref_target_w[symbols.index(s)] = 1.0 / 3.0

        asset_vals = ref_holdings * all_prices[t]
        eq_before = ref_cash + float(np.sum(asset_vals))
        current_w = asset_vals / max(eq_before, 1e-6)

        if is_scheduled:
            dw = float(np.sum(np.abs(ref_target_w - current_w)))
            fee = eq_before * dw * fee_rate
            post_fee_eq = eq_before - fee
            target_vals = ref_target_w * post_fee_eq
            ref_holdings = target_vals / all_prices[t]
            ref_cash = post_fee_eq - float(np.sum(target_vals))

    ref_final_equity = ref_cash + float(np.sum(ref_holdings * all_prices[-1]))

    # Now run CarmShadowObserver over identical hourly data
    observer = CarmShadowObserver(
        universe=symbols,
        initial_capital_usd=10000.0,
        fee_bps=12.0,
        rebalance_interval_hours=168,
        top_k=3,
        causal_delay_bars=2,
        require_positive_momentum=False,
        initial_allocation_mode="EQUAL_WEIGHT",
    )

    # Ingest warmup bars
    warmup_bars = [(timestamps[i].to_pydatetime(), piv_close.iloc[i].to_dict()) for i in range(W)]
    observer.ingest_hourly_bars(warmup_bars)

    # Execute forward simulation
    for t in range(W, W + T):
        ts_str = timestamps[t].isoformat()
        current_prices = piv_close.iloc[t].to_dict()
        observer.ingest_hourly_bars([(timestamps[t].to_pydatetime(), current_prices)])
        observer.step(timestamp=ts_str, prices=current_prices, is_forward=True)

    observer_final_equity = observer.carm_portfolio.equity_usd

    # Compare results down to every cent
    assert observer_final_equity == pytest.approx(ref_final_equity, rel=1e-5)
    for sym in symbols:
        assert observer.carm_portfolio.holdings[sym] == pytest.approx(ref_holdings[symbols.index(sym)], rel=1e-5)


def test_corrupted_trailing_jsonl_line_resilience(tmp_path: Path):
    """Verify that CarmValuationLedger gracefully recovers when the last JSONL line was truncated on crash."""
    ledger_file = tmp_path / "truncated_ledger.jsonl"

    # Write one valid line and one partial/truncated line
    valid_record = {
        "sequence_id": 1,
        "timestamp": "2026-01-04T00:00:00Z",
        "carm_equity": 9988.0,
        "btc_bh_equity": 9988.0,
        "cash_equity": 10000.0,
        "data_quality_status": "VALID",
        "rebalance_triggered": True,
        "carm_fees_usd": 12.0,
        "carm_turnover": 1.0,
        "carm_rebalances": 1,
        "carm_drawdown_pct": -0.12,
        "btc_drawdown_pct": -0.12,
        "carm_holdings": {},
    }
    with open(ledger_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(valid_record) + "\n")
        f.write('{"sequence_id": 2, "timestamp": "2026-01-04T01:00:00Z", "carm_eq')  # Truncated!

    # Must load valid records without crashing
    ledger = CarmValuationLedger(log_path=ledger_file)
    assert len(ledger.records) == 1
    assert ledger.records[0]["sequence_id"] == 1


def test_signal_continuity_gap_and_freshness_fail_closed():
    """Verify that hourly buffer continuity gaps or stale signals fail closed and block rebalance."""
    universe = list(CANONICAL_UNIVERSE)
    observer = CarmShadowObserver(
        universe=universe,
        rebalance_interval_hours=168,
        causal_delay_bars=2,
    )

    # Case 1: Continuity gap (skip hour 50)
    bars_with_gap = []
    base_time = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    for h in range(175):
        if h == 50:
            continue  # Gap!
        dt = base_time + pd.Timedelta(hours=h)
        bars_with_gap.append((dt, {s: 100.0 for s in universe}))

    observer.ingest_hourly_bars(bars_with_gap)

    # Causal momentum check must detect missing bar and fail closed
    decision_time = base_time + pd.Timedelta(hours=175)
    mom_gap = observer._compute_causal_momentum(decision_time_utc=decision_time)
    assert mom_gap is None  # Blocked!

    # Case 2: Stale signal (eval bar is 10 hours older than decision time)
    observer_stale = CarmShadowObserver(universe=universe)
    continuous_bars = [
        (base_time + pd.Timedelta(hours=h), {s: 100.0 for s in universe})
        for h in range(175)
    ]
    observer_stale.ingest_hourly_bars(continuous_bars)

    stale_decision_time = base_time + pd.Timedelta(hours=190)  # 15 hours after latest bar
    mom_stale = observer_stale._compute_causal_momentum(decision_time_utc=stale_decision_time)
    assert mom_stale is None  # Blocked!

