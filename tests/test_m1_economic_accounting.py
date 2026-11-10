"""
tests/test_m1_economic_accounting.py
Comprehensive validation of canonical economic accounting, financial reconciliation,
execution timing (Next-Bar-Open), and ExperimentSpec deep immutability.
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
    build_seven_layer_proxy_spec,
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


def _make_bar(
    time_iso: str,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 1000.0,
    symbol: str = "BTCUSDT",
) -> dict:
    return {
        "symbol": symbol,
        "time": time_iso,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
    }


def _make_spec(**overrides) -> ExperimentSpec:
    defaults = {
        "experiment_id": "exp-acct-test",
        "strategy_id": "test_strat",
        "strategy_version": "1.0",
        "dataset_manifest_identity": "manifest-test",
        "feature_set_version": "f-v1",
        "symbol_universe": ("BTCUSDT",),
        "timeframe": "15m",
        "oos_window": ("2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z"),
        "initial_capital": 10_000.0,
        "allocation_pct": 0.10,  # $1000 per trade
        "execution_timing_policy": "NEXT_BAR_OPEN",
        "same_candle_policy": "CONSERVATIVE_SL_FIRST",
    }
    defaults.update(overrides)
    return ExperimentSpec(**defaults)


# ── 1. No Trade Invariant ─────────────────────────────────────────────────────

def test_1_no_trade_cash_equity_invariance():
    """No trade executed keeps cash and equity unchanged at initial_capital with 0 fees."""
    spec = _make_spec(strategy_id="always_flat")
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50100, 49900, 50050),
        _make_bar("2026-04-01T00:15:00Z", 50050, 50200, 50000, 50150),
    ]
    runner = ExperimentRunner(spec)
    res = runner.run(AlwaysFlatStrategy(), {"BTCUSDT": bars})

    assert res.total_trades == 0
    assert res.resolved_trades == 0
    assert res.open_positions_count == 0
    assert res.cash_settled == 10_000.0
    assert res.final_equity == 10_000.0
    assert res.gross_realized_pnl == 0.0
    assert res.net_realized_pnl == 0.0
    assert res.unrealized_pnl == 0.0
    assert res.total_fees == 0.0
    assert res.reconciliation_error == 0.0


# ── 2. Single Completed Round Trip Reconciliation ─────────────────────────────

def test_2_single_round_trip_reconciliation():
    """Single completed round trip: gross - total_fee == net_pnl, and equity == initial + net_pnl."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 5.0, "is_futures": True},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
        allocation_pct=0.10,
    )
    # Target notional: $1000.
    # Bar 0: Signal BUY emitted at close
    # Bar 1: Fill BUY at Open=50000. Qty = 1000 / 50000 = 0.02. Entry fee = 1000 * 0.0005 = 0.50.
    #        Signal CLOSE emitted at close.
    # Bar 2: Fill CLOSE at Open=55000 (+10%). Notional exit = 0.02 * 55000 = 1100.
    #        Gross PnL = (55000 - 50000) * 0.02 = 100.00.
    #        Exit fee = 1100 * 0.0005 = 0.55.
    #        Total fee = 0.50 + 0.55 = 1.05.
    #        Net PnL = 100.00 - 1.05 = 98.95.
    #        Final cash / equity = 10000 + 98.95 = 10098.95.
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 49900, 50100, 49800, 50000),
        _make_bar("2026-04-01T00:15:00Z", 50000, 52000, 49900, 52000),
        _make_bar("2026-04-01T00:30:00Z", 55000, 56000, 54000, 55500),
    ]

    class SingleTradeStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if len(historical_candles) == 1 and current_position is None:
                return {"action": "BUY"}
            elif len(historical_candles) == 2 and current_position is not None:
                return {"action": "CLOSE"}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(SingleTradeStrategy("single_trade"), {"BTCUSDT": bars})

    assert res.total_trades == 1
    assert res.resolved_trades == 1
    assert res.open_positions_count == 0
    assert abs(res.gross_realized_pnl - 100.00) < 1e-2
    assert abs(res.total_fees - 1.05) < 1e-2
    assert abs(res.net_realized_pnl - 98.95) < 1e-2
    assert abs(res.final_equity - 10098.95) < 1e-2
    assert abs(res.cash_settled - 10098.95) < 1e-2
    # Canonical Invariant: net_pnl = gross_pnl - total_fee
    assert round(res.gross_realized_pnl - res.total_fees, 2) == round(res.net_realized_pnl, 2)
    # Canonical Invariant: final_equity = initial_capital + net_realized_pnl
    assert round(res.initial_capital + res.net_realized_pnl, 2) == round(res.final_equity, 2)
    assert res.reconciliation_error < 1e-4


