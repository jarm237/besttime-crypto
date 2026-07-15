"""
tests/test_hard_risk_limits.py
PR 4 — Boundary tests for Stage 1 Hard Risk Limits.

Tests boundary conditions (just below, exact, just above) for all risk limits:
    - max_daily_loss_usdt (5.0)
    - max_rolling_24h_loss_usdt (7.0)
    - max_orders_per_day (3)
    - max_open_positions (1)
    - max_single_order_usdt (15.0)
    - max_position_usdt (20.0)
    - max_risk_per_trade_pct (0.25%)
"""
import pytest
import time
from btc_scraper.execution.hard_risk_limits import HardRiskLimits, RiskLimitSet, OrderIntent


@pytest.fixture(autouse=True)
def clean_risk_state(tmp_path, monkeypatch):
    # Redirect risk state path to temp dir to isolate from developer state
    state_file = tmp_path / "risk_state.json"
    monkeypatch.setattr("btc_scraper.execution.hard_risk_limits.STATE_PATH", state_file)


def test_max_single_order_notional():
    # Stage 1 max_single_order_usdt is 15.0
    limits = HardRiskLimits(stage=1)

    # 1. Just below (14.99) -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 14.99, open_positions_count=0)
    assert dec1.allowed

    # 2. Exact (15.0) -> Allowed
    dec2 = limits.evaluate(OrderIntent.ENTRY, 15.0, open_positions_count=0)
    assert dec2.allowed

    # 3. Just above (15.01) -> Blocked
    dec3 = limits.evaluate(OrderIntent.ENTRY, 15.01, open_positions_count=0)
    assert not dec3.allowed
    assert "order_too_large" in dec3.reason


def test_max_position_notional():
    # Stage 1 max_position_usdt is 20.0
    # Set max_single_order_usdt higher to test max_position_usdt without order_too_large.
    custom_limits = RiskLimitSet(
        max_position_usdt=20.0,
        max_single_order_usdt=50.0,
    )
    limits = HardRiskLimits(stage=1, limits=custom_limits)

    # 1. Just below (19.99) -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 19.99, open_positions_count=0)
    assert dec1.allowed

    # 2. Exact (20.0) -> Allowed
    dec2 = limits.evaluate(OrderIntent.ENTRY, 20.0, open_positions_count=0)
    assert dec2.allowed

    # 3. Just above (20.01) -> Blocked
    dec3 = limits.evaluate(OrderIntent.ENTRY, 20.01, open_positions_count=0)
    assert not dec3.allowed
    assert "position_too_large" in dec3.reason


def test_max_daily_loss():
    # Stage 1 max_daily_loss_usdt is 5.0
    limits = HardRiskLimits(stage=1)

    # 1. Just below limit (loss = 4.99) -> Allowed
    limits.update_unrealized(-4.99)
    dec1 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert dec1.allowed

    # 2. Exact/Above limit (loss = 5.0) -> Blocked
    limits.update_unrealized(-5.0)
    dec2 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert not dec2.allowed
    assert "calendar_daily_loss_breach" in dec2.reason


def test_max_rolling_24h_loss():
    # Stage 1 max_rolling_24h_loss_usdt is 7.0.
    # Set max_daily_loss_usdt higher to test max_rolling_24h_loss_usdt without daily loss breach.
    custom_limits = RiskLimitSet(
        max_rolling_24h_loss_usdt=7.0,
        max_daily_loss_usdt=50.0,
    )
    limits = HardRiskLimits(stage=1, limits=custom_limits)

    # Record 6.99 USDT realized loss in rolling window
    limits.record_fill(realized_pnl=-6.99, fee=0.0)
    # Just below (6.99 loss) -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert dec1.allowed

    # Record another 0.02 loss -> total rolling loss = 7.01 -> Blocked
    limits.record_fill(realized_pnl=-0.02, fee=0.0)
    dec2 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert not dec2.allowed
    assert "rolling_24h_loss_breach" in dec2.reason


def test_max_orders_per_day():
    # Stage 1 max_orders_per_day is 3
    limits = HardRiskLimits(stage=1)

    # Fill 2 orders
    limits.record_fill()
    limits.record_fill()
    # 1. 2 orders -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert dec1.allowed

    # Fill 3rd order -> 3 orders -> Blocked
    limits.record_fill()
    dec2 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert not dec2.allowed
    assert "daily_order_count_reached" in dec2.reason


def test_max_open_positions():
    # Stage 1 max_open_positions is 1
    limits = HardRiskLimits(stage=1)

    # 1. 0 open positions -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=0)
    assert dec1.allowed

    # 2. 1 open position -> Blocked
    dec2 = limits.evaluate(OrderIntent.ENTRY, 10.0, open_positions_count=1)
    assert not dec2.allowed
    assert "max_open_positions_reached" in dec2.reason


def test_max_risk_per_trade_pct():
    # Stage 1 max_risk_per_trade_pct is 0.25%
    # Portfolio equity = 10,000 -> 0.25% is 25 USDT.
    # Set max_single_order_usdt and max_position_usdt higher to test risk pct without order/position too large.
    custom_limits = RiskLimitSet(
        max_risk_per_trade_pct=0.25,
        max_single_order_usdt=50.0,
        max_position_usdt=50.0,
    )
    limits = HardRiskLimits(stage=1, limits=custom_limits)

    # 1. Just below risk limit (24.9 USDT size -> risk = 0.249%) -> Allowed
    dec1 = limits.evaluate(OrderIntent.ENTRY, 24.9, open_positions_count=0, portfolio_equity_usdt=10000.0)
    assert dec1.allowed

    # 2. Exact (25.0 USDT size -> risk = 0.25%) -> Allowed
    dec2 = limits.evaluate(OrderIntent.ENTRY, 25.0, open_positions_count=0, portfolio_equity_usdt=10000.0)
    assert dec2.allowed

    # 3. Just above (25.1 USDT size -> risk = 0.251%) -> Blocked
    dec3 = limits.evaluate(OrderIntent.ENTRY, 25.1, open_positions_count=0, portfolio_equity_usdt=10000.0)
    assert not dec3.allowed
    assert "risk_per_trade_exceeded" in dec3.reason
