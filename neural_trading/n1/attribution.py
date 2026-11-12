"""
neural_trading/n1/attribution.py

Phase N1.1: Exact portfolio return reconciliation, Carino geometrically linked
Brinson attribution, paired decision ledger inspection, H1/H2 causal utility
ablations, and PIT downside/risk-budget feasibility diagnostics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple
import numpy as np
import pandas as pd
import torch

from neural_trading.n1.model import CrossSectionalMarketPolicy
from neural_trading.n1.experiment import (
    ASSET_FEATURE_COLS,
    enforce_external_hard_risk,
    simulate_step_policy,
    train_n1_policy,
)


def trace_detailed_ledger(
    target_weights_seq: np.ndarray,  # (K, N + 1)
    is_hold_seq: np.ndarray,         # (K,) bool
    fwd_ret_seq: np.ndarray,         # (K, N)
    active_seq: np.ndarray,          # (K, N) bool
    horizon_h: int = 12,
    initial_capital: float = 20_000.0,
    cost_per_leg_bps: float = 7.0,
    min_cash: float = 0.05,
    max_asset: float = 0.35,
) -> Dict[str, Any]:
    """
    Runs the exact same sequential portfolio simulation as `simulate_step_policy`
    while returning step-level arrays (`exec_weights`, `gross_step_rets`,
    `net_step_rets`, `step_costs_frac`, `ew_mkt_rets`, `equity_curve`) for
    exact dollar and Carino geometric reconciliation.
    """
    summary = simulate_step_policy(
        target_weights_seq, is_hold_seq, fwd_ret_seq, active_seq,
        horizon_h=horizon_h, initial_capital=initial_capital,
        cost_per_leg_bps=cost_per_leg_bps, min_cash=min_cash, max_asset=max_asset,
    )
    K, N = fwd_ret_seq.shape
    cost_rate = cost_per_leg_bps / 10_000.0

    cap = initial_capital
    w_curr = np.zeros(N + 1, dtype=np.float64)
    w_curr[0] = 1.0

    exec_weights = np.zeros((K, N + 1), dtype=np.float64)
    gross_step_rets = np.zeros(K, dtype=np.float64)
    net_step_rets = np.zeros(K, dtype=np.float64)
    cost_frac_seq = np.zeros(K, dtype=np.float64)
    ew_mkt_rets = np.zeros(K, dtype=np.float64)
    equity_curve = np.zeros(K + 1, dtype=np.float64)
    equity_curve[0] = initial_capital

    for t in range(K):
        act_t = active_seq[t]
        delisted_held = (w_curr[1:] > 1e-5) & (~act_t)
        violates_static = (
            (w_curr[0] < min_cash - 1e-5)
            or np.any(w_curr[1:] > max_asset + 1e-5)
            or np.any(delisted_held)
        )
        if is_hold_seq[t] and t > 0 and not violates_static:
            w_exec = w_curr.copy()
        else:
            if is_hold_seq[t] and t > 0 and violates_static:
                w_exec = enforce_external_hard_risk(w_curr, act_t, min_cash=min_cash, max_asset=max_asset)
            else:
                w_exec = enforce_external_hard_risk(target_weights_seq[t], act_t, min_cash=min_cash, max_asset=max_asset)

        delta_risky = np.abs(w_exec[1:] - w_curr[1:])
        real_leg_mask = (delta_risky * cap) >= 1.0
        delta_clean = np.where(real_leg_mask, delta_risky, 0.0)
        leg_sum = float(np.sum(delta_clean))
        cost_frac = leg_sum * cost_rate

        r_assets = fwd_ret_seq[t] * act_t.astype(np.float64)
        gross_r = float(np.sum(w_exec[1:] * r_assets))
        net_r = (1.0 - cost_frac) * (1.0 + gross_r) - 1.0

        cap = cap * (1.0 + net_r)
        equity_curve[t + 1] = cap
        exec_weights[t] = w_exec
        gross_step_rets[t] = gross_r
        net_step_rets[t] = net_r
        cost_frac_seq[t] = cost_frac
        n_act = max(int(np.sum(act_t)), 1)
        ew_mkt_rets[t] = float(np.sum(r_assets) / n_act)

        y_vec = np.concatenate([[1.0], 1.0 + r_assets])
        w_post = w_exec * y_vec
        w_curr = w_post / max(float(np.sum(w_post)), 1e-12)

    return {
        "summary": summary,
        "exec_weights": exec_weights,
        "gross_step_rets": gross_step_rets,
        "net_step_rets": net_step_rets,
        "cost_frac_seq": cost_frac_seq,
        "ew_mkt_rets": ew_mkt_rets,
        "equity_curve": equity_curve,
    }


def _carino_weights(r_p: np.ndarray, r_b: np.ndarray) -> np.ndarray:
    """
    Computes exact Carino (1999) geometric linking weights k_t such that for any
    additive decomposition of step return differences (r_p[t] - r_b[t]) = sum_j c_{j,t},
    the sum over t of k_t * c_{j,t} equals (R_P - R_B) identically, where
    R_P = prod(1 + r_p) - 1 and R_B = prod(1 + r_b) - 1.
    """
    R_p = float(np.prod(1.0 + r_p) - 1.0)
    R_b = float(np.prod(1.0 + r_b) - 1.0)
    if abs(R_p - R_b) < 1e-12:
        K_tot = 1.0 / (1.0 + R_p)
    else:
        K_tot = (np.log1p(R_p) - np.log1p(R_b)) / (R_p - R_b)

    diff = r_p - r_b
    k_t = np.where(
        np.abs(diff) < 1e-12,
        1.0 / (1.0 + r_p),
        (np.log1p(r_p) - np.log1p(r_b)) / np.where(np.abs(diff) < 1e-12, 1.0, diff),
    )
    return k_t / K_tot


def reconcile_portfolio_and_brinson(
    neural_trace: Dict[str, Any],
    matched_bnh_trace: Dict[str, Any],
    passive_ew_trace: Dict[str, Any],
    fwd_ret_seq: np.ndarray,
    active_seq: np.ndarray,
    initial_capital: float = 20_000.0,
    cost_per_leg_bps: float = 7.0,
) -> Dict[str, Any]:
    """
    Phase A reconciliation:
      1. Direct terminal equity & dollar Net PnL identity between Neural and
         Matched Buy-and-Hold (`Exposure-Matched Passive` row in N1 report).
      2. Exact explanation of why N1's `net_excess_vs_matched_pct` (Arithmetic
         Step-Sum vs Rebalanced Constant-Exposure EW) differs from Direct
         Terminal Net Return Difference vs Matched Buy-and-Hold.
      3. Exact Carino Geometrically-Linked Multi-Period Attribution that sums
         to 100.00% of the terminal compounded return & dollar PnL difference.
    """
    r_p_net = neural_trace["net_step_rets"]
    r_p_gross = neural_trace["gross_step_rets"]
    w_p = neural_trace["exec_weights"]
    E_p = np.sum(w_p[:, 1:], axis=1)
    E_p_bar = float(np.mean(E_p))

    r_m_net = matched_bnh_trace["net_step_rets"]
    r_m_gross = matched_bnh_trace["gross_step_rets"]
    w_m = matched_bnh_trace["exec_weights"]
    E_m = np.sum(w_m[:, 1:], axis=1)
    E_m_bar = float(np.mean(E_m))

    ew_mkt = neural_trace["ew_mkt_rets"]
    K = len(ew_mkt)
    cost_rate = cost_per_leg_bps / 10_000.0

    # Synthetic constant-exposure step-rebalanced EW used inside simulate_step_policy
    synth_gross_step = E_p_bar * ew_mkt
    synth_net_step = synth_gross_step.copy()
    if K > 0:
        synth_net_step[0] -= E_p_bar * cost_rate

    # Step-level Brinson vs synthetic constant-exposure EW
    step_timing_vs_ebar = (E_p - E_p_bar) * ew_mkt
    step_sel_vs_ew = r_p_gross - E_p * ew_mkt
    step_cost_diff_vs_synth = (r_p_net - r_p_gross) - (synth_net_step - synth_gross_step)

    # Step-level decomposition of Neural vs Matched Buy-and-Hold (actual table benchmark):
    # At each step t:
    #   r_p_net[t] - r_m_net[t]
    #     = (E_p_bar - E_m_bar) * ew_mkt[t]                          [1. Mean Exposure / Market Beta Gap]
    #     + ((E_p[t] - E_p_bar) - (E_m[t] - E_m_bar)) * ew_mkt[t]    [2. Dynamic Timing vs B&H Exposure Drift]
    #     + (r_p_gross[t] - E_p[t] * ew_mkt[t])                      [3. Neural Cross-Sectional Selection vs EW]
    #     - (r_m_gross[t] - E_m[t] * ew_mkt[t])                      [4. Minus B&H Cross-Sectional Drift vs EW]
    #     + ((r_p_net[t] - r_p_gross[t]) - (r_m_net[t] - r_m_gross[t])) [5. Net Transaction Cost Drag Diff]
    c1_mean_exp_gap = (E_p_bar - E_m_bar) * ew_mkt
    c2_dyn_timing_vs_bnh = ((E_p - E_p_bar) - (E_m - E_m_bar)) * ew_mkt
    c3_neural_xs_sel = r_p_gross - E_p * ew_mkt
    c4_bnh_xs_drift = -(r_m_gross - E_m * ew_mkt)
    c5_cost_drag_diff = (r_p_net - r_p_gross) - (r_m_net - r_m_gross)

    # Verify step-by-step identity
    step_recon_err = float(np.max(np.abs(
        (r_p_net - r_m_net) - (c1_mean_exp_gap + c2_dyn_timing_vs_bnh + c3_neural_xs_sel + c4_bnh_xs_drift + c5_cost_drag_diff)
    )))

    # Carino geometric weights linking step differences to exact terminal return difference
    k_bnh = _carino_weights(r_p_net, r_m_net)
    carino_c1_pct = float(np.sum(k_bnh * c1_mean_exp_gap) * 100.0)
    carino_c2_pct = float(np.sum(k_bnh * c2_dyn_timing_vs_bnh) * 100.0)
    carino_c3_pct = float(np.sum(k_bnh * c3_neural_xs_sel) * 100.0)
    carino_c4_pct = float(np.sum(k_bnh * c4_bnh_xs_drift) * 100.0)
    carino_c5_pct = float(np.sum(k_bnh * c5_cost_drag_diff) * 100.0)
    carino_total_pct = carino_c1_pct + carino_c2_pct + carino_c3_pct + carino_c4_pct + carino_c5_pct

    # Also compute Carino geometric decomposition of Neural Net Return vs 0% Cash (Total Return Breakdown):
    # r_p_net[t] = E_p_bar * ew_mkt[t] + (E_p[t] - E_p_bar) * ew_mkt[t] + (r_p_gross[t] - E_p[t] * ew_mkt[t]) + (r_p_net[t] - r_p_gross[t])
    k_zero = _carino_weights(r_p_net, np.zeros_like(r_p_net))
    tot_beta_pct = float(np.sum(k_zero * (E_p_bar * ew_mkt)) * 100.0)
    tot_timing_pct = float(np.sum(k_zero * step_timing_vs_ebar) * 100.0)
    tot_xs_sel_pct = float(np.sum(k_zero * step_sel_vs_ew) * 100.0)
    tot_cost_pct = float(np.sum(k_zero * (r_p_net - r_p_gross)) * 100.0)

    # Also compute Costed Constant-Exposure Rebalanced EW (rebalanced at 6% deadband)
    w_rebal_ew = np.zeros((K, active_seq.shape[1] + 1), dtype=np.float64)
    hold_rebal_ew = np.zeros(K, dtype=bool)
    for t in range(K):
        act = active_seq[t]
        n_act = max(int(np.sum(act)), 1)
        w_rebal_ew[t, 0] = 1.0 - E_p_bar
        w_rebal_ew[t, 1:] = np.where(act, E_p_bar / n_act, 0.0)
    rebal_ew_sim = simulate_step_policy(
        w_rebal_ew, hold_rebal_ew, fwd_ret_seq, active_seq,
        initial_capital=initial_capital, cost_per_leg_bps=cost_per_leg_bps,
    )

    # Bisection-calibrated Buy-and-Hold whose realized time-average risky exposure equals E_p_bar
    lo, hi = 0.05, 0.95
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        w_try = np.zeros((K, active_seq.shape[1] + 1), dtype=np.float64)
        hold_try = np.ones(K, dtype=bool)
        hold_try[0] = False
        for t in range(K):
            act = active_seq[t]
            n_act = max(int(np.sum(act)), 1)
            w_try[t, 0] = mid
            w_try[t, 1:] = np.where(act, (1.0 - mid) / n_act, 0.0)
            if t > 0 and not np.array_equal(active_seq[t], active_seq[t - 1]):
                hold_try[t] = False
        sim_try = simulate_step_policy(
            w_try, hold_try, fwd_ret_seq, active_seq,
            initial_capital=initial_capital, cost_per_leg_bps=cost_per_leg_bps,
        )
        if sim_try["risk_exposure_pct"] / 100.0 > E_p_bar:
            lo = mid
        else:
            hi = mid

    ns = neural_trace["summary"]
    ms = matched_bnh_trace["summary"]
    ps = passive_ew_trace["summary"]

    direct_pnl_diff_usd = round(ns["net_pnl_usd"] - ms["net_pnl_usd"], 2)
    direct_ret_diff_pct = round(ns["net_return_pct"] - ms["net_return_pct"], 2)

    return {
        "initial_capital_usd": initial_capital,
        "neural_final_equity_usd": ns["final_equity"],
        "neural_gross_pnl_usd": ns["gross_pnl_usd"],
        "neural_net_pnl_usd": ns["net_pnl_usd"],
        "neural_gross_return_pct": ns["gross_return_pct"],
        "neural_net_return_pct": ns["net_return_pct"],
        "neural_avg_risk_exposure_pct": ns["risk_exposure_pct"],
        "matched_bnh_initial_cash_pct": round(100.0 - E_p_bar * 100.0, 2),
        "matched_bnh_realized_risk_exposure_pct": ms["risk_exposure_pct"],
        "matched_bnh_final_equity_usd": ms["final_equity"],
        "matched_bnh_gross_pnl_usd": ms["gross_pnl_usd"],
        "matched_bnh_net_pnl_usd": ms["net_pnl_usd"],
        "matched_bnh_gross_return_pct": ms["gross_return_pct"],
        "matched_bnh_net_return_pct": ms["net_return_pct"],
        "direct_net_pnl_diff_vs_matched_bnh_usd": direct_pnl_diff_usd,
        "direct_net_return_diff_vs_matched_bnh_pct": direct_ret_diff_pct,
        "passive_ew_net_pnl_usd": ps["net_pnl_usd"],
        "passive_ew_net_return_pct": ps["net_return_pct"],
        "direct_net_pnl_diff_vs_passive_ew_usd": round(ns["net_pnl_usd"] - ps["net_pnl_usd"], 2),
        "direct_net_return_diff_vs_passive_ew_pct": round(ns["net_return_pct"] - ps["net_return_pct"], 2),
        "time_avg_calibrated_bnh": {
            "initial_cash_pct": round(mid * 100.0, 2),
            "realized_risk_exposure_pct": sim_try["risk_exposure_pct"],
            "net_pnl_usd": sim_try["net_pnl_usd"],
            "net_return_pct": sim_try["net_return_pct"],
            "direct_neural_minus_calibrated_bnh_usd": round(ns["net_pnl_usd"] - sim_try["net_pnl_usd"], 2),
            "direct_neural_minus_calibrated_bnh_pct": round(ns["net_return_pct"] - sim_try["net_return_pct"], 2),
        },
        "costed_step_rebalanced_ew": {
            "realized_risk_exposure_pct": rebal_ew_sim["risk_exposure_pct"],
            "net_pnl_usd": rebal_ew_sim["net_pnl_usd"],
            "net_return_pct": rebal_ew_sim["net_return_pct"],
            "tx_cost_usd": rebal_ew_sim["transaction_cost_usd"],
            "direct_neural_minus_rebal_ew_usd": round(ns["net_pnl_usd"] - rebal_ew_sim["net_pnl_usd"], 2),
            "direct_neural_minus_rebal_ew_pct": round(ns["net_return_pct"] - rebal_ew_sim["net_return_pct"], 2),
        },
        "brinson_arithmetic_step_sum_vs_synth_ew": {
            "definition": "Uncompounded sum of 12h step return differences vs frictionless step-rebalanced constant-exposure EW",
            "timing_step_sum_pct": ns["timing_value_pct"],
            "selection_step_sum_pct": ns["asset_selection_value_pct"],
            "gross_excess_step_sum_pct": ns["gross_excess_vs_matched_pct"],
            "cost_diff_step_sum_pct": round(float(np.sum(step_cost_diff_vs_synth) * 100.0), 2),
            "reported_net_excess_step_sum_pct": ns["net_excess_vs_matched_pct"],
            "synth_ew_compounded_net_return_pct": round(float((np.prod(1.0 + synth_net_step) - 1.0) * 100.0), 2),
            "compounding_interaction_vs_synth_ew_pct": round(
                ns["net_return_pct"]
                - float((np.prod(1.0 + synth_net_step) - 1.0) * 100.0)
                - ns["net_excess_vs_matched_pct"],
                2,
            ),
        },
        "carino_geometric_reconciliation_vs_matched_bnh": {
            "c1_mean_exposure_gap_pct": round(carino_c1_pct, 2),
            "c2_dynamic_timing_vs_bnh_drift_pct": round(carino_c2_pct, 2),
            "c3_neural_xs_selection_vs_ew_pct": round(carino_c3_pct, 2),
            "c4_minus_bnh_xs_drift_vs_ew_pct": round(carino_c4_pct, 2),
            "c5_net_cost_drag_diff_pct": round(carino_c5_pct, 2),
            "sum_of_components_pct": round(carino_total_pct, 2),
            "exact_direct_net_return_diff_pct": direct_ret_diff_pct,
            "step_identity_max_abs_err": step_recon_err,
        },
        "carino_total_neural_return_decomposition": {
            "market_beta_contribution_pct": round(tot_beta_pct, 2),
            "dynamic_timing_contribution_pct": round(tot_timing_pct, 2),
            "cross_sectional_selection_contribution_pct": round(tot_xs_sel_pct, 2),
            "transaction_cost_drag_pct": round(tot_cost_pct, 2),
            "total_neural_net_return_pct": ns["net_return_pct"],
            "market_beta_contribution_usd": round(initial_capital * tot_beta_pct / 100.0, 2),
            "dynamic_timing_contribution_usd": round(initial_capital * tot_timing_pct / 100.0, 2),
            "cross_sectional_selection_contribution_usd": round(initial_capital * tot_xs_sel_pct / 100.0, 2),
            "transaction_cost_drag_usd": round(initial_capital * tot_cost_pct / 100.0, 2),
        },
    }


def evaluate_single_feature_long_only_tilt(
    feat_slice: np.ndarray,      # (K, N) normalized feature
    active_seq: np.ndarray,      # (K, N) bool
    fwd_ret_seq: np.ndarray,     # (K, N)
    target_cash: float = 0.10,
    deadband_oneway: float = 0.06,
    cost_per_leg_bps: float = 7.0,
) -> Dict[str, Any]:
    """
    Constructs a long-only implementable portfolio tilted strictly by a single
    cross-sectional feature (softmax over active assets with temperature 1.0)
    at fixed target cash, subject to external hard-risk constraints and deadband.
    """
    K, N = feat_slice.shape
    w_seq = np.zeros((K, N + 1), dtype=np.float64)
    is_hold = np.zeros(K, dtype=bool)
    w_prev = np.zeros(N + 1, dtype=np.float64)
    w_prev[0] = 1.0

    for t in range(K):
        act = active_seq[t]
        if not np.any(act):
            w_seq[t, 0] = 1.0
            is_hold[t] = True
            continue
        scores = np.where(act, feat_slice[t], -1e9)
        scores = scores - np.max(scores[act])
        probs = np.where(act, np.exp(0.8 * scores), 0.0)
        probs /= max(float(np.sum(probs)), 1e-9)

        w_cand = np.zeros(N + 1, dtype=np.float64)
        w_cand[0] = target_cash
        w_cand[1:] = (1.0 - target_cash) * probs
        w_cand = enforce_external_hard_risk(w_cand, act)

        oneway_to = 0.5 * float(np.sum(np.abs(w_cand[1:] - w_prev[1:])))
        if t > 0 and oneway_to < deadband_oneway and not np.any((w_prev[1:] > 0) & (~act)):
            w_seq[t] = w_prev.copy()
            is_hold[t] = True
        else:
            w_seq[t] = w_cand
            w_prev = w_cand.copy()
            is_hold[t] = False

    return simulate_step_policy(
        w_seq, is_hold, fwd_ret_seq, active_seq, cost_per_leg_bps=cost_per_leg_bps
    )


def compute_fold_feature_diagnostics(
    ax_norm_ev: np.ndarray,      # (K, N, d_a)
    active_ev: np.ndarray,       # (K, N)
    fwd_ret_ev: np.ndarray,      # (K, N)
    neural_weights: np.ndarray,  # (K, N + 1)
    ew_mkt_rets: np.ndarray,     # (K,)
    passive_ew_net_ret_pct: float,
    target_cash: float,
) -> Dict[str, Any]:
    """
    Computes per-feature predictive spread, beta-adjusted log spread, cross-sectional
    IC, correlation with the frozen N1 neural policy's active asset tilts, and
    standalone long-only implementable payoff.
    """
    K, N, d_a = ax_norm_ev.shape
    E_t = np.maximum(np.sum(neural_weights[:, 1:], axis=1, keepdims=True), 1e-8)
    n_act = np.maximum(np.sum(active_ev, axis=1, keepdims=True), 1)
    # Normalized active weight tilt of neural policy relative to equal-weight:
    neural_tilt = (neural_weights[:, 1:] / E_t) - (active_ev.astype(np.float64) / n_act)

    log_ret_ev = np.log1p(np.maximum(fwd_ret_ev, -0.99))
    log_mkt = np.sum(log_ret_ev * active_ev, axis=1, keepdims=True) / n_act
    beta_adj_log_ret = (log_ret_ev - log_mkt) * active_ev

    out: Dict[str, Any] = {}
    for j, col in enumerate(ASSET_FEATURE_COLS):
        f_mat = ax_norm_ev[:, :, j]
        q_raw_spreads = []
        q_beta_log_spreads = []
        ics = []
        tilt_corrs = []

        for t in range(K):
            act = active_ev[t]
            if np.sum(act) < 5:
                continue
            fv = f_mat[t, act]
            rv = fwd_ret_ev[t, act]
            blv = beta_adj_log_ret[t, act]
            tv = neural_tilt[t, act]
            if np.std(fv) < 1e-8:
                continue
            q20, q80 = np.quantile(fv, [0.20, 0.80])
            hi = fv >= q80
            lo = fv <= q20
            if np.any(hi) and np.any(lo):
                q_raw_spreads.append(float(np.mean(rv[hi]) - np.mean(rv[lo])) * 10_000.0)
                q_beta_log_spreads.append(float(np.mean(blv[hi]) - np.mean(blv[lo])) * 10_000.0)
            if np.std(rv) > 1e-8:
                ics.append(float(np.corrcoef(fv, rv)[0, 1]))
            if np.std(tv) > 1e-8:
                tilt_corrs.append(float(np.corrcoef(fv, tv)[0, 1]))

        lo_sim = evaluate_single_feature_long_only_tilt(
            f_mat, active_ev, fwd_ret_ev, target_cash=target_cash, cost_per_leg_bps=7.0
        )
        out[col] = {
            "cross_sectional_predictive_spread_bps": round(float(np.mean(q_raw_spreads)) if q_raw_spreads else 0.0, 2),
            "beta_adjusted_signal_bps": round(float(np.mean(q_beta_log_spreads)) if q_beta_log_spreads else 0.0, 2),
            "cross_sectional_ic_mean": round(float(np.mean(ics)) if ics else 0.0, 4),
            "neural_weight_tilt_corr": round(float(np.mean(tilt_corrs)) if tilt_corrs else 0.0, 4),
            "long_only_implementable_gross_ret_pct": lo_sim["gross_return_pct"],
            "long_only_implementable_net_ret_pct": lo_sim["net_return_pct"],
            "long_only_excess_vs_passive_ew_pct": round(lo_sim["net_return_pct"] - passive_ew_net_ret_pct, 2),
            "turnover_required_ann": lo_sim["annualized_turnover"],
            "realized_execution_cost_usd": lo_sim["transaction_cost_usd"],
            "long_only_selection_step_sum_pct": lo_sim["asset_selection_value_pct"],
        }
    return out


def analyze_policy_allocation_and_downside(
    neural_trace: Dict[str, Any],
    fwd_ret_ev: np.ndarray,
    active_ev: np.ndarray,
    symbols: Sequence[str],
    timestamps_ev: pd.DatetimeIndex,
) -> Dict[str, Any]:
    """
    Phase D diagnostics:
      - Cash & total risky exposure distribution over time.
      - Asset concentration (HHI, effective N), mean weights, and per-asset
        selection contribution.
      - Pure unit-exposure (100% risky normalized) cross-sectional return vs
        unit-exposure active equal-weight return (completely removing total
        exposure / market beta level).
      - Drawdown episodes and winning vs losing selection steps.
    """
    w = neural_trace["exec_weights"]  # (K, N + 1)
    cash_w = w[:, 0]
    asset_w = w[:, 1:]
    E_t = np.sum(asset_w, axis=1)
    K, N = asset_w.shape
    ew_mkt = neural_trace["ew_mkt_rets"]

    # Normalized within-risky portfolio weights p_{t,i} = w_{t,i} / E_t
    p_t = asset_w / np.maximum(E_t[:, None], 1e-8)
    hhi_t = np.sum(p_t ** 2, axis=1)
    neff_t = 1.0 / np.maximum(hhi_t, 1e-8)
    n_act_t = np.maximum(np.sum(active_ev, axis=1), 1)
    ew_p_t = active_ev.astype(np.float64) / n_act_t[:, None]

    # Unit-exposure (beta-normalized) cross-sectional step return:
    # sum_i p_{t,i} r_{t,i} - R_{m,t}
    r_act = fwd_ret_ev * active_ev.astype(np.float64)
    unit_xs_ret_t = np.sum(p_t * r_act, axis=1)
    unit_sel_diff_t = unit_xs_ret_t - ew_mkt

    # Per-symbol selection contribution (in bps of total portfolio per step, summed over fold)
    sym_contrib = {}
    for i, sym in enumerate(symbols):
        act_steps = int(np.sum(active_ev[:, i]))
        if act_steps == 0:
            continue
        mean_w = float(np.mean(asset_w[:, i]))
        mean_p = float(np.mean(p_t[active_ev[:, i], i]))
        mean_ew_p = float(np.mean(ew_p_t[active_ev[:, i], i]))
        # Step selection contribution of symbol i: (w_{t,i} - E_t * ew_p_{t,i}) * (r_{t,i} - R_{m,t})
        sel_i = (asset_w[:, i] - E_t * ew_p_t[:, i]) * (r_act[:, i] - ew_mkt) * active_ev[:, i]
        sym_contrib[sym] = {
            "active_steps": act_steps,
            "mean_portfolio_weight_pct": round(mean_w * 100.0, 2),
            "mean_within_risky_share_pct": round(mean_p * 100.0, 2),
            "equal_weight_share_pct": round(mean_ew_p * 100.0, 2),
            "active_overweight_pct": round((mean_p - mean_ew_p) * 100.0, 2),
            "cum_selection_contrib_pct": round(float(np.sum(sel_i) * 100.0), 2),
            "symbol_buy_and_hold_ret_pct": round(float((np.prod(1.0 + r_act[:, i]) - 1.0) * 100.0), 2),
        }

    # Block-bootstrap CI on unit-exposure cross-sectional selection return (annualized %)
    rng = np.random.default_rng(42)
    b_len = 4
    n_b = int(np.ceil(K / b_len))
    starts = rng.integers(0, max(1, K - b_len + 1), size=(400, n_b))
    idx = (starts[:, :, None] + np.arange(b_len)[None, None, :]).reshape(400, -1)[:, :K]
    boot_unit_sel = np.mean(unit_sel_diff_t[idx], axis=1) * 730.0 * 100.0
    ci_lo, ci_hi = np.percentile(boot_unit_sel, [2.5, 97.5])
    prob_pos_sel = float(np.mean(boot_unit_sel > 0.0))

    pos_steps = unit_sel_diff_t > 0
    neg_steps = unit_sel_diff_t < 0

    # Exposure during worst market drawdown steps (when ew_mkt < -2% in 12h)
    crash_steps = ew_mkt < -0.02
    calm_steps = ew_mkt >= 0.0

    return {
        "cash_weight_stats_pct": {
            "min": round(float(np.min(cash_w) * 100.0), 2),
            "p25": round(float(np.percentile(cash_w, 25) * 100.0), 2),
            "median": round(float(np.median(cash_w) * 100.0), 2),
            "mean": round(float(np.mean(cash_w) * 100.0), 2),
            "p75": round(float(np.percentile(cash_w, 75) * 100.0), 2),
            "max": round(float(np.max(cash_w) * 100.0), 2),
        },
        "risky_exposure_stats_pct": {
            "min": round(float(np.min(E_t) * 100.0), 2),
            "median": round(float(np.median(E_t) * 100.0), 2),
            "mean": round(float(np.mean(E_t) * 100.0), 2),
            "max": round(float(np.max(E_t) * 100.0), 2),
            "mean_during_market_drop_gt_2pct": round(float(np.mean(E_t[crash_steps]) * 100.0), 2) if np.any(crash_steps) else 0.0,
            "mean_during_positive_market_steps": round(float(np.mean(E_t[calm_steps]) * 100.0), 2) if np.any(calm_steps) else 0.0,
        },
        "concentration_stats": {
            "mean_hhi": round(float(np.mean(hhi_t)), 4),
            "mean_effective_n_assets": round(float(np.mean(neff_t)), 2),
            "equal_weight_n_assets": round(float(np.mean(n_act_t)), 2),
            "mean_max_single_asset_weight_pct": round(float(np.mean(np.max(asset_w, axis=1)) * 100.0), 2),
        },
        "unit_exposure_cross_sectional_selection": {
            "unit_neural_cum_return_pct": round(float((np.prod(1.0 + unit_xs_ret_t) - 1.0) * 100.0), 2),
            "unit_ew_mkt_cum_return_pct": round(float((np.prod(1.0 + ew_mkt) - 1.0) * 100.0), 2),
            "unit_compounded_selection_spread_pct": round(
                float(((np.prod(1.0 + unit_xs_ret_t) - 1.0) - (np.prod(1.0 + ew_mkt) - 1.0)) * 100.0), 2
            ),
            "unit_step_sum_selection_spread_pct": round(float(np.sum(unit_sel_diff_t) * 100.0), 2),
            "selection_step_hit_rate_pct": round(float(np.mean(pos_steps) * 100.0), 2),
            "mean_winning_step_sel_bps": round(float(np.mean(unit_sel_diff_t[pos_steps]) * 10_000.0), 2) if np.any(pos_steps) else 0.0,
            "mean_losing_step_sel_bps": round(float(np.mean(unit_sel_diff_t[neg_steps]) * 10_000.0), 2) if np.any(neg_steps) else 0.0,
            "boot_ci95_ann_sel_pct": [round(float(ci_lo), 2), round(float(ci_hi), 2)],
            "prob_positive_selection": round(prob_pos_sel, 3),
        },
        "per_symbol_attribution": sym_contrib,
    }
