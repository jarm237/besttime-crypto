"""Unit tests for Canonical Runtime Contract Parity and P4 Serialization."""
from __future__ import annotations

import pandas as pd
import pytest

from btc_scraper.trading.event_driven_accounting import (
    AccountingConfig,
    EventDrivenAccountingEngine,
)


def test_p4_cooldown_blocks_same_asset_within_96_bars():
    """P4 Rule: 96-bar (24h) cooldown blocks second trade on same asset."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        cooldown_bars=96,
        bar_interval_minutes=15,  # 96 * 15m = 1440m = 24h
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        # Trade 1: BTC exits at 12:00 on Day 1
        {
            "trade_id": "T1",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2026-10-01T10:00:00Z",
            "exit_timestamp": "2026-10-01T12:00:00Z",
            "entry_price": 50000.0,
            "exit_price": 50250.0,
            "raw_pnl": 0.0050,
        },
        # Trade 2: BTC tries to enter at 16:00 on Day 1 (only 4 hours after exit < 24h cooldown)
        {
            "trade_id": "T2",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2026-10-01T16:00:00Z",
            "exit_timestamp": "2026-10-01T18:00:00Z",
            "entry_price": 50300.0,
            "exit_price": 50550.0,
            "raw_pnl": 0.0050,
        },
        # Trade 3: BTC enters at 12:01 on Day 2 (> 24h after Day 1 exit)
        {
            "trade_id": "T3",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2026-10-02T12:01:00Z",
            "exit_timestamp": "2026-10-02T14:00:00Z",
            "entry_price": 50600.0,
            "exit_price": 50850.0,
            "raw_pnl": 0.0050,
        },
    ]

    res = engine.run(candidates)
    assert res.executed_trades_count == 2
    assert res.rejected_capacity_count == 1
    executed_ids = [t.trade_id for t in res.executed_trades]
    assert executed_ids == ["T1", "T3"]


def test_p4_global_concurrency_limit_3():
    """P4 Rule: Maximum 3 concurrent positions globally."""
    cfg = AccountingConfig(
        initial_capital=100000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
    )
    engine = EventDrivenAccountingEngine(cfg)

    # 4 distinct assets arriving at same timestamp
    candidates = [
        {"trade_id": f"T_{sym}", "symbol": sym, "side": "BUY", "entry_timestamp": "2026-10-01T10:00:00Z", "exit_timestamp": "2026-10-01T12:00:00Z", "raw_pnl": 0.005}
        for sym in ["BTC", "ETH", "BNB", "SOL"]
    ]

    res = engine.run(candidates)
    assert res.executed_trades_count == 3
    assert res.rejected_capacity_count == 1


def test_p4_side_lock_rejects_opposing_position():
    """P4 Rule: No opposing positions on same asset."""
    cfg = AccountingConfig(
        initial_capital=100000.0,
        max_concurrent_positions=5,
        max_positions_per_asset=2,  # even if asset limit was > 1
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        # Long BTC
        {"trade_id": "T_LONG", "symbol": "BTC", "side": "BUY", "entry_timestamp": "2026-10-01T10:00:00Z", "exit_timestamp": "2026-10-01T14:00:00Z", "raw_pnl": 0.01},
        # Short BTC while Long is active
        {"trade_id": "T_SHORT", "symbol": "BTC", "side": "SELL", "entry_timestamp": "2026-10-01T11:00:00Z", "exit_timestamp": "2026-10-01T13:00:00Z", "raw_pnl": 0.01},
    ]

    res = engine.run(candidates)
    assert res.executed_trades_count == 1
    assert res.executed_trades[0].trade_id == "T_LONG"
    assert res.rejected_capacity_count == 1


def test_same_timestamp_exit_frees_capacity_for_entry():
    """Parity Rule: Exit at timestamp t releases capital and slot for entry at timestamp t."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=1,  # strictly 1 position at a time
        max_positions_per_asset=1,
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        # Position 1: BTC closes at 12:00
        {"trade_id": "T1", "symbol": "BTC", "side": "BUY", "entry_timestamp": "2026-10-01T10:00:00Z", "exit_timestamp": "2026-10-01T12:00:00Z", "raw_pnl": 0.01},
        # Position 2: ETH enters at 12:00 (exact same timestamp as BTC exit)
        {"trade_id": "T2", "symbol": "ETH", "side": "BUY", "entry_timestamp": "2026-10-01T12:00:00Z", "exit_timestamp": "2026-10-01T14:00:00Z", "raw_pnl": 0.01},
    ]

    res = engine.run(candidates)
    assert res.executed_trades_count == 2
    assert res.rejected_capacity_count == 0


