"""
scripts/n1_run_phase_f_economic_pilot.py

Executes the Phase F bounded economic experiment for N1 across chronological
walk-forward folds (2022 Bear, 2024 Recovery+BookDepth, 2025 Adaptive Comparison)
under both 14 bps RT (7 bps/leg) and 28 bps RT (14 bps/leg) cost scenarios.

Compares:
  1. 100% Cash
  2. Passive Diversified Portfolio (Active Universe Equal-Weight)
  3. Exposure-Matched Passive Benchmark
  4. Simple Information-Based Non-Neural Baseline
  5. Unified Neural Policy (N1 CrossSectionalMarketPolicy)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import torch

from neural_trading.n1.pit_dataset import (
    SPOT_SYMBOLS, DEPTH_SYMBOLS, build_spot_panel, build_bookdepth_hourly,
)
from neural_trading.n1.information_tests import compute_h1_features
from neural_trading.n1.model import CrossSectionalMarketPolicy
from neural_trading.n1.experiment import (
    build_step_tensors, normalize_causal_train,
    simulate_step_policy, train_n1_policy, enforce_external_hard_risk,
)

RAW_ROOT = REPO / "data" / "historical" / "neural_n1" / "raw"
CACHE_DIR = REPO / "data" / "historical" / "neural_n1" / "pit_cache"
OUT_DIR = REPO / "research" / "neural_n1"


def build_non_neural_baseline_weights(
    asset_x_norm: np.ndarray,   # (K, N, d_a)
    market_x_norm: np.ndarray,  # (K, d_m)
    active_mask: np.ndarray,    # (K, N)
    deadband_oneway: float = 0.06,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Simple Information-Based Non-Neural Baseline:
      - Uses Market Breadth (mkt_x[0]), 72h Trend (mkt_x[2]), inverse Parkinson
        Vol (-mkt_x[3]), and Order-Book Depth Imbalance (mkt_x[5]) to set total
        risky exposure E_t in [0.15, 0.90].
      - Tilts active asset weights by a linear score of cross-sectional relative
        spot taker-buy imbalance (asset_x[5]), trade-size z-score (asset_x[6]),
        and relative 24h return (asset_x[10]), penalized by Parkinson vol (asset_x[8]).
      - Holds when one-way turnover vs previous target is below `deadband_oneway`.
    """
    K, N, _ = asset_x_norm.shape
    w_seq = np.zeros((K, N + 1), dtype=np.float64)
    is_hold = np.zeros(K, dtype=bool)
    w_prev = np.zeros(N + 1, dtype=np.float64)
    w_prev[0] = 1.0

    for t in range(K):
        act = active_mask[t]
        if not np.any(act):
            w_seq[t, 0] = 1.0
            is_hold[t] = True
            continue
        # Regime score -> risky exposure in [0.15, 0.90]
        m = market_x_norm[t]
        reg_score = 0.35 * m[0] + 0.35 * m[2] - 0.30 * m[3] + 0.20 * m[5]
        risky_exp = float(np.clip(0.52 + 0.25 * np.tanh(reg_score), 0.15, 0.90))

        # Cross-sectional score on active assets
        ax = asset_x_norm[t]
        a_score = 0.35 * ax[:, 5] + 0.30 * ax[:, 6] + 0.25 * ax[:, 10] - 0.20 * ax[:, 8]
        a_score = np.where(act, a_score, -1e9)
        a_score = a_score - np.max(a_score[act])
        probs = np.where(act, np.exp(0.8 * a_score), 0.0)
        probs /= max(float(np.sum(probs)), 1e-9)

        w_cand = np.zeros(N + 1, dtype=np.float64)
        w_cand[0] = 1.0 - risky_exp
        w_cand[1:] = risky_exp * probs
        w_cand = enforce_external_hard_risk(w_cand, act)

        oneway_to = 0.5 * float(np.sum(np.abs(w_cand[1:] - w_prev[1:])))
        if t > 0 and oneway_to < deadband_oneway and not np.any((w_prev[1:] > 0) & (~act)):
            w_seq[t] = w_prev.copy()
            is_hold[t] = True
        else:
            w_seq[t] = w_cand
            w_prev = w_cand.copy()
            is_hold[t] = False
    return w_seq, is_hold


