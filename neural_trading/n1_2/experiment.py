"""N1.2 Phase E & Phase F — Conditional Neural Architecture & Post-Cost Economic Experiment.

Implements `MicrostructureDislocationPolicy` (a compact cross-sectional + temporal neural policy with
explicit turnover hysteresis and cash-budget head) and evaluates the 4-way Phase F comparison:
1. Cash
2. Passive allocation (100% Equal-Weight & Exposure-Matched Equal-Weight)
3. Simple hypothesis-specific baseline
4. Neural policy (evaluated only when authorized or as a bounded diagnostic verification of Phase D findings)

Strictly outputs all 10 mandatory Phase F evaluation metrics:
- predictive_information
- implementable_gross_edge
- realized_execution_cost
- net_economic_value
- turnover
- max_drawdown
- risk_exposure
- asset_or_venue_consistency
- regime_consistency
- economic_uncertainty
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F

from neural_trading.n1_2.discovery import (
    _newey_west_tstat,
    _spearman_ic_series,
    build_cash_weights,
    build_passive_equal_weight,
    build_simple_hypothesis_baseline_weights,
    simulate_spot_long_only_portfolio,
)


class MicrostructureDislocationPolicy(nn.Module):
    """Compact cross-sectional & temporal neural policy with stateful hysteresis gate.

    Designed specifically for N1.2 H-A (tick-level order-flow & sweep dislocation) and
    H-B (cross-venue Coinbase/Binance & 5m Perp/Spot lead-lag).
    """

    def __init__(self, n_features: int, n_assets: int, hidden_dim: int = 24, max_weight: float = 0.35) -> None:
        super().__init__()
        self.n_features = n_features
        self.n_assets = n_assets
        self.max_weight = max_weight

        self.encoder = nn.Sequential(
            nn.Linear(n_features * 2, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
        )
        self.score_head = nn.Linear(hidden_dim, 1)
        self.risk_budget_head = nn.Sequential(
            nn.Linear(hidden_dim, 12),
            nn.SiLU(),
            nn.Linear(12, 1),
            nn.Sigmoid(),
        )
        # Learnable temperature and hysteresis threshold
        self.logit_temp = nn.Parameter(torch.tensor(0.0))

    def forward_step(self, x_t: torch.Tensor, prev_w: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Single decision step over (n_assets, n_features) tensor x_t."""
        cs_mean = x_t.mean(dim=0, keepdim=True)
        x_aug = torch.cat([x_t, x_t - cs_mean], dim=-1)
        h = self.encoder(x_aug)  # (A, H)
        raw_scores = self.score_head(h).squeeze(-1)  # (A,)
        temp = torch.exp(self.logit_temp).clamp(0.2, 5.0)
        rel_probs = F.softmax(raw_scores * temp, dim=-1)

        # Global risk budget from cross-sectional pooled embedding
        h_pool = h.mean(dim=0, keepdim=True)
        budget = self.risk_budget_head(h_pool).squeeze()  # scalar in (0, 1)

        prop_w = torch.clamp(rel_probs * budget, 0.0, self.max_weight)
        # Smooth blending with previous weights to suppress spurious turnover
        gate = torch.sigmoid((raw_scores.max() - raw_scores.mean()) * 1.5 - 0.5)
        new_w = gate * prop_w + (1.0 - gate) * prev_w
        return new_w, raw_scores