def test_mark_to_market_captures_intratrade_drawdown():
    """MTM Path Rule: Intratrade adverse price excursion produces deeper MTM drawdown than realized drawdown."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=1,
        allocation_pct_per_trade=1.0,  # 100% allocation
        fee_rate_bps=0.0,             # zero fee for exact price tracking
        slippage_bps=0.0,
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    # Trade: Entry at $100, Exit at $105 (+5% win realized)
    candidates = [{
        "trade_id": "T1",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-01T10:00:00Z",
        "exit_timestamp": "2026-10-01T10:45:00Z",
        "entry_price": 100.0,
        "exit_price": 105.0,
        "raw_pnl": 0.05,
    }]

    # Candle path:
    # 10:00 -> 100 (entry)
    # 10:15 -> 80  (intratrade plunge -20%!)
    # 10:30 -> 90
    # 10:45 -> 105 (exit with +5% win)
    candle_df = pd.DataFrame([
        {"timestamp": "2026-10-01T10:00:00Z", "close": 100.0},
        {"timestamp": "2026-10-01T10:15:00Z", "close": 80.0},
        {"timestamp": "2026-10-01T10:30:00Z", "close": 90.0},
        {"timestamp": "2026-10-01T10:45:00Z", "close": 105.0},
    ])

    res = engine.run(candidates, candle_data={"BTC": candle_df})

    # Realized drawdown on event curve: initial 10,000 -> final 10,500 (0% realized DD)
    assert res.realized_drawdown_pct == 0.0

    # MTM drawdown captured the -20% dip to $8,000!
    assert res.mtm_drawdown_pct == pytest.approx(20.0, abs=0.1)
    assert res.max_drawdown_pct == pytest.approx(20.0, abs=0.1)
    assert res.win_count == 1
    assert res.final_equity == pytest.approx(10500.0)


def test_short_trade_mtm_valuation():
    """Short Trade MTM Rule: Short position gains when price drops and loses when price rises."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=1,
        allocation_pct_per_trade=1.0,
        fee_rate_bps=0.0,
        slippage_bps=0.0,
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [{
        "trade_id": "T_SHORT",
        "symbol": "ETH",
        "side": "SELL",
        "entry_timestamp": "2026-10-01T10:00:00Z",
        "exit_timestamp": "2026-10-01T10:30:00Z",
        "entry_price": 2000.0,
        "exit_price": 1800.0,
        "raw_pnl": 0.10,  # +10% gain on short
    }]

    candle_df = pd.DataFrame([
        {"timestamp": "2026-10-01T10:00:00Z", "close": 2000.0},
        {"timestamp": "2026-10-01T10:15:00Z", "close": 2200.0},  # price went up: short loses 10%
        {"timestamp": "2026-10-01T10:30:00Z", "close": 1800.0},  # price dropped: short wins 10%
    ])

    res = engine.run(candidates, candle_data={"ETH": candle_df})

    # Intratrade dip from 10,000 to 9,000 is 10% DD
    assert res.mtm_drawdown_pct == pytest.approx(10.0, abs=0.1)
    assert res.final_equity == pytest.approx(11000.0)