def evaluate_neural_sequence(
    model: CrossSectionalMarketPolicy,
    asset_x_norm: np.ndarray,
    market_x_norm: np.ndarray,
    active_mask: np.ndarray,
    fwd_ret: np.ndarray,
    deadband_oneway: float = 0.06,
) -> Tuple[np.ndarray, np.ndarray]:
    model.eval()
    K, N, _ = asset_x_norm.shape
    w_seq = np.zeros((K, N + 1), dtype=np.float64)
    is_hold = np.zeros(K, dtype=bool)
    w_curr = np.zeros(N + 1, dtype=np.float64)
    w_curr[0] = 1.0

    with torch.no_grad():
        for t in range(K):
            act = active_mask[t]
            ax_t = torch.tensor(asset_x_norm[t:t+1], dtype=torch.float32)
            mx_t = torch.tensor(market_x_norm[t:t+1], dtype=torch.float32)
            am_t = torch.tensor(act.reshape(1, N), dtype=torch.bool)
            wc_t = torch.tensor(w_curr.reshape(1, N + 1), dtype=torch.float32)

            w_eff, _, _ = model(ax_t, mx_t, am_t, wc_t)
            w_prop = enforce_external_hard_risk(w_eff.squeeze(0).numpy().astype(np.float64), act)
            oneway_to = 0.5 * float(np.sum(np.abs(w_prop[1:] - w_curr[1:])))
            delisted_held = np.any((w_curr[1:] > 1e-5) & (~act))

            if t > 0 and oneway_to < deadband_oneway and not delisted_held:
                w_exec = w_curr.copy()
                is_hold[t] = True
            else:
                w_exec = w_prop
                is_hold[t] = False

            w_seq[t] = w_exec
            r_assets = fwd_ret[t] * act.astype(np.float64)
            y_vec = np.concatenate([[1.0], 1.0 + r_assets])
            w_post = w_exec * y_vec
            w_curr = w_post / max(float(np.sum(w_post)), 1e-12)

    return w_seq, is_hold