# ── 3. Multiple Completed Trades ──────────────────────────────────────────────

def test_3_multiple_completed_trades_reconciliation():
    """Multiple trades: sum of net PnL and total fees matches final cash and equity exactly."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 5.0, "is_futures": True},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
        allocation_pct=0.10,
    )
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000), # bar 0: emit buy 1
        _make_bar("2026-04-01T00:15:00Z", 50000, 52000, 50000, 52000), # bar 1: fill buy 1 at 50000, emit close 1
        _make_bar("2026-04-01T00:30:00Z", 52000, 52000, 50000, 51000), # bar 2: fill close 1 at 52000, emit buy 2
        _make_bar("2026-04-01T00:45:00Z", 51000, 51000, 48000, 49000), # bar 3: fill buy 2 at 51000, emit close 2
        _make_bar("2026-04-01T01:00:00Z", 49000, 49000, 48000, 48500), # bar 4: fill close 2 at 49000
    ]

    class MultiTradeStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            step = len(historical_candles) - 1
            if step == 0 and current_position is None:
                return {"action": "BUY"}
            elif step == 1 and current_position is not None:
                return {"action": "CLOSE"}
            elif step == 2 and current_position is None:
                return {"action": "BUY"}
            elif step == 3 and current_position is not None:
                return {"action": "CLOSE"}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(MultiTradeStrategy("multi_trade"), {"BTCUSDT": bars})

    assert res.resolved_trades == 2
    assert res.open_positions_count == 0
    # Invariant: net_pnl = gross_pnl - total_fees
    assert round(res.gross_realized_pnl - res.total_fees, 2) == round(res.net_realized_pnl, 2)
    # Invariant: final_equity = initial_capital + net_realized_pnl
    assert round(res.initial_capital + res.net_realized_pnl, 2) == round(res.final_equity, 2)
    assert res.reconciliation_error < 1e-4


# ── 4. Open Position at End of Period ─────────────────────────────────────────

def test_4_open_position_end_of_period_accounting():
    """Open position at end: cash + marked_position_value == final_equity, unrealized tracked cleanly."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 5.0, "is_futures": True},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
        allocation_pct=0.10,
    )
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000), # emit BUY
        _make_bar("2026-04-01T00:15:00Z", 50000, 55000, 50000, 55000), # fill BUY at 50000 ($1000 notional, fee $0.50). Close is 55000 (+10%).
    ]

    class OpenPositionStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if current_position is None and len(historical_candles) == 1:
                return {"action": "BUY"}
            return None

    runner = ExperimentRunner(spec, liquidate_at_end=False)
    res = runner.run(OpenPositionStrategy("open_strat"), {"BTCUSDT": bars})

    assert res.total_trades == 1
    assert res.resolved_trades == 0
    assert res.open_positions_count == 1
    assert res.net_realized_pnl == 0.0
    assert abs(res.total_open_entry_fees - 0.50) < 1e-2
    # Cash settled: initial ($10000) - invested ($1000) - entry fee ($0.50) = $8999.50
    assert abs(res.cash_settled - 8999.50) < 1e-2
    # Marked position value: 0.02 BTC * 55000 = $1100.00
    assert abs(res.marked_position_value - 1100.00) < 1e-2
    # Final Equity: 8999.50 + 1100.00 = 10099.50
    assert abs(res.final_equity - 10099.50) < 1e-2
    # Unrealized PnL: 1100 - 1000 = 100.00
    assert abs(res.unrealized_pnl - 100.00) < 1e-2

    # Invariant: final_equity = cash_settled + marked_position_value
    assert round(res.cash_settled + res.marked_position_value, 2) == round(res.final_equity, 2)
    # Invariant: final_equity = initial_capital + net_realized + unrealized - open_entry_fees
    theoretical = res.initial_capital + res.net_realized_pnl + res.unrealized_pnl - res.total_open_entry_fees
    assert round(theoretical, 2) == round(res.final_equity, 2)
    assert res.reconciliation_error < 1e-4


