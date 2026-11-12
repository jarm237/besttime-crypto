r"""N1.3 Phase A — Close N1.2 Material Definitions (aggTrades Semantics & Exact Gross/Net Accounting Bridge).

Resolves two material definitions from N1.2 without rerunning H-A research or retraining models:
1. Phase A1 (`aggTrades` semantics):
   Explicitly separates:
   - `aggregate_trade_events` (rows in Binance `aggTrades` stream)
   - `underlying_execution_matches` (`last_trade_id - first_trade_id + 1`: number of individual match events
     aggregated into the `aggTrade` at identical price, timestamp, and aggressor side — NOT unique resting limit orders,
     nor multi-price-level sweeps, because Binance `aggTrades` aggregates same-price, same-timestamp fills).
   - `unique_resting_orders` (unobservable from `aggTrades` alone because one resting order can be partially filled
     across multiple timestamps or multiple resting orders can sit at the exact same price level).
   - `multi_price_level_sweeps` (consecutive same-timestamp, same-aggressor-side `aggTrades` across distinct prices $p_k \ne p_{k-1}$).
2. Phase A2 (Exact Trade-Ledger Gross/Net Bridge):
   Decomposes portfolio PnL into five exact components that reconcile to $0.00 discrepancy:
   - `gross_pnl_same_executed_path` = $\sum_{t=0}^{T-1} E^{\text{net,post-cost}}_t \cdot r^{\text{port}}_t$
   - `zero_friction_counterfactual_pnl` = $E^{\text{gross}}_T - E_0$
   - `transaction_friction_paid` = $\sum_{t=0}^{T-1} c_t$
   - `capital_path_effect` = `gross_pnl_same_executed_path` - `zero_friction_counterfactual_pnl`
   - `realized_net_pnl` = `gross_pnl_same_executed_path` - `transaction_friction_paid`
     = `zero_friction_counterfactual_pnl` + `capital_path_effect` - `transaction_friction_paid`
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

AGGTRADES_SEMANTIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "aggregate_trade_events": {
        "formula": "count(agg_trade_id)",
        "observable_in_aggtrades": "EXACT",
        "meaning": (
            "Number of rows in the Binance `aggTrades` archive. Each row represents trades from a single taker order "
            "that filled at the SAME price and within the SAME timestamp unit."
        ),
    },
    "underlying_execution_matches": {
        "formula": "sum(last_trade_id - first_trade_id + 1)",
        "observable_in_aggtrades": "EXACT",
        "meaning": (
            "Number of individual matching-engine trade executions (`trade_id`s) compressed into an `aggTrade` row "
            "at the same price and timestamp. Each match pairs the aggressor order against a resting maker slice at that single price level."
        ),
        "n1_2_renamed_from": "underlying_order_count / sweep_orders_per_aggtrade",
        "n1_3_canonical_name": "underlying_execution_match_count / same_price_match_fragmentation",
    },
    "unique_resting_orders": {
        "formula": "count(distinct maker_order_id)",
        "observable_in_aggtrades": "UNOBSERVABLE_WITHOUT_L3_ORDER_ID",
        "meaning": (
            "True count of distinct resting limit orders on the book. Cannot be equated to `last_trade_id - first_trade_id + 1` "
            "when one maker order is hit across multiple aggTrades or when self-trade prevention / iceberg replenishment splits executions."
        ),
    },
    "multi_price_level_sweeps": {
        "formula": "count(consecutive aggTrades with ts_k == ts_{k-1}, sign_k == sign_{k-1}, and price_k != price_{k-1})",
        "observable_in_aggtrades": "OBSERVABLE_ACROSS_CONSECUTIVE_AGGTRADE_ROWS_ONLY",
        "meaning": (
            "A single aggressive market order walking across multiple distinct price levels on the order book. "
            "Because Binance `aggTrades` splits whenever price changes, a multi-price-level sweep produces MULTIPLE "
            "`aggTrade` rows at the identical timestamp with monotonic price progression, whereas `last_id - first_id + 1 >= 3` "
            "within a single `aggTrade` row measures multi-match fragmentation at a SINGLE price level."
        ),
    },
}

FEATURE_RENAME_MAP_N1_2_TO_N1_3: Dict[str, str] = {
    "underlying_order_count": "underlying_execution_match_count",
    "buy_sweep_orders": "buy_same_price_execution_matches",
    "sell_sweep_orders": "sell_same_price_execution_matches",
    "ha_sweep_intensity_raw": "ha_same_price_match_fragmentation_raw",
    "ha_sweep_intensity_z": "ha_same_price_match_fragmentation_z",
    "ha_signed_sweep_imb_raw": "ha_signed_match_fragmentation_imb_raw",
    "ha_signed_sweep_imb": "ha_signed_match_fragmentation_imb",
    "ha_multifill_ofi_raw": "ha_multimatch_same_price_ofi_raw",
    "ha_multifill_ofi": "ha_multimatch_same_price_ofi",
}


def compute_exact_gross_net_bridge(
    df: pd.DataFrame,
    weights_df: pd.DataFrame,
    cost_per_leg_bps: float = 7.0,
    extra_half_spread_col: Optional[str] = None,
    initial_capital: float = 20_000.0,
) -> Dict[str, Any]:
    r"""Compute the 5-term exact trade-ledger gross/net bridge with zero reconciliation error.

    Why `zero_friction_counterfactual_pnl - transaction_friction_paid != realized_net_pnl` in N1.2:
    - In N1.2, `gross_pnl_usd` was computed on a counterfactual zero-friction equity path $E^{\text{gross}}_t$
      that never paid transaction costs, whereas `net_pnl_usd` compounded returns on the actual post-cost
      equity base $E^{\text{net}}_t$.
    - At every step $t$, the dollar return earned on the actual executed capital base is:
      $\Delta E^{\text{gross,actual}}_t = (E^{\text{net}}_t - c_t) \cdot r^{\text{port}}_t$,
      and the step net equity change is:
      $E^{\text{net}}_{t+1} - E^{\text{net}}_t = \Delta E^{\text{gross,actual}}_t - c_t$.
    - Summing over $t = 0 \dots T-1$ gives the exact identity:
      `realized_net_pnl == gross_pnl_same_executed_path - transaction_friction_paid`
      and
      `gross_pnl_same_executed_path == zero_friction_counterfactual_pnl + capital_path_effect`.
    """
    piv_ret = df.pivot(index="hour_close_ms", columns="symbol", values="fwd_ret_1h").fillna(0.0)
    common_ts = weights_df.index.intersection(piv_ret.index).sort_values()
    w_mat = weights_df.loc[common_ts].fillna(0.0).clip(lower=0.0)
    row_sum = w_mat.sum(axis=1)
    scale = np.where(row_sum > 1.0, 1.0 / np.maximum(row_sum, 1e-9), 1.0)
    w_mat = w_mat.mul(scale, axis=0)

    r_mat = np.expm1(piv_ret.loc[common_ts, w_mat.columns].to_numpy(dtype=np.float64))
    w_arr = w_mat.to_numpy(dtype=np.float64)
    n_steps, n_assets = w_arr.shape

    if extra_half_spread_col and extra_half_spread_col in df.columns:
        piv_sp = (
            df.pivot(index="hour_close_ms", columns="symbol", values=extra_half_spread_col)
            .reindex(index=common_ts, columns=w_mat.columns)
            .fillna(1.0)
            .to_numpy(dtype=np.float64)
            * 0.5
        )
    else:
        piv_sp = np.zeros_like(w_arr)

    leg_rate_mat = (cost_per_leg_bps + piv_sp) * 1e-4

    equity_net = float(initial_capital)
    equity_zero_friction = float(initial_capital)
    prev_w = np.zeros(n_assets, dtype=np.float64)

    gross_pnl_same_executed_path = 0.0
    transaction_friction_paid = 0.0
    trade_events_count = 0
    total_one_way_turnover = 0.0

    for t in range(n_steps):
        target_w = w_arr[t]
        delta_w = np.abs(target_w - prev_w)
        one_way_to = float(np.sum(delta_w))
        total_one_way_turnover += one_way_to
        if one_way_to > 1e-6:
            trade_events_count += int(np.sum(delta_w > 1e-4))

        cost_frac = float(np.sum(delta_w * leg_rate_mat[t]))
        cost_usd = equity_net * cost_frac
        transaction_friction_paid += cost_usd
        eq_after_cost = max(0.0, equity_net - cost_usd)

        port_ret = float(np.dot(target_w, r_mat[t]))
        step_gross_same_path = eq_after_cost * port_ret
        gross_pnl_same_executed_path += step_gross_same_path

        equity_net = eq_after_cost + step_gross_same_path
        equity_zero_friction *= 1.0 + port_ret

        denom = 1.0 + port_ret
        if denom > 1e-9:
            prev_w = target_w * (1.0 + r_mat[t]) / denom
        else:
            prev_w = np.zeros(n_assets, dtype=np.float64)

    zero_friction_counterfactual_pnl = equity_zero_friction - initial_capital
    realized_net_pnl = equity_net - initial_capital
    capital_path_effect = gross_pnl_same_executed_path - zero_friction_counterfactual_pnl

    # Exact identity checks
    identity_diff_same_path = realized_net_pnl - (gross_pnl_same_executed_path - transaction_friction_paid)
    identity_diff_counterfactual = realized_net_pnl - (
        zero_friction_counterfactual_pnl + capital_path_effect - transaction_friction_paid
    )

    years = max(n_steps / 8760.0, 1e-6)
    return {
        "bars": int(n_steps),
        "initial_capital": round(initial_capital, 2),
        "final_equity_zero_friction": round(equity_zero_friction, 2),
        "final_equity_net": round(equity_net, 2),
        "gross_pnl_same_executed_path": round(gross_pnl_same_executed_path, 2),
        "zero_friction_counterfactual_pnl": round(zero_friction_counterfactual_pnl, 2),
        "transaction_friction_paid": round(transaction_friction_paid, 2),
        "capital_path_effect": round(capital_path_effect, 2),
        "realized_net_pnl": round(realized_net_pnl, 2),
        "naive_gross_minus_cost_discrepancy_explained": round(-capital_path_effect, 2),
        "reconciliation_residual_same_path_usd": round(identity_diff_same_path, 8),
        "reconciliation_residual_full_bridge_usd": round(identity_diff_counterfactual, 8),
        "trade_leg_count": int(trade_events_count),
        "annualized_turnover": round(total_one_way_turnover / years, 2),
    }
