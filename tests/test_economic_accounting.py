"""Invariant tests for event-driven capital & economic accounting."""
from __future__ import annotations

import pandas as pd
import pytest

from btc_scraper.trading.event_driven_accounting import (
    AccountingConfig,
    EventDrivenAccountingEngine,
    validate_economic_replay_trade,
)


def test_invariant_1_no_pnl_credited_before_exit():
    """Invariant 1: Cash is locked at entry, and PnL is strictly not added before exit timestamp."""
    cfg = AccountingConfig(initial_capital=10000.0, max_concurrent_positions=2, allocation_pct_per_trade=0.20)
    engine = EventDrivenAccountingEngine(cfg)

    # 1 trade with 10% gain, entry 10:00, exit 11:00
    candidate = [{
        "trade_id": "T1",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-31T10:00:00Z",
        "exit_timestamp": "2026-10-31T11:00:00Z",
        "entry_price": 50000.0,
        "exit_price": 55000.0,
        "raw_pnl": 0.10,
    }]

    res = engine.run(candidate)
    curve = res.equity_curve

    # At entry 10:00, cash must decrease by locked capital + entry fee
    entry_row = curve[curve["timestamp"] == pd.Timestamp("2026-10-31T10:00:00Z")].iloc[0]
    assert entry_row["locked_capital"] == pytest.approx(2000.0)
    assert entry_row["cash"] < 10000.0 - 2000.0  # entry fee deducted
    assert entry_row["equity"] <= 10000.0  # equity does NOT reflect unbooked future profit!

    # At exit 11:00, cash is released with net profit
    exit_row = curve[curve["timestamp"] == pd.Timestamp("2026-10-31T11:00:00Z")].iloc[0]
    assert exit_row["locked_capital"] == 0.0
    assert exit_row["cash"] > 10000.0
    assert exit_row["equity"] > 10000.0


def test_invariant_2_total_locked_cash_bounded_by_capital():
    """Invariant 2: Total locked capital never exceeds available cash or policy limit."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=5,
        allocation_pct_per_trade=0.40,  # 40% each
    )
    engine = EventDrivenAccountingEngine(cfg)

    # 4 overlapping trades requested simultaneously
    candidates = [
        {
            "trade_id": f"T{i}",
            "symbol": sym,
            "side": "BUY",
            "entry_timestamp": "2026-10-31T10:00:00Z",
            "exit_timestamp": "2026-10-31T12:00:00Z",
            "raw_pnl": 0.01,
        }
        for i, sym in enumerate(["BTC", "ETH", "BNB", "SOL"])
    ]

    res = engine.run(candidates)
    curve = res.equity_curve

    # Total locked capital must never exceed initial capital
    for _, row in curve.iterrows():
        assert row["locked_capital"] <= 10000.0
        assert row["cash"] >= 0.0

    # Max 2 could be accepted since 40% * 2 = 80%, 3rd would require 40% of equity which exceeds remaining cash
    assert res.executed_trades_count == 2
    assert res.rejected_capacity_count == 2


def test_invariant_3_concurrent_positions_bounded_by_policy():
    """Invariant 3: Number of concurrent open positions strictly <= max_concurrent_positions."""
    cfg = AccountingConfig(
        initial_capital=100000.0,
        max_concurrent_positions=3,
        allocation_pct_per_trade=0.10,
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        {
            "trade_id": f"T_{i}",
            "symbol": sym,
            "side": "BUY",
            "entry_timestamp": "2026-10-31T10:00:00Z",
            "exit_timestamp": "2026-10-31T15:00:00Z",
            "raw_pnl": 0.01,
        }
        for i, sym in enumerate(["BTC", "ETH", "BNB", "DOGE", "NEAR", "SOL"])
    ]

    res = engine.run(candidates)
    assert res.executed_trades_count == 3
    assert res.rejected_capacity_count == 3


def test_invariant_4_losing_trade_creates_positive_drawdown():
    """Invariant 4: A losing trade MUST produce a positive max drawdown (MDD > 0)."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=2,
        allocation_pct_per_trade=0.25,
        cooldown_bars=0,  # disable cooldown for pure drawdown test
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        # Win first
        {
            "trade_id": "T1",
            "symbol": "BTC",
            "entry_timestamp": "2026-10-31T10:00:00Z",
            "exit_timestamp": "2026-10-31T11:00:00Z",
            "raw_pnl": 0.05,
        },
        # Big loss second
        {
            "trade_id": "T2",
            "symbol": "BTC",
            "entry_timestamp": "2026-10-31T12:00:00Z",
            "exit_timestamp": "2026-10-31T13:00:00Z",
            "raw_pnl": -0.10,
        },
    ]

    res = engine.run(candidates)
    assert res.max_drawdown_pct > 0.0
    assert res.max_drawdown_usd > 0.0
    assert res.loss_count == 1
    assert res.win_count == 1


