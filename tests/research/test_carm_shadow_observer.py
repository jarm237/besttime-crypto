"""Hermetic unit and integration tests for CARM Read-Only Shadow Observer.

Verifies:
  1. Strict read-only safety invariants (REAL_TRADING=False, no exchange orders).
  2. Initial capital parity ($10,000.00 each) across all three portfolios.
  3. Inception cost modeling (12 bps friction on BTC and CARM entry).
  4. Causal momentum calculation without lookahead.
  5. 168-hour decision clock cadence.
  6. Ledger persistence and readback fidelity.
  7. Comparative economic scorecard generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.carm_scorecard import CarmComparativeScorecard, CarmValuationLedger
from btc_scraper.research.carm_shadow_observer import (
    BENCHMARK_BTC_SYMBOL,
    CANONICAL_UNIVERSE,
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
    res = observer.step(timestamp="2026-01-01T00:00:00", prices=prices)

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
    res2 = observer.step(timestamp="2026-01-01T01:00:00", prices={BENCHMARK_BTC_SYMBOL: btc_price_2})
    expected_eq_2 = expected_units * btc_price_2
    assert observer.btc_portfolio.equity_usd == pytest.approx(expected_eq_2, rel=1e-5)
    # Fees and turnover must remain unchanged
    assert observer.btc_portfolio.cumulative_fees_usd == pytest.approx(12.0, rel=1e-5)
    assert observer.btc_portfolio.rebalance_count == 1


def test_cash_benchmark_invariance():
    """Verify CASH benchmark remains strictly invariant across price movements."""
    observer = CarmShadowObserver(initial_capital_usd=10_000.0)
    for i in range(5):
        prices = {BENCHMARK_BTC_SYMBOL: 50_000.0 * (1.0 + 0.05 * i)}
        res = observer.step(timestamp=f"2026-01-01T0{i}:00:00", prices=prices)
        assert res.cash_equity == 10_000.0
        assert observer.cash_portfolio.cumulative_fees_usd == 0.0
        assert observer.cash_portfolio.max_drawdown_pct == 0.0


def test_causal_momentum_without_lookahead():
    """Verify momentum is strictly computed on historical bars with causal delay."""
    universe = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(universe=universe, rebalance_interval_hours=2, causal_delay_bars=1)

    # 4 bars of price history:
    # t=0: all 100
    # t=1: ADA=120, BTC=100, ETH=90, SOL=110
    # t=2: ADA=130, BTC=100, ETH=80, SOL=105
    # t=3: current bar
    # With rebalance_interval=2 and delay=1:
    # Decision at bar 3 (idx 3):
    # t_eval = 3 - 1 = 2
    # t_base = 2 - 2 = 0
    # momentum = (P[2] / P[0]) - 1
    prices_history = [
        {"ADAUSDT": 100.0, "BTCUSDT": 100.0, "ETHUSDT": 100.0, "SOLUSDT": 100.0},
        {"ADAUSDT": 120.0, "BTCUSDT": 100.0, "ETHUSDT": 90.0, "SOLUSDT": 110.0},
        {"ADAUSDT": 130.0, "BTCUSDT": 100.0, "ETHUSDT": 80.0, "SOLUSDT": 105.0},
        {"ADAUSDT": 500.0, "BTCUSDT": 500.0, "ETHUSDT": 500.0, "SOLUSDT": 500.0},  # current bar (should not leak)
    ]
    df_history = pd.DataFrame(prices_history)

    mom = observer._compute_causal_momentum(warmup_history=df_history)
    assert mom is not None
    # Past return from t=0 to t=2:
    # ADA: 130/100 - 1 = +0.30
    # BTC: 100/100 - 1 = 0.0
    # ETH: 80/100 - 1 = -0.20
    # SOL: 105/100 - 1 = +0.05
    assert mom["ADAUSDT"] == pytest.approx(0.30, rel=1e-5)
    assert mom["SOLUSDT"] == pytest.approx(0.05, rel=1e-5)
    assert mom["BTCUSDT"] == pytest.approx(0.00, rel=1e-5)
    assert mom["ETHUSDT"] == pytest.approx(-0.20, rel=1e-5)


def test_rebalance_decision_clock_cadence():
    """Verify that CARM rebalances strictly on scheduled hours (e.g. every 5 hours)."""
    universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(universe=universe, rebalance_interval_hours=5, top_k=2)

    # 10 bars of historical warmup data
    warmup_data = [{sym: 100.0 + k for sym in universe} for k in range(10)]
    warmup_df = pd.DataFrame(warmup_data)

    # Generate 15 ticks with warmup
    rebalance_ticks = []
    for i in range(15):
        prices = {sym: 110.0 + i for sym in universe}
        # Append current bar to warmup for realistic streaming
        cur_warmup = pd.concat([warmup_df, pd.DataFrame([{sym: 110.0 + k for sym in universe} for k in range(i + 1)])], ignore_index=True)
        res = observer.step(timestamp=i, prices=prices, warmup_history=cur_warmup)
        if res.rebalance_triggered:
            rebalance_ticks.append(i)

    # Scheduled ticks with interval=5 are exactly 0, 5, 10
    assert rebalance_ticks == [0, 5, 10]


def test_turnover_and_fee_deduction():
    """Verify exact weight delta turnover and 12 bps fee deduction."""
    universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(universe=universe, top_k=2, fee_bps=12.0)

    # Current state: 100% cash ($10,000)
    current_prices = {"BTCUSDT": 100.0, "ETHUSDT": 200.0, "SOLUSDT": 50.0}
    momentum_scores = {"SOLUSDT": 0.20, "BTCUSDT": 0.10, "ETHUSDT": -0.05}

    details = observer._rebalance_carm(current_prices, momentum_scores)

    # Selected assets: SOLUSDT, BTCUSDT (top 2, 50% each)
    assert details["selected_assets"] == ["SOLUSDT", "BTCUSDT"]
    # Turnover from 100% cash to 50% SOL + 50% BTC:
    # dw = |0.5 - 0| + |0.5 - 0| + |0 - 0| = 1.0
    assert details["turnover"] == pytest.approx(1.0, rel=1e-5)
    # Fee: $10,000 * 1.0 * 0.0012 = $12.00
    assert details["fee_usd"] == pytest.approx(12.0, rel=1e-5)
    assert details["post_fee_equity"] == pytest.approx(9_988.0, rel=1e-5)

    # Holdings allocated equally ($4,994 each)
    assert observer.carm_portfolio.holdings["SOLUSDT"] == pytest.approx(4_994.0 / 50.0, rel=1e-5)
    assert observer.carm_portfolio.holdings["BTCUSDT"] == pytest.approx(4_994.0 / 100.0, rel=1e-5)
    assert observer.carm_portfolio.holdings["ETHUSDT"] == 0.0
    assert observer.carm_portfolio.cumulative_fees_usd == pytest.approx(12.0, rel=1e-5)


def test_valuation_ledger_and_persistence(tmp_path: Path):
    """Verify ledger recording and append-only JSONL readback."""
    log_file = tmp_path / "valuation_ledger.jsonl"
    ledger = CarmValuationLedger(log_path=log_file)
    observer = CarmShadowObserver(universe=["BTCUSDT", "ETHUSDT"])

    prices = {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0}
    res1 = observer.step(timestamp="2026-01-01T00:00:00", prices=prices)
    ledger.append(res1)

    prices2 = {"BTCUSDT": 52_000.0, "ETHUSDT": 3_100.0}
    res2 = observer.step(timestamp="2026-01-01T01:00:00", prices=prices2)
    ledger.append(res2)

    assert len(ledger.records) == 2
    assert log_file.exists()

    # Readback
    readback_ledger = CarmValuationLedger(log_path=log_file)
    assert len(readback_ledger.records) == 2
    assert readback_ledger.records[0]["carm_equity"] == pytest.approx(10_000.0, rel=1e-5)
    assert readback_ledger.records[1]["btc_bh_equity"] > 10_000.0

    # DataFrame conversion
    df = ledger.to_dataframe()
    assert len(df) == 2
    assert "carm_equity" in df.columns
    assert "btc_bh_equity" in df.columns


def test_comparative_scorecard_generation():
    """Verify comparative scorecard computes all required economic metrics."""
    records = [
        {
            "timestamp": "2026-01-01T00:00:00",
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
            "timestamp": "2026-01-08T00:00:00",
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


def test_batch_simulation_and_ledger():
    """Verify batch simulation produces full sequence of ObserverTickResults."""
    dates = pd.date_range("2026-01-01", periods=10, freq="h")
    symbols = ["ADAUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
    data = {sym: [100.0 + i * (1 if sym == "SOLUSDT" else 0.2) for i in range(10)] for sym in symbols}
    piv_close = pd.DataFrame(data, index=dates)

    observer = CarmShadowObserver(universe=symbols, rebalance_interval_hours=3, top_k=2)
    ledger = CarmValuationLedger()

    results = observer.run_simulation(piv_close)
    for res in results:
        ledger.append(res)

    assert len(results) == 10
    assert len(ledger.records) == 10
    df = ledger.to_dataframe()
    assert len(df) == 10
    assert df["btc_bh_equity"].iloc[-1] > df["btc_bh_equity"].iloc[0]


def test_rebalance_rotation_turnover_accuracy():
    """Verify turnover when 1 asset rotates out and 1 rotates in."""
    universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    observer = CarmShadowObserver(universe=universe, top_k=2, fee_bps=12.0)

    # Inception rebalance: 50% BTC, 50% ETH
    prices_t0 = {"BTCUSDT": 100.0, "ETHUSDT": 100.0, "SOLUSDT": 100.0}
    mom_t0 = {"BTCUSDT": 0.10, "ETHUSDT": 0.08, "SOLUSDT": 0.01}
    det0 = observer._rebalance_carm(prices_t0, mom_t0)
    assert det0["selected_assets"] == ["BTCUSDT", "ETHUSDT"]
    assert det0["turnover"] == pytest.approx(1.0, rel=1e-5)

    # Next rebalance: SOL overtakes ETH. Top 2 becomes BTC and SOL.
    # BTC remains 50%, ETH goes from 50% to 0%, SOL goes from 0% to 50%.
    # Turnover dw = |0.5 - 0.5| + |0 - 0.5| + |0.5 - 0| = 1.0 (or 0.5 sell + 0.5 buy = 1.0 total turnover)
    prices_t1 = {"BTCUSDT": 100.0, "ETHUSDT": 100.0, "SOLUSDT": 100.0}
    mom_t1 = {"BTCUSDT": 0.15, "SOLUSDT": 0.25, "ETHUSDT": -0.05}
    det1 = observer._rebalance_carm(prices_t1, mom_t1)
    assert det1["selected_assets"] == ["SOLUSDT", "BTCUSDT"]
    assert det1["turnover"] == pytest.approx(1.0, rel=1e-5)
    # Fee is equity_before * 1.0 * 0.0012
    assert det1["fee_usd"] == pytest.approx(det1["equity_before"] * 0.0012, rel=1e-5)
    # New holdings reflect SOL and BTC, zero ETH
    assert observer.carm_portfolio.holdings["ETHUSDT"] == 0.0
    assert observer.carm_portfolio.holdings["SOLUSDT"] > 0.0
    assert observer.carm_portfolio.holdings["BTCUSDT"] > 0.0