# ── 5. Loss-Making Trade ──────────────────────────────────────────────────────

def test_5_loss_making_trade_reconciliation():
    """Loss-making trade: net_pnl is negative, fee increases loss, cash reconciles."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 5.0, "is_futures": True},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
        allocation_pct=0.10,
    )
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000),
        _make_bar("2026-04-01T00:15:00Z", 50000, 50000, 45000, 46000), # fill BUY at 50000 ($1000 notional, fee $0.50)
        _make_bar("2026-04-01T00:30:00Z", 45000, 46000, 44000, 45000), # fill CLOSE at 45000 (-10%)
    ]

    class LossStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if len(historical_candles) == 1 and current_position is None:
                return {"action": "BUY"}
            elif len(historical_candles) == 2 and current_position is not None:
                return {"action": "CLOSE"}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(LossStrategy("loss_strat"), {"BTCUSDT": bars})

    assert res.resolved_trades == 1
    assert res.winning_trades == 0
    assert res.losing_trades == 1
    assert abs(res.gross_realized_pnl - (-100.00)) < 1e-2
    # Exit fee: 900 * 0.0005 = 0.45. Total fee = 0.50 + 0.45 = 0.95.
    assert abs(res.total_fees - 0.95) < 1e-2
    assert abs(res.net_realized_pnl - (-100.95)) < 1e-2
    assert abs(res.final_equity - (10_000.0 - 100.95)) < 1e-2
    assert round(res.gross_realized_pnl - res.total_fees, 2) == round(res.net_realized_pnl, 2)
    assert round(res.initial_capital + res.net_realized_pnl, 2) == round(res.final_equity, 2)


# ── 6. Full Friction: Fee + Spread + Slippage ─────────────────────────────────

def test_6_spread_and_slippage_friction():
    """Friction test: spread and slippage adjust effective entry up and exit down."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 5.0, "is_futures": True},
        slippage_model={"enabled": True, "base_slippage_bps": 2.0},
        spread_model={"enabled": True, "typical_spread_bps": 2.0},
        allocation_pct=0.10,
    )
    # Buy at raw 50000:
    # spread_drag = 50000 * (2 / 20000) = 5.0
    # slip_drag = 50000 * (2 / 10000) = 10.0
    # effective_entry_price = 50015.0
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000),
        _make_bar("2026-04-01T00:15:00Z", 50000, 50000, 50000, 50000),
        _make_bar("2026-04-01T00:30:00Z", 50000, 50000, 50000, 50000),
    ]

    class FlatMoveStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if len(historical_candles) == 1 and current_position is None:
                return {"action": "BUY"}
            elif len(historical_candles) == 2 and current_position is not None:
                return {"action": "CLOSE"}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(FlatMoveStrategy("flat_move"), {"BTCUSDT": bars})

    # Both entry and exit incurred spread and slippage on the same raw price 50000
    assert res.total_slippage > 0.0
    assert res.total_spread > 0.0
    assert res.total_fees > 0.0
    # Because of friction, buying and selling at flat raw price 50000 yields negative net PnL
    assert res.net_realized_pnl < 0.0
    assert round(res.gross_realized_pnl - res.total_fees, 2) == round(res.net_realized_pnl, 2)
    assert round(res.initial_capital + res.net_realized_pnl, 2) == round(res.final_equity, 2)


# ── 7. Insufficient Cash Guard ────────────────────────────────────────────────

def test_7_insufficient_cash_guard():
    """When capital is depleted or below minimum notional ($10), new orders are rejected safely."""
    spec = _make_spec(
        initial_capital=5.0,  # Below minimum trade size
        allocation_pct=1.0,
    )
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000),
        _make_bar("2026-04-01T00:15:00Z", 50000, 50000, 50000, 50000),
    ]

    class ForceBuyStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            return {"action": "BUY"}

    runner = ExperimentRunner(spec)
    res = runner.run(ForceBuyStrategy("force_buy"), {"BTCUSDT": bars})

    # No trade executed due to insufficient capital
    assert res.total_trades == 0
    assert res.final_equity == 5.0
    assert res.cash_settled == 5.0


# ── 8. Execution Timing: NEXT_BAR_OPEN Verification ───────────────────────────