def test_invariant_5_multiple_exits_same_day_cannot_exceed_leverage():
    """Invariant 5: Multiple exits on the same day cannot create leverage exceeding policy."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=2,
        allocation_pct_per_trade=0.20,
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    # 10 sequential trades closing on the EXACT same day
    candidates = []
    for i in range(10):
        entry_h = 10 + (i // 2)
        exit_h = entry_h + 1
        candidates.append({
            "trade_id": f"SEQ_{i}",
            "symbol": "BTC" if i % 2 == 0 else "ETH",
            "entry_timestamp": f"2026-10-31T{entry_h:02d}:00:00Z",
            "exit_timestamp": f"2026-10-31T{exit_h:02d}:00:00Z",
            "raw_pnl": 0.02,
        })

    res = engine.run(candidates)
    # Total executed trades can be up to 10 because they are sequential,
    # but at ANY timestamp, locked capital was at most 2 * 20% = 40% of equity!
    for _, row in res.equity_curve.iterrows():
        # Locked capital ratio must not exceed 40% (+ slight buffer for compounding)
        locked_ratio = row["locked_capital"] / row["equity"] if row["equity"] > 0 else 0.0
        assert locked_ratio <= 0.4001, f"Excessive leverage observed: {locked_ratio}"


def test_invariant_6_final_equity_matches_cash_plus_realized_pnl():
    """Invariant 6: Final equity matches initial capital + sum of all executed net PnL in USD."""
    cfg = AccountingConfig(initial_capital=10000.0)
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        {
            "trade_id": "T1",
            "symbol": "BTC",
            "entry_timestamp": "2026-10-31T10:00:00Z",
            "exit_timestamp": "2026-10-31T11:00:00Z",
            "raw_pnl": 0.03,
        },
        {
            "trade_id": "T2",
            "symbol": "ETH",
            "entry_timestamp": "2026-10-31T12:00:00Z",
            "exit_timestamp": "2026-10-31T13:00:00Z",
            "raw_pnl": -0.015,
        },
        {
            "trade_id": "T3",
            "symbol": "BNB",
            "entry_timestamp": "2026-10-31T14:00:00Z",
            "exit_timestamp": "2026-10-31T15:00:00Z",
            "raw_pnl": 0.02,
        },
    ]

    res = engine.run(candidates)
    expected_final = cfg.initial_capital + sum(t.net_pnl_usd for t in res.executed_trades)
    assert res.final_equity == pytest.approx(expected_final, rel=1e-8)
    assert res.total_net_pnl_usd == pytest.approx(sum(t.net_pnl_usd for t in res.executed_trades), rel=1e-8)


def test_invariant_7_deterministic_replay():
    """Invariant 7: Running replay twice produces identical equity curves and metrics bit-for-bit."""
    cfg = AccountingConfig(initial_capital=10000.0)
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        {"trade_id": f"T{i}", "symbol": "BTC", "entry_timestamp": f"2026-10-31T{10+i:02d}:00:00Z", "exit_timestamp": f"2026-10-31T{11+i:02d}:00:00Z", "raw_pnl": 0.01 * (1 if i % 2 == 0 else -1)}
        for i in range(5)
    ]

    res1 = engine.run(candidates)
    res2 = engine.run(candidates)

    assert res1.final_equity == res2.final_equity
    assert res1.total_net_pnl_usd == res2.total_net_pnl_usd
    assert res1.max_drawdown_pct == res2.max_drawdown_pct
    assert res1.daily_sharpe == res2.daily_sharpe
    assert len(res1.executed_trades) == len(res2.executed_trades)


# ─── New Schema & Invariant Tests (Section B Requirements) ────────────────────

def test_missing_gross_return_raises_error():
    """Missing gross return MUST fail-closed with ValueError; silent zero PnL prohibited."""
    engine = EventDrivenAccountingEngine()
    invalid_candidate = [{
        "trade_id": "T_NO_PNL",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-31T10:00:00Z",
        "exit_timestamp": "2026-10-31T11:00:00Z",
        # No gross_return_fraction, no gross_pnl_bps, no raw_pnl!
    }]
    with pytest.raises(ValueError, match="missing gross return"):
        engine.run(invalid_candidate)


def test_price_return_inconsistency_raises_error():
    """Contradiction between entry/exit prices and gross return MUST raise ValueError."""
    engine = EventDrivenAccountingEngine()
    # entry 100, exit 110 (+10% gain), but claiming -5% loss
    invalid_candidate = [{
        "trade_id": "T_CONTRADICT",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-31T10:00:00Z",
        "exit_timestamp": "2026-10-31T11:00:00Z",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "gross_return_fraction": -0.05,
    }]
    with pytest.raises(ValueError, match="price-return inconsistency"):
        engine.run(invalid_candidate)


def test_gross_pnl_bps_consistency_validation():
    """Mismatched gross_pnl_bps and gross_return_fraction MUST raise ValueError."""
    engine = EventDrivenAccountingEngine()
    invalid_candidate = [{
        "trade_id": "T_BPS_MISMATCH",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-31T10:00:00Z",
        "exit_timestamp": "2026-10-31T11:00:00Z",
        "gross_pnl_bps": 50.0,            # +50 bps
        "gross_return_fraction": 0.0100,   # +100 bps
    }]
    with pytest.raises(ValueError, match="inconsistency"):
        engine.run(invalid_candidate)


def test_tp_sl_long_short_timeout_accounting():
    """Validates TP, SL, TIMEOUT for Long and Short, confirming ~14 bps friction without double-charge."""
    # 5 bps fee + 2 bps slippage per leg = 7 bps per leg = ~14 bps round-trip
    cfg = AccountingConfig(
        initial_capital=10000.0,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
        allocation_pct_per_trade=0.25,
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    candidates = [
        # 1. Long TP: gross +50 bps (+0.0050)
        {
            "trade_id": "LONG_TP",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2026-10-31T10:00:00Z",
            "exit_timestamp": "2026-10-31T10:30:00Z",
            "entry_price": 10000.0,
            "exit_price": 10050.0,  # (10050 - 10000)/10000 = +0.0050
            "gross_return_fraction": 0.0050,
            "exit_reason": "TP",
        },
        # 2. Long SL: gross -30 bps (-0.0030)
        {
            "trade_id": "LONG_SL",
            "symbol": "ETH",
            "side": "BUY",
            "entry_timestamp": "2026-10-31T11:00:00Z",
            "exit_timestamp": "2026-10-31T11:30:00Z",
            "entry_price": 2000.0,
            "exit_price": 1994.0,   # (1994 - 2000)/2000 = -0.0030
            "gross_return_fraction": -0.0030,
            "exit_reason": "SL",
        },
        # 3. Short TP: gross +50 bps (+0.0050)
        {
            "trade_id": "SHORT_TP",
            "symbol": "BNB",
            "side": "SELL",
            "entry_timestamp": "2026-10-31T12:00:00Z",
            "exit_timestamp": "2026-10-31T12:30:00Z",
            "entry_price": 500.0,
            "exit_price": 497.5,    # (500 - 497.5)/500 = +0.0050
            "gross_return_fraction": 0.0050,
            "exit_reason": "TP",
        },
        # 4. Short SL: gross -30 bps (-0.0030)
        {
            "trade_id": "SHORT_SL",
            "symbol": "BTC",
            "side": "SELL",
            "entry_timestamp": "2026-10-31T13:00:00Z",
            "exit_timestamp": "2026-10-31T13:30:00Z",
            "entry_price": 10000.0,
            "exit_price": 10030.0,  # (10000 - 10030)/10000 = -0.0030
            "gross_return_fraction": -0.0030,
            "exit_reason": "SL",
        },
        # 5. Timeout: gross +15 bps (+0.0015)
        {
            "trade_id": "TIMEOUT_TRADE",
            "symbol": "ETH",
            "side": "BUY",
            "entry_timestamp": "2026-10-31T14:00:00Z",
            "exit_timestamp": "2026-10-31T18:00:00Z",
            "entry_price": 2000.0,
            "exit_price": 2003.0,   # (2003 - 2000)/2000 = +0.0015
            "gross_return_fraction": 0.0015,
            "exit_reason": "TIMEOUT",
            "bars_held": 16,
        },
    ]

    res = engine.run(candidates)
    trades = {t.trade_id: t for t in res.executed_trades}

    # 1. Long TP: gross +50 bps, net ~ +36 bps (+35.96 bps after compounding slippage/fee)
    t_long_tp = trades["LONG_TP"]
    assert t_long_tp.gross_return_fraction == pytest.approx(0.0050, rel=1e-4)
    assert 35.8 < t_long_tp.net_return_bps < 36.2
    assert t_long_tp.exit_reason == "TP"

    # 2. Long SL: gross -30 bps, net ~ -44 bps (-43.98 bps)
    t_long_sl = trades["LONG_SL"]
    assert t_long_sl.gross_return_fraction == pytest.approx(-0.0030, rel=1e-4)
    assert -44.2 < t_long_sl.net_return_bps < -43.8
    assert t_long_sl.exit_reason == "SL"

    # 3. Short TP: gross +50 bps, net ~ +36 bps
    t_short_tp = trades["SHORT_TP"]
    assert t_short_tp.gross_return_fraction == pytest.approx(0.0050, rel=1e-4)
    assert 35.8 < t_short_tp.net_return_bps < 36.2
    assert t_short_tp.exit_reason == "TP"

    # 4. Short SL: gross -30 bps, net ~ -44 bps
    t_short_sl = trades["SHORT_SL"]
    assert t_short_sl.gross_return_fraction == pytest.approx(-0.0030, rel=1e-4)
    assert -44.2 < t_short_sl.net_return_bps < -43.8
    assert t_short_sl.exit_reason == "SL"

    # 5. Timeout: gross +15 bps, net ~ +1 bps (+0.97 bps)
    t_timeout = trades["TIMEOUT_TRADE"]
    assert t_timeout.gross_return_fraction == pytest.approx(0.0015, rel=1e-4)
    assert 0.8 < t_timeout.net_return_bps < 1.2
    assert t_timeout.exit_reason == "TIMEOUT"
    assert t_timeout.bars_held == 16


def test_half_open_date_range_and_cross_boundary_exclude_policy():
    """Enforces half-open [start, end) across entries, MTM grid, daily calendar, and cross-boundary exits."""
    cfg = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=5,
        max_positions_per_asset=5,
        allocation_pct_per_trade=0.10,
        cooldown_bars=0,
    )
    engine = EventDrivenAccountingEngine(cfg)

    start = "2024-01-01T00:00:00Z"
    end = "2024-01-03T00:00:00Z"  # Half-open [2024-01-01 00:00Z, 2024-01-03 00:00Z)

    candidates = [
        # Before start -> excluded
        {
            "trade_id": "BEFORE_START",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2023-12-31T23:45:00Z",
            "exit_timestamp": "2024-01-01T00:15:00Z",
            "gross_return_fraction": 0.01,
        },
        # Entry exactly at start, exit strictly < end -> INCLUDED
        {
            "trade_id": "AT_START",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2024-01-01T00:00:00Z",
            "exit_timestamp": "2024-01-01T01:00:00Z",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "gross_return_fraction": 0.01,
        },
        # Entry at end - 15m, exit strictly < end (say end - 5m) -> INCLUDED
        {
            "trade_id": "BEFORE_END_INSIDE",
            "symbol": "ETH",
            "side": "BUY",
            "entry_timestamp": "2024-01-02T23:30:00Z",
            "exit_timestamp": "2024-01-02T23:45:00Z",
            "entry_price": 200.0,
            "exit_price": 202.0,
            "gross_return_fraction": 0.01,
        },
        # Entry at end - 15m, exit EXACTLY at end -> cross-boundary -> EXCLUDED under default policy
        {
            "trade_id": "CROSS_EXIT_AT_END",
            "symbol": "BNB",
            "side": "BUY",
            "entry_timestamp": "2024-01-02T23:45:00Z",
            "exit_timestamp": "2024-01-03T00:00:00Z",
            "entry_price": 300.0,
            "exit_price": 309.0,
            "gross_return_fraction": 0.03,
        },
        # Entry at end - 15m, exit AFTER end -> cross-boundary -> EXCLUDED under default policy
        {
            "trade_id": "CROSS_EXIT_AFTER_END",
            "symbol": "SOL",
            "side": "BUY",
            "entry_timestamp": "2024-01-02T23:45:00Z",
            "exit_timestamp": "2024-01-03T01:00:00Z",
            "entry_price": 100.0,
            "exit_price": 105.0,
            "gross_return_fraction": 0.05,
        },
        # Entry EXACTLY at end -> outside [start, end) -> EXCLUDED (not even a candidate in window)
        {
            "trade_id": "ENTRY_AT_END",
            "symbol": "DOGE",
            "side": "BUY",
            "entry_timestamp": "2024-01-03T00:00:00Z",
            "exit_timestamp": "2024-01-03T01:00:00Z",
            "gross_return_fraction": 0.02,
        },
        # Entry AFTER end -> outside [start, end) -> EXCLUDED
        {
            "trade_id": "ENTRY_AFTER_END",
            "symbol": "NEAR",
            "side": "BUY",
            "entry_timestamp": "2024-01-03T00:15:00Z",
            "exit_timestamp": "2024-01-03T01:00:00Z",
            "gross_return_fraction": 0.02,
        },
    ]

    candle_df = pd.DataFrame({
        "timestamp": pd.date_range("2023-12-31T23:45:00Z", "2024-01-03T00:30:00Z", freq="15min", tz="UTC"),
        "close": 100.5,
    })

    res = engine.run(candidates, date_range=(start, end), candle_data={"BTC": candle_df, "ETH": candle_df})
    exec_ids = [t.trade_id for t in res.executed_trades]

    assert exec_ids == ["AT_START", "BEFORE_END_INSIDE"]
    assert res.excluded_cross_boundary_count == 2
    assert res.cross_boundary_policy == "EXCLUDE_CROSS_BOUNDARY_OUTCOME"

    # MTM grid must strictly obey start <= ts < end (never containing 2024-01-03T00:00:00Z)
    assert res.mtm_equity_curve["timestamp"].min() == pd.Timestamp(start)
    assert res.mtm_equity_curve["timestamp"].max() == pd.Timestamp("2024-01-02T23:45:00Z")
    assert (res.mtm_equity_curve["timestamp"] < pd.Timestamp(end)).all()

    # Daily calendar must strictly contain [2024-01-01, 2024-01-02] and NEVER 2024-01-03
    expected_days = list(pd.date_range("2024-01-01", "2024-01-02", freq="1D", tz="UTC"))
    assert list(res.daily_returns.index) == expected_days
    compounded_eq = cfg.initial_capital * float((1.0 + res.daily_returns).prod())
    assert compounded_eq == pytest.approx(res.final_equity, rel=1e-9)


def test_cross_boundary_truncate_at_end_policy():
    """Optional TRUNCATE_AT_END marks open cross-boundary positions to the last bar strictly < end."""
    cfg = AccountingConfig(initial_capital=10000.0, cooldown_bars=0, allocation_pct_per_trade=0.20)
    engine = EventDrivenAccountingEngine(cfg)

    start = "2024-01-01T00:00:00Z"
    end = "2024-01-01T01:00:00Z"
    candidates = [
        {
            "trade_id": "CROSS_TRUNC",
            "symbol": "BTC",
            "side": "BUY",
            "entry_timestamp": "2024-01-01T00:30:00Z",
            "exit_timestamp": "2024-01-01T02:00:00Z",  # Future outcome +10% after end
            "entry_price": 100.0,
            "exit_price": 110.0,
            "gross_return_fraction": 0.10,
        }
    ]
    # Mark price at 00:45Z (< end) is 101.0 (+1%), while at 01:00Z (== end) it jumps to 110.0
    candle_df = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2024-01-01T00:30:00Z"),
            pd.Timestamp("2024-01-01T00:45:00Z"),
            pd.Timestamp("2024-01-01T01:00:00Z"),
        ],
        "close": [100.0, 101.0, 110.0],
    })

    res = engine.run(
        candidates,
        date_range=(start, end),
        candle_data={"BTC": candle_df},
        cross_boundary_policy="TRUNCATE_AT_END",
    )
    assert res.executed_trades_count == 1
    tr = res.executed_trades[0]
    assert tr.exit_timestamp == pd.Timestamp("2024-01-01T00:45:00Z")
    assert tr.exit_price == pytest.approx(101.0)
    assert tr.gross_return_fraction == pytest.approx(0.01)
    assert tr.exit_reason == "BOUNDARY_TRUNCATED"


def test_supplied_net_pnl_bps_never_overrides_accounting_engine():
    """Supplied net_pnl_bps is optional informational metadata and cannot override realized accounting."""
    # 1. Validator neither derives net_pnl_bps when omitted nor trusts it without explicit cost contract
    omitted = validate_economic_replay_trade({
        "trade_id": "T_OMIT",
        "symbol": "BTC",
        "side": "BUY",
        "entry_timestamp": "2026-10-31T10:00:00Z",
        "exit_timestamp": "2026-10-31T11:00:00Z",
        "gross_return_fraction": 0.0050,
    })
    assert omitted.net_pnl_bps is None

    extreme_pos = dict(
        trade_id="T_SAME",
        symbol="BTC",
        side="BUY",
        entry_timestamp="2026-10-31T10:00:00Z",
        exit_timestamp="2026-10-31T11:00:00Z",
        entry_price=1000.0,
        exit_price=1005.0,
        gross_return_fraction=0.0050,
        net_pnl_bps=99999.0,  # Bogus informational transport value
    )
    extreme_neg = dict(extreme_pos, net_pnl_bps=-99999.0)
    clean_none = {k: v for k, v in extreme_pos.items() if k != "net_pnl_bps"}

    cfg = AccountingConfig(initial_capital=10000.0, fee_rate_bps=5.0, slippage_bps=2.0)
    engine = EventDrivenAccountingEngine(cfg)

    res_none = engine.run([clean_none])
    res_pos = engine.run([extreme_pos])
    res_neg = engine.run([extreme_neg])

    assert res_pos.final_equity == pytest.approx(res_none.final_equity, rel=1e-12)
    assert res_neg.final_equity == pytest.approx(res_none.final_equity, rel=1e-12)
    assert res_pos.executed_trades[0].net_return_bps == pytest.approx(
        res_none.executed_trades[0].net_return_bps, rel=1e-12
    )
    assert res_neg.executed_trades[0].net_return_bps == pytest.approx(
        res_none.executed_trades[0].net_return_bps, rel=1e-12
    )

    # 2. When explicit cost-contract metadata IS provided, validator enforces consistency
    with pytest.raises(ValueError, match="explicit cost-contract net_pnl_bps mismatch"):
        validate_economic_replay_trade({
            **extreme_pos,
            "cost_contract_version": "canonical-v1",
            "fee_rate_bps": 5.0,
            "slippage_bps": 2.0,
            "roundtrip_cost_semantics": "additive_bps",
        })


def test_leak_free_fold_mask_excludes_cross_boundary_outcomes():
    """Training fold mask must require BOTH entry_timestamp < end AND exit_timestamp < end."""
    from scripts.evaluate_candidates_and_promotion_gates_v2 import build_leak_free_fold_mask

    df = pd.DataFrame({
        "trade_id": ["BEFORE", "AT_START", "INSIDE_END_M15", "CROSS_AT_END", "CROSS_AFTER_END", "ENTRY_AT_END"],
        "entry_timestamp": pd.to_datetime([
            "2022-12-31T23:45:00Z",
            "2023-01-01T00:00:00Z",
            "2023-12-31T23:30:00Z",
            "2023-12-31T23:45:00Z",
            "2023-12-31T23:45:00Z",
            "2024-01-01T00:00:00Z",
        ], utc=True),
        "exit_timestamp": pd.to_datetime([
            "2023-01-01T00:15:00Z",
            "2023-01-01T01:00:00Z",
            "2023-12-31T23:45:00Z",
            "2024-01-01T00:00:00Z",
            "2024-01-01T02:00:00Z",
            "2024-01-01T01:00:00Z",
        ], utc=True),
    })
    mask = build_leak_free_fold_mask(df, "2023-01-01", "2024-01-01")
    assert df.loc[mask, "trade_id"].tolist() == ["AT_START", "INSIDE_END_M15"]


def test_promotion_gates_reject_small_sample_single_symbol_single_trade_and_zero_fold():
    """Promotion gates enforce N>=30, daily block CI, multi-symbol/multi-trade dispersion, 20bps resilience, and non-zero folds."""
    import numpy as np
    from scripts.evaluate_candidates_and_promotion_gates_v2 import evaluate_gates

    # 1. Tiny sample (N=1 winning trade) -> MUST FAIL
    tiny_res = {"executed_trades_count": 1, "expectancy_bps": 36.0, "profit_factor": 999.0, "max_drawdown_pct": 0.0}
    tiny_trades = [{"symbol": "BTC", "gross_return_fraction": 0.0050, "net_return_bps": 36.0, "net_pnl_usd": 9.0}]
    g_tiny = evaluate_gates(tiny_res, executed_trades=tiny_trades)
    assert g_tiny["gate_4_sample_size"]["passed"] is False
    assert g_tiny["all_gates_passed"] is False

    # 2. Adequate N=40, balanced across 3 symbols, resilient at 20 bps, AND positive daily portfolio block CI ->
    #    PASSES historical exploratory gates, while prospective_shadow_mandatory_before_active_paper remains True!
    balanced_trades = [
        {
            "symbol": ["BTC", "ETH", "BNB"][i % 3],
            "gross_return_fraction": 0.0045 if i % 2 == 0 else -0.0010,
            "net_return_bps": 31.0 if i % 2 == 0 else -24.0,
            "net_pnl_usd": 7.75 if i % 2 == 0 else -6.0,
        }
        for i in range(40)
    ]
    rng = np.random.default_rng(123)
    positive_daily_returns = 0.0012 + rng.normal(0.0, 0.0005, size=120)
    good_res = {"executed_trades_count": 40, "expectancy_bps": 3.5, "profit_factor": 1.29, "max_drawdown_pct": 4.2}
    g_good = evaluate_gates(
        good_res,
        executed_trades=balanced_trades,
        daily_returns=positive_daily_returns,
        fold_counts=[20, 20],
    )
    assert g_good["gate_7_primary_daily_portfolio_block_ci"]["passed"] is True
    assert g_good["gate_7_primary_daily_portfolio_block_ci"]["iid_trade_ci_allowed_for_promotion"] is False
    assert g_good["all_gates_passed"] is True
    assert g_good["multiple_testing_trials_count"] == "UNKNOWN"
    assert g_good["historical_ci_epistemic_status"] == "EXPLORATORY_PRE_PROSPECTIVE_LOCK"
    assert g_good["prospective_shadow_mandatory_before_active_paper"] is True

    # 3. Missing daily portfolio returns MUST fail-closed on gate_7 even when IID trade CI is positive
    g_missing_daily = evaluate_gates(good_res, executed_trades=balanced_trades, fold_counts=[20, 20])
    assert g_missing_daily["gate_7_primary_daily_portfolio_block_ci"]["passed"] is False
    assert g_missing_daily["all_gates_passed"] is False

    # 4. Zero coverage in Fold 2 -> MUST FAIL gate_9
    g_zero_fold = evaluate_gates(
        good_res,
        executed_trades=balanced_trades,
        daily_returns=positive_daily_returns,
        fold_counts=[40, 0],
    )
    assert g_zero_fold["gate_9_no_zero_coverage_fold"]["passed"] is False
    assert g_zero_fold["all_gates_passed"] is False

    # 5. Single-symbol concentration (100% BTC) -> MUST FAIL gate_8
    one_sym_trades = [{**t, "symbol": "BTC"} for t in balanced_trades]
    g_one_sym = evaluate_gates(
        good_res,
        executed_trades=one_sym_trades,
        daily_returns=positive_daily_returns,
        fold_counts=[20, 20],
    )
    assert g_one_sym["gate_8_diversification"]["passed"] is False
    assert g_one_sym["all_gates_passed"] is False

    # 6. Single-trade profit dominance (>50% of positive PnL from 1 trade) -> MUST FAIL gate_8
    one_trade_dom = [
        {"symbol": ["BTC", "ETH", "BNB"][i % 3], "gross_return_fraction": 0.0015, "net_return_bps": 1.0, "net_pnl_usd": 0.25}
        for i in range(39)
    ] + [{"symbol": "BTC", "gross_return_fraction": 0.10, "net_return_bps": 986.0, "net_pnl_usd": 250.0}]
    g_one_trade = evaluate_gates(
        good_res,
        executed_trades=one_trade_dom,
        daily_returns=positive_daily_returns,
        fold_counts=[20, 20],
    )
    assert g_one_trade["gate_8_diversification"]["passed"] is False
    assert g_one_trade["all_gates_passed"] is False


def test_vcb_next_bar_open_execution_contract_no_same_close_fill():
    """P0 #1: Signal at bar i close enters strictly at bar i+1 open; never enters at signal close."""
    import numpy as np
    from scripts.evaluate_candidates_and_promotion_gates_v2 import (
        extract_vcb_causal_signals_for_symbol,
        simulate_next_bar_open_barrier_trade,
    )

    n = 440
    ts = pd.date_range("2024-01-01T00:00:00Z", periods=n, freq="15min", tz="UTC")
    # Construct deterministic gentle uptrend with distinct open vs close on every bar
    closes = np.linspace(1000.0, 1020.0, n)
    opens = closes - 0.75  # opens are systematically distinct from closes
    highs = closes + 1.50
    lows = opens - 1.00
    vols = np.full(n, 100.0)

    # Trigger an unmistakable breakout at signal bar i = 400
    sig_idx = 400
    closes[sig_idx] = 1045.0   # signal close = 1045.0
    highs[sig_idx] = 1046.0
    lows[sig_idx] = 1017.0
    vols[sig_idx] = 350.0      # > 1.2x vol_ma

    # Next bar i + 1 = 401 opens with an upward gap at 1051.25 (strictly != closes[sig_idx])
    opens[sig_idx + 1] = 1051.25
    highs[sig_idx + 1] = 1055.0
    lows[sig_idx + 1] = 1049.0
    closes[sig_idx + 1] = 1053.0

    c_df = pd.DataFrame({
        "timestamp": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })

    signals = extract_vcb_causal_signals_for_symbol("BTC", c_df)
    matching = [s for s in signals if s["signal_index"] == sig_idx]
    assert len(matching) == 1
    sig = matching[0]
    assert sig["side"] == "BUY"
    assert sig["signal_timestamp"] == ts[sig_idx]

    sim = simulate_next_bar_open_barrier_trade(
        sig["side"],
        sig["signal_index"],
        opens,
        highs,
        lows,
        closes,
        ts.tolist(),
        max_hold=16,
        tp_bps=350.0,
        sl_bps=150.0,
    )

    # Strict next-bar-open contract checks
    assert sim["signal_index"] == sig_idx
    assert sim["entry_index"] == sig_idx + 1
    assert sim["signal_timestamp"] == ts[sig_idx]
    assert sim["signal_close_timestamp"] == ts[sig_idx] + pd.Timedelta(minutes=15)
    assert sim["entry_timestamp"] == ts[sig_idx + 1]
    assert sim["entry_timestamp"] == sim["signal_close_timestamp"]
    assert sim["entry_price"] == pytest.approx(opens[sig_idx + 1], rel=1e-12)
    assert sim["entry_price"] != pytest.approx(closes[sig_idx], rel=1e-6)


