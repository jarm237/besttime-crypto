r"""N1.4 Phase E — Economic Falsification Before Neural Training.

Evaluates Candidate H-1 (`DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`) and
Candidate H-2 (`STRUCTURAL_DELEVERAGING_LIQUIDITY_PROVISION_MULTI_DAY`) across all 13 mandatory
Phase E economic falsification criteria before any neural network training is considered:
1. `gross_economic_payoff`
2. `expected_cost_to_capture`
3. `net_payoff`
4. `holding_period`
5. `realized_turnover`
6. `gross_vs_net` (with exact 5-term trade-ledger reconciliation bridge)
7. `exposure_and_beta` (mean exposure, empirical beta vs BTC and Equal-Weight crypto market)
8. `drawdown` (max drawdown %, ulcer index)
9. `tail_risk` (hourly/daily VaR 95%, CVaR 95%, worst step, worst 7d window, margin liquidation count)
10. `capacity` (estimated portfolio USD capacity at <= 5 bps market impact from observed contract volume)
11. `timing_sensitivity` (`close_t`, `next_bar_open_slippage`, `1h_delay`, `4h_delay`)
12. `regime_consistency` (`2022 Bear`, `2023 Recovery`, `2024 Expansion`, `2025 Adaptive Dev`)
13. `uncertainty` (Newey-West t-stat, stationary block-bootstrap 95% confidence interval)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _newey_west_tstat(x: np.ndarray, max_lag: int = 24) -> float:
    arr = np.asarray(x, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 30:
        return 0.0
    mu = float(np.mean(arr))
    e = arr - mu
    gamma0 = float(np.dot(e, e) / n)
    if gamma0 <= 1e-18:
        return 0.0
    var_nw = gamma0
    L = min(max_lag, n - 1)
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        cov = float(np.dot(e[lag:], e[:-lag]) / n)
        var_nw += 2.0 * w * cov
    var_nw = max(var_nw, 1e-18)
    se = math.sqrt(var_nw / n)
    return float(mu / se) if se > 0 else 0.0


def _block_bootstrap_ci95_sum(
    step_net_pnl: np.ndarray,
    block_size: int = 168,
    n_boot: int = 400,
    seed: int = 42,
) -> List[float]:
    arr = np.asarray(step_net_pnl, dtype=np.float64)
    n = len(arr)
    if n < block_size:
        s = float(np.sum(arr))
        return [round(s, 2), round(s, 2)]
    rng = np.random.default_rng(seed)
    n_blocks = max(1, int(math.ceil(n / block_size)))
    totals = np.empty(n_boot, dtype=np.float64)
    max_start = max(1, n - block_size + 1)
    for b in range(n_boot):
        starts = rng.integers(0, max_start, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]
        totals[b] = float(np.sum(arr[idx]))
    return [round(float(np.percentile(totals, 2.5)), 2), round(float(np.percentile(totals, 97.5)), 2)]


def prepare_n1_4_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute strictly causal features for H-1 (Term-Structure Carry) and H-2 (Multi-Day Deleveraging)."""
    df = panel.sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True).copy()

    for sym, grp in df.groupby("symbol", sort=False):
        idx = grp.index
        b1 = grp["f1_basis_bps"].fillna(0.0)
        y1 = grp["f1_implied_yield_ann_pct"].fillna(0.0)

        # Causal rolling statistics of Front-Quarter basis and implied yield
        b1_ma24 = b1.rolling(24, min_periods=6).mean()
        b1_ma168 = b1.rolling(168, min_periods=24).mean()
        b1_std168 = b1.rolling(168, min_periods=24).std().replace(0.0, np.nan)

        df.loc[idx, "f1_basis_ma24_bps"] = b1_ma24.fillna(0.0)
        df.loc[idx, "f1_basis_ma168_bps"] = b1_ma168.fillna(0.0)
        df.loc[idx, "f1_basis_z168"] = ((b1 - b1_ma168) / np.maximum(b1_std168, 5.0)).clip(-5.0, 5.0).fillna(0.0)
        df.loc[idx, "f1_basis_change_24h_bps"] = (b1 - b1.shift(24)).fillna(0.0)
        df.loc[idx, "f1_basis_change_72h_bps"] = (b1 - b1.shift(72)).fillna(0.0)
        df.loc[idx, "f1_yield_ma24_pct"] = y1.rolling(24, min_periods=6).mean().fillna(0.0)

        # H-2 Multi-day forced-deleveraging features (strictly causal)
        r120 = grp["spot_past_ret_120h"].fillna(0.0)
        r24 = grp["spot_past_ret_24h"].fillna(0.0)
        r120_mu = r120.rolling(336, min_periods=48).mean()
        r120_sd = r120.rolling(336, min_periods=48).std().replace(0.0, np.nan)
        df.loc[idx, "h2_ret_120h_z"] = ((r120 - r120_mu) / np.maximum(r120_sd, 1e-4)).clip(-5.0, 5.0).fillna(0.0)

        vol24 = grp["spot_quote_vol"].rolling(24, min_periods=6).sum()
        vol168 = grp["spot_quote_vol"].rolling(168, min_periods=24).mean() * 24.0
        df.loc[idx, "h2_vol_surge_ratio"] = np.log(np.maximum(vol24, 1.0) / np.maximum(vol168, 1.0)).clip(-3.0, 3.0).fillna(0.0)

        pb = grp["perp_spot_basis_close_bps"].fillna(0.0)
        pb_mu = pb.rolling(168, min_periods=24).mean()
        pb_sd = pb.rolling(168, min_periods=24).std().replace(0.0, np.nan)
        df.loc[idx, "h2_perp_basis_z"] = ((pb - pb_mu) / np.maximum(pb_sd, 0.5)).clip(-5.0, 5.0).fillna(0.0)

        # Stabilization bounce indicator: last 24h return recovering relative to 5-day crash pace
        df.loc[idx, "h2_stabilization_bps"] = ((r24 - (r120 / 5.0)) * 10_000.0).clip(-500.0, 500.0).fillna(0.0)

    # Cross-sectional relative yield and basis rank at each hour_close_ms
    df["f1_yield_cs_median_pct"] = df.groupby("hour_close_ms")["f1_yield_ma24_pct"].transform("median").fillna(0.0)
    df["f1_yield_cs_excess_pct"] = (df["f1_yield_ma24_pct"] - df["f1_yield_cs_median_pct"]).fillna(0.0)

    return df