def test_8_next_bar_open_execution_timing():
    """Signal at bar t close does NOT fill at bar t; it fills at bar t+1 open."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 0.0},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
    )
    # Bar 0: Close is 50000. Signal BUY emitted.
    # Bar 1: Open is 51000 (gapped up at open). Fill must occur at 51000, NOT 50000!
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 49500, 50500, 49000, 50000),
        _make_bar("2026-04-01T00:15:00Z", 51000, 52000, 50500, 51500),
    ]

    class TimingCheckStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if len(historical_candles) == 1:
                return {"action": "BUY"}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(TimingCheckStrategy("timing_strat"), {"BTCUSDT": bars})

    assert res.open_positions_count == 1
    open_pos = res.open_positions_snapshot[0]
    # Verified: entry price is 51000 (bar 1 open), proving no lookahead to bar 0 close
    assert open_pos["entry_price"] == 51000.0
    assert open_pos["entry_time"] == "2026-04-01T00:15:00Z"


# ── 9. Intrabar Gap and Same-Candle SL/TP Policy ───────────────────────────────

def test_9_gap_and_same_candle_conservative_policy():
    """When a bar touches both SL and TP, CONSERVATIVE_SL_FIRST triggers SL; gap past SL exits at open."""
    spec = _make_spec(
        fee_model={"futures_taker_bps": 0.0},
        slippage_model={"enabled": False},
        spread_model={"enabled": False},
        same_candle_policy="CONSERVATIVE_SL_FIRST",
    )
    # Bar 0: emit BUY with SL=48000, TP=55000.
    # Bar 1: Open=50000. Position opened. High=56000 (touches TP), Low=47000 (touches SL).
    # Since CONSERVATIVE_SL_FIRST is configured, SL must hit!
    bars = [
        _make_bar("2026-04-01T00:00:00Z", 50000, 50000, 50000, 50000),
        _make_bar("2026-04-01T00:15:00Z", 50000, 56000, 47000, 51000),
    ]

    class VolatileBarStrategy(BaselineStrategy):
        def evaluate_bar(self, symbol, current_candle, historical_candles, current_position):
            if current_position is None and len(historical_candles) == 1:
                return {"action": "BUY", "stop_loss": 48000.0, "take_profit": 55000.0}
            return None

    runner = ExperimentRunner(spec)
    res = runner.run(VolatileBarStrategy("vol_strat"), {"BTCUSDT": bars})

    assert res.resolved_trades == 1
    trade = res.trade_lineage[0]
    assert "stop_loss" in trade["reason"]
    assert trade["exit_price"] == 48000.0


# ── 10. ExperimentSpec Deep Immutability ───────────────────────────────────────

def test_10_experiment_spec_deep_immutability():
    """Nested parameters and models cannot be mutated post-init; spec_hash remains immutable."""
    spec = build_champion_baseline_spec()
    
    # 10a. Top level mutation fails
    with pytest.raises(Exception):
        spec.initial_capital = 99999.0

    # 10b. Nested mapping mutation fails (MappingProxyType)
    with pytest.raises(TypeError):
        spec.fee_model["futures_taker_bps"] = 999.0

    with pytest.raises(TypeError):
        spec.slippage_model["base_slippage_bps"] = 999.0

    with pytest.raises(TypeError):
        spec.parameters["min_confidence"] = 0.10

    # Spec hash is non-empty and 64 hex chars
    assert len(spec.spec_hash) == 64


# ── 11. SevenLayerProxy vs Champion Baseline Governance ────────────────────────

def test_11_seven_layer_proxy_governance_and_status():
    """SevenLayerProxy is explicitly marked PROXY / NOT_PRODUCTION_EQUIVALENT."""
    proxy_spec = build_seven_layer_proxy_spec()
    assert proxy_spec.strategy_tier == "PROXY"
    assert proxy_spec.parameters["proxy_status"] == "PROXY / NOT_PRODUCTION_EQUIVALENT"

    strat = SevenLayerProxyStrategy()
    assert strat.TIER == "PROXY"
    assert strat.STATUS == "PROXY / NOT_PRODUCTION_EQUIVALENT"

    champ_alias = Champion7LayerStrategy()
    assert champ_alias.TIER == "PROXY"
    assert champ_alias.STATUS == "PROXY / NOT_PRODUCTION_EQUIVALENT"