def test_vcb_signal_extraction_strictly_causal_no_future_lookahead():
    """P0 #1: Mutating bars strictly after bar i (including open/high/low/close/vol of i+1) NEVER changes signal at bar i."""
    import numpy as np
    from scripts.evaluate_candidates_and_promotion_gates_v2 import extract_vcb_causal_signals_for_symbol

    n = 430
    rng = np.random.default_rng(7)
    ts = pd.date_range("2024-03-01T00:00:00Z", periods=n, freq="15min", tz="UTC")
    base_close = 2000.0 + np.cumsum(rng.normal(0.2, 2.5, size=n))
    base_open = np.r_[base_close[0], base_close[:-1]]
    base_high = np.maximum(base_open, base_close) + rng.uniform(0.5, 4.0, size=n)
    base_low = np.minimum(base_open, base_close) - rng.uniform(0.5, 4.0, size=n)
    base_vol = rng.uniform(80.0, 120.0, size=n)

    # Guarantee a causal breakout at bar 405
    cutoff_i = 405
    base_close[cutoff_i] = float(np.max(base_high[cutoff_i - 96 : cutoff_i]) + 25.0)
    base_high[cutoff_i] = base_close[cutoff_i] + 3.0
    base_vol[cutoff_i] = 400.0

    df_a = pd.DataFrame({
        "timestamp": ts,
        "open": base_open.copy(),
        "high": base_high.copy(),
        "low": base_low.copy(),
        "close": base_close.copy(),
        "volume": base_vol.copy(),
    })

    # Mutate ALL bars >= cutoff_i + 1 with extreme opposing crash values
    df_b = df_a.copy()
    df_b.loc[cutoff_i + 1 :, "open"] = 50.0
    df_b.loc[cutoff_i + 1 :, "high"] = 55.0
    df_b.loc[cutoff_i + 1 :, "low"] = 10.0
    df_b.loc[cutoff_i + 1 :, "close"] = 12.0
    df_b.loc[cutoff_i + 1 :, "volume"] = 999999.0

    sigs_a = [s for s in extract_vcb_causal_signals_for_symbol("ETH", df_a) if s["signal_index"] <= cutoff_i]
    sigs_b = [s for s in extract_vcb_causal_signals_for_symbol("ETH", df_b) if s["signal_index"] <= cutoff_i]

    assert len(sigs_a) >= 1
    assert sigs_a == sigs_b