def train_and_evaluate_neural_pilot(
    df: pd.DataFrame,
    feature_cols: List[str],
    train_years: List[int],
    eval_years: List[int],
    rebalance_every_h: int = 12,
    cost_per_leg_bps: float = 7.0,
    extra_half_spread_col: Optional[str] = None,
    epochs: int = 25,
    lr: float = 3e-3,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Train `MicrostructureDislocationPolicy` on `train_years` with post-cost differentiable utility and evaluate on `eval_years`."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    symbols = sorted(df["symbol"].unique().tolist())
    n_assets = len(symbols)
    n_feat = len(feature_cols)

    piv_ret_1h = df.pivot(index="hour_close_ms", columns="symbol", values="fwd_ret_1h").reindex(columns=symbols).fillna(0.0)
    piv_ret_h = (
        df.pivot(index="hour_close_ms", columns="symbol", values=f"fwd_ret_{rebalance_every_h}h")
        .reindex(columns=symbols)
        .fillna(0.0)
    )
    ts_all = piv_ret_1h.index.to_numpy(dtype=np.int64)
    years_all = pd.to_datetime(ts_all, unit="ms", utc=True).year.to_numpy()

    feat_mats = []
    for col in feature_cols:
        p = df.pivot(index="hour_close_ms", columns="symbol", values=col).reindex(index=ts_all, columns=symbols).fillna(0.0)
        feat_mats.append(p.to_numpy(dtype=np.float32))
    # shape: (T, A, F)
    x_all = np.stack(feat_mats, axis=-1)
    r_h_all = np.expm1(piv_ret_h.to_numpy(dtype=np.float32))

    # Subsample decision grid every `rebalance_every_h` hours for training
    train_mask = np.isin(years_all, train_years)
    train_indices = np.where(train_mask)[0][::rebalance_every_h]
    # Purge last 2 steps before boundary
    if len(train_indices) > 4:
        train_indices = train_indices[:-2]

    x_train = torch.tensor(x_all[train_indices], dtype=torch.float32)
    r_train = torch.tensor(r_h_all[train_indices], dtype=torch.float32)

    model = MicrostructureDislocationPolicy(n_features=n_feat, n_assets=n_assets)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    leg_cost = (cost_per_leg_bps + 0.5) * 1e-4

    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        prev_w = torch.zeros(n_assets, dtype=torch.float32)
        step_nets = []
        turnovers = []
        for idx in range(len(x_train)):
            w_t, _ = model.forward_step(x_train[idx], prev_w)
            to_t = torch.abs(w_t - prev_w).sum()
            gross_t = (w_t * r_train[idx]).sum()
            net_t = gross_t - to_t * leg_cost * 1.25  # Slightly conservative friction penalty during training
            step_nets.append(net_t)
            turnovers.append(to_t)
            prev_w = w_t * (1.0 + r_train[idx]) / torch.clamp(1.0 + gross_t, min=1e-6)

        rets_t = torch.stack(step_nets)
        mean_r = rets_t.mean()
        std_r = rets_t.std() + 1e-6
        downside = torch.clamp(-rets_t, min=0.0).pow(2).mean().sqrt() + 1e-6
        loss = -(mean_r / std_r) - 0.5 * (mean_r / downside) + 0.05 * torch.stack(turnovers).mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

    # Inference on eval_years
    model.eval()
    eval_mask = np.isin(years_all, eval_years)
    eval_ts = ts_all[eval_mask]
    x_eval = torch.tensor(x_all[eval_mask], dtype=torch.float32)

    w_out = np.zeros((len(eval_ts), n_assets), dtype=np.float64)
    scores_out = np.zeros((len(eval_ts), n_assets), dtype=np.float64)
    curr_w = torch.zeros(n_assets, dtype=torch.float32)

    with torch.no_grad():
        for t in range(len(eval_ts)):
            if t % rebalance_every_h == 0:
                prop_w, raw_s = model.forward_step(x_eval[t], curr_w)
                if torch.abs(prop_w - curr_w).sum().item() >= 0.10:
                    curr_w = prop_w
            else:
                _, raw_s = model.forward_step(x_eval[t], curr_w)
            w_out[t] = curr_w.cpu().numpy()
            scores_out[t] = raw_s.cpu().numpy()

    w_df = pd.DataFrame(w_out, index=eval_ts, columns=symbols)
    s_df = pd.DataFrame(scores_out, index=eval_ts, columns=symbols)
    return w_df, s_df, {"rebalance_every_h": rebalance_every_h, "epochs": epochs, "train_years": train_years, "eval_years": eval_years}


def build_phase_f_10_metric_scorecard(
    df_eval: pd.DataFrame,
    weights_df: pd.DataFrame,
    score_col_or_df: Any,
    passive_matched_sim: Dict[str, Any],
    cost_per_leg_bps: float = 7.0,
    extra_half_spread_col: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute all 10 mandatory Phase F evaluation metrics for a policy on `df_eval`."""
    sim = simulate_spot_long_only_portfolio(
        df_eval,
        weights_df,
        cost_per_leg_bps=cost_per_leg_bps,
        extra_half_spread_col=extra_half_spread_col,
    )

    # 1. Predictive information (IC on 12h forward return)
    if isinstance(score_col_or_df, str) and score_col_or_df in df_eval.columns:
        _, ic_arr = _spearman_ic_series(df_eval, score_col_or_df, "fwd_ret_12h")
        mu_ic, se_ic, t_ic = _newey_west_tstat(ic_arr[::12], max_lag=6)
    elif isinstance(score_col_or_df, pd.DataFrame):
        s_long = score_col_or_df.stack().reset_index()
        s_long.columns = ["hour_close_ms", "symbol", "_model_score"]
        merged = pd.merge(df_eval[["hour_close_ms", "symbol", "fwd_ret_12h"]], s_long, on=["hour_close_ms", "symbol"], how="inner")
        _, ic_arr = _spearman_ic_series(merged, "_model_score", "fwd_ret_12h")
        mu_ic, se_ic, t_ic = _newey_west_tstat(ic_arr[::12], max_lag=6)
    else:
        mu_ic, se_ic, t_ic = 0.0, 0.0, 0.0

    # Regime consistency across years or half-years inside df_eval
    df_eval_tmp = df_eval.copy()
    df_eval_tmp["half_year"] = (
        df_eval_tmp["dt"].dt.year.astype(str) + "-H" + ((df_eval_tmp["dt"].dt.month - 1) // 6 + 1).astype(str)
    )
    regime_nets: Dict[str, float] = {}
    for reg, grp in df_eval_tmp.groupby("half_year"):
        reg_ts = grp["hour_close_ms"].unique()
        w_sub = weights_df.loc[weights_df.index.intersection(reg_ts)]
        if len(w_sub) > 24:
            sub_sim = simulate_spot_long_only_portfolio(
                grp, w_sub, cost_per_leg_bps=cost_per_leg_bps, extra_half_spread_col=extra_half_spread_col
            )
            regime_nets[str(reg)] = sub_sim["net_pnl_usd"]

    gross_excess_vs_matched = round(sim["gross_pnl_usd"] - passive_matched_sim["gross_pnl_usd"], 2)
    net_excess_vs_matched = round(sim["net_pnl_usd"] - passive_matched_sim["net_pnl_usd"], 2)

    return {
        "predictive_information": {
            "mean_ic_12h": round(mu_ic, 5),
            "ic_nw_se": round(se_ic, 5),
            "ic_nw_tstat": round(t_ic, 3),
        },
        "implementable_gross_edge": {
            "gross_pnl_usd": sim["gross_pnl_usd"],
            "gross_return_pct": sim["gross_return_pct"],
            "gross_excess_vs_exposure_matched_ew_usd": gross_excess_vs_matched,
        },
        "realized_execution_cost": {
            "total_cost_usd": sim["realized_execution_cost_usd"],
            "cost_per_leg_bps_base": cost_per_leg_bps,
            "extra_half_spread_applied": bool(extra_half_spread_col),
        },
        "net_economic_value": {
            "net_pnl_usd": sim["net_pnl_usd"],
            "net_return_pct": sim["net_return_pct"],
            "net_excess_vs_exposure_matched_ew_usd": net_excess_vs_matched,
            "sharpe_annualized": sim["sharpe_annualized"],
        },
        "turnover": {
            "annualized_one_way_turnover": sim["annualized_turnover"],
        },
        "max_drawdown": {
            "max_drawdown_pct": sim["max_drawdown_pct"],
        },
        "risk_exposure": {
            "mean_total_risk_exposure": sim["mean_risk_exposure"],
        },
        "asset_or_venue_consistency": {
            "positive_assets_count": sim["positive_assets_count"],
            "total_assets_count": sim["total_assets_count"],
            "per_asset_gross_pnl_usd": sim["asset_gross_contribution_usd"],
        },
        "regime_consistency": {
            "positive_half_years_count": sum(1 for v in regime_nets.values() if v > 0),
            "total_half_years_count": len(regime_nets),
            "half_year_net_pnl_usd": regime_nets,
        },
        "economic_uncertainty": {
            "net_step_nw_tstat": sim["net_step_tstat"],
            "net_pnl_ci95_usd": sim["net_pnl_ci95_usd"],
        },
    }
