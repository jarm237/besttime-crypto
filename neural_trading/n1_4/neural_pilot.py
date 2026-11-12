r"""N1.4 Phase F — Bounded Stateful Term-Structure Neural Policy (`TermStructureCarryPolicy`).

Executed ONLY after Candidate H-1 (`DATED_QUARTERLY_DELIVERY_BASIS_CARRY_AND_CONVERGENCE`) passes
Phase E post-cost economic falsification.

Architecture & Design Principles:
1. Designed directly from the economic mechanics of fixed-maturity cash-and-carry:
   - Operates on a 24h decision horizon (matching multi-week carry holding periods).
   - Observes 6 stationary term-structure features per asset (`f1_basis_ma24`, `f1_yield_ma24`,
     `f1_ttm_frac`, `f1_basis_z168`, `term_structure_slope`, `f1_yield_cs_excess`) PLUS explicit
     current portfolio state (`w_prev_i`, `cash_prev`).
   - Outputs per-asset target carry allocations, a stateful HOLD/rebalance gate $g_{t,i} \in (0, 1)$,
     and an aggregate Cash vs Carry exposure budget $B_t \in [0, 1]$.
2. External deterministic risk controls (enforced outside the neural network):
   - Hard mask on inactive/expiring contracts (`f1_ttm_hours < 1.0`) and deep backwardation (`f1_basis_ma24_bps <= 5.0`).
   - Hard single-asset concentration cap ($w_{t,i} \le 0.35$) and portfolio simplex cap ($\sum_i w_{t,i} \le 1.0$).
3. Trained end-to-end on realized post-cost net economic utility (`22.0 bps` round-trip pair cost + `5.5 bps`
   quarterly roll fee) using strictly chronological training splits (`2022–2023 -> 2024` and `2022–2024 -> Dev 2025`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from neural_trading.n1_4.falsification import (
    build_h1_passive_carry_benchmark_weights,
    build_h1_simple_carry_weights,
    simulate_quarterly_carry_portfolio,
)

H1_FEATURE_COLS: List[str] = [
    "f1_basis_ma24_bps",
    "f1_yield_ma24_pct",
    "f1_ttm_hours",
    "f1_basis_z168",
    "term_structure_slope_ann_pct",
    "f1_yield_cs_excess_pct",
]


class TermStructureCarryPolicy(nn.Module):
    """Stateful cost-aware neural policy for fixed-maturity quarterly delivery basis carry."""

    def __init__(self, n_features: int = 6, hidden_dim: int = 24, max_single_weight: float = 0.35) -> None:
        super().__init__()
        self.n_features = n_features
        self.max_single_weight = max_single_weight

        # Input per asset: 6 term-structure features + 6 cross-sectionally demeaned features + [w_prev_i, cash_prev] = 14 dims
        in_dim = n_features * 2 + 2
        self.asset_encoder = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
        )
        self.score_head = nn.Linear(hidden_dim, 1)
        self.hold_gate_head = nn.Linear(hidden_dim, 1)
        self.budget_head = nn.Sequential(
            nn.Linear(hidden_dim + 2, hidden_dim // 2),
            nn.SiLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward_step(
        self,
        x_t: torch.Tensor,
        active_mask_t: torch.Tensor,
        contango_mask_t: torch.Tensor,
        w_prev: torch.Tensor,
    ) -> torch.Tensor:
        """Single 24h decision step with explicit portfolio state and external deterministic risk controls.

        x_t: (N, F) scaled stationary term-structure features
        active_mask_t: (N,) boolean/float mask for active quarterly contract (ttm >= 24h or held with ttm >= 2h)
        contango_mask_t: (N,) boolean/float mask for positive basis regime (f1_basis_ma24_bps > 15 bps)
        w_prev: (N,) current portfolio weights
        """
        valid = (active_mask_t > 0.5) & (contango_mask_t > 0.5)
        if not torch.any(valid):
            return torch.zeros_like(w_prev)

        x_mean = x_t.mean(dim=0, keepdim=True)
        x_rel = x_t - x_mean
        cash_prev = torch.clamp(1.0 - w_prev.sum(), min=0.0, max=1.0).expand(x_t.shape[0], 1)
        state_in = torch.cat([x_t, x_rel, w_prev.unsqueeze(-1), cash_prev], dim=-1)

        h = self.asset_encoder(state_in)
        raw_scores = self.score_head(h).squeeze(-1)

        # Mask out invalid/backwardated contracts outside the network
        masked_scores = torch.where(valid, raw_scores, torch.full_like(raw_scores, -1e9))
        alloc_probs = torch.softmax(masked_scores, dim=-1)
        alloc_probs = torch.where(valid, alloc_probs, torch.zeros_like(alloc_probs))

        # Aggregate carry exposure budget conditioned on pooled embeddings + max contango feature + current cash
        h_pool = h.mean(dim=0)
        max_yield_feat = x_t[:, 1].max().unsqueeze(0)
        cash_scalar = torch.clamp(1.0 - w_prev.sum(), min=0.0, max=1.0).unsqueeze(0)
        budget_in = torch.cat([h_pool, max_yield_feat, cash_scalar], dim=-1)
        budget = torch.sigmoid(self.budget_head(budget_in)).squeeze(-1)

        w_prop = torch.clamp(alloc_probs * budget, min=0.0, max=self.max_single_weight)
        w_sum = w_prop.sum()
        w_prop = torch.where(w_sum > 1.0, w_prop / torch.clamp(w_sum, min=1e-8), w_prop)

        # Per-asset stateful HOLD vs rebalance gate:
        # When w_prev > 0 and contract remains valid, network learns to blend w_prev and w_prop to save 22 bps RT cost
        rebal_gate = torch.sigmoid(self.hold_gate_head(h).squeeze(-1) - 0.5)
        w_blended = torch.where(valid, rebal_gate * w_prop + (1.0 - rebal_gate) * w_prev, torch.zeros_like(w_prev))
        w_blended = torch.clamp(w_blended, min=0.0, max=self.max_single_weight)
        b_sum = w_blended.sum()
        w_blended = torch.where(b_sum > 1.0, w_blended / torch.clamp(b_sum, min=1e-8), w_blended)
        return w_blended


def _extract_24h_decision_tensors(
    df: pd.DataFrame,
    rebalance_every_hours: int = 24,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[int], List[str]]:
    """Build 24h decision-step tensors and cumulative 24h carry returns for training."""
    symbols = sorted(df["symbol"].unique())
    hours = np.sort(df["hour_close_ms"].unique())
    n_hours = len(hours)
    n_assets = len(symbols)

    # Scale features into O(1) stationary units without lookahead
    f_mats = []
    scales = {
        "f1_basis_ma24_bps": 100.0,
        "f1_yield_ma24_pct": 10.0,
        "f1_ttm_hours": 2160.0,
        "f1_basis_z168": 1.0,
        "term_structure_slope_ann_pct": 10.0,
        "f1_yield_cs_excess_pct": 10.0,
    }
    for col in H1_FEATURE_COLS:
        piv = (
            df.pivot(index="hour_close_ms", columns="symbol", values=col)
            .reindex(index=hours, columns=symbols)
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        f_mats.append(np.clip(piv / scales[col], -5.0, 5.0))

    x_hourly = np.stack(f_mats, axis=-1)  # (T_h, N, F)

    piv_ttm = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_ttm_hours")
        .reindex(index=hours, columns=symbols)
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )
    piv_b24 = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_ma24_bps")
        .reindex(index=hours, columns=symbols)
        .fillna(-999.0)
        .to_numpy(dtype=np.float64)
    )
    piv_raw_b = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_bps")
        .reindex(index=hours, columns=symbols)
        .fillna(-999.0)
        .to_numpy(dtype=np.float64)
    )
    piv_ret1h = (
        df.pivot(index="hour_close_ms", columns="symbol", values="f1_carry_ret_1h")
        .reindex(index=hours, columns=symbols)
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )

    step_indices = list(range(0, n_hours, rebalance_every_hours))
    n_steps = len(step_indices)
    x_steps = np.zeros((n_steps, n_assets, len(H1_FEATURE_COLS)), dtype=np.float32)
    act_steps = np.zeros((n_steps, n_assets), dtype=np.float32)
    cont_steps = np.zeros((n_steps, n_assets), dtype=np.float32)
    ret_steps = np.zeros((n_steps, n_assets), dtype=np.float32)

    for k, t0 in enumerate(step_indices):
        t1 = min(t0 + rebalance_every_hours, n_hours)
        x_steps[k] = x_hourly[t0]
        act_steps[k] = (piv_ttm[t0] >= 24.0).astype(np.float32)
        cont_steps[k] = ((piv_b24[t0] > 20.0) & (piv_raw_b[t0] > 10.0)).astype(np.float32)
        # Compounded carry return over the 24h interval [t0, t1)
        block_r = piv_ret1h[t0:t1]
        comp_r = np.prod(1.0 + block_r, axis=0) - 1.0
        ret_steps[k] = comp_r.astype(np.float32)

    return x_steps, act_steps, cont_steps, ret_steps, list(hours), symbols


def train_and_evaluate_h1_neural_pilot(
    df_train: pd.DataFrame,
    df_eval: pd.DataFrame,
    rebalance_every_hours: int = 24,
    pair_cost_per_leg_bps: float = 11.0,
    seed: int = 42,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Train TermStructureCarryPolicy on df_train and generate hourly weight schedule on df_eval."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    x_tr, act_tr, cont_tr, ret_tr, _, _ = _extract_24h_decision_tensors(df_train, rebalance_every_hours)
    x_t = torch.tensor(x_tr, dtype=torch.float32)
    act_t = torch.tensor(act_tr, dtype=torch.float32)
    cont_t = torch.tensor(cont_tr, dtype=torch.float32)
    ret_t = torch.tensor(ret_tr, dtype=torch.float32)

    model = TermStructureCarryPolicy(n_features=len(H1_FEATURE_COLS), hidden_dim=24, max_single_weight=0.35)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-3)
    cost_rate = pair_cost_per_leg_bps / 10_000.0

    n_steps, n_assets, _ = x_t.shape
    for epoch in range(45):
        optimizer.zero_grad()
        w_prev = torch.zeros(n_assets, dtype=torch.float32)
        net_rets = []
        turnovers = []

        for k in range(n_steps):
            w_curr = model.forward_step(x_t[k], act_t[k], cont_t[k], w_prev)
            turn_k = torch.abs(w_curr - w_prev).sum()
            gross_r = (w_curr * ret_t[k]).sum()
            net_r = gross_r - turn_k * (cost_rate * 1.15)  # 1.15x penalty cushion for roll/slippage
            net_rets.append(net_r)
            turnovers.append(turn_k)
            w_prev = w_curr

        r_vec = torch.stack(net_rets)
        t_vec = torch.stack(turnovers)
        mu = r_vec.mean()
        sd = r_vec.std() + 1e-6
        downside = torch.clamp(-r_vec, min=0.0)
        sd_down = torch.sqrt((downside**2).mean() + 1e-8)

        sharpe_daily = (mu / sd) * np.sqrt(365.25)
        sortino_daily = (mu / sd_down) * np.sqrt(365.25)
        loss = -0.6 * sharpe_daily - 0.4 * sortino_daily - 20.0 * mu + 0.15 * t_vec.mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

    # Evaluate on df_eval hourly grid with exact causal 24h decision steps + hard intrabar safety exits
    model.eval()
    symbols = sorted(df_eval["symbol"].unique())
    hours = np.sort(df_eval["hour_close_ms"].unique())
    n_eval_hours = len(hours)

    scales = {
        "f1_basis_ma24_bps": 100.0,
        "f1_yield_ma24_pct": 10.0,
        "f1_ttm_hours": 2160.0,
        "f1_basis_z168": 1.0,
        "term_structure_slope_ann_pct": 10.0,
        "f1_yield_cs_excess_pct": 10.0,
    }
    f_mats = []
    for col in H1_FEATURE_COLS:
        piv = (
            df_eval.pivot(index="hour_close_ms", columns="symbol", values=col)
            .reindex(index=hours, columns=symbols)
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )
        f_mats.append(np.clip(piv / scales[col], -5.0, 5.0))
    x_eval_h = np.stack(f_mats, axis=-1).astype(np.float32)

    piv_ttm = (
        df_eval.pivot(index="hour_close_ms", columns="symbol", values="f1_ttm_hours")
        .reindex(index=hours, columns=symbols)
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )
    piv_b24 = (
        df_eval.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_ma24_bps")
        .reindex(index=hours, columns=symbols)
        .fillna(-999.0)
        .to_numpy(dtype=np.float64)
    )
    piv_raw_b = (
        df_eval.pivot(index="hour_close_ms", columns="symbol", values="f1_basis_bps")
        .reindex(index=hours, columns=symbols)
        .fillna(-999.0)
        .to_numpy(dtype=np.float64)
    )

    w_out = np.zeros((n_eval_hours, len(symbols)), dtype=np.float64)
    w_prev_np = np.zeros(len(symbols), dtype=np.float64)

    with torch.no_grad():
        for t in range(n_eval_hours):
            active_contract = (piv_ttm[t] >= 1.0) & (piv_raw_b[t] > -500.0)
            early_harvest = (piv_b24[t] <= 15.0) | (piv_raw_b[t] <= 5.0)

            if t % rebalance_every_hours == 0:
                x_step = torch.tensor(x_eval_h[t], dtype=torch.float32)
                act_mask = torch.tensor(
                    ((piv_ttm[t] >= 24.0) | ((w_prev_np > 1e-4) & (piv_ttm[t] >= 2.0))).astype(np.float32)
                )
                cont_mask = torch.tensor(
                    (
                        ((piv_b24[t] >= 65.0) & (piv_raw_b[t] >= 40.0))
                        | ((w_prev_np > 1e-4) & (~early_harvest))
                    ).astype(np.float32)
                )
                w_prev_t = torch.tensor(w_prev_np, dtype=torch.float32)
                w_prop = model.forward_step(x_step, act_mask, cont_mask, w_prev_t).numpy().astype(np.float64)

                # Deterministic L1 hysteresis outside the network (0.08)
                if float(np.sum(np.abs(w_prop - w_prev_np))) >= 0.08 or (
                    np.sum(w_prop) == 0.0 and np.sum(w_prev_np) > 0.0
                ):
                    w_curr = w_prop
                else:
                    w_curr = w_prev_np.copy()
                    w_curr[~active_contract | early_harvest] = 0.0
            else:
                w_curr = w_prev_np.copy()
                w_curr[~active_contract] = 0.0

            w_out[t] = w_curr
            w_prev_np = w_curr

    w_df = pd.DataFrame(w_out, index=hours, columns=symbols)
    sim_res = simulate_quarterly_carry_portfolio(df_eval, w_df, pair_cost_per_leg_bps=pair_cost_per_leg_bps)
    return w_df, sim_res


def run_phase_f_bounded_neural_evaluation(df: pd.DataFrame) -> Dict[str, Any]:
    """Run Phase F bounded neural pilot on H-1 across Validation 2024 and Adaptive Dev 2025."""
    df_22_23 = df[df["year"].isin([2022, 2023])].copy()
    df_24 = df[df["year"] == 2024].copy()
    df_22_24 = df[df["year"].isin([2022, 2023, 2024])].copy()
    df_25 = df[df["year"] == 2025].copy()

    # 1. Validation 2024 (Trained strictly on 2022-2023)
    w_nn_24, sim_nn_24 = train_and_evaluate_h1_neural_pilot(df_22_23, df_24, rebalance_every_hours=24)
    w_pass_nn_24 = build_h1_passive_carry_benchmark_weights(df_24, w_nn_24)
    sim_pass_nn_24 = simulate_quarterly_carry_portfolio(df_24, w_pass_nn_24, pair_cost_per_leg_bps=11.0)
    w_simp_24 = build_h1_simple_carry_weights(df_24)
    sim_simp_24 = simulate_quarterly_carry_portfolio(df_24, w_simp_24, pair_cost_per_leg_bps=11.0)

    sim_nn_24["net_excess_vs_matched_passive_carry_usd"] = round(sim_nn_24["net_pnl_usd"] - sim_pass_nn_24["net_pnl_usd"], 2)
    sim_nn_24["net_excess_vs_simple_carry_baseline_usd"] = round(sim_nn_24["net_pnl_usd"] - sim_simp_24["net_pnl_usd"], 2)

    # 2. Adaptive Dev 2025 (Trained strictly on 2022-2024)
    w_nn_25, sim_nn_25 = train_and_evaluate_h1_neural_pilot(df_22_24, df_25, rebalance_every_hours=24)
    w_pass_nn_25 = build_h1_passive_carry_benchmark_weights(df_25, w_nn_25)
    sim_pass_nn_25 = simulate_quarterly_carry_portfolio(df_25, w_pass_nn_25, pair_cost_per_leg_bps=11.0)
    w_simp_25 = build_h1_simple_carry_weights(df_25)
    sim_simp_25 = simulate_quarterly_carry_portfolio(df_25, w_simp_25, pair_cost_per_leg_bps=11.0)

    sim_nn_25["net_excess_vs_matched_passive_carry_usd"] = round(sim_nn_25["net_pnl_usd"] - sim_pass_nn_25["net_pnl_usd"], 2)
    sim_nn_25["net_excess_vs_simple_carry_baseline_usd"] = round(sim_nn_25["net_pnl_usd"] - sim_simp_25["net_pnl_usd"], 2)

    return {
        "validation_2024_train_2022_2023": {
            "neural_term_structure_policy": sim_nn_24,
            "matched_passive_carry_benchmark": sim_pass_nn_24,
            "simple_carry_baseline": sim_simp_24,
        },
        "adaptive_dev_2025_train_2022_2024": {
            "neural_term_structure_policy": sim_nn_25,
            "matched_passive_carry_benchmark": sim_pass_nn_25,
            "simple_carry_baseline": sim_simp_25,
        },
    }
