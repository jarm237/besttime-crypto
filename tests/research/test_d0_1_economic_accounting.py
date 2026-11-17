"""Golden numerical tests for Causal BTC/Cash Portfolio Accounting."""

import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.causal_btc_accounting import (
    execute_causal_btc_rebalance,
    simulate_causal_btc_portfolio,
)


def test_golden_10k_btc_doubles_100pct_target():
    """Verify $10,000 initial cash buying 100% BTC at $100 then doubling to $200.
    
    Guarantees:
    - Cash is exactly 0.0 (never negative)
    - Fee is deducted upfront from purchasing power
    - Equity post-trade reconciles exactly: $10,000 - fee
    - When price doubles, equity doubles from post-trade base
    """
    initial_cash = 10000.0
    price_buy = 100.0
    fee_bps = 12.0
    phi = 12.0 / 10000.0  # 0.0012
    
    cash_post, btc_units_post, fee_paid, notional = execute_causal_btc_rebalance(
        cash_pre=initial_cash,
        btc_units_pre=0.0,
        exec_price=price_buy,
        target_btc_weight=1.0,
        fee_bps=fee_bps,
    )
    
    # 1. Non-negative cash
    assert cash_post >= 0.0
    assert abs(cash_post) < 1e-10  # Exactly 0 cash remaining
    
    # 2. Exact fee deduction
    expected_notional = initial_cash / (1.0 + phi)
    expected_fee = expected_notional * phi
    assert pytest.approx(notional, abs=1e-6) == expected_notional
    assert pytest.approx(fee_paid, abs=1e-6) == expected_fee
    
    # 3. Post-trade equity reconciliation
    equity_post = cash_post + btc_units_post * price_buy
    assert pytest.approx(equity_post, abs=1e-6) == initial_cash - fee_paid
    assert pytest.approx(btc_units_post, abs=1e-6) == expected_notional / price_buy
    
    # 4. BTC price doubles to $200
    price_double = 200.0
    equity_double = cash_post + btc_units_post * price_double
    expected_final = (expected_notional / price_buy) * price_double
    assert pytest.approx(equity_double, abs=1e-6) == expected_final
    assert equity_double > 19970.0 and equity_double < 19980.0  # ~ $19,976.03


def test_golden_50pct_target():
    """Verify rebalance to exactly 50% BTC / 50% Cash with exact fee reconciliation."""
    initial_cash = 10000.0
    price = 100.0
    fee_bps = 12.0
    phi = 0.0012
    
    cash_post, btc_units_post, fee_paid, notional = execute_causal_btc_rebalance(
        cash_pre=initial_cash,
        btc_units_pre=0.0,
        exec_price=price,
        target_btc_weight=0.5,
        fee_bps=fee_bps,
    )
    
    equity_post = cash_post + btc_units_post * price
    btc_val = btc_units_post * price
    
    # Equity reconciles
    assert pytest.approx(equity_post, abs=1e-6) == initial_cash - fee_paid
    # Exact 50% target weight achieved post-trade
    assert pytest.approx(btc_val / equity_post, abs=1e-6) == 0.50
    assert pytest.approx(cash_post / equity_post, abs=1e-6) == 0.50
    assert cash_post > 0.0
    assert btc_units_post > 0.0


def test_golden_100pct_btc_to_100pct_cash():
    """Verify liquidating 100% BTC to 100% Cash."""
    btc_units = 10.0
    price = 200.0
    fee_bps = 12.0
    phi = 0.0012
    initial_val = btc_units * price  # $2000
    
    cash_post, btc_units_post, fee_paid, notional = execute_causal_btc_rebalance(
        cash_pre=0.0,
        btc_units_pre=btc_units,
        exec_price=price,
        target_btc_weight=0.0,
        fee_bps=fee_bps,
    )
    
    assert btc_units_post == 0.0
    assert pytest.approx(notional, abs=1e-6) == initial_val
    expected_fee = initial_val * phi
    assert pytest.approx(fee_paid, abs=1e-6) == expected_fee
    assert pytest.approx(cash_post, abs=1e-6) == initial_val - expected_fee


def test_golden_partial_rebalances_both_directions():
    """Verify sequence of partial rebalances (buy from 50% to 75%, sell to 25%, sell to 0%)."""
    cash = 10000.0
    btc = 0.0
    price = 100.0
    fee_bps = 12.0
    
    targets = [0.50, 0.75, 0.25, 0.0]
    for target_w in targets:
        pre_eq = cash + btc * price
        cash_post, btc_post, fee, notional = execute_causal_btc_rebalance(
            cash_pre=cash,
            btc_units_pre=btc,
            exec_price=price,
            target_btc_weight=target_w,
            fee_bps=fee_bps,
        )
        post_eq = cash_post + btc_post * price
        # Invariants:
        assert cash_post >= 0.0
        assert btc_post >= 0.0
        assert pytest.approx(post_eq, abs=1e-6) == pre_eq - fee
        if post_eq > 1e-4:
            realized_w = (btc_post * price) / post_eq
            assert pytest.approx(realized_w, abs=1e-6) == target_w
        cash = cash_post
        btc = btc_post


def test_golden_zero_fee_reference():
    """Verify zero-fee execution has exact equity conservation."""
    cash_pre = 5000.0
    btc_pre = 50.0  # at $100 = $5000, total = $10,000
    price = 100.0
    
    cash_post, btc_post, fee, notional = execute_causal_btc_rebalance(
        cash_pre=cash_pre,
        btc_units_pre=btc_pre,
        exec_price=price,
        target_btc_weight=0.8,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    assert fee == 0.0
    assert pytest.approx(cash_post + btc_post * price, abs=1e-9) == 10000.0
    assert pytest.approx((btc_post * price) / 10000.0, abs=1e-9) == 0.80


def test_golden_stress_30bps():
    """Verify stress fee (25 bps fee + 5 bps slippage = 30 bps) maintains non-negativity."""
    cash_pre = 10000.0
    btc_pre = 0.0
    price = 50.0
    
    cash_post, btc_post, fee, notional = execute_causal_btc_rebalance(
        cash_pre=cash_pre,
        btc_units_pre=btc_pre,
        exec_price=price,
        target_btc_weight=1.0,
        fee_bps=25.0,
        slippage_bps=5.0,
    )
    assert cash_post >= 0.0
    assert abs(cash_post) < 1e-10
    phi = 0.0030
    assert pytest.approx(fee, abs=1e-6) == (10000.0 / 1.0030) * 0.0030
    assert pytest.approx(cash_post + btc_post * price, abs=1e-6) == 10000.0 - fee