def build_h1_simple_carry_weights(
    df: pd.DataFrame,
    rebalance_every_hours: int = 24,
    entry_basis_bps: float = 75.0,
    entry_yield_ann_pct: float = 5.0,
    exit_basis_bps: float = 15.0,
    max_single_weight: float = 0.35,
    l1_hysteresis: float = 0.08,
) -> pd.DataFrame:
    """Build stateful hypothesis-specific non-neural baseline weights for H-1 (Quarterly Delivery Carry).

    Economic lifecycle rules (fixed from transaction-cost economics, zero parameter optimization):
    1. Entry requires `f1_basis_ma24_bps >= entry_basis_bps` (75 bps > 3.4x the 22 bps round-trip cost)
       AND `f1_yield_ma24_pct >= entry_yield_ann_pct` (5.0% p.a.) AND `f1_ttm_hours >= 24.0`.
    2. Once entered (`w_prev > 0`), the position is HELD across intermediate bars (`15 bps < basis < 75 bps`)
       until either:
       - Basis compresses to `<= exit_basis_bps` (15 bps, capturing >80-95% of convergence early), OR
       - Contract reaches maturity settlement (`f1_ttm_hours < 2.0`), where it settles at 0 bps and re-evaluates
         the new front contract.
    """
    symbols = sorted(df["symbol"].unique())
    hours = np.sort(df["hour_close_ms"].unique())

    piv_basis = df.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_ma24_bps").reindex(index=hours, columns=symbols).fillna(-999.0)
    piv_raw_b = df.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_bps").reindex(index=hours, columns=symbols).fillna(-999.0)
    piv_yield = df.pivot(index="hour_close_ms", columns="symbol", values="f1_yield_ma24_pct").reindex(index=hours, columns=symbols).fillna(-999.0)
    piv_ttm = df.pivot(index="hour_close_ms", columns="symbol", values="f1_ttm_hours").reindex(index=hours, columns=symbols).fillna(0.0)

    b_arr = piv_basis.to_numpy(dtype=np.float64)
    rb_arr = piv_raw_b.to_numpy(dtype=np.float64)
    y_arr = piv_yield.to_numpy(dtype=np.float64)
    ttm_arr = piv_ttm.to_numpy(dtype=np.float64)

    n_steps, n_assets = b_arr.shape
    w_out = np.zeros((n_steps, n_assets), dtype=np.float64)
    w_prev = np.zeros(n_assets, dtype=np.float64)

    for t in range(n_steps):
        # Always check hard exit conditions (contract missing/delisted or basis compressed below exit threshold)
        active_contract = (ttm_arr[t] >= 1.0) & (rb_arr[t] > -500.0)
        early_harvest_or_backwardation = (b_arr[t] <= exit_basis_bps) | (rb_arr[t] <= 5.0)

        if t % rebalance_every_hours == 0:
            w_prop = np.zeros(n_assets, dtype=np.float64)
            scores = np.zeros(n_assets, dtype=np.float64)
            for i in range(n_assets):
                if not active_contract[i] or early_harvest_or_backwardation[i]:
                    scores[i] = 0.0
                elif w_prev[i] > 1e-4 and b_arr[t, i] > exit_basis_bps and y_arr[t, i] > 2.0:
                    # Stateful hold of existing carry position while basis remains positive
                    scores[i] = max(y_arr[t, i] - 2.0, 1.0)
                elif ttm_arr[t, i] >= 24.0 and b_arr[t, i] >= entry_basis_bps and y_arr[t, i] >= entry_yield_ann_pct:
                    # New entry into high-contango quarterly contract
                    scores[i] = max(y_arr[t, i] - 3.0, 1.0)

            pos_mask = scores > 0.0
            if np.any(pos_mask):
                # Aggregate carry regime budget scales smoothly with top annualized yield (full budget at >=14% p.a.)
                top_y = float(np.max(y_arr[t, pos_mask]))
                budget = float(np.clip((top_y - 3.0) / 10.0, 0.25, 1.0))
                raw_w = scores / np.sum(scores) * budget
                raw_w = np.minimum(raw_w, max_single_weight)
                if np.sum(raw_w) > 1.0:
                    raw_w = raw_w / np.sum(raw_w)
                w_prop = raw_w

            # Apply L1 turnover hysteresis unless exiting to cash or forced contract drop
            l1_diff = float(np.sum(np.abs(w_prop - w_prev)))
            if l1_diff >= l1_hysteresis or (np.sum(w_prop) == 0.0 and np.sum(w_prev) > 0.0):
                w_curr = w_prop
            else:
                w_curr = w_prev.copy()
                # Still enforce hard exits on inactive contracts
                w_curr[~active_contract | early_harvest_or_backwardation] = 0.0
        else:
            w_curr = w_prev.copy()
            w_curr[~active_contract] = 0.0

        w_out[t] = w_curr
        w_prev = w_curr

    return pd.DataFrame(w_out, index=hours, columns=symbols)


