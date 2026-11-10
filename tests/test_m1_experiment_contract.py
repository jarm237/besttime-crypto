"""
tests/test_m1_experiment_contract.py
Phase M1: Reproducible Economic Baselines & Common Experiment Contract.

Covers:
1. ExperimentSpec: immutability, validation, canonical serialization, SHA-256 spec_hash.
2. ExperimentResult: standard accounting, fees, slippage, net vs gross returns, estimability.
3. Baseline Strategies:
   - Always Flat (0 trades, 0 PnL anchor)
   - Passive Buy & Hold
   - Simple Moving Average (SMA) Trend Following
   - Champion 7-Layer Strategy Adapter
4. Pure Deterministic Reproducibility:
   Repeated runs on the same dataset with identical spec yield bit-for-bit identical metrics.
5. Multi-Baseline Comparison:
   Runs all 4 baselines side-by-side on identical candles and cost models.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from btc_scraper.research.experiment_contract import (
    ExperimentResult,
    ExperimentSpec,
    build_champion_baseline_spec,
    compute_spec_hash,
)
from btc_scraper.research.baseline_runner import (
    AlwaysFlatStrategy,
    BaselineStrategy,
    Champion7LayerStrategy,
    ExperimentRunner,
    PassiveBuyAndHoldStrategy,
    SevenLayerProxyStrategy,
    SimpleMovingAverageCrossoverStrategy,
)


def _generate_synthetic_candles(
    symbol: str = "BTCUSDT",
    n_bars: int = 200,
    start_price: float = 50_000.0,
    trend_pct: float = 0.05,
) -> list[dict]:
    """Generates synthetic deterministic OHLCV candles."""
    candles = []
    base_t = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    curr_p = start_price

    for i in range(n_bars):
        t_iso = (base_t + timedelta(minutes=15 * i)).isoformat()
        # Simple cyclic + trend drift
        cycle_wave = math_sin = 0.002 * (1.0 if (i // 10) % 2 == 0 else -1.0)
        drift = trend_pct / n_bars
        curr_p = curr_p * (1.0 + cycle_wave + drift)
        
        candle = {
            "symbol": symbol,
            "open": curr_p * 0.999,
            "high": curr_p * 1.003,
            "low": curr_p * 0.997,
            "close": curr_p,
            "volume": 100_000.0,
            "time": t_iso,
        }
        candles.append(candle)
    return candles


# ── Test 1: ExperimentSpec Invariance & Hashing ───────────────────────────────

def test_1_experiment_spec_invariance_and_hashing():
    """ExperimentSpec produces a deterministic SHA-256 digest invariant to property ordering."""
    spec1 = ExperimentSpec(
        experiment_id="exp-test-1",
        strategy_id="sma_trend",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-btc-2026",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )
    spec2 = ExperimentSpec(
        experiment_id="exp-test-1",
        strategy_id="sma_trend",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-btc-2026",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )
    assert spec1.spec_hash == spec2.spec_hash
    assert len(spec1.spec_hash) == 64

    # Frozen dataclass cannot be mutated
    with pytest.raises(Exception):
        spec1.initial_capital = 20_000.0


# ── Test 2: ExperimentResult Standard Accounting ─────────────────────────────

def test_2_experiment_result_accounting_and_empty_trades():
    """ExperimentResult cleanly identifies non-estimable metrics for zero-trade runs."""
    spec = build_champion_baseline_spec(oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"))
    
    # 2a. Zero trade run
    res_empty = ExperimentResult.from_trades_and_equity(spec, [], [])
    assert res_empty.total_trades == 0
    assert res_empty.is_estimable is False
    assert res_empty.win_rate is None
    assert res_empty.profit_factor is None
    assert res_empty.status == "EMPTY_TRADES"

    # 2b. Standard positive trade run
    trades = [
        {"symbol": "BTCUSDT", "gross_pnl": 50.0, "fee_usd": 1.0, "net_pnl": 49.0, "notional": 1000.0, "direction": "LONG"},
        {"symbol": "BTCUSDT", "gross_pnl": -20.0, "fee_usd": 1.0, "net_pnl": -21.0, "notional": 1000.0, "direction": "LONG"},
        {"symbol": "BTCUSDT", "gross_pnl": 30.0, "fee_usd": 1.0, "net_pnl": 29.0, "notional": 1000.0, "direction": "SHORT"},
        {"symbol": "BTCUSDT", "gross_pnl": 40.0, "fee_usd": 1.0, "net_pnl": 39.0, "notional": 1000.0, "direction": "LONG"},
        {"symbol": "BTCUSDT", "gross_pnl": -10.0, "fee_usd": 1.0, "net_pnl": -11.0, "notional": 1000.0, "direction": "SHORT"},
    ]
    eq_curve = [{"equity": 10_000.0 + i * 15.0} for i in range(10)]
    res = ExperimentResult.from_trades_and_equity(spec, trades, eq_curve)
    
    assert res.total_trades == 5
    assert res.winning_trades == 3
    assert res.losing_trades == 2
    assert res.gross_pnl == 90.0
    assert res.net_pnl == 85.0
    assert res.total_fees == 5.0
    assert res.win_rate == 0.6
    assert res.is_estimable is True


# ── Test 3: Always Flat Strategy Baseline ─────────────────────────────────────

def test_3_always_flat_strategy_baseline():
    """AlwaysFlatStrategy records exactly 0 trades, 0 PnL, and 0 drift."""
    candles = _generate_synthetic_candles("BTCUSDT", n_bars=100)
    spec = ExperimentSpec(
        experiment_id="exp-flat-1",
        strategy_id="always_flat",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-test",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )
    runner = ExperimentRunner(spec)
    result = runner.run(AlwaysFlatStrategy(), {"BTCUSDT": candles})

    assert result.total_trades == 0
    assert result.net_pnl == 0.0
    assert result.total_fees == 0.0
    assert result.final_equity == 10_000.0
    assert result.is_estimable is False


# ── Test 4: Passive Buy & Hold Baseline ──────────────────────────────────────

def test_4_passive_buy_and_hold_baseline():
    """Passive Buy & Hold executes on first bar and holds, accurately reflecting underlying move."""
    candles = _generate_synthetic_candles("BTCUSDT", n_bars=100, start_price=50_000.0, trend_pct=0.10)
    spec = ExperimentSpec(
        experiment_id="exp-bnh-1",
        strategy_id="buy_and_hold",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-test",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
        allocation_pct=0.20,
    )
    # Test with liquidation at end
    runner_liq = ExperimentRunner(spec, liquidate_at_end=True)
    res_liq = runner_liq.run(PassiveBuyAndHoldStrategy(), {"BTCUSDT": candles})

    assert res_liq.total_trades == 1
    assert res_liq.resolved_trades == 1
    assert res_liq.total_fees > 0.0
    # Asset went up ~10%, so net PnL is positive on the allocated position
    assert res_liq.net_pnl > 0.0
    assert res_liq.final_equity > 10_000.0
    assert round(res_liq.gross_pnl - res_liq.total_fees, 2) == round(res_liq.net_pnl, 2)
    assert round(res_liq.initial_capital + res_liq.net_pnl, 2) == round(res_liq.final_equity, 2)

    # Test with position remaining open at end
    runner_open = ExperimentRunner(spec, liquidate_at_end=False)
    res_open = runner_open.run(PassiveBuyAndHoldStrategy(), {"BTCUSDT": candles})
    assert res_open.open_positions_count == 1
    assert res_open.unrealized_pnl > 0.0
    assert res_open.final_equity > 10_000.0
    assert res_open.reconciliation_error < 1e-4


# ── Test 5: SMA Trend Following Baseline ──────────────────────────────────────

def test_5_sma_trend_following_baseline():
    """SMA Crossover enters on golden cross and closes on death cross."""
    candles = _generate_synthetic_candles("BTCUSDT", n_bars=150, start_price=50_000.0, trend_pct=0.08)
    spec = ExperimentSpec(
        experiment_id="exp-sma-1",
        strategy_id="sma_crossover",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-test",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )
    runner = ExperimentRunner(spec, liquidate_at_end=True)
    result = runner.run(SimpleMovingAverageCrossoverStrategy(fast_period=5, slow_period=15), {"BTCUSDT": candles})

    assert result.total_trades >= 1
    assert result.total_fees > 0.0
    assert len(result.trade_lineage) == result.resolved_trades
    assert abs((result.gross_pnl - result.total_fees) - result.net_pnl) <= 0.02
    assert abs((result.initial_capital + result.net_pnl) - result.final_equity) <= 0.02


# ── Test 6: Pure Deterministic Reproducibility ────────────────────────────────

def test_6_pure_deterministic_reproducibility():
    """Running the exact same ExperimentSpec twice yields 100% bit-for-bit identical results."""
    candles = _generate_synthetic_candles("BTCUSDT", n_bars=120)
    spec = build_champion_baseline_spec(
        experiment_id="exp-repro-test",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )
    strategy1 = Champion7LayerStrategy(r_multiple=2.0)
    strategy2 = Champion7LayerStrategy(r_multiple=2.0)

    runner1 = ExperimentRunner(spec)
    runner2 = ExperimentRunner(spec)

    res1 = runner1.run(strategy1, {"BTCUSDT": candles})
    res2 = runner2.run(strategy2, {"BTCUSDT": candles})

    # Exact equality across all financial and operational metrics
    assert res1.spec_hash == res2.spec_hash
    assert res1.net_pnl == res2.net_pnl
    assert res1.gross_pnl == res2.gross_pnl
    assert res1.total_fees == res2.total_fees
    assert res1.total_trades == res2.total_trades
    assert res1.final_equity == res2.final_equity
    assert res1.max_drawdown_pct == res2.max_drawdown_pct


# ── Test 7: Multi-Baseline Comparison Report ──────────────────────────────────

def test_7_multi_baseline_comparison_report():
    """Runs all 4 baselines on the exact same dataset and produces comparable metrics."""
    candles = _generate_synthetic_candles("BTCUSDT", n_bars=150, start_price=50_000.0, trend_pct=0.06)
    dataset = {"BTCUSDT": candles}
    
    spec = ExperimentSpec(
        experiment_id="exp-multi-comparison",
        strategy_id="multi_eval",
        strategy_version="1.0",
        dataset_manifest_identity="manifest-test",
        feature_set_version="f-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="15m",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
        allocation_pct=0.10,
    )
    runner = ExperimentRunner(spec)

    strategies = [
        AlwaysFlatStrategy(),
        PassiveBuyAndHoldStrategy(),
        SimpleMovingAverageCrossoverStrategy(fast_period=5, slow_period=15),
        Champion7LayerStrategy(r_multiple=2.0),
    ]

    results = {}
    for strat in strategies:
        res = runner.run(strat, dataset)
        results[strat.name] = res

    assert "always_flat" in results
    assert "buy_and_hold" in results
    assert "sma_crossover_5_15" in results
    assert "champion_v3_7layer" in results

    # Verify Always Flat has zero cost drag
    assert results["always_flat"].total_fees == 0.0
    assert results["always_flat"].net_pnl == 0.0

    # Verify all strategies share the exact same initial capital
    for name, r in results.items():
        assert r.initial_capital == 10_000.0
