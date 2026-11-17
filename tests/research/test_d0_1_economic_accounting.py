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


def test_weekly_rebalance_drift_and_trade_count():
    """Verify weekly policy rebalances only on weekly boundaries and drifts mid-week.

    Over 14 daily periods (starting on Sunday):
    - Exactly 2 scheduled decisions (Sunday day 0, Sunday day 7).
    - Exactly 2 actual trades executed (executing at Monday open days 1 and 8).
    - Days 2-7 and 9-13 experience price drift without trades or fees.
    """
    dates = pd.date_range("2023-01-01", periods=14, freq="1D", tz="UTC")  # 2023-01-01 is Sunday (dayofweek=6)
    assert dates[0].dayofweek == 6
    assert dates[7].dayofweek == 6

    # Prices drift up each day
    open_prices = np.array([100.0 + i * 2.0 for i in range(14)])
    close_prices = open_prices + 1.0

    # Target 50% BTC on Sundays, unchanged target vector
    targets = np.full(14, 0.50)
    rebalance_mask = (dates.dayofweek == 6)

    res = simulate_causal_btc_portfolio(
        timestamps=dates,
        open_prices=open_prices,
        close_prices=close_prices,
        target_weights=targets,
        policy_name="weekly_test",
        initial_capital_usd=10000.0,
        rebalance_mask=rebalance_mask,
    )

    # Max 2 actual trades over 14 days
    assert res["actual_trades_executed"] == 2
    assert res["min_observed_cash"] >= 0.0
    assert res["max_accounting_residual"] < 1e-6
    assert not res["unbacked_leverage_detected"]


def test_simulation_accounting_invariants_and_diagnostics():
    """Verify diagnostic fields are tracked and exact conservation holds across noisy rebalances."""
    dates = pd.date_range("2023-01-01", periods=30, freq="1D", tz="UTC")
    np.random.seed(42)
    open_prices = 100.0 + np.cumsum(np.random.randn(30) * 2.0)
    open_prices = np.maximum(open_prices, 10.0)
    close_prices = open_prices + np.random.randn(30)

    # Random targets between 0.0 and 1.0
    targets = np.random.uniform(0.0, 1.0, size=30)

    res = simulate_causal_btc_portfolio(
        timestamps=dates,
        open_prices=open_prices,
        close_prices=close_prices,
        target_weights=targets,
        policy_name="noise_test",
        initial_capital_usd=10000.0,
        fee_bps=12.0,
    )

    assert res["min_observed_cash"] >= 0.0
    assert res["min_observed_btc_units"] >= 0.0
    assert res["max_observed_risky_exposure"] <= 1.000001
    assert res["max_accounting_residual"] < 1e-4
    assert res["unbacked_leverage_detected"] is False