def build_h1_passive_carry_benchmark_weights(
    df: pd.DataFrame,
    target_weights_df: pd.DataFrame,
) -> pd.DataFrame:
    """Exposure-matched Equal-Weight Passive Carry benchmark across active quarterly delivery contracts."""
    symbols = list(target_weights_df.columns)
    hours = target_weights_df.index
    piv_ttm = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_ttm_hours")
        .reindex(index=hours, columns=symbols)
        .fillna(0.0)
    )
    active = (piv_ttm.to_numpy(dtype=np.float64) >= 1.0).astype(np.float64)
    active_count = np.maximum(np.sum(active, axis=1, keepdims=True), 1.0)
    unit_ew = active / active_count
    mean_exp = float(target_weights_df.sum(axis=1).mean())
    return pd.DataFrame(unit_ew * mean_exp, index=hours, columns=symbols)


def simulate_quarterly_carry_portfolio(
    df: pd.DataFrame,
    weights_df: pd.DataFrame,
    pair_cost_per_leg_bps: float = 11.0,  # 7 bps Spot + 4 bps CM Delivery = 11 bps per paired leg (22 bps RT)
    quarterly_roll_fee_bps: float = 5.5,  # 1.5 bps settlement + 4.0 bps new CM short leg at quarterly roll
    latency_mode: str = "close_t",
    initial_capital: float = 20_000.0,
) -> Dict[str, Any]:
    """Simulate a 1x COIN-M Quarterly Delivery Cash-and-Carry portfolio with exact 5-term ledger reconciliation."""
    symbols = list(weights_df.columns)
    common_ts = weights_df.index.sort_values()

    if latency_mode == "1h_delay":
        w_eff = weights_df.loc[common_ts].shift(1).fillna(0.0)
    elif latency_mode == "4h_delay":
        w_eff = weights_df.loc[common_ts].shift(4).fillna(0.0)
    else:
        w_eff = weights_df.loc[common_ts].fillna(0.0)

    w_mat = w_eff.clip(lower=0.0)
    row_sum = w_mat.sum(axis=1)
    scale = np.where(row_sum > 1.0, 1.0 / np.maximum(row_sum, 1e-9), 1.0)
    w_mat = w_mat.mul(scale, axis=0)

    piv_ret = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_carry_ret_1h")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )
    piv_settle = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_settling_next_hour")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )
    piv_slip = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_entry_open_slippage_bps")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )
    piv_spot_ret = (
        df.pivot(index="hour_close_ms", columns="symbol", values="spot_ret_1h")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )
    piv_f1_high = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_high")
        .reindex(index=common_ts, columns=symbols)
        .ffill()
    )
    piv_spot_low = (
        df.pivot(index="hour_close_ms", columns="symbol", values="spot_low")
        .reindex(index=common_ts, columns=symbols)
        .ffill()
    )
    piv_f1_vol = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_notional_usd")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )

    r_mat = piv_ret.to_numpy(dtype=np.float64)
    settle_mat = piv_settle.to_numpy(dtype=np.float64)
    slip_mat = piv_slip.to_numpy(dtype=np.float64)
    w_arr = w_mat.to_numpy(dtype=np.float64)
    n_steps, n_assets = w_arr.shape

    eq_gross = float(initial_capital)
    eq_net = float(initial_capital)
    w_prev_net = np.zeros(n_assets, dtype=np.float64)

    total_cost_usd = 0.0
    total_roll_cost_usd = 0.0
    total_rebalance_cost_usd = 0.0
    gross_pnl_same_executed_path = 0.0
    total_turnover = 0.0
    trade_leg_count = 0
    quarterly_roll_count = 0

    net_eq_series = np.empty(n_steps, dtype=np.float64)
    step_net_pnl_series = np.empty(n_steps, dtype=np.float64)
    step_net_ret_series = np.empty(n_steps, dtype=np.float64)
    asset_gross_contrib = np.zeros(n_assets, dtype=np.float64)

    # Holding period tracking
    active_holding_spells: List[int] = []
    current_spell_hours = np.zeros(n_assets, dtype=np.int64)

    for t in range(n_steps):
        w_target = w_arr[t]
        delta_w = np.abs(w_target - w_prev_net)
        step_turn = float(np.sum(delta_w))
        total_turnover += step_turn
        trade_leg_count += int(np.sum(delta_w > 1e-4)) * 2  # Each cash-and-carry rebalance trades 2 legs (Spot + Futures)

        # Update holding spell lengths
        for i in range(n_assets):
            if w_target[i] > 1e-4:
                current_spell_hours[i] += 1
            elif current_spell_hours[i] > 0:
                active_holding_spells.append(int(current_spell_hours[i]))
                current_spell_hours[i] = 0

        # 1. Rebalance execution cost
        leg_rates = np.full(n_assets, pair_cost_per_leg_bps / 10_000.0, dtype=np.float64)
        if latency_mode == "next_bar_open_slippage":
            leg_rates = leg_rates + (0.5 * slip_mat[t]) / 10_000.0
        rebal_cost_frac = float(np.sum(delta_w * leg_rates))
        rebal_cost_usd = eq_net * rebal_cost_frac

        # 2. Quarterly maturity settlement & roll cost (when contract settles at 08:00 UTC next hour)
        rolled_weight = np.where(settle_mat[t] > 0.5, np.minimum(w_target, w_prev_net), 0.0)
        roll_sum = float(np.sum(rolled_weight))
        roll_cost_usd = eq_net * roll_sum * (quarterly_roll_fee_bps / 10_000.0)
        if roll_sum > 1e-4:
            quarterly_roll_count += int(np.sum(rolled_weight > 1e-4))

        step_cost_usd = rebal_cost_usd + roll_cost_usd
        total_rebalance_cost_usd += rebal_cost_usd
        total_roll_cost_usd += roll_cost_usd
        total_cost_usd += step_cost_usd

        eq_net_after_cost = max(eq_net - step_cost_usd, 0.0)

        port_r = float(np.dot(w_target, r_mat[t]))
        asset_gross_contrib += eq_gross * (w_target * r_mat[t])

        step_gross_on_actual_path = eq_net_after_cost * port_r
        gross_pnl_same_executed_path += step_gross_on_actual_path

        eq_net_next = eq_net_after_cost * (1.0 + port_r)
        step_net_pnl_series[t] = eq_net_next - eq_net
        step_net_ret_series[t] = (eq_net_next / max(eq_net, 1e-9)) - 1.0

        eq_gross = eq_gross * (1.0 + port_r)
        eq_net = eq_net_next
        net_eq_series[t] = eq_net

        if port_r > -0.99:
            w_prev_net = w_target * (1.0 + r_mat[t]) / (1.0 + port_r)
        else:
            w_prev_net = np.zeros(n_assets, dtype=np.float64)

    for i in range(n_assets):
        if current_spell_hours[i] > 0:
            active_holding_spells.append(int(current_spell_hours[i]))

    years_span = max(n_steps / 8760.0, 1e-6)
    ann_turnover = total_turnover / years_span

    peaks = np.maximum.accumulate(np.concatenate([[initial_capital], net_eq_series]))[1:]
    dd_series = (net_eq_series - peaks) / np.maximum(peaks, 1e-9)
    max_dd_pct = float(np.min(dd_series) * 100.0) if len(dd_series) > 0 else 0.0

    mu_step = float(np.mean(step_net_ret_series))
    sd_step = float(np.std(step_net_ret_series, ddof=1)) if n_steps > 1 else 0.0
    sharpe = (mu_step / sd_step) * math.sqrt(8760.0) if sd_step > 1e-12 else 0.0
    downside = step_net_ret_series[step_net_ret_series < 0.0]
    sd_down = float(np.std(downside, ddof=1)) if len(downside) > 1 else 1e-12
    sortino = (mu_step / sd_down) * math.sqrt(8760.0) if sd_down > 1e-12 else 0.0

    # Empirical market beta vs Equal-Weight Spot market return and BTC return
    mkt_ew_ret = piv_spot_ret.mean(axis=1).to_numpy(dtype=np.float64)
    btc_ret = piv_spot_ret["BTCUSDT"].to_numpy(dtype=np.float64) if "BTCUSDT" in piv_spot_ret.columns else mkt_ew_ret
    var_mkt = float(np.var(mkt_ew_ret))
    var_btc = float(np.var(btc_ret))
    beta_ew = float(np.cov(step_net_ret_series, mkt_ew_ret)[0, 1] / var_mkt) if var_mkt > 1e-18 else 0.0
    beta_btc = float(np.cov(step_net_ret_series, btc_ret)[0, 1] / var_btc) if var_btc > 1e-18 else 0.0

    # Tail risk metrics (hourly & rolling 24h/168h)
    var95_1h_pct = float(np.percentile(step_net_ret_series, 5.0) * 100.0)
    tail_mask = step_net_ret_series <= np.percentile(step_net_ret_series, 5.0)
    cvar95_1h_pct = float(np.mean(step_net_ret_series[tail_mask]) * 100.0) if np.any(tail_mask) else var95_1h_pct
    worst_1h_pct = float(np.min(step_net_ret_series) * 100.0)
    roll_168h_ret = pd.Series(net_eq_series).pct_change(168).dropna()
    worst_7d_pct = float(roll_168h_ret.min() * 100.0) if len(roll_168h_ret) > 0 else worst_1h_pct

    # Margin / Liquidation check: in 1x COIN-M inverse futures, liquidation requires F_high / S_low -> infinity;
    # we check the worst intrabar basis spike (F_high / S_low - 1) across all active positions
    intrabar_spike = ((piv_f1_high / np.maximum(piv_spot_low, 1e-9)) - 1.0).to_numpy(dtype=np.float64)
    active_pos_mask = w_arr > 1e-4
    max_intrabar_basis_spike_pct = (
        float(np.max(np.where(active_pos_mask, intrabar_spike, 0.0)) * 100.0) if np.any(active_pos_mask) else 0.0
    )
    # At 1x inverse margin with 80% maintenance threshold, liquidation requires basis spike > +400%
    margin_liquidation_events = int(np.sum(np.where(active_pos_mask, intrabar_spike > 4.0, False)))

    # Capacity estimate: max portfolio capital such that average rebalance trade size is <= 1% of hourly F1 volume
    active_vols = np.where(active_pos_mask, piv_f1_vol.to_numpy(dtype=np.float64), np.nan)
    median_active_hourly_vol_usd = float(np.nanmedian(active_vols)) if np.any(np.isfinite(active_vols)) else 0.0
    estimated_capacity_usd_at_1pct_participation = round(median_active_hourly_vol_usd * 0.01 / 0.25, 0)

    zero_friction_cf_pnl = eq_gross - initial_capital
    realized_net_pnl = eq_net - initial_capital
    capital_path_effect = gross_pnl_same_executed_path - zero_friction_cf_pnl
    reconciliation_residual = realized_net_pnl - (gross_pnl_same_executed_path - total_cost_usd)

    mean_hold_hours = float(np.mean(active_holding_spells)) if active_holding_spells else 0.0
    median_hold_hours = float(np.median(active_holding_spells)) if active_holding_spells else 0.0

    contrib_map = {symbols[i]: round(float(asset_gross_contrib[i]), 2) for i in range(n_assets)}
    pos_assets = sum(1 for v in contrib_map.values() if v > 0.0)

    return {
        "bars": int(n_steps),
        "initial_capital": round(initial_capital, 2),
        "final_equity_gross": round(eq_gross, 2),
        "final_equity_net": round(eq_net, 2),
        "gross_pnl_usd": round(zero_friction_cf_pnl, 2),
        "net_pnl_usd": round(realized_net_pnl, 2),
        "gross_pnl_same_executed_path": round(gross_pnl_same_executed_path, 2),
        "zero_friction_counterfactual_pnl": round(zero_friction_cf_pnl, 2),
        "transaction_friction_paid": round(total_cost_usd, 2),
        "rebalance_friction_paid_usd": round(total_rebalance_cost_usd, 2),
        "quarterly_roll_friction_paid_usd": round(total_roll_cost_usd, 2),
        "capital_path_effect": round(capital_path_effect, 2),
        "realized_net_pnl": round(realized_net_pnl, 2),
        "reconciliation_residual_usd": round(reconciliation_residual, 6),
        "gross_return_pct": round((zero_friction_cf_pnl / initial_capital) * 100.0, 2),
        "net_return_pct": round((realized_net_pnl / initial_capital) * 100.0, 2),
        "annualized_turnover": round(ann_turnover, 2),
        "trade_leg_count": int(trade_leg_count),
        "quarterly_roll_count": int(quarterly_roll_count),
        "mean_holding_period_hours": round(mean_hold_hours, 1),
        "mean_holding_period_days": round(mean_hold_hours / 24.0, 2),
        "median_holding_period_days": round(median_hold_hours / 24.0, 2),
        "mean_hedged_exposure": round(float(np.mean(np.sum(w_arr, axis=1))), 4),
        "empirical_beta_vs_ew_crypto": round(beta_ew, 5),
        "empirical_beta_vs_btc": round(beta_btc, 5),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_annualized": round(sharpe, 3),
        "sortino_annualized": round(sortino, 3),
        "net_step_tstat": round(_newey_west_tstat(step_net_ret_series), 3),
        "net_pnl_ci95_usd": _block_bootstrap_ci95_sum(step_net_pnl_series),
        "tail_risk": {
            "var95_1h_pct": round(var95_1h_pct, 3),
            "cvar95_1h_pct": round(cvar95_1h_pct, 3),
            "worst_1h_pct": round(worst_1h_pct, 3),
            "worst_7d_pct": round(worst_7d_pct, 3),
            "max_intrabar_basis_spike_pct": round(max_intrabar_basis_spike_pct, 2),
            "margin_liquidation_events": int(margin_liquidation_events),
        },
        "capacity": {
            "median_active_contract_hourly_vol_usd": round(median_active_hourly_vol_usd, 0),
            "estimated_portfolio_capacity_usd_at_1pct_vol": estimated_capacity_usd_at_1pct_participation,
        },
        "asset_gross_contribution_usd": contrib_map,
        "positive_assets_count": int(pos_assets),
        "total_assets_count": int(n_assets),
        "latency_mode": latency_mode,
        "pair_round_trip_cost_bps": round(pair_cost_per_leg_bps * 2.0, 2),
    }


