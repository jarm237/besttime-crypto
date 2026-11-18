"""Standardized Portfolio Accounting and Quantitative Metrics Engine.

Provides unified, mathematically consistent accounting across all research baselines,
heuristic policies, and neural models in besttime-crypto.

Guarantees:
  - Exact turnover decomposition: reports both gross_asset_turnover and one_way_turnover.
  - Zero fee leakage: transaction fees (12.0 bps default) are charged strictly on traded crypto volume.
  - Cash preservation: cash quote currency incurs zero holding or exchange fees.
  - Standardized Sharpe and Sortino: annualized via sqrt(8760), r_f = 0,
    downside deviation = sqrt(mean(min(0, r)^2)).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class StandardizedPortfolioMetrics:
    portfolio_name: str
    initial_capital_usd: float
    final_equity_usd: float
    net_return_pct: float
    max_drawdown_pct: float
    annualized_sharpe: float
    annualized_sortino: float
    one_way_turnover: float
    gross_asset_turnover: float
    total_traded_notional_usd: float
    total_fees_usd: float
    rebalance_count: int
    mean_cash_weight: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_standardized_metrics(
    portfolio_name: str,
    equity_series: pd.Series,
    initial_capital_usd: float,
    total_fees_usd: float,
    one_way_turnover: float,
    gross_asset_turnover: float,
    total_traded_notional_usd: float,
    rebalance_count: int,
    mean_cash_weight: float = 0.0,
    periods_per_year: float = 8760.0,
) -> Dict[str, Any]:
    """Calculate standardized quantitative portfolio metrics from an equity curve."""
    fin_eq = float(equity_series.iloc[-1])
    net_ret = ((fin_eq / initial_capital_usd) - 1.0) * 100.0

    peaks = np.maximum(initial_capital_usd, equity_series.cummax())
    dd_series = (equity_series - peaks) / np.maximum(peaks, 1e-6) * 100.0
    max_dd = float(dd_series.min())

    rets = equity_series.pct_change().dropna()
    if len(rets) > 24 and rets.std() > 1e-8:
        mean_r = float(rets.mean())
        std_r = float(rets.std())
        ann_sharpe = float((mean_r / std_r) * np.sqrt(periods_per_year))

        neg_rets = np.minimum(rets.to_numpy(), 0.0)
        downside_dev = float(np.sqrt(np.mean(neg_rets ** 2)))
        if downside_dev > 1e-8:
            ann_sortino = float((mean_r / downside_dev) * np.sqrt(periods_per_year))
        else:
            ann_sortino = ann_sharpe if mean_r >= 0 else -ann_sharpe
    else:
        ann_sharpe = 0.0
        ann_sortino = 0.0

    return {
        "portfolio_name": portfolio_name,
        "initial_capital_usd": round(initial_capital_usd, 2),
        "final_equity_usd": round(fin_eq, 2),
        "net_return_pct": round(net_ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "annualized_sharpe": round(ann_sharpe, 3),
        "annualized_sortino": round(ann_sortino, 3),
        "one_way_turnover": round(one_way_turnover, 2),
        "gross_asset_turnover": round(gross_asset_turnover, 2),
        "total_traded_notional_usd": round(total_traded_notional_usd, 2),
        "total_fees_usd": round(total_fees_usd, 2),
        "rebalance_count": int(rebalance_count),
        "mean_cash_weight": round(mean_cash_weight, 3),
    }


def execute_rebalance_step(
    current_holdings: np.ndarray,
    current_cash: float,
    open_prices: np.ndarray,
    target_weights: np.ndarray,
    target_cash_w: float,
    fee_bps: float = 12.0,
) -> Tuple[np.ndarray, float, float, float, float, float]:
    """Execute a single rebalance step with standard portfolio accounting.

    Args:
        current_holdings: Current units held of each asset [N].
        current_cash: Current cash in USD.
        open_prices: Current open execution prices for all assets [N].
        target_weights: Desired portfolio weights for assets [N] (sum <= 1.0).
        target_cash_w: Desired portfolio weight for cash (1.0 - sum(target_weights)).
        fee_bps: Transaction fee in basis points (12.0 bps = 0.0012).

    Returns:
        new_holdings: Updated asset units held [N].
        new_cash: Updated cash in USD.
        traded_notional: Traded asset volume in USD.
        fee_paid: Fee charged in USD.
        step_one_way_turnover: Normalized one-way portfolio turnover for this step.
        step_gross_asset_turnover: Two-sided gross asset turnover for this step.
    """
    fee_rate = fee_bps / 10000.0

    # Mark current holdings to open prices before rebalance
    asset_vals = current_holdings * open_prices
    equity_before = current_cash + float(np.sum(asset_vals))
    denom = max(equity_before, 1e-6)

    current_w = asset_vals / denom
    current_cash_w = current_cash / denom

    # Turnover accounting
    delta_w_assets = np.abs(target_weights - current_w)
    step_gross_asset_turnover = float(np.sum(delta_w_assets))

    delta_w_cash = abs(target_cash_w - current_cash_w)
    step_one_way_turnover = float(0.5 * (step_gross_asset_turnover + delta_w_cash))

    # Fee charged on traded crypto asset volume
    traded_notional = step_gross_asset_turnover * equity_before
    fee_paid = traded_notional * fee_rate

    # Capital allocation post fee
    post_fee_equity = equity_before - fee_paid
    new_holdings = (post_fee_equity * target_weights) / open_prices
    new_cash = post_fee_equity * target_cash_w

    return (
        new_holdings,
        new_cash,
        traded_notional,
        fee_paid,
        step_one_way_turnover,
        step_gross_asset_turnover,
    )


def execute_self_consistent_rebalance_step(
    current_holdings: np.ndarray,
    current_cash: float,
    open_prices: np.ndarray,
    target_weights: np.ndarray,
    target_cash_w: float,
    action_gate: int = 1,
    fee_bps: float = 12.0,
    min_notional: float = 0.0,
    max_iter: int = 10,
    tol: float = 1e-8,
) -> Tuple[np.ndarray, float, float, float, float, float, int]:
    """Execute a single rebalance step with exact self-consistent fixed-point transaction fee accounting.

    Guarantees:
      - Exact HOLD (action_gate == 0): exactly 0 orders, $0.00 traded notional, $0.00 fee paid, physical units frozen.
      - Self-consistent fee equation: TC = c * sum(|(V_pre - TC) * w_i - A_i|) solved to machine precision.
      - Strict Conservation: V_post = V_pre - fee_paid; sum(new_holdings * open_prices) + new_cash == V_post.
      - Non-negative capital: new_cash >= 0, new_holdings >= 0.
      - Minimum notional filtering: if min_notional > 0, trades below threshold are filtered out.

    Returns:
        new_holdings: Updated asset units held [N].
        new_cash: Updated cash in USD.
        actual_traded_notional: Actual traded asset volume in USD.
        fee_paid: Fee charged in USD (fee_rate * actual_traded_notional).
        step_one_way_turnover: Normalized one-way portfolio turnover for this step.
        step_gross_asset_turnover: Two-sided gross asset turnover for this step.
        executed_orders_count: Number of assets traded.
    """
    fee_rate = fee_bps / 10000.0
    asset_vals = current_holdings * open_prices
    equity_before = current_cash + float(np.sum(asset_vals))
    denom = max(equity_before, 1e-6)

    if action_gate == 0:
        # EXACT HOLD: Zero orders, zero traded notional, zero fees, physical units frozen
        return (
            current_holdings.copy(),
            float(current_cash),
            0.0,
            0.0,
            0.0,
            0.0,
            0,
        )

    # Fixed-point iteration for exact self-consistent fee
    # TC = c * sum(|(V_pre - TC) * w_i - A_i|)
    fee = fee_rate * float(np.sum(np.abs(equity_before * target_weights - asset_vals)))
    for _ in range(max_iter):
        V_post = equity_before - fee
        traded_notional = float(np.sum(np.abs(V_post * target_weights - asset_vals)))
        new_fee = fee_rate * traded_notional
        if abs(new_fee - fee) < tol:
            fee = new_fee
            break
        fee = new_fee

    V_post = max(0.0, equity_before - fee)
    intended_holdings = (V_post * target_weights) / open_prices

    if min_notional > 0.0:
        new_holdings = current_holdings.copy()
        traded_mask = np.zeros(len(open_prices), dtype=bool)
        for i in range(len(open_prices)):
            trade_notional_i = abs(intended_holdings[i] - current_holdings[i]) * open_prices[i]
            if trade_notional_i >= min_notional:
                new_holdings[i] = intended_holdings[i]
                traded_mask[i] = True

        executed_orders_count = int(np.sum(traded_mask))
        actual_traded_notional = float(np.sum(np.abs(new_holdings - current_holdings) * open_prices))
        fee_paid = actual_traded_notional * fee_rate
        new_cash = equity_before - fee_paid - float(np.sum(new_holdings * open_prices))
        new_cash = max(0.0, new_cash)
    else:
        new_holdings = intended_holdings
        traded_diffs = np.abs(new_holdings - current_holdings) * open_prices
        traded_mask = traded_diffs > 1e-6
        executed_orders_count = int(np.sum(traded_mask))
        actual_traded_notional = float(np.sum(traded_diffs))
        fee_paid = actual_traded_notional * fee_rate
        new_cash = equity_before - fee_paid - float(np.sum(new_holdings * open_prices))
        new_cash = max(0.0, new_cash)

    # Turnover metrics
    current_w = asset_vals / denom
    current_cash_w = current_cash / denom
    post_asset_w = (new_holdings * open_prices) / denom
    post_cash_w = new_cash / denom

    step_gross_asset_turnover = float(np.sum(np.abs(post_asset_w - current_w)))
    step_one_way_turnover = float(0.5 * (step_gross_asset_turnover + abs(post_cash_w - current_cash_w)))

    # Conservation assertion
    V_post_check = float(np.sum(new_holdings * open_prices)) + new_cash
    assert abs(V_post_check - (equity_before - fee_paid)) < 1e-4, f"Conservation failed: {V_post_check} vs {equity_before - fee_paid}"

    return (
        new_holdings,
        new_cash,
        actual_traded_notional,
        fee_paid,
        step_one_way_turnover,
        step_gross_asset_turnover,
        executed_orders_count,
    )