def test_next_bar_open_tp_sl_collision_gap_and_max_hold_determinism():
    """P0 #1: Verifies entry-bar TP/SL, conservative SL-first collision, adverse SL_GAP open fill, and entry-anchored max_hold."""
    import numpy as np
    from scripts.evaluate_candidates_and_promotion_gates_v2 import simulate_next_bar_open_barrier_trade

    ts = pd.date_range("2024-06-01T00:00:00Z", periods=10, freq="15min", tz="UTC").tolist()

    # 1. Entry-bar TP (BUY enters at bar 1 open = 100.0, TP=+200 bps -> 102.0, SL=-100 bps -> 99.0)
    opens = np.array([98.0, 100.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0])
    highs = np.array([99.5, 102.5, 101.5, 101.5, 101.5, 101.5, 101.5, 101.5, 101.5, 101.5])
    lows = np.array([97.5, 99.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 100.5])
    closes = np.array([99.0, 102.2, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0])
    res_tp = simulate_next_bar_open_barrier_trade(
        "BUY", 0, opens, highs, lows, closes, ts, max_hold=4, tp_bps=200.0, sl_bps=100.0
    )
    assert res_tp["entry_index"] == 1
    assert res_tp["exit_index"] == 1
    assert res_tp["exit_reason"] == "TP"
    assert res_tp["bars_held"] == 1
    assert res_tp["exit_price"] == pytest.approx(102.0)
    assert res_tp["gross_pnl_bps"] == pytest.approx(200.0)

    # 2. Same-candle TP + SL collision on entry bar -> conservative SL-first MUST win
    highs_col = highs.copy()
    lows_col = lows.copy()
    highs_col[1] = 103.0  # hits TP (102.0)
    lows_col[1] = 98.5    # ALSO hits SL (99.0)
    res_col = simulate_next_bar_open_barrier_trade(
        "BUY", 0, opens, highs_col, lows_col, closes, ts, max_hold=4, tp_bps=200.0, sl_bps=100.0
    )
    assert res_col["exit_index"] == 1
    assert res_col["exit_reason"] == "SL"
    assert res_col["same_bar_collision"] is True
    assert res_col["exit_price"] == pytest.approx(99.0)
    assert res_col["gross_pnl_bps"] == pytest.approx(-100.0)

    # 3. Gap through stop on subsequent bar (bar 2 opens at 97.0 < sl_target=99.0) -> adverse open fill SL_GAP (97.0, NOT 99.0!)
    opens_gap = np.array([98.0, 100.0, 97.0, 97.0, 97.0, 97.0, 97.0, 97.0, 97.0, 97.0])
    highs_gap = np.array([99.5, 100.8, 98.0, 98.0, 98.0, 98.0, 98.0, 98.0, 98.0, 98.0])
    lows_gap = np.array([97.5, 99.4, 96.5, 96.5, 96.5, 96.5, 96.5, 96.5, 96.5, 96.5])
    closes_gap = np.array([99.0, 99.6, 97.2, 97.2, 97.2, 97.2, 97.2, 97.2, 97.2, 97.2])
    res_gap = simulate_next_bar_open_barrier_trade(
        "BUY", 0, opens_gap, highs_gap, lows_gap, closes_gap, ts, max_hold=4, tp_bps=200.0, sl_bps=100.0
    )
    assert res_gap["exit_index"] == 2
    assert res_gap["exit_reason"] == "SL_GAP"
    assert res_gap["gap_through_stop"] is True
    assert res_gap["exit_price"] == pytest.approx(97.0)  # adverse open fill, worse than -100 bps stop
    assert res_gap["gross_pnl_bps"] == pytest.approx(-300.0)

    # 4. max_hold anchored at entry_index (entry_idx=1, max_hold=4 -> inspects bars 1,2,3,4; exits at close of bar 4, NOT bar 3!)
    opens_to = np.full(10, 100.0)
    highs_to = np.full(10, 100.5)
    lows_to = np.full(10, 99.5)
    closes_to = np.array([99.8, 100.1, 100.2, 100.3, 101.25, 105.0, 105.0, 105.0, 105.0, 105.0])
    res_to = simulate_next_bar_open_barrier_trade(
        "BUY", 0, opens_to, highs_to, lows_to, closes_to, ts, max_hold=4, tp_bps=200.0, sl_bps=100.0
    )
    assert res_to["entry_index"] == 1
    assert res_to["exit_index"] == 4
    assert res_to["bars_held"] == 4
    assert res_to["exit_reason"] == "TIMEOUT"
    assert res_to["exit_price"] == pytest.approx(101.25)
    assert res_to["exit_timestamp"] == ts[4] + pd.Timedelta(minutes=15)