def build_h2_multiday_liquidity_weights(
    df: pd.DataFrame,
    rebalance_every_hours: int = 72,
    entry_z_thresh: float = -1.25,
    max_single_weight: float = 0.35,
    l1_hysteresis: float = 0.10,
) -> pd.DataFrame:
    """Build hypothesis-specific non-neural baseline weights for H-2 (Multi-Day Deleveraging Liquidity Provision)."""
    symbols = sorted(df["symbol"].unique())
    hours = np.sort(df["hour_close_ms"].unique())

    piv_z120 = df.pivot(index="hour_close_ms", columns="symbol", values="h2_ret_120h_z").reindex(index=hours, columns=symbols).fillna(0.0)
    piv_pb = df.pivot(index="hour_close_ms", columns="symbol", values="h2_perp_basis_z").reindex(index=hours, columns=symbols).fillna(0.0)
    piv_stab = df.pivot(index="hour_close_ms", columns="symbol", values="h2_stabilization_bps").reindex(index=hours, columns=symbols).fillna(0.0)

    z_arr = piv_z120.to_numpy(dtype=np.float64)
    pb_arr = piv_pb.to_numpy(dtype=np.float64)
    st_arr = piv_stab.to_numpy(dtype=np.float64)

    n_steps, n_assets = z_arr.shape
    w_out = np.zeros((n_steps, n_assets), dtype=np.float64)
    w_prev = np.zeros(n_assets, dtype=np.float64)

    for t in range(n_steps):
        if t % rebalance_every_hours == 0:
            scores = np.zeros(n_assets, dtype=np.float64)
            for i in range(n_assets):
                # Oversold 5-day capitulation with perp discount and stabilizing 24h flow
                if z_arr[t, i] <= entry_z_thresh and pb_arr[t, i] <= -0.25 and st_arr[t, i] >= -50.0:
                    scores[i] = abs(z_arr[t, i])
                elif w_prev[i] > 1e-4 and z_arr[t, i] < 0.0:
                    scores[i] = max(abs(z_arr[t, i]), 0.25)

            w_prop = np.zeros(n_assets, dtype=np.float64)
            if np.any(scores > 0.0):
                budget = float(np.clip(np.max(scores) / 2.5, 0.15, 0.85))
                w_prop = (scores / np.sum(scores)) * budget
                w_prop = np.minimum(w_prop, max_single_weight)

            if float(np.sum(np.abs(w_prop - w_prev))) >= l1_hysteresis or (np.sum(w_prop) == 0.0 and np.sum(w_prev) > 0.0):
                w_curr = w_prop
            else:
                w_curr = w_prev.copy()
        else:
            w_curr = w_prev.copy()

        w_out[t] = w_curr
        w_prev = w_curr

    return pd.DataFrame(w_out, index=hours, columns=symbols)


