"""
neural_trading/n1/experiment.py

Phase F: Bounded economic simulation, exact Brinson timing/selection
decomposition, and block-bootstrap economic uncertainty estimation for N1.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple
import numpy as np
import pandas as pd
import torch
import torch.optim as optim

from neural_trading.n1.model import CrossSectionalMarketPolicy

ASSET_FEATURE_COLS = [
    "r12h", "r24h", "r72h",
    "H1_spot_taker_imb_12h", "H1_spot_taker_imb_24h", "H1_xs_rel_imb_24h",
    "H1_trade_size_z168h", "H1_vol_shock_z168h",
    "H1_parkinson_vol_24h", "H1_clv_shadow_12h", "H1_xs_rel_ret_24h",
]


def build_step_tensors(
    h1_feats: Dict[str, pd.DataFrame],
    bd_panel: Dict[str, pd.DataFrame],
    horizon_h: int = 12,
) -> Dict[str, Any]:
    """
    Constructs non-overlapping H-hour decision step tensors indexed by `available_at`.
    At step t:
      - Features use strictly causal bars up to t.
      - Forward asset price relatives use close(t + H) / close(t).
      - Active mask requires asset to be active at t; if an asset delists during
        (t, t + H], its last observed close in (t, t + H] is used for final settlement.
    """
    close = h1_feats["close"]
    active = h1_feats["active"]
    step_idx = close.index[::horizon_h][:-1]
    symbols = list(close.columns)
    N = len(symbols)
    K = len(step_idx)

    # Forward H-hour simple returns: close(t+H)/close(t) - 1, with forward-fill of last print if delisted mid-step
    close_ffill = close.ffill()
    fwd_ret_df = (close_ffill.shift(-horizon_h) / close - 1.0).reindex(step_idx)
    fwd_ret = np.nan_to_num(fwd_ret_df.to_numpy(dtype=np.float64), nan=0.0)
    act_mask = active.reindex(step_idx).fillna(False).to_numpy(dtype=bool)

    # Per-asset feature tensor: (K, N, d_a)
    d_a = len(ASSET_FEATURE_COLS)
    asset_x = np.zeros((K, N, d_a), dtype=np.float32)
    for j, col in enumerate(ASSET_FEATURE_COLS):
        arr = h1_feats[col].reindex(step_idx).to_numpy(dtype=np.float32)
        asset_x[:, :, j] = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    # Global market & order-book liquidity context tensor: (K, d_m = 9)
    mkt_breadth = h1_feats["H1_mkt_breadth_24h"].mean(axis=1).reindex(step_idx).to_numpy(dtype=np.float32)
    mkt_disp = h1_feats["H1_mkt_disp_24h"].mean(axis=1).reindex(step_idx).to_numpy(dtype=np.float32)
    mkt_trend = h1_feats["H1_mkt_trend_72h"].mean(axis=1).reindex(step_idx).to_numpy(dtype=np.float32)
    mkt_pvol = h1_feats["H1_parkinson_vol_24h"].mean(axis=1).reindex(step_idx).to_numpy(dtype=np.float32)

    btc_bd = bd_panel["BTCUSDT"].reindex(step_idx)
    eth_bd = bd_panel["ETHUSDT"].reindex(step_idx)
    bd_avail = (btc_bd["imb_1pct_mean"].notna() & eth_bd["imb_1pct_mean"].notna()).to_numpy(dtype=np.float32)
    bd_imb1 = 0.5 * (btc_bd["imb_1pct_ma4h"].fillna(0.0) + eth_bd["imb_1pct_ma4h"].fillna(0.0)).to_numpy(dtype=np.float32)
    bd_imb5 = 0.5 * (btc_bd["imb_5pct_ma4h"].fillna(0.0) + eth_bd["imb_5pct_ma4h"].fillna(0.0)).to_numpy(dtype=np.float32)
    bd_slope = 0.5 * (btc_bd["slope_1_5_mean"].fillna(0.0) + eth_bd["slope_1_5_mean"].fillna(0.0)).to_numpy(dtype=np.float32)
    bd_thin = 0.5 * (btc_bd["depth_thinning_z168h"].fillna(0.0) + eth_bd["depth_thinning_z168h"].fillna(0.0)).to_numpy(dtype=np.float32)

    market_x = np.stack([
        np.nan_to_num(mkt_breadth - 0.5, nan=0.0),
        np.nan_to_num(mkt_disp, nan=0.0),
        np.nan_to_num(mkt_trend, nan=0.0),
        np.nan_to_num(mkt_pvol, nan=0.0),
        bd_avail,
        np.nan_to_num(bd_imb1, nan=0.0),
        np.nan_to_num(bd_imb5, nan=0.0),
        np.nan_to_num(bd_slope, nan=0.0),
        np.nan_to_num(bd_thin, nan=0.0),
    ], axis=-1).astype(np.float32)

    return {
        "timestamps": step_idx,
        "symbols": symbols,
        "asset_x": asset_x,
        "market_x": market_x,
        "active_mask": act_mask,
        "fwd_ret": fwd_ret,
        "horizon_h": horizon_h,
    }


def normalize_causal_train(
    asset_x: np.ndarray,
    market_x: np.ndarray,
    active_mask: np.ndarray,
    train_sl: slice,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fits mean/std strictly on train_sl active observations and clips to [-5, 5]."""
    ax_tr = asset_x[train_sl]
    am_tr = active_mask[train_sl]
    a_mean = np.zeros((1, 1, asset_x.shape[-1]), dtype=np.float32)
    a_std = np.ones((1, 1, asset_x.shape[-1]), dtype=np.float32)
    for j in range(asset_x.shape[-1]):
        vals = ax_tr[:, :, j][am_tr]
        if len(vals) > 10:
            a_mean[0, 0, j] = float(np.mean(vals))
            a_std[0, 0, j] = max(float(np.std(vals)), 1e-6)
    ax_norm = np.clip((asset_x - a_mean) / a_std, -5.0, 5.0) * active_mask[:, :, None].astype(np.float32)

    mx_tr = market_x[train_sl]
    m_mean = np.mean(mx_tr, axis=0, keepdims=True)
    m_std = np.maximum(np.std(mx_tr, axis=0, keepdims=True), 1e-6)
    # Keep column 4 (bd_avail binary indicator) unscaled
    m_mean[0, 4] = 0.0
    m_std[0, 4] = 1.0
    # For bookDepth columns 5..8, compute stats on rows where bd_avail == 1 in train (if any)
    bd_rows = mx_tr[:, 4] > 0.5
    if bd_rows.sum() > 20:
        for c in (5, 6, 7, 8):
            m_mean[0, c] = float(np.mean(mx_tr[bd_rows, c]))
            m_std[0, c] = max(float(np.std(mx_tr[bd_rows, c])), 1e-6)
    mx_norm = np.clip((market_x - m_mean) / m_std, -5.0, 5.0)
    # Zero out bookDepth columns when bd_avail == 0
    mx_norm[:, 5:9] *= (market_x[:, 4:5] > 0.5).astype(np.float32)
    return ax_norm, mx_norm