def test_primary_gate_requires_daily_portfolio_block_ci_and_clusters_contemporaneous_symbols():
    """P0 #3: Candidate with positive IID trade CI MUST fail promotion when clustered daily portfolio block CI <= 0."""
    import numpy as np
    from scripts.evaluate_candidates_and_promotion_gates_v2 import (
        bootstrap_trade_returns_ci,
        evaluate_gates,
        time_cluster_trade_bootstrap_ci,
    )

    # Textbook cross-symbol + serial clustering case across K=10 weeks (N=60 trades):
    # - 8 bull weeks: BTC, ETH, BNB each fire 2 overlapping trades winning +40 bps (48 trades * +40 = +1920 bps)
    # - 2 crash weeks: BTC, ETH, BNB each fire 2 overlapping trades losing -80 bps (12 trades * -80 = -960 bps)
    # Mean net trade return = +16.0 bps:
    # - Naive IID assumes N=60 independent trades -> SE = 48/sqrt(60) = 6.2 bps -> 95% CI lower ~ +4.0 bps > 0!
    # - True time-clustered / daily block bootstrap sees only K=10 independent weeks -> SE = 48/sqrt(10) = 15.2 bps
    #   -> 95% CI lower ~ -16.0 bps < 0, so Primary Gate 7 MUST reject promotion!
    base = pd.Timestamp("2025-01-01T00:00:00Z")
    trades = []
    daily_rets = np.zeros(100, dtype=float)

    for wk in range(8):
        day_idx = wk * 7
        for rep in range(2):
            for j, sym in enumerate(["BTC", "ETH", "BNB"]):
                trades.append({
                    "symbol": sym,
                    "entry_timestamp": base + pd.Timedelta(days=day_idx + rep, hours=j),
                    "gross_return_fraction": 0.0054,
                    "net_return_bps": 40.0,
                    "net_pnl_usd": 10.0,
                })
        daily_rets[day_idx : day_idx + 2] = 0.0012  # +24 bps/week portfolio gain

    for wk in [8, 9]:
        day_idx = wk * 7
        for rep in range(2):
            for j, sym in enumerate(["BTC", "ETH", "BNB"]):
                trades.append({
                    "symbol": sym,
                    "entry_timestamp": base + pd.Timedelta(days=day_idx + rep, hours=j),
                    "gross_return_fraction": -0.0066,
                    "net_return_bps": -80.0,
                    "net_pnl_usd": -20.0,
                })
        daily_rets[day_idx : day_idx + 2] = -0.0024  # -48 bps/week synchronized crash

    iid_ci = bootstrap_trade_returns_ci(np.array([t["net_return_bps"] for t in trades]))
    cluster_ci = time_cluster_trade_bootstrap_ci(trades, cluster_days=7)
    assert iid_ci["used_for_promotion_gate"] is False
    assert iid_ci["ci_lower"] > 0.0  # Naive IID falsely claims statistically significant edge!
    assert cluster_ci["n_clusters"] == 10  # All 60 cross-symbol trades collapsed into 10 weekly clusters
    assert cluster_ci["ci_lower"] <= 0.0

    summary_res = {
        "executed_trades_count": len(trades),
        "expectancy_bps": float(np.mean([t["net_return_bps"] for t in trades])),
        "profit_factor": 2.0,
        "max_drawdown_pct": 5.5,
    }
    gates = evaluate_gates(
        summary_res,
        executed_trades=trades,
        daily_returns=daily_rets,
        fold_counts=[30, 30],
    )
    assert gates["gate_1_positive_net_expectancy"]["passed"] is True
    assert gates["gate_7_primary_daily_portfolio_block_ci"]["diagnostic_iid_trade_ci_lower_bps"] > 0.0
    assert gates["gate_7_primary_daily_portfolio_block_ci"]["primary_daily_block_ci_lower_bps"] <= 0.0
    assert gates["gate_7_primary_daily_portfolio_block_ci"]["passed"] is False
    assert gates["all_gates_passed"] is False