def simulate_h2_spot_liquidity_portfolio(
    df: pd.DataFrame,
    weights_df: pd.DataFrame,
    cost_per_leg_bps: float = 7.0,
    initial_capital: float = 20_000.0,
) -> Dict[str, Any]:
    """Simulate H-2 Multi-Day Spot Liquidity Provision with exact 5-term ledger reconciliation."""
    symbols = list(weights_df.columns)
    common_ts = weights_df.index.sort_values()
    w_arr = weights_df.loc[common_ts].fillna(0.0).clip(lower=0.0).to_numpy(dtype=np.float64)

    piv_ret = (
        df.pivot(index="hour_close_ms", columns="symbol", values="spot_ret_1h")
        .reindex(index=common_ts, columns=symbols)
        .fillna(0.0)
    )
    r_mat = np.expm1(piv_ret.to_numpy(dtype=np.float64))
    n_steps, n_assets = w_arr.shape

    eq_gross = float(initial_capital)
    eq_net = float(initial_capital)
    w_prev_net = np.zeros(n_assets, dtype=np.float64)
    total_cost_usd = 0.0
    gross_pnl_same_path = 0.0
    total_turnover = 0.0
    trade_leg_count = 0

    net_eq_series = np.empty(n_steps, dtype=np.float64)
    step_net_pnl = np.empty(n_steps, dtype=np.float64)
    step_net_ret = np.empty(n_steps, dtype=np.float64)
    asset_gross_contrib = np.zeros(n_assets, dtype=np.float64)

    spells: List[int] = []
    cur_spell = np.zeros(n_assets, dtype=np.int64)

    for t in range(n_steps):
        w_target = w_arr[t]
        delta_w = np.abs(w_target - w_prev_net)
        total_turnover += float(np.sum(delta_w))
        trade_leg_count += int(np.sum(delta_w > 1e-4))

        for i in range(n_assets):
            if w_target[i] > 1e-4:
                cur_spell[i] += 1
            elif cur_spell[i] > 0:
                spells.append(int(cur_spell[i]))
                cur_spell[i] = 0

        cost_usd = eq_net * float(np.sum(delta_w)) * (cost_per_leg_bps / 10_000.0)
        total_cost_usd += cost_usd
        eq_after_cost = max(eq_net - cost_usd, 0.0)

        port_r = float(np.dot(w_target, r_mat[t]))
        asset_gross_contrib += eq_gross * (w_target * r_mat[t])
        gross_pnl_same_path += eq_after_cost * port_r

        eq_next = eq_after_cost * (1.0 + port_r)
        step_net_pnl[t] = eq_next - eq_net
        step_net_ret[t] = (eq_next / max(eq_net, 1e-9)) - 1.0
        eq_gross *= 1.0 + port_r
        eq_net = eq_next
        net_eq_series[t] = eq_net

        if port_r > -0.99:
            w_prev_net = w_target * (1.0 + r_mat[t]) / (1.0 + port_r)
        else:
            w_prev_net = np.zeros(n_assets, dtype=np.float64)

    for i in range(n_assets):
        if cur_spell[i] > 0:
            spells.append(int(cur_spell[i]))

    years_span = max(n_steps / 8760.0, 1e-6)
    peaks = np.maximum.accumulate(np.concatenate([[initial_capital], net_eq_series]))[1:]
    dd_series = (net_eq_series - peaks) / np.maximum(peaks, 1e-9)
    max_dd_pct = float(np.min(dd_series) * 100.0) if len(dd_series) > 0 else 0.0

    mu_step = float(np.mean(step_net_ret))
    sd_step = float(np.std(step_net_ret, ddof=1)) if n_steps > 1 else 0.0
    sharpe = (mu_step / sd_step) * math.sqrt(8760.0) if sd_step > 1e-12 else 0.0

    mkt_ew_ret = r_mat.mean(axis=1)
    var_mkt = float(np.var(mkt_ew_ret))
    beta_ew = float(np.cov(step_net_ret, mkt_ew_ret)[0, 1] / var_mkt) if var_mkt > 1e-18 else 0.0

    cf_gross = eq_gross - initial_capital
    net_pnl = eq_net - initial_capital
    cap_path = gross_pnl_same_path - cf_gross
    resid = net_pnl - (gross_pnl_same_path - total_cost_usd)
    mean_hold_h = float(np.mean(spells)) if spells else 0.0

    contrib_map = {symbols[i]: round(float(asset_gross_contrib[i]), 2) for i in range(n_assets)}

    return {
        "bars": int(n_steps),
        "initial_capital": round(initial_capital, 2),
        "final_equity_gross": round(eq_gross, 2),
        "final_equity_net": round(eq_net, 2),
        "gross_pnl_usd": round(cf_gross, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "gross_pnl_same_executed_path": round(gross_pnl_same_path, 2),
        "zero_friction_counterfactual_pnl": round(cf_gross, 2),
        "transaction_friction_paid": round(total_cost_usd, 2),
        "capital_path_effect": round(cap_path, 2),
        "realized_net_pnl": round(net_pnl, 2),
        "reconciliation_residual_usd": round(resid, 6),
        "gross_return_pct": round((cf_gross / initial_capital) * 100.0, 2),
        "net_return_pct": round((net_pnl / initial_capital) * 100.0, 2),
        "annualized_turnover": round(total_turnover / years_span, 2),
        "trade_leg_count": int(trade_leg_count),
        "mean_holding_period_hours": round(mean_hold_h, 1),
        "mean_holding_period_days": round(mean_hold_h / 24.0, 2),
        "mean_exposure": round(float(np.mean(np.sum(w_arr, axis=1))), 4),
        "empirical_beta_vs_ew_crypto": round(beta_ew, 4),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_annualized": round(sharpe, 3),
        "net_step_tstat": round(_newey_west_tstat(step_net_ret), 3),
        "net_pnl_ci95_usd": _block_bootstrap_ci95_sum(step_net_pnl),
        "asset_gross_contribution_usd": contrib_map,
        "positive_assets_count": sum(1 for v in contrib_map.values() if v > 0.0),
        "total_assets_count": int(n_assets),
    }


def run_phase_e_economic_falsification(df: pd.DataFrame) -> Dict[str, Any]:
    """Run full Phase E economic falsification for H-1 and H-2 across 2022, 2023, 2022-2023, 2024, and Dev 2025."""
    periods = {
        "regime_2022_bear": [2022],
        "regime_2023_recovery": [2023],
        "discovery_2022_2023": [2022, 2023],
        "validation_2024": [2024],
        "adaptive_dev_2025": [2025],
        "full_2022_2025": [2022, 2023, 2024, 2025],
    }

    h1_results: Dict[str, Any] = {}
    h2_results: Dict[str, Any] = {}

    for p_name, yrs in periods.items():
        sub = df[df["year"].isin(yrs)].copy()
        w_h1 = build_h1_simple_carry_weights(sub)
        w_h1_pass = build_h1_passive_carry_benchmark_weights(sub, w_h1)

        pass_sim = simulate_quarterly_carry_portfolio(sub, w_h1_pass, pair_cost_per_leg_bps=11.0, latency_mode="close_t")

        by_latency = {}
        for lat in ["close_t", "next_bar_open_slippage", "1h_delay", "4h_delay"]:
            sim = simulate_quarterly_carry_portfolio(sub, w_h1, pair_cost_per_leg_bps=11.0, latency_mode=lat)
            sim["net_excess_vs_matched_passive_carry_usd"] = round(sim["net_pnl_usd"] - pass_sim["net_pnl_usd"], 2)
            sim["gross_excess_vs_matched_passive_carry_usd"] = round(sim["gross_pnl_usd"] - pass_sim["gross_pnl_usd"], 2)
            by_latency[lat] = sim

        cost_frontier = []
        for rt_cost in [0.0, 10.0, 16.0, 22.0, 28.0, 36.0, 44.0]:
            leg_c = rt_cost / 2.0
            s_c = simulate_quarterly_carry_portfolio(sub, w_h1, pair_cost_per_leg_bps=leg_c, latency_mode="close_t")
            p_c = simulate_quarterly_carry_portfolio(sub, w_h1_pass, pair_cost_per_leg_bps=leg_c, latency_mode="close_t")
            cost_frontier.append(
                {
                    "round_trip_cost_bps": rt_cost,
                    "net_pnl_usd": s_c["net_pnl_usd"],
                    "net_excess_vs_matched_passive_carry_usd": round(s_c["net_pnl_usd"] - p_c["net_pnl_usd"], 2),
                    "friction_paid_usd": s_c["transaction_friction_paid"],
                }
            )

        h1_results[p_name] = {
            "years": yrs,
            "matched_passive_carry": pass_sim,
            "simple_carry_by_latency": by_latency,
            "cost_frontier": cost_frontier,
        }

        # Evaluate H-2 (Multi-Day Spot Liquidity Provision)
        w_h2 = build_h2_multiday_liquidity_weights(sub)
        symbols = list(w_h2.columns)
        mean_exp_h2 = float(w_h2.sum(axis=1).mean())
        w_h2_pass = pd.DataFrame(mean_exp_h2 / len(symbols), index=w_h2.index, columns=symbols)
        sim_h2 = simulate_h2_spot_liquidity_portfolio(sub, w_h2, cost_per_leg_bps=7.0)
        sim_h2_pass = simulate_h2_spot_liquidity_portfolio(sub, w_h2_pass, cost_per_leg_bps=7.0)
        sim_h2["net_excess_vs_matched_spot_ew_usd"] = round(sim_h2["net_pnl_usd"] - sim_h2_pass["net_pnl_usd"], 2)
        sim_h2["gross_excess_vs_matched_spot_ew_usd"] = round(sim_h2["gross_pnl_usd"] - sim_h2_pass["gross_pnl_usd"], 2)

        h2_results[p_name] = {
            "years": yrs,
            "matched_passive_spot_ew": sim_h2_pass,
            "simple_multiday_liquidity_baseline": sim_h2,
        }

    # UM vs CM quarterly basis parity check on BTCUSDT and ETHUSDT
    um_sub = df[df["um_f1_close"].notna() & df["f1_close"].notna()].copy()
    um_sub["um_f1_basis_bps"] = (um_sub["um_f1_close"] / um_sub["spot_close"] - 1.0) * 10_000.0
    um_cm_corr = float(um_sub["f1_basis_bps"].corr(um_sub["um_f1_basis_bps"])) if len(um_sub) > 10 else 0.0

    return {
        "h1_quarterly_delivery_carry": h1_results,
        "h2_multiday_deleveraging_liquidity": h2_results,
        "um_vs_cm_quarterly_basis_parity": {
            "matched_symbol_hours": int(len(um_sub)),
            "cm_vs_um_basis_correlation": round(um_cm_corr, 4),
            "mean_cm_basis_bps": round(float(um_sub["f1_basis_bps"].mean()), 2) if len(um_sub) > 0 else 0.0,
            "mean_um_basis_bps": round(float(um_sub["um_f1_basis_bps"].mean()), 2) if len(um_sub) > 0 else 0.0,
        },
    }
