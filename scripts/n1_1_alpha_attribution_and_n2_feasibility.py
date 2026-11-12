"""
scripts/n1_1_alpha_attribution_and_n2_feasibility.py

Executes the complete N1.1 Cross-Sectional Alpha Attribution & Neural
Risk-Budget Feasibility audit across Phases A, B, C, D, and E.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import torch

from neural_trading.n1.pit_dataset import (
    SPOT_SYMBOLS, DEPTH_SYMBOLS, build_spot_panel, build_bookdepth_hourly,
)
from neural_trading.n1.information_tests import compute_h1_features
from neural_trading.n1.model import CrossSectionalMarketPolicy
from neural_trading.n1.experiment import (
    ASSET_FEATURE_COLS,
    build_step_tensors,
    normalize_causal_train,
    simulate_step_policy,
    train_n1_policy,
    enforce_external_hard_risk,
)
from neural_trading.n1.attribution import (
    trace_detailed_ledger,
    reconcile_portfolio_and_brinson,
    compute_fold_feature_diagnostics,
    analyze_policy_allocation_and_downside,
)
from scripts.n1_run_phase_f_economic_pilot import (
    evaluate_neural_sequence,
    build_passive_weights,
    build_non_neural_baseline_weights,
)

RAW_ROOT = REPO / "data" / "historical" / "neural_n1" / "raw"
CACHE_DIR = REPO / "data" / "historical" / "neural_n1" / "pit_cache"
OUT_DIR = REPO / "research" / "neural_n1"


def evaluate_causal_pit_risk_budget_overlay(
    w_neural: np.ndarray,
    hold_neural: np.ndarray,
    market_x_raw: np.ndarray,
    fwd_ret_ev: np.ndarray,
    active_ev: np.ndarray,
    ew_mkt_hist: np.ndarray,  # full series of 12h equal-weight market returns up to ev_sl
    ev_start_idx: int,
    deadband_oneway: float = 0.06,
    cost_per_leg_bps: float = 7.0,
) -> Dict[str, Any]:
    """
    Tests whether strictly causal PIT market-regime information (trailing 14d
    market drawdown, 72h market trend, 24h market breadth, and 24h Parkinson
    volatility) contains actionable risk-budgeting value when combined with N1's
    cross-sectional asset weights p_{t,i} = w_{t,i} / E_t.
    """
    K, N = fwd_ret_ev.shape
    w_rb = np.zeros((K, N + 1), dtype=np.float64)
    is_hold = np.zeros(K, dtype=bool)
    w_prev = np.zeros(N + 1, dtype=np.float64)
    w_prev[0] = 1.0

    # Compute strictly causal trailing 28-step (14-day) market return and drawdown from ew_mkt_hist
    cum_mkt = np.cumprod(1.0 + ew_mkt_hist)
    for t in range(K):
        g_idx = ev_start_idx + t
        act = active_ev[t]
        if not np.any(act):
            w_rb[t, 0] = 1.0
            is_hold[t] = True
            continue

        # Strictly causal window [g_idx - 28 .. g_idx - 1] (completed prior 14 days)
        lo_i = max(0, g_idx - 28)
        if g_idx > lo_i:
            win_eq = cum_mkt[lo_i:g_idx]
            peak_14d = float(np.max(win_eq))
            curr_eq = float(win_eq[-1])
            dd_14d = (curr_eq - peak_14d) / max(peak_14d, 1e-9)  # <= 0
            ret_14d = (curr_eq / max(float(win_eq[0]), 1e-9)) - 1.0
            vol_14d = float(np.std(ew_mkt_hist[lo_i:g_idx])) * np.sqrt(730.0)
        else:
            dd_14d = 0.0
            ret_14d = 0.0
            vol_14d = 0.50

        # Extract causal market_x at step t:
        # market_x columns: [breadth-0.5, disp_24h, trend_72h, pvol_24h, bd_avail, imb1, imb5, slope, thin]
        breadth_centered = float(market_x_raw[g_idx, 0])
        trend_72h = float(market_x_raw[g_idx, 2])

        # Simple, parameter-free PIT Volatility + Drawdown Target Risk Budget:
        # Target annualized vol = 45%, scaled down when 14d drawdown exceeds -8% or 72h trend < -3%
        vol_scalar = np.clip(0.45 / max(vol_14d, 0.25), 0.20, 0.95)
        dd_scalar = np.clip(1.0 + 3.5 * min(0.0, dd_14d + 0.05), 0.15, 1.0)
        trend_scalar = 0.70 if (trend_72h < -0.03 and breadth_centered < -0.15) else 1.0
        target_exp = float(np.clip(vol_scalar * dd_scalar * trend_scalar, 0.10, 0.92))

        # Keep N1's exact cross-sectional relative weights p_{t,i}
        asset_w_n1 = w_neural[t, 1:] * act.astype(np.float64)
        s_n1 = float(np.sum(asset_w_n1))
        if s_n1 > 1e-8:
            p_t = asset_w_n1 / s_n1
        else:
            p_t = act.astype(np.float64) / max(int(np.sum(act)), 1)

        w_cand = np.zeros(N + 1, dtype=np.float64)
        w_cand[0] = 1.0 - target_exp
        w_cand[1:] = target_exp * p_t
        w_cand = enforce_external_hard_risk(w_cand, act)

        oneway_to = 0.5 * float(np.sum(np.abs(w_cand[1:] - w_prev[1:])))
        if t > 0 and oneway_to < deadband_oneway and not np.any((w_prev[1:] > 0) & (~act)):
            w_rb[t] = w_prev.copy()
            is_hold[t] = True
        else:
            w_rb[t] = w_cand
            w_prev = w_cand.copy()
            is_hold[t] = False

    return simulate_step_policy(
        w_rb, is_hold, fwd_ret_ev, active_ev, cost_per_leg_bps=cost_per_leg_bps
    )


def main() -> None:
    spot_panel = build_spot_panel(RAW_ROOT, SPOT_SYMBOLS, CACHE_DIR / "spot_panel_1h.parquet")
    h1_feats = compute_h1_features(spot_panel)
    bd_panel = build_bookdepth_hourly(RAW_ROOT, DEPTH_SYMBOLS, CACHE_DIR / "bookdepth_1h.parquet")

    data = build_step_tensors(h1_feats, bd_panel, horizon_h=12)
    ts = data["timestamps"]
    asset_x = data["asset_x"]
    market_x = data["market_x"]
    active_mask = data["active_mask"]
    fwd_ret = data["fwd_ret"]

    # Full-series 12h active equal-weight market return (strictly causal per step)
    n_act_all = np.maximum(np.sum(active_mask, axis=1), 1)
    ew_mkt_all = np.sum(fwd_ret * active_mask, axis=1) / n_act_all

    folds = {
        "Fold1_2022_Bear": ("2018-06-01", "2021-12-31", "2022-01-03", "2022-12-31"),
        "Fold2_2024_Expansion_BookDepth": ("2018-06-01", "2023-12-31", "2024-01-03", "2024-12-31"),
        "Fold3_2025_Adaptive_Comparison": ("2018-06-01", "2024-12-31", "2025-01-03", "2025-12-31"),
    }

    report_data: Dict[str, Any] = {
        "phase_a_reconciliation": {},
        "phase_b_independence_and_eligibility": {},
        "phase_c_information_utility_and_ablations": {},
        "phase_d_allocation_and_risk_budget": {},
    }

    for fold_name, (tr_s, tr_e, ev_s, ev_e) in folds.items():
        tr_idx = np.where((ts >= tr_s) & (ts <= tr_e))[0]
        ev_idx = np.where((ts >= ev_s) & (ts <= ev_e))[0]
        tr_sl = slice(int(tr_idx[0]), int(tr_idx[-1]) + 1)
        ev_sl = slice(int(ev_idx[0]), int(ev_idx[-1]) + 1)

        ax_norm, mx_norm = normalize_causal_train(asset_x, market_x, active_mask, tr_sl)

        # Reproduce exact frozen N1 model (seed=42, epochs=18, lr=1.5e-3)
        model = CrossSectionalMarketPolicy(
            asset_feat_dim=asset_x.shape[-1],
            market_feat_dim=market_x.shape[-1],
            embed_dim=24,
            num_heads=4,
            deadband_oneway=0.06,
        )
        train_n1_policy(
            model,
            ax_norm[tr_sl], mx_norm[tr_sl], active_mask[tr_sl], fwd_ret[tr_sl],
            horizon_h=12, cost_per_leg_bps=7.0, epochs=18, seed=42,
        )

        # Examine raw cash_logit vs asset_logits on evaluation slice
        model.eval()
        with torch.no_grad():
            ax_t = torch.tensor(ax_norm[ev_sl], dtype=torch.float32)
            mx_t = torch.tensor(mx_norm[ev_sl], dtype=torch.float32)
            am_t = torch.tensor(active_mask[ev_sl], dtype=torch.bool)
            wc_t = torch.zeros((len(ev_idx), len(SPOT_SYMBOLS) + 1), dtype=torch.float32)
            wc_t[:, 0] = 0.10
            wc_t[:, 1:] = 0.90 / 13.0
            _, w_cand_raw, step_gate_raw = model(ax_t, mx_t, am_t, wc_t)
            mean_cand_cash_pct = float(w_cand_raw[:, 0].mean().item() * 100.0)
            mean_step_gate = float(step_gate_raw.mean().item())

        w_neural, hold_neural = evaluate_neural_sequence(
            model, ax_norm[ev_sl], mx_norm[ev_sl], active_mask[ev_sl], fwd_ret[ev_sl], deadband_oneway=0.06
        )
        w_pass, hold_pass = build_passive_weights(active_mask[ev_sl], cash_weight=0.05)

        neural_trace = trace_detailed_ledger(
            w_neural, hold_neural, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=7.0
        )
        target_cash = neural_trace["summary"]["average_cash_pct"] / 100.0
        w_match, hold_match = build_passive_weights(active_mask[ev_sl], cash_weight=target_cash)
        matched_trace = trace_detailed_ledger(
            w_match, hold_match, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=7.0
        )
        passive_trace = trace_detailed_ledger(
            w_pass, hold_pass, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=7.0
        )

        # Phase A: Portfolio Return Reconciliation & Carino/Brinson Attribution
        recon = reconcile_portfolio_and_brinson(
            neural_trace, matched_trace, passive_trace, fwd_ret[ev_sl], active_mask[ev_sl]
        )
        report_data["phase_a_reconciliation"][fold_name] = recon

        # Phase B: Research Leakage & Data Eligibility Audit
        act_tr = active_mask[tr_sl]
        act_ev = active_mask[ev_sl]
        bd_avail_tr = float(np.mean(market_x[tr_sl, 4]))
        bd_avail_ev = float(np.mean(market_x[ev_sl, 4]))
        eos_idx = SPOT_SYMBOLS.index("EOSUSDT")
        sol_idx = SPOT_SYMBOLS.index("SOLUSDT")
        doge_idx = SPOT_SYMBOLS.index("DOGEUSDT")

        report_data["phase_b_independence_and_eligibility"][fold_name] = {
            "train_window": f"{ts[tr_sl][0].isoformat()} .. {ts[tr_sl][-1].isoformat()}",
            "eval_window": f"{ts[ev_sl][0].isoformat()} .. {ts[ev_sl][-1].isoformat()}",
            "purge_gap_hours": round(float((ts[ev_sl][0] - ts[tr_sl][-1]).total_seconds() / 3600.0), 1),
            "train_steps": int(len(tr_idx)),
            "eval_steps": int(len(ev_idx)),
            "in_phase_d_2018_2024_discovery_window": bool(ts[ev_sl][-1] <= pd.Timestamp("2024-12-31 23:59:59+00:00")),
            "epistemic_classification": (
                "ADAPTIVE_DEVELOPMENT_VALIDATION (Inside 2018-2024 Phase D feature/horizon discovery sample)"
                if ts[ev_sl][-1] <= pd.Timestamp("2024-12-31 23:59:59+00:00")
                else "SEMI_ADAPTIVE_HOLDOUT_COMPARISON (Outside 2018-2024 Phase D discovery, but post N0-N0.3 2025 architectural iterations)"
            ),
            "active_symbols_train_min_max": [int(np.min(np.sum(act_tr, axis=1))), int(np.max(np.sum(act_tr, axis=1)))],
            "active_symbols_eval_min_max": [int(np.min(np.sum(act_ev, axis=1))), int(np.max(np.sum(act_ev, axis=1)))],
            "eos_active_eval_steps": int(np.sum(act_ev[:, eos_idx])),
            "eos_max_weight_when_inactive": float(np.max(neural_trace["exec_weights"][~act_ev[:, eos_idx], eos_idx + 1])) if np.any(~act_ev[:, eos_idx]) else 0.0,
            "sol_active_train_steps": int(np.sum(act_tr[:, sol_idx])),
            "doge_active_train_steps": int(np.sum(act_tr[:, doge_idx])),
            "h2_bookdepth_avail_train_frac": round(bd_avail_tr, 4),
            "h2_bookdepth_avail_eval_frac": round(bd_avail_ev, 4),
            "h2_features_zero_masked_in_eval": bool(bd_avail_ev == 0.0),
        }

        # Phase C: Feature Diagnostics + Frozen Zero-Mask Counterfactuals + Bounded Retrained Ablations
        feat_diag = compute_fold_feature_diagnostics(
            ax_norm[ev_sl], active_mask[ev_sl], fwd_ret[ev_sl],
            neural_trace["exec_weights"], neural_trace["ew_mkt_rets"],
            passive_trace["summary"]["net_return_pct"], target_cash=target_cash,
        )

        # Frozen-model zero-masking counterfactuals for priority features & groups
        idx_ts = ASSET_FEATURE_COLS.index("H1_trade_size_z168h")
        idx_xsret = ASSET_FEATURE_COLS.index("H1_xs_rel_ret_24h")
        idx_xsimb = ASSET_FEATURE_COLS.index("H1_xs_rel_imb_24h")
        idx_pvol = ASSET_FEATURE_COLS.index("H1_parkinson_vol_24h")
        h1_flow_vol_indices = [3, 4, 5, 6, 7, 8, 9]  # all H1 non-return features

        frozen_counterfactuals: Dict[str, Any] = {}
        mask_specs = {
            "drop_H1_trade_size_z168h": ([idx_ts], []),
            "drop_H1_xs_rel_ret_24h": ([idx_xsret], []),
            "drop_H1_xs_rel_imb_24h": ([idx_xsimb], []),
            "drop_H1_parkinson_vol_24h": ([idx_pvol], [3]),
            "drop_all_H1_flow_size_vol": (h1_flow_vol_indices, [0, 1, 3]),
            "drop_all_H2_bookDepth": ([], [4, 5, 6, 7, 8]),
        }
        base_net_pnl = neural_trace["summary"]["net_pnl_usd"]
        base_net_ret = neural_trace["summary"]["net_return_pct"]
        base_sel_pct = neural_trace["summary"]["asset_selection_value_pct"]

        for cf_name, (a_cols, m_cols) in mask_specs.items():
            ax_cf = ax_norm[ev_sl].copy()
            mx_cf = mx_norm[ev_sl].copy()
            if a_cols:
                ax_cf[:, :, a_cols] = 0.0
            if m_cols:
                mx_cf[:, m_cols] = 0.0
            w_cf, hold_cf = evaluate_neural_sequence(
                model, ax_cf, mx_cf, active_mask[ev_sl], fwd_ret[ev_sl], deadband_oneway=0.06
            )
            sim_cf = simulate_step_policy(w_cf, hold_cf, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=7.0)
            frozen_counterfactuals[cf_name] = {
                "ablation_net_pnl_usd": sim_cf["net_pnl_usd"],
                "ablation_net_return_pct": sim_cf["net_return_pct"],
                "marginal_value_of_dropped_info_usd": round(base_net_pnl - sim_cf["net_pnl_usd"], 2),
                "marginal_value_of_dropped_info_pct": round(base_net_ret - sim_cf["net_return_pct"], 2),
                "marginal_selection_value_pct": round(base_sel_pct - sim_cf["asset_selection_value_pct"], 2),
            }

        # Bounded Retrained Ablations (identical seed=42, epochs=18, lr=1.5e-3, simulator)
        retrained_ablations: Dict[str, Any] = {}
        for ab_name, (a_cols, m_cols) in mask_specs.items():
            ax_ab = ax_norm.copy()
            mx_ab = mx_norm.copy()
            if a_cols:
                ax_ab[:, :, a_cols] = 0.0
            if m_cols:
                mx_ab[:, m_cols] = 0.0
            m_ab = CrossSectionalMarketPolicy(
                asset_feat_dim=asset_x.shape[-1],
                market_feat_dim=market_x.shape[-1],
                embed_dim=24,
                num_heads=4,
                deadband_oneway=0.06,
            )
            train_n1_policy(
                m_ab,
                ax_ab[tr_sl], mx_ab[tr_sl], active_mask[tr_sl], fwd_ret[tr_sl],
                horizon_h=12, cost_per_leg_bps=7.0, epochs=18, seed=42,
            )
            w_ab, hold_ab = evaluate_neural_sequence(
                m_ab, ax_ab[ev_sl], mx_ab[ev_sl], active_mask[ev_sl], fwd_ret[ev_sl], deadband_oneway=0.06
            )
            sim_ab = simulate_step_policy(w_ab, hold_ab, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=7.0)
            retrained_ablations[ab_name] = {
                "retrained_net_pnl_usd": sim_ab["net_pnl_usd"],
                "retrained_net_return_pct": sim_ab["net_return_pct"],
                "retrained_sharpe": sim_ab["annualized_sharpe"],
                "retrained_selection_pct": sim_ab["asset_selection_value_pct"],
                "incremental_value_of_dropped_info_usd": round(base_net_pnl - sim_ab["net_pnl_usd"], 2),
                "incremental_value_of_dropped_info_pct": round(base_net_ret - sim_ab["net_return_pct"], 2),
                "incremental_selection_value_pct": round(base_sel_pct - sim_ab["asset_selection_value_pct"], 2),
            }

        report_data["phase_c_information_utility_and_ablations"][fold_name] = {
            "feature_diagnostics": feat_diag,
            "frozen_zero_mask_counterfactuals": frozen_counterfactuals,
            "bounded_retrained_ablations": retrained_ablations,
        }

        # Phase D: Allocation Time-Series, Unit-Exposure Selection, and Causal PIT Risk-Budget Feasibility
        alloc_diag = analyze_policy_allocation_and_downside(
            neural_trace, fwd_ret[ev_sl], active_mask[ev_sl], SPOT_SYMBOLS, ts[ev_sl]
        )
        rb_overlay_sim = evaluate_causal_pit_risk_budget_overlay(
            w_neural, hold_neural, market_x, fwd_ret[ev_sl], active_mask[ev_sl],
            ew_mkt_all, ev_start_idx=int(ev_idx[0]), cost_per_leg_bps=7.0,
        )
        alloc_diag["softmax_structural_bias_diagnostics"] = {
            "active_universe_cardinality_N": int(np.max(np.sum(act_ev, axis=1))),
            "uniform_logit_cash_prior_pct": round(100.0 / (1.0 + float(np.mean(np.sum(act_ev, axis=1)))), 2),
            "unconstrained_candidate_mean_cash_pct": round(mean_cand_cash_pct, 2),
            "mean_step_gate_inertia": round(mean_step_gate, 4),
            "executed_mean_cash_pct": neural_trace["summary"]["average_cash_pct"],
        }
        alloc_diag["causal_pit_risk_budget_overlay_test"] = {
            "net_pnl_usd": rb_overlay_sim["net_pnl_usd"],
            "net_return_pct": rb_overlay_sim["net_return_pct"],
            "annualized_sharpe": rb_overlay_sim["annualized_sharpe"],
            "max_drawdown_pct": rb_overlay_sim["max_drawdown_pct"],
            "risk_exposure_pct": rb_overlay_sim["risk_exposure_pct"],
            "annualized_turnover": rb_overlay_sim["annualized_turnover"],
            "transaction_cost_usd": rb_overlay_sim["transaction_cost_usd"],
            "timing_value_pct": rb_overlay_sim["timing_value_pct"],
            "asset_selection_value_pct": rb_overlay_sim["asset_selection_value_pct"],
            "delta_net_pnl_vs_n1_usd": round(rb_overlay_sim["net_pnl_usd"] - base_net_pnl, 2),
            "delta_max_dd_vs_n1_pct": round(rb_overlay_sim["max_drawdown_pct"] - neural_trace["summary"]["max_drawdown_pct"], 2),
        }
        report_data["phase_d_allocation_and_risk_budget"][fold_name] = alloc_diag

        print(f"\n================ {fold_name} N1.1 Summary ================")
        print(
            f"  Phase A Direct vs Matched B&H: Neural=${recon['neural_net_pnl_usd']:+.2f} ({recon['neural_net_return_pct']:+.2f}%) "
            f"| Matched B&H=${recon['matched_bnh_net_pnl_usd']:+.2f} ({recon['matched_bnh_net_return_pct']:+.2f}%) "
            f"| Direct Delta=${recon['direct_net_pnl_diff_vs_matched_bnh_usd']:+.2f} ({recon['direct_net_return_diff_vs_matched_bnh_pct']:+.2f}%)"
        )
        print(
            f"  Phase A Carino vs Matched B&H: ExpGap={recon['carino_geometric_reconciliation_vs_matched_bnh']['c1_mean_exposure_gap_pct']:+.2f}% "
            f"| DynTim={recon['carino_geometric_reconciliation_vs_matched_bnh']['c2_dynamic_timing_vs_bnh_drift_pct']:+.2f}% "
            f"| NeuralSel={recon['carino_geometric_reconciliation_vs_matched_bnh']['c3_neural_xs_selection_vs_ew_pct']:+.2f}% "
            f"| -BnHDrift={recon['carino_geometric_reconciliation_vs_matched_bnh']['c4_minus_bnh_xs_drift_vs_ew_pct']:+.2f}% "
            f"| CostDiff={recon['carino_geometric_reconciliation_vs_matched_bnh']['c5_net_cost_drag_diff_pct']:+.2f}% "
            f"| Sum={recon['carino_geometric_reconciliation_vs_matched_bnh']['sum_of_components_pct']:+.2f}%"
        )
        print(
            f"  Phase A Total Neural Carino Breakdown: Beta={recon['carino_total_neural_return_decomposition']['market_beta_contribution_pct']:+.2f}% "
            f"| Timing={recon['carino_total_neural_return_decomposition']['dynamic_timing_contribution_pct']:+.2f}% "
            f"| XS_Sel={recon['carino_total_neural_return_decomposition']['cross_sectional_selection_contribution_pct']:+.2f}% "
            f"| Cost={recon['carino_total_neural_return_decomposition']['transaction_cost_drag_pct']:+.2f}%"
        )
        u_sel = alloc_diag["unit_exposure_cross_sectional_selection"]
        print(
            f"  Phase D Unit-Exposure Selection: UnitNeural={u_sel['unit_neural_cum_return_pct']:+.2f}% "
            f"vs UnitEW={u_sel['unit_ew_mkt_cum_return_pct']:+.2f}% "
            f"(Spread={u_sel['unit_compounded_selection_spread_pct']:+.2f}%, StepSum={u_sel['unit_step_sum_selection_spread_pct']:+.2f}%, "
            f"CI95={u_sel['boot_ci95_ann_sel_pct']}, Prob>0={u_sel['prob_positive_selection']:.3f})"
        )
        rb_t = alloc_diag["causal_pit_risk_budget_overlay_test"]
        print(
            f"  Phase D Causal PIT Risk-Budget Overlay: Net={rb_t['net_return_pct']:+.2f}% (${rb_t['net_pnl_usd']:+.2f}) "
            f"Sh={rb_t['annualized_sharpe']:+.2f} DD={rb_t['max_drawdown_pct']:.2f}% Exp={rb_t['risk_exposure_pct']:.1f}% "
            f"Tim={rb_t['timing_value_pct']:+.2f}% Sel={rb_t['asset_selection_value_pct']:+.2f}%"
        )

    out_path = OUT_DIR / "n1_1_alpha_attribution_and_n2_feasibility.json"
    out_path.write_text(json.dumps(report_data, indent=2))
    print(f"\nSaved N1.1 audit results to {out_path}", flush=True)


if __name__ == "__main__":
    main()
