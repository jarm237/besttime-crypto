"""Causal BTC/Cash Portfolio Accounting Module.

Provides exact, closed-form, zero-drift portfolio rebalancing accounting
with non-negative cash, non-negative asset holdings, exact fee reconciliation,
and verified post-trade target weight parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class CausalPortfolioState:
    cash: float
    btc_units: float
    equity: float
    btc_weight: float
    cash_weight: float


def execute_causal_btc_rebalance(
    cash_pre: float,
    btc_units_pre: float,
    exec_price: float,
    target_btc_weight: float,
    fee_bps: float = 12.0,
    slippage_bps: float = 0.0,
) -> Tuple[float, float, float, float]:
    """Execute a causal rebalance to target BTC weight with closed-form fee deduction.

    Guarantees:
    1. Cash is NEVER negative: cash_post >= 0.0
    2. BTC units are NEVER negative: btc_units_post >= 0.0
    3. Equity reconciles exactly: equity_post = equity_pre - fee_paid
    4. Post-trade weight matches target_btc_weight (unless total equity <= 0)
    5. No unbacked leverage or hidden short positions

    Returns:
        (cash_post, btc_units_post, fee_paid, traded_notional)
    """
    assert cash_pre >= -1e-9, f"Input cash cannot be negative: {cash_pre}"
    assert btc_units_pre >= -1e-9, f"Input BTC units cannot be negative: {btc_units_pre}"
    assert exec_price > 0.0, f"Execution price must be positive: {exec_price}"
    assert 0.0 <= target_btc_weight <= 1.0, f"Target BTC weight must be in [0, 1]: {target_btc_weight}"

    cash_pre = max(0.0, float(cash_pre))
    btc_units_pre = max(0.0, float(btc_units_pre))

    btc_val_pre = btc_units_pre * exec_price
    equity_pre = cash_pre + btc_val_pre

    if equity_pre <= 1e-12:
        return 0.0, 0.0, 0.0, 0.0

    phi = (fee_bps + slippage_bps) / 10000.0
    w_star = float(target_btc_weight)
    current_w = btc_val_pre / equity_pre

    # Check if rebalance is needed
    if abs(w_star - current_w) < 1e-9:
        return cash_pre, btc_units_pre, 0.0, 0.0

    if w_star > current_w:
        # BUY BTC:
        # Solving: (V_pre + N) / (E_pre - N * phi) = w_star
        # => N = (w_star * E_pre - V_pre) / (1 + w_star * phi)
        numerator = w_star * equity_pre - btc_val_pre
        denominator = 1.0 + w_star * phi
        trade_notional = max(0.0, numerator / denominator)

        # Bound notional by spendable cash: N * (1 + phi) <= cash_pre
        max_spendable_notional = cash_pre / (1.0 + phi) if (1.0 + phi) > 0 else 0.0
        trade_notional = min(trade_notional, max_spendable_notional)

        fee_paid = trade_notional * phi
        total_cash_spent = trade_notional + fee_paid

        cash_post = max(0.0, cash_pre - total_cash_spent)
        btc_units_post = btc_units_pre + (trade_notional / exec_price)
    else:
        # SELL BTC:
        # Solving: (V_pre - N) / (E_pre - N * phi) = w_star
        # => N = (V_pre - w_star * E_pre) / (1 - w_star * phi)
        numerator = btc_val_pre - w_star * equity_pre
        denominator = 1.0 - w_star * phi
        trade_notional = max(0.0, numerator / denominator) if denominator > 0 else 0.0

        # Bound notional by existing BTC holdings: N <= btc_val_pre
        trade_notional = min(trade_notional, btc_val_pre)

        fee_paid = trade_notional * phi
        net_cash_proceeds = trade_notional - fee_paid

        cash_post = cash_pre + net_cash_proceeds
        btc_units_post = max(0.0, btc_units_pre - (trade_notional / exec_price))

    return cash_post, btc_units_post, fee_paid, trade_notional


def simulate_causal_btc_portfolio(
    timestamps: pd.DatetimeIndex,
    open_prices: np.ndarray,
    close_prices: np.ndarray,
    target_weights: np.ndarray,
    policy_name: str,
    initial_capital_usd: float = 10000.0,
    fee_bps: float = 12.0,
    slippage_bps: float = 0.0,
    rebalance_mask: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Simulate a causal portfolio with daily/hourly MTM and next-open order execution."""
    n_steps = len(timestamps)
    assert len(open_prices) == n_steps
    assert len(close_prices) == n_steps
    assert len(target_weights) == n_steps

    if rebalance_mask is None:
        rebalance_mask = np.ones(n_steps, dtype=bool)

    cash = float(initial_capital_usd)
    btc_units = 0.0

    hourly_equities = []
    daily_turnover = []
    daily_fees = []
    realized_weights = []

    pending_weight: Optional[float] = None
    total_fees_paid = 0.0
    total_traded_notional = 0.0
    actual_trades_executed = 0

    min_observed_cash = float(initial_capital_usd)
    min_observed_btc_units = 0.0
    max_observed_risky_exposure = 0.0
    max_accounting_residual = 0.0

    for t in range(n_steps):
        # 1. Execute pending order from t-1 at Open of t
        step_fee = 0.0
        step_notional = 0.0
        if pending_weight is not None:
            exec_px = open_prices[t]
            pre_eq = cash + btc_units * exec_px
            c_post, b_post, fee, notional = execute_causal_btc_rebalance(
                cash_pre=cash,
                btc_units_pre=btc_units,
                exec_price=exec_px,
                target_btc_weight=pending_weight,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            # Reconcile accounting conservation: E_post == E_pre - fee
            post_eq = c_post + b_post * exec_px
            residual = abs(post_eq - (pre_eq - fee))
            max_accounting_residual = max(max_accounting_residual, residual)

            cash = c_post
            btc_units = b_post
            step_fee = fee
            step_notional = notional
            total_fees_paid += fee
            total_traded_notional += notional
            if notional > 1e-4:
                actual_trades_executed += 1
                turnover_fraction = notional / max(pre_eq, 1e-6)
                daily_turnover.append(turnover_fraction)
            else:
                daily_turnover.append(0.0)
            pending_weight = None
        else:
            daily_turnover.append(0.0)

        daily_fees.append(step_fee)

        # 2. Mark to Market at Close of t
        close_px = close_prices[t]
        equity_t = cash + btc_units * close_px
        hourly_equities.append(equity_t)
        realized_w = (btc_units * close_px) / max(equity_t, 1e-6)
        realized_weights.append(realized_w)

        min_observed_cash = min(min_observed_cash, cash)
        min_observed_btc_units = min(min_observed_btc_units, btc_units)
        max_observed_risky_exposure = max(max_observed_risky_exposure, realized_w)

        # 3. Schedule next order at Close of t if t is a rebalance decision point
        if rebalance_mask[t]:
            pending_weight = float(target_weights[t])

    eq_series = pd.Series(hourly_equities, index=timestamps)
    daily_returns = eq_series.pct_change().dropna()

    # Subperiods
    tr_eq = eq_series.loc[:"2024-12-31 23:59:59"]
    va_eq = eq_series.loc["2025-01-01 00:00:00":"2025-12-31 23:59:59"]
    ho_eq = eq_series.loc["2026-01-01 00:00:00":]

    tr_ret = (tr_eq.iloc[-1] / tr_eq.iloc[0] - 1.0) * 100.0 if len(tr_eq) > 1 else 0.0
    va_ret = (va_eq.iloc[-1] / va_eq.iloc[0] - 1.0) * 100.0 if len(va_eq) > 1 else 0.0
    ho_ret = (ho_eq.iloc[-1] / ho_eq.iloc[0] - 1.0) * 100.0 if len(ho_eq) > 1 else 0.0
    full_ret = (eq_series.iloc[-1] / eq_series.iloc[0] - 1.0) * 100.0

    # Sharpe & Sortino
    mean_ret = daily_returns.mean()
    std_ret = daily_returns.std()
    downside_std = daily_returns[daily_returns < 0].std()

    # Annualization factor based on frequency
    # If daily sampling: sqrt(365.25), if hourly: sqrt(8760)
    freq_factor = np.sqrt(365.25) if len(daily_returns) < 5000 else np.sqrt(8760.0)
    sharpe = (mean_ret / std_ret * freq_factor) if std_ret > 1e-6 else 0.0
    sortino = (mean_ret / downside_std * freq_factor) if downside_std > 1e-6 else 0.0

    # Max Drawdown
    peaks = eq_series.cummax()
    dd = (eq_series - peaks) / peaks
    max_dd = float(dd.min()) * 100.0

    unbacked_leverage = bool(max_observed_risky_exposure > 1.000001 or min_observed_cash < -1e-6)

    return {
        "policy_name": policy_name,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "initial_capital_usd": round(initial_capital_usd, 2),
        "final_equity_usd": round(float(eq_series.iloc[-1]), 2),
        "full_horizon_net_return_pct": round(float(full_ret), 2),
        "train_net_return_pct": round(float(tr_ret), 2),
        "val_net_return_pct": round(float(va_ret), 2),
        "holdout_net_return_pct": round(float(ho_ret), 2),
        "annualized_sharpe": round(float(sharpe), 3),
        "annualized_sortino": round(float(sortino), 3),
        "max_drawdown_pct": round(float(max_dd), 2),
        "one_way_turnover": round(float(np.sum(daily_turnover)), 2),
        "total_traded_notional_usd": round(float(total_traded_notional), 2),
        "total_fees_paid_usd": round(float(total_fees_paid), 2),
        "actual_trades_executed": int(actual_trades_executed),
        "mean_realized_btc_exposure": round(float(np.mean(realized_weights)), 4),
        "min_observed_cash": round(float(min_observed_cash), 4),
        "min_observed_btc_units": round(float(min_observed_btc_units), 6),
        "max_observed_risky_exposure": round(float(max_observed_risky_exposure), 4),
        "max_accounting_residual": float(max_accounting_residual),
        "unbacked_leverage_detected": unbacked_leverage,
        "equity_series": eq_series,
    }