def build_passive_weights(active_mask: np.ndarray, cash_weight: float) -> Tuple[np.ndarray, np.ndarray]:
    K, N = active_mask.shape
    w_seq = np.zeros((K, N + 1), dtype=np.float64)
    is_hold = np.ones(K, dtype=bool)
    is_hold[0] = False
    for t in range(K):
        act = active_mask[t]
        n_act = max(int(np.sum(act)), 1)
        w_seq[t, 0] = cash_weight
        w_seq[t, 1:] = np.where(act, (1.0 - cash_weight) / n_act, 0.0)
        if t > 0 and not np.array_equal(active_mask[t], active_mask[t - 1]):
            # Rebalance only if active symbol membership changed (listing/delisting)
            is_hold[t] = False
    return w_seq, is_hold


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

    folds = {
        "Fold1_2022_Bear": ("2018-06-01", "2021-12-31", "2022-01-03", "2022-12-31"),
        "Fold2_2024_Expansion_BookDepth": ("2018-06-01", "2023-12-31", "2024-01-03", "2024-12-31"),
        "Fold3_2025_Adaptive_Comparison": ("2018-06-01", "2024-12-31", "2025-01-03", "2025-12-31"),
    }

    all_results: Dict[str, Any] = {}
    for fold_name, (tr_s, tr_e, ev_s, ev_e) in folds.items():
        tr_idx = np.where((ts >= tr_s) & (ts <= tr_e))[0]
        ev_idx = np.where((ts >= ev_s) & (ts <= ev_e))[0]
        tr_sl = slice(int(tr_idx[0]), int(tr_idx[-1]) + 1)
        ev_sl = slice(int(ev_idx[0]), int(ev_idx[-1]) + 1)

        ax_norm, mx_norm = normalize_causal_train(asset_x, market_x, active_mask, tr_sl)

        model = CrossSectionalMarketPolicy(
            asset_feat_dim=asset_x.shape[-1],
            market_feat_dim=market_x.shape[-1],
            embed_dim=24,
            num_heads=4,
            deadband_oneway=0.06,
        )
        tr_diag = train_n1_policy(
            model,
            ax_norm[tr_sl], mx_norm[tr_sl], active_mask[tr_sl], fwd_ret[tr_sl],
            horizon_h=12, cost_per_leg_bps=7.0, epochs=18, seed=42,
        )

        w_neural, hold_neural = evaluate_neural_sequence(
            model, ax_norm[ev_sl], mx_norm[ev_sl], active_mask[ev_sl], fwd_ret[ev_sl], deadband_oneway=0.06
        )
        w_info, hold_info = build_non_neural_baseline_weights(
            ax_norm[ev_sl], mx_norm[ev_sl], active_mask[ev_sl], deadband_oneway=0.06
        )
        w_cash, hold_cash = build_passive_weights(active_mask[ev_sl], cash_weight=1.0)
        w_pass, hold_pass = build_passive_weights(active_mask[ev_sl], cash_weight=0.05)

        fold_out: Dict[str, Any] = {"train_diag": tr_diag, "eval_steps": int(len(ev_idx)), "scenarios": {}}
        for scen_name, leg_bps in (("baseline_14bps_rt", 7.0), ("stress_28bps_rt", 14.0)):
            res_neural = simulate_step_policy(
                w_neural, hold_neural, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=leg_bps
            )
            target_cash = res_neural["average_cash_pct"] / 100.0
            w_match, hold_match = build_passive_weights(active_mask[ev_sl], cash_weight=target_cash)

            sc = {
                "100% Cash": simulate_step_policy(w_cash, hold_cash, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=leg_bps, min_cash=1.0),
                "Passive Diversified (Active EW)": simulate_step_policy(w_pass, hold_pass, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=leg_bps),
                f"Exposure-Matched Passive ({res_neural['average_cash_pct']:.1f}% Cash)": simulate_step_policy(w_match, hold_match, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=leg_bps),
                "Simple Info Non-Neural Baseline": simulate_step_policy(w_info, hold_info, fwd_ret[ev_sl], active_mask[ev_sl], cost_per_leg_bps=leg_bps),
                "Unified Neural Policy (N1)": res_neural,
            }
            fold_out["scenarios"][scen_name] = sc

        all_results[fold_name] = fold_out
        print(f"\n================ {fold_name} (14 bps RT) ================")
        for k, r in fold_out["scenarios"]["baseline_14bps_rt"].items():
            print(
                f"  {k:44s} | Gross={r['gross_return_pct']:+6.2f}% Net={r['net_return_pct']:+6.2f}% "
                f"(${r['net_pnl_usd']:+8.2f}) | Sh={r['annualized_sharpe']:+5.2f} DD={r['max_drawdown_pct']:5.2f}% "
                f"TO={r['annualized_turnover']:5.1f}x Cost=${r['transaction_cost_usd']:6.2f} "
                f"Exp={r['risk_exposure_pct']:4.1f}% Tim={r['timing_value_pct']:+5.2f}% Sel={r['asset_selection_value_pct']:+5.2f}% "
                f"CI95={r['economic_uncertainty']['ann_net_excess_ci95_pct']}",
                flush=True,
            )

    out_path = OUT_DIR / "n1_phase_f_economic_pilot_results.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved Phase F pilot results to {out_path}", flush=True)


if __name__ == "__main__":
    main()
