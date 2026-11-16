"""Canonical CARM reference implementation extracted unmodified from commit 0d9f6660.

Source file: scripts/run_information_mechanism_discovery.py at commit 0d9f6660.
Preserved for regression testing and canonical mathematical parity verification.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def simulate_carm_top_momentum_strategy(
    piv_close: pd.DataFrame,
    symbols: List[str],
    prices: np.ndarray,
    timestamps: pd.Index,
    top_k: int = 3,
    rebalance_interval_hours: int = 168,
    rebalance_on_drift: bool = False,
    fee_bps: float = 12.0,
    initial_capital_usd: float = 10000.0,
) -> Dict[str, Any]:
    """Causal stateful evaluation of CARM-CC Top-K Weekly Momentum Strategy.

    Separates:
    - CARM_WEEKLY_ONLY (rebalance_on_drift=False): trades only on scheduled weekly dates (t % 168 == 0).
    - CARM_WEEKLY_WITH_DRIFT_CONTROL (rebalance_on_drift=True): trades on scheduled dates AND when drift > 1%.

    Guarantees:
    - Initial capital = $10,000.00 before fees.
    - Entry fees deducted exactly once at inception.
    - Net return = (final_equity / initial_capital) - 1.
    - Strictly causal: 168h return evaluated at bar t-2 close, signal at t-1 close, executed at bar t prices.
    """
    T, N = prices.shape
    fee_rate = fee_bps / 10000.0

    # Causal 168h return available for decision (shift 2 guarantees causal 1h execution delay)
    piv_past_168h = piv_close.pct_change(rebalance_interval_hours).shift(2)

    cash = initial_capital_usd
    holdings = np.zeros(N)
    equities = []
    fees_paid = []
    turnovers = []
    rebalance_count = 0

    current_target_w = np.full(N, 1.0 / N)

    for t in range(T):
        is_scheduled = (t == 0) or (t % rebalance_interval_hours == 0)

        # Update target ranking on scheduled ranking dates
        if t >= rebalance_interval_hours and is_scheduled:
            row = piv_past_168h.iloc[t]
            top_assets = row.nlargest(top_k).index
            current_target_w = np.zeros(N)
            for sym in top_assets:
                current_target_w[symbols.index(sym)] = 1.0 / top_k

        # Current holdings value at price t before trade
        asset_vals = holdings * prices[t]
        equity_before = cash + float(np.sum(asset_vals))
        current_w = asset_vals / max(equity_before, 1e-6)

        should_rebalance = False
        if is_scheduled:
            should_rebalance = True
        elif rebalance_on_drift and np.sum(np.abs(current_target_w - current_w)) > 0.01:
            should_rebalance = True

        if should_rebalance:
            rebalance_count += 1
            dw = float(np.sum(np.abs(current_target_w - current_w)))
            fee = equity_before * dw * fee_rate
            post_fee_equity = equity_before - fee

            target_vals = current_target_w * post_fee_equity
            holdings = target_vals / prices[t]
            cash = post_fee_equity - float(np.sum(target_vals))
            fees_paid.append(fee)
            turnovers.append(dw)
        else:
            fees_paid.append(0.0)
            turnovers.append(0.0)

        equity_after = cash + float(np.sum(holdings * prices[t]))
        equities.append(equity_after)

    equity_series = pd.Series(equities, index=timestamps)
    fee_series = pd.Series(fees_paid, index=timestamps)

    final_equity = float(equity_series.iloc[-1])
    # Exact reconciliation with initial capital
    net_return_pct = float(((final_equity / initial_capital_usd) - 1.0) * 100.0)

    peak = equity_series.cummax()
    drawdowns = (equity_series - peak) / peak
    max_drawdown_pct = float(drawdowns.min() * 100.0)

    # Risk metrics
    port_rets = equity_series.pct_change().dropna()
    mean_ret_ann = float(port_rets.mean() * 8760.0)
    std_ret_ann = float(port_rets.std() * np.sqrt(8760.0))
    sharpe_ann = float(mean_ret_ann / (std_ret_ann + 1e-9))

    downside_rets = port_rets.clip(upper=0.0)
    downside_dev_ann = float(np.sqrt(np.mean(downside_rets ** 2)) * np.sqrt(8760.0))
    sortino_ann = float(mean_ret_ann / (downside_dev_ann + 1e-9))

    return {
        "initial_capital_usd": initial_capital_usd,
        "final_equity_usd": round(final_equity, 2),
        "net_return_pct": round(net_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "annualized_return_pct": round(mean_ret_ann * 100.0, 2),
        "annualized_sharpe": round(sharpe_ann, 3),
        "annualized_sortino": round(sortino_ann, 3),
        "rebalance_count": rebalance_count,
        "total_turnover": round(sum(turnovers), 2),
        "total_fees_paid_usd": round(sum(fees_paid), 2),
        "equity_series": equity_series,
        "fee_series": fee_series,
        "final_holdings": holdings,
    }