def test_attribution_slice_schema_and_small_sample_guard():
    """Attribution cells emit 10/14/20/30 bps net EV, 95% CI, MDD, turnover, coverage, and small-N flag."""
    from scripts.diagnose_negative_edge import analyze_slice

    base_ts = pd.Timestamp("2024-01-01T00:00:00Z")
    small_rows = [
        {
            "symbol": "BTC",
            "entry_timestamp": base_ts + pd.Timedelta(days=2 * i),
            "exit_timestamp": base_ts + pd.Timedelta(days=2 * i, hours=2),
            "gross_return_fraction": 0.0030,
            "exit_reason": "TP",
        }
        for i in range(10)
    ]
    c_small = analyze_slice(small_rows, cost_bps=14.0, population_total_n=100)
    assert c_small["count"] == 10
    assert c_small["coverage_pct"] == 10.0
    assert c_small["sample_adequacy"] == "SMALL_SAMPLE_NOT_EDGE_EVIDENCE"
    assert set(c_small["net_expectancy_by_cost_bps"].keys()) == {"10bps", "14bps", "20bps", "30bps"}
    assert c_small["net_expectancy_by_cost_bps"]["10bps"] == pytest.approx(20.0)
    assert c_small["net_expectancy_by_cost_bps"]["14bps"] == pytest.approx(16.0)
    assert c_small["net_expectancy_by_cost_bps"]["20bps"] == pytest.approx(10.0)
    assert c_small["net_expectancy_by_cost_bps"]["30bps"] == pytest.approx(0.0)
    assert "ci_lower" in c_small["bootstrap_ci_95_net14_bps"]
    assert c_small["turnover"] > 0.0