def enforce_external_hard_risk(
    w_prop: np.ndarray,
    active_t: np.ndarray,
    min_cash: float = 0.05,
    max_asset: float = 0.35,
) -> np.ndarray:
    """Projects proposed weights [cash, asset_1..N] onto hard-risk & active-symbol constraints."""
    w = np.maximum(w_prop.copy(), 0.0)
    w[1:] *= active_t.astype(np.float64)
    w[1:] = np.minimum(w[1:], max_asset)
    risky_sum = float(np.sum(w[1:]))
    max_risky = 1.0 - min_cash
    if risky_sum > max_risky and risky_sum > 1e-9:
        w[1:] *= max_risky / risky_sum
    w[0] = max(min_cash, 1.0 - float(np.sum(w[1:])))
    w /= np.sum(w)
    return w


def simulate_step_policy(
    target_weights_seq: np.ndarray,  # (K_eval, N + 1)
    is_hold_seq: np.ndarray,         # (K_eval,) bool
    fwd_ret_seq: np.ndarray,         # (K_eval, N)
    active_seq: np.ndarray,          # (K_eval, N) bool
    horizon_h: int = 12,
    initial_capital: float = 20_000.0,
    cost_per_leg_bps: float = 7.0,
    min_cash: float = 0.05,
    max_asset: float = 0.35,
) -> Dict[str, Any]:
    """
    Executes sequential portfolio simulation with exact Brinson attribution
    (Timing Value vs Asset Selection Value) and block-bootstrap uncertainty.
    """
    K, N = fwd_ret_seq.shape
    cost_rate = cost_per_leg_bps / 10_000.0
    steps_per_year = (24.0 / horizon_h) * 365.0

    cap = initial_capital
    gross_cap = initial_capital
    w_curr = np.zeros(N + 1, dtype=np.float64)
    w_curr[0] = 1.0  # start in 100% cash

    exec_weights = np.zeros((K, N + 1), dtype=np.float64)
    gross_step_rets = np.zeros(K, dtype=np.float64)
    net_step_rets = np.zeros(K, dtype=np.float64)
    oneway_turnovers = np.zeros(K, dtype=np.float64)
    step_costs_usd = np.zeros(K, dtype=np.float64)
    ew_mkt_rets = np.zeros(K, dtype=np.float64)
    equity_curve = np.zeros(K + 1, dtype=np.float64)
    equity_curve[0] = initial_capital

    hold_count = 0
    rebal_count = 0
    risk_forced_count = 0
    trade_legs = 0

    for t in range(K):
        act_t = active_seq[t]
        # If any held asset delisted at step t, force-liquidate that asset to cash
        delisted_held = (w_curr[1:] > 1e-5) & (~act_t)
        violates_static = (w_curr[0] < min_cash - 1e-5) or np.any(w_curr[1:] > max_asset + 1e-5) or np.any(delisted_held)

        if is_hold_seq[t] and t > 0 and not violates_static:
            w_exec = w_curr.copy()
            hold_count += 1
        else:
            if is_hold_seq[t] and t > 0 and violates_static:
                w_exec = enforce_external_hard_risk(w_curr, act_t, min_cash=min_cash, max_asset=max_asset)
                risk_forced_count += 1
            else:
                w_exec = enforce_external_hard_risk(target_weights_seq[t], act_t, min_cash=min_cash, max_asset=max_asset)

        delta_risky = np.abs(w_exec[1:] - w_curr[1:])
        real_leg_mask = (delta_risky * cap) >= 1.0
        delta_clean = np.where(real_leg_mask, delta_risky, 0.0)
        leg_sum = float(np.sum(delta_clean))  # sum of |buy| + |sell| risky notional fractions
        oneway_to = 0.5 * leg_sum
        n_legs = int(np.sum(real_leg_mask))
        trade_legs += n_legs
        if n_legs > 0 and not (is_hold_seq[t] and t > 0 and not violates_static):
            rebal_count += 1
        elif n_legs == 0 and not (is_hold_seq[t] and t > 0 and not violates_static):
            hold_count += 1

        cost_frac = leg_sum * cost_rate
        cost_usd = cap * cost_frac

        r_assets = fwd_ret_seq[t] * act_t.astype(np.float64)
        gross_r = float(np.sum(w_exec[1:] * r_assets))
        net_r = (1.0 - cost_frac) * (1.0 + gross_r) - 1.0

        cap = cap * (1.0 + net_r)
        gross_cap = gross_cap * (1.0 + gross_r)
        equity_curve[t + 1] = cap

        exec_weights[t] = w_exec
        gross_step_rets[t] = gross_r
        net_step_rets[t] = net_r
        oneway_turnovers[t] = oneway_to
        step_costs_usd[t] = cost_usd
        n_act = max(int(np.sum(act_t)), 1)
        ew_mkt_rets[t] = float(np.sum(r_assets) / n_act)

        # Drift weights to t + 1
        y_vec = np.concatenate([[1.0], 1.0 + r_assets])
        w_post = w_exec * y_vec
        w_curr = w_post / max(float(np.sum(w_post)), 1e-12)

    # Exposure & Exact Brinson Timing / Selection Attribution
    risky_exp_t = np.sum(exec_weights[:, 1:], axis=1)
    mean_risky_exp = float(np.mean(risky_exp_t))
    mean_cash_exp = float(np.mean(exec_weights[:, 0]))

    # Brinson identity per step: gross_step_rets[t] - mean_risky_exp * ew_mkt_rets[t]
    #   == timing_step[t] + selection_step[t]
    timing_step = (risky_exp_t - mean_risky_exp) * ew_mkt_rets
    selection_step = gross_step_rets - risky_exp_t * ew_mkt_rets
    matched_gross_step = mean_risky_exp * ew_mkt_rets

    # Annualized Sharpe & Drawdown
    sd = float(np.std(net_step_rets))
    ann_sharpe = float((np.mean(net_step_rets) / sd) * np.sqrt(steps_per_year)) if sd > 1e-9 else 0.0
    peaks = np.maximum.accumulate(equity_curve)
    dd_pct = float(np.max((peaks - equity_curve) / np.maximum(peaks, 1e-9)) * 100.0)

    # Block-bootstrap economic uncertainty on net excess step returns vs matched-exposure benchmark
    # Matched benchmark pays entry cost on step 0 only:
    matched_net_step = matched_gross_step.copy()
    if K > 0:
        matched_net_step[0] -= mean_risky_exp * cost_rate
    excess_net_step = net_step_rets - matched_net_step

    rng = np.random.default_rng(42)
    b_len = max(2, 48 // horizon_h)
    n_b = max(1, int(np.ceil(K / b_len)))
    starts = rng.integers(0, max(1, K - b_len + 1), size=(400, n_b))
    idx = (starts[:, :, None] + np.arange(b_len)[None, None, :]).reshape(400, -1)[:, :K]
    boot_ann_exc_pct = idx.shape[1] and (np.mean(excess_net_step[idx], axis=1) * steps_per_year * 100.0)
    ci_lo, ci_hi = np.percentile(boot_ann_exc_pct, [2.5, 97.5])
    prob_pos = float(np.mean(boot_ann_exc_pct > 0.0))

    return {
        "initial_capital": initial_capital,
        "final_equity": round(float(cap), 2),
        "gross_pnl_usd": round(float(gross_cap - initial_capital), 2),
        "net_pnl_usd": round(float(cap - initial_capital), 2),
        "gross_return_pct": round(float((gross_cap / initial_capital - 1.0) * 100.0), 2),
        "net_return_pct": round(float((cap / initial_capital - 1.0) * 100.0), 2),
        "annualized_sharpe": round(ann_sharpe, 2),
        "max_drawdown_pct": round(dd_pct, 2),
        "annualized_turnover": round(float(np.mean(oneway_turnovers) * steps_per_year), 2),
        "transaction_cost_usd": round(float(np.sum(step_costs_usd)), 2),
        "transaction_cost_pct": round(float(np.sum(step_costs_usd) / initial_capital * 100.0), 2),
        "risk_exposure_pct": round(mean_risky_exp * 100.0, 2),
        "average_cash_pct": round(mean_cash_exp * 100.0, 2),
        "timing_value_pct": round(float(np.sum(timing_step) * 100.0), 2),
        "asset_selection_value_pct": round(float(np.sum(selection_step) * 100.0), 2),
        "gross_excess_vs_matched_pct": round(float(np.sum(timing_step + selection_step) * 100.0), 2),
        "net_excess_vs_matched_pct": round(float(np.sum(excess_net_step) * 100.0), 2),
        "economic_uncertainty": {
            "ann_net_excess_ci95_pct": [round(float(ci_lo), 2), round(float(ci_hi), 2)],
            "prob_positive_net_excess": round(prob_pos, 3),
        },
        "actual_trade_count": trade_legs,
        "hold_rate_pct": round(float(hold_count / max(K, 1) * 100.0), 2),
        "risk_forced_rebalance_count": risk_forced_count,
    }


def train_n1_policy(
    model: CrossSectionalMarketPolicy,
    asset_x_tr: np.ndarray,
    market_x_tr: np.ndarray,
    active_tr: np.ndarray,
    fwd_ret_tr: np.ndarray,
    horizon_h: int = 12,
    cost_per_leg_bps: float = 7.0,
    epochs: int = 18,
    rollout_steps: int = 32,
    batch_rollouts: int = 24,
    lr: float = 1.5e-3,
    seed: int = 42,
) -> Dict[str, float]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model.train()
    opt = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)
    cost_rate = cost_per_leg_bps / 10_000.0
    ann_factor = float(np.sqrt((24.0 / horizon_h) * 365.0))
    S, N, _ = asset_x_tr.shape

    ax_t = torch.tensor(asset_x_tr, dtype=torch.float32)
    mx_t = torch.tensor(market_x_tr, dtype=torch.float32)
    am_t = torch.tensor(active_tr, dtype=torch.bool)
    fr_t = torch.tensor(fwd_ret_tr, dtype=torch.float32)

    rng = np.random.default_rng(seed)
    for ep in range(epochs):
        starts = rng.integers(0, max(1, S - rollout_steps), size=batch_rollouts)
        w_curr = torch.zeros((batch_rollouts, N + 1), dtype=torch.float32)
        w_curr[:, 0] = 1.0

        step_net_rets = []
        step_tos = []
        for s in range(rollout_steps):
            idx = starts + s
            w_eff, _, _ = model(ax_t[idx], mx_t[idx], am_t[idx], w_curr)
            leg_turnover = torch.sum(torch.abs(w_eff[:, 1:] - w_curr[:, 1:]), dim=-1)
            cost_s = cost_rate * leg_turnover
            r_s = torch.sum(w_eff[:, 1:] * fr_t[idx] * am_t[idx].float(), dim=-1)
            net_r_s = r_s - cost_s
            step_net_rets.append(net_r_s)
            step_tos.append(0.5 * leg_turnover)

            # Drift weights to next step
            y_s = torch.cat([torch.ones((batch_rollouts, 1)), 1.0 + fr_t[idx] * am_t[idx].float()], dim=-1).clamp(min=1e-4)
            w_post = w_eff * y_s
            w_curr = w_post / w_post.sum(dim=-1, keepdim=True).clamp(min=1e-8)

        rets = torch.stack(step_net_rets, dim=1)  # (B, L)
        tos = torch.stack(step_tos, dim=1)
        mu = rets.mean(dim=1)
        sd = torch.sqrt(rets.var(dim=1) + 1e-6)
        sharpe = (mu / sd) * ann_factor
        downside = torch.mean(torch.relu(-rets) ** 2, dim=1) * 40.0
        to_pen = tos.mean(dim=1) * 0.15

        loss = torch.mean(-sharpe + downside + to_pen)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()

    return {"final_train_loss": round(float(loss.item()), 4), "final_train_sharpe": round(float(sharpe.mean().item()), 2)}
